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
        self.assertIn("不得自行降低既有人工门禁", skill)
        self.assertIn("不得把普通阶段完成当作人工审批点", authorization)
        self.assertIn("已有用户授权或仓库策略明确允许", authorization)
        self.assertIn("不得静默降低既有人工门禁", authorization)

    def test_canary_feedback_is_enforced_by_public_skills(self) -> None:
        router = (ROOT / "skills/engineering-assistant/SKILL.md").read_text(
            encoding="utf-8"
        )
        context = (ROOT / "skills/repo-context/SKILL.md").read_text(encoding="utf-8")
        review = (ROOT / "skills/code-review/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("engineering_assistant_route", router)
        self.assertIn("阶段状态审计", router)
        self.assertIn("插件自动采集", context)
        self.assertIn("不是硬约束", context)
        self.assertIn("代码图已经返回的源码不得重复打开", context)
        self.assertIn("outbox、通知 payload、URL", review)
        self.assertIn("当前源码、配置和运行结果与历史报告冲突", review)
        self.assertIn("ea artifact-validate", review)
        self.assertIn("用户点名的阶段结果、自测、代码评审和运行证据", router)
        self.assertIn("秘密、鉴权、持久化和外部动作", review)
        self.assertIn("payload -> outbox/持久化 -> dispatcher/provider/log", review)
        self.assertIn("每一类都必须独立读取", review)

    def test_canary_efficiency_rules_prevent_duplicate_routing_and_evidence_dumping(self) -> None:
        router = (ROOT / "skills/engineering-assistant/SKILL.md").read_text(
            encoding="utf-8"
        )
        context = (ROOT / "skills/repo-context/SKILL.md").read_text(encoding="utf-8")
        review = (ROOT / "skills/code-review/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("该选择即为本轮平台能力选择结果", router)
        self.assertIn("不得为了确认 skill 再次调用 `engineering_assistant_route`", router)
        self.assertIn("不等同于 Runtime `RouteDecision`", router)
        self.assertIn("旧插件路径", review)
        self.assertIn("不得扫描插件目录猜测替代路径", review)
        self.assertIn("精确区间", review)
        self.assertIn("不得输出大目录清单", review)
        self.assertIn("不是产品 blocker", review)
        self.assertIn("`not_evaluated`", review)
        self.assertIn("不得把“未见”升级为实现缺陷", review)
        self.assertIn("不得创造 `blocked_by_*`", review)
        self.assertIn("必须使用仓库或 schema 已注册 enum", review)
        self.assertIn("结构化 reason/blocker", review)
        self.assertIn("不能自行删除产物或合同明确要求的最终人工批准", review)
        self.assertIn("detached HEAD", review)
        self.assertIn("未跟踪的 `.run-artifacts/`", review)
        self.assertIn("只有发布契约明确要求分支形态或洁净范围时", review)
        self.assertIn("不得用跨模块 `rg -n -C`", review)
        self.assertIn("宽泛 `git ls-files`", review)
        self.assertIn("全目录 `find`", review)
        self.assertIn("完整 `git show`", review)
        self.assertIn("一次拼接多份整文件输出", review)
        self.assertIn("不得为了减少调用次数扩大单次输出", review)
        self.assertIn("不得再用 shell 读取自己的 `SKILL.md`", review)
        self.assertIn("精确区间", context)
        self.assertIn("不得输出大目录清单", context)
        self.assertIn("证据充分后立即停止", review)

    def test_review_separates_blocker_confidence_from_human_review_state(self) -> None:
        review = (ROOT / "skills/code-review/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("决定性证据仍包含“可能”", review)
        self.assertIn("不得定级为已证实 blocker", review)
        self.assertIn("`technical_status`", review)
        self.assertIn("`human_review_status`", review)
        self.assertIn("不得用技术 `blocked` 覆盖待人工批准", review)
        self.assertIn("技术问题关闭后仍恢复到原人工门禁", review)

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
                "docs/operations/canary.md",
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
