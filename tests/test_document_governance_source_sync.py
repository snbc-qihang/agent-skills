#!/usr/bin/env python3
"""Regression checks for document governance and plugin source sync."""

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


class DocumentGovernanceSourceSyncTest(unittest.TestCase):
    def test_source_contains_document_governance_contract(self) -> None:
        standard_path = ROOT / "engineering-assistant" / "standards" / "document-governance-standard.md"
        checklist_path = ROOT / "engineering-assistant" / "checklists" / "document-governance-checklist.md"
        schema_path = ROOT / "engineering-assistant" / "schemas" / "document-lifecycle.schema.json"

        self.assertTrue(standard_path.exists(), "missing document governance standard")
        self.assertTrue(checklist_path.exists(), "missing document governance checklist")
        self.assertTrue(schema_path.exists(), "missing document lifecycle schema")

        standard = standard_path.read_text(encoding="utf-8")
        self.assertIn("DG1", standard)
        self.assertIn("DG5", standard)
        self.assertIn("中间过程文档", standard)

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertIn("document_number", schema["required"])
        self.assertIn("document_status", schema["required"])
        self.assertIn("retention_policy", schema["required"])
        self.assertIn("document_class", schema["properties"])
        self.assertIn("retention_scope", schema["properties"])
        self.assertIn("canonical_path", schema["properties"])
        self.assertIn("DG23", standard)
        self.assertIn("formal_design", standard)
        self.assertIn("artifacts/_control", standard)
        self.assertIn("最终项目留存集合", standard)

    def test_document_retention_policy_separates_final_docs_from_agent_workspace(self) -> None:
        workflow = json.loads((ROOT / "engineering-assistant" / "workflows" / "full-feature-development.yaml").read_text(encoding="utf-8"))
        policy = workflow["design_governance_policy"]["document_retention_policy"]

        self.assertIn("formal_design", policy["persist_allowed_document_classes"])
        self.assertIn("agent_workspace", policy["transient_only_document_classes"])
        self.assertIn("docs/design/", policy["final_project_document_roots"])
        self.assertIn("artifacts/_control/", policy["agent_workspace_roots"])
        self.assertIn("研发完成后只保留", policy["completion_rule"])

    def test_source_contains_required_information_contract(self) -> None:
        standard_path = ROOT / "engineering-assistant" / "standards" / "required-information-standard.md"
        checklist_path = ROOT / "engineering-assistant" / "checklists" / "required-information-checklist.md"
        schema_path = ROOT / "engineering-assistant" / "schemas" / "required-information-request.schema.json"

        self.assertTrue(standard_path.exists(), "missing required information standard")
        self.assertTrue(checklist_path.exists(), "missing required information checklist")
        self.assertTrue(schema_path.exists(), "missing required information request schema")

        standard = standard_path.read_text(encoding="utf-8")
        self.assertIn("QIN1", standard)
        self.assertIn("主动询问", standard)
        self.assertIn("waiting_for_input", standard)

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertIn("request_id", schema["required"])
        self.assertIn("questions", schema["required"])
        self.assertIn("blocking", schema["required"])

    def test_lifecycle_validator_allows_only_formal_docs_to_persist(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_document_lifecycle.py"
        formal_document = {
            "document_number": "HLD-ORDER-20260621-001",
            "document_status": "final",
            "retention_policy": "persist",
            "retention_scope": "final_project_record",
            "document_class": "formal_design",
            "canonical_path": "docs/design/high-level-design.md",
            "title": "订单概要设计",
            "owner": "架构师",
            "source_artifacts": ["artifacts/high-level-design/high-level-design.md"],
        }
        agent_trace = {
            "document_number": "RPT-ORDER-20260621-001",
            "document_status": "final",
            "retention_policy": "persist",
            "retention_scope": "run_scoped",
            "document_class": "agent_workspace",
            "canonical_path": "artifacts/_control/workflow-trace.json",
            "title": "agent 工作痕迹",
            "owner": "workflow owner",
            "source_artifacts": ["artifacts/_control/workflow-trace.json"],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            formal_path = Path(temp_dir) / "formal.json"
            trace_path = Path(temp_dir) / "trace.json"
            formal_path.write_text(json.dumps(formal_document, ensure_ascii=False), encoding="utf-8")
            trace_path.write_text(json.dumps(agent_trace, ensure_ascii=False), encoding="utf-8")

            ok = subprocess.run(["python3", str(validator), str(formal_path)], cwd=ROOT, text=True, capture_output=True, check=False)
            blocked = subprocess.run(["python3", str(validator), str(trace_path)], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(0, ok.returncode, ok.stderr + ok.stdout)
        self.assertNotEqual(0, blocked.returncode)
        output = blocked.stderr + blocked.stdout
        self.assertIn("persist 文档必须声明 document_class", output)
        self.assertIn("artifacts/_control 或 HTML 目录不得作为正式留存源", output)

    def test_stage_result_validator_blocks_persisted_agent_artifacts(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_stage_run_result.py"
        stage_result = {
            "run_id": "run-001",
            "skill_id": "high-level-design",
            "status": "succeeded",
            "preflight_input_state": "ready",
            "language": "zh-CN",
            "document_metadata": {
                "document_number": "RPT-ORDER-20260621-002",
                "document_status": "final",
                "retention_policy": "persist",
                "retention_scope": "run_scoped",
                "document_class": "process_trace",
                "canonical_path": "artifacts/_control/traceability-matrix.json",
                "title": "追踪矩阵运行证据",
                "owner": "workflow owner",
                "source_artifacts": ["artifacts/_control/traceability-matrix.json"],
            },
            "artifacts": [],
            "quality_gates": [],
            "findings": [],
            "required_human_reviews": [],
            "required_information_requests": [],
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as tmp:
            json.dump(stage_result, tmp, ensure_ascii=False)
            tmp_path = Path(tmp.name)
        try:
            result = subprocess.run(["python3", str(validator), str(tmp_path)], cwd=ROOT, text=True, capture_output=True, check=False)
        finally:
            tmp_path.unlink(missing_ok=True)

        self.assertNotEqual(0, result.returncode)
        output = result.stderr + result.stdout
        self.assertIn("process_trace 只能作为运行期或 agent 工作产物", output)
        self.assertIn("canonical_path 必须位于正式 docs 目录", output)

    def test_generated_contracts_require_proactive_information_requests(self) -> None:
        contract_path = ROOT / "skills" / "detailed-design" / "contract.yaml"
        output_schema_path = ROOT / "skills" / "detailed-design" / "output.schema.json"
        skill_md_path = ROOT / "skills" / "detailed-design" / "SKILL.md"
        agent_meta_path = ROOT / "skills" / "detailed-design" / "agents" / "openai.yaml"
        template_path = ROOT / "skills" / "detailed-design" / "assets" / "artifact-template.md"

        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        self.assertIn("required_information_policy", contract)
        self.assertIn("required_information_requests", contract["workflow_interface"])
        self.assertIn("language_policy", contract)
        self.assertEqual("ask_user", contract["language_policy"]["when_unspecified"])
        self.assertTrue(contract["execution_gates"]["preflight_required_information"])
        self.assertTrue(contract["execution_gates"]["formal_document_metadata_required"])

        output_schema = json.loads(output_schema_path.read_text(encoding="utf-8"))
        self.assertIn("required_information_requests", output_schema["required"])
        self.assertIn("required_information_requests", output_schema["properties"])
        self.assertIn("document_metadata", output_schema["required"])
        self.assertIn("language", output_schema["required"])

        skill_md = skill_md_path.read_text(encoding="utf-8")
        self.assertIn("语言策略", skill_md)
        self.assertIn("未指定输出语言时", skill_md)
        self.assertIn("主动询问", skill_md)
        self.assertIn("waiting_for_input", skill_md)
        self.assertIn("执行门禁", skill_md)

        agent_meta = agent_meta_path.read_text(encoding="utf-8")
        self.assertIn("language_policy:", agent_meta)
        self.assertIn("when_unspecified: \"ask_user\"", agent_meta)

        template = template_path.read_text(encoding="utf-8")
        self.assertIn("document_number:", template)
        self.assertIn("document_status:", template)
        self.assertIn("retention_policy:", template)

    def test_generator_preserves_standard_plugin_layout(self) -> None:
        generator = (ROOT / "generator" / "legacy_generator.py").read_text(encoding="utf-8")
        self.assertIn('"publish_plugin.py"', generator)
        self.assertIn('copy_tree(skills, plugin_root / "skills")', generator)
        self.assertIn('copy_tree(runtime, plugin_root / "engineering-assistant")', generator)
        self.assertNotIn('plugin_root / "standards"', generator)
        self.assertNotIn('plugin_root / "schemas"', generator)
        self.assertNotIn('plugin_root / "renderers"', generator)
        self.assertNotIn('plugin_root / "templates"', generator)
        self.assertNotIn('plugin_root / "marketplace.example.json"', generator)

    def test_plugin_has_no_root_level_source_mirrors(self) -> None:
        plugin_root = publish_to_temp(self)
        forbidden = [
            "checklists",
            "evals",
            "profiles",
            "registry",
            "renderers",
            "schemas",
            "scripts",
            "standards",
            "templates",
            "workflows",
            "marketplace.example.json",
            "README.md",
        ]
        existing = [item for item in forbidden if (plugin_root / item).exists()]
        self.assertEqual([], existing)

    def test_lifecycle_validator_blocks_intermediate_persisted_docs(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_document_lifecycle.py"
        invalid_document = {
            "document_number": "DDD-ORDER-20260518-001",
            "document_status": "draft",
            "retention_policy": "persist",
            "title": "订单详细设计草稿",
            "owner": "研发负责人",
            "source_artifacts": ["artifacts/detailed-design/design.md"],
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as tmp:
            json.dump(invalid_document, tmp, ensure_ascii=False)
            tmp_path = Path(tmp.name)

        try:
            result = subprocess.run(
                ["python3", str(validator), str(tmp_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("中间过程文档不得 persist", result.stderr + result.stdout)

    def test_required_information_validator_blocks_empty_questions(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_required_information_request.py"
        invalid_request = {
            "request_id": "req-info-001",
            "run_id": "run-001",
            "skill_id": "detailed-design",
            "blocking": True,
            "status": "waiting_for_input",
            "questions": [],
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as tmp:
            json.dump(invalid_request, tmp, ensure_ascii=False)
            tmp_path = Path(tmp.name)

        try:
            result = subprocess.run(
                ["python3", str(validator), str(tmp_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("questions 不能为空", result.stderr + result.stdout)

    def test_stage_result_validator_blocks_missing_runtime_gates(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_stage_run_result.py"
        invalid_result = {
            "run_id": "run-001",
            "skill_id": "detailed-design",
            "status": "succeeded",
            "language": "",
            "document_metadata": {},
            "artifacts": [],
            "quality_gates": [],
            "findings": [],
            "required_human_reviews": [],
            "required_information_requests": [],
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as tmp:
            json.dump(invalid_result, tmp, ensure_ascii=False)
            tmp_path = Path(tmp.name)

        try:
            result = subprocess.run(
                ["python3", str(validator), str(tmp_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        self.assertNotEqual(0, result.returncode)
        output = result.stderr + result.stdout
        self.assertIn("language 不能为空", output)
        self.assertIn("document_metadata 缺少 document_number", output)

    def test_skill_evals_assert_language_document_and_questions(self) -> None:
        eval_runner = ROOT / "engineering-assistant" / "scripts" / "run_skill_evals.py"
        text = eval_runner.read_text(encoding="utf-8")

        self.assertIn("language_policy", text)
        self.assertIn("document_metadata", text)
        self.assertIn("required_information_requests", text)
        self.assertIn("missing_required_input", text)
        self.assertIn("questions", text)


if __name__ == "__main__":
    unittest.main()
