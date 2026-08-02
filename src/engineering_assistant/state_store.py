"""Revision-safe persisted run state."""

from __future__ import annotations

import re
import os
from datetime import datetime, timezone
from pathlib import Path

from .artifact_io import ArtifactConflict, ArtifactIO
from .codec import approval_record_from_dict, run_state_from_dict
from .model import ApprovalRecord, RunState
from .validation import ValidationFailure, load_json, validate_instance


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RevisionConflict(RuntimeError):
    pass


class StateStore:
    def __init__(
        self,
        project_root: Path | str,
        schema_root: Path | str,
        run_root: str = ".run-artifacts/engineering-assistant",
        *,
        allow_author_repository: bool = False,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.schema_root = Path(schema_root).resolve()
        self.run_root = self.project_root / run_root
        self.artifacts = ArtifactIO(self.project_root, self.run_root)
        author_mode = allow_author_repository or os.environ.get(
            "ENGINEERING_ASSISTANT_AUTHOR_MODE"
        ) == "1"
        self.artifacts.assert_runtime_target(
            self.schema_root,
            allow_author_repository=author_mode,
        )

    def run_dir(self, run_id: str) -> Path:
        if SAFE_ID.fullmatch(run_id) is None:
            raise ValidationFailure(f"unsafe run id {run_id!r}")
        return self.artifacts.path(run_id)

    def path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run-state.json"

    def create(self, state: RunState, *, manifest: dict | None = None) -> Path:
        path = self.path(state.run_id)
        if state.revision != 0:
            raise RevisionConflict("new run must start at revision 0")
        payload = state.to_dict()
        validate_instance(payload, load_json(self.schema_root / "run-state.schema.json"), "run-state")
        try:
            _, created = self.artifacts.create_immutable_json_with_status(
                payload, state.run_id, "run-state.json"
            )
            if not created:
                raise RevisionConflict(f"run {state.run_id} already exists")
        except ArtifactConflict as exc:
            raise RevisionConflict(f"run {state.run_id} already exists") from exc
        if manifest is not None:
            validate_instance(
                manifest,
                load_json(self.schema_root / "run-manifest.schema.json"),
                "run-manifest",
            )
            self.artifacts.create_immutable_json(
                manifest, state.run_id, "run-manifest.json"
            )
        return path

    def load(self, run_id: str) -> RunState:
        path = self.path(run_id)
        if not path.is_file():
            raise FileNotFoundError(f"run {run_id} does not exist")
        data = self.artifacts.read_json(run_id, "run-state.json")
        if data.get("schema_version") != "2":
            raise ValidationFailure(
                "旧 RC 协议不受支持：RunState 缺少 schema_version=2；旧文件已保留且不会迁移"
            )
        validate_instance(data, load_json(self.schema_root / "run-state.schema.json"), str(path))
        return self._recover_step(run_state_from_dict(data))

    def save(self, state: RunState, *, expected_revision: int) -> Path:
        if state.revision <= expected_revision:
            raise RevisionConflict(
                f"saved revision must advance beyond {expected_revision}, got {state.revision}"
            )
        path = self.path(state.run_id)
        payload = state.to_dict()
        validate_instance(payload, load_json(self.schema_root / "run-state.schema.json"), "run-state")
        try:
            self.artifacts.replace_json_cas(
                payload,
                state.run_id,
                "run-state.json",
                expected_revision=expected_revision,
            )
        except ArtifactConflict as exc:
            raise RevisionConflict(str(exc)) from exc
        return path

    def record_step(
        self,
        *,
        result: dict,
        gate: dict,
        node_output: dict | None,
        input_revision: int,
        output_revision: int,
        state_after: dict,
    ) -> Path:
        run_id = str(result["run_id"])
        node_id = str(result["node_id"])
        steps = self.artifacts.path(run_id, "steps")
        sequence = 1
        if steps.is_dir():
            sequence += sum(1 for path in steps.iterdir() if path.suffix == ".json")
        payload = {
            "schema_version": "2",
            "sequence": sequence,
            "run_id": run_id,
            "node_id": node_id,
            "input_revision": input_revision,
            "output_revision": output_revision,
            "result": result,
            "gate": gate,
            "node_output": node_output,
            "state_after": state_after,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        validate_instance(
            payload,
            load_json(self.schema_root / "step-record.schema.json"),
            "step-record",
        )
        return self.artifacts.create_immutable_json(
            payload,
            run_id,
            "steps",
            f"{sequence:04d}-{node_id}.json",
        )

    def save_with_step(
        self,
        state: RunState,
        *,
        expected_revision: int,
        result: dict,
        gate: dict,
        node_output: dict | None,
    ) -> Path:
        """Write a recoverable step record before advancing the CAS state."""

        if state.revision <= expected_revision:
            raise RevisionConflict(
                f"saved revision must advance beyond {expected_revision}, got {state.revision}"
            )
        validate_instance(
            state.to_dict(),
            load_json(self.schema_root / "run-state.schema.json"),
            "run-state",
        )
        step_path = self.record_step(
            result=result,
            gate=gate,
            node_output=node_output,
            input_revision=expected_revision,
            output_revision=state.revision,
            state_after=state.to_dict(),
        )
        try:
            self.save(state, expected_revision=expected_revision)
        except RevisionConflict:
            recovered = self.load(state.run_id)
            if recovered.to_dict() != state.to_dict():
                raise
        return step_path

    def _recover_step(self, state: RunState) -> RunState:
        directory = self.artifacts.path(state.run_id, "steps")
        if not directory.is_dir():
            return state
        schema = load_json(self.schema_root / "step-record.schema.json")
        state_schema = load_json(self.schema_root / "run-state.schema.json")
        for path in sorted(directory.glob("*.json")):
            payload = self.artifacts.read_json(state.run_id, "steps", path.name)
            validate_instance(payload, schema, str(path))
            if payload["input_revision"] != state.revision:
                continue
            state_after = payload["state_after"]
            if (
                state_after.get("run_id") != state.run_id
                or state_after.get("revision") != payload["output_revision"]
            ):
                raise ValidationFailure("step recovery state does not match its revisions")
            validate_instance(state_after, state_schema, "step-recovery-state")
            try:
                self.artifacts.replace_json_cas(
                    state_after,
                    state.run_id,
                    "run-state.json",
                    expected_revision=state.revision,
                )
            except ArtifactConflict as exc:
                raise RevisionConflict(str(exc)) from exc
            state = run_state_from_dict(state_after)
        return state

    def list_states(
        self,
        *,
        include_terminal: bool = False,
        limit: int = 50,
        after_run_id: str | None = None,
    ) -> tuple[list[RunState], str | None]:
        if not 1 <= limit <= 100:
            raise ValidationFailure("run page limit must be between 1 and 100")
        if not self.run_root.is_dir():
            return [], None
        run_ids = sorted(
            path.name
            for path in self.run_root.iterdir()
            if path.is_dir() and SAFE_ID.fullmatch(path.name)
        )
        if after_run_id is not None:
            run_ids = [run_id for run_id in run_ids if run_id > after_run_id]
        states: list[RunState] = []
        for run_id in run_ids:
            try:
                state = self.load(run_id)
            except (FileNotFoundError, ValidationFailure):
                continue
            if include_terminal or state.status not in {"blocked", "cancelled", "completed"}:
                states.append(state)
            if len(states) > limit:
                break
        next_cursor = states[limit - 1].run_id if len(states) > limit else None
        return states[:limit], next_cursor


class ApprovalStore:
    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store
        self.schema = load_json(state_store.schema_root / "approval-record.schema.json")

    def save(self, record: ApprovalRecord) -> Path:
        if SAFE_ID.fullmatch(record.record_id) is None:
            raise ValidationFailure(f"unsafe approval record id {record.record_id!r}")
        validate_instance(record.to_dict(), self.schema, "approval-record")
        try:
            return self.state_store.artifacts.create_immutable_json(
                record.to_dict(),
                record.run_id,
                "approvals",
                f"{record.record_id}.json",
            )
        except ArtifactConflict as exc:
            raise ValidationFailure(
                f"approval record {record.record_id} is immutable"
            ) from exc

    def list(self, run_id: str) -> list[ApprovalRecord]:
        directory = self.state_store.artifacts.path(run_id, "approvals")
        if not directory.is_dir():
            return []
        records = []
        for path in sorted(directory.glob("*.json")):
            payload = self.state_store.artifacts.read_json(
                run_id, "approvals", path.name
            )
            validate_instance(payload, self.schema, str(path))
            records.append(approval_record_from_dict(payload))
        return records
