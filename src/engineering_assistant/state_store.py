"""Revision-safe persisted run state."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

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

    def run_dir(self, run_id: str) -> Path:
        if SAFE_ID.fullmatch(run_id) is None:
            raise ValidationFailure(f"unsafe run id {run_id!r}")
        return self.run_root / run_id

    def path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run-state.json"

    def create(self, state: RunState) -> Path:
        path = self.path(state.run_id)
        if path.exists():
            raise RevisionConflict(f"run {state.run_id} already exists")
        if state.revision != 0:
            raise RevisionConflict("new run must start at revision 0")
        self._write(path, state)
        return path

    def load(self, run_id: str) -> RunState:
        path = self.path(run_id)
        if not path.is_file():
            raise FileNotFoundError(f"run {run_id} does not exist")
        data = load_json(path)
        validate_instance(data, load_json(self.schema_root / "run-state.schema.json"), str(path))
        return run_state_from_dict(data)

    def save(self, state: RunState, *, expected_revision: int) -> Path:
        current = self.load(state.run_id)
        if current.revision != expected_revision:
            raise RevisionConflict(
                f"run {state.run_id} revision changed: expected {expected_revision}, found {current.revision}"
            )
        if state.revision <= expected_revision:
            raise RevisionConflict(
                f"saved revision must advance beyond {expected_revision}, got {state.revision}"
            )
        path = self.path(state.run_id)
        self._write(path, state)
        return path

    def _write(self, path: Path, state: RunState) -> None:
        payload = state.to_dict()
        validate_instance(payload, load_json(self.schema_root / "run-state.schema.json"), "run-state")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".run-state-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
