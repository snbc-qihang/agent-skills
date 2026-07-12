from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryGovernanceTests(unittest.TestCase):
    def test_stage_reviews_default_to_delegated_agent_review(self) -> None:
        skill = (ROOT / "skills/engineering-assistant/SKILL.md").read_text(encoding="utf-8")
        authorization = (
            ROOT / "skills/engineering-assistant/references/authorization.md"
        ).read_text(encoding="utf-8")
        self.assertIn("子 Agent 自动评审", skill)
        self.assertIn("不得把普通阶段完成当作人工审批点", authorization)

    def test_canary_feedback_is_enforced_by_public_skills(self) -> None:
        router = (ROOT / "skills/engineering-assistant/SKILL.md").read_text(
            encoding="utf-8"
        )
        context = (ROOT / "skills/repo-context/SKILL.md").read_text(encoding="utf-8")
        review = (ROOT / "skills/code-review/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("engineering_assistant_route", router)
        self.assertIn("阶段状态审计", router)
        self.assertIn("证据预算", context)
        self.assertIn("代码图已经返回的源码不得重复打开", context)
        self.assertIn("outbox、通知 payload、URL", review)
        self.assertIn("当前源码、配置和运行结果与历史报告冲突", review)
        self.assertIn("ea artifact-validate", review)
        self.assertIn("用户点名的阶段结果、自测、代码评审和运行证据", router)
        self.assertIn("秘密、鉴权、持久化和外部动作", review)
        self.assertIn("payload -> outbox/持久化 -> dispatcher/provider/log", review)
        self.assertIn("每一类都必须独立读取", review)

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
            {
                path.relative_to(ROOT).as_posix()
                for path in (ROOT / "docs").rglob("*")
                if path.is_file() and path.name != ".DS_Store"
            },
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
