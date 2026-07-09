---
name: requirement-intake
description: Use when 判断需求是否具备进入设计阶段的条件，并输出可复用需求契约；Do not use when do not 替代产品决策。
---

# When To Use
- 判断需求是否具备进入设计阶段的条件，并输出可复用需求契约。
- 需求准入、需求边界确认、验收标准检查、进入设计前风险判断时使用。

# Do Not Use When
- 不替代产品决策。
- 不生成代码。
- 不直接批准高风险需求进入设计。

# Inputs
- `organization_context`
- `current_process`
- `requirement_materials`
- `risk_policy`

# Do This
- 读取 organization_context, current_process, requirement_materials、项目 profile、团队规则目录和 artifact index。
- 执行 requirement-intake preflight：确认语言、必填信息、风险、审批状态和 `organization_context` 证据。
- 业务目标。
- 用户场景。
- 需求范围。
- 非目标。
- 验收标准。

# Evidence / Done
- `requirement-intake-report.md` 已生成并可追溯。
- `requirement-contract.json` 已生成并可追溯。
- `missing-information-list.md` 已生成并可追溯。
- `requirement-risk-assessment.json` 已生成并可追溯。
- 业务目标存在 有证据、假设或 required action。
- 验收标准存在 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `organization_context` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `业务目标存在` 失败时 blocked，不得降级为普通建议。
- 高风险需求 需要人工审批或 waiting_for_human_review。
- 跨系统重大依赖 需要人工审批或 waiting_for_human_review。
- 数据/权限/发布风险 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
