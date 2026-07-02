#!/usr/bin/env python3
"""Regression checks for document spine, subagent monitoring, and product-plan alignment governance."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExecutionGovernanceSpineTests(unittest.TestCase):
    def test_workflow_publishes_document_spine_monitoring_and_plan_alignment_policies(self) -> None:
        workflow = json.loads((ROOT / "engineering-assistant" / "workflows" / "full-feature-development.yaml").read_text(encoding="utf-8"))
        policy = workflow["lean_runtime_router_policy"]

        document_policy = policy["document_spine_policy"]
        monitor_policy = policy["agent_execution_monitor_policy"]
        alignment_policy = policy["product_plan_alignment_policy"]

        self.assertEqual("docs/00-index/product-planning-spine.md", document_policy["spine_artifact"])
        self.assertEqual("docs/00-index/document-index.json", document_policy["machine_index"])
        self.assertEqual(12, document_policy["active_document_budget"])
        self.assertIn("不得因 docs 增长而全量扫读", document_policy["active_context_rule"])
        self.assertIn("SUBAGENT_UNVERIFIED_SUCCESS", monitor_policy["failure_markers"])
        self.assertIn("observed_evidence", monitor_policy["strict_check_rule"])
        self.assertTrue(alignment_policy["required_before_task_close"])
        self.assertIn("LOCAL_OPTIMUM_ONLY", alignment_policy["drift_markers"])

    def test_contracts_gate_document_spine_monitoring_and_post_task_alignment(self) -> None:
        workflow_contract = json.loads((ROOT / "skills" / "workflow-orchestrator" / "contract.yaml").read_text(encoding="utf-8"))
        code_contract = json.loads((ROOT / "skills" / "code-development" / "contract.yaml").read_text(encoding="utf-8"))
        quality_contract = json.loads((ROOT / "skills" / "code-quality-governor" / "contract.yaml").read_text(encoding="utf-8"))

        for contract in [workflow_contract, code_contract, quality_contract]:
            self.assertTrue(contract["execution_gates"]["document_spine_context_required"])
            self.assertTrue(contract["execution_gates"]["agent_execution_monitor_required_for_delegation"])
            self.assertTrue(contract["execution_gates"]["post_task_plan_alignment_required"])
            self.assertIn("DOC_SPRAWL_RISK", contract["runtime_rule_markers"])
            self.assertIn("PRODUCT_PLAN_DRIFT", contract["runtime_rule_markers"])

        self.assertIn("SUBAGENT_UNVERIFIED_SUCCESS", workflow_contract["runtime_rule_markers"])
        self.assertIn("SUBAGENT_EVIDENCE_MISSING", quality_contract["runtime_rule_markers"])

    def test_schema_files_exist_for_planning_spine_monitoring_and_alignment(self) -> None:
        schema_dir = ROOT / "engineering-assistant" / "schemas"
        spine = json.loads((schema_dir / "planning-spine.schema.json").read_text(encoding="utf-8"))
        monitor = json.loads((schema_dir / "agent-execution-monitor.schema.json").read_text(encoding="utf-8"))
        alignment = json.loads((schema_dir / "post-task-plan-alignment.schema.json").read_text(encoding="utf-8"))

        self.assertIn("active_documents", spine["required"])
        self.assertEqual(12, spine["properties"]["active_documents"]["maxItems"])
        self.assertIn("observed_evidence", monitor["properties"]["agents"]["items"]["properties"])
        self.assertIn("consumed_by_orchestrator", monitor["required"])
        self.assertIn("alignment_status", alignment["required"])
        self.assertIn("drift_detected", alignment["properties"]["alignment_status"]["enum"])

    def test_agent_execution_monitor_blocks_self_report_only_success(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_agent_execution_monitor.py"
        bad = {
            "run_id": "run-001",
            "task_id": "task-001",
            "agents": [
                {
                    "agent_id": "worker-1",
                    "role": "reviewer",
                    "assigned_scope": ["review backend"],
                    "forbidden_scope": ["edit files"],
                    "expected_outputs": ["findings"],
                    "required_checks": ["tests inspected"],
                    "status": "succeeded",
                    "self_report": "all good",
                }
            ],
            "monitor_checks": [{"check_id": "scope_adherence"}],
            "consumed_by_orchestrator": False,
        }
        good = {
            **bad,
            "agents": [
                {
                    **bad["agents"][0],
                    "observed_evidence": [{"type": "test_output", "path": ".run-artifacts/engineering-assistant/run-001/tests.log"}],
                    "independent_verification": True,
                }
            ],
            "monitor_checks": [
                {"check_id": "scope_adherence"},
                {"check_id": "evidence_returned"},
                {"check_id": "independent_verification"},
                {"check_id": "artifact_consumed_by_orchestrator"},
                {"check_id": "no_unverified_success_claim"},
            ],
            "consumed_by_orchestrator": True,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            bad_path = Path(temp_dir) / "bad.json"
            good_path = Path(temp_dir) / "good.json"
            bad_path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
            good_path.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
            bad_result = subprocess.run(["python3", str(validator), str(bad_path)], cwd=ROOT, text=True, capture_output=True, check=False)
            good_result = subprocess.run(["python3", str(validator), str(good_path)], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertNotEqual(0, bad_result.returncode)
        self.assertIn("SUBAGENT_EVIDENCE_MISSING", bad_result.stderr + bad_result.stdout)
        self.assertIn("MONITOR_CHECK_NOT_CONSUMED", bad_result.stderr + bad_result.stdout)
        self.assertEqual(0, good_result.returncode, good_result.stderr + good_result.stdout)

    def test_post_task_plan_alignment_blocks_local_only_completion_and_unindexed_docs(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_post_task_plan_alignment.py"
        bad = {
            "run_id": "run-001",
            "product_goal": "完整订阅能力",
            "capability_path": "billing/subscription/renewal",
            "accepted_scope": ["renewal API"],
            "out_of_scope": [],
            "integration_points": ["payment", "notification"],
            "next_plan_update": "docs/00-index/product-planning-spine.md",
            "alignment_status": "drift_detected",
            "drift_findings": [{"marker": "LOCAL_OPTIMUM_ONLY", "resolved": False}],
            "document_changes": [{"path": "docs/design/renewal.md", "document_index_updated": False}],
            "checked_by": "workflow-orchestrator",
        }
        good = {
            **bad,
            "alignment_status": "aligned_with_followups",
            "drift_findings": [{"marker": "LOCAL_OPTIMUM_ONLY", "resolved": True}],
            "document_changes": [{"path": "docs/design/renewal.md", "document_index_updated": True, "replaces": "docs/design/old-renewal.md", "superseded_previous": True}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            bad_path = Path(temp_dir) / "bad.json"
            good_path = Path(temp_dir) / "good.json"
            bad_path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
            good_path.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
            bad_result = subprocess.run(["python3", str(validator), str(bad_path)], cwd=ROOT, text=True, capture_output=True, check=False)
            good_result = subprocess.run(["python3", str(validator), str(good_path)], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertNotEqual(0, bad_result.returncode)
        self.assertIn("MISSING_POST_TASK_ALIGNMENT", bad_result.stderr + bad_result.stdout)
        self.assertIn("UNINDEXED_FORMAL_DOC", bad_result.stderr + bad_result.stdout)
        self.assertEqual(0, good_result.returncode, good_result.stderr + good_result.stdout)


if __name__ == "__main__":
    unittest.main()
