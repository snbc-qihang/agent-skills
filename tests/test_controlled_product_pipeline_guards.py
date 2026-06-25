#!/usr/bin/env python3
"""Regression checks for hard gates in the product-development plugin flow."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCRIPTS = ROOT / "engineering-assistant" / "scripts"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_script(script_name: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(PLUGIN_SCRIPTS / script_name), *args],
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class ControlledProductPipelineGuardTests(unittest.TestCase):
    def make_control_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        control = root / "artifacts" / "_control"
        control.mkdir(parents=True)
        write_json(control / "current-task.json", {"task_id": "aip", "status": "contract_compiled"})
        write_json(control / "design-contract.json", {"task_id": "aip", "goals": ["deliver product"]})
        write_json(control / "artifact-index.json", {"artifacts": {}})
        write_json(control / "open-questions.json", {"questions": []})
        (control / "task-context.agent.md").write_text("# Agent Context\n", encoding="utf-8")
        return root

    def make_strict_control_root(self) -> Path:
        root = self.make_control_root()
        control = root / "artifacts" / "_control"
        active_slice = {
            "schema_version": "2.0.0",
            "slice_id": "aip",
            "parent_task_id": "aip",
            "title": "AIP",
            "kind": "implementation_contract",
            "status": "contract_compiled",
            "control_artifacts": {
                "current_task": "artifacts/_control/current-task.json",
                "current_subtask": "artifacts/_control/current-subtask.json",
                "quality_contract": "artifacts/_control/quality-contract.json",
            },
            "updated_at": "2026-06-25T00:00:00Z",
        }
        write_json(
            control / "current-task.json",
            {
                "schema_version": "2.0.0",
                "task_id": "aip",
                "title": "AIP",
                "language": "zh-CN",
                "workflow_id": "contract-driven-development",
                "status": "contract_compiled",
                "control_dir": "artifacts/_control",
                "created_at": "2026-06-25T00:00:00Z",
                "updated_at": "2026-06-25T00:00:00Z",
                "current_contracts": {},
                "active_slice": active_slice,
            },
        )
        write_json(control / "current-subtask.json", active_slice)
        write_json(
            control / "design-contract.json",
            {
                "schema_version": "2.0.0",
                "task_id": "aip",
                "source_design": "docs/design.md",
                "source_checksum": "sha256:test",
                "goals": ["deliver product"],
                "acceptance_criteria": ["validated"],
                "module_boundaries": {"allowed_from_design": ["backend/"]},
                "assumptions": ["test fixture"],
            },
        )
        write_json(
            control / "implementation-contract.json",
            {
                "schema_version": "2.0.0",
                "task_id": "aip",
                "allowed_modules": ["backend/"],
                "forbidden_modules": ["frontend/"],
                "required_files_or_patterns": ["backend/"],
                "architecture_rules": ["Follow architecture"],
                "required_tests": ["unit"],
                "done_conditions": ["validated"],
                "expected_interfaces": ["api"],
                "expected_services": ["service"],
                "expected_repositories_or_mappers": ["mapper"],
                "technology_adoption_contract": {"required_indicators": [], "forbidden_indicators": [], "minimum_required_indicators": 0},
            },
        )
        write_json(
            control / "quality-contract.json",
            {
                "schema_version": "2.0.0",
                "task_id": "aip",
                "required_commands": [{"id": "unit", "command": "python3 -c 'print(1)'", "required": True}],
                "required_evidence": ["quality_commands"],
                "quality_gates": ["build_lint_test"],
                "repair_policy": {"max_attempts": 2},
            },
        )
        return root

    def test_strict_control_contracts_block_unknown_fields_and_placeholder_commands(self) -> None:
        root = self.make_strict_control_root()
        control = root / "artifacts" / "_control"
        design = json.loads((control / "design-contract.json").read_text(encoding="utf-8"))
        design["unexpected"] = True
        write_json(control / "design-contract.json", design)
        quality = json.loads((control / "quality-contract.json").read_text(encoding="utf-8"))
        quality["required_commands"] = [{"id": "todo", "command": "TODO", "required": True}]
        write_json(control / "quality-contract.json", quality)

        result = run_script("validate_strict_control_contracts.py", "--root", str(root))

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("unknown fields", output)
        self.assertIn("placeholder command", output)

    def test_strict_control_contracts_accept_v2_control_surface(self) -> None:
        root = self.make_strict_control_root()

        result = run_script("validate_strict_control_contracts.py", "--root", str(root))

        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual("pass", json.loads(result.stdout)["status"])

    def test_contract_control_blocks_weak_implementation_contract(self) -> None:
        root = self.make_control_root()
        control = root / "artifacts" / "_control"
        write_json(
            control / "implementation-contract.json",
            {
                "task_id": "aip",
                "allowed_modules": ["backend/"],
                "forbidden_modules": [".git/"],
                "architecture_rules": ["Follow architecture"],
                "done_conditions": ["Design-to-code validation passes."],
            },
        )
        write_json(control / "quality-contract.json", {"required_commands": []})

        result = run_script("validate_contract_control.py", str(root))

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("expected_interfaces", output)
        self.assertIn("required_tests", output)
        self.assertIn("required_commands", output)

    def test_design_to_code_validation_blocks_major_findings(self) -> None:
        root = self.make_control_root()
        control = root / "artifacts" / "_control"
        write_json(
            control / "implementation-contract.json",
            {
                "allowed_modules": ["backend/contexts/identity-access"],
                "forbidden_modules": ["node_modules/"],
                "required_files_or_patterns": [],
            },
        )
        write_json(control / "changed-files-report.json", {"changed_files": ["frontend/console-web/src/app/App.tsx"]})

        result = run_script("validate_design_to_code.py", "--root", str(root))

        self.assertNotEqual(0, result.returncode)
        report = json.loads((control / "design-to-code-validation.json").read_text(encoding="utf-8"))
        self.assertEqual("block", report["status"])
        self.assertEqual("major", report["findings"][0]["severity"])

    def test_traceability_report_builds_structured_html_for_humans(self) -> None:
        root = self.make_control_root()
        control = root / "artifacts" / "_control"
        write_json(
            control / "design-contract.json",
            {
                "task_id": "aip",
                "source_design": "artifacts/detailed-design/aip/detailed-design.md",
                "goals": ["登录用户可以查询导出任务状态"],
                "acceptance_criteria": ["REQ-001 查询导出任务状态必须返回当前处理进度"],
            },
        )
        write_json(
            control / "implementation-contract.json",
            {
                "task_id": "aip",
                "allowed_modules": ["backend/contexts/export"],
                "required_tests": ["ExportTaskServiceTest"],
            },
        )
        write_json(control / "quality-contract.json", {"required_evidence": ["traceability_matrix"]})
        write_json(control / "changed-files-report.json", {"changed_files": ["backend/contexts/export/ExportTaskService.java"]})
        write_json(control / "design-to-code-validation.json", {"status": "pass", "findings": []})
        mapping = root / "artifacts" / "code-development" / "design-to-code-mapping.yaml"
        mapping.parent.mkdir(parents=True)
        mapping.write_text(
            "- requirement: REQ-001\n  design: detailed-design.md#查询导出任务状态\n  code: backend/contexts/export/ExportTaskService.java\n  test: backend/contexts/export/ExportTaskServiceTest.java\n",
            encoding="utf-8",
        )

        result = run_script("build_traceability_report.py", "--root", str(root))

        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        matrix = json.loads((control / "traceability-matrix.json").read_text(encoding="utf-8"))
        html = (root / "docs" / "human-readable" / "traceability-report.html").read_text(encoding="utf-8")
        self.assertEqual("pass", matrix["rows"][0]["validation_status"])
        self.assertIn("backend/contexts/export/ExportTaskService.java", html)
        self.assertIn('data-human-readable-report="traceability"', html)
        self.assertIn("追踪矩阵", html)
        self.assertNotIn("# 需求-设计-代码追踪报告", html)

    def test_quality_runner_blocks_missing_required_commands(self) -> None:
        root = self.make_control_root()
        control = root / "artifacts" / "_control"
        write_json(control / "quality-contract.json", {"required_commands": []})

        result = run_script("run_quality_commands.py", "--root", str(root))

        self.assertNotEqual(0, result.returncode)
        report = json.loads((control / "quality-run-report.json").read_text(encoding="utf-8"))
        self.assertEqual("block", report["status"])
        self.assertIn("no required quality commands", report["errors"][0])

    def test_quality_contract_runner_blocks_required_failure_even_when_make_validate_passes(self) -> None:
        root = self.make_control_root()
        control = root / "artifacts" / "_control"
        write_json(
            control / "quality-contract.json",
            {
                "task_id": "refactor-readiness",
                "required_commands": [
                    {"id": "make-validate", "command": "sh -c 'echo make validate passed'", "required": True},
                    {"id": "backend-required-test", "command": "python3 -c 'import sys; sys.exit(2)'", "required": True},
                ],
            },
        )

        result = run_script("run_quality_contract.py", "--root", str(root))

        self.assertNotEqual(0, result.returncode)
        report = json.loads((control / "quality-run-report.json").read_text(encoding="utf-8"))
        self.assertEqual("block", report["status"])
        self.assertTrue(report["summary"]["make_validate_passed"])
        self.assertEqual(1, report["summary"]["required_failed"])
        finding_ids = {item["id"] for item in report["findings"]}
        self.assertIn("QUALITY-CONTRACT-REQUIRED-FAILED-DESPITE-MAKE-VALIDATE", finding_ids)

        task = json.loads((control / "current-task.json").read_text(encoding="utf-8"))
        subtask = json.loads((control / "current-subtask.json").read_text(encoding="utf-8"))
        questions = json.loads((control / "open-questions.json").read_text(encoding="utf-8"))
        self.assertEqual("blocked", task["status"])
        self.assertEqual("blocked", task["active_slice"]["status"])
        self.assertEqual("blocked", subtask["status"])
        self.assertTrue(any(item["id"] == "QR-BLOCKER-001" and item["blocking"] for item in questions["questions"]))

    def test_quality_contract_runner_records_success_and_resolves_quality_blocker(self) -> None:
        root = self.make_control_root()
        control = root / "artifacts" / "_control"
        write_json(
            control / "open-questions.json",
            {"questions": [{"id": "QR-BLOCKER-001", "severity": "blocker", "status": "open", "blocking": True}]},
        )
        write_json(
            control / "quality-contract.json",
            {"task_id": "refactor-readiness", "required_commands": [{"id": "unit", "command": "python3 -c 'print(1)'", "required": True}]},
        )

        result = run_script("run_quality_contract.py", "--root", str(root))

        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        report = json.loads((control / "quality-run-report.json").read_text(encoding="utf-8"))
        self.assertEqual("pass", report["status"])
        self.assertEqual(0, report["results"][0]["exit_code"])
        questions = json.loads((control / "open-questions.json").read_text(encoding="utf-8"))
        blocker = next(item for item in questions["questions"] if item["id"] == "QR-BLOCKER-001")
        self.assertEqual("resolved", blocker["status"])
        self.assertFalse(blocker["blocking"])

    def test_quality_contract_runner_refreshes_project_quality_inputs_after_control_sync(self) -> None:
        root = self.make_control_root()
        control = root / "artifacts" / "_control"
        quality_scripts = root / "scripts" / "quality"
        quality_scripts.mkdir(parents=True)
        (quality_scripts / "generate_quality_inputs.py").write_text(
            "from pathlib import Path\n"
            "Path('artifacts/code-quality').mkdir(parents=True, exist_ok=True)\n"
            "Path('artifacts/code-quality/refresh-order.txt').write_text('inputs\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        (quality_scripts / "generate_code_review_artifacts.py").write_text(
            "from pathlib import Path\n"
            "path = Path('artifacts/code-quality/refresh-order.txt')\n"
            "path.write_text(path.read_text(encoding='utf-8') + 'review\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        write_json(
            control / "quality-contract.json",
            {"task_id": "refactor-readiness", "required_commands": [{"id": "unit", "command": "python3 -c 'print(1)'", "required": True}]},
        )

        result = run_script("run_quality_contract.py", "--root", str(root))

        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual("inputs\nreview\n", (root / "artifacts/code-quality/refresh-order.txt").read_text(encoding="utf-8"))
        report = json.loads((control / "quality-run-report.json").read_text(encoding="utf-8"))
        self.assertEqual("pass", report["status"])

    def test_rule_index_excludes_nested_generated_dependency_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs").mkdir()
            (root / "docs" / "standard.md").write_text("- 必须执行真实环境验收。\n", encoding="utf-8")
            nested = root / "frontend" / "console-web" / "node_modules" / "pkg"
            nested.mkdir(parents=True)
            (nested / "README.md").write_text("- must not leak dependency docs into project rules.\n", encoding="utf-8")

            result = run_script("build_rule_index.py", "--root", str(root), "--max-rules-per-pack", "20")

            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            registry = json.loads((root / "artifacts" / "rule-governance" / "rule-registry.json").read_text(encoding="utf-8"))
            sources = [rule["source"]["path"] for rule in registry["rules"]]
            self.assertNotIn("frontend/console-web/node_modules/pkg/README.md", sources)
            self.assertIn("docs/standard.md", sources)

    def test_stage_result_validator_blocks_succeeded_with_blocking_evidence(self) -> None:
        validator = ROOT / "engineering-assistant" / "scripts" / "validate_stage_run_result.py"
        invalid_result = {
            "run_id": "run-001",
            "skill_id": "code-review",
            "status": "succeeded",
            "language": "zh-CN",
            "document_metadata": {
                "document_number": "CRR-AIP-20260520-001",
                "document_status": "final",
                "retention_policy": "keep_until_run_end",
                "title": "Code Review",
                "owner": "code-review-agent",
                "source_artifacts": ["artifacts/code-development/implementation-summary.md"],
            },
            "artifacts": [],
            "quality_gates": [{"name": "Product completion", "result": "block_for_completion"}],
            "findings": [{"id": "BLOCK-001", "severity": "blocker", "summary": "业务流程未完成"}],
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
        self.assertIn("succeeded 不允许包含 blocker/major finding", output)
        self.assertIn("succeeded 不允许包含阻断质量门禁", output)


if __name__ == "__main__":
    unittest.main()
