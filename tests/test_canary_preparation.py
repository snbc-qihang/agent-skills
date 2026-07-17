from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CANARY_BROKER_ID = "enterprise-evidence"
CANARY_HOST_CONFIG_DIGEST = "sha256:" + "c" * 64
IMPORT_TRUST = {
    "evidence_broker_id": CANARY_BROKER_ID,
    "host_trust_config_digest": CANARY_HOST_CONFIG_DIGEST,
}
VALIDATION_TRUST = {
    "expected_evidence_broker_id": CANARY_BROKER_ID,
    "expected_host_trust_config_digest": CANARY_HOST_CONFIG_DIGEST,
}

from engineering_assistant.artifact_io import ArtifactIO  # noqa: E402
from engineering_assistant import canary as canary_module  # noqa: E402
from engineering_assistant.canary import (  # noqa: E402
    import_canary_attestation,
    prepare_canary_bundle,
)
from engineering_assistant.canary_protocol import audit_canary_protocol, canonical_digest  # noqa: E402
from engineering_assistant.cli import build_parser  # noqa: E402
from engineering_assistant.eval_runner import (  # noqa: E402
    assemble_canary_result,
    run_canary_result,
)
from engineering_assistant.validation import ValidationFailure  # noqa: E402
from engineering_assistant.trust import (  # noqa: E402
    ExternalTrustVerifier,
    canary_observation_claims,
)
from tests import test_canary_protocol as canary_protocol_fixtures  # noqa: E402


