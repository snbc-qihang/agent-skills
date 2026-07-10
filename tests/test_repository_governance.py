from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryGovernanceTests(unittest.TestCase):
    def test_readme_is_a_complete_current_repository_guide(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        required_sections = [
            "## 项目定位",
            "## 核心设计",
            "## 仓库结构",
            "## 公开 Skills",
            "## 内部 Flows",
            "## 能力与策略 Packs",
            "## 运行机制",
            "## 开发与验证",
            "## 本机发布",
            "## 安全边界",
        ]
        for section in required_sections:
            self.assertIn(section, readme, section)
        self.assertIn("sunliming625@gmail.com", readme)
        self.assertNotIn("迁移资料", readme)
        self.assertNotIn("升级记录", readme)

    def test_only_current_architecture_and_operations_documents_remain(self) -> None:
        self.assertEqual(
            {
                "docs/architecture/overview.md",
                "docs/operations/local-publish.md",
            },
            {path.relative_to(ROOT).as_posix() for path in (ROOT / "docs").rglob("*") if path.is_file()},
        )

    def test_local_publish_policy_is_current_configuration_not_history(self) -> None:
        policy = json.loads((ROOT / "config/local-publish-policy.json").read_text(encoding="utf-8"))
        self.assertTrue(policy["enabled"])
        self.assertEqual(["codex", "hermes"], policy["platforms"])
        self.assertTrue(policy["requires_explicit_yes"])
        self.assertFalse(policy["stable_release_allowed"])
        self.assertFalse(policy["product_repository_changes_allowed"])
        for process_field in ["reviewer", "decided_at", "execution_result", "rollback"]:
            self.assertNotIn(process_field, policy)


if __name__ == "__main__":
    unittest.main()
