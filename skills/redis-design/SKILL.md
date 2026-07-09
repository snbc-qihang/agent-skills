---
name: redis-design
description: Use when 设计 Redis 使用方案，明确 key、value、TTL、一致性、降级和回滚策略；Do not use when do not 替代数据库主数据设计。
---

# When To Use
- 设计 Redis 使用方案，明确 key、value、TTL、一致性、降级和回滚策略。
- Redis 设计、缓存 key 注册、TTL、数据结构、缓存一致性和 Redis 风险评估时使用。

# Do Not Use When
- 不替代数据库主数据设计。
- 不未经审批批量删除 Redis key。
- 不默认缓存所有查询。

# Inputs
- `detailed-design.md`
- `redis-standard.md`
- `repo_context`
- `risk_policy`

# Do This
- 读取 detailed-design.md, redis-standard.md, repo_context、项目 profile、团队规则目录和 artifact index。
- 执行 redis-design preflight：确认语言、必填信息、风险、审批状态和 `detailed-design.md` 证据。
- R1 Redis 只做加速层、协调层、短态承载层，不做事实库、分析库、跨服务共享源、消息队列。
- R2 已用 RabbitMQ 项目禁止 Redis 发布订阅或延迟队列。
- R3 Redis 统一使用 db0。
- R4 Key 格式为 {服务模块}:{租户ID}:{数据结构}:{业务Key}，长度不超过 100 字节。
- R5 Value 单 Key 不超过 1MB，常规 String 建议不超过 10KB。

# Evidence / Done
- `redis-design.md` 已生成并可追溯。
- `redis-key-registry.yaml` 已生成并可追溯。
- `cache-consistency-plan.md` 已生成并可追溯。
- `redis-risk-report.json` 已生成并可追溯。
- redis-design.md 使用团队 Redis 模板 有证据、假设或 required action。
- key 命名合规 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `detailed-design.md` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `redis-design.md 使用团队 Redis 模板` 失败时 blocked，不得降级为普通建议。
- Redis key 批量删除 需要人工审批或 waiting_for_human_review。
- 核心链路缓存策略变化 需要人工审批或 waiting_for_human_review。
- Redis 新 Key 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
- 模板执行协议：先读取 assets/redis-design-template.md，按章节顺序生成，等待输入时停在 waiting_for_input，不得删除团队模板必需章节。
