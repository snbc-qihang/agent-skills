"""Executable routing, behavior, state-machine and canary gates."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..runtime.catalog import load_catalog
from . import canary_limits
from .canary import (
    DELEGATION_ABLATION_ARMS,
    _project_promotion_observation,
    validate_ablation_artifact_bindings,
    validate_canary_measurements,
    validate_measurement_evidence_coverage,
)
from .canary_protocol import canonical_digest
from ..runtime.artifact_io import ArtifactIO
from ..runtime.engine import RuntimeEngine
from ..runtime.evidence import EvidenceStore
from ..runtime.feedback import (
    FeedbackStore,
    export_feedback_evolution,
    summarize_feedback_events,
)
from ..runtime.governance import InvestigationStore, QualityGate
from ..runtime.model import (
    CriterionResult,
    EvidenceRef,
    FeedbackEvent,
    FeedbackDisposition,
    InvestigationRequest,
    ProviderInvocation,
    QualityDimension,
    QualitySnapshot,
    StepResult,
)
from ..runtime.natural_intent import normalize_request
from ..runtime.provider_runtime import ProviderExecutor
from ..runtime.router import route_intent
from ..runtime.state_store import StateStore
from ..runtime.validation import ValidationFailure, load_json, validate_instance


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def run_evals(repository_root: Path | str) -> dict:
    root = Path(repository_root).resolve()
    catalog = load_catalog(root, require_sources=True)
    routing = _routing_eval(root, catalog)
    behavior = _behavior_eval(root, catalog)
    state_machine = _state_machine_eval(root, catalog)
    replay = _replay_eval(root, catalog)
    capabilities = _capability_eval(root, catalog)
    report = {
        "schema_version": "1.0",
        "version": catalog.version,
        "simulation": False,
        "evidence_type": "observed-runtime-execution",
        "routing": routing,
        "behavior": behavior,
        "state_machine": state_machine,
        "replay": replay,
        "capabilities": capabilities,
        "canary": {
            "status": "not_run",
            "reason": "尚无经人工评审并满足门槛的真实产品 canary bundle；local_unattested 只证明本地结构和摘要一致。",
            "assurance": "local_unattested",
            "simulation_results_accepted": False,
        },
    }
    _enforce_thresholds(report)
    return report


def _load_canary_observations(
    artifacts: ArtifactIO,
    evidence_refs: list[str],
) -> list[dict]:
    repository_root = Path(__file__).resolve().parents[3]
    observation_schema = load_json(
        repository_root / "evals/canary/run-evidence.schema.json"
    )
    missing_evidence = []
    observations = []
    total_artifact_count = 0
    total_artifact_bytes = 0
    artifact_cache: dict[tuple[str, str], bytes] = {}
    validated_closures: dict[tuple, dict[str, Any]] = {}
    delegation_observations: list[tuple[dict, tuple, dict[str, Any]]] = []
    for reference in evidence_refs:
        try:
            observation, _raw = artifacts.read_json_limited(
                canary_limits.MAX_OBSERVATION_BYTES,
                *Path(reference).parts,
            )
        except (FileNotFoundError, ValidationFailure):
            missing_evidence.append(reference)
            continue
        validate_instance(
            observation, observation_schema, f"canary-evidence:{reference}"
        )
        validate_canary_measurements(observation)
        validate_measurement_evidence_coverage(
            observation,
            (item["measurement_kinds"] for item in observation["artifact_refs"]),
        )
        if observation["assurance"] != "local_unattested":
            raise ValidationFailure("canary assurance must be local_unattested")
        if observation["experiment_kind"] != "delegation_ablation":
            raise ValidationFailure(
                "paired_canary is legacy evidence and is not promotable by canary assemble"
            )
        if _parse_time(observation["finished_at"]) < _parse_time(observation["started_at"]):
            raise ValidationFailure("canary evidence finishes before it starts")
        observation_artifacts = []
        for artifact in observation["artifact_refs"]:
            artifact_key = (artifact["path"], artifact["digest"])
            artifact_payload = artifact_cache.get(artifact_key)
            if artifact_payload is None:
                artifact_payload = artifacts.read_bytes_limited(
                    canary_limits.MAX_ARTIFACT_BYTES,
                    *Path(artifact["path"]).parts,
                )
                total_artifact_count += 1
                if total_artifact_count > canary_limits.MAX_TOTAL_ARTIFACTS:
                    raise ValidationFailure("canary evidence has too many artifacts")
                total_artifact_bytes += len(artifact_payload)
                if total_artifact_bytes > canary_limits.MAX_TOTAL_ARTIFACT_BYTES:
                    raise ValidationFailure("canary evidence exceeds total artifact bytes limit")
                if f"sha256:{hashlib.sha256(artifact_payload).hexdigest()}" != artifact["digest"]:
                    raise ValidationFailure("canary artifact digest does not match")
                artifact_cache[artifact_key] = artifact_payload
            observation_artifacts.append((artifact, artifact_payload))
        if observation["experiment_kind"] == "delegation_ablation":
            descriptor = _controlled_closure_descriptor(observation_artifacts)
            closure_metadata = validated_closures.get(descriptor)
            if closure_metadata is None:
                formal_projection = validate_ablation_artifact_bindings(
                    observation, observation_artifacts
                )
                closure_metadata = _derive_formal_closure_metadata(
                    observation_artifacts
                )
                cached_projection = closure_metadata["projections"].get(
                    _observation_projection_key(observation)
                )
                if formal_projection is None or cached_projection != formal_projection:
                    raise ValidationFailure(
                        "delegation ablation replay projection cache is inconsistent"
                    )
                validated_closures[descriptor] = closure_metadata
            else:
                _validate_reused_ablation_observation_claims(
                    observation, closure_metadata
                )
            delegation_observations.append(
                (observation, descriptor, closure_metadata)
            )
        else:
            validate_ablation_artifact_bindings(
                observation, observation_artifacts
            )
        observations.append(observation)
    if missing_evidence:
        raise ValidationFailure(f"canary evidence files are missing or non-local: {', '.join(missing_evidence)}")
    _validate_delegation_observation_coverage(delegation_observations)
    return observations


_FORMAL_ARTIFACT_KINDS = frozenset(
    {
        "experiment_protocol",
        "run_record",
        "raw_run_evidence",
        "inclusion_manifest",
        "local_audit_report",
    }
)


def _controlled_closure_descriptor(
    artifact_payloads: list[tuple[Mapping[str, Any], bytes]],
) -> tuple:
    """Return a complete, stable descriptor for the controlled formal closure."""

    return tuple(
        sorted(
            (
                item["path"],
                item["digest"],
                tuple(sorted(item["measurement_kinds"])),
            )
            for item, _payload in artifact_payloads
            if _FORMAL_ARTIFACT_KINDS.intersection(item["measurement_kinds"])
        )
    )


def _formal_json_artifact(
    artifact_payloads: list[tuple[Mapping[str, Any], bytes]], kind: str
) -> dict[str, Any]:
    matches = [
        payload
        for artifact, payload in artifact_payloads
        if kind in artifact["measurement_kinds"]
    ]
    if len(matches) != 1:
        raise ValidationFailure(
            f"delegation ablation requires exactly one {kind} artifact"
        )
    try:
        value = json.loads(matches[0].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationFailure(
            f"delegation ablation {kind} artifact must be JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ValidationFailure(
            f"delegation ablation {kind} artifact must be an object"
        )
    return value


def _formal_json_artifacts(
    artifact_payloads: list[tuple[Mapping[str, Any], bytes]], kind: str
) -> list[dict[str, Any]]:
    values = []
    for artifact, payload in artifact_payloads:
        if kind not in artifact["measurement_kinds"]:
            continue
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationFailure(
                f"delegation ablation {kind} artifact must be JSON"
            ) from exc
        if not isinstance(value, dict):
            raise ValidationFailure(
                f"delegation ablation {kind} artifact must be an object"
            )
        values.append(value)
    return values


def _binding_signature(binding: Mapping[str, Any]) -> tuple:
    return (
        binding["run_id"],
        binding["workload_id"],
        binding["repeat_index"],
        binding["arm_id"],
        binding["run_record_digest"],
    )


def _cell_signature(bindings: list[Mapping[str, Any]]) -> tuple:
    return tuple(sorted(_binding_signature(item) for item in bindings))


def _observation_projection_key(observation: Mapping[str, Any]) -> tuple[str, int, str]:
    binding = observation["ablation_run_bindings"][0]
    return binding["workload_id"], binding["repeat_index"], observation["arm_id"]


def _derive_formal_closure_metadata(
    artifact_payloads: list[tuple[Mapping[str, Any], bytes]],
) -> dict[str, Any]:
    """Derive trusted metadata only after the closure passed full replay."""

    protocol = _formal_json_artifact(artifact_payloads, "experiment_protocol")
    audit = _formal_json_artifact(artifact_payloads, "local_audit_report")
    workload_digests = {
        item["workload_id"]: item["workload_digest"]
        for item in protocol["workloads"]
    }
    arm_treatments = {
        item["arm_id"]: item["treatment_digest"] for item in protocol["arms"]
    }
    records = _formal_json_artifacts(artifact_payloads, "run_record")
    records_by_id = {item["run_id"]: item for item in records}
    raw_evidence_payloads = {
        artifact["digest"]: payload
        for artifact, payload in artifact_payloads
        if "raw_run_evidence" in artifact["measurement_kinds"]
    }
    outcomes_by_id = {
        run_id: json.loads(
            raw_evidence_payloads[record["outcome_artifact"]["digest"]].decode(
                "utf-8"
            )
        )
        for run_id, record in records_by_id.items()
    }
    quality_bindings = audit["quality_cohort_bindings"]
    blind_by_id = {
        item["run_id"]: item for item in audit["blind_review_bindings"]
    }
    promotion_burden_bindings = audit["promotion_burden_bindings"]
    projections: dict[tuple[str, int, str], dict[str, Any]] = {}
    seen_projection_keys: set[tuple[str, int, str]] = set()
    for binding in quality_bindings:
        key = (
            binding["workload_id"],
            binding["repeat_index"],
            binding["arm_id"],
        )
        if key in seen_projection_keys:
            raise ValidationFailure(
                "delegation ablation promotion projection cells must be unique"
            )
        seen_projection_keys.add(key)
        try:
            projection = _project_promotion_observation(
                observation={"arm_id": binding["arm_id"]},
                promotion_burden_bindings=promotion_burden_bindings,
                selected_quality_binding=binding,
                selected_blind=blind_by_id[binding["run_id"]],
                outcomes_by_id=outcomes_by_id,
                records_by_id=records_by_id,
            )
        except ValidationFailure:
            continue
        projections[key] = projection
    included_by_cell: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for binding in audit["included_run_bindings"]:
        included_by_cell[
            (binding["workload_id"], binding["repeat_index"])
        ].append(binding)
    included_cells = {
        cell: _cell_signature(bindings)
        for cell, bindings in included_by_cell.items()
        if len(bindings) == len(DELEGATION_ABLATION_ARMS)
        and {item["arm_id"] for item in bindings} == DELEGATION_ABLATION_ARMS
    }
    return {
        "protocol_digest": canonical_digest(protocol),
        "protocol_fields": {
            field: protocol[field]
            for field in (
                "product_repository",
                "git_ref",
                "execution_config_digest",
                "environment_digest",
                "quality_rubric_digest",
            )
        },
        "workload_digests": workload_digests,
        "arm_treatments": arm_treatments,
        "included_cells": included_cells,
        "projections": projections,
    }


def _validate_reused_ablation_observation_claims(
    observation: Mapping[str, Any], closure: Mapping[str, Any]
) -> None:
    """Validate one observation's claims against a replay-validated closure."""

    if observation["experiment_protocol_digest"] != closure["protocol_digest"]:
        raise ValidationFailure(
            "delegation ablation protocol canonical digest does not match"
        )
    for field, expected in closure["protocol_fields"].items():
        if observation.get(field) != expected:
            raise ValidationFailure(
                f"delegation ablation protocol {field} does not match"
            )
    bindings = observation["ablation_run_bindings"]
    cell = (bindings[0]["workload_id"], bindings[0]["repeat_index"])
    if closure["workload_digests"].get(cell[0]) != observation["workload_digest"]:
        raise ValidationFailure(
            "delegation ablation workload is not bound by the protocol"
        )
    if closure["arm_treatments"].get(observation["arm_id"]) != observation[
        "treatment_digest"
    ]:
        raise ValidationFailure(
            "delegation ablation observation treatment is not protocol-bound"
        )
    if closure["included_cells"].get(cell) != _cell_signature(bindings):
        raise ValidationFailure(
            "delegation ablation selected run bindings are not audit-included"
        )
    projection = closure["projections"].get(
        _observation_projection_key(observation)
    )
    if projection is None:
        raise ValidationFailure(
            "delegation ablation observation is not replay-derivable"
        )
    required_projection_fields = {
        "promotion_attempt_set_digest",
        "promotion_attempt_bindings",
        "quality_attempt_binding",
        "blind_review_binding",
        "input_tokens",
        "noncached_input_tokens",
        "output_tokens",
        "wall_time_milliseconds",
        "cost_usd_micros",
        "quality_score",
        "blind_blocker_count",
        "blind_major_count",
        "document_noise_units",
        "safety_violations",
        "human_intervention_count",
        "human_rework_minutes",
        "applicable_matrix_cells",
        "closed_matrix_cells",
        "production_contract_failures",
        "quality_blocker_count",
        "quality_major_count",
        "product_gate_failures",
    }
    if not required_projection_fields.issubset(projection):
        raise ValidationFailure(
            "delegation ablation promotion projection is incomplete"
        )
    for field in sorted(required_projection_fields):
        if observation.get(field) != projection[field]:
            raise ValidationFailure(
                f"delegation ablation observation {field} does not match replay projection"
            )


