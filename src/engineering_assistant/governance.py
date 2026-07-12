"""Evidence-backed quality gates and user-governed investigation queues."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .artifact_io import ArtifactConflict
from .codec import investigation_record_from_dict, quality_snapshot_from_dict
from .evidence import EvidenceStore
from .model import (
    InvestigationDecisionGrant,
    InvestigationRecord,
    InvestigationRequest,
    InvestigationTransition,
    QualitySnapshot,
)
from .state_store import SAFE_ID, StateStore
from .trust import TrustVerifier, parse_time
from .validation import ValidationFailure, load_json, validate_instance


QUALITY_DIMENSIONS = frozenset(
    {"correctness", "complexity", "redundancy", "performance", "architecture", "test_quality"}
)
QUALITY_EVIDENCE_KINDS = {
    "correctness": {"test", "ci"},
    "test_quality": {"test", "ci", "review"},
    "complexity": {"source", "review"},
    "redundancy": {"source", "review"},
    "performance": {"test", "ci"},
    "architecture": {"source", "review"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str, label: str) -> None:
    if SAFE_ID.fullmatch(value) is None:
        raise ValidationFailure(f"unsafe {label} {value!r}")


@dataclass(frozen=True)
class QualityAssessment:
    decision: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"decision": self.decision, "reasons": list(self.reasons)}


class QualityGate:
    """A strict gate: warnings and unevaluated dimensions require repair."""

    @staticmethod
    def evaluate(snapshot: QualitySnapshot) -> QualityAssessment:
        reasons: list[str] = []
        ids = [item.id for item in snapshot.dimensions]
        if len(ids) != len(QUALITY_DIMENSIONS) or set(ids) != QUALITY_DIMENSIONS:
            reasons.append("all quality dimensions must appear exactly once")
        reasons.extend(
            f"{item.id} is {item.status}"
            for item in snapshot.dimensions
            if item.status != "pass"
        )
        reasons.extend(
            f"finding {item.id} is {item.severity}"
            for item in snapshot.findings
            if item.severity in {"medium", "high", "blocker"}
        )
        if snapshot.required_repairs:
            reasons.append("required repairs remain open")
        return QualityAssessment("repair" if reasons else "pass", tuple(reasons))


class QualityStore:
    MAX_AGE_SECONDS = 3600
    MAX_FUTURE_SKEW_SECONDS = 300

    def __init__(
        self, state_store: StateStore, evidence_store: EvidenceStore
    ) -> None:
        self.state_store = state_store
        self.evidence_store = evidence_store
        self.schema = load_json(state_store.schema_root / "quality-snapshot.schema.json")

    def save(
        self,
        snapshot: QualitySnapshot,
        *,
        current_state_revision: int | None = None,
    ) -> QualitySnapshot:
        _safe_id(snapshot.id, "quality snapshot id")
        _safe_id(snapshot.run_id, "run id")
        validate_instance(snapshot.to_dict(), self.schema, "quality-snapshot")
        if current_state_revision is not None and snapshot.state_revision != current_state_revision:
            raise ValidationFailure("quality snapshot targets a stale run revision")
        self._validate_time(snapshot)
        snapshot = replace(snapshot, observed_at=_now())
        assessment = QualityGate.evaluate(snapshot)
        if "all quality dimensions must appear exactly once" in assessment.reasons:
            raise ValidationFailure("quality dimensions must appear exactly once")
        referenced = set(snapshot.evidence_refs)
        referenced.update(evidence for item in snapshot.dimensions for evidence in item.evidence_ids)
        referenced.update(evidence for item in snapshot.findings for evidence in item.evidence_ids)
        if not snapshot.evidence_refs:
            raise ValidationFailure("quality snapshot must reference observed evidence")
        if snapshot.candidate_evidence_id not in snapshot.evidence_refs:
            raise ValidationFailure("candidate evidence must be included in quality evidence refs")
        self._validate_evidence_bindings(snapshot, referenced)
        try:
            self.state_store.artifacts.create_immutable_json(
                snapshot.to_dict(), snapshot.run_id, "quality", f"{snapshot.id}.json"
            )
        except ArtifactConflict as exc:
            existing = quality_snapshot_from_dict(
                self.state_store.artifacts.read_json(
                    snapshot.run_id, "quality", f"{snapshot.id}.json"
                )
            )
            if replace(snapshot, observed_at=existing.observed_at) == existing:
                return existing
            raise ValidationFailure(f"quality snapshot id {snapshot.id} is immutable") from exc
        return snapshot

    def latest(self, run_id: str, node_id: str) -> QualitySnapshot | None:
        directory = self.state_store.artifacts.path(run_id, "quality")
        if not directory.is_dir():
            return None
        snapshots = [
            quality_snapshot_from_dict(
                self.state_store.artifacts.read_json(run_id, "quality", path.name)
            )
            for path in directory.glob("*.json")
        ]
        matching = [item for item in snapshots if item.run_id == run_id and item.node_id == node_id]
        return max(matching, key=lambda item: parse_time(item.observed_at), default=None)

    def latest_valid(
        self,
        run_id: str,
        node_id: str,
        *,
        current_state_revision: int,
    ) -> QualitySnapshot | None:
        snapshot = self.latest(run_id, node_id)
        if snapshot is None or snapshot.state_revision != current_state_revision:
            return None
        try:
            self._validate_time(snapshot)
            referenced = set(snapshot.evidence_refs)
            referenced.update(
                evidence for item in snapshot.dimensions for evidence in item.evidence_ids
            )
            referenced.update(
                evidence for item in snapshot.findings for evidence in item.evidence_ids
            )
            self._validate_evidence_bindings(snapshot, referenced)
        except (FileNotFoundError, ValidationFailure):
            return None
        return snapshot

    def _validate_evidence_bindings(
        self, snapshot: QualitySnapshot, referenced: set[str]
    ) -> None:
        evidence_by_id = {}
        for evidence_id in referenced | {snapshot.candidate_evidence_id}:
            try:
                evidence_by_id[evidence_id] = self.evidence_store.get(
                    snapshot.run_id, evidence_id
                )
            except FileNotFoundError as exc:
                raise ValidationFailure(
                    f"quality snapshot references unregistered evidence: {evidence_id}"
                ) from exc
        candidate = evidence_by_id[snapshot.candidate_evidence_id]
        if candidate.kind != "source" or candidate.trust_level not in {
            "observed",
            "verified",
        }:
            raise ValidationFailure("candidate evidence must be an observed source artifact")
        if candidate.digest != snapshot.candidate_ref:
            raise ValidationFailure(
                "quality snapshot candidate digest does not match its evidence"
            )
        for evidence_id in referenced:
            item = evidence_by_id[evidence_id]
            if item.trust_level not in {"observed", "verified"}:
                raise ValidationFailure(
                    f"quality evidence {evidence_id} must be observed or verified"
                )
            if item.subject_digest != snapshot.candidate_ref:
                raise ValidationFailure(
                    f"quality evidence {evidence_id} is not bound to the candidate"
                )
            age = (datetime.now(timezone.utc) - parse_time(item.observed_at)).total_seconds()
            if age < -self.MAX_FUTURE_SKEW_SECONDS:
                raise ValidationFailure(
                    f"quality evidence {evidence_id} is too far in the future"
                )
            if age > self.MAX_AGE_SECONDS:
                raise ValidationFailure(f"quality evidence {evidence_id} is stale")
        for dimension in snapshot.dimensions:
            evidence = [evidence_by_id[evidence_id] for evidence_id in dimension.evidence_ids]
            if not any(
                item.trust_level in {"observed", "verified"}
                and item.kind in QUALITY_EVIDENCE_KINDS[dimension.id]
                and item.subject_digest == snapshot.candidate_ref
                for item in evidence
            ):
                raise ValidationFailure(
                    f"quality dimension {dimension.id} lacks candidate-bound attested evidence"
                )

    def _validate_time(self, snapshot: QualitySnapshot) -> None:
        observed = parse_time(snapshot.observed_at)
        now = datetime.now(timezone.utc)
        age = (now - observed).total_seconds()
        if age < -self.MAX_FUTURE_SKEW_SECONDS:
            raise ValidationFailure("quality snapshot observed_at is too far in the future")
        if age > self.MAX_AGE_SECONDS:
            raise ValidationFailure("quality snapshot is stale")

class InvestigationStore:
    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store
        self.request_schema = load_json(state_store.schema_root / "investigation-request.schema.json")
        self.record_schema = load_json(state_store.schema_root / "investigation-record.schema.json")

    def propose(
        self,
        request: InvestigationRequest,
        *,
        investigation_policy: dict | None = None,
    ) -> InvestigationRecord:
        _safe_id(request.id, "investigation id")
        _safe_id(request.run_id, "run id")
        policy = investigation_policy or {"default_mode": request.mode}
        selected_mode = policy.get("default_mode", "suggest_then_run")
        if selected_mode not in {"auto_readonly", "suggest_then_run", "guided", "disabled"}:
            raise ValidationFailure(f"unsupported investigation mode {selected_mode}")
        request = replace(request, mode=selected_mode)
        validate_instance(request.to_dict(), self.request_schema, "investigation-request")
        if request.status != "proposed":
            raise ValidationFailure("new investigation must have proposed status")
        now = _now()
        record = InvestigationRecord(
            request=request,
            decision_ref=None,
            evidence_refs=[],
            remaining_source_scope=list(request.source_scope),
            current_source_scope=[],
            transition_history=[InvestigationTransition("", "proposed", "propose", None, now)],
            updated_at=now,
            revision=0,
        )
        path = self._path(request.run_id, request.id)
        if path.exists():
            existing = self.load(request.run_id, request.id)
            comparable = replace(existing.request, status="proposed", mode=request.mode)
            if comparable != request:
                raise ValidationFailure(f"investigation id {request.id} already exists")
            return existing
        self._create(record)
        if selected_mode == "disabled":
            return self._transition(
                record, "declined", "decline", "profile:disabled", mode="disabled"
            )
        if selected_mode == "auto_readonly":
            auto = policy.get("auto_readonly", {})
            cost_rank = {"low": 0, "medium": 1, "high": 2}
            allowed = set(auto.get("allowed_source_scope", []))
            within_scope = set(request.source_scope).issubset(allowed)
            within_cost = cost_rank[request.estimated_cost] <= cost_rank.get(
                auto.get("max_cost", "low"), 0
            )
            if auto.get("enabled") and within_scope and within_cost:
                approved = self._transition(
                    record,
                    "approved",
                    "approve",
                    "profile:" + str(auto.get("authorization_id", "auto-readonly")),
                    mode="auto_readonly",
                )
                return self._transition(
                    approved,
                    "running",
                    "start",
                    approved.decision_ref,
                )
            return self._transition(
                record,
                "proposed",
                "propose",
                "profile:auto-readonly-out-of-bounds",
                mode="suggest_then_run",
            )
        return record

    def apply_grant(
        self,
        grant: InvestigationDecisionGrant,
        *,
        verifier: TrustVerifier | None,
        current_run_revision: int,
        expected_broker_id: str | None = None,
        expected_audience: str = "engineering-assistant",
    ) -> InvestigationRecord:
        validate_instance(
            grant.to_dict(),
            load_json(self.state_store.schema_root / "investigation-decision-grant.schema.json"),
            "investigation-decision-grant",
        )
        if verifier is None or not verifier.verify_decision(grant):
            raise ValidationFailure("investigation decision requires a valid external broker grant")
        if expected_broker_id is not None and grant.broker_id != expected_broker_id:
            raise ValidationFailure("investigation decision grant has the wrong broker")
        if grant.audience != expected_audience:
            raise ValidationFailure("investigation decision grant has the wrong audience")
        now = datetime.now(timezone.utc)
        if parse_time(grant.issued_at) > now or parse_time(grant.expires_at) <= now:
            raise ValidationFailure("investigation decision grant is not currently valid")
        if grant.run_revision != current_run_revision:
            raise ValidationFailure("investigation decision grant targets a stale run revision")
        record = self.load(grant.run_id, grant.investigation_id)
        if record.request.status != "proposed":
            raise ValidationFailure("only proposed investigations can be decided")
        approved_scope = list(record.request.source_scope)
        if grant.selected_mode == "guided":
            selected = set(grant.allowed_source_scope)
            if len(selected) != 1 or not selected.issubset(record.remaining_source_scope):
                raise ValidationFailure("guided investigation grants must approve exactly one requested source")
            approved_scope = list(grant.allowed_source_scope)
        elif not set(record.request.source_scope).issubset(grant.allowed_source_scope):
            raise ValidationFailure("investigation exceeds the source scope approved by the broker")
        cost_rank = {"low": 0, "medium": 1, "high": 2}
        if cost_rank[record.request.estimated_cost] > cost_rank[grant.max_cost]:
            raise ValidationFailure("investigation exceeds the cost approved by the broker")
        if grant.decision == "approve" and grant.selected_mode == "disabled":
            raise ValidationFailure("disabled investigation mode cannot be approved")
        status = "approved" if grant.decision == "approve" else "declined"
        return self._transition(
            record,
            status,
            grant.decision,
            grant.grant_id,
            mode=grant.selected_mode,
            current_source_scope=approved_scope,
            remaining_source_scope=[
                item for item in record.remaining_source_scope if item not in approved_scope
            ],
        )

    def start(self, run_id: str, investigation_id: str) -> InvestigationRecord:
        record = self.load(run_id, investigation_id)
        if record.request.status != "approved":
            raise ValidationFailure("investigation must be approved before it can start")
        return self._transition(record, "running", "start", record.decision_ref)

    def finish(
        self,
        run_id: str,
        investigation_id: str,
        *,
        outcome: str,
        evidence_refs: list[str],
        available_evidence: set[str] | None = None,
    ) -> InvestigationRecord:
        if outcome not in {"completed", "blocked"}:
            raise ValidationFailure("outcome must be completed or blocked")
        record = self.load(run_id, investigation_id)
        if record.request.status != "running":
            raise ValidationFailure("only running investigations can finish")
        if not evidence_refs:
            raise ValidationFailure("investigation finish requires evidence")
        unknown = sorted(set(evidence_refs) - (available_evidence or set()))
        if unknown:
            raise ValidationFailure(f"investigation references unregistered evidence: {', '.join(unknown)}")
        action = "complete" if outcome == "completed" else "block"
        if (
            outcome == "completed"
            and record.request.mode == "guided"
            and record.remaining_source_scope
        ):
            return self._transition(
                record,
                "proposed",
                "advance_step",
                record.decision_ref,
                evidence_refs=evidence_refs,
                current_source_scope=[],
            )
        return self._transition(record, outcome, action, record.decision_ref, evidence_refs=evidence_refs)

    def load(self, run_id: str, investigation_id: str) -> InvestigationRecord:
        path = self._path(run_id, investigation_id)
        if not path.is_file():
            raise FileNotFoundError(f"investigation {investigation_id} does not exist")
        payload = self.state_store.artifacts.read_json(
            run_id, "investigations", f"{investigation_id}.json"
        )
        validate_instance(payload, self.record_schema, str(path))
        validate_instance(payload["request"], self.request_schema, str(path) + ":request")
        return investigation_record_from_dict(payload)

    def list(self, run_id: str) -> list[InvestigationRecord]:
        directory = self.state_store.artifacts.path(run_id, "investigations")
        if not directory.is_dir():
            return []
        return [self.load(run_id, path.stem) for path in sorted(directory.glob("*.json"))]

    def _transition(
        self,
        record: InvestigationRecord,
        status: str,
        action: str,
        decision_ref: str | None,
        *,
        mode: str | None = None,
        remaining_source_scope: list[str] | None = None,
        current_source_scope: list[str] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> InvestigationRecord:
        now = _now()
        request = replace(
            record.request,
            status=status,
            mode=mode if mode is not None else record.request.mode,
        )
        updated = replace(
            record,
            request=request,
            decision_ref=decision_ref,
            evidence_refs=list(dict.fromkeys(evidence_refs or record.evidence_refs)),
            remaining_source_scope=(
                remaining_source_scope
                if remaining_source_scope is not None
                else record.remaining_source_scope
            ),
            current_source_scope=(
                current_source_scope
                if current_source_scope is not None
                else record.current_source_scope
            ),
            transition_history=record.transition_history
            + [InvestigationTransition(record.request.status, status, action, decision_ref, now)],
            updated_at=now,
            revision=record.revision + 1,
        )
        self._replace(updated, expected_revision=record.revision)
        return updated

    def _path(self, run_id: str, investigation_id: str) -> Path:
        _safe_id(run_id, "run id")
        _safe_id(investigation_id, "investigation id")
        return self.state_store.artifacts.path(
            run_id, "investigations", f"{investigation_id}.json"
        )

    def _validate(self, record: InvestigationRecord) -> None:
        validate_instance(record.request.to_dict(), self.request_schema, "investigation-request")
        validate_instance(record.to_dict(), self.record_schema, "investigation-record")

    def _create(self, record: InvestigationRecord) -> None:
        self._validate(record)
        try:
            self.state_store.artifacts.create_immutable_json(
                record.to_dict(),
                record.request.run_id,
                "investigations",
                f"{record.request.id}.json",
            )
        except ArtifactConflict as exc:
            raise ValidationFailure(f"investigation id {record.request.id} already exists") from exc

    def _replace(self, record: InvestigationRecord, *, expected_revision: int) -> None:
        self._validate(record)
        try:
            self.state_store.artifacts.replace_json_cas(
                record.to_dict(),
                record.request.run_id,
                "investigations",
                f"{record.request.id}.json",
                expected_revision=expected_revision,
            )
        except ArtifactConflict as exc:
            raise ValidationFailure(f"investigation revision conflict: {exc}") from exc
