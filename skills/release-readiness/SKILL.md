---
name: release-readiness
description: Use when 发布前需要检查发布窗口、影响范围、回滚、灰度、监控、值班和审批是否齐全时；Do not use when do not执行生产发布。
---

# When To Use
- 发布前需要检查发布窗口、影响范围、回滚、灰度、监控、值班和审批是否齐全时。
- 需要决定代码是否具备进入发布执行或人工审批的条件时。

# Do Not Use When
- 不要执行生产发布。
- 不要绕过高风险发布审批。
- 不要省略回滚方案。

# Inputs
- `code-quality-report.json`
- `code-review-report.md`
- `release-standard.md`
- `risk_policy`

# Do This
- 读取 code-quality-report、code-review-report、release standard 和风险策略。
- 检查发布窗口、依赖系统、配置/DB 变更、灰度策略、回滚策略、验证步骤、监控告警和值班人员。
- 把缺失项标记 owner、截止时间、审批状态和阻断级别。
- 输出 release-plan、checklist、rollback-plan、risk report 和 gate decision。

# Evidence / Done
- release-gate-decision.json 明确是否可发布。
- release-checklist.md 每项有状态、owner 和证据。
- rollback-plan.md 可执行且覆盖配置、DB、服务和数据风险。

# Stop / Escalate
- 质量门禁、回滚、监控或审批缺失时 blocked。
- 生产发布、生产配置或高风险发布未审批时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