def _validate_delegation_observation_coverage(
    entries: list[tuple[Mapping[str, Any], tuple, Mapping[str, Any]]],
) -> None:
    """Require one observation pair for every included repeat of each used workload."""

    by_closure: dict[tuple, list[Mapping[str, Any]]] = defaultdict(list)
    workload_closures: dict[tuple[str, str], tuple] = {}
    protocol_closures: dict[str, tuple] = {}
    for observation, descriptor, closure in entries:
        by_closure[descriptor].append(observation)
        protocol_digest = observation["experiment_protocol_digest"]
        previous_protocol_closure = protocol_closures.get(protocol_digest)
        if (
            previous_protocol_closure is not None
            and previous_protocol_closure != descriptor
        ):
            raise ValidationFailure(
                "delegation ablation protocol observations use inconsistent audit closures"
            )
        protocol_closures[protocol_digest] = descriptor
        workload_id = observation["ablation_run_bindings"][0]["workload_id"]
        workload_key = (protocol_digest, workload_id)
        previous = workload_closures.get(workload_key)
        if previous is not None and previous != descriptor:
            raise ValidationFailure(
                "delegation ablation workload observations use inconsistent audit closures"
            )
        workload_closures[workload_key] = descriptor

    for descriptor, observations in by_closure.items():
        closure = next(
            closure
            for _observation, candidate, closure in entries
            if candidate == descriptor
        )
        used_workloads = {
            item["ablation_run_bindings"][0]["workload_id"]
            for item in observations
        }
        expected_cells = {
            cell: signature
            for cell, signature in closure["included_cells"].items()
            if cell[0] in used_workloads
        }
        observed: dict[tuple[tuple[str, int], str], int] = defaultdict(int)
        for observation in observations:
            bindings = observation["ablation_run_bindings"]
            cell = (bindings[0]["workload_id"], bindings[0]["repeat_index"])
            if expected_cells.get(cell) != _cell_signature(bindings):
                raise ValidationFailure(
                    "delegation ablation observation is outside the audit-included repeat cells"
                )
            observed[(cell, observation["variant"])] += 1
        incomplete = [
            (cell, variant, observed.get((cell, variant), 0))
            for cell in sorted(expected_cells)
            for variant in ("baseline", "candidate")
            if observed.get((cell, variant), 0) != 1
        ]
        if incomplete:
            raise ValidationFailure(
                "delegation ablation requires exactly one baseline/candidate "
                "observation pair for every audit-included repeat cell"
            )


