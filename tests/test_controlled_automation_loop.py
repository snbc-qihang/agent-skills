#!/usr/bin/env python3
"""Regression checks for the controlled automation runner."""

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


class ControlledAutomationLoopTests(unittest.TestCase):
    def test_runner_records_repair_attempts_and_stops_on_gate_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
                    "technology_adoption_contract": {"persistence_framework": "mybatis-plus", "minimum_required_indicators": 0},
                },
            )
            write_json(
                control / "quality-contract.json",
                {
                    "schema_version": "2.0.0",
                    "task_id": "aip",
                    "required_commands": [{"id": "fail", "command": "python3 -c 'import sys; sys.exit(1)'", "required": True}],
                    "required_evidence": ["quality_commands"],
                    "quality_gates": ["build_lint_test"],
                    "repair_policy": {"max_attempts": 2},
                },
            )
            (control / "task-context.agent.md").write_text("# Agent Context\n", encoding="utf-8")
            pack = root / "artifacts" / "rule-governance" / "task-rule-packs" / "code-development.json"
            write_json(pack, {"task_type": "code-development", "rule_count": 1, "rules": [{"rule_id": "RG-001", "severity": "major"}]})
            evidence = root / "artifacts" / "code-development" / "implementation-summary.json"
            write_json(evidence, {"rule_refs": ["RG-001"], "summary": "mapped"})

            result = subprocess.run(
                [
                    "python3",
                    str(PLUGIN_SCRIPTS / "run_controlled_task.py"),
                    "--root",
                    str(root),
                    "--task-type",
                    "code-development",
                    "--rule-evidence",
                    "artifacts/code-development/implementation-summary.json",
                    "--max-repair-attempts",
                    "2",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            attempts = json.loads((control / "repair-attempts.json").read_text(encoding="utf-8"))
            self.assertEqual(2, attempts["max_attempts"])
            self.assertEqual("blocked", attempts["status"])
            self.assertTrue(any(item["step"] == "run_quality_commands" for item in attempts["failures"]))


if __name__ == "__main__":
    unittest.main()
