#!/usr/bin/env python3
"""Regression checks for v3.1 task-specific SOP skill refactor."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOP_HEADINGS = [
    "# When To Use",
    "# Do Not Use When",
    "# Inputs",
    "# Do This",
    "# Evidence / Done",
    "# Stop / Escalate",
    "# References / Scripts",
]


def run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(ROOT / "engineering-assistant" / "scripts" / script), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class V31TaskSopSkillTests(unittest.TestCase):
    def test_manifest_and_runtime_are_v31(self) -> None:
        manifest = json.loads((ROOT / "engineering-assistant" / "plugin" / "plugin.json").read_text(encoding="utf-8"))
        runtime = json.loads((ROOT / "engineering-assistant" / "runtime" / "compiled" / "skill-runtime-index.json").read_text(encoding="utf-8"))
        self.assertEqual("3.1.0", manifest["version"])
        self.assertEqual("3.1.0", runtime["version"])

    def test_all_skill_md_files_use_short_task_sop_sections(self) -> None:
        common_headings = None
        for skill_md in sorted((ROOT / "skills").glob("*/SKILL.md")):
            text = skill_md.read_text(encoding="utf-8")
            headings = [line for line in text.splitlines() if line.startswith("# ")]
            self.assertEqual(SOP_HEADINGS, headings, skill_md)
            self.assertLessEqual(len(text.splitlines()), 120, skill_md)
            description = next(line for line in text.splitlines() if line.startswith("description: "))
            self.assertIn("Use when", description)
            self.assertIn("Do not use", description)
            self.assertNotIn("request is about", description)
            common_headings = set(headings) if common_headings is None else common_headings & set(headings)
        self.assertLessEqual(len(common_headings or set()), 8)

    def test_all_skills_have_task_specific_eval_profiles(self) -> None:
        registry = json.loads((ROOT / "engineering-assistant" / "registry" / "skills.yaml").read_text(encoding="utf-8"))
        skill_ids = {item["skill_id"] for item in registry["skills"]}
        self.assertGreaterEqual(len(skill_ids), 25)
        for skill_id in skill_ids:
            for case in ["happy_path", "policy_conflict", "regression_case"]:
                eval_case = json.loads((ROOT / "skills" / skill_id / "evals" / f"{case}.yaml").read_text(encoding="utf-8"))
                self.assertEqual("task_sop_full", eval_case["eval_profile"], f"{skill_id}/{case}")
                material = eval_case["scenario"]["material"]
                self.assertNotIn("输入材料覆盖", material)
                self.assertGreaterEqual(len(eval_case["scenario"]["risk_focus"]), 3)
            self.assertEqual("block", json.loads((ROOT / "skills" / skill_id / "evals" / "policy_conflict.yaml").read_text(encoding="utf-8"))["expected_gate_decision"])

    def test_effectiveness_report_exposes_v31_sop_metrics(self) -> None:
        result = run_script("run_skill_effectiveness_evals.py", "--mode", "grade", "--no-write-report")
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual("pass", report["status"])
        self.assertGreaterEqual(report["metrics"]["mean_pass_rate"]["current_engineering_assistant"], 0.89)
        self.assertLessEqual(report["metrics"]["mean_token_or_time_cost"]["current_engineering_assistant"], 1.16)
        self.assertLessEqual(report["doc_noise_score"], 0.20)
        self.assertGreaterEqual(report["frontend_product_score"], 0.85)
        metrics = report["skill_sop_metrics"]
        self.assertGreaterEqual(metrics["task_sop_skill_count"], 25)
        self.assertLessEqual(metrics["task_sop_average_similarity"], 0.45)
        self.assertLessEqual(metrics["global_average_similarity"], 0.60)
        self.assertLessEqual(metrics["common_heading_count"], 8)
        self.assertEqual(1.0, metrics["description_route_quality"])
        self.assertTrue(metrics["context_budget"]["pass"])
        self.assertTrue(metrics["real_output_evidence"]["task_sop_sections_present"])


if __name__ == "__main__":
    unittest.main()