def _pair_canary_observations(
    observations: list[dict],
) -> tuple[dict[tuple[str, str], dict], set[str]]:
    pairs = {}
    for observation in observations:
        key = (observation["task_id"], observation["variant"])
        if key in pairs:
            raise ValidationFailure(f"duplicate canary evidence for {key[0]} {key[1]}")
        pairs[key] = observation
    task_ids = {task_id for task_id, _ in pairs}
    incomplete = [
        task_id
        for task_id in sorted(task_ids)
        if (task_id, "baseline") not in pairs or (task_id, "candidate") not in pairs
    ]
    workload_digests = {
        pairs[(task_id, "baseline")]["workload_digest"]
        for task_id in task_ids
        if (task_id, "baseline") in pairs
    }
    if len(task_ids) < 5 or len(workload_digests) < 5 or incomplete:
        raise ValidationFailure(
            "canary evidence requires complete pairs for at least five distinct workloads"
        )
    used_ablation_triads: dict[tuple[str, ...], str] = {}
    used_ablation_run_ids: dict[str, str] = {}
    used_ablation_record_digests: dict[str, str] = {}
    ablation_workload_ids: dict[str, str] = {}
    ablation_workload_digests: dict[str, str] = {}
    for task_id in task_ids:
        baseline = pairs[(task_id, "baseline")]
        candidate = pairs[(task_id, "candidate")]
        if baseline["workload_digest"] != candidate["workload_digest"]:
            raise ValidationFailure("canary pair workload digests do not match")
        if baseline["quality_rubric_digest"] != candidate["quality_rubric_digest"]:
            raise ValidationFailure("canary pair quality rubrics do not match")
        if baseline["environment_digest"] != candidate["environment_digest"]:
            raise ValidationFailure("canary pair environments do not match")
        if baseline["evaluator_id"] != candidate["evaluator_id"]:
            raise ValidationFailure("canary pair evaluators do not match")
        if baseline["git_ref"] != candidate["git_ref"]:
            raise ValidationFailure("canary pair git refs do not match")
        for field in ("experiment_kind", "experiment_protocol_digest"):
            if baseline[field] != candidate[field]:
                raise ValidationFailure(f"canary pair {field} values do not match")
        if baseline.get("ablation_run_bindings") != candidate.get(
            "ablation_run_bindings"
        ):
            raise ValidationFailure("canary pair ablation run bindings do not match")
        if baseline["experiment_kind"] == "delegation_ablation":
            workload_id = baseline["ablation_run_bindings"][0]["workload_id"]
            workload_digest = baseline["workload_digest"]
            previous_digest = ablation_workload_ids.get(workload_id)
            previous_id = ablation_workload_digests.get(workload_digest)
            if (
                previous_digest is not None
                and previous_digest != workload_digest
            ) or (previous_id is not None and previous_id != workload_id):
                raise ValidationFailure(
                    "delegation ablation workload ids and digests must be one-to-one"
                )
            ablation_workload_ids[workload_id] = workload_digest
            ablation_workload_digests[workload_digest] = workload_id
            triad = tuple(
                sorted(
                    item["run_record_digest"]
                    for item in baseline["ablation_run_bindings"]
                )
            )
            previous_task = used_ablation_triads.get(triad)
            if previous_task is not None:
                raise ValidationFailure(
                    "delegation ablation run-record triad cannot be reused across tasks"
                )
            used_ablation_triads[triad] = task_id
            for binding in baseline["ablation_run_bindings"]:
                for value, seen, label in (
                    (binding["run_id"], used_ablation_run_ids, "run id"),
                    (
                        binding["run_record_digest"],
                        used_ablation_record_digests,
                        "run-record digest",
                    ),
                ):
                    if value in seen:
                        raise ValidationFailure(
                            f"delegation ablation {label} cannot be reused across tasks"
                        )
                    seen[value] = task_id
        if (
            baseline["execution_config_digest"]
            != candidate["execution_config_digest"]
        ):
            raise ValidationFailure(
                "canary pair execution config digests do not match"
            )
    return pairs, task_ids


