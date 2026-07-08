#!/usr/bin/env python3
"""Regression checks for v3 prototype gates and feedback-driven skill evolution."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V3PrototypeFeedbackEvolutionTests(unittest.TestCase):
    def test_version_and_new_skills_are_registered(self) -> None:
        manifest = json.loads((ROOT / "engineering-assistant" / "plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual("3.1.0", manifest["version"])

        registry = json.loads((ROOT / "engineering-assistant" / "registry" / "skills.yaml").read_text(encoding="utf-8"))
        skill_ids = {item["skill_id"] for item in registry["skills"]}
        for skill_id in [
            "product-prototype-design",
            "prototype-review-loop",
            "assistant-feedback-capture",
            "skill-evolution-review",
        ]:
            self.assertIn(skill_id, skill_ids)
            self.assertTrue((ROOT / "skills" / skill_id / "SKILL.md").exists())

    def test_frontend_workflows_require_prototype_review_before_design_and_implementation(self) -> None:
        for workflow_id in ["full-feature-development", "frontend-only", "design-only"]:
            workflow = json.loads((ROOT / "engineering-assistant" / "workflows" / f"{workflow_id}.yaml").read_text(encoding="utf-8"))
            node_ids = [node["node_id"] for node in workflow["nodes"]]
            self.assertIn("product-prototype-design", node_ids)
            self.assertIn("prototype-review-loop", node_ids)
            self.assertLess(node_ids.index("product-prototype-design"), node_ids.index("prototype-review-loop"))
            for downstream in ["frontend-design", "implementation-controller", "code-development", "frontend-development"]:
                if downstream in node_ids:
                    self.assertLess(node_ids.index("prototype-review-loop"), node_ids.index(downstream))
            self.assertEqual(3, workflow["prototype_review_policy"]["minimum_review_rounds"])

    def test_feedback_evolution_workflow_and_contracts_require_approval(self) -> None:
        workflow = json.loads((ROOT / "engineering-assistant" / "workflows" / "knowledge-review.yaml").read_text(encoding="utf-8"))
        self.assertEqual(
            ["assistant-feedback-capture", "engineering-knowledge-miner", "skill-evolution-review", "skill-quality-auditor"],
            [node["node_id"] for node in workflow["nodes"]],
        )

        capture = json.loads((ROOT / "skills" / "assistant-feedback-capture" / "contract.yaml").read_text(encoding="utf-8"))
        evolution = json.loads((ROOT / "skills" / "skill-evolution-review" / "contract.yaml").read_text(encoding="utf-8"))
        self.assertEqual("artifacts/_control/feedback/", capture["feedback_evolution_policy"]["target_project_feedback_root"])
        self.assertFalse(evolution["feedback_evolution_policy"]["auto_apply_to_formal_skills"])
        self.assertTrue(evolution["execution_gates"]["feedback_evolution_requires_human_approval"])

    def test_required_v3_schemas_exist(self) -> None:
        schema_dir = ROOT / "engineering-assistant" / "schemas"
        for name in [
            "feedback-event.schema.json",
            "feedback-inbox.schema.json",
            "skill-evolution-candidate.schema.json",
            "skill-patch-proposal.schema.json",
            "regression-case-candidate.schema.json",
            "third-party-capability-ledger.schema.json",
            "product-prototype-contract.schema.json",
            "prototype-review-report.schema.json",
            "delivery-loop-state.schema.json",
        ]:
            self.assertTrue((schema_dir / name).exists(), f"missing schema {name}")

    def test_feedback_evolution_validator_blocks_missing_evidence_and_unapproved_auto_apply(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_feedback_evolution.py"
        valid = {
            "mode": "evolution_review",
            "events": [
                {
                    "event_id": "fb-001",
                    "source_task_id": "task-001",
                    "source_run_id": "run-001",
                    "triggered_skill_id": "frontend-design",
                    "event_type": "user_correction",
                    "severity": "high",
                    "symptom": "用户三次纠正前端仍像 demo",
                    "user_correction_summary": "需要企业级产品原型和截图证据",
                    "evidence_paths": ["artifacts/_control/feedback/fb-001.json"],
                    "repeat_count": 3,
                    "recommended_action": "新增回归 eval",
                    "regression_case_candidate": True,
                    "consumed_by_evolution_review": True,
                    "verdict": "accepted_candidate",
                }
            ],
            "candidates": [
                {
                    "candidate_id": "cand-001",
                    "human_approval_required": True,
                    "auto_apply": False,
                    "verdict": "accepted_candidate",
                }
            ],
        }
        missing_evidence = {**valid, "events": [{**valid["events"][0], "evidence_paths": []}]}
        no_regression = {**valid, "events": [{**valid["events"][0], "regression_case_candidate": False}]}
        auto_apply = {**valid, "candidates": [{**valid["candidates"][0], "auto_apply": True}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = []
            for name, payload in [
                ("valid", valid),
                ("missing", missing_evidence),
                ("no-regression", no_regression),
                ("auto-apply", auto_apply),
            ]:
                path = Path(temp_dir) / f"{name}.json"
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                paths.append(path)

            ok = subprocess.run(["python3", str(validator), str(paths[0])], cwd=ROOT, text=True, capture_output=True, check=False)
            missing = subprocess.run(["python3", str(validator), str(paths[1])], cwd=ROOT, text=True, capture_output=True, check=False)
            regression = subprocess.run(["python3", str(validator), str(paths[2])], cwd=ROOT, text=True, capture_output=True, check=False)
            blocked_auto = subprocess.run(["python3", str(validator), str(paths[3])], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(0, ok.returncode, ok.stderr + ok.stdout)
        self.assertNotEqual(0, missing.returncode)
        self.assertIn("FEEDBACK_EVENT_MISSING_EVIDENCE", missing.stderr + missing.stdout)
        self.assertNotEqual(0, regression.returncode)
        self.assertIn("REGRESSION_CANDIDATE_REQUIRED", regression.stderr + regression.stdout)
        self.assertNotEqual(0, blocked_auto.returncode)
        self.assertIn("不允许 auto_apply", blocked_auto.stderr + blocked_auto.stdout)


if __name__ == "__main__":
    unittest.main()
