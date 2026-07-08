---
name: design-review
description: Use when 概要、详细和专项设计完成后，需要判断是否可以进入代码研发时；Do not use when do not代替审批人签字。
---

# When To Use
- 概要、详细和专项设计完成后，需要判断是否可以进入代码研发时。
- 需要对 blocker、审批、测试策略和设计完整性做证据化评审时。

# Do Not Use When
- 不要代替审批人签字。
- 不要修正文档正文。
- 不要放行未关闭 blocker。

# Inputs
- `high-level-design.md`
- `detailed-design.md`
- `database-design.md`
- `redis-design.md`
- `mq-design.md`

# Do This
- 读取 HLD、DDD、DB/Redis/MQ、接口契约和测试策略。
- 逐项评审需求准入、边界、数据流、异常流、专项设计、事务、幂等、权限和回滚。
- 把每个 finding 标记 severity、evidence、owner、required action 和阻断状态。
- 输出 design-review-report、review-findings 和 design-gate-decision。

# Evidence / Done
- design-gate-decision.json 明确 pass/block/waiting_for_human_review。
- review-findings.json 中每个 finding 有证据路径和关闭状态。
- 高风险豁免或 blocker 关闭都有审批记录。

# Stop / Escalate
- 关键设计或专项设计缺失时 blocked。
- 高风险设计放行、blocker 关闭或关键设计豁免未审批时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
