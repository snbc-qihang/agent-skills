---
name: release-retrospective
description: Use when 复盘发布过程，消费已采集反馈事件，沉淀发布问题、测试遗漏、设计遗漏、规范改进候选和 skill 改进候选；Do not use when do not 将候选规范直接发布。
---

# When To Use
- 复盘发布过程，消费已采集反馈事件，沉淀发布问题、测试遗漏、设计遗漏、规范改进候选和 skill 改进候选。
- 发布复盘、发布问题归纳、规范候选、skill 改进候选和后续行动整理时使用。

# Do Not Use When
- 不将候选规范直接发布。
- 不隐藏发布问题。
- 不替代 assistant-feedback-capture 的全量反馈采集。

# Inputs
- `release-verification-report.md`
- `code-quality-report.json`
- `feedback-inbox.json`
- `incident reports`
- `release logs`

# Do This
- 读取 release-verification-report.md, code-quality-report.json, feedback-inbox.json、项目 profile、团队规则目录和 artifact index。
- 执行 release-retrospective preflight：确认语言、必填信息、风险、审批状态和 `release-verification-report.md` 证据。
- 发布过程问题。
- 测试遗漏。
- 设计遗漏。
- 代码质量问题。
- 发布验证问题。

# Evidence / Done
- `release-retrospective.md` 已生成并可追溯。
- `release-lessons.yaml` 已生成并可追溯。
- `follow-up-actions.md` 已生成并可追溯。
- 问题有证据 有证据、假设或 required action。
- feedback inbox 已消费 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `release-verification-report.md` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `问题有证据` 失败时 blocked，不得降级为普通建议。
- 行动项关闭 需要人工审批或 waiting_for_human_review。
- 规范候选批准 需要人工审批或 waiting_for_human_review。
- 高风险复盘结论发布 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
