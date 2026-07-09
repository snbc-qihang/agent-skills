---
name: release-readiness
description: Use when 判断是否具备发布条件，并输出发布计划、检查清单、回滚计划和 gate 决策；Do not use when do not 执行生产发布。
---

# When To Use
- 判断是否具备发布条件，并输出发布计划、检查清单、回滚计划和 gate 决策。
- 发布准备、发布条件判断、回滚方案、灰度策略、监控和值班审批检查时使用。

# Do Not Use When
- 不执行生产发布。
- 不绕过高风险发布审批。
- 不省略回滚方案。

# Inputs
- `code-quality-report.json`
- `code-review-report.md`
- `release-standard.md`
- `risk_policy`

# Do This
- 读取 code-quality-report.json, code-review-report.md, release-standard.md、项目 profile、团队规则目录和 artifact index。
- 执行 release-readiness preflight：确认语言、必填信息、风险、审批状态和 `code-quality-report.json` 证据。
- 发布窗口。
- 影响范围。
- 依赖系统。
- 配置变更。
- DB 变更。

# Evidence / Done
- `release-plan.md` 已生成并可追溯。
- `release-checklist.md` 已生成并可追溯。
- `rollback-plan.md` 已生成并可追溯。
- `release-risk-report.json` 已生成并可追溯。
- 发布窗口明确 有证据、假设或 required action。
- 回滚方案存在 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `code-quality-report.json` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `发布窗口明确` 失败时 blocked，不得降级为普通建议。
- 生产发布 需要人工审批或 waiting_for_human_review。
- 生产配置变更 需要人工审批或 waiting_for_human_review。
- 高风险发布 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
