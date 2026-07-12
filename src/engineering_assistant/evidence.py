"""Observed evidence registry for a persisted run."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from .artifact_io import ArtifactConflict
from .model import EvidenceRef
from .state_store import SAFE_ID, StateStore
from .trust import TrustVerifier
from .validation import ValidationFailure, load_json, validate_instance


class EvidenceStore:
    def __init__(self, state_store: StateStore, trust_verifier: TrustVerifier | None = None) -> None:
        self.state_store = state_store
        self.trust_verifier = trust_verifier

    def save(self, run_id: str, evidence: EvidenceRef) -> EvidenceRef:
        if SAFE_ID.fullmatch(evidence.id) is None:
            raise ValidationFailure(f"unsafe evidence id {evidence.id!r}")
        evidence = self._with_observed_digest(evidence)
        if evidence.trust_level in {"observed", "verified"}:
            if self.trust_verifier is None or not self.trust_verifier.verify_evidence(run_id, evidence):
                raise ValidationFailure(
                    f"evidence {evidence.id}: observed trust requires a valid host attestation"
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
        minimum_trust_level: str | None = None,
    ) -> set[str]:
        directory = self.state_store.artifacts.path(run_id, "evidence")
        if not directory.is_dir():
            return set()
        if max_age_seconds is not None and max_age_seconds <= 0:
            raise ValidationFailure("max_age_seconds must be positive")
        trust_rank = {"claimed": 0, "observed": 1, "verified": 2}
        if minimum_trust_level is not None and minimum_trust_level not in trust_rank:
            raise ValidationFailure(f"unknown minimum trust level {minimum_trust_level}")
        result = set()
        now = datetime.now(timezone.utc)
        for path in directory.glob("*.json"):
            data = None
            if max_age_seconds is not None or minimum_trust_level is not None:
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
            if minimum_trust_level is not None and data is not None:
                if trust_rank.get(data.get("trust_level"), -1) < trust_rank[minimum_trust_level]:
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
        if evidence.trust_level in {"observed", "verified"} and (
            self.trust_verifier is None
            or not self.trust_verifier.verify_evidence(run_id, evidence)
        ):
            raise ValidationFailure(f"evidence {evidence_id}: host attestation is invalid")
        return evidence

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
