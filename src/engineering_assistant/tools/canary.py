"""Prepare reproducible, locally audited canary evidence bundles."""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Mapping

from ..runtime.artifact_io import (
    ArtifactConflict,
    ArtifactIO,
)
from . import canary_limits
from .canary_protocol import audit_canary_protocol, canonical_digest
from ..runtime.validation import ValidationFailure, load_json, validate_instance


MEASUREMENT_FIELDS = (
    "input_tokens",
    "noncached_input_tokens",
    "output_tokens",
    "wall_time_milliseconds",
    "cost_usd_micros",
    "quality_score",
    "document_noise_units",
    "safety_violations",
    "blind_blocker_count",
    "blind_major_count",
    "applicable_matrix_cells",
    "closed_matrix_cells",
    "production_contract_failures",
)
DELEGATION_MEASUREMENT_FIELDS = (
    "human_intervention_count",
    "human_rework_minutes",
    "product_gate_failures",
    "quality_blocker_count",
    "quality_major_count",
)
ALL_MEASUREMENT_FIELDS = (*MEASUREMENT_FIELDS, *DELEGATION_MEASUREMENT_FIELDS)
MEASUREMENT_EVIDENCE_KINDS = {
    "input_tokens": "usage",
    "noncached_input_tokens": "usage",
    "output_tokens": "usage",
    "wall_time_milliseconds": "timing",
    "cost_usd_micros": "billing",
    "quality_score": "quality_evaluation",
    "document_noise_units": "document_noise",
    "safety_violations": "safety_audit",
    "blind_blocker_count": "safety_audit",
    "blind_major_count": "safety_audit",
    "applicable_matrix_cells": "safety_audit",
    "closed_matrix_cells": "safety_audit",
    "production_contract_failures": "safety_audit",
    "human_intervention_count": "quality_evaluation",
    "human_rework_minutes": "quality_evaluation",
    "product_gate_failures": "safety_audit",
    "quality_blocker_count": "safety_audit",
    "quality_major_count": "safety_audit",
}
PROMOTION_BINDING_FIELDS = (
    "promotion_attempt_set_digest",
    "promotion_attempt_bindings",
    "quality_attempt_binding",
    "blind_review_binding",
)
MAX_STRUCTURED_CANARY_ARTIFACT_BYTES = 2 * 1024 * 1024

DELEGATION_ABLATION_ARMS = frozenset(
    {
        "minimum_matrix_inline",
        "minimum_matrix_risk_delegation",
        "full_local_control",
    }
)


def _parse_time(value: str):
    from datetime import datetime, timezone

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _observation_claims(observation: Mapping[str, Any]) -> dict[str, Any]:
    return {"canary_observation": {"digest": canonical_digest(observation)}}


def validate_canary_measurements(payload: Mapping[str, Any]) -> None:
    """Validate cross-field usage/timing invariants when measurements are present."""

    for field in ALL_MEASUREMENT_FIELDS:
        value = payload.get(field)
        if isinstance(value, float) and not math.isfinite(value):
            raise ValidationFailure(f"canary measurement {field} must be finite")
    input_tokens = payload.get("input_tokens")
    noncached_input_tokens = payload.get("noncached_input_tokens")
    if input_tokens is not None and noncached_input_tokens is not None:
        if noncached_input_tokens > input_tokens:
            raise ValidationFailure(
                "canary noncached input tokens cannot exceed total input tokens"
            )
    wall_time = payload.get("wall_time_milliseconds")
    if wall_time is not None and wall_time <= 0:
        raise ValidationFailure("canary wall time must be positive")
    applicable_cells = payload.get("applicable_matrix_cells")
    closed_cells = payload.get("closed_matrix_cells")
    if (
        applicable_cells is not None
        and closed_cells is not None
        and closed_cells > applicable_cells
    ):
        raise ValidationFailure(
            "canary closed matrix cells cannot exceed applicable matrix cells"
        )
    experiment_kind = payload.get("experiment_kind")
    arm_id = payload.get("arm_id")
    variant = payload.get("variant")
    bindings = payload.get("ablation_run_bindings")
    if experiment_kind == "paired_canary":
        if arm_id != variant or bindings is not None:
            raise ValidationFailure("paired canary arm must match its variant")
    elif experiment_kind == "delegation_ablation":
        expected_arm = (
            "full_local_control"
            if variant == "baseline"
            else "minimum_matrix_risk_delegation"
        )
        if arm_id != expected_arm or not isinstance(bindings, list):
            raise ValidationFailure("delegation ablation observation binding is incomplete")
        required_fields = {
            "run_id", "workload_id", "repeat_index", "arm_id",
            "run_record_digest",
        }
        if (
            len(bindings) != 3
            or any(not isinstance(item, Mapping) for item in bindings)
            or any(set(item) != required_fields for item in bindings)
            or {item["arm_id"] for item in bindings} != DELEGATION_ABLATION_ARMS
            or len({item["run_id"] for item in bindings}) != 3
            or len({item["run_record_digest"] for item in bindings}) != 3
            or len({item["workload_id"] for item in bindings}) != 1
            or len({item["repeat_index"] for item in bindings}) != 1
        ):
            raise ValidationFailure("delegation ablation must bind all three run records")


def _json_artifact(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) > MAX_STRUCTURED_CANARY_ARTIFACT_BYTES:
        raise ValidationFailure(f"canary {label} artifact exceeds structured JSON limit")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationFailure(f"canary {label} artifact must be JSON") from exc
    if not isinstance(value, dict):
        raise ValidationFailure(f"canary {label} artifact must be an object")
    return value


