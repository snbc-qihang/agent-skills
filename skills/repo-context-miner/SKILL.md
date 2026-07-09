---
name: repo-context-miner
description: Use when 从现有仓库中提取设计和研发所需的代码上下文，形成模块地图、接口/数据/中间件使用清单和影响范围；Do not use when do not 直接修改代码。
---

# When To Use
- 从现有仓库中提取设计和研发所需的代码上下文，形成模块地图、接口/数据/中间件使用清单和影响范围。
- 现有项目代码上下文梳理、模块边界识别、可复用能力识别、影响范围分析时使用。

# Do Not Use When
- 不直接修改代码。
- 不替代业务设计。
- 不在缺少证据时推断实现细节。

# Inputs
- `repository_path`
- `requirement-contract.json`
- `team_standards`
- `risk_policy`

# Do This
- 读取 repository_path, requirement-contract.json, team_standards、项目 profile、团队规则目录和 artifact index。
- 执行 repo-context-miner preflight：确认语言、必填信息、风险、审批状态和 `repository_path` 证据。
- 识别 controller/service/domain/mapper/repository 等现有分层结构。
- 梳理已有接口、DTO、异常码、返回结构和权限控制方式。
- 梳理已有表结构、Mapper、SQL、索引和事务边界使用方式。
- 梳理 Redis key、MQ exchange/routingKey/queue、定时任务和外部依赖。
- 识别可复用 service、工具类、领域能力和禁止改动边界。

# Evidence / Done
- `repo-context-report.md` 已生成并可追溯。
- `module-map.yaml` 已生成并可追溯。
- `impact-scope.yaml` 已生成并可追溯。
- `reusable-capabilities.md` 已生成并可追溯。
- 仓库路径可访问 有证据、假设或 required action。
- 模块边界有证据 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `repository_path` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `仓库路径可访问` 失败时 blocked，不得降级为普通建议。
- 读取敏感配置 需要人工审批或 waiting_for_human_review。
- 跨仓库分析 需要人工审批或 waiting_for_human_review。
- 高风险影响范围确认 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
