#!/usr/bin/env python3
"""Regression checks for design governance workflow gates."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMAL_DESIGN_ARTIFACTS = {
    "high-level-design.md",
    "detailed-design.md",
    "database-design.md",
    "redis-design.md",
    "mq-design.xlsx",
    "interface-contracts.yaml",
    "test-strategy.md",
}
CONTROL_ARTIFACTS = {
    "information-inventory.json",
    "context-source-map.json",
    "missing-information-list.json",
    "required-information-request.json",
    "design-objective-plan.md",
    "scope-and-non-goals.yaml",
    "user-confirmed-facts.json",
    "design-direction-decision.md",
    "workflow-trace.json",
    "resume-point.json",
}
SPECIFIC_BUSINESS_FACTS = [
    "queue.franchise",
    "VEMISSUE.topic",
    "changeDeliverStatus",
    "changePendingPaymentStatus",
    "paySuccessOrder",
    "getVemIdAndTenantIdListForFacDataPermission",
    "辛强睿",
]


def workflow_payload(status: str, preflight_state: str, artifacts: list[dict[str, str]]) -> dict:
    return {
        "run_id": "run-design-governance-001",
        "skill_id": "workflow-orchestrator",
        "status": status,
        "preflight_input_state": preflight_state,
        "language": "zh-CN",
        "trace_id": "trace-design-governance-001",
        "document_metadata": {
            "document_number": "RPT-WORKFLOW-20260611-001",
            "document_status": "waiting_for_input" if preflight_state != "ready" else "draft",
            "retention_policy": "keep_until_run_end",
            "title": "workflow governance test",
            "owner": "workflow owner",
            "source_artifacts": [],
        },
        "artifacts": [
            {
                "name": item["name"],
                "path": item.get("path", item["name"]),
                "artifact_type": item.get("artifact_type", "json"),
                "producer_skill": "workflow-orchestrator",
            }
            for item in artifacts
        ],
        "quality_gates": [],
        "findings": [],
        "required_human_reviews": [],
        "required_information_requests": [],
        "repair_summary": {"attempts": 0, "max_attempts": 0, "status": "not_needed"},
        "next_action": "blocked" if preflight_state != "ready" else "complete",
    }


class DesignGovernanceWorkflowTests(unittest.TestCase):
    def test_workflow_contract_exposes_design_governance_state_machine(self) -> None:
        contract = json.loads((ROOT / "skills" / "workflow-orchestrator" / "contract.yaml").read_text(encoding="utf-8"))
        policy = contract["design_governance_policy"]
        self.assertIn("intake_collecting", policy["states"])
        self.assertIn("tl_rule_candidate_pending", policy["states"])
        self.assertTrue(policy["hard_gates"]["information_complete_before_formal_generation"])
        self.assertTrue(policy["hard_gates"]["self_review_passed_before_human_review"])
        self.assertEqual(set(policy["waiting_for_input_policy"]["forbidden_artifacts"]), FORMAL_DESIGN_ARTIFACTS)
        self.assertTrue(CONTROL_ARTIFACTS.issubset(set(policy["waiting_for_input_policy"]["allowed_artifacts"])))
        self.assertFalse(policy["knowledge_mining_policy"]["auto_apply_to_plugin"])
        self.assertTrue(policy["knowledge_mining_policy"]["tl_review_required"])
        for field in ["original_user_change", "generalized_rule", "scope", "non_scope", "tl_review_status"]:
            self.assertIn(field, policy["knowledge_mining_policy"]["required_fields"])

    def test_workflow_assets_block_formal_design_artifacts_before_preflight_ready(self) -> None:
        workflow = json.loads((ROOT / "engineering-assistant" / "workflows" / "design-only.yaml").read_text(encoding="utf-8"))
        preflight = workflow["preflight_runtime_policy"]
        self.assertEqual(set(preflight["forbidden_formal_artifacts_when_waiting_for_input"]), FORMAL_DESIGN_ARTIFACTS)
        self.assertTrue(CONTROL_ARTIFACTS.issubset(set(preflight["allowed_artifacts_when_waiting_for_input"])))
        self.assertTrue(workflow["design_governance_policy"]["review_feedback_policy"]["classification_required"])
        self.assertEqual(
            "incremental_patch_affected_artifacts",
            workflow["design_governance_policy"]["review_feedback_policy"]["default_update_strategy"],
        )

    def test_workflow_validator_rejects_formal_design_artifact_when_waiting_for_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_path = Path(temp_dir) / "payload.json"
            payload_path.write_text(
                json.dumps(
                    workflow_payload(
                        "waiting_for_input",
                        "waiting_for_input",
                        [{"name": "required-information-request.json"}, {"name": "detailed-design.md", "artifact_type": "markdown"}],
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                ["python3", str(ROOT / "skills" / "workflow-orchestrator" / "scripts" / "validate_output.py"), str(payload_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("preflight 未 ready 时不得生成或登记正式设计文档", result.stderr + result.stdout)

    def test_team_plugin_non_eval_assets_do_not_embed_current_business_facts(self) -> None:
        scanned_roots = [ROOT / "skills", ROOT / "engineering-assistant"]
        offenders: list[str] = []
        for root in scanned_roots:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(ROOT).as_posix()
                if "/evals/" in rel or rel.endswith(".xlsx") or rel.endswith(".png") or rel.endswith(".zip"):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for term in SPECIFIC_BUSINESS_FACTS:
                    if term in text:
                        offenders.append(f"{rel}: {term}")
        self.assertEqual([], offenders)

    def test_delivery_document_records_current_design_governance_plan_and_version(self) -> None:
        delivery = (ROOT / "engineering-assistant-delivery.md").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "engineering-assistant" / "plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual("1.1.0.0", manifest["version"])
        self.assertIn("当前插件版本：`1.1.0.0`", delivery)
        self.assertIn("短 SOP 入口", delivery)
        self.assertIn("可循环的设计治理工作流", delivery)
        self.assertIn("# 8.1 设计治理闭环与防废稿门禁", delivery)
        self.assertIn("preflight_input_state != ready", delivery)
        self.assertIn("不得生成或登记正式设计文档", delivery)
        self.assertIn("TL 审核", delivery)


if __name__ == "__main__":
    unittest.main()
