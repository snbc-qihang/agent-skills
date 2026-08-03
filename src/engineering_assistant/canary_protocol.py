"""Deterministic audit of local three-arm canary experiment evidence."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import shlex
import unicodedata
from urllib.parse import unquote, unquote_plus
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .validation import ValidationFailure, load_json, validate_instance
from .artifact_io import ArtifactIO
from .compiler import verify_package


REQUIRED_ARMS_BY_KIND = {
    "routing_ablation": frozenset({"route_only", "minimum_skills", "full_local"}),
    "delegation_ablation": frozenset(
        {
            "minimum_matrix_inline",
            "minimum_matrix_risk_delegation",
            "full_local_control",
        }
    ),
}
ARM_CONTRACTS = {
    "route_only": (frozenset(), "forbidden"),
    "minimum_skills": (frozenset({"tdd", "code-review"}), "forbidden"),
    "full_local": (
        frozenset({"engineering-assistant", "tdd", "code-review"}),
        "required",
    ),
    "minimum_matrix_inline": (frozenset({"tdd", "code-review"}), "forbidden"),
    "minimum_matrix_risk_delegation": (
        frozenset({"engineering-assistant", "tdd", "code-review"}),
        "allowed",
    ),
    "full_local_control": (
        frozenset({"engineering-assistant", "tdd", "code-review"}),
        "required",
    ),
}
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens")
MAX_EVIDENCE_FILE_BYTES = 64 * 1024 * 1024
MAX_EVIDENCE_FILES = 4096
MAX_EVIDENCE_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_TRANSCRIPT_EVENTS = 1_000_000
MAX_AUDIT_INPUT_FILE_BYTES = 8 * 1024 * 1024
MAX_AUDIT_INPUT_TOTAL_BYTES = 64 * 1024 * 1024
MAX_AUDIT_INPUT_FILES = 4098
MAX_DERIVED_CACHE_ENTRY_BYTES = 256 * 1024
MAX_DERIVED_CACHE_TOTAL_BYTES = 16 * 1024 * 1024
MAX_BLIND_JSONL_EVENTS = 4096
MAX_BLIND_JSON_DEPTH = 24
MAX_BLIND_STRING_FIELDS = 8192
MAX_BLIND_STRING_CHARS = 256 * 1024
MAX_BLIND_DECODE_DEPTH = 4
MAX_BLIND_DECODE_FORMS = 64
MAX_BLIND_BASE64_TOKEN_CHARS = 16 * 1024
_EMPTY_SHA256 = "sha256:" + hashlib.sha256(b"").hexdigest()
_UNCACHEABLE_DERIVED = object()
_INVALID_DERIVED = object()

_BLIND_STABLE_SEMANTIC_ALIASES = frozenset(
    {
        "baseline",
        "baseline arm",
        "candidate",
        "candidate arm",
        "variant",
        "route only",
        "route-only arm",
        "minimum skills",
        "minimum-skills arm",
        "full local",
        "full-local arm",
        "minimum matrix inline",
        "inline matrix arm",
        "minimum matrix risk delegation",
        "risk delegation experiment arm",
        "full local control",
        "full-local control arm",
        "基线",
        "基线组",
        "候选",
        "候选组",
        "实验组",
        "控制组",
        "仅路由组",
        "最小技能组",
        "全量本地组",
        "内联矩阵组",
        "风险委派实验组",
        "全量本地控制组",
    }
)


class _EvidenceBudget:
    def __init__(self, artifacts: ArtifactIO):
        self.artifacts = artifacts
        self._sizes: dict[str, int] = {}
        self._derived: dict[tuple[str, str, str], Any] = {}
        self._uncacheable_derived: set[tuple[str, str, str]] = set()
        self._derived_digests: dict[tuple[str, str], str] = {}
        self._derived_bytes = 0
        self.total_bytes = 0
        self.event_count = 0

    def read_bytes_limited(self, limit: int, reference: str) -> bytes:
        if reference not in self._sizes and len(self._sizes) >= MAX_EVIDENCE_FILES:
            raise ValidationFailure("canary audit evidence file count exceeds limit")
        payload = self.artifacts.read_bytes_limited(limit, reference)
        if reference not in self._sizes:
            if self.total_bytes + len(payload) > MAX_EVIDENCE_TOTAL_BYTES:
                raise ValidationFailure("canary audit evidence bytes exceed limit")
            self._sizes[reference] = len(payload)
            self.total_bytes += len(payload)
        return payload

    def consume_event(self) -> None:
        self.event_count += 1
        if self.event_count > MAX_TRANSCRIPT_EVENTS:
            raise ValidationFailure("canary audit transcript event count exceeds limit")

    def get_derived(self, reference: str, parser_role: str, digest: str) -> Any:
        key = (reference, parser_role, digest)
        if key in self._uncacheable_derived:
            return _UNCACHEABLE_DERIVED
        return self._derived.get(key)

    def get_cached_derived(self, reference: str, parser_role: str) -> tuple[str, Any] | None:
        digest = self._derived_digests.get((reference, parser_role))
        if digest is None:
            return None
        return digest, self.get_derived(reference, parser_role, digest)

    def cache_derived(
        self,
        reference: str,
        parser_role: str,
        digest: str,
        value: Any,
        derived_bytes: int,
    ) -> None:
        source_key = (reference, parser_role)
        if source_key in self._derived_digests:
            return
        self._derived_digests[source_key] = digest
        key = (reference, parser_role, digest)
        if (
            derived_bytes > MAX_DERIVED_CACHE_ENTRY_BYTES
            or self._derived_bytes + derived_bytes > MAX_DERIVED_CACHE_TOTAL_BYTES
        ):
            self._uncacheable_derived.add(key)
            return
        self._derived[key] = value
        self._derived_bytes += derived_bytes


def canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _normalize_legacy_record(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Downgrade pre-hardening local records without rewriting preserved evidence."""

    if (
        record.get("schema_version") != "1.0"
        or record.get("evidence_status") != "local_structural"
    ):
        return record
    return {
        "schema_version": "1.0",
        "evidence_status": "legacy_unverifiable",
        "run_id": record.get("run_id"),
        "experiment_id": record.get("experiment_id"),
        "workload_id": record.get("workload_id"),
        "arm_id": record.get("arm_id"),
        "repeat_index": record.get("repeat_index"),
        "legacy_reason": (
            "pre-attempt-outcome local_structural record lacks a replayable outcome receipt"
        ),
    }


