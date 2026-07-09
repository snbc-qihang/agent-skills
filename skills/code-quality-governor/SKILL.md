---
name: code-quality-governor
description: Use when 建立 Q0-Q4 多层代码质量门禁，输出可被 CI/CD、PR、workflow 消费的结构化质量报告；Do not use when do not 以 LLM 判断替代 build/test/lint。
---

# When To Use
- 建立 Q0-Q4 多层代码质量门禁，输出可被 CI/CD、PR、workflow 消费的结构化质量报告。
- 代码质量门禁、PR 质量审计、代码变更风险评估、发布前质量检查时使用。

# Do Not Use When
- 不以 LLM 判断替代 build/test/lint。
- 不在测试失败时输出 pass。
- 不降级 blocker。

# Inputs
- `changed-files-report.json`
- `design-to-code-mapping.yaml`
- `self-test-report.md`
- `ci artifacts`

# Do This
- 读取 changed-files-report.json, design-to-code-mapping.yaml, self-test-report.md、项目 profile、团队规则目录和 artifact index。
- 执行 code-quality-governor preflight：确认语言、必填信息、风险、审批状态和 `changed-files-report.json` 证据。
- 执行前必须读取 artifacts/_control/quality-contract.json、control-health-report.json、technology-adoption-report.json 和任务规则包。
- build。
- format。
- lint。
- typecheck。

# Evidence / Done
- `code-quality-report.md` 已生成并可追溯。
- `code-quality-report.html` 已生成并可追溯。
- `code-quality-report.json` 已生成并可追溯。
- `gate-decision.json` 已生成并可追溯。
- Q0 设计一致性 有证据、假设或 required action。
- Q1 确定性工程检查 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `changed-files-report.json` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `Q0 设计一致性` 失败时 blocked，不得降级为普通建议。
- 高风险未审批变更 需要人工审批或 waiting_for_human_review。
- 发布脚本变更 需要人工审批或 waiting_for_human_review。
- 权限/认证/鉴权逻辑变更 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
