---
name: detailed-design
description: Use when 概要设计已确认，需要拆成接口契约、模块任务、状态机、事务、幂等、异常和测试策略时；Do not use when do not批准设计进入研发。
---

# When To Use
- 概要设计已确认，需要拆成接口契约、模块任务、状态机、事务、幂等、异常和测试策略时。
- 实现前需要把设计转换为 implementation-plan 和 machine-readable contracts 时。

# Do Not Use When
- 不要批准设计进入研发。
- 不要直接修改代码。
- 不要省略 DB/Redis/MQ/接口/测试等适用专项。

# Inputs
- `high-level-design.md`
- `architecture-decision-record.md`
- `module-boundary.yaml`
- `team_standards`

# Do This
- 读取 HLD、ADR、module-boundary 和团队标准。
- 拆解模块、接口、DTO、状态流转、校验规则、异常码、幂等点、事务边界和回滚策略。
- 为导入、批处理、异步任务写明数据量、批次、超时、进度、失败处理。
- 输出 detailed-design、implementation-plan、interface-contracts 和 test-strategy。

# Evidence / Done
- interface-contracts.yaml 与 detailed-design.md 字段一致。
- implementation-plan.md 的任务能映射到模块边界和测试策略。
- test-strategy.md 覆盖主路径、边界、异常、幂等和回归。

# Stop / Escalate
- 概要设计或模块边界缺失时 waiting_for_input。
- 核心链路事务、高并发或权限设计未审批时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
