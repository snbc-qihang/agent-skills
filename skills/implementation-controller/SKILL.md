---
name: implementation-controller
description: Use when 把已审批设计转换为机器可读实现合同和质量合同，并控制代码实现、验证、修复和最终人工审阅；Do not use when do not 审批设计进入研发。
---

# When To Use
- 把已审批设计转换为机器可读实现合同和质量合同，并控制代码实现、验证、修复和最终人工审阅。
- 已审批设计需要编译成实现合同、控制代码执行范围、驱动质量命令和修复闭环时使用。

# Do Not Use When
- 不审批设计进入研发。
- 不直接替代 code-development 编写业务代码。
- 不把 HTML 人工审阅件作为 agent 事实源。

# Inputs
- `approved design artifact`
- `target project root`
- `project profile`
- `changed-files-report.json`

# Do This
- 读取 approved design artifact, target project root, project profile、项目 profile、团队规则目录和 artifact index。
- 执行 implementation-controller preflight：确认语言、必填信息、风险、审批状态和 `approved design artifact` 证据。
- 只接受已审批 Markdown/JSON/YAML 设计产物，HTML 仅作为人工审阅入口。
- 所有 `_control` 产物写入目标项目 `artifacts/_control/`，不得写入插件目录。
- implementation-contract.json 必须包含 allowed_modules、forbidden_modules、expected_interfaces、expected_services、expected_repositories_or_mappers、required_tests、architecture_rules、done_conditions、technology_adoption_contract。
- quality-contract.json 必须包含 required_commands 和 required_evidence，缺失或占位命令必须阻断。
- 必须生成 artifacts/_control/traceability-matrix.json 作为机读事实源，并生成 docs/human-readable/traceability-report.html 作为人工阅览入口；HTML 不得反向作为 agent 事实输入。

# Evidence / Done
- `current-task.json` 已生成并可追溯。
- `design-contract.json` 已生成并可追溯。
- `implementation-contract.json` 已生成并可追溯。
- `quality-contract.json` 已生成并可追溯。
- 设计合同已编译 有证据、假设或 required action。
- 实现范围明确 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `approved design artifact` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `设计合同已编译` 失败时 blocked，不得降级为普通建议。
- 修改已审批设计范围 需要人工审批或 waiting_for_human_review。
- 高风险实现豁免 需要人工审批或 waiting_for_human_review。
- 生产动作 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
