---
name: release-verification
description: Use when 发布后验证核心功能、监控、日志、业务指标和回滚条件；Do not use when do not 执行未审批回滚。
---

# When To Use
- 发布后验证核心功能、监控、日志、业务指标和回滚条件。
- 发布后验证、生产检查、监控指标、异常列表和回滚条件判断时使用。

# Do Not Use When
- 不执行未审批回滚。
- 不忽略异常。
- 不替代发布准备审批。

# Inputs
- `release-plan.md`
- `release-checklist.md`
- `observability data`
- `risk_policy`

# Do This
- 读取 release-plan.md, release-checklist.md, observability data、项目 profile、团队规则目录和 artifact index。
- 执行 release-verification preflight：确认语言、必填信息、风险、审批状态和 `release-plan.md` 证据。
- 核心功能验证。
- 监控指标。
- 错误率。
- 延迟。
- 业务指标。

# Evidence / Done
- `release-verification-report.md` 已生成并可追溯。
- `production-checks.json` 已生成并可追溯。
- `anomaly-list.md` 已生成并可追溯。
- 核心功能验证通过 有证据、假设或 required action。
- 错误率/延迟未触发阈值 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `release-plan.md` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `核心功能验证通过` 失败时 blocked，不得降级为普通建议。
- 回滚操作 需要人工审批或 waiting_for_human_review。
- 生产验证豁免 需要人工审批或 waiting_for_human_review。
- 延长观察窗口 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
