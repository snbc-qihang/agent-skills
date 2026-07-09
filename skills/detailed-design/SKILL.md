---
name: detailed-design
description: Use when 将概要设计拆解为可实现的详细设计、接口契约、任务清单和测试策略；Do not use when do not 批准设计进入研发。
---

# When To Use
- 将概要设计拆解为可实现的详细设计、接口契约、任务清单和测试策略。
- 详细设计、接口契约、实现任务拆解、测试策略和回滚策略设计时使用。

# Do Not Use When
- 不批准设计进入研发。
- 不直接修改代码。
- 不省略专项设计。

# Inputs
- `high-level-design.md`
- `architecture-decision-record.md`
- `module-boundary.yaml`
- `team_standards`

# Do This
- 读取 high-level-design.md, architecture-decision-record.md, module-boundary.yaml、项目 profile、团队规则目录和 artifact index。
- 执行 detailed-design preflight：确认语言、必填信息、风险、审批状态和 `high-level-design.md` 证据。
- D1 详细设计主文档必须按 `assets/detailed-design-template.md` 的章节顺序生成：修订历史、设计背景与目标摘要、模块/功能详细设计、业务流程图、UML类图、数据库设计、接口定义、API接口列表、中间件设计、单元测试、性能与扩展性设计、人工评审项。
- D2 主文档不得生成来源证据、技术选型、数据库表结构展开、MQ 设计展开、Redis 设计展开、业务规则和校验独立章节、幂等和一致性独立章节、异常和日志独立章节、发布、灰度、上线章节。
- D3 来源证据放入 StageRunResult、repo-context 产物或评审证据；技术选型放入概要设计、技术选型评审或 repo-context 产物，除非用户明确要求，不进入详细设计正文。
- D4 数据库设计章节只能关联 `database-design.md` 或数据库模板；中间件设计章节只能关联 `mq-design.xlsx`、`redis-design.md` 和对应规范，不得在主文档重复展开字段表、消息表、Redis Key 表。
- D5 详细设计流程必须使用 Mermaid flowchart，不得用 sequenceDiagram 替代流程图；每个 flowchart 下必须紧跟流程设计说明。

# Evidence / Done
- `detailed-design.md` 已生成并可追溯。
- `implementation-plan.md` 已生成并可追溯。
- `interface-contracts.yaml` 已生成并可追溯。
- `test-strategy.md` 已生成并可追溯。
- 主详细设计只保留功能实现主线 有证据、假设或 required action。
- 专项设计独立成文并在主文档引用 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `high-level-design.md` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `主详细设计只保留功能实现主线` 失败时 blocked，不得降级为普通建议。
- 核心链路事务边界变化 需要人工审批或 waiting_for_human_review。
- 高并发路径设计 需要人工审批或 waiting_for_human_review。
- 权限/认证/鉴权设计 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
- 模板执行协议：先读取 assets/detailed-design-template.md，按章节顺序生成，等待输入时停在 waiting_for_input，不得删除团队模板必需章节。详细设计必须按章节顺序生成，禁止 sequenceDiagram，必须保留 flowchart、流程设计说明、classDiagram、waiting_for_human_review 规则。
