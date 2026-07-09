---
name: code-development
description: Use when 基于设计文档进行最小必要代码变更或生成代码修改计划；Do not use when do not 修改无关模块。
---

# When To Use
- 基于设计文档进行最小必要代码变更或生成代码修改计划。
- 代码研发、按设计实施代码变更、生成实现总结和设计到代码映射时使用。

# Do Not Use When
- 不修改无关模块。
- 不绕过测试。
- 不执行未审批高风险动作。

# Inputs
- `detailed-design.md`
- `implementation-plan.md`
- `interface-contracts.yaml`
- `repo_context`

# Do This
- 读取 detailed-design.md, implementation-plan.md, interface-contracts.yaml、项目 profile、团队规则目录和 artifact index。
- 执行 code-development preflight：确认语言、必填信息、风险、审批状态和 `detailed-design.md` 证据。
- 执行前必须读取 artifacts/_control/task-context.agent.md、implementation-contract.json、quality-contract.json 和任务规则包。
- 最小必要变更。
- 设计映射。
- 风险标记。
- 测试覆盖。

# Evidence / Done
- `code changes` 已生成并可追溯。
- `implementation-summary.md` 已生成并可追溯。
- `design-to-code-mapping.yaml` 已生成并可追溯。
- `changed-files-report.json` 已生成并可追溯。
- 每个变更映射到设计 有证据、假设或 required action。
- 无无关模块修改 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `detailed-design.md` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `每个变更映射到设计` 失败时 blocked，不得降级为普通建议。
- DB/Redis/MQ/权限/发布脚本变更 需要人工审批或 waiting_for_human_review。
- 核心链路实现偏离设计 需要人工审批或 waiting_for_human_review。
- 高风险重构 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
