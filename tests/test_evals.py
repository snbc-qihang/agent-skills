from __future__ import annotations

import json
import hashlib
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CANARY_BROKER_ID = "enterprise-evidence"
CANARY_HOST_CONFIG_DIGEST = "sha256:" + "c" * 64
VALIDATION_TRUST = {
    "expected_evidence_broker_id": CANARY_BROKER_ID,
    "expected_host_trust_config_digest": CANARY_HOST_CONFIG_DIGEST,
}

from engineering_assistant.eval_runner import (  # noqa: E402
    assemble_canary_result,
    run_canary_result,
    run_evals,
)
from engineering_assistant.cli import (  # noqa: E402
    build_parser,
    command_canary_assemble,
    command_canary_validate,
)
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class EvalTests(unittest.TestCase):
    class CanaryVerifier:
        def verify_canary_observation(self, observation) -> bool:
            return observation.get("attestation") == "trusted-canary-receipt"

    def test_cli_exposes_canary_assembly_as_external_attestation_consumer(self) -> None:
        args = build_parser().parse_args(
            [
                "canary-assemble",
                "--evidence-root",
                "/tmp/canary-bundle",
                "--evidence-ref",
                "observations/baseline.json",
                "--evidence-ref",
                "observations/candidate.json",
                "--output",
                "canary-result.json",
            ]
        )

        self.assertEqual("canary-assemble", args.command)
        self.assertEqual(2, len(args.evidence_ref))
        self.assertFalse(hasattr(args, "attestation"))

    def test_canary_assembly_never_overwrites_a_concurrent_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def competing_writer(*_args, **_kwargs):
                (root / "canary-result.json").write_text(
                    '{"winner":"other"}\n', encoding="utf-8"
                )
                return {"winner": "ours"}

            args = SimpleNamespace(
                repository_root=str(ROOT),
                evidence_root=str(root),
                evidence_ref=["baseline.json", "candidate.json"],
                output="canary-result.json",
                trust_verifier=self.CanaryVerifier(),
                evidence_broker={"enabled": True, "id": CANARY_BROKER_ID},
                host_trust_config_digest=CANARY_HOST_CONFIG_DIGEST,
            )
            with patch(
                "engineering_assistant.cli.assemble_canary_result",
                side_effect=competing_writer,
            ):
                with self.assertRaisesRegex(ValidationFailure, "already exists"):
                    command_canary_assemble(args)
            self.assertEqual(
                '{"winner":"other"}\n',
                (root / "canary-result.json").read_text(encoding="utf-8"),
            )

    def test_canary_cli_requires_an_administrator_bound_broker(self) -> None:
        args = SimpleNamespace(
            repository_root=str(ROOT),
            evidence_root="/tmp/canary-bundle",
            evidence_ref=["baseline.json", "candidate.json"],
            output="canary-result.json",
            trust_verifier=self.CanaryVerifier(),
            evidence_broker={"enabled": True, "id": CANARY_BROKER_ID},
            host_trust_config_digest=None,
        )

        with self.assertRaisesRegex(ValidationFailure, "administrator-bound"):
            command_canary_assemble(args)

    def test_canary_validate_returns_nonzero_when_thresholds_fail(self) -> None:
        args = SimpleNamespace(
            result="/tmp/canary-result.json",
            trust_verifier=self.CanaryVerifier(),
            evidence_broker={"enabled": True, "id": CANARY_BROKER_ID},
            host_trust_config_digest=CANARY_HOST_CONFIG_DIGEST,
        )
        with redirect_stdout(io.StringIO()):
            with patch(
                "engineering_assistant.cli.run_canary_result",
                return_value={"status": "failed", "quality_delta_points": -3},
            ):
                self.assertEqual(2, command_canary_validate(args))
            with patch(
                "engineering_assistant.cli.run_canary_result",
                return_value={"status": "passed"},
            ):
                self.assertEqual(0, command_canary_validate(args))

    def test_canary_assembly_rejects_an_author_source_evidence_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            author = Path(temporary) / "author"
            for relative in (
                "catalog",
                "skills",
                "schemas",
                "src/engineering_assistant",
            ):
                (author / relative).mkdir(parents=True, exist_ok=True)
            args = SimpleNamespace(
                repository_root=str(ROOT),
                evidence_root=str(author),
                evidence_ref=["baseline.json", "candidate.json"],
                output="canary-result.json",
                trust_verifier=self.CanaryVerifier(),
                evidence_broker={"enabled": True, "id": CANARY_BROKER_ID},
                host_trust_config_digest=CANARY_HOST_CONFIG_DIGEST,
            )

            with self.assertRaisesRegex(
                ValidationFailure, "author or installed plugin tree"
            ):
                command_canary_assemble(args)

    def test_real_routing_behavior_state_and_replay_gates(self) -> None:
        report = run_evals(ROOT)
        self.assertFalse(report["simulation"])
        self.assertGreaterEqual(report["routing"]["case_count"], 100)
        self.assertGreaterEqual(report["routing"]["top1_accuracy"], 0.90)
        self.assertLessEqual(report["routing"]["no_result_ratio"], 0.05)
        self.assertEqual(0, report["routing"]["unconfirmed_high_risk_writes"])
        self.assertEqual(1.0, report["behavior"]["pass_ratio"])
        self.assertEqual(1.0, report["state_machine"]["pass_ratio"])
        self.assertEqual(1.0, report["replay"]["pass_ratio"])
        self.assertEqual(4, report["capabilities"]["case_count"])
        self.assertEqual(1.0, report["capabilities"]["pass_ratio"])
        self.assertEqual(
            "selected_runtime_mechanisms_only",
            report["capabilities"]["coverage_claim"],
        )
        self.assertEqual(
            set(report["capabilities"]["required_mechanisms"]),
            {item["capability"] for item in report["capabilities"]["results"]},
        )
        self.assertEqual("not_run", report["canary"]["status"])

    def test_canary_rejects_simulated_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "canary.json"
            path.write_text(
                json.dumps(
                    {
                        "simulation": True,
                        "product_repository": "product",
                        "baseline_ref": "base",
                        "candidate_ref": "candidate",
                        "quality_delta_points": 0,
                        "cost_reduction_ratio": 0.3,
                        "document_noise_reduction_ratio": 0.4,
                        "safety_violations": 0,
                        "evidence_refs": ["observed:test"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValidationFailure):
                run_canary_result(
                    path,
                    trust_verifier=self.CanaryVerifier(),
                    **VALIDATION_TRUST,
                )

    def test_observed_canary_uses_real_evidence_and_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_refs = []
            digest = "sha256:" + "a" * 64
            for index in range(5):
                for variant in ("baseline", "candidate"):
                    artifact = root / f"{variant}-{index}.log"
                    artifact.write_text(
                        f"observed {variant} {index}\n", encoding="utf-8"
                    )
                    artifact_digest = "sha256:" + hashlib.sha256(
                        artifact.read_bytes()
                    ).hexdigest()
                    evidence = root / f"{variant}-{index}.json"
                    evidence.write_text(
                        json.dumps(
                            {
                                "simulation": False,
                                "task_id": f"task-{index}",
                                "workload_digest": digest,
                                "variant": variant,
                                "product_repository": "product",
                                "git_ref": "base" if variant == "baseline" else "candidate",
                                "treatment_digest": "sha256:"
                                + ("b" if variant == "baseline" else "c") * 64,
                                "execution_config_digest": digest,
                                "environment_digest": digest,
                                "quality_rubric_digest": digest,
                                "evaluator_id": "ci-quality-evaluator",
                                "started_at": "2026-07-11T00:00:00+00:00",
                                "finished_at": "2026-07-11T00:10:00+00:00",
                                "input_tokens": 60 if variant == "baseline" else 43,
                                "output_tokens": 40 if variant == "baseline" else 30,
                                "cost_usd_micros": 100 if variant == "baseline" else 73,
                                "quality_score": 80 if variant == "baseline" else 78.5,
                                "document_noise_units": 100 if variant == "baseline" else 69,
                                "safety_violations": 0,
                                "artifact_refs": [
                                    {
                                        "path": artifact.name,
                                        "digest": artifact_digest,
                                        "measurement_kinds": [
                                            "usage",
                                            "billing",
                                            "quality_evaluation",
                                            "document_noise",
                                            "safety_audit",
                                        ],
                                    }
                                ],
                                "trust_provenance": {
                                    "evidence_broker_id": CANARY_BROKER_ID,
                                    "host_trust_config_digest": CANARY_HOST_CONFIG_DIGEST,
                                },
                                "attestation": "trusted-canary-receipt",
                            }
                        ),
                        encoding="utf-8",
                    )
                    evidence_refs.append(evidence.name)
            assembled = assemble_canary_result(
                root,
                evidence_refs,
                trust_verifier=self.CanaryVerifier(),
                **VALIDATION_TRUST,
            )
            self.assertEqual("product", assembled["product_repository"])
            self.assertEqual("base", assembled["baseline_ref"])
            self.assertEqual("candidate", assembled["candidate_ref"])
            self.assertNotEqual(
                assembled["baseline_treatment_digest"],
                assembled["candidate_treatment_digest"],
            )
            self.assertAlmostEqual(-1.5, assembled["quality_delta_points"])
            self.assertAlmostEqual(0.27, assembled["cost_reduction_ratio"])
            self.assertEqual(
                {
                    "evidence_broker_id": CANARY_BROKER_ID,
                    "host_trust_config_digest": CANARY_HOST_CONFIG_DIGEST,
                },
                assembled["trust_provenance"],
            )
            with patch(
                "engineering_assistant.canary_limits.MAX_TOTAL_ARTIFACTS",
                9,
            ), self.assertRaisesRegex(ValidationFailure, "too many artifacts"):
                assemble_canary_result(
                    root,
                    evidence_refs,
                    trust_verifier=self.CanaryVerifier(),
                    **VALIDATION_TRUST,
                )
            with self.assertRaisesRegex(ValidationFailure, "different host trust"):
                assemble_canary_result(
                    root,
                    evidence_refs,
                    trust_verifier=self.CanaryVerifier(),
                    expected_evidence_broker_id=CANARY_BROKER_ID,
                    expected_host_trust_config_digest="sha256:" + "d" * 64,
                )
            with self.assertRaisesRegex(ValidationFailure, "external evidence broker"):
                assemble_canary_result(root, evidence_refs, **VALIDATION_TRUST)

            incomplete_mapping_path = root / "candidate-0.json"
            original_mapping_payload = incomplete_mapping_path.read_text(
                encoding="utf-8"
            )
            incomplete_mapping = json.loads(original_mapping_payload)
            incomplete_mapping["artifact_refs"][0]["measurement_kinds"] = [
                "usage"
            ]
            incomplete_mapping_path.write_text(
                json.dumps(incomplete_mapping), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ValidationFailure,
                "measurement artifact coverage",
            ):
                assemble_canary_result(
                    root,
                    evidence_refs,
                    trust_verifier=self.CanaryVerifier(),
                    **VALIDATION_TRUST,
                )
            incomplete_mapping_path.write_text(
                original_mapping_payload, encoding="utf-8"
            )

            originals = {}
            for evidence_ref in evidence_refs:
                if not evidence_ref.startswith("candidate-"):
                    continue
                evidence_path = root / evidence_ref
                originals[evidence_ref] = evidence_path.read_text(encoding="utf-8")
                observation = json.loads(originals[evidence_ref])
                observation["treatment_digest"] = "sha256:" + "b" * 64
                evidence_path.write_text(json.dumps(observation), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "treatment"):
                assemble_canary_result(
                    root,
                    evidence_refs,
                    trust_verifier=self.CanaryVerifier(),
                    **VALIDATION_TRUST,
                )
            for evidence_ref, payload in originals.items():
                (root / evidence_ref).write_text(payload, encoding="utf-8")

            result = root / "canary.json"
            result.write_text(json.dumps(assembled), encoding="utf-8")
            report = run_canary_result(
                result,
                trust_verifier=self.CanaryVerifier(),
                **VALIDATION_TRUST,
            )
            self.assertEqual("passed", report["status"])
            self.assertEqual(5, report["task_count"])
            with self.assertRaisesRegex(ValidationFailure, "external evidence broker"):
                run_canary_result(result, **VALIDATION_TRUST)

            artifact = root / "candidate-0.log"
            original_artifact = artifact.read_text(encoding="utf-8")
            artifact.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "digest"):
                run_canary_result(
                    result,
                    trust_verifier=self.CanaryVerifier(),
                    **VALIDATION_TRUST,
                )
            artifact.write_text(original_artifact, encoding="utf-8")

            observation_path = root / "candidate-0.json"
            original_observation = observation_path.read_text(encoding="utf-8")
            observation = json.loads(original_observation)
            observation["execution_config_digest"] = "sha256:" + "b" * 64
            observation_path.write_text(json.dumps(observation), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "execution config"):
                run_canary_result(
                    result,
                    trust_verifier=self.CanaryVerifier(),
                    **VALIDATION_TRUST,
                )
            observation_path.write_text(original_observation, encoding="utf-8")

            forged = json.loads(result.read_text(encoding="utf-8"))
            forged["cost_reduction_ratio"] = 0.5
            result.write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "does not match"):
                run_canary_result(
                    result,
                    trust_verifier=self.CanaryVerifier(),
                    **VALIDATION_TRUST,
                )


if __name__ == "__main__":
    unittest.main()