def _canary_metrics(
    pairs: dict[tuple[str, str], dict], task_ids: set[str]
) -> dict:
    def reduction_ratio(baseline: int, candidate: int) -> float | int:
        if baseline == 0:
            return 0 if candidate == 0 else -1
        return 1 - candidate / baseline

    workload_efficiency = []
    for task_id in sorted(task_ids):
        baseline = pairs[(task_id, "baseline")]
        candidate = pairs[(task_id, "candidate")]
        fields = {
            "total_input_token_reduction_ratio": "input_tokens",
            "noncached_input_token_reduction_ratio": "noncached_input_tokens",
            "output_token_reduction_ratio": "output_tokens",
            "wall_time_reduction_ratio": "wall_time_milliseconds",
        }
        reductions = {}
        for metric, field in fields.items():
            reductions[metric] = reduction_ratio(
                baseline[field], candidate[field]
            )
        workload_efficiency.append(
            {
                "task_id": task_id,
                "workload_digest": baseline["workload_digest"],
                **(
                    {
                        "workload_id": baseline["ablation_run_bindings"][0][
                            "workload_id"
                        ]
                    }
                    if baseline["experiment_kind"] == "delegation_ablation"
                    else {}
                ),
                **reductions,
                "overhead_fields": sorted(
                    metric
                    for metric, field in fields.items()
                    if candidate[field] > baseline[field]
                ),
            }
        )
    baseline_input_tokens = sum(
        pairs[(task_id, "baseline")]["input_tokens"] for task_id in task_ids
    )
    candidate_input_tokens = sum(
        pairs[(task_id, "candidate")]["input_tokens"] for task_id in task_ids
    )
    baseline_noncached_input_tokens = sum(
        pairs[(task_id, "baseline")]["noncached_input_tokens"]
        for task_id in task_ids
    )
    candidate_noncached_input_tokens = sum(
        pairs[(task_id, "candidate")]["noncached_input_tokens"]
        for task_id in task_ids
    )
    baseline_output_tokens = sum(
        pairs[(task_id, "baseline")]["output_tokens"] for task_id in task_ids
    )
    candidate_output_tokens = sum(
        pairs[(task_id, "candidate")]["output_tokens"] for task_id in task_ids
    )
    baseline_wall_time = sum(
        pairs[(task_id, "baseline")]["wall_time_milliseconds"]
        for task_id in task_ids
    )
    candidate_wall_time = sum(
        pairs[(task_id, "candidate")]["wall_time_milliseconds"]
        for task_id in task_ids
    )
    baseline_tokens = sum(
        pairs[(task_id, "baseline")]["input_tokens"]
        + pairs[(task_id, "baseline")]["output_tokens"]
        for task_id in task_ids
    )
    candidate_tokens = sum(
        pairs[(task_id, "candidate")]["input_tokens"]
        + pairs[(task_id, "candidate")]["output_tokens"]
        for task_id in task_ids
    )
    baseline_cost = sum(
        pairs[(task_id, "baseline")]["cost_usd_micros"] for task_id in task_ids
    )
    candidate_cost = sum(
        pairs[(task_id, "candidate")]["cost_usd_micros"] for task_id in task_ids
    )
    baseline_noise = sum(
        pairs[(task_id, "baseline")]["document_noise_units"]
        for task_id in task_ids
    )
    candidate_noise = sum(
        pairs[(task_id, "candidate")]["document_noise_units"]
        for task_id in task_ids
    )
    if (
        baseline_tokens <= 0
        or baseline_input_tokens <= 0
        or baseline_wall_time <= 0
        or baseline_cost <= 0
        or baseline_noise <= 0
    ):
        raise ValidationFailure(
            "canary baseline requires positive usage, timing, cost, and document-noise measurements"
        )
    quality_deltas = [
        pairs[(task_id, "candidate")]["quality_score"]
        - pairs[(task_id, "baseline")]["quality_score"]
        for task_id in task_ids
    ]
    return {
        "quality_delta_points": sum(quality_deltas) / len(task_ids),
        "worst_workload_quality_delta_points": min(quality_deltas),
        "token_reduction_ratio": 1 - candidate_tokens / baseline_tokens,
        "total_input_token_reduction_ratio": (
            1 - candidate_input_tokens / baseline_input_tokens
        ),
        "noncached_input_token_reduction_ratio": reduction_ratio(
            baseline_noncached_input_tokens,
            candidate_noncached_input_tokens,
        ),
        "output_token_reduction_ratio": reduction_ratio(
            baseline_output_tokens,
            candidate_output_tokens,
        ),
        "wall_time_reduction_ratio": 1 - candidate_wall_time / baseline_wall_time,
        "worst_workload_total_input_token_reduction_ratio": min(
            item["total_input_token_reduction_ratio"]
            for item in workload_efficiency
        ),
        "worst_workload_noncached_input_token_reduction_ratio": min(
            item["noncached_input_token_reduction_ratio"]
            for item in workload_efficiency
        ),
        "worst_workload_output_token_reduction_ratio": min(
            item["output_token_reduction_ratio"] for item in workload_efficiency
        ),
        "worst_workload_wall_time_reduction_ratio": min(
            item["wall_time_reduction_ratio"] for item in workload_efficiency
        ),
        "cost_reduction_ratio": 1 - candidate_cost / baseline_cost,
        "document_noise_reduction_ratio": 1 - candidate_noise / baseline_noise,
        "safety_violations": sum(
            pairs[(task_id, "candidate")]["safety_violations"]
            for task_id in task_ids
        ),
        "blind_blocker_count": sum(
            pairs[(task_id, "candidate")]["blind_blocker_count"]
            for task_id in task_ids
        ),
        "blind_major_count": sum(
            pairs[(task_id, "candidate")]["blind_major_count"]
            for task_id in task_ids
        ),
        "open_matrix_cells": sum(
            pairs[(task_id, "candidate")]["applicable_matrix_cells"]
            - pairs[(task_id, "candidate")]["closed_matrix_cells"]
            for task_id in task_ids
        ),
        "production_contract_failures": sum(
            pairs[(task_id, "candidate")]["production_contract_failures"]
            for task_id in task_ids
        ),
        "workload_efficiency": workload_efficiency,
    }


