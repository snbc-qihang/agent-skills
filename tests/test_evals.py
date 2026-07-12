from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.eval_runner import run_canary_result, run_evals  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class EvalTests(unittest.TestCase):
    class CanaryVerifier:
        def verify_canary_observation(self, observation) -> bool:
            return observation.get("attestation") == "trusted-canary-receipt"

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
                run_canary_result(path, trust_verifier=self.CanaryVerifier())

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
                                    {"path": artifact.name, "digest": artifact_digest}
                                ],
                                "attestation": "trusted-canary-receipt",
                            }
                        ),
                        encoding="utf-8",
                    )
                    evidence_refs.append(evidence.name)
            result = root / "canary.json"
            result.write_text(
                json.dumps(
                    {
                        "simulation": False,
                        "product_repository": "product",
                        "baseline_ref": "base",
                        "candidate_ref": "candidate",
                        "baseline_execution_config_digest": digest,
                        "candidate_execution_config_digest": digest,
                        "quality_delta_points": -1.5,
                        "token_reduction_ratio": 0.27,
                        "cost_reduction_ratio": 0.27,
                        "document_noise_reduction_ratio": 0.31,
                        "safety_violations": 0,
                        "evidence_refs": evidence_refs,
                    }
                ),
                encoding="utf-8",
            )
            report = run_canary_result(
                result, trust_verifier=self.CanaryVerifier()
            )
            self.assertEqual("passed", report["status"])
            self.assertEqual(5, report["task_count"])
            with self.assertRaisesRegex(ValidationFailure, "external evidence broker"):
                run_canary_result(result)

            artifact = root / "candidate-0.log"
            original_artifact = artifact.read_text(encoding="utf-8")
            artifact.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "digest"):
                run_canary_result(
                    result, trust_verifier=self.CanaryVerifier()
                )
            artifact.write_text(original_artifact, encoding="utf-8")

            observation_path = root / "candidate-0.json"
            original_observation = observation_path.read_text(encoding="utf-8")
            observation = json.loads(original_observation)
            observation["execution_config_digest"] = "sha256:" + "b" * 64
            observation_path.write_text(json.dumps(observation), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "execution config"):
                run_canary_result(
                    result, trust_verifier=self.CanaryVerifier()
                )
            observation_path.write_text(original_observation, encoding="utf-8")

            forged = json.loads(result.read_text(encoding="utf-8"))
            forged["cost_reduction_ratio"] = 0.5
            result.write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "does not match"):
                run_canary_result(
                    result, trust_verifier=self.CanaryVerifier()
                )


if __name__ == "__main__":
    unittest.main()
