#!/usr/bin/env python3
"""Regression checks for preflight/design-governance workflow assets."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DesignGovernanceWorkflowTests(unittest.TestCase):
    def load_workflow(self, workflow_id: str) -> dict:
        return json.loads((ROOT / "engineering-assistant" / "workflows" / f"{workflow_id}.yaml").read_text(encoding="utf-8"))

    def test_design_workflows_publish_preflight_and_governance_policy(self) -> None:
        for workflow_id in ["full-feature-development", "design-only", "coding-only", "frontend-only"]:
            workflow = self.load_workflow(workflow_id)
            self.assertIn("preflight_runtime_policy", workflow)
            self.assertIn("design_governance_policy", workflow)
            preflight = workflow["preflight_runtime_policy"]
            self.assertEqual(preflight["state_field"], "preflight_input_state")
            self.assertIn("ready", preflight["states"])
            self.assertIn("waiting_for_input", preflight["states"])
            self.assertTrue(preflight["block_next_nodes"])
            governance = workflow["design_governance_policy"]
            self.assertIn("waiting_for_input_policy", governance)
            self.assertIn("knowledge_mining_policy", governance)
            self.assertIn("formal_design_artifacts", governance)
            self.assertIn("high-level-design.md", governance["formal_design_artifacts"])

    def test_workflow_orchestrator_contract_and_schema_require_preflight_state(self) -> None:
        contract = json.loads((ROOT / "skills" / "workflow-orchestrator" / "contract.yaml").read_text(encoding="utf-8"))
        self.assertIn("preflight_runtime_gate", contract)
        self.assertIn("design_governance_policy", contract)
        self.assertEqual(contract["preflight_runtime_gate"]["state_field"], "preflight_input_state")
        self.assertEqual(contract["required_information_policy"]["formal_generation_entry_condition"], "preflight_input_state == ready")

        schema = json.loads((ROOT / "skills" / "workflow-orchestrator" / "output.schema.json").read_text(encoding="utf-8"))
        self.assertIn("preflight_input_state", schema["required"])
        self.assertEqual(
            set(schema["properties"]["preflight_input_state"]["enum"]),
            {"ready", "waiting_for_input", "waiting_for_human_review", "blocked"},
        )

    def test_workflow_orchestrator_validate_output_script_carries_governance_guards(self) -> None:
        script = (ROOT / "skills" / "workflow-orchestrator" / "scripts" / "validate_output.py").read_text(encoding="utf-8")
        self.assertIn("preflight_input_state", script)
        self.assertIn("validator-summary.json", script)
        self.assertIn("defect-analysis.json", script)
        self.assertIn("不得产出正式设计工件", script)

    def test_stage_result_validator_rejects_formal_design_artifact_before_preflight_ready(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_stage_run_result.py"
        invalid_result = {
            "run_id": "run-001",
            "skill_id": "high-level-design",
            "status": "waiting_for_input",
            "preflight_input_state": "waiting_for_input",
            "language": "zh-CN",
            "document_metadata": {},
            "artifacts": [
                {
                    "name": "high-level-design.md",
                    "path": "artifacts/high-level-design/high-level-design.md",
                    "artifact_type": "markdown",
                    "producer_skill": "high-level-design",
                },
                {
                    "name": "human-review.html",
                    "path": "docs/human-review/run-001.html",
                    "artifact_type": "html",
                    "producer_skill": "high-level-design",
                },
            ],
            "quality_gates": [],
            "findings": [],
            "required_human_reviews": [],
            "required_information_requests": [
                {
                    "request_id": "req-001",
                    "run_id": "run-001",
                    "skill_id": "high-level-design",
                    "blocking": True,
                    "status": "waiting_for_input",
                    "questions": [
                        {
                            "id": "q-1",
                            "question": "请确认系统边界",
                            "reason": "缺少核心输入",
                            "required": True,
                            "priority": "critical",
                            "expected_format": "text",
                        }
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs" / "human-review").mkdir(parents=True)
            (root / "docs" / "human-review" / "run-001.html").write_text(
                '<html data-human-review-packet="true"><body><textarea></textarea><div id="answer-json"></div><button>下载 JSON</button></body></html>',
                encoding="utf-8",
            )
            (root / "artifacts" / "high-level-design").mkdir(parents=True)
            (root / "artifacts" / "high-level-design" / "high-level-design.md").write_text("# draft", encoding="utf-8")
            payload_path = root / "stage-result.json"
            payload_path.write_text(json.dumps(invalid_result, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(validator), str(payload_path)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("不得产出正式设计工件", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