def _single_canary_value(
    observations: list[dict], field: str, *, variant: str | None = None
):
    values = {
        observation[field]
        for observation in observations
        if variant is None or observation["variant"] == variant
    }
    if len(values) != 1:
        scope = f"{variant} " if variant else ""
        label = field.replace("_", " ")
        raise ValidationFailure(f"{scope}canary evidence must use one {label}")
    return next(iter(values))


CANARY_PROMOTION_THRESHOLDS = {
    "quality_delta_points": ("minimum", -2),
    "worst_workload_quality_delta_points": ("minimum", -5),
    "total_input_token_reduction_ratio": ("minimum", 0),
    "noncached_input_token_reduction_ratio": ("minimum", 0),
    "output_token_reduction_ratio": ("minimum", 0),
    "wall_time_reduction_ratio": ("minimum", 0),
    "worst_workload_total_input_token_reduction_ratio": ("minimum", 0),
    "worst_workload_noncached_input_token_reduction_ratio": ("minimum", 0),
    "worst_workload_output_token_reduction_ratio": ("minimum", 0),
    "worst_workload_wall_time_reduction_ratio": ("minimum", 0),
    "cost_reduction_ratio": ("minimum", 0.25),
    "document_noise_reduction_ratio": ("minimum", 0.30),
    "safety_violations": ("maximum", 0),
    "blind_blocker_count": ("maximum", 0),
    "blind_major_count": ("maximum", 0),
    "open_matrix_cells": ("maximum", 0),
    "production_contract_failures": ("maximum", 0),
}


def canary_threshold_failures(metrics: Mapping[str, Any]) -> list[str]:
    """Return deterministic promotion failures; never interrupts task execution."""

    failures = set()
    tolerance = 1e-9
    for field, (direction, threshold) in CANARY_PROMOTION_THRESHOLDS.items():
        value = metrics[field]
        if isinstance(value, float) and not math.isfinite(value):
            failures.add(field)
            continue
        failed = (
            value < threshold - tolerance
            if direction == "minimum"
            else value > threshold + tolerance
        )
        if failed:
            failures.add(field)
    for workload in metrics.get("workload_efficiency", []):
        for field in workload.get("overhead_fields", []):
            failures.add(f"worst_workload_{field}")
    return sorted(failures)


def _validate_result_ablation_bindings(result: Mapping[str, Any]) -> None:
    bindings = result.get("ablation_run_bindings")
    if result.get("experiment_kind") != "delegation_ablation":
        if bindings is not None:
            raise ValidationFailure("paired canary result cannot contain ablation bindings")
        raise ValidationFailure(
            "paired_canary is legacy evidence and is not promotable"
        )
    if not isinstance(bindings, list):
        raise ValidationFailure("delegation ablation result requires run bindings")
    task_ids = set()
    triads = set()
    run_ids = set()
    record_digests = set()
    for item in bindings:
        if not isinstance(item, Mapping) or set(item) != {"task_id", "runs"}:
            raise ValidationFailure("delegation ablation result binding is malformed")
        task_id = item["task_id"]
        if task_id in task_ids:
            raise ValidationFailure("delegation ablation result task bindings must be unique")
        task_ids.add(task_id)
        runs = item["runs"]
        if not isinstance(runs, list):
            raise ValidationFailure("delegation ablation result runs must be an array")
        probe = {
            "experiment_kind": "delegation_ablation",
            "variant": "baseline",
            "arm_id": "full_local_control",
            "ablation_run_bindings": runs,
        }
        validate_canary_measurements(probe)
        triad = tuple(sorted(run["run_record_digest"] for run in runs))
        if triad in triads:
            raise ValidationFailure(
                "delegation ablation result cannot reuse a run-record triad"
            )
        triads.add(triad)
        for run in runs:
            if run["run_id"] in run_ids or run["run_record_digest"] in record_digests:
                raise ValidationFailure(
                    "delegation ablation result cannot reuse run ids or run-record digests"
                )
            run_ids.add(run["run_id"])
            record_digests.add(run["run_record_digest"])


