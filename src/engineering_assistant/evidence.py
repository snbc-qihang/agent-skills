"""Local provenance evidence registry for a persisted run."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from .artifact_io import ArtifactConflict
from .model import EvidenceRef
from .state_store import SAFE_ID, StateStore
from .validation import ValidationFailure, load_json, validate_instance


class EvidenceStore:
    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store

    def register(
        self,
        run_id: str,
        *,
        evidence_id: str,
        kind: str,
        uri: str,
        producer: str,
        scope: str,
        scope_tags: list[str] | None = None,
        contract_refs: list[str] | None = None,
        subject_digest: str | None = None,
    ) -> EvidenceRef:
        path = self._local_path(uri)
        if path is not None:
            if not path.is_file():
                raise ValidationFailure(
                    f"evidence {evidence_id}: local file does not exist: {uri}"
                )
            provenance = "runtime_observed"
        else:
            provenance = "agent_reported"
        return self.save(
            run_id,
            EvidenceRef(
                id=evidence_id,
                kind=kind,
                uri=uri,
                producer=producer,
                observed_at=datetime.now(timezone.utc).isoformat(),
                provenance=provenance,
                scope=scope,
                scope_tags=list(scope_tags or []),
                contract_refs=list(contract_refs or []),
                subject_digest=subject_digest,
            ),
        )

    def save(self, run_id: str, evidence: EvidenceRef) -> EvidenceRef:
        if SAFE_ID.fullmatch(evidence.id) is None:
            raise ValidationFailure(f"unsafe evidence id {evidence.id!r}")
        evidence = self._with_observed_digest(evidence)
        path = self._local_path(evidence.uri)
        expected_provenance = "runtime_observed" if path is not None else "agent_reported"
        if evidence.provenance != expected_provenance and evidence.provenance != "user_confirmed":
            raise ValidationFailure(
                f"evidence {evidence.id}: provenance must be assigned by the runtime"
            )
        validate_instance(
            evidence.to_dict(),
            load_json(self.state_store.schema_root / "evidence-ref.schema.json"),
            "evidence-ref",
        )
        try:
            self.state_store.artifacts.create_immutable_json(
                evidence.to_dict(), run_id, "evidence", f"{evidence.id}.json"
            )
        except ArtifactConflict as exc:
            raise ValidationFailure(
                f"evidence id {evidence.id} is immutable and already has different content"
            ) from exc
        return evidence

    def ids(
        self,
        run_id: str,
        *,
        max_age_seconds: int | None = None,
        minimum_provenance: str | None = None,
    ) -> set[str]:
        directory = self.state_store.artifacts.path(run_id, "evidence")
        if not directory.is_dir():
            return set()
        if max_age_seconds is not None and max_age_seconds <= 0:
            raise ValidationFailure("max_age_seconds must be positive")
        accepted = {
            "agent_reported": {"agent_reported", "runtime_observed", "user_confirmed"},
            "runtime_observed": {"runtime_observed", "user_confirmed"},
            "user_confirmed": {"user_confirmed"},
        }
        if minimum_provenance is not None and minimum_provenance not in accepted:
            raise ValidationFailure(f"unknown minimum provenance {minimum_provenance}")
        result = set()
        now = datetime.now(timezone.utc)
        for path in directory.glob("*.json"):
            data = None
            if max_age_seconds is not None or minimum_provenance is not None:
                data = self.state_store.artifacts.read_json(
                    run_id, "evidence", path.name
                )
            if max_age_seconds is not None and data is not None:
                try:
                    observed = datetime.fromisoformat(data["observed_at"].replace("Z", "+00:00"))
                    if observed.tzinfo is None:
                        observed = observed.replace(tzinfo=timezone.utc)
                except (KeyError, TypeError, ValueError):
                    continue
                if (now - observed).total_seconds() > max_age_seconds:
                    continue
            if minimum_provenance is not None and data is not None:
                if data.get("provenance") not in accepted[minimum_provenance]:
                    continue
                try:
                    self.get(run_id, path.stem)
                except (FileNotFoundError, ValidationFailure):
                    continue
            result.add(path.stem)
        return result

    def get(self, run_id: str, evidence_id: str) -> EvidenceRef:
        if SAFE_ID.fullmatch(evidence_id) is None:
            raise ValidationFailure(f"unsafe evidence id {evidence_id!r}")
        data = self.state_store.artifacts.read_json(
            run_id, "evidence", f"{evidence_id}.json"
        )
        evidence = EvidenceRef(**data)
        validate_instance(
            evidence.to_dict(),
            load_json(self.state_store.schema_root / "evidence-ref.schema.json"),
            "evidence-ref",
        )
        evidence = self._with_observed_digest(evidence)
        return evidence

    def _with_observed_digest(self, evidence: EvidenceRef) -> EvidenceRef:
        path = self._local_path(evidence.uri)
        if path is None:
            return evidence
        if not path.is_file():
            raise ValidationFailure(
                f"evidence {evidence.id}: local file does not exist: {evidence.uri}"
            )
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if evidence.digest is not None and evidence.digest != digest:
            raise ValidationFailure(f"evidence {evidence.id}: digest does not match {path}")
        return replace(evidence, digest=digest)

    def _local_path(self, uri: str) -> Path | None:
        parsed = urlparse(uri)
        if parsed.scheme == "file":
            candidate = Path(unquote(parsed.path)).resolve()
            return self._bounded_local_path(candidate)
        if parsed.scheme:
            return None
        candidate = Path(uri)
        resolved = (
            candidate
            if candidate.is_absolute()
            else self.state_store.project_root / candidate
        ).resolve()
        return self._bounded_local_path(resolved)

    def _bounded_local_path(self, path: Path) -> Path:
        try:
            path.relative_to(self.state_store.project_root)
        except ValueError as exc:
            raise ValidationFailure(
                f"local evidence must remain inside project_root: {path}"
            ) from exc
        return path