def audit_canary_protocol(
    protocol: Mapping[str, Any],
    run_records: Sequence[Mapping[str, Any]],
    inclusion_manifest: Mapping[str, Any],
    *,
    schema_root: Path | str,
    evidence_root: Path | str,
    plugin_content_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate structure and cross-artifact invariants without mutating evidence.

    ``plugin_content_root`` is a read-only replay seam for frozen skill bytes.  The
    protocol-declared ``plugin_root`` remains authoritative for transcript command
    validation and is never replaced in the protocol or its digests.
    """

    root = Path(schema_root)
    evidence = ArtifactIO(evidence_root, ".")
    evidence.assert_runtime_target(root)
    evidence_budget = _EvidenceBudget(evidence)
    evidence_digests: dict[str, str] = {}
    validate_instance(
        protocol,
        load_json(root / "experiment-protocol.schema.json"),
        "canary-experiment-protocol",
    )
    source_run_records = list(run_records)
    normalized_run_records = [_normalize_legacy_record(record) for record in run_records]
    run_schema = load_json(root / "run-record.schema.json")
    for index, record in enumerate(normalized_run_records):
        validate_instance(record, run_schema, f"canary-run-record[{index}]")
    validate_instance(
        inclusion_manifest,
        load_json(root / "inclusion-manifest.schema.json"),
        "canary-inclusion-manifest",
    )

    execution_config = protocol["execution_config"]
    if not isinstance(execution_config.get("plugin_root"), str) or not isinstance(
        execution_config.get("plugin_skill_digests"), Mapping
    ):
        evidence.close()
        return {
            "status": "legacy_unverifiable",
            "experiment_id": str(protocol["experiment_id"]),
            "protocol_digest": canonical_digest(protocol),
            "assurance": "local_unattested",
            "billing_status": "not_collected",
            "promotion_eligible": False,
            "included_structural_runs": 0,
            "included_run_bindings": [],
            "audited_run_bindings": [],
            "limitations": [
                "local_audit_is_not_independently_verified",
                "billing_not_collected",
                "plugin_skill_root_or_content_digest_not_frozen",
            ],
            "failures": [],
            "excluded_run_failures": [],
            "warnings": [
                "legacy protocol lacks a frozen plugin root and per-skill content digests"
            ],
        }

    failures: list[str] = []
    warnings: list[str] = []
    experiment_id = str(protocol["experiment_id"])
    expected_protocol_digest = canonical_digest(protocol)
    declared_plugin_root = Path(str(execution_config["plugin_root"]))
    content_root = (
        Path(plugin_content_root)
        if plugin_content_root is not None
        else declared_plugin_root
    )
    package_manifest_artifact = execution_config["package_manifest_artifact"]
    try:
        if package_manifest_artifact["ref"] != "package-manifest.json":
            raise ValidationFailure("package manifest artifact ref must be package-manifest.json")
        package_io = ArtifactIO(content_root, ".")
        try:
            manifest_raw = package_io.read_bytes_limited(
                1024 * 1024, "package-manifest.json"
            )
        finally:
            package_io.close()
        if (
            "sha256:" + hashlib.sha256(manifest_raw).hexdigest()
            != package_manifest_artifact["digest"]
        ):
            raise ValidationFailure("package manifest artifact digest mismatch")
        package_manifest = verify_package(content_root)
        if package_manifest["payload_digest"] != execution_config["plugin_payload_digest"]:
            raise ValidationFailure("plugin payload digest mismatch")
        for skill_id, digest in execution_config["plugin_skill_digests"].items():
            if package_manifest["payload_files"].get(
                f"skills/{skill_id}/SKILL.md"
            ) != digest:
                raise ValidationFailure("plugin skill digest is absent from package manifest")
    except (OSError, ValidationFailure):
        failures.append("plugin_package_verification_failed")
    if protocol["execution_config_digest"] != canonical_digest(protocol["execution_config"]):
        failures.append("execution_config_digest_mismatch")
    expected_workloads = {
        str(item["workload_id"]): str(item["workload_digest"])
        for item in protocol["workloads"]
    }
    workload_artifacts = {
        str(item["workload_id"]): item["input_artifact"]
        for item in protocol["workloads"]
    }
    workload_capture_contracts = {
        str(item["workload_id"]): item["deliverable_capture"]
        for item in protocol["workloads"]
    }
    for workload in protocol["workloads"]:
        workload_id = str(workload["workload_id"])
        artifact = workload["input_artifact"]
        if artifact["digest"] != workload["workload_digest"]:
            failures.append(f"workload_input_binding_mismatch:{workload_id}")
        if _evidence_digest(
            evidence_budget, str(artifact["ref"]), evidence_digests
        ) != artifact["digest"]:
            failures.append(f"workload_input_digest_mismatch:{workload_id}")
        for path_root in workload["deliverable_capture"].get("path_roots", []):
            if not _safe_relative_path(str(path_root)):
                failures.append(f"unsafe_deliverable_capture_root:{workload_id}")
    for field, artifact_field, label in (
        ("quality_rubric_digest", "quality_rubric_artifact", "quality_rubric"),
        ("environment_digest", "environment_artifact", "environment"),
    ):
        artifact = protocol[artifact_field]
        if artifact["digest"] != protocol[field]:
            failures.append(f"{label}_artifact_binding_mismatch")
        if _evidence_digest(
            evidence_budget, str(artifact["ref"]), evidence_digests
        ) != artifact["digest"]:
            failures.append(f"{label}_artifact_digest_mismatch")
    experiment_kind = str(protocol.get("experiment_kind", "routing_ablation"))
    required_arms = REQUIRED_ARMS_BY_KIND[experiment_kind]
    arms = {str(item["arm_id"]): item for item in protocol["arms"]}
    if len(expected_workloads) != len(protocol["workloads"]):
        failures.append("duplicate_workload_id")
    if set(arms) != required_arms or len(arms) != len(protocol["arms"]):
        failures.append("three_arm_protocol_required")
    for arm_id, arm in arms.items():
        conformance = arm["conformance"]
        if conformance["minimum_route_calls"] > conformance["maximum_route_calls"]:
            failures.append(f"invalid_route_call_bounds:{arm_id}")
        required = set(conformance["required_skill_ids"])
        if not required.issubset(conformance["allowed_skill_ids"]):
            failures.append(f"required_skills_not_allowed:{arm_id}")
        if arm["treatment_digest"] != canonical_digest(
            {
                "arm_id": arm_id,
                "prompt_digest": arm["prompt_digest"],
                "conformance": conformance,
            }
        ):
            failures.append(f"treatment_definition_digest_mismatch:{arm_id}")
        if (
            conformance["minimum_route_calls"] != 1
            or conformance["maximum_route_calls"] != 1
            or conformance["maximum_active_runtime_calls"] != 0
            or conformance["maximum_other_engineering_assistant_calls"] != 0
        ):
            failures.append(f"unsafe_treatment_definition:{arm_id}")
        for allowed_root in conformance["allowed_read_roots"]:
            if not _safe_relative_path(str(allowed_root)):
                failures.append(f"unsafe_allowed_read_root:{arm_id}")
        expected_skills, expected_delegation = ARM_CONTRACTS[arm_id]
        if (
            set(conformance["required_skill_ids"]) != expected_skills
            or set(conformance["allowed_skill_ids"]) != expected_skills
            or conformance["delegation_policy"] != expected_delegation
            or not conformance["forbid_recursive_discovery"]
        ):
            failures.append(f"fixed_arm_contract_mismatch:{arm_id}")

    gate_specs = {str(item["gate_id"]): item for item in protocol["gate_specs"]}
    if set(gate_specs) != set(protocol["required_gate_ids"]) or len(gate_specs) != len(
        protocol["gate_specs"]
    ):
        failures.append("gate_spec_set_mismatch")

    planned_by_id: dict[str, Mapping[str, Any]] = {}
    planned_orders: set[int] = set()
    planned_cells: Counter[tuple[str, str]] = Counter()
    for planned in protocol["run_plan"]:
        run_id = str(planned["run_id"])
        order = int(planned["planned_order"])
        if run_id in planned_by_id:
            failures.append(f"duplicate_planned_run_id:{run_id}")
        if order in planned_orders:
            failures.append(f"duplicate_planned_order:{order}")
        planned_by_id[run_id] = planned
        planned_orders.add(order)
        cell = (str(planned["workload_id"]), str(planned["arm_id"]))
        if planned["plan_role"] == "primary":
            planned_cells[cell] += 1
        if cell[0] not in expected_workloads or cell[1] not in required_arms:
            failures.append(f"invalid_planned_cell:{run_id}")
    for workload_id in expected_workloads:
        for arm_id in required_arms:
            if planned_cells[(workload_id, arm_id)] < int(protocol["minimum_repeats"]):
                failures.append(f"insufficient_planned_repeats:{workload_id}:{arm_id}")
    primary_plan = [item for item in protocol["run_plan"] if item["plan_role"] == "primary"]
    ordered_plan = sorted(primary_plan, key=lambda item: item["planned_order"])
    if {item["planned_order"] for item in ordered_plan} != set(
        range(1, len(primary_plan) + 1)
    ):
        failures.append("planned_order_not_contiguous")
    for offset in range(0, len(ordered_plan), 3):
        block = ordered_plan[offset : offset + 3]
        if len(block) != 3 or len({(item["workload_id"], item["repeat_index"]) for item in block}) != 1 or {
            item["arm_id"] for item in block
        } != required_arms:
            failures.append(f"interleaved_block_invalid:{offset // 3 + 1}")
    for spare in (item for item in protocol["run_plan"] if item["plan_role"] == "replacement_spare"):
        original = planned_by_id.get(str(spare["replacement_for_run_id"]))
        if (
            original is None
            or original["plan_role"] != "primary"
            or any(
                spare[key] != original[key]
                for key in ("workload_id", "arm_id", "repeat_index")
            )
        ):
            failures.append(f"invalid_replacement_spare:{spare['run_id']}")

    records_by_id: dict[str, Mapping[str, Any]] = {}
    record_failures: dict[str, list[str]] = {}
    source_records_by_id = {str(record["run_id"]): record for record in source_run_records}
    for record in normalized_run_records:
        run_id = str(record["run_id"])
        local_failures: list[str] = []
        record_failures[run_id] = local_failures
        if run_id in records_by_id:
            failures.append(f"duplicate_run_id:{run_id}")
        records_by_id[run_id] = record
        planned = planned_by_id.get(run_id)
        if planned is not None and any(
            record.get(key) != planned.get(key)
            for key in ("workload_id", "arm_id", "repeat_index")
        ):
            local_failures.append(f"run_plan_mismatch:{run_id}")
        if record["experiment_id"] != experiment_id:
            local_failures.append(f"record_experiment_mismatch:{run_id}")
        if record["evidence_status"] == "local_structural":
            if planned is not None and record["actual_start_order"] != planned["planned_order"]:
                local_failures.append(f"actual_start_order_mismatch:{run_id}")
            started = datetime.fromisoformat(str(record["started_at"]).replace("Z", "+00:00"))
            finished = datetime.fromisoformat(str(record["finished_at"]).replace("Z", "+00:00"))
            if finished <= started:
                local_failures.append(f"run_time_nonpositive:{run_id}")
            elif int((finished - started).total_seconds() * 1000) != record["usage"][
                "wall_time_milliseconds"
            ]:
                local_failures.append(f"run_wall_time_mismatch:{run_id}")
            if record["process_exit_code"] != 0:
                local_failures.append(f"process_exit_nonzero:{run_id}")

    seen_thread_refs: dict[str, str] = {}
    seen_thread_digests: dict[str, str] = {}
    seen_native_refs: dict[str, str] = {}
    seen_native_digests: dict[str, str] = {}
    seen_artifact_refs: dict[str, tuple[str, str]] = {}
    seen_artifact_digests: dict[str, tuple[str, str]] = {}
    for run_id, record in records_by_id.items():
        if record["evidence_status"] != "local_structural":
            continue
        for thread in record["usage"]["threads"]:
            for value, seen, label in (
                (str(thread["transcript_ref"]), seen_thread_refs, "reference"),
                (str(thread["transcript_digest"]), seen_thread_digests, "digest"),
            ):
                if value in seen and seen[value] != run_id:
                    failures.append(
                        f"experiment_thread_transcript_{label}_reused:{run_id}"
                    )
                else:
                    seen[value] = run_id
            for value, seen, role, label in (
                (
                    str(thread["transcript_ref"]),
                    seen_artifact_refs,
                    "export",
                    "reference",
                ),
                (
                    str(thread["transcript_digest"]),
                    seen_artifact_digests,
                    "export",
                    "digest",
                ),
            ):
                previous = seen.get(value)
                if previous is not None and previous != (run_id, role):
                    failures.append(
                        f"experiment_thread_artifact_{label}_reused:{run_id}"
                    )
                else:
                    seen[value] = (run_id, role)
            if thread["parent_thread_id"] is None:
                continue
            for value, seen, label in (
                (thread.get("native_transcript_ref"), seen_native_refs, "reference"),
                (thread.get("native_transcript_digest"), seen_native_digests, "digest"),
            ):
                if not isinstance(value, str):
                    continue
                if value in seen and seen[value] != run_id:
                    failures.append(
                        f"experiment_native_transcript_{label}_reused:{run_id}"
                    )
                else:
                    seen[value] = run_id
            for value, seen, role, label in (
                (
                    thread.get("native_transcript_ref"),
                    seen_artifact_refs,
                    "native",
                    "reference",
                ),
                (
                    thread.get("native_transcript_digest"),
                    seen_artifact_digests,
                    "native",
                    "digest",
                ),
            ):
                if not isinstance(value, str):
                    continue
                previous = seen.get(value)
                if previous is not None and previous != (run_id, role):
                    failures.append(
                        f"experiment_thread_artifact_{label}_reused:{run_id}"
                    )
                else:
                    seen[value] = (run_id, role)

    entries_by_id: dict[str, Mapping[str, Any]] = {}
    for entry in inclusion_manifest["entries"]:
        run_id = str(entry["run_id"])
        if run_id in entries_by_id:
            failures.append(f"duplicate_manifest_run_id:{run_id}")
        entries_by_id[run_id] = entry
    if inclusion_manifest["experiment_id"] != experiment_id:
        failures.append("manifest_experiment_mismatch")
    if inclusion_manifest["protocol_digest"] != expected_protocol_digest:
        failures.append("manifest_protocol_digest_mismatch")
    required_primary_ids = {
        run_id for run_id, item in planned_by_id.items() if item["plan_role"] == "primary"
    }
    for run_id in sorted(required_primary_ids - set(entries_by_id)):
        failures.append(f"planned_run_missing_from_manifest:{run_id}")
    for run_id in sorted(set(records_by_id) - set(entries_by_id)):
        failures.append(f"run_missing_from_manifest:{run_id}")
    for run_id in sorted(set(entries_by_id) - set(records_by_id)):
        failures.append(f"manifest_run_missing_record:{run_id}")
    for run_id in sorted(set(records_by_id) - set(planned_by_id)):
        failures.append(f"unplanned_run_record:{run_id}")
    for run_id in sorted(set(entries_by_id) - set(planned_by_id)):
        failures.append(f"unplanned_manifest_run:{run_id}")

    valid_infrastructure_invalidations: dict[str, Mapping[str, Any]] = {}
    for run_id, entry in entries_by_id.items():
        record_for_digest = records_by_id.get(run_id)
        source_record = source_records_by_id.get(run_id)
        if source_record is not None and entry["run_record_digest"] != canonical_digest(
            source_record
        ):
            failures.append(f"run_record_digest_mismatch:{run_id}")
        disposition = str(entry["disposition"])
        reason = str(entry["reason_code"])
        if disposition == "included" and reason != "protocol_conformant":
            failures.append(f"included_reason_mismatch:{run_id}")
        if (
            disposition == "included"
            and record_for_digest is not None
            and record_for_digest["evidence_status"] == "legacy_unverifiable"
        ):
            warnings.append(f"legacy manifest inclusion ignored: {run_id}")
        if disposition != "included" and reason == "protocol_conformant":
            failures.append(f"excluded_reason_mismatch:{run_id}")
        if entry["disposition"] != "replaced":
            if "replacement_run_id" in entry:
                failures.append(f"unexpected_replacement_run_id:{run_id}")
            if "invalidation_artifact" in entry:
                failures.append(f"unexpected_invalidation_artifact:{run_id}")
            continue
        replacement_id = str(entry["replacement_run_id"])
        original = records_by_id.get(run_id)
        replacement = records_by_id.get(replacement_id)
        replacement_entry = entries_by_id.get(replacement_id)
        replacement_plan = planned_by_id.get(replacement_id)
        if replacement is None or replacement_entry is None:
            failures.append(f"replacement_missing:{run_id}")
            continue
        if replacement_entry["disposition"] != "included":
            failures.append(f"replacement_not_included:{run_id}")
        if (
            replacement_plan is None
            or replacement_plan["plan_role"] != "replacement_spare"
            or replacement_plan.get("replacement_for_run_id") != run_id
        ):
            failures.append(f"replacement_not_preregistered:{run_id}")
        if original is not None and any(
            original.get(key) != replacement.get(key)
            for key in ("workload_id", "arm_id", "repeat_index")
        ):
            failures.append(f"replacement_cell_mismatch:{run_id}")
        if original is None or replacement is None:
            continue
        invalidation = _audit_infrastructure_invalidation(
            entry,
            original=original,
            replacement=replacement,
            evidence=evidence_budget,
            evidence_digests=evidence_digests,
            failures=failures,
            schema_root=root,
        )
        if invalidation is not None:
            valid_infrastructure_invalidations[run_id] = invalidation

    included_structural: list[Mapping[str, Any]] = []
    excluded_run_failures: list[dict[str, Any]] = []
    blind_review_bindings: list[dict[str, Any]] = []
    seen_blind_labels: set[str] = set()
    seen_blind_material_refs: set[str] = set()
    seen_blind_material_digests: set[str] = set()
    has_legacy = any(
        record["evidence_status"] == "legacy_unverifiable"
        and (
            entries_by_id.get(run_id) is None
            or entries_by_id[run_id]["disposition"] != "replaced"
        )
        for run_id, record in records_by_id.items()
    )
    for run_id, record in records_by_id.items():
        if record["evidence_status"] == "legacy_unverifiable":
            record_failures[run_id].append(f"legacy_unverifiable:{run_id}")
    for run_id, record in records_by_id.items():
        if record["evidence_status"] == "legacy_unverifiable":
            continue
        local_failures = record_failures[run_id]
        _audit_structural_record(
            record,
            protocol=protocol,
            protocol_digest=expected_protocol_digest,
            workloads=expected_workloads,
            workload_artifacts=workload_artifacts,
            workload_capture_contracts=workload_capture_contracts,
            arms=arms,
            gate_specs=gate_specs,
            evidence=evidence_budget,
            evidence_digests=evidence_digests,
            failures=local_failures,
            schema_root=root,
            plugin_content_root=(
                Path(plugin_content_root) if plugin_content_root is not None else None
            ),
        )
        entry = entries_by_id.get(run_id)
        if entry is None:
            continue
        if entry["disposition"] == "included":
            blind_binding = _audit_blind_review(
                record,
                entry=entry,
                protocol=protocol,
                evidence=evidence_budget,
                evidence_digests=evidence_digests,
                failures=local_failures,
                schema_root=root,
                seen_labels=seen_blind_labels,
                seen_material_refs=seen_blind_material_refs,
                seen_material_digests=seen_blind_material_digests,
            )
            if blind_binding is not None:
                blind_review_bindings.append(blind_binding)
            included_structural.append(record)
            failures.extend(local_failures)
        elif run_id in valid_infrastructure_invalidations:
            allowed_failures = {f"process_exit_nonzero:{run_id}"}
            disallowed_failures = sorted(set(local_failures) - allowed_failures)
            if disallowed_failures:
                failures.append(f"replacement_disallowed_attempt_failure:{run_id}")
                failures.extend(disallowed_failures)
            elif not local_failures:
                failures.append(f"unjustified_infrastructure_invalidation:{run_id}")
            else:
                excluded_run_failures.append(
                    {"run_id": run_id, "failures": sorted(set(local_failures))}
                )
        elif not local_failures:
            failures.append(f"unjustified_exclusion:{run_id}")
        else:
            excluded_run_failures.append(
                {"run_id": run_id, "failures": sorted(set(local_failures))}
            )
            expected_reasons = _expected_exclusion_reasons(local_failures)
            if entry["reason_code"] not in expected_reasons:
                failures.append(f"exclusion_reason_mismatch:{run_id}")
            if entry["disposition"] == "excluded":
                failures.append(f"excluded_without_replacement:{run_id}")

    for run_id, record in records_by_id.items():
        if record["evidence_status"] != "legacy_unverifiable":
            continue
        entry = entries_by_id.get(run_id)
        if entry is not None and entry["disposition"] == "included":
            has_legacy = True
        elif entry is not None:
            excluded_run_failures.append(
                {"run_id": run_id, "failures": [f"legacy_unverifiable:{run_id}"]}
            )
            if entry["reason_code"] != "legacy_unverifiable":
                failures.append(f"exclusion_reason_mismatch:{run_id}")

    cell_counts = Counter(
        (str(record["workload_id"]), str(record["arm_id"]))
        for record in included_structural
    )
    repeat_indices: dict[tuple[str, str], set[int]] = {}
    for record in included_structural:
        cell = (str(record["workload_id"]), str(record["arm_id"]))
        indices = repeat_indices.setdefault(cell, set())
        repeat_index = int(record["repeat_index"])
        if repeat_index in indices:
            failures.append(
                f"duplicate_repeat_index:{cell[0]}:{cell[1]}:{repeat_index}"
            )
        indices.add(repeat_index)
    minimum_repeats = int(protocol["minimum_repeats"])
    for workload_id in expected_workloads:
        for arm_id in required_arms:
            if cell_counts[(workload_id, arm_id)] < minimum_repeats:
                failures.append(f"insufficient_repeats:{workload_id}:{arm_id}")

    unique_failures = sorted(set(failures))
    if has_legacy and all(
        item.startswith(("legacy_unverifiable:", "insufficient_repeats:"))
        for item in unique_failures
    ):
        status = "legacy_unverifiable"
    elif unique_failures:
        status = "failed"
    else:
        status = "local_structural"
        warnings.append(
            "local protocol audit verifies structure and digests, not independent identity or billing provenance"
        )
    def attempt_binding(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "run_id": str(record["run_id"]),
            "workload_id": str(record["workload_id"]),
            "repeat_index": int(record["repeat_index"]),
            "arm_id": str(record["arm_id"]),
            "run_record_digest": canonical_digest(
                source_records_by_id[str(record["run_id"])]
            ),
        }

    attempt_bindings = sorted(
        (attempt_binding(record) for record in normalized_run_records),
        key=lambda item: item["run_id"],
    )
    quality_cohort_bindings = sorted(
        (attempt_binding(record) for record in included_structural),
        key=lambda item: item["run_id"],
    )
    invalidated_attempt_bindings = sorted(
        (
            attempt_binding(records_by_id[run_id])
            for run_id in valid_infrastructure_invalidations
        ),
        key=lambda item: item["run_id"],
    )
    replacement_edges = sorted(
        (
            {
                "invalidated_run_id": run_id,
                "replacement_run_id": str(entries_by_id[run_id]["replacement_run_id"]),
                "invalidation_artifact_digest": str(
                    entries_by_id[run_id]["invalidation_artifact"]["digest"]
                ),
            }
            for run_id in valid_infrastructure_invalidations
        ),
        key=lambda item: (item["invalidated_run_id"], item["replacement_run_id"]),
    )
    report = {
        "status": status,
        "experiment_id": experiment_id,
        "protocol_digest": expected_protocol_digest,
        "assurance": "local_unattested",
        "billing_status": "not_collected",
        "promotion_eligible": False,
        "included_structural_runs": len(included_structural),
        "included_run_bindings": sorted(
            (
                {
                    "run_id": str(record["run_id"]),
                    "workload_id": str(record["workload_id"]),
                    "repeat_index": int(record["repeat_index"]),
                    "arm_id": str(record["arm_id"]),
                    "run_record_digest": canonical_digest(
                        source_records_by_id[str(record["run_id"])]
                    ),
                }
                for record in included_structural
            ),
            key=lambda item: item["run_id"],
        ),
        "audited_run_bindings": sorted(
            (
                {
                    "run_id": str(record["run_id"]),
                    "workload_id": str(record["workload_id"]),
                    "repeat_index": int(record["repeat_index"]),
                    "arm_id": str(record["arm_id"]),
                    "run_record_digest": canonical_digest(record),
                }
                for record in source_run_records
            ),
            key=lambda item: (item["run_id"], item["run_record_digest"]),
        ),
        "attempt_bindings": attempt_bindings,
        "quality_cohort_bindings": quality_cohort_bindings,
        "promotion_burden_bindings": attempt_bindings,
        "invalidated_attempt_bindings": invalidated_attempt_bindings,
        "replacement_edges": replacement_edges,
        "promotion_attempt_set_digest": canonical_digest(
            {"attempt_bindings": attempt_bindings}
        ),
        "blind_review_bindings": sorted(
            blind_review_bindings, key=lambda item: item["run_id"]
        ),
        "limitations": [
            "local_audit_is_not_independently_verified",
            "billing_not_collected",
            "skill_reads_command_confirmed_not_dedicated_host_load_events",
            "delegation_scope_derived_from_locally_transcript_bound_prompt_artifacts",
            "descendant_conformance_derived_from_native_transcript",
            "read_scope_observation_is_local_unattested",
            "parent_child_usage_exclusivity_not_unified_by_platform",
        ],
        "failures": unique_failures,
        "excluded_run_failures": excluded_run_failures,
        "warnings": warnings,
    }
    evidence.close()
    return report


def _audit_structural_record(
    record: Mapping[str, Any],
    *,
    protocol: Mapping[str, Any],
    protocol_digest: str,
    workloads: Mapping[str, str],
    workload_artifacts: Mapping[str, Mapping[str, Any]],
    workload_capture_contracts: Mapping[str, Mapping[str, Any]],
    arms: Mapping[str, Mapping[str, Any]],
    gate_specs: Mapping[str, Mapping[str, Any]],
    evidence: _EvidenceBudget,
    evidence_digests: dict[str, str],
    failures: list[str],
    schema_root: Path,
    plugin_content_root: Path | None,
) -> None:
    run_id = str(record["run_id"])
    exact_fields = (
        "experiment_id",
        "product_repository",
        "git_ref",
        "execution_config_digest",
        "environment_digest",
        "quality_rubric_digest",
    )
    for field in exact_fields:
        if record[field] != protocol[field]:
            failures.append(f"{field}_mismatch:{run_id}")
    if record["protocol_digest"] != protocol_digest:
        failures.append(f"protocol_digest_mismatch:{run_id}")
    workload_id = str(record["workload_id"])
    if workloads.get(workload_id) != record["workload_digest"]:
        failures.append(f"workload_digest_mismatch:{run_id}")
    arm_id = str(record["arm_id"])
    arm = arms.get(arm_id)
    if arm is None:
        failures.append(f"unknown_arm:{run_id}")
        return
    if record["treatment_digest"] != arm["treatment_digest"]:
        failures.append(f"treatment_digest_mismatch:{run_id}")
    if record["prompt_digest"] != arm["prompt_digest"]:
        failures.append(f"prompt_digest_mismatch:{run_id}")
    prompt_artifact = record["prompt_artifact"]
    prompt_artifact_digest = _evidence_digest(
        evidence,
        str(prompt_artifact["ref"]),
        evidence_digests,
    )
    if prompt_artifact_digest != prompt_artifact["digest"]:
        failures.append(f"prompt_artifact_digest_mismatch:{run_id}")
    if prompt_artifact_digest != record["prompt_digest"]:
        failures.append(f"prompt_artifact_binding_mismatch:{run_id}")

    platform = record["platform_transcript"]
    if not platform["complete"]:
        failures.append(f"platform_transcript_incomplete:{run_id}")
    platform_digest, root_counts = _read_transcript_observation(
        evidence,
        str(platform["ref"]),
        parser_role="codex_export",
        plugin_root=Path(str(protocol["execution_config"]["plugin_root"])),
        plugin_skill_digests=protocol["execution_config"]["plugin_skill_digests"],
        plugin_content_root=plugin_content_root,
    )
    if platform_digest == _EMPTY_SHA256:
        failures.append(f"platform_transcript_empty:{run_id}")
    evidence_digests[str(platform["ref"])] = platform_digest
    if platform_digest != platform["digest"]:
        failures.append(f"platform_transcript_digest_mismatch:{run_id}")
    plugin_root = Path(str(protocol["execution_config"]["plugin_root"]))
    plugin_skill_digests = protocol["execution_config"]["plugin_skill_digests"]
    if root_counts is None:
        failures.append(f"platform_transcript_invalid_jsonl:{run_id}")
    elif record["prompt_digest"] not in root_counts["user_message_digests"]:
        failures.append(f"root_prompt_message_missing:{run_id}")
    conformance_observations: list[Mapping[str, Any]] = []
    if root_counts is not None:
        conformance_observations.append(root_counts)

    receipts = {str(item["gate_id"]): item for item in record["gate_receipts"]}
    if len(receipts) != len(record["gate_receipts"]):
        failures.append(f"duplicate_gate_receipt:{run_id}")
    for gate_id in protocol["required_gate_ids"]:
        receipt = receipts.get(str(gate_id))
        if receipt is None:
            failures.append(f"gate_receipt_missing:{run_id}:{gate_id}")
        else:
            gate_spec = gate_specs[str(gate_id)]
            if receipt["argv"] != gate_spec["argv"] or receipt["cwd"] != gate_spec["cwd"]:
                failures.append(f"gate_command_mismatch:{run_id}:{gate_id}")
            if receipt["command_digest"] != canonical_digest(
                {"argv": receipt["argv"], "cwd": receipt["cwd"]}
            ):
                failures.append(f"gate_command_digest_mismatch:{run_id}:{gate_id}")
            if _evidence_digest(evidence, str(receipt["stdout_ref"]), evidence_digests) != receipt[
                "stdout_digest"
            ]:
                failures.append(f"gate_stdout_digest_mismatch:{run_id}:{gate_id}")
            if _evidence_digest(evidence, str(receipt["stderr_ref"]), evidence_digests) != receipt[
                "stderr_digest"
            ]:
                failures.append(f"gate_stderr_digest_mismatch:{run_id}:{gate_id}")
            if receipt["exit_code"] != 0 or receipt["timed_out"]:
                failures.append(f"gate_outcome_mismatch:{run_id}:{gate_id}")
            if receipt["status"] != "passed":
                failures.append(f"gate_not_passed:{run_id}:{gate_id}")
            gate_started = datetime.fromisoformat(
                str(receipt["started_at"]).replace("Z", "+00:00")
            )
            gate_finished = datetime.fromisoformat(
                str(receipt["finished_at"]).replace("Z", "+00:00")
            )
            if gate_finished <= gate_started or int(
                (gate_finished - gate_started).total_seconds() * 1000
            ) != receipt["wall_time_milliseconds"]:
                failures.append(f"gate_timing_mismatch:{run_id}:{gate_id}")

    usage = record["usage"]
    threads = usage["threads"]
    thread_ids = {str(thread["thread_id"]) for thread in threads}
    roots = [thread for thread in threads if thread["parent_thread_id"] is None]
    descendants = [thread for thread in threads if thread["parent_thread_id"] is not None]
    transcript_refs = [str(thread["transcript_ref"]) for thread in threads]
    transcript_digests = [str(thread["transcript_digest"]) for thread in threads]
    if len(transcript_refs) != len(set(transcript_refs)):
        failures.append(f"thread_transcript_reference_reused:{run_id}")
    if len(transcript_digests) != len(set(transcript_digests)):
        failures.append(f"thread_transcript_digest_reused:{run_id}")
    if len(thread_ids) != len(threads) or len(roots) != 1:
        failures.append(f"usage_thread_graph_invalid:{run_id}")
    elif record["root_thread_id"] != roots[0]["thread_id"]:
        failures.append(f"root_thread_mismatch:{run_id}")
    elif (
        roots[0]["transcript_ref"] != platform["ref"]
        or roots[0]["transcript_digest"] != platform["digest"]
    ):
        failures.append(f"platform_root_thread_mismatch:{run_id}")
    if root_counts is not None and roots:
        root_usage = root_counts["root_usage"]
        if root_usage is None:
            failures.append(f"root_usage_missing_from_transcript:{run_id}")
        else:
            for field in TOKEN_FIELDS:
                if roots[0][field] != root_usage[field]:
                    failures.append(f"root_usage_mismatch:{run_id}:{field}")
    native_refs: list[str] = []
    native_digests: list[str] = []
    native_observations_by_thread: dict[str, Mapping[str, Any]] = {}
    thread_evidence: dict[str, dict[str, tuple[str, str]]] = {}
    workload_artifact = workload_artifacts.get(workload_id)
    required_thread_evidence = [
        (protocol["quality_rubric_artifact"], "quality_rubric"),
        (protocol["environment_artifact"], "fixed_environment_snapshot"),
    ]
    if workload_artifact is not None:
        required_thread_evidence.insert(
            0, (workload_artifact, "fixed_workload_input")
        )
    for thread in threads:
        thread_id = str(thread["thread_id"])
        declared_evidence: dict[str, tuple[str, str]] = {}
        declared_content_digests: set[str] = set()
        for item in thread["evidence_refs"]:
            reference = str(item["ref"])
            declared_digest = str(item["digest"])
            evidence_kind = str(item["evidence_kind"])
            if reference in declared_evidence:
                failures.append(f"thread_evidence_reference_reused:{run_id}:{thread_id}")
                continue
            if declared_digest in declared_content_digests:
                failures.append(f"thread_evidence_content_reused:{run_id}:{thread_id}")
            declared_content_digests.add(declared_digest)
            declared_evidence[reference] = (declared_digest, evidence_kind)
            if _evidence_digest(evidence, reference, evidence_digests) != declared_digest:
                failures.append(f"thread_evidence_digest_mismatch:{run_id}:{thread_id}")
        thread_evidence[thread_id] = declared_evidence
        for artifact, evidence_kind in required_thread_evidence:
            if (
                str(artifact["digest"]), evidence_kind
            ) not in declared_evidence.values():
                failures.append(
                    f"thread_fixed_evidence_missing:{run_id}:{thread_id}:{evidence_kind}"
                )
        thread_ref = str(thread["transcript_ref"])
        if thread_ref == str(platform["ref"]):
            thread_digest, thread_observation = platform_digest, root_counts
        else:
            thread_digest, thread_observation = _read_transcript_observation(
                evidence,
                thread_ref,
                parser_role="codex_export",
                plugin_root=plugin_root,
                plugin_skill_digests=plugin_skill_digests,
                plugin_content_root=plugin_content_root,
            )
        evidence_digests[thread_ref] = thread_digest
        if thread_digest != thread["transcript_digest"]:
            failures.append(
                f"thread_transcript_digest_mismatch:{run_id}:{thread_id}"
            )
        if thread_observation is None or thread_observation["root_usage"] is None:
            failures.append(f"thread_usage_missing:{run_id}:{thread_id}")
            failures.append(f"usage_attribution_incomplete:{run_id}")
        else:
            if thread_observation["thread_id"] != thread_id:
                failures.append(
                    f"thread_identity_mismatch:{run_id}:{thread_id}"
                )
            for field in TOKEN_FIELDS:
                if thread[field] != thread_observation["root_usage"][field]:
                    failures.append(
                        f"thread_usage_mismatch:{run_id}:{thread_id}:{field}"
                    )
        if thread["parent_thread_id"] is not None:
            native_ref = thread.get("native_transcript_ref")
            native_digest = thread.get("native_transcript_digest")
            if not isinstance(native_ref, str) or not isinstance(native_digest, str):
                failures.append(
                    f"descendant_native_usage_provenance_missing:{run_id}:{thread_id}"
                )
            else:
                native_refs.append(native_ref)
                native_digests.append(native_digest)
                observed_native_digest, native_observation = _read_transcript_observation(
                    evidence,
                    native_ref,
                    parser_role="codex_native",
                )
                evidence_digests[native_ref] = observed_native_digest
                if observed_native_digest != native_digest:
                    failures.append(
                        f"descendant_native_transcript_digest_mismatch:{run_id}:{thread_id}"
                    )
                native_usage = (
                    native_observation.get("root_usage")
                    if native_observation is not None
                    else None
                )
                if native_observation is None or native_usage is None:
                    failures.append(
                        f"descendant_native_usage_missing:{run_id}:{thread_id}"
                    )
                else:
                    native_observations_by_thread[thread_id] = native_observation
                    session_links = set(native_observation["session_links"])
                    expected_session_links = _expected_session_links(
                        thread_id, threads
                    )
                    if not any(
                        linked_thread_id == thread_id
                        for linked_thread_id, _parent_id in session_links
                    ):
                        failures.append(
                            f"descendant_native_thread_mismatch:{run_id}:{thread_id}"
                        )
                    if (
                        thread_id, thread["parent_thread_id"]
                    ) not in session_links:
                        failures.append(
                            f"descendant_native_parent_mismatch:{run_id}:{thread_id}"
                        )
                    if session_links != expected_session_links:
                        failures.append(
                            f"descendant_native_session_chain_mismatch:{run_id}:{thread_id}"
                        )
                    if native_observation["unverified_skill_read"]:
                        failures.append(
                            f"descendant_skill_read_unverified:{run_id}:{thread_id}"
                        )
                    conformance_observations.append(native_observation)
                    for field in TOKEN_FIELDS:
                        if thread[field] != native_usage[field]:
                            failures.append(
                                f"descendant_native_usage_mismatch:{run_id}:{thread_id}:{field}"
                            )
    if len(native_refs) != len(set(native_refs)):
        failures.append(f"native_transcript_reference_reused:{run_id}")
    if len(native_digests) != len(set(native_digests)):
        failures.append(f"native_transcript_digest_reused:{run_id}")
    if set(transcript_refs) & set(native_refs):
        failures.append(f"thread_export_native_reference_reused:{run_id}")
    if set(transcript_digests) & set(native_digests):
        failures.append(f"thread_export_native_digest_reused:{run_id}")
    if any(thread["parent_thread_id"] not in thread_ids for thread in descendants):
        failures.append(f"usage_orphan_thread:{run_id}")
    elif roots and any(
        not _thread_reaches_root(thread, threads, str(roots[0]["thread_id"]))
        for thread in descendants
    ):
        failures.append(f"usage_thread_cycle:{run_id}")
    if usage["delegation_event_count"] != len(descendants):
        failures.append(f"delegated_usage_incomplete:{run_id}")
    if (
        not usage["complete"]
        or any(not thread["complete"] for thread in threads)
        or (descendants and usage["coverage"] != "root_and_descendants")
        or usage["aggregation_semantics"] == "unknown"
    ):
        failures.append(f"usage_attribution_incomplete:{run_id}")
    components = threads if usage["aggregation_semantics"] == "per_thread_exclusive" else roots
    for field in TOKEN_FIELDS:
        if usage["aggregate"][field] != sum(int(item[field]) for item in components):
            failures.append(f"usage_total_mismatch:{run_id}:{field}")
    for label, component in [
        *((str(item["thread_id"]), item) for item in threads),
        ("aggregate", usage["aggregate"]),
    ]:
        if component["cached_input_tokens"] > component["input_tokens"]:
            failures.append(f"cached_input_exceeds_input:{run_id}:{label}")

    if record["assurance"] != "local_unattested":
        failures.append(f"assurance_nonlocal:{run_id}")
    if record["billing"].get("status") not in {"not_collected", "collected"}:
        failures.append(f"billing_status_nonlocal:{run_id}")

    _audit_attempt_outcome(
        record,
        capture_contract=workload_capture_contracts.get(workload_id),
        platform_observation=root_counts,
        evidence=evidence,
        evidence_digests=evidence_digests,
        failures=failures,
        schema_root=schema_root,
    )

    derived_counts = (
        _aggregate_conformance_counts(conformance_observations)
        if conformance_observations
        else None
    )
    observed = record["treatment_observation"]
    conformance = arm["conformance"]
    if derived_counts is not None:
        observed_to_derived = {
            "route_call_count": "route_call_count",
            "active_runtime_call_count": "active_runtime_call_count",
            "other_engineering_assistant_call_count": "other_engineering_assistant_call_count",
            "recursive_discovery_count": "recursive_discovery_count",
        }
        for observed_field, derived_field in observed_to_derived.items():
            if observed[observed_field] != derived_counts[derived_field]:
                failures.append(f"transcript_count_mismatch:{run_id}:{observed_field}")
        if set(observed["loaded_skill_ids"]) != set(derived_counts["loaded_skill_ids"]):
            failures.append(f"transcript_skill_load_mismatch:{run_id}")
        if derived_counts["active_runtime_call_count"] > conformance[
            "maximum_active_runtime_calls"
        ]:
            failures.append(f"derived_active_runtime_calls_nonconformant:{run_id}")
        if derived_counts["other_engineering_assistant_call_count"] > conformance[
            "maximum_other_engineering_assistant_calls"
        ]:
            failures.append(
                f"derived_other_engineering_assistant_calls_nonconformant:{run_id}"
            )
        if conformance["forbid_recursive_discovery"] and derived_counts[
            "recursive_discovery_count"
        ]:
            failures.append(f"derived_recursive_discovery_nonconformant:{run_id}")
    if not (
        conformance["minimum_route_calls"]
        <= observed["route_call_count"]
        <= conformance["maximum_route_calls"]
    ):
        failures.append(f"route_call_count_nonconformant:{run_id}")
    loaded = set(observed["loaded_skill_ids"])
    if not set(conformance["required_skill_ids"]).issubset(loaded) or not loaded.issubset(
        conformance["allowed_skill_ids"]
    ):
        failures.append(f"skills_nonconformant:{run_id}")
    if observed["active_runtime_call_count"] > conformance["maximum_active_runtime_calls"]:
        failures.append(f"active_runtime_calls_nonconformant:{run_id}")
    if observed["other_engineering_assistant_call_count"] > conformance[
        "maximum_other_engineering_assistant_calls"
    ]:
        failures.append(f"other_engineering_assistant_calls_nonconformant:{run_id}")
    if observed["delegation_event_count"] != usage["delegation_event_count"]:
        failures.append(f"delegation_observation_mismatch:{run_id}")
    delegation_policy = conformance["delegation_policy"]
    if delegation_policy == "forbidden" and observed["delegation_event_count"] != 0:
        failures.append(f"delegation_nonconformant:{run_id}")
    if delegation_policy == "required" and observed["delegation_event_count"] == 0:
        failures.append(f"delegation_nonconformant:{run_id}")
    unresolved = observed["unresolved_hypothesis_ids"]
    batches = observed["delegation_hypothesis_batches"]
    hypothesis_artifact = observed["hypothesis_artifact"]
    hypothesis_document = _read_bound_json_artifact(
        evidence,
        hypothesis_artifact,
        evidence_digests,
        failures,
        f"hypothesis_artifact:{run_id}",
    )
    derived_unresolved: list[str] | None = None
    if hypothesis_document is not None:
        expected_keys = {
            "schema_version", "run_id", "root_thread_id", "unresolved_hypothesis_ids",
        }
        candidate = hypothesis_document.get("unresolved_hypothesis_ids")
        if (
            set(hypothesis_document) != expected_keys
            or hypothesis_document.get("schema_version") != "1.0"
            or hypothesis_document.get("run_id") != run_id
            or hypothesis_document.get("root_thread_id") != record["root_thread_id"]
            or root_counts is None
            or hypothesis_artifact["digest"]
            not in root_counts.get("user_message_digests", [])
            or not isinstance(candidate, list)
            or any(not isinstance(item, str) or not item for item in candidate)
            or len(candidate) != len(set(candidate))
        ):
            failures.append(f"hypothesis_artifact_nonconformant:{run_id}")
        else:
            derived_unresolved = candidate

    descendants_by_id = {str(item["thread_id"]): item for item in descendants}
    batch_thread_ids: list[str] = []
    targeted_hypotheses: list[str] = []
    full_review_count = 0
    seen_delegation_prompt_refs: set[str] = set()
    seen_delegation_prompt_digests: set[str] = set()
    for batch in batches:
        child_thread_id = str(batch["child_thread_id"])
        batch_thread_ids.append(child_thread_id)
        prompt_ref = str(batch["prompt_artifact"]["ref"])
        prompt_digest = str(batch["prompt_artifact"]["digest"])
        if (
            prompt_ref in seen_delegation_prompt_refs
            or prompt_digest in seen_delegation_prompt_digests
        ):
            failures.append(f"delegation_prompt_reused:{run_id}:{child_thread_id}")
            continue
        seen_delegation_prompt_refs.add(prompt_ref)
        seen_delegation_prompt_digests.add(prompt_digest)
        prompt_document = _read_bound_json_artifact(
            evidence,
            batch["prompt_artifact"],
            evidence_digests,
            failures,
            f"delegation_prompt_artifact:{run_id}:{child_thread_id}",
        )
        child = descendants_by_id.get(child_thread_id)
        if prompt_document is None or child is None:
            failures.append(f"delegation_prompt_nonconformant:{run_id}:{child_thread_id}")
            continue
        expected_keys = {
            "schema_version", "run_id", "child_thread_id", "delegation_scope",
            "hypothesis_ids", "evidence_refs",
        }
        scope = prompt_document.get("delegation_scope")
        hypotheses = prompt_document.get("hypothesis_ids")
        prompt_evidence = prompt_document.get("evidence_refs")
        valid_prompt_evidence = isinstance(prompt_evidence, list) and all(
            isinstance(item, Mapping)
            and set(item) == {"ref", "digest", "evidence_kind"}
            and isinstance(item.get("ref"), str)
            and isinstance(item.get("digest"), str)
            and isinstance(item.get("evidence_kind"), str)
            for item in prompt_evidence
        )
        if (
            set(prompt_document) != expected_keys
            or prompt_document.get("schema_version") != "1.0"
            or prompt_document.get("run_id") != run_id
            or prompt_document.get("child_thread_id") != child_thread_id
            or batch["prompt_artifact"]["digest"]
            not in native_observations_by_thread.get(child_thread_id, {}).get(
                "user_message_digests", []
            )
            or scope not in {"targeted_hypotheses", "full_review"}
            or not isinstance(hypotheses, list)
            or any(not isinstance(item, str) or not item for item in hypotheses)
            or len(hypotheses) != len(set(hypotheses))
            or not valid_prompt_evidence
            or {
                str(item["ref"]): (str(item["digest"]), str(item["evidence_kind"]))
                for item in prompt_evidence or []
            } != thread_evidence.get(child_thread_id, {})
            or (scope == "targeted_hypotheses" and not hypotheses)
            or (scope == "full_review" and hypotheses)
        ):
            failures.append(f"delegation_prompt_nonconformant:{run_id}:{child_thread_id}")
            continue
        if scope == "full_review":
            full_review_count += 1
        else:
            targeted_hypotheses.extend(hypotheses)

    duplicate_full_reviews = max(0, full_review_count - 1)
    root_evidence_by_digest = {
        digest: evidence_kind
        for digest, evidence_kind in thread_evidence.get(
            str(record["root_thread_id"]), {}
        ).values()
    }
    derived_shared: set[tuple[str, str]] = set()
    for child in descendants:
        for digest, evidence_kind in thread_evidence.get(
            str(child["thread_id"]), {}
        ).values():
            root_kind = root_evidence_by_digest.get(digest)
            if root_kind is None:
                continue
            if root_kind != evidence_kind:
                failures.append(f"shared_evidence_kind_mismatch:{run_id}:{digest}")
                continue
            derived_shared.add((digest, evidence_kind))
    declared_shared = observed["root_child_shared_evidence"]
    declared_shared_keys = {
        (str(item["digest"]), str(item["evidence_kind"])) for item in declared_shared
    }
    if (
        derived_unresolved is None
        or unresolved != derived_unresolved
        or len(batch_thread_ids) != len(set(batch_thread_ids))
        or set(batch_thread_ids) != set(descendants_by_id)
        or len(targeted_hypotheses) != len(set(targeted_hypotheses))
        or set(targeted_hypotheses) != set(unresolved)
        or observed["duplicate_full_review_delegations"] != duplicate_full_reviews
        or duplicate_full_reviews != 0
        or len(declared_shared) != len(declared_shared_keys)
        or declared_shared_keys != derived_shared
    ):
        failures.append(f"delegation_hypothesis_nonconformant:{run_id}")
    if arm_id == "minimum_matrix_risk_delegation":
        expected_events = len(batches) if unresolved else 0
        if (
            (unresolved and not batches)
            or full_review_count
            or observed["delegation_event_count"] != expected_events
        ):
            failures.append(f"risk_triggered_delegation_nonconformant:{run_id}")
    elif arm_id == "minimum_matrix_inline" and (unresolved or batches):
        failures.append(f"inline_matrix_hypothesis_nonconformant:{run_id}")
    elif protocol.get("experiment_kind", "routing_ablation") == "routing_ablation" and (
        unresolved or targeted_hypotheses
    ):
        failures.append(f"routing_hypothesis_observation_nonconformant:{run_id}")
    if conformance["forbid_recursive_discovery"] and observed[
        "recursive_discovery_count"
    ]:
        failures.append(f"recursive_discovery_nonconformant:{run_id}")
    if (
        observed["read_path_capture_status"] == "not_exposed"
        and observed["observed_read_paths"]
    ):
        failures.append(f"unexposed_read_paths_present:{run_id}")
    for observed_path in observed["observed_read_paths"]:
        if not _path_is_allowed(str(observed_path), conformance["allowed_read_roots"]):
            failures.append(f"read_scope_nonconformant:{run_id}:{observed_path}")


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _blind_forbidden_identities(
    record: Mapping[str, Any], protocol: Mapping[str, Any]
) -> list[str]:
    """Build the blind classifier from the frozen protocol plus stable aliases."""

    identities = set(_BLIND_STABLE_SEMANTIC_ALIASES)
    for field in ("run_id", "arm_id", "treatment_digest"):
        value = record.get(field)
        if isinstance(value, str) and value:
            identities.add(value)
    for arm in protocol.get("arms", []):
        if not isinstance(arm, Mapping):
            continue
        for field in ("arm_id", "name", "display_name", "variant", "treatment_digest"):
            value = arm.get(field)
            if isinstance(value, str) and value:
                identities.add(value)
    for planned in protocol.get("run_plan", []):
        if not isinstance(planned, Mapping):
            continue
        value = planned.get("run_id")
        if isinstance(value, str) and value:
            identities.add(value)
    return sorted(identities)


def _audit_blind_review(
    record: Mapping[str, Any],
    *,
    entry: Mapping[str, Any],
    protocol: Mapping[str, Any],
    evidence: _EvidenceBudget,
    evidence_digests: dict[str, str],
    failures: list[str],
    schema_root: Path,
    seen_labels: set[str],
    seen_material_refs: set[str],
    seen_material_digests: set[str],
) -> dict[str, Any] | None:
    """Replay one opaque assignment -> frozen score -> reveal chain."""

    run_id = str(record["run_id"])
    failure_count = len(failures)
    chain = record.get("blind_review")
    if not isinstance(chain, Mapping) or entry.get("blind_review") != chain:
        failures.append(f"blind_review_chain_binding_mismatch:{run_id}")
        return None
    loaded: dict[str, tuple[Mapping[str, Any], bytes, Mapping[str, Any]]] = {}
    for role, schema_name in (
        ("assignment", "blind-assignment.schema.json"),
        ("score", "blind-score.schema.json"),
        ("reveal", "blind-reveal.schema.json"),
    ):
        artifact = chain.get(f"{role}_artifact")
        if not isinstance(artifact, Mapping):
            failures.append(f"blind_{role}_missing:{run_id}")
            return None
        raw = evidence.read_bytes_limited(MAX_DERIVED_CACHE_ENTRY_BYTES, str(artifact["ref"]))
        raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        evidence_digests[str(artifact["ref"])] = raw_digest
        if raw_digest != artifact["digest"]:
            failures.append(f"blind_{role}_digest_mismatch:{run_id}")
        try:
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError
            validate_instance(
                value, load_json(schema_root / schema_name),
                f"canary-blind-{role}:{run_id}",
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationFailure):
            failures.append(f"blind_{role}_nonconformant:{run_id}")
            return None
        loaded[role] = (value, raw, artifact)

    assignment, assignment_raw, assignment_artifact = loaded["assignment"]
    score, score_raw, score_artifact = loaded["score"]
    reveal, _reveal_raw, reveal_artifact = loaded["reveal"]
    labels = {assignment["opaque_label"], score["opaque_label"], reveal["opaque_label"]}
    label = str(assignment["opaque_label"])
    if len(labels) != 1 or label in seen_labels:
        failures.append(f"blind_opaque_label_reused_or_mismatched:{run_id}")
    seen_labels.add(label)

    outcome_artifact = record.get("outcome_artifact")
    outcome = (
        _read_bound_json_artifact(
            evidence, outcome_artifact, evidence_digests, failures,
            f"blind_outcome:{run_id}",
        )
        if isinstance(outcome_artifact, Mapping) else None
    )
    if not isinstance(outcome, Mapping) or outcome.get("blind_review") != chain:
        failures.append(f"blind_outcome_chain_binding_mismatch:{run_id}")
        return None
    outcome_fact = {
        key: value for key, value in outcome.items()
        if key not in {"raw_receipts", "blind_review"}
    }
    expected_reveal = {
        "experiment_id": record["experiment_id"],
        "opaque_label": label,
        "run_id": run_id,
        "arm_id": record["arm_id"],
        "treatment_digest": record["treatment_digest"],
        "outcome_fact_digest": canonical_digest(outcome_fact),
        "assignment_raw_digest": assignment_artifact["digest"],
        "assignment_canonical_digest": canonical_digest(assignment),
        "score_raw_digest": score_artifact["digest"],
        "score_canonical_digest": canonical_digest(score),
    }
    if (
        assignment.get("experiment_id") != record["experiment_id"]
        or score.get("experiment_id") != record["experiment_id"]
        or any(reveal.get(key) != value for key, value in expected_reveal.items())
    ):
        failures.append(f"blind_reveal_binding_mismatch:{run_id}")
    try:
        assigned = datetime.fromisoformat(str(assignment["assigned_at"]).replace("Z", "+00:00"))
        frozen = datetime.fromisoformat(str(score["frozen_at"]).replace("Z", "+00:00"))
        revealed = datetime.fromisoformat(str(reveal["revealed_at"]).replace("Z", "+00:00"))
        if not assigned < frozen < revealed:
            failures.append(f"blind_review_timing_invalid:{run_id}")
    except (ValueError, TypeError):
        failures.append(f"blind_review_timing_invalid:{run_id}")

    asset = assignment["asset_artifact"]
    rubric = assignment["rubric_artifact"]
    if (
        score["asset_digest"] != asset["digest"]
        or score["rubric_digest"] != rubric["digest"]
        or rubric != protocol["quality_rubric_artifact"]
        or _evidence_digest(evidence, str(asset["ref"]), evidence_digests) != asset["digest"]
        or _evidence_digest(evidence, str(rubric["ref"]), evidence_digests) != rubric["digest"]
    ):
        failures.append(f"blind_review_asset_or_rubric_mismatch:{run_id}")
    asset_payload: bytes | None = None
    deliverable_capture = outcome.get("deliverable_capture")
    deliverable_artifact = (
        deliverable_capture.get("artifact")
        if isinstance(deliverable_capture, Mapping)
        else None
    )
    try:
        asset_payload = evidence.read_bytes_limited(
            MAX_DERIVED_CACHE_ENTRY_BYTES, str(asset["ref"])
        )
        deliverable_payload = (
            evidence.read_bytes_limited(
                MAX_DERIVED_CACHE_ENTRY_BYTES, str(deliverable_artifact["ref"])
            )
            if isinstance(deliverable_artifact, Mapping)
            else None
        )
        if (
            deliverable_payload is None
            or asset_payload != deliverable_payload
            or asset["digest"] != deliverable_artifact.get("digest")
            or "sha256:" + hashlib.sha256(deliverable_payload).hexdigest()
            != deliverable_artifact.get("digest")
        ):
            failures.append(f"blind_asset_deliverable_binding_mismatch:{run_id}")
    except (KeyError, TypeError, ValidationFailure):
        failures.append(f"blind_asset_deliverable_binding_mismatch:{run_id}")

    executor_ids = {
        str(item["thread_id"]) for item in record["usage"]["threads"]
    }
    assignment_session = str(assignment["assignment_session_id"])
    evaluator_session = str(score["evaluator_session_id"])
    reveal_session = str(reveal["reveal_session_id"])
    review_sessions = {assignment_session, evaluator_session, reveal_session}
    if len(review_sessions) != 3 or review_sessions & executor_ids:
        failures.append(f"blind_reviewer_session_not_isolated:{run_id}")

    forbidden = _blind_forbidden_identities(record, protocol)
    try:
        frozen_strings = [
            *_bounded_blind_strings(assignment),
            *_bounded_blind_strings(score),
        ]
    except ValueError:
        failures.append(f"blind_review_material_scan_invalid:{run_id}")
        frozen_strings = []
    transcript_observations: dict[str, Mapping[str, Any]] = {}
    for transcript_key, expected_session in (
        ("assignment_transcript_artifact", assignment_session),
        ("evaluator_transcript_artifact", evaluator_session),
    ):
        owner = assignment if transcript_key.startswith("assignment") else score
        artifact = owner[transcript_key]
        raw = evidence.read_bytes_limited(
            MAX_DERIVED_CACHE_ENTRY_BYTES, str(artifact["ref"])
        )
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        evidence_digests[str(artifact["ref"])] = digest
        if digest != artifact["digest"]:
            failures.append(f"blind_transcript_digest_mismatch:{run_id}")
        observation = _blind_transcript_observation(
            raw, expected_session, frozen
        )
        if observation is None:
            failures.append(f"blind_transcript_provenance_invalid:{run_id}")
            continue
        transcript_observations[transcript_key] = observation
        frozen_strings.extend(observation["strings"])

    evaluator_observation = transcript_observations.get(
        "evaluator_transcript_artifact"
    )
    if evaluator_observation is not None and not any(
        all(
            expected in prompt
            for expected in (label, str(asset["digest"]), str(rubric["digest"]))
        )
        for prompt in evaluator_observation["user_prompts"]
    ):
        failures.append(f"blind_transcript_access_binding_invalid:{run_id}")

    try:
        if asset_payload is None:
            raise ValueError("blind asset is unavailable")
        frozen_strings.extend(_bounded_blind_payload_strings(asset_payload))
    except (UnicodeDecodeError, ValueError):
        failures.append(f"blind_review_asset_scan_invalid:{run_id}")
    if _blind_identity_leak(frozen_strings, forbidden):
        failures.append(f"blind_identity_leak_before_freeze:{run_id}")

    material = [
        assignment_artifact, score_artifact, reveal_artifact,
        assignment["asset_artifact"], assignment["assignment_transcript_artifact"],
        score["evaluator_transcript_artifact"],
    ]
    refs = {str(item["ref"]) for item in material}
    digests = {str(item["digest"]) for item in material}
    if refs & seen_material_refs or digests & seen_material_digests:
        failures.append(f"blind_review_material_reused:{run_id}")
    seen_material_refs.update(refs)
    seen_material_digests.update(digests)

    if len(failures) != failure_count:
        return None
    return {
        "run_id": run_id,
        "opaque_label": label,
        "assignment_raw_digest": assignment_artifact["digest"],
        "assignment_canonical_digest": canonical_digest(assignment),
        "score_raw_digest": score_artifact["digest"],
        "score_canonical_digest": canonical_digest(score),
        "reveal_raw_digest": reveal_artifact["digest"],
        "outcome_fact_digest": canonical_digest(outcome_fact),
        "evaluator_session_id": evaluator_session,
        "quality_score": score["quality_score"],
        "blind_blocker_count": score["blind_blocker_count"],
        "blind_major_count": score["blind_major_count"],
    }


def _blind_transcript_observation(
    raw: bytes, expected_session_id: str, frozen_at: datetime
) -> dict[str, Any] | None:
    sessions: list[tuple[Any, Any]] = []
    strings: list[str] = []
    user_prompts: list[str] = []
    try:
        for index, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            if index > MAX_BLIND_JSONL_EVENTS:
                return None
            event = json.loads(line)
            if not isinstance(event, dict):
                return None
            strings.extend(_bounded_blind_strings(event))
            at = datetime.fromisoformat(str(event["at"]).replace("Z", "+00:00"))
            if at >= frozen_at:
                return None
            payload = event.get("payload", {})
            if event.get("type") == "session_meta" and isinstance(payload, dict):
                sessions.append((payload.get("id"), payload.get("parent_thread_id")))
            elif (
                event.get("type") == "response_item"
                and isinstance(payload, Mapping)
                and payload.get("type") == "message"
                and payload.get("role") == "user"
            ):
                prompt = _message_text(payload.get("content"))
                if prompt is None:
                    return None
                user_prompts.append(prompt)
    except (
        KeyError, UnicodeDecodeError, ValueError, TypeError,
        json.JSONDecodeError, RecursionError,
    ):
        return None
    if sessions != [(expected_session_id, None)]:
        return None
    return {"strings": strings, "user_prompts": user_prompts}


def _bounded_blind_strings(value: Any) -> list[str]:
    """Collect JSON keys and string values with explicit shape/size bounds."""

    result: list[str] = []
    total_chars = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_BLIND_JSON_DEPTH:
            raise ValueError("blind JSON nesting exceeds limit")
        if isinstance(current, str):
            total_chars += len(current)
            if (
                len(result) >= MAX_BLIND_STRING_FIELDS
                or total_chars > MAX_BLIND_STRING_CHARS
            ):
                raise ValueError("blind JSON strings exceed limit")
            result.append(current)
        elif isinstance(current, Mapping):
            for key, item in current.items():
                stack.append((key, depth + 1))
                stack.append((item, depth + 1))
        elif isinstance(current, (list, tuple)):
            stack.extend((item, depth + 1) for item in current)
    return result


def _bounded_blind_payload_strings(raw: bytes) -> list[str]:
    text = raw.decode("utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        if len(text) > MAX_BLIND_STRING_CHARS:
            raise ValueError("blind text exceeds limit")
        return [text]
    return _bounded_blind_strings(value)


_BLIND_BASE64_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_/-])[A-Za-z0-9_-]{8,}={0,2}(?![A-Za-z0-9_/-])"
)
_BLIND_JSON_UNICODE_ESCAPE = re.compile(r"(?:\\u[0-9A-Fa-f]{4})+")


def _blind_identity_leak(values: Sequence[str], forbidden: Sequence[str]) -> bool:
    forbidden_tokens = {
        unicodedata.normalize("NFKC", token).casefold()
        for token in forbidden
        if token
    }
    try:
        for value in values:
            for decoded in _blind_decoded_forms(value):
                normalized = unicodedata.normalize("NFKC", decoded).casefold()
                if any(token in normalized for token in forbidden_tokens):
                    return True
    except (UnicodeError, ValueError):
        return True
    return False


def _blind_decoded_forms(value: str) -> set[str]:
    """Decode a bounded set of common wrappers; never recurse without limits."""

    initial = unicodedata.normalize("NFKC", value)
    forms = {initial}
    frontier = {initial}
    for depth in range(MAX_BLIND_DECODE_DEPTH):
        next_frontier: set[str] = set()
        for candidate in frontier:
            for transformed in _blind_one_layer_forms(candidate):
                if transformed != candidate and transformed not in forms:
                    next_frontier.add(transformed)
                    if len(forms) + len(next_frontier) > MAX_BLIND_DECODE_FORMS:
                        raise ValueError("blind decode expansion exceeds limit")
        if not next_frontier:
            break
        forms.update(next_frontier)
        frontier = next_frontier
        if depth == MAX_BLIND_DECODE_DEPTH - 1 and any(
            any(transformed != candidate for transformed in _blind_one_layer_forms(candidate))
            for candidate in frontier
        ):
            raise ValueError("blind decode depth exceeds limit")
    return forms


def _blind_one_layer_forms(value: str) -> set[str]:
    transformations = {
        unicodedata.normalize("NFKC", unquote(value)),
        unicodedata.normalize("NFKC", unquote_plus(value)),
        _decode_blind_json_unicode(value),
    }
    tokens = {value.strip(), *_BLIND_BASE64_TOKEN.findall(value)}
    for token in tokens:
        decoded = _decode_blind_base64(token)
        if decoded is not None:
            transformations.add(unicodedata.normalize("NFKC", decoded))
    return transformations


def _decode_blind_json_unicode(value: str) -> str:
    def decode(match: re.Match[str]) -> str:
        return "".join(
            chr(int(code, 16))
            for code in re.findall(r"\\u([0-9A-Fa-f]{4})", match.group(0))
        )

    return _BLIND_JSON_UNICODE_ESCAPE.sub(decode, value)


def _decode_blind_base64(value: str) -> str | None:
    if (
        len(value) < 8
        or len(value) > MAX_BLIND_BASE64_TOKEN_CHARS
        or re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value) is None
        or len(value.rstrip("=")) % 4 == 1
    ):
        return None
    unpadded = value.rstrip("=")
    padded = unpadded + "=" * ((-len(unpadded)) % 4)
    try:
        return base64.b64decode(
            padded.replace("-", "+").replace("_", "/"), validate=True
        ).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _audit_infrastructure_invalidation(
    entry: Mapping[str, Any],
    *,
    original: Mapping[str, Any],
    replacement: Mapping[str, Any],
    evidence: _EvidenceBudget,
    evidence_digests: dict[str, str],
    failures: list[str],
    schema_root: Path,
) -> Mapping[str, Any] | None:
    """Verify replacement authority from independent, replayable infrastructure facts."""

    run_id = str(original["run_id"])
    failure_count = len(failures)
    artifact = entry.get("invalidation_artifact")
    if not isinstance(artifact, Mapping):
        failures.append(f"replacement_invalidation_missing:{run_id}")
        return None
    invalidation = _read_bound_json_artifact(
        evidence,
        artifact,
        evidence_digests,
        failures,
        f"infrastructure_invalidation:{run_id}",
    )
    if invalidation is None:
        return None
    try:
        validate_instance(
            invalidation,
            load_json(schema_root / "infrastructure-invalidation.schema.json"),
            f"canary-infrastructure-invalidation:{run_id}",
        )
    except ValidationFailure:
        failures.append(f"infrastructure_invalidation_nonconformant:{run_id}")
        return None

    if invalidation["invalidated_run_id"] != run_id:
        failures.append(f"invalidation_run_binding_mismatch:{run_id}")
    outcome_artifact = original.get("outcome_artifact")
    expected_outcome_digest = (
        outcome_artifact.get("digest") if isinstance(outcome_artifact, Mapping) else None
    )
    if invalidation["invalidated_outcome_digest"] != expected_outcome_digest:
        failures.append(f"invalidation_outcome_digest_mismatch:{run_id}")
    if invalidation["decided_at"] != entry["decided_at"]:
        failures.append(f"invalidation_decision_time_mismatch:{run_id}")
    try:
        original_finished = datetime.fromisoformat(
            str(original["finished_at"]).replace("Z", "+00:00")
        )
        decision_time = datetime.fromisoformat(
            str(invalidation["decided_at"]).replace("Z", "+00:00")
        )
        replacement_started = datetime.fromisoformat(
            str(replacement["started_at"]).replace("Z", "+00:00")
        )
        if not original_finished < decision_time < replacement_started:
            failures.append(f"invalidation_timing_invalid:{run_id}")
    except (KeyError, ValueError, TypeError):
        failures.append(f"invalidation_timing_invalid:{run_id}")

    executor_ids = sorted(
        str(item["thread_id"])
        for item in original.get("usage", {}).get("threads", [])
        if isinstance(item, Mapping) and "thread_id" in item
    )
    reviewer_id = str(invalidation["reviewer_session_id"])
    if (
        invalidation["executor_session_ids"] != executor_ids
        or reviewer_id in executor_ids
        or reviewer_id == original.get("root_thread_id")
    ):
        failures.append(f"invalidation_reviewer_not_isolated:{run_id}")

    reviewer_artifact = invalidation["reviewer_session_artifact"]
    reviewer_ref = str(reviewer_artifact["ref"])
    reviewer_payload = evidence.read_bytes_limited(
        MAX_DERIVED_CACHE_ENTRY_BYTES, reviewer_ref
    )
    reviewer_digest = "sha256:" + hashlib.sha256(reviewer_payload).hexdigest()
    evidence_digests[reviewer_ref] = reviewer_digest
    if reviewer_digest != reviewer_artifact["digest"]:
        failures.append(f"invalidation_reviewer_artifact_digest_mismatch:{run_id}")
    reviewer_sessions: list[tuple[str, Any]] = []
    try:
        for raw_line in reviewer_payload.splitlines():
            if not raw_line.strip():
                continue
            event = json.loads(raw_line)
            payload = event.get("payload", {}) if isinstance(event, dict) else {}
            if event.get("type") == "session_meta" and isinstance(payload, dict):
                reviewer_sessions.append(
                    (str(payload.get("id", "")), payload.get("parent_thread_id"))
                )
    except (UnicodeDecodeError, json.JSONDecodeError):
        reviewer_sessions = []
    if reviewer_sessions != [(reviewer_id, None)]:
        failures.append(f"invalidation_reviewer_session_unverified:{run_id}")

    reason = str(invalidation["reason_code"])
    diagnostic_kinds = set()
    for diagnostic in invalidation["diagnostic_artifacts"]:
        diagnostic_kinds.add(str(diagnostic["diagnostic_kind"]))
        if _evidence_digest(
            evidence, str(diagnostic["ref"]), evidence_digests
        ) != diagnostic["digest"]:
            failures.append(f"invalidation_diagnostic_digest_mismatch:{run_id}")
    if diagnostic_kinds != {reason}:
        failures.append(f"invalidation_diagnostic_reason_mismatch:{run_id}")

    outcome = None
    if isinstance(outcome_artifact, Mapping):
        outcome = _read_bound_json_artifact(
            evidence,
            outcome_artifact,
            evidence_digests,
            failures,
            f"invalidation_outcome:{run_id}",
        )
    if not isinstance(outcome, Mapping):
        failures.append(f"invalidation_outcome_unverified:{run_id}")
    else:
        gate_failed = any(
            item.get("status") != "passed"
            or item.get("exit_code") != 0
            or item.get("timed_out") is not False
            for item in outcome.get("gate_outcomes", [])
            if isinstance(item, Mapping)
        )
        safety_count = outcome.get("safety", {}).get("count")
        quality_count = outcome.get("quality", {}).get("count")
        if gate_failed or safety_count != 0 or quality_count != 0:
            failures.append(f"replacement_disallowed_promotion_burden:{run_id}")
        if reason == "runner_crash" and outcome.get("process_exit_code") == 0:
            failures.append(f"runner_crash_without_failed_process:{run_id}")

    return invalidation if len(failures) == failure_count else None


def _audit_attempt_outcome(
    record: Mapping[str, Any],
    *,
    capture_contract: Mapping[str, Any] | None,
    platform_observation: Mapping[str, Any] | None,
    evidence: _EvidenceBudget,
    evidence_digests: dict[str, str],
    failures: list[str],
    schema_root: Path,
) -> None:
    """Derive one attempt fact from bound receipt bytes and compare every duplicate field."""

    run_id = str(record["run_id"])
    artifact = record["outcome_artifact"]
    outcome = _read_bound_json_artifact(
        evidence,
        artifact,
        evidence_digests,
        failures,
        f"outcome_artifact:{run_id}",
    )
    if outcome is None:
        return
    try:
        validate_instance(
            outcome,
            load_json(schema_root / "attempt-outcome.schema.json"),
            f"canary-attempt-outcome:{run_id}",
        )
    except ValidationFailure:
        failures.append(f"outcome_artifact_nonconformant:{run_id}")
        return
    capture = outcome["deliverable_capture"]
    capture_kind = str(capture["capture_kind"])
    if (
        capture_contract is None
        or capture_kind != capture_contract.get("capture_kind")
    ):
        failures.append(f"deliverable_capture_kind_mismatch:{run_id}")
    deliverable = capture["artifact"]
    observed_deliverable_digest = _evidence_digest(
        evidence, str(deliverable["ref"]), evidence_digests
    )
    if observed_deliverable_digest != deliverable["digest"]:
        failures.append(f"deliverable_capture_artifact_digest_mismatch:{run_id}")
    if capture_kind == "final_response":
        response_digests = (
            platform_observation.get("agent_message_digests", [])
            if isinstance(platform_observation, Mapping)
            else []
        )
        if (
            len(response_digests) != 1
            or not platform_observation.get("terminal_item_is_agent_message", False)
        ):
            failures.append(f"deliverable_final_response_not_unique:{run_id}")
        elif response_digests[0] != deliverable["digest"]:
            failures.append(f"deliverable_final_response_binding_mismatch:{run_id}")
    elif capture_kind in {"workspace_patch", "workspace_tree"}:
        failures.append(f"deliverable_capture_provenance_unavailable:{run_id}")
    receipt_artifact = outcome["raw_receipts"][0]
    receipt = _read_bound_json_artifact(
        evidence,
        receipt_artifact,
        evidence_digests,
        failures,
        f"outcome_receipt:{run_id}",
    )
    expected_receipt_keys = {"schema_version", "receipt_kind", "attempt_fact"}
    if (
        receipt is None
        or set(receipt) != expected_receipt_keys
        or receipt.get("schema_version") != "1.0"
        or receipt.get("receipt_kind") != "attempt_fact"
        or receipt.get("attempt_fact")
        != {key: value for key, value in outcome.items() if key != "raw_receipts"}
    ):
        failures.append(f"outcome_receipt_mismatch:{run_id}")
        return

    expected_bindings = {
        "run_id": record["run_id"],
        "protocol_digest": record["protocol_digest"],
        "workload_id": record["workload_id"],
        "workload_digest": record["workload_digest"],
        "arm_id": record["arm_id"],
        "treatment_digest": record["treatment_digest"],
        "process_exit_code": record["process_exit_code"],
    }
    if any(outcome[field] != value for field, value in expected_bindings.items()):
        failures.append(f"outcome_run_binding_mismatch:{run_id}")
    expected_gates = [
        {
            "gate_id": item["gate_id"],
            "status": item["status"],
            "exit_code": item["exit_code"],
            "timed_out": item["timed_out"],
        }
        for item in record["gate_receipts"]
    ]
    if outcome["gate_outcomes"] != expected_gates:
        failures.append(f"outcome_gate_mismatch:{run_id}")
    aggregate = record["usage"]["aggregate"]
    expected_usage = {
        "status": "collected",
        **{field: aggregate[field] for field in TOKEN_FIELDS},
        "wall_time_milliseconds": record["usage"]["wall_time_milliseconds"],
    }
    if outcome["usage"] != expected_usage:
        failures.append(f"outcome_usage_mismatch:{run_id}")
    if outcome["cost"] != record["billing"]:
        failures.append(f"outcome_cost_mismatch:{run_id}")
    expected_status = (
        "completed"
        if record["process_exit_code"] == 0
        and all(
            item["status"] == "passed"
            and item["exit_code"] == 0
            and not item["timed_out"]
            for item in record["gate_receipts"]
        )
        else "failed"
    )
    if outcome["attempt_status"] != expected_status:
        failures.append(f"outcome_status_mismatch:{run_id}")


def _path_is_allowed(value: str, roots: Sequence[str]) -> bool:
    if not _safe_relative_path(value):
        return False
    path = PurePosixPath(value)
    return any(path == PurePosixPath(root) or PurePosixPath(root) in path.parents for root in roots)


def _evidence_digest(
    evidence: _EvidenceBudget,
    reference: str,
    cache: dict[str, str],
) -> str:
    if reference in cache:
        return cache[reference]
    payload = evidence.read_bytes_limited(MAX_EVIDENCE_FILE_BYTES, reference)
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    cache[reference] = digest
    return digest


def _read_bound_json_artifact(
    evidence: _EvidenceBudget,
    artifact: Mapping[str, Any],
    digest_cache: dict[str, str],
    failures: list[str],
    label: str,
) -> Mapping[str, Any] | None:
    reference = str(artifact["ref"])
    observed_digest = digest_cache.get(reference)
    cached_entry = evidence.get_cached_derived(reference, "json_object")
    if cached_entry is not None:
        cached_digest, cached = cached_entry
        observed_digest = cached_digest
        digest_cache[reference] = cached_digest
        if observed_digest != artifact["digest"]:
            failures.append(f"{label}_digest_mismatch")
            return None
        if cached is _UNCACHEABLE_DERIVED:
            failures.append(f"{label}_uncacheable_reuse")
            return None
        if cached is _INVALID_DERIVED:
            failures.append(f"{label}_invalid_json")
            return None
        return cached
    # These artifacts are small control documents, not transcripts. Bound them
    # before json.loads so a compact JSON payload cannot expand into an
    # unbounded Python object on its first parse.
    payload = evidence.read_bytes_limited(MAX_DERIVED_CACHE_ENTRY_BYTES, reference)
    observed_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    digest_cache[reference] = observed_digest
    if observed_digest != artifact["digest"]:
        failures.append(f"{label}_digest_mismatch")
        return None
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        evidence.cache_derived(
            reference, "json_object", observed_digest, _INVALID_DERIVED, 1
        )
        failures.append(f"{label}_invalid_json")
        return None
    if not isinstance(document, Mapping):
        evidence.cache_derived(
            reference, "json_object", observed_digest, _INVALID_DERIVED, 1
        )
        failures.append(f"{label}_invalid_json")
        return None
    evidence.cache_derived(
        reference, "json_object", observed_digest, document, len(payload)
    )
    return document


def _thread_reaches_root(
    thread: Mapping[str, Any],
    threads: Sequence[Mapping[str, Any]],
    root_id: str,
) -> bool:
    parents = {str(item["thread_id"]): item["parent_thread_id"] for item in threads}
    current = str(thread["thread_id"])
    visited: set[str] = set()
    while current != root_id:
        if current in visited or current not in parents or parents[current] is None:
            return False
        visited.add(current)
        current = str(parents[current])
    return True


def _expected_session_links(
    thread_id: str, threads: Sequence[Mapping[str, Any]]
) -> set[tuple[str, str | None]]:
    parents = {str(item["thread_id"]): item["parent_thread_id"] for item in threads}
    result: set[tuple[str, str | None]] = set()
    visited: set[str] = set()
    current = thread_id
    while current in parents:
        if current in visited:
            return set()
        visited.add(current)
        parent = parents[current]
        result.add((current, None if parent is None else str(parent)))
        if parent is None:
            break
        current = str(parent)
    return result


ACTIVE_RUNTIME_TOOLS = frozenset(
    {
        "engineering_assistant_start",
        "engineering_assistant_next",
        "engineering_assistant_complete",
        "engineering_assistant_quality_submit",
        "engineering_assistant_provider_invoke",
        "engineering_assistant_evidence_import",
        "engineering_assistant_approval_import",
        "engineering_assistant_investigation_propose",
        "engineering_assistant_investigation_list",
        "engineering_assistant_investigation_approval_import",
        "engineering_assistant_investigation_start",
        "engineering_assistant_investigation_finish",
    }
)


def _read_transcript_observation(
    evidence: _EvidenceBudget,
    reference: str,
    *,
    parser_role: str,
    plugin_root: Path | None = None,
    plugin_skill_digests: Mapping[str, Any] | None = None,
    plugin_content_root: Path | None = None,
) -> tuple[str, dict[str, Any] | None]:
    cached_entry = evidence.get_cached_derived(reference, parser_role)
    if cached_entry is not None:
        digest, cached = cached_entry
        if cached is _INVALID_DERIVED or cached is _UNCACHEABLE_DERIVED:
            return digest, None
        return digest, cached

    payload = evidence.read_bytes_limited(MAX_EVIDENCE_FILE_BYTES, reference)
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if parser_role == "codex_export":
        observation = _derive_codex_counts(
            payload,
            plugin_root=plugin_root,
            plugin_skill_digests=plugin_skill_digests,
            plugin_content_root=plugin_content_root,
            evidence_budget=evidence,
        )
    elif parser_role == "codex_native":
        observation = _derive_native_codex_observation(
            payload, evidence_budget=evidence
        )
    else:
        raise ValueError(f"unsupported transcript parser role: {parser_role}")

    if observation is None:
        evidence.cache_derived(
            reference, parser_role, digest, _INVALID_DERIVED, 1
        )
        return digest, None
    try:
        derived_bytes = len(
            json.dumps(
                observation,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError):
        derived_bytes = MAX_DERIVED_CACHE_ENTRY_BYTES + 1
    evidence.cache_derived(
        reference, parser_role, digest, observation, derived_bytes
    )
    return digest, observation


def _derive_codex_counts(
    payload: bytes,
    *,
    plugin_root: Path | None = None,
    plugin_skill_digests: Mapping[str, Any] | None = None,
    plugin_content_root: Path | None = None,
    evidence_budget: _EvidenceBudget | None = None,
) -> dict[str, Any] | None:
    counts: dict[str, Any] = {
        "route_call_count": 0,
        "active_runtime_call_count": 0,
        "other_engineering_assistant_call_count": 0,
        "recursive_discovery_count": 0,
        "loaded_skill_ids": set(),
        "root_usage": None,
        "thread_id": None,
        "user_message_digests": set(),
        "agent_message_digests": [],
        "terminal_item_is_agent_message": False,
    }
    try:
        lines = io.BytesIO(payload)
        for raw_line in lines:
            if not raw_line.strip():
                continue
            if evidence_budget is not None:
                evidence_budget.consume_event()
            event = json.loads(raw_line)
            if not isinstance(event, dict):
                return None
            event_type = event.get("type")
            if event_type == "thread.started":
                thread_id = event.get("thread_id")
                if not isinstance(thread_id, str):
                    return None
                if counts["thread_id"] not in (None, thread_id):
                    return None
                counts["thread_id"] = thread_id
                continue
            if event_type == "turn.completed":
                usage = event.get("usage")
                if not isinstance(usage, dict) or any(
                    not isinstance(usage.get(field), int) or isinstance(usage.get(field), bool)
                    for field in TOKEN_FIELDS
                ):
                    return None
                if counts["root_usage"] is None:
                    counts["root_usage"] = {field: 0 for field in TOKEN_FIELDS}
                for field in TOKEN_FIELDS:
                    counts["root_usage"][field] += usage[field]
                continue
            if event_type != "item.completed":
                continue
            item = event.get("item", event)
            if not isinstance(item, dict):
                continue
            counts["terminal_item_is_agent_message"] = (
                item.get("type") == "agent_message"
            )
            if item.get("type") == "user_message" and isinstance(
                item.get("content"), str
            ):
                counts["user_message_digests"].add(
                    "sha256:"
                    + hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
                )
                continue
            if item.get("type") == "agent_message" and isinstance(
                item.get("content"), str
            ):
                counts["agent_message_digests"].append(
                    "sha256:"
                    + hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
                )
                continue
            tool = item.get("tool") or item.get("tool_name") or item.get("name")
            server = item.get("server")
            if isinstance(tool, str):
                normalized = tool.split("__")[-1]
                is_engineering_assistant = (
                    server == "engineering-assistant"
                    or normalized.startswith("engineering_assistant_")
                )
                if is_engineering_assistant:
                    if normalized == "engineering_assistant_route":
                        counts["route_call_count"] += 1
                    elif normalized in ACTIVE_RUNTIME_TOOLS:
                        counts["active_runtime_call_count"] += 1
                    else:
                        counts["other_engineering_assistant_call_count"] += 1
            command = item.get("command")
            if isinstance(command, str):
                counts["loaded_skill_ids"].update(
                    _verified_skill_reads(
                        item,
                        plugin_root=plugin_root,
                        plugin_skill_digests=plugin_skill_digests,
                        plugin_content_root=plugin_content_root,
                    )
                )
                if re.search(
                    r"(?:^|[\s;&|])(?:rg\b[^\n;&|]*\s--files\b|find\s+|git\s+ls-files\b)",
                    command,
                ):
                    counts["recursive_discovery_count"] += 1
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    counts["loaded_skill_ids"] = sorted(counts["loaded_skill_ids"])
    counts["user_message_digests"] = sorted(counts["user_message_digests"])
    return counts


def _verified_skill_reads(
    item: Mapping[str, Any],
    *,
    plugin_root: Path | None,
    plugin_skill_digests: Mapping[str, Any] | None,
    plugin_content_root: Path | None,
) -> set[str]:
    if item.get("status") != "completed" or item.get("exit_code") != 0:
        return set()
    command = item.get("command")
    output = item.get("aggregated_output")
    if not isinstance(command, str) or not isinstance(output, str):
        return set()
    try:
        outer = shlex.split(command)
    except ValueError:
        return set()
    if (
        len(outer) == 3
        and PurePosixPath(outer[0]).name in {"sh", "bash", "zsh"}
        and outer[1] == "-lc"
    ):
        script = outer[2]
    else:
        script = command
    if plugin_root is None or plugin_skill_digests is None or not plugin_root.is_absolute():
        return set()
    skill_ids: list[str] = []
    for segment in re.split(r"\s*(?:;|&&|\n)\s*", script):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            return set()
        if not tokens:
            continue
        executable = PurePosixPath(tokens[0]).name
        if executable == "wc" and len(tokens) >= 3 and tokens[1] == "-l":
            if not all(
                re.fullmatch(r"/?(?:[^/]+/)*skills/([^/]+)/SKILL\.md", path)
                for path in tokens[2:]
            ):
                return set()
            continue
        if executable == "sed" and len(tokens) == 4 and tokens[1] == "-n":
            path = tokens[3]
        elif executable == "cat" and len(tokens) == 2:
            path = tokens[1]
        else:
            return set()
        match = re.fullmatch(r"/?(?:[^/]+/)*skills/([^/]+)/SKILL\.md", path)
        if match is None:
            return set()
        skill_id = match.group(1)
        expected_path = plugin_root / "skills" / skill_id / "SKILL.md"
        if Path(path) != expected_path:
            return set()
        skill_ids.append(skill_id)
    declared_names = set(re.findall(r"(?m)^name:\s*([a-z0-9][a-z0-9-]*)\s*$", output))
    if not skill_ids or not set(skill_ids).issubset(declared_names):
        return set()
    content_root = plugin_content_root or plugin_root
    plugin_io = ArtifactIO(content_root, ".")
    try:
        for skill_id in skill_ids:
            relative = f"skills/{skill_id}/SKILL.md"
            payload = plugin_io.read_bytes_limited(1024 * 1024, relative)
            observed_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
            if plugin_skill_digests.get(skill_id) != observed_digest:
                return set()
            try:
                full_text = payload.decode("utf-8")
            except UnicodeDecodeError:
                return set()
            if full_text not in output:
                return set()
    finally:
        plugin_io.close()
    return set(skill_ids)


def _derive_native_codex_observation(
    payload: bytes, *, evidence_budget: _EvidenceBudget | None = None
) -> dict[str, Any] | None:
    observed: dict[str, Any] = {
        "session_links": [],
        "root_usage": None,
        "route_call_count": 0,
        "active_runtime_call_count": 0,
        "other_engineering_assistant_call_count": 0,
        "recursive_discovery_count": 0,
        "loaded_skill_ids": [],
        "unverified_skill_read": False,
        "user_message_digests": set(),
    }
    try:
        lines = io.BytesIO(payload)
        for raw_line in lines:
            if not raw_line.strip():
                continue
            if evidence_budget is not None:
                evidence_budget.consume_event()
            event = json.loads(raw_line)
            if not isinstance(event, dict):
                return None
            if not _consume_native_event(observed, event):
                return None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    observed["user_message_digests"] = sorted(observed["user_message_digests"])
    return observed


def _consume_native_event(observed: dict[str, Any], event: Mapping[str, Any]) -> bool:
    if event.get("type") == "session_meta":
        metadata = event.get("payload")
        if not isinstance(metadata, dict):
            return False
        thread_id = metadata.get("id")
        parent_thread_id = metadata.get("parent_thread_id")
        if not isinstance(thread_id, str) or not (
            isinstance(parent_thread_id, str) or parent_thread_id is None
        ):
            return False
        observed["session_links"].append((thread_id, parent_thread_id))
        return True
    event_payload = event.get("payload")
    if event.get("type") == "response_item" and isinstance(event_payload, dict):
        payload_type = event_payload.get("type")
        if payload_type == "message" and event_payload.get("role") == "user":
            message_text = _message_text(event_payload.get("content"))
            if message_text is not None:
                observed["user_message_digests"].add(
                    "sha256:" + hashlib.sha256(message_text.encode("utf-8")).hexdigest()
                )
        elif payload_type == "function_call":
            _count_engineering_assistant_tool(
                observed,
                event_payload.get("name"),
                event_payload.get("namespace"),
            )
        elif payload_type == "custom_tool_call" and event_payload.get("status") == "completed":
            tool_input = event_payload.get("input")
            if isinstance(tool_input, str):
                for tool in re.findall(
                    r"tools\.(mcp__engineering_assistant__engineering_assistant_[a-zA-Z0-9_]+)",
                    tool_input,
                ):
                    _count_engineering_assistant_tool(observed, tool, None)
                command_match = re.search(
                    r"\bcmd:\s*(\"(?:\\.|[^\"\\])*\")", tool_input
                )
                if command_match is not None:
                    try:
                        command = json.loads(command_match.group(1))
                    except json.JSONDecodeError:
                        command = ""
                    if isinstance(command, str):
                        if re.search(
                            r"(?:^|[\s;&|])(?:rg\b[^\n;&|]*\s--files\b|find\s+|git\s+ls-files\b)",
                            command,
                        ):
                            observed["recursive_discovery_count"] += 1
                        if "/skills/" in command and "/SKILL.md" in command:
                            observed["unverified_skill_read"] = True
        return True
    if event.get("type") != "event_msg":
        return True
    if not isinstance(event_payload, dict) or event_payload.get("type") != "token_count":
        return True
    info = event_payload.get("info")
    usage = info.get("total_token_usage") if isinstance(info, dict) else None
    if not isinstance(usage, dict) or any(
        not isinstance(usage.get(field), int) or isinstance(usage.get(field), bool)
        for field in TOKEN_FIELDS
    ):
        return True
    observed["root_usage"] = {field: usage[field] for field in TOKEN_FIELDS}
    return True


def _message_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or not content:
        return None
    parts: list[str] = []
    for item in content:
        if not isinstance(item, Mapping) or item.get("type") not in {
            "input_text", "text"
        } or not isinstance(item.get("text"), str):
            return None
        parts.append(str(item["text"]))
    return "".join(parts)


def _count_engineering_assistant_tool(
    counts: dict[str, Any], tool: Any, server: Any
) -> None:
    if not isinstance(tool, str):
        return
    normalized = tool.split("__")[-1]
    if server != "engineering-assistant" and not normalized.startswith(
        "engineering_assistant_"
    ):
        return
    if normalized == "engineering_assistant_route":
        counts["route_call_count"] += 1
    elif normalized in ACTIVE_RUNTIME_TOOLS:
        counts["active_runtime_call_count"] += 1
    else:
        counts["other_engineering_assistant_call_count"] += 1


def _aggregate_conformance_counts(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    aggregate: dict[str, Any] = {
        "route_call_count": 0,
        "active_runtime_call_count": 0,
        "other_engineering_assistant_call_count": 0,
        "recursive_discovery_count": 0,
        "loaded_skill_ids": set(),
        "root_usage": None,
    }
    for observation in observations:
        for field in (
            "route_call_count",
            "active_runtime_call_count",
            "other_engineering_assistant_call_count",
            "recursive_discovery_count",
        ):
            aggregate[field] += int(observation[field])
        aggregate["loaded_skill_ids"].update(observation["loaded_skill_ids"])
    aggregate["loaded_skill_ids"] = sorted(aggregate["loaded_skill_ids"])
    return aggregate


def _expected_exclusion_reasons(record_failures: Sequence[str]) -> set[str]:
    expected: set[str] = set()
    for failure in record_failures:
        if failure.startswith("gate_"):
            expected.add("standard_gate_failed")
        elif failure.startswith(
            (
                "usage_", "delegated_", "root_usage_", "thread_usage_",
                "descendant_native_", "native_transcript_", "thread_export_native_",
                "experiment_thread_artifact_",
            )
        ):
            expected.add("usage_attribution_incomplete")
        elif failure.startswith(("platform_", "thread_")):
            expected.add("transcript_incomplete")
        elif failure.startswith(
            (
                "route_", "skills_", "active_runtime_", "other_engineering_assistant_",
                "delegation_", "recursive_", "read_scope_", "transcript_count_",
                "derived_", "descendant_skill_",
            )
        ):
            expected.add("treatment_nonconformance")
        else:
            expected.add("protocol_nonconformant")
    return expected