def validate_ablation_artifact_bindings(
    observation: Mapping[str, Any],
    artifact_payloads: list[tuple[Mapping[str, Any], bytes]],
    *,
    schema_root: Path | None = None,
) -> dict[str, Any] | None:
    """Bind delegation claims to rehashed protocol/run-record artifact bytes."""

    if observation.get("experiment_kind") != "delegation_ablation":
        return None
    schema_root = schema_root or Path(__file__).resolve().parents[3] / "evals/canary"
    validate_canary_measurements(observation)
    controlled_kinds = {
        "experiment_protocol", "run_record", "raw_run_evidence",
        "inclusion_manifest", "local_audit_report",
    }
    if any(
        len(controlled_kinds.intersection(item[0]["measurement_kinds"])) > 1
        for item in artifact_payloads
    ):
        raise ValidationFailure("formal canary artifact roles cannot overlap")
    protocol_artifacts = [
        item for item in artifact_payloads
        if "experiment_protocol" in item[0]["measurement_kinds"]
    ]
    record_artifacts = [
        item for item in artifact_payloads
        if "run_record" in item[0]["measurement_kinds"]
    ]
    if len(protocol_artifacts) != 1 or len(record_artifacts) < 3:
        raise ValidationFailure(
            "delegation ablation requires one protocol and all audited run-record artifacts"
        )
    protocol_ref, protocol_raw = protocol_artifacts[0]
    if _sha256_bytes(protocol_raw) != protocol_ref["digest"]:
        raise ValidationFailure("delegation ablation protocol digest does not match artifact")
    protocol = _json_artifact(protocol_raw, "experiment protocol")
    validate_instance(
        protocol,
        load_json(schema_root / "experiment-protocol.schema.json"),
        "formal-delegation-experiment-protocol",
    )
    protocol_digest = canonical_digest(protocol)
    if protocol_digest != observation["experiment_protocol_digest"]:
        raise ValidationFailure("delegation ablation protocol canonical digest does not match")
    if protocol.get("experiment_kind") != "delegation_ablation":
        raise ValidationFailure("delegation ablation protocol artifact has the wrong kind")
    for field in (
        "product_repository", "git_ref", "execution_config_digest",
        "environment_digest", "quality_rubric_digest",
    ):
        if protocol.get(field) != observation.get(field):
            raise ValidationFailure(f"delegation ablation protocol {field} does not match")

    bindings = observation["ablation_run_bindings"]
    workload_id = bindings[0]["workload_id"]
    workload = next(
        (item for item in protocol.get("workloads", []) if item.get("workload_id") == workload_id),
        None,
    )
    if not workload or workload.get("workload_digest") != observation["workload_digest"]:
        raise ValidationFailure("delegation ablation workload is not bound by the protocol")
    arm_treatments = {
        item.get("arm_id"): item.get("treatment_digest")
        for item in protocol.get("arms", [])
        if isinstance(item, Mapping)
    }
    if set(arm_treatments) != DELEGATION_ABLATION_ARMS:
        raise ValidationFailure("delegation ablation protocol does not define the three arms")
    if arm_treatments.get(observation["arm_id"]) != observation["treatment_digest"]:
        raise ValidationFailure("delegation ablation observation treatment is not protocol-bound")
    planned = {
        item.get("run_id"): item
        for item in protocol.get("run_plan", [])
        if isinstance(item, Mapping)
    }
    audit_artifacts = [
        item for item in artifact_payloads
        if "local_audit_report" in item[0]["measurement_kinds"]
    ]
    inclusion_artifacts = [
        item for item in artifact_payloads
        if "inclusion_manifest" in item[0]["measurement_kinds"]
    ]
    if len(audit_artifacts) != 1 or len(inclusion_artifacts) != 1:
        raise ValidationFailure(
            "delegation ablation requires exactly one audit report and inclusion manifest"
        )
    audit = _json_artifact(audit_artifacts[0][1], "local audit report")
    inclusion = _json_artifact(inclusion_artifacts[0][1], "inclusion manifest")
    validate_instance(
        inclusion,
        load_json(schema_root / "inclusion-manifest.schema.json"),
        "formal-delegation-inclusion-manifest",
    )
    if inclusion["protocol_digest"] != protocol_digest:
        raise ValidationFailure("delegation ablation inclusion protocol digest does not match")

    included_bindings = _validated_audit_bindings(
        audit.get("included_run_bindings"), "included"
    )
    audited_bindings = _validated_audit_bindings(
        audit.get("audited_run_bindings"), "audited"
    )
    attempt_bindings = _validated_audit_bindings(
        audit.get("attempt_bindings"), "attempt"
    )
    quality_cohort_bindings = _validated_audit_bindings(
        audit.get("quality_cohort_bindings"), "quality cohort"
    )
    promotion_burden_bindings = _validated_audit_bindings(
        audit.get("promotion_burden_bindings"), "promotion burden"
    )
    invalidated_attempt_bindings = _validated_audit_bindings(
        audit.get("invalidated_attempt_bindings"), "invalidated attempt"
    )
    included_by_id = {item["run_id"]: item for item in included_bindings}
    audited_by_id = {item["run_id"]: item for item in audited_bindings}
    selected_by_id = {item["run_id"]: item for item in bindings}
    expected_attempt_set_digest = canonical_digest(
        {"attempt_bindings": promotion_burden_bindings}
    )
    blind_review_bindings = audit.get("blind_review_bindings")
    if (
        not isinstance(blind_review_bindings, list)
        or any(not isinstance(item, dict) or "run_id" not in item for item in blind_review_bindings)
        or len({item["run_id"] for item in blind_review_bindings})
        != len(blind_review_bindings)
    ):
        raise ValidationFailure("delegation ablation blind review bindings are invalid")
    blind_by_id = {item["run_id"]: item for item in blind_review_bindings}
    quality_by_id = {item["run_id"]: item for item in quality_cohort_bindings}
    if (
        audit.get("status") != "local_structural"
        or audit.get("protocol_digest") != protocol_digest
        or audit.get("failures") != []
        or any(
            {item["run_id"]: item for item in quality_cohort_bindings}.get(run_id)
            != item
            for run_id, item in selected_by_id.items()
        )
        or any(audited_by_id.get(run_id) != item for run_id, item in included_by_id.items())
        or attempt_bindings != audited_bindings
        or promotion_burden_bindings != attempt_bindings
        or quality_cohort_bindings != included_bindings
        or any(
            audited_by_id.get(item["run_id"]) != item
            for item in invalidated_attempt_bindings
        )
        or audit.get("promotion_attempt_set_digest") != expected_attempt_set_digest
        or set(blind_by_id) != set(quality_by_id)
    ):
        raise ValidationFailure("delegation ablation local audit report is not successful")
    selected_quality_binding = next(
        (item for item in bindings if item["arm_id"] == observation["arm_id"]), None
    )
    selected_blind = (
        blind_by_id.get(selected_quality_binding["run_id"])
        if selected_quality_binding is not None else None
    )
    if selected_blind is None:
        raise ValidationFailure(
            "delegation ablation frozen blind score is missing"
        )
    manifest_bindings = {
        item["run_id"]: item["run_record_digest"] for item in inclusion["entries"]
    }
    if (
        set(manifest_bindings) != set(audited_by_id)
        or any(
            manifest_bindings[run_id] != item["run_record_digest"]
            for run_id, item in audited_by_id.items()
        )
    ):
        raise ValidationFailure("delegation ablation inclusion manifest is not audit-complete")

    raw_evidence_payloads = {}
    for artifact_ref, raw in artifact_payloads:
        if "raw_run_evidence" not in artifact_ref["measurement_kinds"]:
            continue
        digest = artifact_ref["digest"]
        if _sha256_bytes(raw) != digest:
            raise ValidationFailure("delegation ablation raw evidence digest does not match")
        raw_evidence_payloads[digest] = raw
    raw_evidence_digests = set(raw_evidence_payloads)
    replacement_edges = audit.get("replacement_edges")
    if not isinstance(replacement_edges, list):
        raise ValidationFailure("delegation ablation replacement edges are invalid")
    invalidated_by_id = {item["run_id"]: item for item in invalidated_attempt_bindings}
    manifest_replacements = {
        item["run_id"]: item
        for item in inclusion["entries"]
        if item["disposition"] == "replaced"
    }
    edge_by_original = {
        item.get("invalidated_run_id"): item
        for item in replacement_edges if isinstance(item, Mapping)
    }
    if (
        set(invalidated_by_id) != set(manifest_replacements)
        or set(edge_by_original) != set(manifest_replacements)
        or any(
            set(edge) != {
                "invalidated_run_id", "replacement_run_id",
                "invalidation_artifact_digest",
            }
            or edge["replacement_run_id"] != entry["replacement_run_id"]
            or edge["invalidation_artifact_digest"]
            != entry["invalidation_artifact"]["digest"]
            for run_id, entry in manifest_replacements.items()
            for edge in [edge_by_original[run_id]]
        )
    ):
        raise ValidationFailure("delegation ablation replacement audit bindings are invalid")
    for run_id, entry in manifest_replacements.items():
        invalidation_artifact = entry["invalidation_artifact"]
        invalidation_raw = raw_evidence_payloads.get(invalidation_artifact["digest"])
        if invalidation_raw is None:
            raise ValidationFailure(
                "delegation ablation infrastructure invalidation closure is incomplete"
            )
        invalidation = _json_artifact(invalidation_raw, "infrastructure invalidation")
        validate_instance(
            invalidation,
            load_json(schema_root / "infrastructure-invalidation.schema.json"),
            f"formal-delegation-infrastructure-invalidation:{run_id}",
        )
        nested_digests = {
            invalidation["reviewer_session_artifact"]["digest"],
            *(item["digest"] for item in invalidation["diagnostic_artifacts"]),
        }
        if not nested_digests.issubset(raw_evidence_digests):
            raise ValidationFailure(
                "delegation ablation invalidation diagnostic closure is incomplete"
            )
    package_manifest_artifact = protocol["execution_config"][
        "package_manifest_artifact"
    ]
    package_manifest_raw = raw_evidence_payloads.get(
        package_manifest_artifact["digest"]
    )
    if (
        package_manifest_artifact["ref"] != "package-manifest.json"
        or package_manifest_raw is None
        or _sha256_bytes(package_manifest_raw) != package_manifest_artifact["digest"]
    ):
        raise ValidationFailure(
            "delegation ablation frozen package manifest closure is incomplete"
        )
    package_manifest = _json_artifact(package_manifest_raw, "package manifest")
    payload_files = package_manifest.get("payload_files")
    skill_digests = protocol["execution_config"]["plugin_skill_digests"]
    for skill_id, digest in skill_digests.items():
        payload = raw_evidence_payloads.get(digest)
        if payload is None or _sha256_bytes(payload) != digest:
            raise ValidationFailure(
                "delegation ablation frozen skill evidence closure is incomplete"
            )
    if (
        not isinstance(payload_files, dict)
        or len(payload_files) > canary_limits.MAX_TOTAL_ARTIFACTS
    ):
        raise ValidationFailure(
            "delegation ablation frozen package payload closure is incomplete"
        )
    reconstructed_package_bytes = 0
    for path, digest in payload_files.items():
        candidate = Path(path) if isinstance(path, str) else Path(".")
        payload = raw_evidence_payloads.get(digest) if isinstance(digest, str) else None
        if (
            not isinstance(path, str)
            or not path
            or candidate.is_absolute()
            or ".." in candidate.parts
            or path == "package-manifest.json"
            or payload is None
            or _sha256_bytes(payload) != digest
        ):
            raise ValidationFailure(
                "delegation ablation frozen package payload closure is incomplete"
            )
        reconstructed_package_bytes += len(payload)
    if reconstructed_package_bytes > canary_limits.MAX_TOTAL_ARTIFACT_BYTES:
        raise ValidationFailure(
            "delegation ablation frozen package payload closure exceeds replay limit"
        )
    fixed_protocol_artifacts = [
        protocol["quality_rubric_artifact"],
        protocol["environment_artifact"],
        *(workload["input_artifact"] for workload in protocol["workloads"]),
    ]
    if any(
        raw_evidence_payloads.get(artifact["digest"]) is None
        or _sha256_bytes(raw_evidence_payloads[artifact["digest"]])
        != artifact["digest"]
        for artifact in fixed_protocol_artifacts
    ):
        raise ValidationFailure(
            "delegation ablation fixed protocol evidence closure is incomplete"
        )
    records_by_id = {}
    outcomes_by_id: dict[str, Mapping[str, Any]] = {}
    record_canonical_digests = set()
    for artifact_ref, raw in record_artifacts:
        if _sha256_bytes(raw) != artifact_ref["digest"]:
            raise ValidationFailure("delegation ablation run-record digest does not match")
        record = _json_artifact(raw, "run record")
        run_id = record.get("run_id")
        binding = audited_by_id.get(run_id)
        if binding is None:
            raise ValidationFailure("delegation ablation run-record is absent from audit report")
        validate_instance(
            record,
            load_json(schema_root / "run-record.schema.json"),
            f"formal-delegation-run-record:{binding['run_id']}",
        )
        record_digest = canonical_digest(record)
        if record_digest != binding["run_record_digest"]:
            raise ValidationFailure("delegation ablation run-record canonical digest does not match")
        if run_id in records_by_id or record_digest in record_canonical_digests:
            raise ValidationFailure("delegation ablation audited run records must be unique")
        records_by_id[run_id] = record
        record_canonical_digests.add(record_digest)
        for field in ("run_id", "workload_id", "repeat_index", "arm_id"):
            if record.get(field) != binding[field]:
                raise ValidationFailure(f"delegation ablation run record {field} does not match")
        if record.get("evidence_status") != "local_structural":
            raise ValidationFailure("delegation ablation run record is not locally audited")
        if record.get("protocol_digest") != observation["experiment_protocol_digest"]:
            raise ValidationFailure("delegation ablation run record protocol digest does not match")
        if record.get("treatment_digest") != arm_treatments[binding["arm_id"]]:
            raise ValidationFailure("delegation ablation run record treatment does not match")
        plan = planned.get(binding["run_id"])
        if not plan or any(
            plan.get(field) != binding[field]
            for field in ("run_id", "workload_id", "repeat_index", "arm_id")
        ):
            raise ValidationFailure("delegation ablation run record is absent from protocol plan")
        required_raw_digests = _run_record_raw_evidence_digests(record)
        if not required_raw_digests.issubset(raw_evidence_digests):
            raise ValidationFailure(
                "delegation ablation run record raw evidence closure is incomplete"
            )
        outcome_artifact = record["outcome_artifact"]
        outcome_raw = raw_evidence_payloads.get(outcome_artifact["digest"])
        if outcome_raw is None:
            raise ValidationFailure(
                "delegation ablation attempt outcome closure is incomplete"
            )
        outcome = _json_artifact(outcome_raw, "attempt outcome")
        validate_instance(
            outcome,
            load_json(schema_root / "attempt-outcome.schema.json"),
            f"formal-delegation-attempt-outcome:{binding['run_id']}",
        )
        receipt_digests = {
            item["digest"] for item in outcome["raw_receipts"]
        }
        if not receipt_digests.issubset(raw_evidence_digests):
            raise ValidationFailure(
                "delegation ablation attempt outcome receipt closure is incomplete"
            )
        deliverable = outcome["deliverable_capture"]["artifact"]
        deliverable_raw = raw_evidence_payloads.get(deliverable["digest"])
        if (
            deliverable_raw is None
            or _sha256_bytes(deliverable_raw) != deliverable["digest"]
        ):
            raise ValidationFailure(
                "delegation ablation deliverable capture closure is incomplete"
            )
        outcomes_by_id[str(binding["run_id"])] = outcome
        if binding["run_id"] in quality_by_id:
            _validate_formal_blind_review_closure(
                record,
                inclusion=inclusion,
                expected_binding=blind_by_id[binding["run_id"]],
                raw_evidence_payloads=raw_evidence_payloads,
                schema_root=schema_root,
            )
    if set(records_by_id) != set(audited_by_id):
        raise ValidationFailure("delegation ablation audited run-record set is incomplete")
    _replay_local_protocol_audit(
        protocol=protocol,
        records=list(records_by_id.values()),
        inclusion=inclusion,
        supplied_audit=audit,
        raw_evidence_payloads=raw_evidence_payloads,
        schema_root=schema_root,
    )
    projection = _project_promotion_observation(
        observation=observation,
        promotion_burden_bindings=promotion_burden_bindings,
        selected_quality_binding=selected_quality_binding,
        selected_blind=selected_blind,
        outcomes_by_id=outcomes_by_id,
        records_by_id=records_by_id,
    )
    for field, derived in projection.items():
        if field in observation and observation[field] != derived:
            raise ValidationFailure(
                f"delegation ablation manifest {field} does not match replay-derived value"
            )
    for field in (
        "cost_usd_micros",
    ):
        if field in observation and field not in projection:
            raise ValidationFailure(
                f"delegation ablation manifest {field} is not replay-derivable"
            )
    return projection


