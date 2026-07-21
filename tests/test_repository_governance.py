from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryGovernanceTests(unittest.TestCase):
    def test_stage_reviews_use_risk_triggered_nonduplicative_delegation(self) -> None:
        skill = (ROOT / "skills/engineering-assistant/SKILL.md").read_text(encoding="utf-8")
        authorization = (
            ROOT / "skills/engineering-assistant/references/authorization.md"
        ).read_text(encoding="utf-8")
        self.assertIn("风险触发子 Agent 自动评审", skill)
        self.assertIn("同时满足", skill)
        self.assertIn("尚未闭合的可证伪风险假设", skill)
        self.assertIn("可证伪风险假设", skill)
        self.assertIn("全部适用反例矩阵单元格", skill)
        self.assertIn("彼此不重复的假设全部", skill)
        self.assertIn("不得只选择其中一个", skill)
        self.assertIn("不得重复主 Agent 已完成的全量评审", skill)
        self.assertIn("平台不支持委派时逐项内联检查", skill)
        self.assertIn("标为 `not_evaluated`", skill)
        self.assertIn("不得据此降低标准门禁或原有人工门禁", skill)
        self.assertNotIn("默认发起子 Agent 自动评审", skill)
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

        canary = (ROOT / "docs/operations/canary.md").read_text(encoding="utf-8")
        self.assertIn("盲评 Blocker、盲评 Major、未闭合矩阵单元格", canary)
        self.assertIn("进入 broker 签名 claims", canary)
        self.assertIn("`delegation_ablation`", canary)
        self.assertIn("主/子 Agent 证据重叠", canary)

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
        self.assertIn("`recommended_execution=skills_only`", router)
        self.assertIn("不调用任何需要 active run 的 Runtime 工具", router)
        self.assertIn("`provider_invoke`、`investigation_*`", router)
        self.assertIn("不得省略已选 skill 要求的 TDD、测试、风险评审或安全门禁", router)
        self.assertIn("否则只内联报告六维判断", (ROOT / "skills/tdd/SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("否则只内联合并六维判断", review)
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

    def test_security_seam_references_close_observed_high_risk_boundaries(self) -> None:
        tdd_skill = (ROOT / "skills/tdd/SKILL.md").read_text(encoding="utf-8")
        review_skill = (ROOT / "skills/code-review/SKILL.md").read_text(encoding="utf-8")
        tdd_reference = (
            ROOT / "skills/tdd/references/security-seams.md"
        ).read_text(encoding="utf-8")
        review_reference = (
            ROOT / "skills/code-review/references/security-seams.md"
        ).read_text(encoding="utf-8")
        for skill in (tdd_skill, review_skill):
            self.assertIn("references/security-seams.md", skill)
            self.assertIn("行为触及身份或授权状态", skill)
        for reference in (tdd_reference, review_reference):
            self.assertIn("终止后旧结果不得恢复受保护数据", reference)
            self.assertIn("适用变换与组合链", reference)
            self.assertIn("通用键值", reference)
            self.assertIn("短编码", reference)
            self.assertIn("裸认证", reference)
            self.assertIn("adapter 返回的 persistence ID 是事实源", reference)
            self.assertIn("适用反例矩阵", reference)
            self.assertIn("嵌入普通文本的编码片段", reference)
            self.assertIn("畸形 percent", reference)
            self.assertIn("真实生产 adapter", reference)
            self.assertIn("最终 commit/rollback 可见性", reference)
            self.assertIn("resultStatus", reference)
            self.assertIn("ID 类型", reference)
            self.assertIn("不适用项记录理由，不生成测试", reference)
        self.assertIn("malformed envelope", tdd_reference)
        self.assertIn("旧请求的 401", tdd_reference)
        self.assertIn("身份替换后的旧 bootstrap", tdd_reference)

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
                "docs/operations/team-training.md",
            },
            {
                path.relative_to(ROOT).as_posix()
                for path in (ROOT / "docs").rglob("*")
                if path.is_file() and path.name != ".DS_Store"
            },
        )

    def test_team_training_covers_cross_platform_delivery_contract(self) -> None:
        training = (ROOT / "docs/operations/team-training.md").read_text(encoding="utf-8")
        for required in (
            "插件介绍",
            "Windows 原生",
            "WSL2",
            "macOS",
            "PowerShell",
            "teamwork-engineering-assistant",
            "diagnosing-bugs",
            "code-review",
            "scripts/publish_local.py --platform codex --dry-run",
            "--codex-home",
            "外部 Skills、Plugins 和 MCP",
            "插件内置",
            "skill-creator",
            "plugin-creator",
            "ui-ux-pro-max",
            "codex mcp add",
            "requirement_id",
            "design_source",
            "base_digest",
            "stale",
            "0..N",
            "不限制数量",
            "人工批准",
            "Git 无文本冲突不能证明",
        ):
            self.assertIn(required, training)
        self.assertNotIn("/Users/sunliming", training)

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
