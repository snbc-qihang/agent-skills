---
name: design-review
description: Use when 评审设计产物，判断是否可以进入代码研发；Do not use when do not 代替审批人签字。
---

# When To Use
- 评审设计产物，判断是否可以进入代码研发。
- 设计评审、设计产物完整性检查、风险关闭和进入代码研发 gate 判断时使用。

# Do Not Use When
- 不代替审批人签字。
- 不修正文档内容。
- 不放行 blocker。

# Inputs
- `high-level-design.md`
- `detailed-design.md`
- `database-design.md`
- `redis-design.md`
- `mq-design.xlsx`

# Do This
- 读取 high-level-design.md, detailed-design.md, database-design.md、项目 profile、团队规则目录和 artifact index。
- 执行 design-review preflight：确认语言、必填信息、风险、审批状态和 `high-level-design.md` 证据。
- A/H/D/I/E/P/R/M/DB 规范逐项检查。
- 需求契约已准入，概要设计和详细设计均完整。
- 目标业务系统与目标客户端系统的系统边界、业务域、接口、事件协作、最终一致性已说明。
- DB/Redis/MQ 专项设计齐全，未涉及项有明确不适用说明。
- 接口、异常、幂等、并发、状态流转、事务边界、回滚策略均有证据。

# Evidence / Done
- `design-review-report.md` 已生成并可追溯。
- `review-findings.json` 已生成并可追溯。
- `design-gate-decision.json` 已生成并可追溯。
- 无未关闭 blocker 有证据、假设或 required action。
- 关键专项设计齐全 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `high-level-design.md` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `无未关闭 blocker` 失败时 blocked，不得降级为普通建议。
- 高风险设计放行 需要人工审批或 waiting_for_human_review。
- blocker 关闭确认 需要人工审批或 waiting_for_human_review。
- 关键设计豁免 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
