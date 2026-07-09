---
name: database-design
description: Use when 设计数据库表结构、索引、迁移、修复和必要恢复方案，并标记生产变更审批点；Do not use when do not 执行生产 DDL。
---

# When To Use
- 设计数据库表结构、索引、迁移、修复和必要恢复方案，并标记生产变更审批点。
- 数据库设计、表结构、索引、迁移、修复和必要恢复方案设计时使用。

# Do Not Use When
- 不执行生产 DDL。
- 不做无用途字段和索引。
- 不省略回滚方案。

# Inputs
- `detailed-design.md`
- `database-standard.md`
- `repo_context`
- `risk_policy`

# Do This
- 读取 detailed-design.md, database-standard.md, repo_context、项目 profile、团队规则目录和 artifact index。
- 执行 database-design preflight：确认语言、必填信息、风险、审批状态和 `detailed-design.md` 证据。
- DB1 MySQL 是事实数据唯一真相来源，Redis/MQ 不作为事实数据最终来源。
- DB2 数据库设计说明字段用途、索引用途、唯一约束、状态字段、审计字段是否必要。
- DB3 禁止无条件全表查询，动态 where 至少有有效条件。
- DB4 写库操作明确事务边界；多表写入说明同事务或最终一致性方案。
- DB5 删除优先逻辑删除，并说明关联数据校验规则。

# Evidence / Done
- `database-design.md` 已生成并可追溯。
- `schema-change-plan.sql` 已生成并可追溯。
- `migration-plan.md` 已生成并可追溯。
- `rollback-plan.md` 已生成并可追溯。
- database-design.md 使用 OLTP 或 OLAP 团队模板 有证据、假设或 required action。
- 字段和索引均有查询/约束用途 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `detailed-design.md` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `database-design.md 使用 OLTP 或 OLAP 团队模板` 失败时 blocked，不得降级为普通建议。
- DDL 需要人工审批或 waiting_for_human_review。
- 数据订正 需要人工审批或 waiting_for_human_review。
- 删除字段 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
- 模板执行协议：先读取 assets/database-oltp-template.md、assets/database-olap-template.md，按章节顺序生成，等待输入时停在 waiting_for_input，不得删除团队模板必需章节。
