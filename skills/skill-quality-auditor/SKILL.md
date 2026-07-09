---
name: skill-quality-auditor
description: Use when 审计 skills 质量，防止空泛 prompt，阻断不合格 skill 入库；Do not use when do not 执行业务研发阶段。
---

# When To Use
- 审计 skills 质量，防止空泛 prompt，阻断不合格 skill 入库。
- 检查人工编写或 Agent 生成的 Codex Skills 质量、契约完整性、触发描述、eval 覆盖、workflow 兼容性时使用。

# Do Not Use When
- 不执行业务研发阶段。
- 不替代 eval 执行。
- 不放行缺少 gate 的高风险 skill。

# Inputs
- `skills`
- `engineering-assistant/registry/skills.yaml`
- `skill-contract.schema.json`

# Do This
- 读取 skills, engineering-assistant/registry/skills.yaml, skill-contract.schema.json、项目 profile、团队规则目录和 artifact index。
- 执行 skill-quality-auditor preflight：确认语言、必填信息、风险、审批状态和 `skills` 证据。
- front matter。
- 职责单一。
- non-goals。
- 输入输出契约。
- deterministic validation scripts。

# Evidence / Done
- `skill-quality-report.md` 已生成并可追溯。
- `skill-quality-report.json` 已生成并可追溯。
- `skill-fix-suggestions.md` 已生成并可追溯。
- `skill-gate-decision.json` 已生成并可追溯。
- SKILL.md 存在 有证据、假设或 required action。
- description 清楚 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `skills` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `SKILL.md 存在` 失败时 blocked，不得降级为普通建议。
- 高风险 skill 入库 需要人工审批或 waiting_for_human_review。
- 修改高风险质量门禁 需要人工审批或 waiting_for_human_review。
- skill gate 豁免 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
