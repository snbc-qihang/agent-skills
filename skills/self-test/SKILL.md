---
name: self-test
description: Use when 生成并执行自测方案，输出失败原因、影响范围和阻断判断；Do not use when do not 伪造测试结果。
---

# When To Use
- 生成并执行自测方案，输出失败原因、影响范围和阻断判断。
- 自测、测试命令执行、覆盖率汇总、失败测试分析和发布前测试风险判断时使用。

# Do Not Use When
- 不伪造测试结果。
- 不忽略失败测试。
- 不替代发布验证。

# Inputs
- `implementation-summary.md`
- `changed-files-report.json`
- `test-strategy.md`
- `repo_context`

# Do This
- 读取 implementation-summary.md, changed-files-report.json, test-strategy.md、项目 profile、团队规则目录和 artifact index。
- 执行 self-test preflight：确认语言、必填信息、风险、审批状态和 `implementation-summary.md` 证据。
- 执行前必须读取 artifacts/_control/quality-contract.json 和任务规则包。
- 单元测试。
- 集成测试。
- 回归测试。
- 边界测试。

# Evidence / Done
- `self-test-report.md` 已生成并可追溯。
- `test-commands.log` 已生成并可追溯。
- `coverage-summary.md` 已生成并可追溯。
- `failed-tests.md` 已生成并可追溯。
- 测试命令实际执行 有证据、假设或 required action。
- 失败测试明确阻断 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `implementation-summary.md` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `测试命令实际执行` 失败时 blocked，不得降级为普通建议。
- 高风险测试豁免 需要人工审批或 waiting_for_human_review。
- 无法执行关键测试 需要人工审批或 waiting_for_human_review。
- 发布前置测试缺失 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
