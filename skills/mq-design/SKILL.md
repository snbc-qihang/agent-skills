---
name: mq-design
description: Use when 设计 MQ 主题、消息体、生产消费链路、幂等、重试、死信和回放策略；Do not use when do not 未经审批删除或重命名 topic。
---

# When To Use
- 设计 MQ 主题、消息体、生产消费链路、幂等、重试、死信和回放策略。
- MQ 设计、topic、routing key、消息体、生产消费链路、重试和死信策略设计时使用。

# Do Not Use When
- 不未经审批删除或重命名 topic。
- 不隐藏重复消费风险。
- 不把不同语义消息混成单一处理流。

# Inputs
- `detailed-design.md`
- `mq-standard.md`
- `repo_context`
- `risk_policy`

# Do This
- 读取 detailed-design.md, mq-standard.md, repo_context、项目 profile、团队规则目录和 artifact index。
- 执行 mq-design preflight：确认语言、必填信息、风险、审批状态和 `detailed-design.md` 证据。
- M1 MQ 仅用于削峰填谷和服务解耦；进程内异步不用 MQ。
- M2 服务内通信使用 MQ 必须评审。
- M3 一个服务一个队列，一个队列可绑定多个 Exchange/routingKey。
- M4 队列默认使用仲裁队列；非仲裁队列需要评审。
- M5 必须配置死信队列，至少记录失败消息。

# Evidence / Done
- `mq-design.xlsx` 已生成并可追溯。
- `mq-topic-contract.yaml` 已生成并可追溯。
- `message-schema.json` 已生成并可追溯。
- `mq-risk-report.json` 已生成并可追溯。
- mq-design.xlsx 使用团队 MQ Excel 模板 有证据、假设或 required action。
- 生产者表完整 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `detailed-design.md` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `mq-design.xlsx 使用团队 MQ Excel 模板` 失败时 blocked，不得降级为普通建议。
- MQ topic 删除或重命名 需要人工审批或 waiting_for_human_review。
- MQ 新队列或 topic 需要人工审批或 waiting_for_human_review。
- 核心消息链路变化 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
- 模板执行协议：先读取 assets/mq-design-template.xlsx，按章节顺序生成，等待输入时停在 waiting_for_input，不得删除团队模板必需章节。