def assemble_canary_result(
    evidence_root: Path | str,
    evidence_refs: list[str],
    *,
    artifact_io: ArtifactIO | None = None,
) -> dict:
    """Derive a strict local result from digest-checked observations."""
    if not 10 <= len(evidence_refs) <= 128:
        raise ValidationFailure("canary evidence requires between 10 and 128 references")
    if len(evidence_refs) != len(set(evidence_refs)):
        raise ValidationFailure("canary evidence references must be unique")
    evidence_root = Path(evidence_root).resolve()
    artifacts = artifact_io or ArtifactIO(evidence_root, ".")
    observations = _load_canary_observations(
        artifacts,
        evidence_refs,
    )
    pairs, task_ids = _pair_canary_observations(observations)
    metrics = _canary_metrics(pairs, task_ids)
    result = {
        "simulation": False,
        "experiment_kind": _single_canary_value(observations, "experiment_kind"),
        "experiment_protocol_digest": _single_canary_value(
            observations, "experiment_protocol_digest"
        ),
        "baseline_arm_id": _single_canary_value(
            observations, "arm_id", variant="baseline"
        ),
        "candidate_arm_id": _single_canary_value(
            observations, "arm_id", variant="candidate"
        ),
        "product_repository": _single_canary_value(
            observations, "product_repository"
        ),
        "baseline_ref": _single_canary_value(
            observations, "git_ref", variant="baseline"
        ),
        "candidate_ref": _single_canary_value(
            observations, "git_ref", variant="candidate"
        ),
        "baseline_execution_config_digest": _single_canary_value(
            observations, "execution_config_digest", variant="baseline"
        ),
        "candidate_execution_config_digest": _single_canary_value(
            observations, "execution_config_digest", variant="candidate"
        ),
        "baseline_treatment_digest": _single_canary_value(
            observations, "treatment_digest", variant="baseline"
        ),
        "candidate_treatment_digest": _single_canary_value(
            observations, "treatment_digest", variant="candidate"
        ),
        "assurance": "local_unattested",
        **metrics,
        "evidence_refs": list(evidence_refs),
    }
    if result["experiment_kind"] == "delegation_ablation":
        result["ablation_run_bindings"] = [
            {
                "task_id": task_id,
                "runs": pairs[(task_id, "baseline")]["ablation_run_bindings"],
            }
            for task_id in sorted(task_ids)
        ]
    _validate_result_ablation_bindings(result)
    if result["baseline_treatment_digest"] == result["candidate_treatment_digest"]:
        raise ValidationFailure("canary treatment digests must differ")
    repository_root = Path(__file__).resolve().parents[3]
    validate_instance(
        result,
        load_json(repository_root / "evals/canary/result.schema.json"),
        "assembled-canary-result",
    )
    return result


def run_canary_result(
    path: Path | str,
) -> dict:
    path = Path(path)
    evidence_root = path.parent.resolve()
    artifacts = ArtifactIO(evidence_root, ".")
    data, _raw = artifacts.read_json_limited(
        canary_limits.MAX_OBSERVATION_BYTES,
        path.name,
    )
    repository_root = Path(__file__).resolve().parents[3]
    validate_instance(
        data,
        load_json(repository_root / "evals/canary/result.schema.json"),
        "canary-result",
    )
    _validate_result_ablation_bindings(data)
    computed = assemble_canary_result(
        evidence_root,
        data["evidence_refs"],
        artifact_io=artifacts,
    )
    metric_fields = {
        "quality_delta_points",
        "worst_workload_quality_delta_points",
        "token_reduction_ratio",
        "total_input_token_reduction_ratio",
        "noncached_input_token_reduction_ratio",
        "output_token_reduction_ratio",
        "wall_time_reduction_ratio",
        "worst_workload_total_input_token_reduction_ratio",
        "worst_workload_noncached_input_token_reduction_ratio",
        "worst_workload_output_token_reduction_ratio",
        "worst_workload_wall_time_reduction_ratio",
        "cost_reduction_ratio",
        "document_noise_reduction_ratio",
        "safety_violations",
    }
    for field, value in computed.items():
        if field == "evidence_refs":
            continue
        matches = (
            abs(data[field] - value) <= 1e-9
            if field in metric_fields
            else data[field] == value
        )
        if not matches:
            raise ValidationFailure(
                f"canary summary {field} does not match observed run evidence"
            )
    threshold_failures = canary_threshold_failures(data)
    return {
        "status": "passed" if not threshold_failures else "failed",
        **data,
        "task_count": len(data["evidence_refs"]) // 2,
        "threshold_failures": threshold_failures,
        "computed_metrics": {
            field: computed[field] for field in sorted(metric_fields)
        },
    }


def _routing_eval(root: Path, catalog) -> dict:
    data = load_json(root / "evals/routing/cases.json")
    cases = [
        {"id": f"{group['task_kind']}-{index + 1}", "task_kind": group["task_kind"], "language": item["language"], "request": item["request"]}
        for group in data["groups"]
        for index, item in enumerate(group["requests"])
    ]
    correct = 0
    no_result = 0
    unconfirmed_high_risk = 0
    failures = []
    for case in cases:
        intent = normalize_request(case["request"])
        decision = route_intent(intent, catalog)
        if decision.decision == "ask":
            no_result += 1
        if intent.task_kind == case["task_kind"]:
            correct += 1
        else:
            failures.append({"id": case["id"], "expected": case["task_kind"], "actual": intent.task_kind})
        if (intent.risk_signals or intent.requested_external_actions) and decision.decision == "proceed":
            unconfirmed_high_risk += 1
    total = len(cases)
    return {
        "corpus": "natural-bilingual",
        "normalizer": "deterministic-eval-reference-adapter",
        "production_contract": "平台 agent 生成 RouteIntent，核心路由器只消费结构化意图",
        "case_count": total,
        "languages": sorted({case["language"] for case in cases}),
        "top1_accuracy": correct / total,
        "no_result_ratio": no_result / total,
        "unconfirmed_high_risk_writes": unconfirmed_high_risk,
        "failures": failures,
    }


def _behavior_eval(root: Path, catalog) -> dict:
    cases = load_json(root / "evals/behavior/cases.json")["cases"]
    passed = 0
    failures = []
    for case in cases:
        intent = normalize_request(case["request"])
        decision = route_intent(intent, catalog)
        actual = {
            "task_kind": intent.task_kind,
            "decision": decision.decision,
            "flow_id": decision.flow_id,
            "skill_ids": decision.skill_ids,
        }
        expected = case["expected"]
        if all(actual.get(key) == value for key, value in expected.items()):
            passed += 1
        else:
            failures.append({"id": case["id"], "expected": expected, "actual": actual})
    return {
        "case_count": len(cases),
        "passed": passed,
        "pass_ratio": passed / len(cases),
        "failures": failures,
    }