class CanaryPreparationTests(unittest.TestCase):
    class CanaryVerifier:
        def verify_canary_observation(self, observation) -> bool:
            return observation.get("attestation") == "trusted-canary-receipt"

    class BrokerResponse:
        def __init__(self, claims: dict) -> None:
            self.payload = json.dumps(
                {"active": True, "claims": claims}
            ).encode("utf-8")
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            if size < 0:
                size = len(self.payload) - self.offset
            chunk = self.payload[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    def test_structured_canary_artifact_is_bounded_before_json_decode(self) -> None:
        payload = b'{"value":"' + (
            b"x" * canary_module.MAX_STRUCTURED_CANARY_ARTIFACT_BYTES
        ) + b'"}'
        with self.assertRaisesRegex(ValidationFailure, "structured JSON limit"):
            canary_module._json_artifact(payload, "protocol")

    def manifest(self, artifact: Path, **overrides) -> dict:
        digest = "sha256:" + "a" * 64
        run = {
            "experiment_kind": "paired_canary",
            "experiment_protocol_digest": digest,
            "arm_id": "candidate",
            "task_id": "task-1",
            "workload_digest": digest,
            "variant": "candidate",
            "git_ref": "candidate-ref",
            "treatment_digest": "sha256:" + "b" * 64,
            "execution_config_digest": digest,
            "environment_digest": digest,
            "quality_rubric_digest": digest,
            "evaluator_id": "independent-quality-evaluator",
            "started_at": "2026-07-14T00:00:00+00:00",
            "finished_at": "2026-07-14T00:10:00+00:00",
            "input_tokens": 100,
            "noncached_input_tokens": 20,
            "output_tokens": 20,
            "wall_time_milliseconds": 10_000,
            "cost_usd_micros": 250,
            "quality_score": 92.5,
            "document_noise_units": 8,
            "safety_violations": 0,
            "blind_blocker_count": 0,
            "blind_major_count": 0,
            "applicable_matrix_cells": 4,
            "closed_matrix_cells": 4,
            "production_contract_failures": 0,
            "artifact_paths": [artifact.name],
            "artifact_measurements": {
                artifact.name: [
                    "usage",
                    "timing",
                    "billing",
                    "quality_evaluation",
                    "document_noise",
                    "safety_audit",
                ]
            },
        }
        run.update(overrides)
        if "variant" in overrides and "arm_id" not in overrides:
            run["arm_id"] = run["variant"]
        if "artifact_paths" in overrides and "artifact_measurements" not in overrides:
            run["artifact_measurements"] = {
                path: [
                    "usage",
                    "timing",
                    "billing",
                    "quality_evaluation",
                    "document_noise",
                    "safety_audit",
                ]
                for path in run["artifact_paths"]
            }
        return {
            "schema_version": "1.0",
            "product_repository": "ai-platform",
            "runs": [run],
        }

    def prepared_import_bundle(
        self,
        root: Path,
        payloads: list[bytes],
    ) -> tuple[Path, str, str]:
        sources = []
        for index, payload in enumerate(payloads):
            source = root / f"artifact-{index}.log"
            source.write_bytes(payload)
            sources.append(source)
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                self.manifest(
                    sources[0],
                    artifact_paths=[source.name for source in sources],
                )
            ),
            encoding="utf-8",
        )
        bundle = root / "bundle"
        report = prepare_canary_bundle(
            manifest,
            bundle,
            repository_root=ROOT,
            **IMPORT_TRUST,
        )
        draft_ref = report["draft_refs"][0]
        draft_path = bundle / draft_ref
        response_ref = "attestations/response.json"
        ArtifactIO(bundle, ".").create_immutable_json(
            {
                "schema_version": "1.0",
                "draft_digest": "sha256:"
                + hashlib.sha256(draft_path.read_bytes()).hexdigest(),
                "attestation": "trusted-canary-receipt",
            },
            *Path(response_ref).parts,
        )
        return bundle, draft_ref, response_ref

    def delegation_manifest(self, root: Path, measurement: Path) -> dict:
        digest = "sha256:" + "a" * 64
        def write_raw(name: str, payload: bytes) -> tuple[str, str]:
            path = root / name
            path.write_bytes(payload)
            return name, "sha256:" + hashlib.sha256(payload).hexdigest()

        treatments = {
            arm: "sha256:" + seed * 64
            for arm, seed in (
                ("minimum_matrix_inline", "1"),
                ("minimum_matrix_risk_delegation", "2"),
                ("full_local_control", "3"),
            )
        }
        prompt_refs = {
            arm: write_raw(f"prompt-{index}.txt", f"prompt {arm}\n".encode())
            for index, arm in enumerate(treatments, 1)
        }
        transcript_ref = write_raw("platform.jsonl", b'{"type":"turn.completed"}\n')
        stdout_ref = write_raw("gate.stdout", b"ok\n")
        stderr_ref = write_raw("gate.stderr", b"")
        hypothesis_ref = write_raw("hypotheses.json", b'{"hypotheses":[]}\n')
        protocol = {
            "schema_version": "1.0",
            "experiment_kind": "delegation_ablation",
            "experiment_id": "formal-exp",
            "product_repository": "ai-platform",
            "git_ref": "candidate-ref",
            "minimum_repeats": 2,
            "execution_config_digest": digest,
            "execution_config": {
                "model": "test-model", "reasoning_effort": "high",
                "sandbox_mode": "workspace-write", "approval_policy": "never",
                "network_policy": "disabled", "plugin_payload_digest": digest,
                "prompt_digest": digest, "cli_argv": ["codex", "exec"],
            },
            "environment_digest": digest,
            "quality_rubric_digest": digest,
            "order_policy": "interleaved_blocks",
            "randomization_seed_digest": digest,
            "required_gate_ids": ["tests"],
            "gate_specs": [{"gate_id": "tests", "argv": ["test"], "cwd": "."}],
            "workloads": [{"workload_id": "workload-1", "workload_digest": digest}],
            "arms": [
                {
                    "arm_id": arm,
                    "prompt_digest": prompt_refs[arm][1],
                    "treatment_digest": treatment,
                    "conformance": {
                        "minimum_route_calls": 0, "maximum_route_calls": 1,
                        "required_skill_ids": [], "allowed_skill_ids": [],
                        "maximum_active_runtime_calls": 0,
                        "maximum_other_engineering_assistant_calls": 0,
                        "delegation_policy": "allowed" if arm == "minimum_matrix_risk_delegation" else "forbidden",
                        "allowed_read_roots": ["."], "forbid_recursive_discovery": True
                    },
                }
                for arm, treatment in treatments.items()
            ],
            "run_plan": [
                {
                    "run_id": f"run-{arm}-{repeat}",
                    "workload_id": "workload-1",
                    "repeat_index": repeat,
                    "arm_id": arm,
                    "planned_order": order,
                    "plan_role": "primary",
                }
                for order, (repeat, arm) in enumerate(
                    ((repeat, arm) for repeat in (1, 2) for arm in treatments), 1
                )
            ],
        }
        protocol_path = root / "protocol.json"
        protocol_path.write_bytes(ArtifactIO.canonical_json_bytes(protocol))
        protocol_digest = "sha256:" + hashlib.sha256(protocol_path.read_bytes()).hexdigest()
        bindings = []
        record_paths = []
        for order, (arm, treatment) in enumerate(treatments.items(), 1):
            record = {
                "schema_version": "1.0",
                "evidence_status": "local_structural",
                "run_id": f"run-{arm}-1",
                "experiment_id": "formal-exp",
                "workload_id": "workload-1",
                "repeat_index": 1,
                "arm_id": arm,
                "protocol_digest": protocol_digest,
                "workload_digest": digest,
                "actual_start_order": order,
                "started_at": "2026-07-14T00:00:00+00:00",
                "finished_at": "2026-07-14T00:01:00+00:00",
                "process_exit_code": 0,
                "product_repository": "ai-platform",
                "git_ref": "candidate-ref",
                "treatment_digest": treatment,
                "prompt_digest": prompt_refs[arm][1],
                "prompt_artifact": {"ref": prompt_refs[arm][0], "digest": prompt_refs[arm][1]},
                "execution_config_digest": digest,
                "environment_digest": digest,
                "quality_rubric_digest": digest,
                "root_thread_id": "root",
                "platform_transcript": {"ref": transcript_ref[0], "digest": transcript_ref[1], "complete": True},
                "gate_receipts": [{
                    "gate_id": "tests", "argv": ["test"], "cwd": ".",
                    "command_digest": digest,
                    "started_at": "2026-07-14T00:00:00+00:00",
                    "finished_at": "2026-07-14T00:00:01+00:00",
                    "wall_time_milliseconds": 1000, "exit_code": 0,
                    "timed_out": False, "status": "passed",
                    "stdout_ref": stdout_ref[0], "stdout_digest": stdout_ref[1],
                    "stderr_ref": stderr_ref[0], "stderr_digest": stderr_ref[1],
                }],
                "usage": {
                    "aggregation_semantics": "root_inclusive", "coverage": "root_only",
                    "complete": True, "delegation_event_count": 0,
                    "threads": [{
                        "thread_id": "root", "parent_thread_id": None, "role": "root",
                        "transcript_ref": transcript_ref[0], "transcript_digest": transcript_ref[1],
                        "evidence_refs": [], "complete": True,
                        "input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1,
                    }],
                    "aggregate": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1},
                    "wall_time_milliseconds": 1000,
                },
                "treatment_observation": {
                    "route_call_count": 0, "loaded_skill_ids": [],
                    "active_runtime_call_count": 0, "other_engineering_assistant_call_count": 0,
                    "delegation_event_count": 0, "recursive_discovery_count": 0,
                    "read_path_capture_status": "not_exposed", "observed_read_paths": [],
                    "evidence_binding_version": "2.0",
                    "hypothesis_artifact": {"ref": hypothesis_ref[0], "digest": hypothesis_ref[1]},
                    "unresolved_hypothesis_ids": [], "delegation_hypothesis_batches": [],
                    "duplicate_full_review_delegations": 0, "root_child_shared_evidence": [],
                },
                "broker": {"status": "unavailable"},
                "billing": {"status": "not_collected"},
            }
            path = root / f"record-{arm}.json"
            path.write_bytes(ArtifactIO.canonical_json_bytes(record))
            record_paths.append(path.name)
            bindings.append(
                {
                    "run_id": record["run_id"],
                    "workload_id": record["workload_id"],
                    "repeat_index": record["repeat_index"],
                    "arm_id": arm,
                    "run_record_digest": "sha256:"
                    + hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        audit_path = root / "audit-report.json"
        audit_path.write_text(json.dumps({
            "status": "local_structural", "protocol_digest": protocol_digest, "failures": [],
            "included_run_bindings": [
                {
                    "run_id": binding["run_id"],
                    "run_record_digest": binding["run_record_digest"],
                }
                for binding in bindings
            ] + [{"run_id": "other-cell-run", "run_record_digest": "sha256:" + "f" * 64}],
        }), encoding="utf-8")
        raw_paths = sorted({
            *(item[0] for item in prompt_refs.values()), transcript_ref[0], stdout_ref[0],
            stderr_ref[0], hypothesis_ref[0],
        })
        payload = self.manifest(
            measurement,
            experiment_kind="delegation_ablation",
            experiment_protocol_digest=protocol_digest,
            arm_id="minimum_matrix_risk_delegation",
            ablation_run_bindings=bindings,
            treatment_digest=treatments["minimum_matrix_risk_delegation"],
            artifact_paths=[measurement.name, protocol_path.name, *record_paths, *raw_paths, audit_path.name],
        )
        run = payload["runs"][0]
        run["artifact_measurements"] = {
            measurement.name: [
                "usage", "timing", "billing", "quality_evaluation",
                "document_noise", "safety_audit",
            ],
            protocol_path.name: ["experiment_protocol"],
            **{path: ["run_record"] for path in record_paths},
            **{path: ["raw_run_evidence"] for path in raw_paths},
            audit_path.name: ["local_audit_report"],
        }
        return payload

    def audited_delegation_manifest(
        self, *, with_infrastructure_replacement: bool = False
    ) -> tuple[Path, Path, dict]:
        fixture = canary_protocol_fixtures.CanaryProtocolAuditTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.workloads = [fixture.workloads[0]]
        fixture.protocol["workloads"] = fixture.workloads
        fixture.protocol["product_repository"] = "ai-platform"
        fixture.protocol["gate_specs"] = fixture.protocol["gate_specs"][:1]
        fixture.protocol["required_gate_ids"] = [
            fixture.protocol["gate_specs"][0]["gate_id"]
        ]
        source_arms = {arm["arm_id"]: arm for arm in fixture.protocol["arms"]}
        arm_sources = {
            "minimum_matrix_inline": "minimum_skills",
            "minimum_matrix_risk_delegation": "full_local",
            "full_local_control": "full_local",
        }
        arms = []
        for arm_id, source_id in arm_sources.items():
            arm = json.loads(json.dumps(source_arms[source_id]))
            arm["arm_id"] = arm_id
            arm["conformance"]["delegation_policy"] = (
                "allowed" if arm_id == "minimum_matrix_risk_delegation" else
                ("required" if arm_id == "full_local_control" else "forbidden")
            )
            prompt = arm_id.replace("_only", "").replace(
                "minimum_skills", "minimum"
            ).replace("full_local", "full") + "-prompt"
            arm["prompt_digest"] = "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()
            arm["treatment_digest"] = canonical_digest(
                {
                    "arm_id": arm_id,
                    "prompt_digest": arm["prompt_digest"],
                    "conformance": arm["conformance"],
                }
            )
            arms.append(arm)
        fixture.protocol["experiment_kind"] = "delegation_ablation"
        fixture.protocol["arms"] = arms
        fixture.protocol["run_plan"] = [
            {
                "run_id": f"{workload['workload_id']}-{arm['arm_id']}-{repeat}",
                "workload_id": workload["workload_id"], "arm_id": arm["arm_id"],
                "repeat_index": repeat, "planned_order": order, "plan_role": "primary",
            }
            for order, (workload, arm, repeat) in enumerate(
                ((workload, arm, repeat) for workload in fixture.workloads for repeat in (1, 2) for arm in arms),
                1,
            )
        ]
        replacement_original_id = "w1-minimum_matrix_risk_delegation-1"
        replacement_id = replacement_original_id + "-replacement"
        if with_infrastructure_replacement:
            fixture.protocol["run_plan"].append({
                "run_id": replacement_id,
                "workload_id": "w1",
                "arm_id": "minimum_matrix_risk_delegation",
                "repeat_index": 1,
                "planned_order": 7,
                "plan_role": "replacement_spare",
                "replacement_for_run_id": replacement_original_id,
            })
        fixture.protocol_digest = canonical_digest(fixture.protocol)
        records = [
            fixture.record(workload, arm, repeat, billing_status="collected")
            for workload in fixture.workloads
            for arm in fixture.protocol["arms"]
            for repeat in (1, 2)
        ]
        replacement = None
        original = None
        if with_infrastructure_replacement:
            original = next(
                record for record in records if record["run_id"] == replacement_original_id
            )
            original["process_exit_code"] = 70
            fixture.rewrite_outcome(original)
            replacement = fixture.record(
                fixture.workloads[0],
                next(
                    arm for arm in fixture.protocol["arms"]
                    if arm["arm_id"] == "minimum_matrix_risk_delegation"
                ),
                1,
                run_id_override=replacement_id,
            )
            replacement["started_at"] = "2026-07-15T00:03:00Z"
            replacement["finished_at"] = "2026-07-15T00:03:01Z"
            records.append(replacement)
        inclusion = fixture.manifest(records)
        if with_infrastructure_replacement:
            fixture.add_infrastructure_invalidation(
                inclusion, original, replacement
            )
        audit = audit_canary_protocol(
            fixture.protocol, records, inclusion,
            schema_root=ROOT / "evals/canary", evidence_root=fixture.evidence_root,
        )
        self.assertEqual("local_structural", audit["status"], audit)
        self.assertEqual([], audit["failures"])
        self.assertEqual(len(records), len(audit["audited_run_bindings"]))

        root = fixture.evidence_root
        protocol_path = root / "protocol.json"
        protocol_path.write_bytes(ArtifactIO.canonical_json_bytes(fixture.protocol))
        inclusion_path = root / "inclusion.json"
        inclusion_path.write_bytes(ArtifactIO.canonical_json_bytes(inclusion))
        audit_path = root / "audit-report.json"
        audit_path.write_bytes(ArtifactIO.canonical_json_bytes(audit))
        record_paths = []
        raw_paths = set()
        for record in records:
            path = root / "formal-records" / f"{record['run_id']}.json"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(ArtifactIO.canonical_json_bytes(record))
            record_paths.append(path.relative_to(root).as_posix())
            raw_paths.update(self._record_raw_paths(record, root))
        if with_infrastructure_replacement:
            invalidation_entry = next(
                item for item in inclusion["entries"]
                if item["disposition"] == "replaced"
            )
            invalidation_ref = invalidation_entry["invalidation_artifact"]["ref"]
            invalidation = json.loads((root / invalidation_ref).read_text())
            raw_paths.add(invalidation_ref)
            raw_paths.add(invalidation["reviewer_session_artifact"]["ref"])
            raw_paths.update(
                item["ref"] for item in invalidation["diagnostic_artifacts"]
            )
        frozen_package_root = root / "formal-package-evidence"
        for source in sorted(path for path in fixture.plugin_root.rglob("*") if path.is_file()):
            frozen = frozen_package_root / source.relative_to(fixture.plugin_root)
            frozen.parent.mkdir(parents=True, exist_ok=True)
            frozen.write_bytes(source.read_bytes())
            raw_paths.add(frozen.relative_to(root).as_posix())
        measurement = root / "measurement.jsonl"
        measurement.write_text("{}\n", encoding="utf-8")
        selected = [
            item for item in audit["quality_cohort_bindings"]
            if item["workload_id"] == fixture.workloads[0]["workload_id"]
            and item["repeat_index"] == 1
        ]
        risk = next(arm for arm in arms if arm["arm_id"] == "minimum_matrix_risk_delegation")
        payload = self.manifest(
            measurement,
            experiment_kind="delegation_ablation",
            experiment_protocol_digest=fixture.protocol_digest,
            arm_id="minimum_matrix_risk_delegation",
            ablation_run_bindings=selected,
            workload_digest=fixture.workloads[0]["workload_digest"],
            git_ref=fixture.protocol["git_ref"],
            treatment_digest=risk["treatment_digest"],
            execution_config_digest=fixture.protocol["execution_config_digest"],
            environment_digest=fixture.protocol["environment_digest"],
            quality_rubric_digest=fixture.protocol["quality_rubric_digest"],
            artifact_paths=[
                measurement.name, protocol_path.name, inclusion_path.name,
                audit_path.name, *record_paths, *sorted(raw_paths),
            ],
        )
        for field in canary_module.MEASUREMENT_FIELDS:
            payload["runs"][0].pop(field, None)
        payload["runs"][0]["artifact_measurements"] = {
            measurement.name: ["usage", "timing", "billing", "quality_evaluation", "document_noise", "safety_audit"],
            protocol_path.name: ["experiment_protocol"],
            inclusion_path.name: ["inclusion_manifest"],
            audit_path.name: ["local_audit_report"],
            **{path: ["run_record"] for path in record_paths},
            **{path: ["raw_run_evidence"] for path in raw_paths},
        }
        return root, measurement, payload

    @staticmethod
    def _record_raw_paths(record: dict, evidence_root: Path) -> set[str]:
        paths = {
            record["prompt_artifact"]["ref"],
            record["platform_transcript"]["ref"],
            record["outcome_artifact"]["ref"],
        }
        outcome = json.loads(
            (evidence_root / record["outcome_artifact"]["ref"]).read_text()
        )
        paths.update(item["ref"] for item in outcome["raw_receipts"])
        paths.add(outcome["deliverable_capture"]["artifact"]["ref"])
        for receipt in record["gate_receipts"]:
            paths.update((receipt["stdout_ref"], receipt["stderr_ref"]))
        for thread in record["usage"]["threads"]:
            paths.add(thread["transcript_ref"])
            if "native_transcript_ref" in thread:
                paths.add(thread["native_transcript_ref"])
            paths.update(item["ref"] for item in thread["evidence_refs"])
        treatment = record["treatment_observation"]
        paths.add(treatment["hypothesis_artifact"]["ref"])
        paths.update(
            item["prompt_artifact"]["ref"]
            for item in treatment["delegation_hypothesis_batches"]
        )
        blind = record["blind_review"]
        paths.update(item["ref"] for item in blind.values())
        assignment = json.loads(
            (evidence_root / blind["assignment_artifact"]["ref"]).read_text()
        )
        score = json.loads(
            (evidence_root / blind["score_artifact"]["ref"]).read_text()
        )
        paths.update((
            assignment["asset_artifact"]["ref"],
            assignment["rubric_artifact"]["ref"],
            assignment["assignment_transcript_artifact"]["ref"],
            score["evaluator_transcript_artifact"]["ref"],
        ))
        return paths

    def test_delegation_preparation_binds_real_protocol_and_run_records(self) -> None:
        root, _measurement, payload = self.audited_delegation_manifest()
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        report = prepare_canary_bundle(
            manifest, root / "bundle", repository_root=ROOT, **IMPORT_TRUST
        )
        draft = json.loads(((root / "bundle") / report["draft_refs"][0]).read_text())
        refs = draft["observation"]["artifact_refs"]
        kinds = {kind for ref in refs for kind in ref["measurement_kinds"]}
        self.assertTrue(
            {"experiment_protocol", "run_record", "raw_run_evidence",
             "inclusion_manifest", "local_audit_report"}.issubset(kinds)
        )
        self.assertGreater(
            sum("run_record" in ref["measurement_kinds"] for ref in refs), 3
        )
        self.assertEqual(
            payload["runs"][0]["ablation_run_bindings"],
            draft["claims"]["canary_observation"]["ablation_run_bindings"],
        )

        repeated = json.loads(json.dumps(payload))
        repeated["runs"][0]["ablation_run_bindings"][1]["run_record_digest"] = (
            repeated["runs"][0]["ablation_run_bindings"][0]["run_record_digest"]
        )
        bad_manifest = root / "bad-manifest.json"
        bad_manifest.write_text(json.dumps(repeated), encoding="utf-8")
        with self.assertRaises(ValidationFailure):
            prepare_canary_bundle(
                bad_manifest, root / "bad-bundle", repository_root=ROOT, **IMPORT_TRUST
            )

        incomplete = json.loads(json.dumps(payload))
        incomplete_run = incomplete["runs"][0]
        raw_path = next(
            path for path, kinds in incomplete_run["artifact_measurements"].items()
            if "raw_run_evidence" in kinds and "hypotheses" in path
        )
        incomplete_run["artifact_paths"].remove(raw_path)
        del incomplete_run["artifact_measurements"][raw_path]
        incomplete_manifest = root / "incomplete-manifest.json"
        incomplete_manifest.write_text(json.dumps(incomplete), encoding="utf-8")
        with self.assertRaisesRegex(ValidationFailure, "closure is incomplete"):
            prepare_canary_bundle(
                incomplete_manifest, root / "incomplete-bundle",
                repository_root=ROOT, **IMPORT_TRUST,
            )

    def test_formal_replacement_closure_carries_invalidation_and_diagnostics(self) -> None:
        root, _measurement, payload = self.audited_delegation_manifest(
            with_infrastructure_replacement=True
        )
        manifest = root / "replacement-manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        report = prepare_canary_bundle(
            manifest, root / "replacement-bundle",
            repository_root=ROOT, **IMPORT_TRUST,
        )
        self.assertEqual(1, len(report["draft_refs"]))

        incomplete = json.loads(json.dumps(payload))
        run = incomplete["runs"][0]
        diagnostic_path = next(
            path for path, kinds in run["artifact_measurements"].items()
            if "raw_run_evidence" in kinds and path.endswith(".diagnostic.log")
        )
        run["artifact_paths"].remove(diagnostic_path)
        del run["artifact_measurements"][diagnostic_path]
        incomplete_manifest = root / "replacement-incomplete-manifest.json"
        incomplete_manifest.write_text(json.dumps(incomplete), encoding="utf-8")
        with self.assertRaisesRegex(
            ValidationFailure, "invalidation diagnostic closure is incomplete"
        ):
            prepare_canary_bundle(
                incomplete_manifest, root / "replacement-incomplete-bundle",
                repository_root=ROOT, **IMPORT_TRUST,
            )

    def test_formal_blind_review_is_required_and_overrides_quality_self_report(self) -> None:
        root, _measurement, payload = self.audited_delegation_manifest()
        missing = json.loads(json.dumps(payload))
        run = missing["runs"][0]
        score_path = next(
            path for path, kinds in run["artifact_measurements"].items()
            if "raw_run_evidence" in kinds and path.endswith("/score.json")
        )
        run["artifact_paths"].remove(score_path)
        del run["artifact_measurements"][score_path]
        missing_manifest = root / "blind-missing-manifest.json"
        missing_manifest.write_text(json.dumps(missing), encoding="utf-8")
        with self.assertRaisesRegex(
            ValidationFailure, "(?:run record raw evidence|blind review) closure is incomplete"
        ):
            prepare_canary_bundle(
                missing_manifest, root / "blind-missing-bundle",
                repository_root=ROOT, **IMPORT_TRUST,
            )

        forged = json.loads(json.dumps(payload))
        forged["runs"][0]["quality_score"] = 91.0
        forged["runs"][0]["blind_major_count"] = 1
        forged_manifest = root / "blind-forged-score-manifest.json"
        forged_manifest.write_text(json.dumps(forged), encoding="utf-8")
        with self.assertRaisesRegex(ValidationFailure, "quality_score.*replay-derived"):
            prepare_canary_bundle(
                forged_manifest, root / "blind-forged-score-bundle",
                repository_root=ROOT, **IMPORT_TRUST,
            )

        missing_receipt = json.loads(json.dumps(payload))
        missing_run = missing_receipt["runs"][0]
        receipt_path = next(
            path for path, kinds in missing_run["artifact_measurements"].items()
            if "raw_run_evidence" in kinds and path.endswith("attempt-fact.receipt.json")
        )
        missing_run["artifact_paths"].remove(receipt_path)
        del missing_run["artifact_measurements"][receipt_path]
        missing_receipt_manifest = root / "missing-outcome-receipt-manifest.json"
        missing_receipt_manifest.write_text(json.dumps(missing_receipt), encoding="utf-8")
        with self.assertRaisesRegex(
            ValidationFailure, "attempt outcome receipt closure is incomplete"
        ):
            prepare_canary_bundle(
                missing_receipt_manifest, root / "missing-outcome-receipt-bundle",
                repository_root=ROOT, **IMPORT_TRUST,
            )

        missing_deliverable = json.loads(json.dumps(payload))
        missing_deliverable_run = missing_deliverable["runs"][0]
        deliverable_path = next(
            path
            for path, kinds in missing_deliverable_run["artifact_measurements"].items()
            if "raw_run_evidence" in kinds and path.endswith("/deliverable.json")
        )
        deliverable_bytes = (root / deliverable_path).read_bytes()
        equivalent_paths = [
            path
            for path, kinds in missing_deliverable_run["artifact_measurements"].items()
            if "raw_run_evidence" in kinds
            and (root / path).is_file()
            and (root / path).read_bytes() == deliverable_bytes
        ]
        for equivalent_path in equivalent_paths:
            missing_deliverable_run["artifact_paths"].remove(equivalent_path)
            del missing_deliverable_run["artifact_measurements"][equivalent_path]
        missing_deliverable_manifest = root / "missing-deliverable-manifest.json"
        missing_deliverable_manifest.write_text(
            json.dumps(missing_deliverable), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            ValidationFailure, "deliverable capture closure is incomplete"
        ):
            prepare_canary_bundle(
                missing_deliverable_manifest,
                root / "missing-deliverable-bundle",
                repository_root=ROOT,
                **IMPORT_TRUST,
            )

    def test_formal_delegation_replay_uses_only_bundled_frozen_skill_bytes(self) -> None:
        root, _measurement, payload = self.audited_delegation_manifest()
        shutil.rmtree(root / "plugin")
        manifest = root / "self-contained-manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        bundle = root / "self-contained-bundle"
        report = prepare_canary_bundle(
            manifest, bundle, repository_root=ROOT, **IMPORT_TRUST
        )

        draft_ref = report["draft_refs"][0]
        draft_path = bundle / draft_ref
        response_ref = "attestations/self-contained.json"
        ArtifactIO(bundle, ".").create_immutable_json(
            {
                "schema_version": "1.0",
                "draft_digest": "sha256:"
                + hashlib.sha256(draft_path.read_bytes()).hexdigest(),
                "attestation": "trusted-canary-receipt",
            },
            *Path(response_ref).parts,
        )
        imported = import_canary_attestation(
            bundle,
            draft_ref,
            response_ref,
            "observations/self-contained.json",
            trust_verifier=self.CanaryVerifier(),
            repository_root=ROOT,
            **IMPORT_TRUST,
        )
        self.assertEqual("imported", imported["status"])

    def test_formal_delegation_rejects_missing_or_wrong_frozen_skill_bytes(self) -> None:
        for mutation in ("missing", "wrong"):
            with self.subTest(mutation=mutation):
                root, _measurement, payload = self.audited_delegation_manifest()
                run = payload["runs"][0]
                skill_path = next(
                    path
                    for path, kinds in run["artifact_measurements"].items()
                    if "raw_run_evidence" in kinds
                    and path.startswith("formal-package-evidence/skills/")
                    and path.endswith("/SKILL.md")
                )
                if mutation == "missing":
                    run["artifact_paths"].remove(skill_path)
                    del run["artifact_measurements"][skill_path]
                else:
                    (root / skill_path).write_bytes(b"wrong frozen skill bytes\n")
                manifest = root / f"{mutation}-skill-manifest.json"
                manifest.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(
                    ValidationFailure, "frozen skill evidence closure is incomplete"
                ):
                    prepare_canary_bundle(
                        manifest,
                        root / f"{mutation}-skill-bundle",
                        repository_root=ROOT,
                        **IMPORT_TRUST,
                    )

    def test_formal_delegation_requires_manifest_and_complete_package_payload(self) -> None:
        for artifact_selector in ("manifest", "runtime"):
            for mutation in ("missing", "wrong"):
                with self.subTest(artifact=artifact_selector, mutation=mutation):
                    root, _measurement, payload = self.audited_delegation_manifest()
                    run = payload["runs"][0]
                    suffix = (
                        "formal-package-evidence/package-manifest.json"
                        if artifact_selector == "manifest"
                        else "formal-package-evidence/engineering-assistant/runtime/engine.py"
                    )
                    evidence_ref = next(
                        path
                        for path, kinds in run["artifact_measurements"].items()
                        if "raw_run_evidence" in kinds and path.endswith(suffix)
                    )
                    if mutation == "missing":
                        run["artifact_paths"].remove(evidence_ref)
                        del run["artifact_measurements"][evidence_ref]
                    else:
                        (root / evidence_ref).write_bytes(b"tampered package bytes\n")
                    manifest = root / f"{mutation}-{artifact_selector}-manifest.json"
                    manifest.write_text(json.dumps(payload), encoding="utf-8")
                    expected = (
                        "frozen package manifest closure is incomplete"
                        if artifact_selector == "manifest"
                        else "frozen package payload closure is incomplete"
                    )
                    with self.assertRaisesRegex(ValidationFailure, expected):
                        prepare_canary_bundle(
                            manifest,
                            root / f"{mutation}-{artifact_selector}-bundle",
                            repository_root=ROOT,
                            **IMPORT_TRUST,
                        )

    def test_formal_delegation_requires_fixed_workload_rubric_and_environment_bytes(
        self,
    ) -> None:
        for artifact_selector in ("workload", "rubric", "environment"):
            for mutation in ("missing", "wrong"):
                with self.subTest(artifact=artifact_selector, mutation=mutation):
                    root, _measurement, payload = self.audited_delegation_manifest()
                    protocol = json.loads((root / "protocol.json").read_text())
                    refs = {
                        "workload": protocol["workloads"][0]["input_artifact"]["ref"],
                        "rubric": protocol["quality_rubric_artifact"]["ref"],
                        "environment": protocol["environment_artifact"]["ref"],
                    }
                    run = payload["runs"][0]
                    evidence_ref = refs[artifact_selector]
                    if mutation == "missing":
                        run["artifact_paths"].remove(evidence_ref)
                        del run["artifact_measurements"][evidence_ref]
                    else:
                        (root / evidence_ref).write_bytes(b"wrong fixed evidence bytes\n")
                    manifest = root / f"{mutation}-{artifact_selector}-manifest.json"
                    manifest.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(
                        ValidationFailure, "fixed protocol evidence closure is incomplete"
                    ):
                        prepare_canary_bundle(
                            manifest,
                            root / f"{mutation}-{artifact_selector}-bundle",
                            repository_root=ROOT,
                            **IMPORT_TRUST,
                        )

    def test_prepare_reads_shared_source_closure_once_per_manifest(self) -> None:
        root, _measurement, payload = self.audited_delegation_manifest()
        repeated = json.loads(json.dumps(payload["runs"][0]))
        repeated["task_id"] = "delegation-ablation-shared-closure-copy"
        payload["runs"].append(repeated)
        manifest = root / "shared-closure-manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        unique_references = {
            reference
            for run in payload["runs"]
            for reference in run["artifact_paths"]
        }

        source_reader = canary_module._source_artifact
        with mock.patch.object(
            canary_module,
            "_source_artifact",
            wraps=source_reader,
        ) as reader:
            prepare_canary_bundle(
                manifest,
                root / "shared-closure-bundle",
                repository_root=ROOT,
                **IMPORT_TRUST,
            )

        self.assertEqual(len(unique_references), reader.call_count)

    def test_delegation_prepare_replays_raw_evidence_instead_of_trusting_success_report(self) -> None:
        root, _measurement, payload = self.audited_delegation_manifest()
        run = payload["runs"][0]
        selected = run["ablation_run_bindings"][0]
        record_path = next(
            root / path
            for path, kinds in run["artifact_measurements"].items()
            if "run_record" in kinds
            and json.loads((root / path).read_text())["run_id"] == selected["run_id"]
        )
        record = json.loads(record_path.read_text())
        platform_path = root / record["platform_transcript"]["ref"]
        platform_path.write_bytes(b"not-jsonl\n")
        platform_digest = "sha256:" + hashlib.sha256(platform_path.read_bytes()).hexdigest()
        record["platform_transcript"]["digest"] = platform_digest
        root_thread = next(
            thread
            for thread in record["usage"]["threads"]
            if thread["parent_thread_id"] is None
        )
        root_thread["transcript_digest"] = platform_digest
        record_path.write_bytes(ArtifactIO.canonical_json_bytes(record))
        record_digest = canonical_digest(record)

        inclusion_path = root / "inclusion.json"
        inclusion = json.loads(inclusion_path.read_text())
        next(
            item for item in inclusion["entries"] if item["run_id"] == record["run_id"]
        )["run_record_digest"] = record_digest
        inclusion_path.write_bytes(ArtifactIO.canonical_json_bytes(inclusion))

        audit_path = root / "audit-report.json"
        audit = json.loads(audit_path.read_text())
        for field in (
            "audited_run_bindings", "included_run_bindings", "attempt_bindings",
            "quality_cohort_bindings", "promotion_burden_bindings",
        ):
            next(
                item for item in audit[field] if item["run_id"] == record["run_id"]
            )["run_record_digest"] = record_digest
        audit["promotion_attempt_set_digest"] = canonical_digest(
            {"attempt_bindings": audit["promotion_burden_bindings"]}
        )
        audit_path.write_bytes(ArtifactIO.canonical_json_bytes(audit))
        selected["run_record_digest"] = record_digest

        manifest = root / "forged-success-manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValidationFailure, "replay"):
            prepare_canary_bundle(
                manifest,
                root / "forged-success-bundle",
                repository_root=ROOT,
                **IMPORT_TRUST,
            )

        crossed = json.loads(json.dumps(payload))
        crossed["runs"][0]["artifact_measurements"]["protocol.json"].append("run_record")
        crossed_manifest = root / "crossed-manifest.json"
        crossed_manifest.write_text(json.dumps(crossed), encoding="utf-8")
        with self.assertRaisesRegex(ValidationFailure, "roles cannot overlap"):
            prepare_canary_bundle(
                crossed_manifest, root / "crossed-bundle",
                repository_root=ROOT, **IMPORT_TRUST,
            )

        unaudited = json.loads(json.dumps(payload))
        unaudited_run = unaudited["runs"][0]
        unaudited_run["artifact_paths"].remove("audit-report.json")
        del unaudited_run["artifact_measurements"]["audit-report.json"]
        unaudited_manifest = root / "unaudited-manifest.json"
        unaudited_manifest.write_text(json.dumps(unaudited), encoding="utf-8")
        with self.assertRaisesRegex(ValidationFailure, "exactly one audit"):
            prepare_canary_bundle(
                unaudited_manifest, root / "unaudited-bundle",
                repository_root=ROOT, **IMPORT_TRUST,
            )

    def test_delegation_prepare_rejects_full_local_audit_report_drift(self) -> None:
        root, _measurement, payload = self.audited_delegation_manifest()
        audit_path = root / "audit-report.json"
        original = json.loads(audit_path.read_text())
        run_id = original["audited_run_bindings"][0]["run_id"]
        mutations = (
            ("broker", "broker_status", "attested"),
            ("billing", "billing_status", "collected"),
            ("promotion", "promotion_eligible", True),
            (
                "included-count",
                "included_structural_runs",
                original["included_structural_runs"] + 1,
            ),
            ("limitations", "limitations", [*original["limitations"], "forged"]),
            ("warnings", "warnings", []),
            ("failures", "failures", ["forged_failure"]),
            (
                "excluded-failures",
                "excluded_run_failures",
                [{"run_id": run_id, "failures": ["forged_excluded_failure"]}],
            ),
        )

        for label, field, value in mutations:
            with self.subTest(field=field):
                forged = json.loads(json.dumps(original))
                forged[field] = value
                audit_path.write_bytes(ArtifactIO.canonical_json_bytes(forged))
                manifest = root / f"audit-drift-{label}.manifest.json"
                manifest.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(
                    ValidationFailure,
                    "local audit (?:report is not successful|replay)",
                ):
                    prepare_canary_bundle(
                        manifest,
                        root / f"audit-drift-{label}.bundle",
                        repository_root=ROOT,
                        **IMPORT_TRUST,
                    )

    def test_prepare_copies_artifacts_and_emits_unsigned_claims_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text('{"type":"turn.completed"}\n', encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(self.manifest(artifact)), encoding="utf-8")
            output = root / "bundle"

            report = prepare_canary_bundle(
                manifest,
                output,
                repository_root=ROOT,
                **IMPORT_TRUST,
            )

            self.assertEqual("awaiting_attestation", report["status"])
            self.assertEqual(1, report["draft_count"])
            self.assertEqual([], report["incomplete_runs"])
            draft_path = output / report["draft_refs"][0]
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual("awaiting_attestation", draft["status"])
            self.assertEqual([], draft["missing_fields"])
            self.assertNotIn("attestation", draft["observation"])
            self.assertNotIn("attestation", json.dumps(draft["claims"]))
            copied = output / draft["observation"]["artifact_refs"][0]["path"]
            self.assertEqual(artifact.read_bytes(), copied.read_bytes())
            self.assertEqual(
                "sha256:" + hashlib.sha256(copied.read_bytes()).hexdigest(),
                draft["observation"]["artifact_refs"][0]["digest"],
            )
            self.assertEqual(
                [
                    "billing",
                    "document_noise",
                    "quality_evaluation",
                    "safety_audit",
                    "timing",
                    "usage",
                ],
                draft["observation"]["artifact_refs"][0]["measurement_kinds"],
            )
            self.assertFalse((output / "canary-result.json").exists())

    def test_prepare_reuses_content_addressed_artifacts_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shared = root / "shared.log"
            shared.write_text("shared evidence\n", encoding="utf-8")
            baseline = self.manifest(
                shared, task_id="task-1", variant="baseline", arm_id="baseline",
                treatment_digest="sha256:" + "1" * 64,
            )["runs"][0]
            candidate = self.manifest(
                shared, task_id="task-1", variant="candidate", arm_id="candidate",
                treatment_digest="sha256:" + "2" * 64,
            )["runs"][0]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": "1.0", "product_repository": "ai-platform",
                "runs": [baseline, candidate],
            }), encoding="utf-8")
            bundle = root / "bundle"
            report = prepare_canary_bundle(
                manifest, bundle, repository_root=ROOT, **IMPORT_TRUST
            )
            paths = [
                json.loads((bundle / ref).read_text())["observation"]["artifact_refs"][0]["path"]
                for ref in report["draft_refs"]
            ]
            self.assertEqual(paths[0], paths[1])
            self.assertEqual(1, len(list((bundle / "artifacts/by-digest").iterdir())))

            first = root / "first.log"
            second = root / "second.log"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            collision = self.manifest(first, artifact_paths=[first.name, second.name])
            collision_manifest = root / "collision-manifest.json"
            collision_manifest.write_text(json.dumps(collision), encoding="utf-8")
            with mock.patch(
                "engineering_assistant.canary._sha256_bytes",
                return_value="sha256:" + "f" * 64,
            ), self.assertRaisesRegex(ValidationFailure, "digest collision"):
                prepare_canary_bundle(
                    collision_manifest, root / "collision-bundle",
                    repository_root=ROOT, **IMPORT_TRUST,
                )

    def test_prepare_rejects_measurements_without_mapped_artifact_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            payload = self.manifest(artifact)
            payload["runs"][0]["artifact_measurements"][artifact.name] = ["usage"]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                ValidationFailure,
                "measurement artifact coverage",
            ):
                prepare_canary_bundle(
                    manifest,
                    root / "bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

    def test_prepare_rejects_incomparable_usage_and_timing_measurements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            for overrides, message in (
                ({"input_tokens": 10, "noncached_input_tokens": 11}, "noncached"),
                ({"wall_time_milliseconds": 0}, "wall_time"),
                (
                    {"applicable_matrix_cells": 3, "closed_matrix_cells": 4},
                    "closed matrix cells",
                ),
            ):
                manifest = root / f"manifest-{message.replace(' ', '-')}.json"
                manifest.write_text(
                    json.dumps(self.manifest(artifact, **overrides)),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValidationFailure, message):
                    prepare_canary_bundle(
                        manifest,
                        root / f"bundle-{message.replace(' ', '-')}",
                        repository_root=ROOT,
                        **IMPORT_TRUST,
                    )

            oversized_manifest = root / "manifest-oversized.json"
            oversized_manifest.write_text(
                json.dumps(self.manifest(artifact, input_tokens=10**4000)),
                encoding="utf-8",
            )
            with self.assertRaises(ValidationFailure):
                prepare_canary_bundle(
                    oversized_manifest,
                    root / "bundle-oversized",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

    def test_missing_real_measurements_stays_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            payload = self.manifest(artifact)
            del payload["runs"][0]["cost_usd_micros"]
            del payload["runs"][0]["quality_score"]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            report = prepare_canary_bundle(
                manifest,
                root / "bundle",
                repository_root=ROOT,
                **IMPORT_TRUST,
            )

            self.assertEqual("incomplete", report["status"])
            self.assertEqual(
                ["cost_usd_micros", "quality_score"],
                report["incomplete_runs"][0]["missing_fields"],
            )

    def test_prepare_claims_are_the_exact_claims_verified_after_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(self.manifest(artifact)), encoding="utf-8"
            )
            bundle = root / "bundle"
            report = prepare_canary_bundle(
                manifest,
                bundle,
                repository_root=ROOT,
                **IMPORT_TRUST,
            )
            draft_ref = report["draft_refs"][0]
            draft_path = bundle / draft_ref
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "evidence_broker_id": CANARY_BROKER_ID,
                    "host_trust_config_digest": CANARY_HOST_CONFIG_DIGEST,
                },
                draft["observation"]["trust_provenance"],
            )
            self.assertEqual(
                canary_observation_claims(draft["observation"]),
                draft["claims"],
            )
            response_ref = "attestations/response.json"
            ArtifactIO(bundle, ".").create_immutable_json(
                {
                    "schema_version": "1.0",
                    "draft_digest": "sha256:"
                    + hashlib.sha256(draft_path.read_bytes()).hexdigest(),
                    "attestation": "trusted-canary-receipt",
                },
                *Path(response_ref).parts,
            )
            verifier = ExternalTrustVerifier(
                evidence_broker={
                    "enabled": True,
                    "id": CANARY_BROKER_ID,
                    "introspection_url": "https://broker.example/canary",
                    "timeout_seconds": 5,
                },
                approval_broker={"enabled": False},
            )
            with mock.patch(
                "urllib.request.urlopen",
                return_value=self.BrokerResponse(draft["claims"]),
            ):
                imported = import_canary_attestation(
                    bundle,
                    draft_ref,
                    response_ref,
                    "observations/run.json",
                    trust_verifier=verifier,
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )
            self.assertEqual("imported", imported["status"])

    def test_canary_writes_reject_a_separate_author_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            author = root / "other-author-tree"
            for relative in (
                "catalog",
                "skills",
                "schemas",
                "src/engineering_assistant",
            ):
                (author / relative).mkdir(parents=True, exist_ok=True)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(self.manifest(artifact)), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ValidationFailure, "author or installed plugin tree"
            ):
                prepare_canary_bundle(
                    manifest,
                    author / "canary-bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )
            with self.assertRaisesRegex(
                ValidationFailure, "author or installed plugin tree"
            ):
                import_canary_attestation(
                    author,
                    "observations/run.draft.json",
                    "attestations/run.json",
                    "observations/run.json",
                    trust_verifier=self.CanaryVerifier(),
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )

    def test_prepare_bounds_total_artifact_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = []
            for index in range(64):
                artifact = root / f"artifact-{index}.log"
                artifact.write_text("x\n", encoding="utf-8")
                artifacts.append(artifact.name)
            runs = []
            for index in range(9):
                runs.append(
                    self.manifest(
                        root / artifacts[0],
                        task_id=f"task-{index}",
                        artifact_paths=artifacts,
                    )["runs"][0]
                )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "product_repository": "ai-platform",
                        "runs": runs,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "engineering_assistant.canary_limits.MAX_TOTAL_ARTIFACTS", 63
            ), self.assertRaisesRegex(ValidationFailure, "too many artifacts"):
                prepare_canary_bundle(
                    manifest,
                    root / "bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

    def test_prepare_bounds_total_artifact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.log"
            second = root / "second.log"
            first.write_text("aa", encoding="utf-8")
            second.write_text("bb", encoding="utf-8")
            payload = self.manifest(
                first,
                artifact_paths=[first.name, second.name],
            )
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch(
                "engineering_assistant.canary_limits.MAX_TOTAL_ARTIFACT_BYTES", 3
            ), self.assertRaisesRegex(
                ValidationFailure, "total artifact bytes"
            ):
                prepare_canary_bundle(
                    manifest,
                    root / "bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

    def test_attestation_import_bounds_external_response_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(self.manifest(artifact)), encoding="utf-8")
            bundle = root / "bundle"
            report = prepare_canary_bundle(
                manifest,
                bundle,
                repository_root=ROOT,
                **IMPORT_TRUST,
            )
            response = bundle / "attestations/oversized.json"
            response.parent.mkdir(parents=True)
            response.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "draft_digest": "sha256:" + "a" * 64,
                        "attestation": "x" * 4096,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch(
                "engineering_assistant.canary_limits.MAX_ATTESTATION_RESPONSE_BYTES",
                256,
            ), self.assertRaisesRegex(ValidationFailure, "size limit"):
                import_canary_attestation(
                    bundle,
                    report["draft_refs"][0],
                    "attestations/oversized.json",
                    "observations/run.json",
                    trust_verifier=self.CanaryVerifier(),
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )

    def test_attestation_import_bounds_total_unique_artifact_count_before_broker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle, draft_ref, response_ref = self.prepared_import_bundle(
                Path(temporary),
                [b"first\n", b"second\n"],
            )
            verifier = mock.Mock()

            with mock.patch(
                "engineering_assistant.canary_limits.MAX_TOTAL_ARTIFACTS",
                1,
            ), self.assertRaisesRegex(ValidationFailure, "too many artifacts"):
                import_canary_attestation(
                    bundle,
                    draft_ref,
                    response_ref,
                    "observations/run.json",
                    trust_verifier=verifier,
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )

            verifier.verify_canary_observation.assert_not_called()

    def test_attestation_import_bounds_total_unique_artifact_bytes_before_broker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle, draft_ref, response_ref = self.prepared_import_bundle(
                Path(temporary),
                [b"aa", b"bb"],
            )
            verifier = mock.Mock()

            with mock.patch(
                "engineering_assistant.canary_limits.MAX_TOTAL_ARTIFACT_BYTES",
                3,
            ), self.assertRaisesRegex(ValidationFailure, "total artifact bytes"):
                import_canary_attestation(
                    bundle,
                    draft_ref,
                    response_ref,
                    "observations/run.json",
                    trust_verifier=verifier,
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )

            verifier.verify_canary_observation.assert_not_called()

    def test_prepare_rejects_symlink_artifact_and_repo_local_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(self.manifest(artifact)), encoding="utf-8")

            with self.assertRaisesRegex(ValidationFailure, "outside the author repository"):
                prepare_canary_bundle(
                    manifest,
                    repository / "bundle",
                    repository_root=repository,
                    **IMPORT_TRUST,
                )

            link = root / "linked-events.jsonl"
            link.symlink_to(artifact)
            manifest.write_text(json.dumps(self.manifest(link)), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "symlink"):
                prepare_canary_bundle(
                    manifest,
                    root / "external-bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

    def test_prepare_never_publishes_or_cleans_a_replaced_staging_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(self.manifest(artifact)),
                encoding="utf-8",
            )
            replacement_marker = root / "replacement-marker"

            original_copy = ArtifactIO.copy_contents_to

            def replace_output_during_copy(
                source,
                destination,
                *,
                max_file_bytes,
            ):
                output = root / "bundle"
                output.rename(root / "held-original-output")
                output.mkdir()
                (output / replacement_marker.name).write_text(
                    "unrelated",
                    encoding="utf-8",
                )
                return original_copy(
                    source,
                    destination,
                    max_file_bytes=max_file_bytes,
                )

            with mock.patch.object(
                ArtifactIO,
                "copy_contents_to",
                new=replace_output_during_copy,
            ), self.assertRaisesRegex(ValidationFailure, "output directory identity"):
                prepare_canary_bundle(
                    manifest,
                    root / "bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

            self.assertEqual(
                "unrelated",
                (root / "bundle" / replacement_marker.name).read_text(encoding="utf-8"),
            )

    def test_prepare_rejects_absolute_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            payload = self.manifest(
                artifact,
                artifact_paths=[str(artifact)],
            )
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValidationFailure, "relative"):
                prepare_canary_bundle(
                    manifest,
                    root / "bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

    def test_cli_exposes_canary_prepare_without_attestation_options(self) -> None:
        args = build_parser().parse_args(
            [
                "canary-prepare",
                "--manifest",
                "/tmp/canary-manifest.json",
                "--output",
                "/tmp/canary-bundle",
            ]
        )

        self.assertEqual("canary-prepare", args.command)
        self.assertEqual("/tmp/canary-manifest.json", args.manifest)
        self.assertEqual("/tmp/canary-bundle", args.output)
        self.assertFalse(hasattr(args, "attestation"))

        imported = build_parser().parse_args(
            [
                "canary-attestation-import",
                "--evidence-root",
                "/tmp/canary-bundle",
                "--draft-ref",
                "observations/run.draft.json",
                "--response-ref",
                "attestations/run.json",
                "--output",
                "observations/run.json",
            ]
        )
        self.assertEqual("canary-attestation-import", imported.command)
        self.assertFalse(hasattr(imported, "attestation"))

    def test_attestation_import_rejects_draft_claim_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(self.manifest(artifact)), encoding="utf-8"
            )
            bundle = root / "bundle"
            report = prepare_canary_bundle(
                manifest,
                bundle,
                repository_root=ROOT,
                **IMPORT_TRUST,
            )
            draft_ref = report["draft_refs"][0]
            draft_path = bundle / draft_ref
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["claims"]["canary_observation"]["quality_score"] = 0
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            response_ref = "attestations/response.json"
            ArtifactIO(bundle, ".").create_immutable_json(
                {
                    "schema_version": "1.0",
                    "draft_digest": "sha256:"
                    + hashlib.sha256(draft_path.read_bytes()).hexdigest(),
                    "attestation": "trusted-canary-receipt",
                },
                *Path(response_ref).parts,
            )

            with self.assertRaisesRegex(ValidationFailure, "claims"):
                import_canary_attestation(
                    bundle,
                    draft_ref,
                    response_ref,
                    "observations/run.json",
                    trust_verifier=self.CanaryVerifier(),
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )

    def test_attested_paired_vertical_chain_stops_before_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text('{"type":"turn.completed"}\n', encoding="utf-8")
            runs = []
            for index in range(5):
                workload_digest = "sha256:" + hashlib.sha256(
                    f"workload:{index}".encode()
                ).hexdigest()
                runs.append(
                    self.manifest(
                        artifact,
                        task_id=f"task-{index}",
                        workload_digest=workload_digest,
                        variant="baseline",
                        git_ref="base",
                        input_tokens=80,
                        output_tokens=20,
                        cost_usd_micros=100,
                        quality_score=90,
                        document_noise_units=10,
                    )["runs"][0]
                )
                runs.append(
                    self.manifest(
                        artifact,
                        task_id=f"task-{index}",
                        workload_digest=workload_digest,
                        variant="candidate",
                        git_ref="base",
                        treatment_digest="sha256:" + "c" * 64,
                        input_tokens=55,
                        output_tokens=18,
                        cost_usd_micros=72,
                        quality_score=90,
                        document_noise_units=6,
                    )["runs"][0]
                )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "product_repository": "ai-platform",
                        "runs": runs,
                    }
                ),
                encoding="utf-8",
            )
            bundle = root / "bundle"
            preparation = prepare_canary_bundle(
                manifest,
                bundle,
                repository_root=ROOT,
                **IMPORT_TRUST,
            )

            evidence_refs = []
            for index, draft_ref in enumerate(preparation["draft_refs"]):
                draft_path = bundle / draft_ref
                response_ref = f"attestations/response-{index}.json"
                ArtifactIO(bundle, ".").create_immutable_json(
                    {
                        "schema_version": "1.0",
                        "draft_digest": "sha256:"
                        + hashlib.sha256(draft_path.read_bytes()).hexdigest(),
                        "attestation": "trusted-canary-receipt",
                    },
                    *Path(response_ref).parts,
                )
                evidence_ref = f"observations/observation-{index}.json"
                import_canary_attestation(
                    bundle,
                    draft_ref,
                    response_ref,
                    evidence_ref,
                    trust_verifier=self.CanaryVerifier(),
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )
                evidence_refs.append(evidence_ref)

            with self.assertRaisesRegex(ValidationFailure, "legacy.*not promotable"):
                assemble_canary_result(
                    bundle,
                    evidence_refs,
                    trust_verifier=self.CanaryVerifier(),
                    **VALIDATION_TRUST,
                )
            return
            ArtifactIO(bundle, ".").create_immutable_json(
                result,
                "canary-result.json",
            )
            validated = run_canary_result(
                bundle / "canary-result.json",
                trust_verifier=self.CanaryVerifier(),
                **VALIDATION_TRUST,
            )
            self.assertEqual("passed", validated["status"])
            self.assertEqual(5, validated["task_count"])
            self.assertEqual(
                {
                    "evidence_broker_id": CANARY_BROKER_ID,
                    "host_trust_config_digest": CANARY_HOST_CONFIG_DIGEST,
                },
                validated["trust_provenance"],
            )


if __name__ == "__main__":
    unittest.main()
