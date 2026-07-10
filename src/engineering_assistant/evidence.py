"""Observed evidence registry for a persisted run."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from .model import EvidenceRef
from .state_store import SAFE_ID, StateStore
from .validation import ValidationFailure, load_json, validate_instance


class EvidenceStore:
    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store

    def save(self, run_id: str, evidence: EvidenceRef) -> EvidenceRef:
        if SAFE_ID.fullmatch(evidence.id) is None:
            raise ValidationFailure(f"unsafe evidence id {evidence.id!r}")
        evidence = self._with_observed_digest(evidence)
        validate_instance(
            evidence.to_dict(),
            load_json(self.state_store.schema_root / "evidence-ref.schema.json"),
            "evidence-ref",
        )
        path = self.state_store.run_dir(run_id) / "evidence" / f"{evidence.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = load_json(path)
            if existing != evidence.to_dict():
                raise ValidationFailure(f"evidence id {evidence.id} is immutable and already has different content")
            return evidence
        self._atomic_json(path, evidence.to_dict())
        return evidence

    def ids(self, run_id: str, *, max_age_seconds: int | None = None) -> set[str]:
        directory = self.state_store.run_dir(run_id) / "evidence"
        if not directory.is_dir():
            return set()
        if max_age_seconds is not None and max_age_seconds <= 0:
            raise ValidationFailure("max_age_seconds must be positive")
        result = set()
        now = datetime.now(timezone.utc)
        for path in directory.glob("*.json"):
            if max_age_seconds is not None:
                data = load_json(path)
                try:
                    observed = datetime.fromisoformat(data["observed_at"].replace("Z", "+00:00"))
                    if observed.tzinfo is None:
                        observed = observed.replace(tzinfo=timezone.utc)
                except (KeyError, TypeError, ValueError):
                    continue
                if (now - observed).total_seconds() > max_age_seconds:
                    continue
            result.add(path.stem)
        return result

    def _with_observed_digest(self, evidence: EvidenceRef) -> EvidenceRef:
        path = self._local_path(evidence.uri)
        if path is None or not path.is_file():
            return evidence
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if evidence.digest is not None and evidence.digest != digest:
            raise ValidationFailure(f"evidence {evidence.id}: digest does not match {path}")
        return replace(evidence, digest=digest)

    def _local_path(self, uri: str) -> Path | None:
        parsed = urlparse(uri)
        if parsed.scheme == "file":
            return Path(unquote(parsed.path)).resolve()
        if parsed.scheme:
            return None
        candidate = Path(uri)
        return (candidate if candidate.is_absolute() else self.state_store.project_root / candidate).resolve()

    @staticmethod
    def _atomic_json(path: Path, payload: dict) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".evidence-", suffix=".json", dir=path.parent)
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