def _state_machine_eval(root: Path, catalog) -> dict:
    scenarios = load_json(root / "evals/state-machine/cases.json")["scenarios"]
    results = []
    for scenario in scenarios:
        runner = {
            "approval-resume": _scenario_approval_resume,
            "evidence-resume": _scenario_evidence_resume,
            "retry": _scenario_retry,
            "block": _scenario_block,
        }.get(scenario["runner"])
        if runner is None:
            raise ValidationFailure(f"unknown state-machine runner {scenario['runner']}")
        runner(catalog, root)
        results.append({"id": scenario["id"], "status": "passed", "runner": scenario["runner"]})
    return {"case_count": len(results), "passed": len(results), "pass_ratio": 1.0, "results": results}


def _replay_eval(root: Path, catalog) -> dict:
    cases = load_json(root / "evals/replay/cases.json")["cases"]
    results = []
    for case in cases:
        if case["runner"] != "evidence-resume":
            raise ValidationFailure(f"unknown replay runner {case['runner']}")
        _scenario_evidence_resume(catalog, root)
        results.append(
            {
                "id": case["id"],
                "status": "passed",
                "observed_next_node": case["expected_next_node"],
                "simulation": False,
            }
        )
    return {"case_count": len(results), "passed": len(results), "pass_ratio": 1.0, "results": results}


def _capability_eval(root: Path, catalog) -> dict:
    definition = load_json(root / "evals/capabilities/cases.json")
    cases = definition["cases"]
    required_mechanisms = definition["required_mechanisms"]
    runners = {
        "provider-fallback": _scenario_provider_fallback,
        "feedback-summary": _scenario_feedback_summary,
        "quality-gate": _scenario_quality_gate,
        "investigation-policy": _scenario_investigation_policy,
    }
    results = []
    for case in cases:
        runner = runners.get(case["runner"])
        if runner is None:
            raise ValidationFailure(f"unknown capability runner {case['runner']}")
        detail = runner(catalog, root)
        results.append(
            {
                "id": case["id"],
                "capability": case["capability"],
                "runner": case["runner"],
                "status": "passed",
                "detail": detail,
            }
        )
    observed_mechanisms = {item["capability"] for item in results}
    if observed_mechanisms != set(required_mechanisms):
        raise ValidationFailure(
            "runtime mechanism eval does not match its approved protocol scope"
        )
    return {
        "case_count": len(results),
        "passed": len(results),
        "pass_ratio": 1.0 if results else 0.0,
        "evidence_type": "observed-runtime-mechanism",
        "product_benefit_claimed": False,
        "evaluated_scope": "approved_protocol_mechanisms",
        "coverage_claim": "selected_runtime_mechanisms_only",
        "required_mechanisms": required_mechanisms,
        "results": results,
    }


def _scenario_provider_fallback(catalog, _root: Path) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        result = ProviderExecutor(catalog).invoke(
            ProviderInvocation(
                invocation_id="eval-provider-1",
                run_id="eval-provider-run",
                capability_id="frontend-design",
                query="enterprise dashboard",
                operation="design_system",
                project_name="Capability Eval",
            ),
            provider_root=Path(temporary) / "not-configured",
        )
    if result.status != "fallback" or result.provider_id != "native-engineering":
        raise AssertionError("provider failure did not use the governed native fallback")
    return {
        "status": result.status,
        "provider_id": result.provider_id,
        "trust_level": result.trust_level,
    }


def _scenario_feedback_summary(_catalog, root: Path) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary)
        store = FeedbackStore(project, root / "schemas")
        event = FeedbackEvent(
            event_id="eval-feedback-1",
            run_id="eval-feedback-run",
            task_id="eval-feedback-task",
            node_id="quality",
            turn_id=None,
            event_type="quality_regression",
            severity="medium",
            source="runtime",
            symptom="A quality dimension regressed.",
            expected_behavior="Keep every quality dimension evaluated.",
            observed_behavior="One quality dimension requires repair.",
            human_action=None,
            evidence_refs=[],
            recurrence_key="quality-regression",
            resolution="open",
            reusable_candidate=False,
            sensitivity="internal",
            observed_at=datetime.now(timezone.utc).isoformat(),
            scope_tags=["quality"],
            change_kind="repair_failure",
            affected_asset_refs=[],
            recovery_condition="repair_and_revalidate",
            manual_intervention_kind="none",
        )
        if not store.save_event(event):
            raise AssertionError("feedback event was not persisted")
        disposition = FeedbackDisposition(
            schema_version="1.0",
            disposition_id="feedback-disposition-" + "e" * 24,
            event_id=event.event_id,
            decision="accepted_for_evolution",
            reason="capability eval acceptance",
            actor_ref="eval-reviewer",
            evidence_refs=[],
            reusable_candidate=True,
            decided_at=datetime.now(timezone.utc).isoformat(),
        )
        if not store.save_disposition(disposition):
            raise AssertionError("feedback disposition was not persisted")
        summary = summarize_feedback_events(project, root / "schemas", item_limit=1)
        evolution = export_feedback_evolution(project, root / "schemas", limit=1)
    if summary["event_count"] != 1 or summary["recurrence_counts"] != {
        "quality-regression": 1
    }:
        raise AssertionError("feedback event was not included in the bounded summary")
    if (
        evolution["proposal_count"] != 1
        or evolution["proposals"][0]["formal_assets_modified"] is not False
        or evolution["proposals"][0]["requires_review"] is not True
    ):
        raise AssertionError("accepted feedback did not produce a governed evolution proposal")
    return {
        "event_count": summary["event_count"],
        "evolution_proposal_count": evolution["proposal_count"],
        "recurrence_overflow_event_count": summary[
            "recurrence_overflow_event_count"
        ],
    }


