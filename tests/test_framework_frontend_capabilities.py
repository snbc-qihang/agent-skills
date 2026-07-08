#!/usr/bin/env python3
"""Regression checks for framework selection and frontend workflow coverage."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def publish_to_temp(test_case: unittest.TestCase) -> Path:
    temp_dir = tempfile.TemporaryDirectory()
    test_case.addCleanup(temp_dir.cleanup)
    publish_root = Path(temp_dir.name) / "publish"
    result = subprocess.run(
        [
            "python3",
            str(ROOT / "engineering-assistant" / "scripts" / "publish_plugin.py"),
            "--publish-root",
            str(publish_root),
            "--marketplace-path",
            str(publish_root / ".agents" / "plugins" / "marketplace.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    test_case.assertEqual(0, result.returncode, result.stderr + result.stdout)
    return publish_root / "plugins" / "engineering-assistant"


class FrameworkFrontendCapabilitiesTest(unittest.TestCase):
    def test_technology_selection_standard_and_policy_exist(self) -> None:
        standard_path = ROOT / "engineering-assistant" / "standards" / "framework-selection-standard.md"
        checklist_path = ROOT / "engineering-assistant" / "checklists" / "framework-selection-checklist.md"
        schema_path = ROOT / "engineering-assistant" / "schemas" / "framework-selection.schema.json"

        self.assertTrue(standard_path.exists(), "missing framework selection standard")
        self.assertTrue(checklist_path.exists(), "missing framework selection checklist")
        self.assertTrue(schema_path.exists(), "missing framework selection schema")

        standard = standard_path.read_text(encoding="utf-8")
        self.assertIn("FW1", standard)
        self.assertIn("技术选型", standard)
        self.assertIn("前端技术栈", standard)
        self.assertIn("测试框架", standard)
        self.assertIn("构建工具", standard)
        self.assertIn("mybatis-plus", standard)
        self.assertIn("JDBC", standard)
        self.assertIn("主动询问", standard)

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertIn("technology_categories", schema["required"])
        self.assertIn("review_status", schema["required"])

    def test_backend_skills_require_framework_selection_review(self) -> None:
        contract = json.loads((ROOT / "skills" / "code-development" / "contract.yaml").read_text(encoding="utf-8"))
        skill_md = (ROOT / "skills" / "code-development" / "SKILL.md").read_text(encoding="utf-8")
        stage_guidance = (ROOT / "skills" / "code-development" / "references" / "stage-guidance.md").read_text(encoding="utf-8")

        self.assertIn("technology_selection_policy", contract)
        policy = contract["technology_selection_policy"]
        self.assertTrue(policy["ask_user_when_unspecified"])
        self.assertIn("backend_framework", policy["categories"])
        self.assertIn("frontend_stack", policy["categories"])
        self.assertIn("test_framework", policy["categories"])
        self.assertEqual("mybatis-plus", policy["team_defaults"]["java_spring_persistence"])
        self.assertIn("JDBC", policy["requires_review"])

        self.assertIn("# References / Scripts", skill_md)
        self.assertIn("references/stage-guidance.md", skill_md)
        self.assertIn("FW1", stage_guidance)
        self.assertIn("mybatis-plus", json.dumps(policy, ensure_ascii=False))
        self.assertIn("JDBC", json.dumps(policy, ensure_ascii=False))
        self.assertTrue(policy["ask_user_when_unspecified"])

    def test_frontend_skills_and_workflows_exist(self) -> None:
        plugin_root = publish_to_temp(self)
        for skill_id in ["frontend-design", "frontend-development"]:
            self.assertTrue((ROOT / "skills" / skill_id / "SKILL.md").exists(), f"missing {skill_id} source skill")
            self.assertTrue((plugin_root / "skills" / skill_id / "SKILL.md").exists(), f"missing {skill_id} plugin skill")

        registry = json.loads((ROOT / "engineering-assistant" / "registry" / "skills.yaml").read_text(encoding="utf-8"))
        skill_ids = {item["skill_id"] for item in registry["skills"]}
        self.assertIn("frontend-design", skill_ids)
        self.assertIn("frontend-development", skill_ids)

        workflows = json.loads((ROOT / "engineering-assistant" / "registry" / "workflows.yaml").read_text(encoding="utf-8"))
        workflow_ids = {item["workflow_id"] for item in workflows["workflows"]}
        self.assertIn("frontend-only", workflow_ids)

        full_feature = json.loads((ROOT / "engineering-assistant" / "workflows" / "full-feature-development.yaml").read_text(encoding="utf-8"))
        full_nodes = [node["skill_id"] for node in full_feature["nodes"]]
        self.assertIn("frontend-design", full_nodes)
        self.assertIn("frontend-development", full_nodes)

    def test_frontend_standard_and_skill_contracts_cover_ui_work(self) -> None:
        standard = (ROOT / "engineering-assistant" / "standards" / "frontend-standard.md").read_text(encoding="utf-8")
        self.assertIn("FE1", standard)
        self.assertIn("组件", standard)
        self.assertIn("接口联调", standard)

        design_contract = json.loads((ROOT / "skills" / "frontend-design" / "contract.yaml").read_text(encoding="utf-8"))
        development_contract = json.loads((ROOT / "skills" / "frontend-development" / "contract.yaml").read_text(encoding="utf-8"))
        self.assertIn("frontend-design.md", [item["name"] for item in design_contract["outputs"]])
        self.assertIn("frontend-implementation-summary.md", [item["name"] for item in development_contract["outputs"]])

    def test_eval_runner_checks_framework_and_frontend_regressions(self) -> None:
        eval_runner = (ROOT / "engineering-assistant" / "scripts" / "run_skill_evals.py").read_text(encoding="utf-8")
        self.assertIn("technology_selection_policy", eval_runner)
        self.assertIn("mybatis-plus", eval_runner)
        self.assertIn("frontend_stack", eval_runner)
        self.assertIn("test_framework", eval_runner)
        self.assertIn("frontend-design", eval_runner)
        self.assertIn("frontend-development", eval_runner)


if __name__ == "__main__":
    unittest.main()
