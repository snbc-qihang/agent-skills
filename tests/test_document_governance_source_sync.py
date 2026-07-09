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
    return publish_root / "plugins" / "teamwork-engineering-assistant"


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
        self.assertTrue(contract["execution_gates"]["preflight_before_formal_artifacts"])
        self.assertTrue(contract["execution_gates"]["preflight_input_state_required"])
        self.assertTrue(contract["execution_gates"]["formal_generation_requires_ready"])
        self.assertTrue(contract["execution_gates"]["formal_document_metadata_required"])
        self.assertEqual("preflight_input_state", contract["preflight_runtime_gate"]["state_field"])
        self.assertEqual("preflight_input_state == ready", contract["preflight_runtime_gate"]["formal_generation_entry_condition"])
        self.assertIn("preflight_sequence", contract["required_information_policy"])
        self.assertEqual("preflight_input_state == ready", contract["required_information_policy"]["formal_generation_entry_condition"])
        self.assertIn("formal_artifacts_allowed_when", contract["required_information_policy"])

        output_schema = json.loads(output_schema_path.read_text(encoding="utf-8"))
        self.assertIn("preflight_input_state", output_schema["required"])
        self.assertEqual(["ready", "waiting_for_input", "waiting_for_human_review", "blocked"], output_schema["properties"]["preflight_input_state"]["enum"])
        self.assertIn("required_information_requests", output_schema["required"])
        self.assertIn("required_information_requests", output_schema["properties"])
        self.assertIn("document_metadata", output_schema["required"])
        self.assertIn("language", output_schema["required"])

        skill_md = skill_md_path.read_text(encoding="utf-8")
        self.assertIn("语言策略", skill_md)
        self.assertIn("未指定输出语言时", skill_md)
        self.assertIn("主动询问", skill_md)
        self.assertIn("preflight_input_state", skill_md)
        self.assertIn("formal_generation", skill_md)
        self.assertIn("waiting_for_input", skill_md)
        self.assertIn("执行门禁", skill_md)
        self.assertIn("preflight 未通过前不得生成正式阶段", skill_md)
        self.assertIn("不得登记正式阶段产物为已完成", skill_md)

        agent_meta = agent_meta_path.read_text(encoding="utf-8")
        self.assertIn("language_policy:", agent_meta)
        self.assertIn("preflight_gate:", agent_meta)
        self.assertIn("formal_generation_entry_condition: \"preflight_input_state == ready\"", agent_meta)
        self.assertIn("when_unspecified: \"ask_user\"", agent_meta)

        template = template_path.read_text(encoding="utf-8")
        self.assertIn("document_number:", template)
        self.assertIn("document_status:", template)
        self.assertIn("retention_policy:", template)

    def test_generator_preserves_standard_plugin_layout(self) -> None:
        generator = (ROOT / "generate_engineering_assistant_assets.py").read_text(encoding="utf-8")
        self.assertIn('"publish_plugin.py"', generator)
        self.assertIn('copy_tree(skills, plugin_root / "skills")', generator)
        self.assertIn('copy_tree(runtime, plugin_root / "engineering-assistant")', generator)
        self.assertNotIn('plugin_root / "standards"', generator)
        self.assertNotIn('plugin_root / "schemas"', generator)
        self.assertNotIn('plugin_root / "renderers"', generator)
        self.assertNotIn('plugin_root / "templates"', generator)
        self.assertNotIn('plugin_root / "marketplace.example.json"', generator)

    def test_upstream_capability_matrix_is_generated_and_packaged(self) -> None:
        matrix_path = ROOT / "engineering-assistant" / "checklists" / "upstream-main-capability-matrix.md"
        self.assertTrue(matrix_path.exists(), "missing upstream capability matrix")

        matrix = matrix_path.read_text(encoding="utf-8")
        self.assertIn("already-covered-by-teamwork", matrix)
        self.assertIn("needs-backport", matrix)
        self.assertIn("do-not-import", matrix)
        self.assertIn("402fe06", matrix)
        self.assertIn("7871cb5", matrix)
        self.assertIn("23b9745", matrix)
        self.assertIn("task SOP / skill shape", matrix)
        self.assertIn("prototype / frontend product gate", matrix)
        self.assertIn("feedback evolution", matrix)
        self.assertIn("manifest / distribution surface", matrix)
        self.assertIn("traceability / implementation control", matrix)
        self.assertIn("runtime governance", matrix)
        self.assertIn("scored eval / workflow / regression", matrix)
        self.assertIn("compatibility alias", matrix)
        self.assertIn("feedback evolution", matrix)
        self.assertIn("本轮将上述 4 个能力按 teamwork profile", matrix)

        plugin_root = publish_to_temp(self)
        self.assertTrue((plugin_root / "engineering-assistant" / "checklists" / "upstream-main-capability-matrix.md").exists())

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
            "preflight_input_state": "blocked",
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
        self.assertIn("succeeded 必须满足 preflight_input_state == ready", output)
        self.assertIn("document_metadata 缺少 document_number", output)

    def test_stage_result_validator_blocks_formal_artifacts_before_input_writeback(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_stage_run_result.py"
        invalid_result = {
            "run_id": "run-001",
            "skill_id": "detailed-design",
            "status": "waiting_for_input",
            "preflight_input_state": "waiting_for_input",
            "language": "zh-CN",
            "document_metadata": {},
            "artifacts": [
                {
                    "name": "detailed-design.md",
                    "path": "artifacts/detailed-design/detailed-design.md",
                    "artifact_type": "markdown",
                    "producer_skill": "detailed-design",
                }
            ],
            "quality_gates": [],
            "findings": [],
            "required_human_reviews": [],
            "required_information_requests": [
                {
                    "id": "REQ-INFO-001",
                    "blocking": True,
                    "questions": [
                        {
                            "id": "Q1",
                            "question": "请确认核心业务边界。",
                            "reason": "缺少边界时不能生成正式详细设计。",
                            "required": True,
                            "priority": "critical",
                            "expected_format": "JSON",
                        }
                    ],
                }
            ],
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
        self.assertIn("waiting_for_input 不得登记正式阶段产物", output)
        self.assertIn("必须在 artifacts 登记可填写的人工审阅 HTML", output)

    def test_skill_evals_assert_language_document_and_questions(self) -> None:
        eval_runner = ROOT / "engineering-assistant" / "scripts" / "run_skill_evals.py"
        text = eval_runner.read_text(encoding="utf-8")

        self.assertIn("language_policy", text)
        self.assertIn("preflight_input_state", text)
        self.assertIn("document_metadata", text)
        self.assertIn("required_information_requests", text)
        self.assertIn("missing_required_input", text)
        self.assertIn("questions", text)
        self.assertIn("docs/human-review", text)
        self.assertIn("不得生成或登记正式阶段", text)


if __name__ == "__main__":
    unittest.main()