def _project_promotion_observation(
    *,
    observation: Mapping[str, Any],
    promotion_burden_bindings: list[dict[str, Any]],
    selected_quality_binding: Mapping[str, Any],
    selected_blind: Mapping[str, Any],
    outcomes_by_id: Mapping[str, Mapping[str, Any]],
    records_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Project one formal arm/cell exclusively from replayed attempt facts."""

    workload_id = selected_quality_binding["workload_id"]
    repeat_index = selected_quality_binding["repeat_index"]
    arm_id = observation["arm_id"]
    burden = sorted(
        (
            binding for binding in promotion_burden_bindings
            if binding["workload_id"] == workload_id
            and binding["repeat_index"] == repeat_index
            and binding["arm_id"] == arm_id
        ),
        key=lambda item: (item["run_id"], item["run_record_digest"]),
    )
    if not burden or selected_quality_binding not in burden:
        raise ValidationFailure("delegation ablation promotion burden cell is incomplete")
    try:
        records = [records_by_id[item["run_id"]] for item in burden]
        outcomes = [outcomes_by_id[item["run_id"]] for item in burden]
    except KeyError as exc:
        raise ValidationFailure(
            "delegation ablation promotion burden outcome closure is incomplete"
        ) from exc

    def count(field: str) -> int:
        values = []
        for outcome in outcomes:
            value = outcome.get(field)
            if not isinstance(value, Mapping) or value.get("status") != "collected":
                raise ValidationFailure(
                    f"delegation ablation burden {field} is not collected"
                )
            values.append(int(value["count"]))
        return sum(values)

    input_tokens = sum(int(item["usage"]["input_tokens"]) for item in outcomes)
    cached_tokens = sum(int(item["usage"]["cached_input_tokens"]) for item in outcomes)
    projection: dict[str, Any] = {
        "promotion_attempt_set_digest": canonical_digest(
            {"attempt_bindings": burden}
        ),
        "promotion_attempt_bindings": burden,
        "quality_attempt_binding": dict(selected_quality_binding),
        "blind_review_binding": dict(selected_blind),
        "input_tokens": input_tokens,
        "noncached_input_tokens": input_tokens - cached_tokens,
        "output_tokens": sum(int(item["usage"]["output_tokens"]) for item in outcomes),
        "wall_time_milliseconds": sum(
            int(item["usage"]["wall_time_milliseconds"]) for item in outcomes
        ),
        "quality_score": selected_blind["quality_score"],
        "blind_blocker_count": selected_blind["blind_blocker_count"],
        "blind_major_count": selected_blind["blind_major_count"],
        "document_noise_units": count("document_noise"),
        "safety_violations": count("safety"),
        "human_intervention_count": count("human_intervention_count"),
        "human_rework_minutes": count("human_rework_minutes"),
        "applicable_matrix_cells": count("applicable_matrix_cells"),
        "closed_matrix_cells": count("closed_matrix_cells"),
        "production_contract_failures": count("production_contract_failures"),
        "quality_blocker_count": count("quality_blocker_count"),
        "quality_major_count": count("quality_major_count"),
        "product_gate_failures": sum(
            1
            for outcome in outcomes
            for gate in outcome["gate_outcomes"]
            if gate["status"] != "passed"
            or gate["exit_code"] != 0
            or gate["timed_out"]
        ),
    }
    costs = [item["cost"] for item in outcomes]
    if all(item.get("status") == "collected" for item in costs):
        projection["cost_usd_micros"] = sum(
            int(item["cost_usd_micros"]) for item in costs
        )
    return projection


def _validated_audit_bindings(value: Any, label: str) -> list[dict[str, Any]]:
    required = {"run_id", "workload_id", "repeat_index", "arm_id", "run_record_digest"}
    if (
        not isinstance(value, list)
        or any(not isinstance(item, dict) or set(item) != required for item in value)
        or len({item["run_id"] for item in value}) != len(value)
        or len({item["run_record_digest"] for item in value}) != len(value)
    ):
        raise ValidationFailure(f"delegation ablation {label} audit bindings are invalid")
    return value


def _run_record_raw_evidence_digests(record: Mapping[str, Any]) -> set[str]:
    """Return every replayable byte digest referenced by a local run record."""

    return set(_run_record_raw_evidence_bindings(record).values())


def _run_record_raw_evidence_bindings(record: Mapping[str, Any]) -> dict[str, str]:
    """Return the original evidence reference to content-digest binding."""

    bindings: dict[str, str] = {}

    def add(item: Any, digest_field: str = "digest", ref_field: str = "ref") -> None:
        if not isinstance(item, Mapping):
            return
        reference = item.get(ref_field)
        digest = item.get(digest_field)
        if not isinstance(reference, str) or not isinstance(digest, str):
            return
        previous = bindings.get(reference)
        if previous is not None and previous != digest:
            raise ValidationFailure(
                "delegation ablation evidence reference has conflicting digests"
            )
        bindings[reference] = digest

    add(record.get("prompt_artifact"))
    add(record.get("outcome_artifact"))
    blind_review = record.get("blind_review")
    if isinstance(blind_review, Mapping):
        add(blind_review.get("assignment_artifact"))
        add(blind_review.get("score_artifact"))
        add(blind_review.get("reveal_artifact"))
    add(record.get("platform_transcript"))
    for receipt in record.get("gate_receipts", []):
        if isinstance(receipt, Mapping):
            add(receipt, "stdout_digest", "stdout_ref")
            add(receipt, "stderr_digest", "stderr_ref")
    usage = record.get("usage")
    if isinstance(usage, Mapping):
        for thread in usage.get("threads", []):
            if not isinstance(thread, Mapping):
                continue
            add(thread, "transcript_digest", "transcript_ref")
            add(thread, "native_transcript_digest", "native_transcript_ref")
            for evidence in thread.get("evidence_refs", []):
                add(evidence)
    treatment = record.get("treatment_observation")
    if isinstance(treatment, Mapping):
        add(treatment.get("hypothesis_artifact"))
        for batch in treatment.get("delegation_hypothesis_batches", []):
            if isinstance(batch, Mapping):
                add(batch.get("prompt_artifact"))
        for evidence in treatment.get("root_child_shared_evidence", []):
            add(evidence)
    return bindings


def _validate_formal_blind_review_closure(
    record: Mapping[str, Any],
    *,
    inclusion: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
    raw_evidence_payloads: Mapping[str, bytes],
    schema_root: Path,
) -> None:
    run_id = str(record["run_id"])
    chain = record.get("blind_review")
    entry = next(
        (item for item in inclusion["entries"] if item["run_id"] == run_id), None
    )
    if not isinstance(chain, Mapping) or not isinstance(entry, Mapping) or entry.get(
        "blind_review"
    ) != chain:
        raise ValidationFailure("delegation ablation blind review chain is incomplete")
    values = {}
    for role, schema_name in (
        ("assignment", "blind-assignment.schema.json"),
        ("score", "blind-score.schema.json"),
        ("reveal", "blind-reveal.schema.json"),
    ):
        artifact = chain[f"{role}_artifact"]
        raw = raw_evidence_payloads.get(artifact["digest"])
        if raw is None or _sha256_bytes(raw) != artifact["digest"]:
            raise ValidationFailure("delegation ablation blind review closure is incomplete")
        value = _json_artifact(raw, f"blind {role}")
        validate_instance(
            value, load_json(schema_root / schema_name),
            f"formal-delegation-blind-{role}:{run_id}",
        )
        values[role] = value
    assignment = values["assignment"]
    score = values["score"]
    reveal = values["reveal"]
    nested = (
        assignment["asset_artifact"],
        assignment["rubric_artifact"],
        assignment["assignment_transcript_artifact"],
        score["evaluator_transcript_artifact"],
    )
    if any(
        raw_evidence_payloads.get(item["digest"]) is None
        or _sha256_bytes(raw_evidence_payloads[item["digest"]]) != item["digest"]
        for item in nested
    ):
        raise ValidationFailure("delegation ablation blind review closure is incomplete")
    outcome_artifact = record["outcome_artifact"]
    outcome_raw = raw_evidence_payloads.get(outcome_artifact["digest"])
    if outcome_raw is None:
        raise ValidationFailure("delegation ablation deliverable capture closure is incomplete")
    outcome = _json_artifact(outcome_raw, "attempt outcome")
    deliverable = outcome.get("deliverable_capture", {}).get("artifact")
    asset_raw = raw_evidence_payloads.get(assignment["asset_artifact"]["digest"])
    deliverable_raw = (
        raw_evidence_payloads.get(deliverable.get("digest"))
        if isinstance(deliverable, Mapping)
        else None
    )
    if (
        not isinstance(deliverable, Mapping)
        or asset_raw is None
        or deliverable_raw is None
        or assignment["asset_artifact"]["digest"] != deliverable.get("digest")
        or asset_raw != deliverable_raw
    ):
        raise ValidationFailure(
            "delegation ablation blind asset is not the captured deliverable"
        )
    expected = {
        "run_id": run_id,
        "opaque_label": assignment["opaque_label"],
        "assignment_raw_digest": chain["assignment_artifact"]["digest"],
        "assignment_canonical_digest": canonical_digest(assignment),
        "score_raw_digest": chain["score_artifact"]["digest"],
        "score_canonical_digest": canonical_digest(score),
        "reveal_raw_digest": chain["reveal_artifact"]["digest"],
        "outcome_fact_digest": reveal["outcome_fact_digest"],
        "evaluator_session_id": score["evaluator_session_id"],
        "quality_score": score["quality_score"],
        "blind_blocker_count": score["blind_blocker_count"],
        "blind_major_count": score["blind_major_count"],
    }
    if dict(expected_binding) != expected:
        raise ValidationFailure("delegation ablation blind review binding does not match")


def _replay_local_protocol_audit(
    *,
    protocol: Mapping[str, Any],
    records: list[Mapping[str, Any]],
    inclusion: Mapping[str, Any],
    supplied_audit: Mapping[str, Any],
    raw_evidence_payloads: Mapping[str, bytes],
    schema_root: Path,
) -> None:
    """Rebuild the original evidence paths and verify the supplied audit by replay."""

    evidence_bindings: dict[str, str] = {}
    for record in records:
        record_bindings = _run_record_raw_evidence_bindings(record)
        outcome_artifact = record.get("outcome_artifact")
        if isinstance(outcome_artifact, Mapping):
            outcome_raw = raw_evidence_payloads.get(outcome_artifact.get("digest"))
            if outcome_raw is None:
                raise ValidationFailure(
                    "delegation ablation attempt outcome closure is incomplete"
                )
            outcome = _json_artifact(outcome_raw, "attempt outcome")
            deliverable = outcome.get("deliverable_capture", {}).get("artifact")
            if not isinstance(deliverable, Mapping):
                raise ValidationFailure(
                    "delegation ablation deliverable capture closure is incomplete"
                )
            deliverable_ref = deliverable.get("ref")
            deliverable_digest = deliverable.get("digest")
            if not isinstance(deliverable_ref, str) or not isinstance(
                deliverable_digest, str
            ):
                raise ValidationFailure(
                    "delegation ablation deliverable capture closure is incomplete"
                )
            record_bindings[deliverable_ref] = deliverable_digest
            for receipt in outcome.get("raw_receipts", []):
                if not isinstance(receipt, Mapping):
                    raise ValidationFailure(
                        "delegation ablation attempt outcome receipt closure is incomplete"
                    )
                reference = receipt.get("ref")
                digest = receipt.get("digest")
                if not isinstance(reference, str) or not isinstance(digest, str):
                    raise ValidationFailure(
                        "delegation ablation attempt outcome receipt closure is incomplete"
                    )
                record_bindings[reference] = digest
        blind_review = record.get("blind_review")
        if isinstance(blind_review, Mapping):
            assignment_raw = raw_evidence_payloads.get(
                blind_review["assignment_artifact"]["digest"]
            )
            score_raw = raw_evidence_payloads.get(
                blind_review["score_artifact"]["digest"]
            )
            if assignment_raw is None or score_raw is None:
                raise ValidationFailure(
                    "delegation ablation blind review closure is incomplete"
                )
            assignment = _json_artifact(assignment_raw, "blind assignment")
            score = _json_artifact(score_raw, "blind score")
            for artifact in (
                assignment["asset_artifact"],
                assignment["assignment_transcript_artifact"],
                score["evaluator_transcript_artifact"],
            ):
                record_bindings[str(artifact["ref"])] = str(artifact["digest"])
        for reference, digest in record_bindings.items():
            previous = evidence_bindings.get(reference)
            if previous is not None and previous != digest:
                raise ValidationFailure(
                    "delegation ablation evidence reference has conflicting digests"
                )
            evidence_bindings[reference] = digest
    for entry in inclusion.get("entries", []):
        if not isinstance(entry, Mapping) or entry.get("disposition") != "replaced":
            continue
        invalidation_artifact = entry.get("invalidation_artifact")
        if not isinstance(invalidation_artifact, Mapping):
            raise ValidationFailure(
                "delegation ablation infrastructure invalidation closure is incomplete"
            )
        invalidation_raw = raw_evidence_payloads.get(invalidation_artifact.get("digest"))
        if invalidation_raw is None:
            raise ValidationFailure(
                "delegation ablation infrastructure invalidation closure is incomplete"
            )
        invalidation = _json_artifact(invalidation_raw, "infrastructure invalidation")
        invalidation_bindings = {
            str(invalidation_artifact["ref"]): str(invalidation_artifact["digest"]),
            str(invalidation["reviewer_session_artifact"]["ref"]): str(
                invalidation["reviewer_session_artifact"]["digest"]
            ),
            **{
                str(item["ref"]): str(item["digest"])
                for item in invalidation["diagnostic_artifacts"]
            },
        }
        for reference, digest in invalidation_bindings.items():
            previous = evidence_bindings.get(reference)
            if previous is not None and previous != digest:
                raise ValidationFailure(
                    "delegation ablation evidence reference has conflicting digests"
                )
            evidence_bindings[reference] = digest
    fixed_protocol_artifacts = [
        protocol["quality_rubric_artifact"],
        protocol["environment_artifact"],
        *(workload["input_artifact"] for workload in protocol["workloads"]),
    ]
    for artifact in fixed_protocol_artifacts:
        reference = str(artifact["ref"])
        digest = str(artifact["digest"])
        previous = evidence_bindings.get(reference)
        if previous is not None and previous != digest:
            raise ValidationFailure(
                "delegation ablation fixed evidence reference has conflicting digests"
            )
        evidence_bindings[reference] = digest

    with tempfile.TemporaryDirectory(prefix="engineering-assistant-canary-replay-") as root:
        replay_root = Path(root)
        evidence_root = replay_root / "evidence"
        plugin_content_root = replay_root / "plugin-content"
        evidence_root.mkdir()
        plugin_content_root.mkdir()
        replay_io = ArtifactIO(evidence_root, ".")
        plugin_io = ArtifactIO(plugin_content_root, ".")
        try:
            for reference, digest in evidence_bindings.items():
                payload = raw_evidence_payloads.get(digest)
                if payload is None:
                    raise ValidationFailure(
                        "delegation ablation replay evidence closure is incomplete"
                    )
                replay_io.write_bytes_exclusive(payload, *Path(reference).parts)
            manifest_artifact = protocol["execution_config"][
                "package_manifest_artifact"
            ]
            manifest_raw = raw_evidence_payloads.get(manifest_artifact["digest"])
            if manifest_raw is None:
                raise ValidationFailure(
                    "delegation ablation frozen package manifest closure is incomplete"
                )
            manifest = _json_artifact(manifest_raw, "package manifest")
            payload_files = manifest.get("payload_files")
            if not isinstance(payload_files, dict):
                raise ValidationFailure(
                    "delegation ablation frozen package payload closure is incomplete"
                )
            for relative, digest in payload_files.items():
                payload = raw_evidence_payloads.get(digest)
                if not isinstance(relative, str) or payload is None:
                    raise ValidationFailure(
                        "delegation ablation frozen package payload closure is incomplete"
                    )
                plugin_io.write_bytes_exclusive(payload, *Path(relative).parts)
            plugin_io.write_bytes_exclusive(
                manifest_raw, *Path(manifest_artifact["ref"]).parts
            )
        finally:
            replay_io.close()
            plugin_io.close()
        replayed = audit_canary_protocol(
            protocol,
            records,
            inclusion,
            schema_root=schema_root,
            evidence_root=evidence_root,
            plugin_content_root=plugin_content_root,
        )

    if (
        replayed.get("status") != "local_structural"
        or replayed.get("failures") != []
        or canonical_digest(replayed) != canonical_digest(supplied_audit)
    ):
        raise ValidationFailure(
            "delegation ablation local audit replay does not match supplied report"
        )


def validate_measurement_evidence_coverage(
    payload: dict[str, Any],
    measurement_groups,
) -> None:
    covered = {kind for group in measurement_groups for kind in group}
    required = {
        MEASUREMENT_EVIDENCE_KINDS[field]
        for field in MEASUREMENT_FIELDS
        if field in payload
    }
    if not required.issubset(covered):
        missing = sorted(required - covered)
        raise ValidationFailure(
            "canary measurement artifact coverage is missing: "
            + ", ".join(missing)
        )
OBSERVATION_FIELDS = (
    "experiment_kind",
    "experiment_protocol_digest",
    "arm_id",
    "ablation_run_bindings",
    "task_id",
    "workload_digest",
    "variant",
    "git_ref",
    "treatment_digest",
    "execution_config_digest",
    "environment_digest",
    "quality_rubric_digest",
    "evaluator_id",
    "started_at",
    "finished_at",
    *ALL_MEASUREMENT_FIELDS,
)


def _sha256_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _outside_repository(output: Path, repository_root: Path) -> None:
    try:
        output.relative_to(repository_root)
    except ValueError:
        return
    raise ValidationFailure("canary bundle output must stay outside the author repository")


def _source_artifact(reference: str, manifest_io: ArtifactIO) -> tuple[Path, bytes]:
    candidate = Path(reference)
    if candidate.is_absolute():
        raise ValidationFailure("canary source artifact paths must be relative to the manifest")
    try:
        payload = manifest_io.read_bytes_limited(
            canary_limits.MAX_ARTIFACT_BYTES,
            *candidate.parts,
        )
    except FileNotFoundError as exc:
        raise ValidationFailure("canary source artifact is missing") from exc
    return candidate, payload


def prepare_canary_bundle(
    manifest_path: Path | str,
    output_root: Path | str,
    *,
    repository_root: Path | str,
) -> dict[str, Any]:
    """Copy raw artifacts and emit local, non-attested audit observations."""

    manifest_path = Path(manifest_path)
    if manifest_path.is_symlink():
        raise ValidationFailure("canary preparation manifest cannot be a symlink")
    manifest_path = manifest_path.resolve()
    manifest_io = ArtifactIO(manifest_path.parent, ".")
    manifest, _manifest_raw = manifest_io.read_json_limited(
        canary_limits.MAX_MANIFEST_BYTES,
        manifest_path.name,
    )

    repository_root = Path(repository_root).resolve()
    output_root = Path(output_root).resolve()
    _outside_repository(output_root, repository_root)
    if not output_root.parent.is_dir():
        raise ValidationFailure("canary bundle output parent must already exist")
    output_io = ArtifactIO(output_root.parent, ".")
    output_io.assert_runtime_target(repository_root / "schemas")
    if output_io.entry_exists(output_root.name):
        raise ValidationFailure("canary bundle output already exists")

    schema_root = repository_root / "evals/canary"
    validate_instance(
        manifest,
        load_json(schema_root / "preparation-manifest.schema.json"),
        "canary-preparation-manifest",
    )
    staging_name = f".{output_root.name}.staging-{secrets.token_hex(6)}"
    _staging_path, staging_fd, staging_metadata = (
        output_io.create_directory_exclusive_open(staging_name)
    )
    staging_io = ArtifactIO.from_open_directory_fd(
        output_root.parent / staging_name,
        staging_fd,
    )
    os.close(staging_fd)
    draft_refs: list[str] = []
    incomplete_runs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    source_artifact_cache: dict[str, tuple[Path, bytes, str]] = {}
    copied_by_digest: dict[str, Path] = {}
    total_artifact_bytes = 0
    try:
        for run in manifest["runs"]:
            key = (run["task_id"], run["variant"])
            if key in seen:
                raise ValidationFailure(
                    f"duplicate canary preparation run for {key[0]} {key[1]}"
                )
            seen.add(key)
            if _parse_time(run["finished_at"]) < _parse_time(run["started_at"]):
                raise ValidationFailure("canary run finishes before it starts")
            validate_canary_measurements(run)
            if set(run["artifact_paths"]) != set(run["artifact_measurements"]):
                raise ValidationFailure(
                    "canary artifact measurement mapping must match artifact paths"
                )
            validate_measurement_evidence_coverage(
                run,
                run["artifact_measurements"].values(),
            )

            task_ref = hashlib.sha256(run["task_id"].encode("utf-8")).hexdigest()[:16]
            artifact_refs = []
            artifact_refs_by_key: dict[tuple[str, str], dict[str, Any]] = {}
            artifact_payload_by_key: dict[tuple[str, str], bytes] = {}
            for reference in run["artifact_paths"]:
                cached_source = source_artifact_cache.get(reference)
                if cached_source is None:
                    source, payload = _source_artifact(reference, manifest_io)
                    raw_digest = _sha256_bytes(payload)
                    source_artifact_cache[reference] = (source, payload, raw_digest)
                    if len(source_artifact_cache) > canary_limits.MAX_TOTAL_ARTIFACTS:
                        raise ValidationFailure(
                            "canary preparation has too many artifacts (unique source/digest)"
                        )
                    total_artifact_bytes += len(payload)
                    if total_artifact_bytes > canary_limits.MAX_TOTAL_ARTIFACT_BYTES:
                        raise ValidationFailure(
                            "canary preparation exceeds the total artifact bytes limit"
                        )
                else:
                    source, payload, raw_digest = cached_source
                relative = copied_by_digest.get(raw_digest)
                if relative is None:
                    relative = Path("artifacts/by-digest") / f"{raw_digest[7:]}.bin"
                    staging_io.write_bytes_exclusive(payload, *relative.parts)
                    copied_by_digest[raw_digest] = relative
                elif staging_io.read_bytes_limited(
                    canary_limits.MAX_ARTIFACT_BYTES, *relative.parts
                ) != payload:
                    raise ValidationFailure("canary artifact digest collision detected")
                ref_key = (relative.as_posix(), raw_digest)
                artifact_ref = artifact_refs_by_key.get(ref_key)
                if artifact_ref is None:
                    artifact_ref = {
                        "path": relative.as_posix(),
                        "digest": raw_digest,
                        "measurement_kinds": sorted(
                            run["artifact_measurements"][reference]
                        ),
                    }
                    artifact_refs_by_key[ref_key] = artifact_ref
                    artifact_payload_by_key[ref_key] = payload
                    artifact_refs.append(artifact_ref)
                else:
                    artifact_ref["measurement_kinds"] = sorted(
                        set(artifact_ref["measurement_kinds"])
                        | set(run["artifact_measurements"][reference])
                    )

            artifact_payloads = [
                (artifact_ref, artifact_payload_by_key[key])
                for key, artifact_ref in artifact_refs_by_key.items()
            ]

            promotion_projection = validate_ablation_artifact_bindings(
                {**run, "product_repository": manifest["product_repository"]},
                artifact_payloads,
                schema_root=schema_root,
            )

            observation = {
                "simulation": False,
                "product_repository": manifest["product_repository"],
                **{field: run[field] for field in OBSERVATION_FIELDS if field in run},
                "artifact_refs": artifact_refs,
                "assurance": "local_unattested",
            }
            if promotion_projection is not None:
                for field in (*ALL_MEASUREMENT_FIELDS, *PROMOTION_BINDING_FIELDS):
                    observation.pop(field, None)
                observation.update(promotion_projection)
            required_measurements = (
                ALL_MEASUREMENT_FIELDS
                if run["experiment_kind"] == "delegation_ablation"
                else MEASUREMENT_FIELDS
            )
            missing_fields = sorted(
                field for field in required_measurements if field not in observation
            )
            status = "incomplete" if missing_fields else "ready_local_audit"
            draft = {
                "schema_version": "1.0",
                "status": status,
                "observation": observation,
                "missing_fields": missing_fields,
                "claims": _observation_claims(observation),
            }
            validate_instance(
                draft,
                load_json(schema_root / "observation-draft.schema.json"),
                "canary-observation-draft",
            )
            relative_draft = Path("observations") / (
                f"observation-{task_ref}-{run['variant']}.draft.json"
            )
            staging_io.write_bytes_exclusive(
                ArtifactIO.canonical_json_bytes(draft),
                *relative_draft.parts,
            )
            draft_refs.append(relative_draft.as_posix())
            if missing_fields:
                incomplete_runs.append(
                    {
                        "task_id": run["task_id"],
                        "variant": run["variant"],
                        "missing_fields": missing_fields,
                    }
                )

        report = {
            "schema_version": "1.0",
            "status": "incomplete" if incomplete_runs else "ready_local_audit",
            "assurance": "local_unattested",
            "draft_count": len(draft_refs),
            "draft_refs": draft_refs,
            "incomplete_runs": incomplete_runs,
            "canary_result_generated": False,
        }
        staging_io.write_bytes_exclusive(
            ArtifactIO.canonical_json_bytes(report),
            "preparation-report.json",
        )
        _output_path, output_fd, output_metadata = (
            output_io.create_directory_exclusive_open(output_root.name)
        )
        final_io = ArtifactIO.from_open_directory_fd(output_root, output_fd)
        os.close(output_fd)
        try:
            staging_io.copy_contents_to(
                final_io,
                max_file_bytes=canary_limits.MAX_ARTIFACT_BYTES,
            )
            if not output_io.child_directory_matches(
                output_root.name,
                output_metadata,
            ):
                raise ValidationFailure("canary output directory identity changed")
        except Exception:
            try:
                final_io.remove_all_contents()
                output_io.remove_child_directory_if_matches(
                    output_root.name,
                    output_metadata,
                )
            except Exception:
                pass
            raise
        staging_io.remove_all_contents()
        output_io.remove_child_directory_if_matches(
            staging_name,
            staging_metadata,
        )
        return report
    except Exception:
        try:
            staging_io.remove_all_contents()
            output_io.remove_child_directory_if_matches(
                staging_name,
                staging_metadata,
            )
        except Exception:
            pass
        raise
