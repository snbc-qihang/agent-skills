#!/usr/bin/env python3
"""Regression checks for plugin efficiency and deeper project quality gates."""

from __future__ import annotations

import hashlib
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


def fingerprint(items: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(items)).encode("utf-8")).hexdigest()


def git_untracked(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def run_script(script_name: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(PLUGIN_SCRIPTS / script_name), *args],
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def make_contract_root(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=False)
    control = root / "artifacts" / "_control"
    control.mkdir(parents=True)
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
            "goals": ["deliver"],
            "acceptance_criteria": ["validated"],
            "module_boundaries": {"allowed_from_design": ["backend/"]},
            "assumptions": ["test fixture"],
        },
    )
    write_json(control / "artifact-index.json", {"artifacts": {}})
    write_json(control / "open-questions.json", {"questions": []})
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
            "required_commands": [{"id": "noop", "command": "python3 -c 'print(1)'", "required": True}],
            "required_evidence": ["quality_commands"],
            "quality_gates": ["build_lint_test"],
            "repair_policy": {"max_attempts": 2},
        },
    )
    (control / "task-context.agent.md").write_text("# Agent Context\n", encoding="utf-8")
    write_json(control / "changed-files-report.json", {"changed_files": [], "workspace_fingerprint": ""})
    changed = git_untracked(root)
    write_json(control / "changed-files-report.json", {"base": "HEAD", "changed_files": changed, "workspace_fingerprint": fingerprint(changed)})


class PluginPerformanceOptimizationTests(unittest.TestCase):
    def test_readonly_control_plane_detects_stale_changed_files_without_mutating_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_contract_root(root)
            report = root / "artifacts" / "_control" / "changed-files-report.json"
            stale_payload = json.loads(report.read_text(encoding="utf-8"))
            stale_payload["workspace_fingerprint"] = "stale"
            report.write_text(json.dumps(stale_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            before = report.read_text(encoding="utf-8")

            result = run_script("validate_control_plane_readonly.py", "--root", str(root))

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, report.read_text(encoding="utf-8"))
            payload = json.loads(result.stdout)
            self.assertEqual("block", payload["status"])
            self.assertIn("stale changed-files report fingerprint", payload["findings"][0]["reason"])

    def test_controlled_runner_audit_readonly_does_not_write_repair_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_contract_root(root)
            report = root / "artifacts" / "_control" / "changed-files-report.json"
            before = report.read_text(encoding="utf-8")

            result = run_script("run_controlled_task.py", "--root", str(root), "--mode", "audit-readonly")

            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            self.assertFalse((root / "artifacts" / "_control" / "repair-attempts.json").exists())
            self.assertEqual(before, report.read_text(encoding="utf-8"))
            self.assertEqual("pass", json.loads(result.stdout)["status"])

    def test_spring_quality_gate_blocks_unmapped_application_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "backend" / "contexts" / "identity-access" / "src" / "main" / "java" / "app"
            source.mkdir(parents=True)
            (source / "ApplicationException.java").write_text("package app; public class ApplicationException extends RuntimeException {}\n", encoding="utf-8")
            (source / "GlobalExceptionHandler.java").write_text("package app; class GlobalExceptionHandler {}\n", encoding="utf-8")

            result = run_script("validate_spring_boot_quality.py", "--root", str(root))

            self.assertNotEqual(0, result.returncode)
            report = json.loads((root / "artifacts" / "_control" / "spring-boot-quality-report.json").read_text(encoding="utf-8"))
            self.assertEqual("block", report["status"])
            self.assertIn("ApplicationException", json.dumps(report["findings"], ensure_ascii=False))

    def test_agent_entrypoint_dry_run_is_short_and_control_plane_focused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = run_script("ensure_agent_entrypoint.py", "--root", str(root), "--project-name", "ai-platform-v1", "--dry-run")

            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            self.assertIn("artifacts/_control/task-context.agent.md", result.stdout)
            self.assertIn("run_controlled_task.py --root . --mode audit-readonly", result.stdout)
            self.assertLess(len(result.stdout.splitlines()), 30)


if __name__ == "__main__":
    unittest.main()
