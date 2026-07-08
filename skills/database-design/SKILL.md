---
name: database-design
description: Use when 设计涉及表结构、字段、索引、唯一约束、迁移、订正、灰度或回滚时；Do not use when do not执行生产 DDL。
---

# When To Use
- 设计涉及表结构、字段、索引、唯一约束、迁移、订正、灰度或回滚时。
- 需要评估查询模式、容量、事务边界和生产 DDL 审批点时。

# Do Not Use When
- 不要执行生产 DDL。
- 不要新增无用途字段、索引或状态列。
- 不要省略迁移和回滚方案。

# Inputs
- `detailed-design.md`
- `database-standard.md`
- `repo_context`
- `risk_policy`

# Do This
- 读取 detailed-design、database standard、repo context 和风险策略。
- 定义表、字段、索引、唯一约束、审计字段、查询模式和事务边界。
- 规划 migration、灰度、数据订正、回滚、容量和锁表风险。
- 输出 database-design、schema-change-plan.sql、migration-plan 和 rollback-plan。

# Evidence / Done
- 每个字段、索引和约束都有业务或查询用途。
- migration-plan.md 与 rollback-plan.md 可成对执行。
- database-risk-report.json 标记容量、锁表、回滚和生产审批风险。

# Stop / Escalate
- 字段/索引用途不明或回滚方案缺失时 blocked。
- DDL、数据订正、删除字段或核心链路索引调整未审批时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
