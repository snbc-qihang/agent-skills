---
name: engineering-knowledge-miner
description: Use when 从研发流程产物中抽取可复用经验，生成规范候选、检查清单候选、eval 回归样例候选和 skill 反哺建议；Do not use when do not 无证据创建规范。
---

# When To Use
- 从研发流程产物中抽取可复用经验，生成规范候选、检查清单候选、eval 回归样例候选和 skill 反哺建议。
- 研发经验总结、规范沉淀、评审问题归纳、事故复盘反哺、skill 规范更新建议时使用。

# Do Not Use When
- 不无证据创建规范。
- 不未经审批修改正式规范。
- 不把偶发低风险问题升级为强制规范。

# Inputs
- `design reports`
- `code quality reports`
- `review reports`
- `CI logs`
- `PR comments`
- `release reports`
- `incident reports`

# Do This
- 读取 design reports, code quality reports, review reports、项目 profile、团队规则目录和 artifact index。
- 执行 engineering-knowledge-miner preflight：确认语言、必填信息、风险、审批状态和 `design reports` 证据。
- 证据收集。
- finding 抽取。
- 问题归类。
- 模式识别。
- 经验候选。

# Evidence / Done
- `engineering-lessons.md` 已生成并可追溯。
- `rule-candidates.yaml` 已生成并可追溯。
- `standard-patch-suggestions.md` 已生成并可追溯。
- `checklist-patch-suggestions.md` 已生成并可追溯。
- 每条经验有来源证据 有证据、假设或 required action。
- 规则默认 candidate 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `design reports` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `每条经验有来源证据` 失败时 blocked，不得降级为普通建议。
- 修改正式团队规范 需要人工审批或 waiting_for_human_review。
- rule_candidate 标记为 approved 需要人工审批或 waiting_for_human_review。
- 修改高风险 skill quality gate 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
