import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUALITY_DIMENSIONS = [
    "bug",
    "vulnerability",
    "security_hotspot",
    "code_smell",
    "complexity",
    "duplication",
    "coverage",
    "maintainability",
    "reliability",
    "security",
    "performance",
    "testability",
    "observability",
]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class CodeReviewCapabilityTests(unittest.TestCase):
    def write_static_report(self, root: Path) -> Path:
        path = root / "artifacts" / "code-quality-governor" / "static-analysis-report.json"
        write_json(
            path,
            {
                "tools": [
                    {"name": "checkstyle", "status": "passed", "reason": "fixture"},
                    {"name": "sonar", "status": "passed", "reason": "fixture"},
                ],
                "summary": {"passed": 2},
            },
        )
        return path

    def write_quality_report(self, root: Path) -> Path:
        path = root / "artifacts" / "code-quality-governor" / "code-quality-report.json"
        write_json(
            path,
            {
                "gate_decision": "warn",
                "findings": [
                    {
                        "id": "CQ-001",
                        "severity": "minor",
                        "dimension": "code_smell",
                        "file": "src/main/java/demo/DemoService.java",
                        "line": 12,
                        "problem": "测试夹具中的可维护性问题",
                        "impact": "方法职责不清晰",
                        "recommendation": "拆分方法并补充断言",
                    }
                ],
            },
        )
        return path

    def stage_result(self, root: Path, artifacts: list[dict]) -> dict:
        return {
            "run_id": "run-001",
            "skill_id": "code-review",
            "status": "succeeded",
            "preflight_input_state": "ready",
            "language": "zh-CN",
            "trace_id": "trace-001",
            "document_metadata": {
                "document_number": "CRR-CODE-20260622-001",
                "document_status": "draft",
                "retention_policy": "keep_until_run_end",
                "title": "代码走查报告",
                "owner": "研发负责人",
                "source_artifacts": [],
            },
            "artifacts": artifacts,
            "quality_gates": [],
            "findings": [],
            "required_human_reviews": [],
            "required_information_requests": [],
            "repair_summary": {"attempts": 0, "max_attempts": 0, "status": "not_needed"},
            "next_action": "complete",
        }

    def code_review_artifacts(self, root: Path, include_html: bool = True, include_static: bool = True) -> list[dict]:
        output = root / "artifacts" / "code-review"
        names = [
            ("code-review-report.md", "markdown"),
            ("review-comments.json", "json"),
            ("blocker-list.md", "markdown"),
        ]
        if include_html:
            names.append(("code-review-report.html", "html"))
        if include_static:
            names.append(("static-analysis-report.json", "json"))
        return [
            {
                "name": name,
                "path": str((root / "artifacts" / "code-quality-governor" / name) if name == "static-analysis-report.json" else (output / name)),
                "artifact_type": kind,
                "producer_skill": "code-review",
            }
            for name, kind in names
        ]

    def test_run_code_review_generates_reports_and_quality_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_static_report(root)
            self.write_quality_report(root)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "engineering-assistant" / "scripts" / "run_code_review.py"),
                    "--root",
                    str(root),
                    "--output",
                    "artifacts/code-review",
                    "--skip-static-analysis-autogen",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = root / "artifacts" / "code-review"
            for name in ["code-review-report.md", "code-review-report.html", "review-comments.json", "blocker-list.md"]:
                self.assertTrue((output / name).exists(), name)
            review = json.loads((output / "review-comments.json").read_text(encoding="utf-8"))
            self.assertEqual({item["dimension"] for item in review["checklist_coverage"]}, set(QUALITY_DIMENSIONS))
            html = (output / "code-review-report.html").read_text(encoding="utf-8")
            self.assertIn("Quality Dimension", html)
            self.assertIn("Checklist Coverage", html)
            self.assertIn("code_smell", html)
            payload = self.stage_result(root, self.code_review_artifacts(root, include_html=True, include_static=True))
            payload_path = root / "result.json"
            write_json(payload_path, payload)
            validation = subprocess.run(
                [sys.executable, str(ROOT / "skills/code-review/scripts/validate_output.py"), str(payload_path)],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

    def test_validator_blocks_missing_html_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            static = self.write_static_report(root)
            output = root / "artifacts" / "code-review"
            output.mkdir(parents=True)
            (output / "code-review-report.md").write_text("# report\n", encoding="utf-8")
            write_json(output / "review-comments.json", {"findings": [], "checklist_coverage": [{"dimension": d, "status": "checked", "evidence": ["fixture"]} for d in QUALITY_DIMENSIONS]})
            (output / "blocker-list.md").write_text("# blockers\n", encoding="utf-8")
            payload = self.stage_result(root, self.code_review_artifacts(root, include_html=False, include_static=True))
            payload_path = root / "result.json"
            write_json(payload_path, payload)
            result = subprocess.run([sys.executable, str(ROOT / "skills/code-review/scripts/validate_output.py"), str(payload_path)], cwd=str(ROOT), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("code-review-report.html", result.stderr + result.stdout)

    def test_validator_blocks_major_finding_without_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_static_report(root)
            output = root / "artifacts" / "code-review"
            output.mkdir(parents=True)
            (output / "code-review-report.md").write_text("# report\n", encoding="utf-8")
            (output / "code-review-report.html").write_text("Quality Dimension\nChecklist Coverage\n问题清单\n人工确认区\n", encoding="utf-8")
            write_json(
                output / "review-comments.json",
                {
                    "findings": [
                        {
                            "id": "CRR-001",
                            "severity": "major",
                            "category": "quality",
                            "problem": "缺少维度",
                            "impact": "无法归类质量风险",
                            "recommendation": "补充 dimension",
                            "blocking": True,
                            "source_ids": ["fixture"],
                        }
                    ],
                    "checklist_coverage": [{"dimension": d, "status": "checked", "evidence": ["fixture"]} for d in QUALITY_DIMENSIONS],
                },
            )
            (output / "blocker-list.md").write_text("# blockers\n", encoding="utf-8")
            payload = self.stage_result(root, self.code_review_artifacts(root, include_html=True, include_static=True))
            payload_path = root / "result.json"
            write_json(payload_path, payload)
            result = subprocess.run([sys.executable, str(ROOT / "skills/code-review/scripts/validate_output.py"), str(payload_path)], cwd=str(ROOT), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dimension", result.stderr + result.stdout)

    def test_validator_blocks_succeeded_without_static_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "artifacts" / "code-review"
            output.mkdir(parents=True)
            (output / "code-review-report.md").write_text("# report\n", encoding="utf-8")
            (output / "code-review-report.html").write_text("Quality Dimension\nChecklist Coverage\n问题清单\n人工确认区\n", encoding="utf-8")
            write_json(output / "review-comments.json", {"findings": [], "checklist_coverage": [{"dimension": d, "status": "checked", "evidence": ["fixture"]} for d in QUALITY_DIMENSIONS]})
            (output / "blocker-list.md").write_text("# blockers\n", encoding="utf-8")
            payload = self.stage_result(root, self.code_review_artifacts(root, include_html=True, include_static=False))
            payload_path = root / "result.json"
            write_json(payload_path, payload)
            result = subprocess.run([sys.executable, str(ROOT / "skills/code-review/scripts/validate_output.py"), str(payload_path)], cwd=str(ROOT), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("static-analysis-report.json", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
