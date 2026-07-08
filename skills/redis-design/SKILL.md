---
name: redis-design
description: Use when 设计涉及 Redis 缓存、分布式锁、限流、会话、排行榜或临时状态，需要明确 key/value/TTL/一致性时；Do not use when do not替代数据库主数据设计。
---

# When To Use
- 设计涉及 Redis 缓存、分布式锁、限流、会话、排行榜或临时状态，需要明确 key/value/TTL/一致性时。
- 需要证明 Redis 不是事实数据最终来源，并定义降级、回源和回滚策略时。

# Do Not Use When
- 不要替代数据库主数据设计。
- 不要未经审批批量删除 Redis key。
- 不要把无 TTL 缓存或无回源策略设计为可上线方案。

# Inputs
- `detailed-design.md`
- `redis-standard.md`
- `repo_context`
- `risk_policy`

# Do This
- 读取 detailed-design、repo context、Redis 标准和风险策略。
- 定义 key pattern、value schema、TTL、容量估算、命中率目标和过期策略。
- 说明缓存一致性、穿透/击穿/雪崩、降级、回源、失效和回滚。
- 输出 redis-design、key-registry、fallback-plan 和 risk report。

# Evidence / Done
- redis-key-registry.yaml 包含 owner、pattern、TTL、value schema 和删除策略。
- fallback-plan.md 说明 Redis 不可用时的业务行为。
- redis-risk-report.json 标记一致性、容量和批量操作风险。

# Stop / Escalate
- 无法证明主数据来源或 TTL 策略时 blocked。
- 批量删除、锁策略或核心链路缓存变更未审批时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
