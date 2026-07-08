---
name: mq-design
description: Use when 设计涉及异步消息、事件通知、任务流转、重试、死信、回放或跨系统最终一致性时；Do not use when do not未经审批删除或重命名 topic。
---

# When To Use
- 设计涉及异步消息、事件通知、任务流转、重试、死信、回放或跨系统最终一致性时。
- 需要明确 topic/exchange/queue、消息体、生产消费链路、幂等和补偿策略时。

# Do Not Use When
- 不要未经审批删除或重命名 topic。
- 不要隐藏重复消费、乱序、丢失或积压风险。
- 不要用 MQ 替代事实数据存储。

# Inputs
- `detailed-design.md`
- `mq-standard.md`
- `repo_context`
- `risk_policy`

# Do This
- 读取 detailed-design、repo context、MQ 标准和风险策略。
- 定义 topic/exchange/routingKey/queue、消息体版本、生产者、消费者和幂等键。
- 设计重试、死信、回放、补偿、顺序性、事务边界和监控告警。
- 输出 mq-design、message-contracts、replay-plan 和 risk report。

# Evidence / Done
- message-contracts.yaml 包含 schema、version、producer、consumer 和 idempotency key。
- replay-plan.md 说明安全回放、补偿和幂等验证。
- mq-risk-report.json 覆盖重复、乱序、积压、丢失和最终一致性。

# Stop / Escalate
- 消息体、幂等或补偿策略缺失时 blocked。
- 删除/重命名 topic 或核心链路事件变更未审批时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
