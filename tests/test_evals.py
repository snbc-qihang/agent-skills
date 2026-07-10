from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.eval_runner import run_canary_result, run_evals  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class EvalTests(unittest.TestCase):
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
                run_canary_result(path)

    def test_observed_canary_uses_real_evidence_and_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "observed-run.json"
            evidence.write_text('{"status":"observed"}\n', encoding="utf-8")
            result = root / "canary.json"
            result.write_text(
                json.dumps(
                    {
                        "simulation": False,
                        "product_repository": "product",
                        "baseline_ref": "base",
                        "candidate_ref": "candidate",
                        "quality_delta_points": -1.5,
                        "cost_reduction_ratio": 0.27,
                        "document_noise_reduction_ratio": 0.31,
                        "safety_violations": 0,
                        "evidence_refs": [str(evidence)],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual("passed", run_canary_result(result)["status"])


if __name__ == "__main__":
    unittest.main()