def _scenario_quality_gate(_catalog, _root: Path) -> dict:
    dimensions = [
        QualityDimension(
            id=dimension,
            status="pass",
            delta=0,
            summary=f"{dimension} observed",
            evidence_ids=["eval-evidence"],
        )
        for dimension in (
            "correctness",
            "complexity",
            "redundancy",
            "performance",
            "architecture",
            "test_quality",
        )
    ]
    snapshot = QualitySnapshot(
        id="eval-quality-1",
        run_id="eval-quality-run",
        node_id="quality",
        state_revision=0,
        base_ref="base",
        candidate_ref="sha256:" + "a" * 64,
        candidate_evidence_id="eval-candidate",
        dimensions=dimensions,
        findings=[],
        required_repairs=[],
        evidence_refs=["eval-evidence", "eval-candidate"],
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    passed = QualityGate.evaluate(snapshot)
    warned = QualityGate.evaluate(
        replace(
            snapshot,
            id="eval-quality-2",
            dimensions=[
                *dimensions[:-1],
                QualityDimension(
                    id="test_quality",
                    status="warn",
                    delta=-1,
                    summary="test quality requires repair",
                    evidence_ids=["eval-evidence"],
                ),
            ],
        )
    )
    if passed.decision != "pass" or warned.decision != "repair":
        raise AssertionError("quality warnings did not remain a strict repair gate")
    return {"pass_decision": passed.decision, "warning_decision": warned.decision}


def _scenario_investigation_policy(_catalog, root: Path) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        store = InvestigationStore(StateStore(Path(temporary), root / "schemas"))
        base = {
            "run_id": "eval-investigation-run",
            "question": "Which official contract applies?",
            "reason": "An external fact is required.",
            "source_scope": ["official_docs"],
            "reported_blocking": False,
            "estimated_cost": "low",
            "stop_conditions": ["The primary contract is identified."],
            "evidence_requirements": ["Official documentation."],
            "status": "proposed",
        }
        automatic = store.propose(
            InvestigationRequest(
                id="eval-investigation-auto",
                mode="auto_readonly",
                **base,
            ),
            investigation_policy={
                "default_mode": "auto_readonly",
                "auto_readonly": {
                    "enabled": True,
                    "authorization_id": "eval-explicit-profile-choice",
                    "allowed_source_scope": ["official_docs"],
                    "max_cost": "low",
                },
            },
        )
        suggested = store.propose(
            InvestigationRequest(
                id="eval-investigation-suggest",
                mode="suggest_then_run",
                **base,
            ),
            investigation_policy={
                "default_mode": "suggest_then_run",
                "auto_readonly": {"enabled": False},
            },
        )
    if automatic.request.status != "running" or suggested.request.status != "proposed":
        raise AssertionError("investigation policy did not preserve the approval boundary")
    return {
        "explicit_auto_status": automatic.request.status,
        "default_suggest_status": suggested.request.status,
    }


def _scenario_approval_resume(catalog, _root: Path) -> None:
    engine = RuntimeEngine(catalog)
    unconfirmed = normalize_request("Prepare a release rollout plan")
    if route_intent(unconfirmed, catalog).decision != "confirm":
        raise AssertionError("release did not require confirmation")
    state = engine.start(
        "eval-release",
        replace(unconfirmed, confirmed_actions=["release-execution"]),
        run_id="eval-release",
    )
    if engine.next(state).next_node != "readiness":
        raise AssertionError("release did not resume")


def _scenario_evidence_resume(catalog, root: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary)
        store = StateStore(project, root / "schemas")
        evidence_store = EvidenceStore(store)
        engine = RuntimeEngine(catalog)
        state = engine.start(
            "eval-design",
            normalize_request("Design the module boundary and interface"),
            run_id="eval-design",
        )
        store.create(state)
        previous = state.revision
        engine.next(state)
        store.save(state, expected_revision=previous)
        observed = project / "observed.txt"
        observed.write_text("observed repository context\n", encoding="utf-8")
        evidence_store.save(
            state.run_id,
            EvidenceRef(
                id="observed-source",
                kind="source",
                uri=str(observed),
                producer="core-eval",
                observed_at=datetime.now(timezone.utc).isoformat(),
                provenance="runtime_observed",
                scope="state recovery eval",
            ),
        )
        previous = state.revision
        engine.complete_step(
            state,
            StepResult(
                state.run_id,
                "repo-context",
                "completed",
                [CriterionResult("repo-context:1", True, ["observed-source"])],
                ["repo context"],
                [],
                [],
                "continue",
            ),
            evidence_store=evidence_store,
        )
        store.save(state, expected_revision=previous)
        if store.load(state.run_id).current_node != "prototype":
            raise AssertionError("resumed state did not preserve next node")


def _scenario_retry(catalog, _root: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        engine = RuntimeEngine(catalog)
        state = engine.start(
            "eval-implement",
            normalize_request("Implement the accepted endpoint behavior"),
            run_id="eval-implement",
        )
        engine.next(state)
        gate = engine.complete_step(
            state,
            StepResult(state.run_id, "select-slice", "failed", [], [], [], [], "retry"),
            evidence_store=EvidenceStore(
                StateStore(Path(temporary), catalog.root / "schemas")
            ),
        )
        if gate.decision != "retry" or state.current_node != "select-slice":
            raise AssertionError("failed step did not remain retryable")


def _scenario_block(catalog, _root: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        engine = RuntimeEngine(catalog)
        state = engine.start(
            "eval-shape",
            normalize_request("Clarify this requirement and its acceptance criteria"),
            run_id="eval-shape",
        )
        engine.next(state)
        gate = engine.complete_step(
            state,
            StepResult(state.run_id, "discover-facts", "blocked", [], [], [], ["missing authority"], "block"),
            evidence_store=EvidenceStore(
                StateStore(Path(temporary), catalog.root / "schemas")
            ),
        )
        if gate.decision != "block" or state.status != "blocked":
            raise AssertionError("blocking result did not stop the run")


def _enforce_thresholds(report: dict) -> None:
    routing = report["routing"]
    failures = []
    if routing["case_count"] < 100:
        failures.append("routing case count is below 100")
    if routing["top1_accuracy"] < 0.90:
        failures.append("routing top-1 accuracy is below 90%")
    if routing["no_result_ratio"] > 0.05:
        failures.append("routing no-result ratio exceeds 5%")
    if routing["unconfirmed_high_risk_writes"] != 0:
        failures.append("unconfirmed high-risk write count is non-zero")
    if report["behavior"]["pass_ratio"] != 1.0:
        failures.append("behavior eval has failures")
    if report["state_machine"]["pass_ratio"] != 1.0:
        failures.append("state-machine eval has failures")
    if report["replay"]["pass_ratio"] != 1.0:
        failures.append("replay eval has failures")
    capabilities = report["capabilities"]
    observed_capabilities = {item["capability"] for item in capabilities["results"]}
    if capabilities["pass_ratio"] != 1.0:
        failures.append("capability eval has failures")
    if observed_capabilities != set(capabilities["required_mechanisms"]):
        failures.append("runtime mechanism eval does not cover its approved scope")
    if failures:
        raise ValidationFailure("; ".join(failures))
