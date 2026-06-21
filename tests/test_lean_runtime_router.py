#!/usr/bin/env python3
"""Regression checks for lean runtime routing, capability decisions, and agent feedback."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LeanRuntimeRouterTests(unittest.TestCase):
    def test_runtime_policy_schemas_exist_and_define_lightweight_routing(self) -> None:
        schema_dir = ROOT / "engineering-assistant" / "schemas"
        route_schema = json.loads((schema_dir / "runtime-route-decision.schema.json").read_text(encoding="utf-8"))
        persistence_schema = json.loads((schema_dir / "artifact-persistence-policy.schema.json").read_text(encoding="utf-8"))
        ledger_schema = json.loads((schema_dir / "capability-invocation-ledger.schema.json").read_text(encoding="utf-8"))
        health_schema = json.loads((schema_dir / "capability-health.schema.json").read_text(encoding="utf-8"))
        feedback_schema = json.loads((schema_dir / "assistant-run-feedback.schema.json").read_text(encoding="utf-8"))

        self.assertEqual(["context", "audit", "change", "release", "self_healing"], route_schema["properties"]["task_kind"]["enum"])
        self.assertEqual(["inline", "lite", "standard", "formal"], route_schema["properties"]["evidence_level"]["enum"])
        self.assertEqual(["inline", "ephemeral", "target_repo", "blocked"], route_schema["properties"]["persistence_mode"]["enum"])
        self.assertEqual("ephemeral", persistence_schema["properties"]["default_persistence_mode"]["const"])
        self.assertIn("capability_decisions", ledger_schema["required"])
        self.assertIn("health_checks", health_schema["required"])
        self.assertIn("consumed_by_agent", feedback_schema["required"])
        self.assertIn("target_repo_pollution_findings", feedback_schema["properties"])

    def test_workflows_publish_lean_runtime_router_policy(self) -> None:
        workflow = json.loads((ROOT / "engineering-assistant" / "workflows" / "coding-only.yaml").read_text(encoding="utf-8"))
        policy = workflow["lean_runtime_router_policy"]

        self.assertEqual("ephemeral", policy["artifact_persistence_policy"]["default_persistence_mode"])
        self.assertEqual(["inline", "lite", "standard", "formal"], policy["evidence_levels"])
        self.assertIn("target_repo", policy["persistence_modes"])
        self.assertIn("assistant-run-feedback.json", policy["required_feedback_artifacts"])
        self.assertIn("TARGET_REPO_ARTIFACT_POLLUTION", policy["pollution_markers"])

    def test_key_contracts_require_strategy_quality_and_feedback_gates(self) -> None:
        workflow_contract = json.loads((ROOT / "skills" / "workflow-orchestrator" / "contract.yaml").read_text(encoding="utf-8"))
        code_contract = json.loads((ROOT / "skills" / "code-development" / "contract.yaml").read_text(encoding="utf-8"))
        quality_contract = json.loads((ROOT / "skills" / "code-quality-governor" / "contract.yaml").read_text(encoding="utf-8"))
        review_contract = json.loads((ROOT / "skills" / "code-review" / "contract.yaml").read_text(encoding="utf-8"))

        self.assertIn("lean_runtime_router_policy", workflow_contract["workflow_runtime_policy"])
        self.assertTrue(workflow_contract["execution_gates"]["assistant_feedback_consumed"])
        self.assertTrue(code_contract["execution_gates"]["implementation_strategy_evaluation_required"])
        self.assertIn("DUPLICATE_CAPABILITY_RISK", code_contract["runtime_rule_markers"])
        self.assertIn("IMPLEMENTATION_STRATEGY_NOT_EVALUATED", code_contract["runtime_rule_markers"])
        for contract in [quality_contract, review_contract]:
            self.assertIn("simplification", contract["quality_audit_policy"]["required_dimensions"])
            self.assertIn("duplicate_capability", contract["quality_audit_policy"]["required_dimensions"])
            self.assertIn("comment_quality", contract["quality_audit_policy"]["required_dimensions"])

    def test_runtime_route_validator_blocks_unjustified_target_repo_persistence(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_runtime_route_decision.py"
        invalid = {
            "run_id": "run-001",
            "task_kind": "change",
            "evidence_level": "standard",
            "persistence_mode": "target_repo",
            "route_reason": "普通开发任务",
            "capability_decisions": [],
        }
        valid = {
            **invalid,
            "evidence_level": "formal",
            "explicit_user_request": True,
            "formal_evidence_reason": "用户要求正式交接留档",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_path = Path(temp_dir) / "invalid.json"
            valid_path = Path(temp_dir) / "valid.json"
            invalid_path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
            valid_path.write_text(json.dumps(valid, ensure_ascii=False), encoding="utf-8")
            blocked = subprocess.run(["python3", str(validator), str(invalid_path)], cwd=ROOT, text=True, capture_output=True, check=False)
            ok = subprocess.run(["python3", str(validator), str(valid_path)], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertNotEqual(0, blocked.returncode)
        self.assertIn("target_repo 持久化必须有明确用户要求或 formal evidence 理由", blocked.stderr + blocked.stdout)
        self.assertEqual(0, ok.returncode, ok.stderr + ok.stdout)

    def test_assistant_feedback_validator_requires_agent_consumption_and_pollution_markers(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_assistant_run_feedback.py"
        base_feedback = {
            "run_id": "run-001",
            "status": "succeeded",
            "route_decision": {
                "task_kind": "change",
                "evidence_level": "standard",
                "persistence_mode": "ephemeral",
            },
            "capability_decisions": [{"family": "code_context", "decision": "skip", "reason": "single-file change"}],
            "capability_health_checked": True,
            "target_repo_pollution_findings": [],
            "rule_violations": [],
            "darwin_required": False,
            "consumed_by_agent": True,
        }
        unconsumed = {**base_feedback, "consumed_by_agent": False}
        polluted_without_marker = {
            **base_feedback,
            "target_repo_pollution_findings": [{"path": "docs/tmp-plan.md", "type": "process_documentation"}],
        }
        polluted_with_marker = {
            **polluted_without_marker,
            "rule_violations": ["PROCESS_DOCUMENTATION_POLLUTION"],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = []
            for name, payload in [("unconsumed", unconsumed), ("bad", polluted_without_marker), ("ok", polluted_with_marker)]:
                path = Path(temp_dir) / f"{name}.json"
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                paths.append(path)
            unconsumed_result = subprocess.run(["python3", str(validator), str(paths[0])], cwd=ROOT, text=True, capture_output=True, check=False)
            bad_result = subprocess.run(["python3", str(validator), str(paths[1])], cwd=ROOT, text=True, capture_output=True, check=False)
            ok_result = subprocess.run(["python3", str(validator), str(paths[2])], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertNotEqual(0, unconsumed_result.returncode)
        self.assertIn("assistant-run-feedback 必须由 agent 消费", unconsumed_result.stderr + unconsumed_result.stdout)
        self.assertNotEqual(0, bad_result.returncode)
        self.assertIn("发现目标仓库过程产物污染时必须标记", bad_result.stderr + bad_result.stdout)
        self.assertEqual(0, ok_result.returncode, ok_result.stderr + ok_result.stdout)


if __name__ == "__main__":
    unittest.main()
