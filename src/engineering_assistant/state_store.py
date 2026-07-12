"""Revision-safe persisted run state."""

from __future__ import annotations

import re
from pathlib import Path

from .artifact_io import ArtifactConflict, ArtifactIO
from .codec import run_state_from_dict
from .model import RunState
from .validation import ValidationFailure, load_json, validate_instance


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RevisionConflict(RuntimeError):
    pass


class StateStore:
    def __init__(self, project_root: Path | str, schema_root: Path | str, run_root: str = ".run-artifacts/engineering-assistant") -> None:
        self.project_root = Path(project_root).resolve()
        self.schema_root = Path(schema_root).resolve()
        self.run_root = self.project_root / run_root
        self.artifacts = ArtifactIO(self.project_root, self.run_root)

    def run_dir(self, run_id: str) -> Path:
        if SAFE_ID.fullmatch(run_id) is None:
            raise ValidationFailure(f"unsafe run id {run_id!r}")
        return self.artifacts.path(run_id)

    def path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run-state.json"

    def create(self, state: RunState) -> Path:
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
        return path

    def load(self, run_id: str) -> RunState:
        path = self.path(run_id)
        if not path.is_file():
            raise FileNotFoundError(f"run {run_id} does not exist")
        data = self.artifacts.read_json(run_id, "run-state.json")
        validate_instance(data, load_json(self.schema_root / "run-state.schema.json"), str(path))
        return run_state_from_dict(data)

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
