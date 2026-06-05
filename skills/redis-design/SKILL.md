---
name: redis-design
description: Use when the request is about 设计 Redis 使用方案，明确 key、value、TTL、一致性、降级和回滚策略。；Do not use when 不替代数据库主数据设计；不未经审批批量删除 Redis key。
---

# 角色
作为研发助手 workflow 中 `redis_design` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
设计 Redis 使用方案，明确 key、value、TTL、一致性、降级和回滚策略。

# 非目标
- 不替代数据库主数据设计
- 不未经审批批量删除 Redis key
- 不默认缓存所有查询

# 输入
- `detailed-design.md`
- `redis-standard.md`
- `repo_context`
- `risk_policy`

# 前置条件
- 加载适用的团队规范、`engineering-assistant/profiles/rrq-yq-team.yaml`、`engineering-assistant/registry/team-rule-catalog.yaml` 和风险策略。
- 若目标项目提供更具体的 profile，以目标项目 profile 为准，并记录与团队默认 profile 的冲突。
- 确认目标范围和运行模式。
- 正式产物生成前必须先读取用户请求、仓库上下文、profile、上游产物和 artifact index，并完成必须信息梳理。
- 如果必填输入缺失或关键边界无法确认，必须先主动询问用户；不得跨越未知边界猜测或先生成半成品。

# 语言策略
- 未指定输出语言时，必须先询问用户选择 `zh-CN`（简体中文）或 `en`（English）。
- 用户确认后，将语言写入 `StageRunRequest.context.language` 和 `StageRunResult.language`。
- 未确认语言时，不得生成正式文档；状态置为 `waiting_for_input` 并输出 blocking 问题。

# 主动询问策略
- 执行前先检查输入、仓库上下文、上游产物和 profile，区分“可推导信息”和“必须用户确认信息”。
- 对必须用户确认的信息，输出 `required_information_requests`，每个问题包含 `question`、`reason`、`required`、`priority`、`expected_format` 和可选示例。
- blocking 问题未回答时，`StageRunResult.status` 必须为 `waiting_for_input`，不得继续生成通过性结论、正式文档或下游节点输入。
- 进入 `waiting_for_input` 或 `waiting_for_human_review` 时，必须在目标项目 `docs/human-review/` 生成可填写的 HTML 人工审阅包；页面必须支持填写每个待确认项并复制或下载结构化答案 JSON；agent 不得把 HTML 作为事实输入源。
- HTML 审阅包只用于人工填写；用户答案必须写回 `StageRunRequest.context`、artifact index 或可机读 MD/JSON/YAML 后，才能继续正式产物生成。
- 一次只询问完成本阶段所需的最小问题集，优先级按 `critical`、`major`、`minor` 排序。
- 用户补充后，将答案写回 `StageRunRequest.context` 或 artifact index，并保留来源。

# 技术/框架选型
- 编码、详细设计、评审和仓库上下文分析必须识别现有技术栈与技术/框架选型。
- 选型范围包括后端框架、持久化框架、前端技术栈、组件库、中间件、测试框架、构建工具、可观测性和部署方式。
- 未能从设计、repo_context 或项目 profile 确认技术选型时，必须主动询问用户。
- Java/Spring 后端持久化默认建议 `mybatis-plus`；生成直接 `JDBC` 代码前必须有明确项目约束或评审批准。
- 任何技术替换、绕过现有 mapper/repository 模式、前端技术栈/组件库变更、测试框架或构建工具替换都必须进入 `required_information_requests` 或人工评审。

# 执行门禁
- preflight 阶段必须先完成语言确认、上下文读取和必须信息检查；preflight 未通过前不得生成正式阶段 Markdown/Excel/JSON 产物。
- 若存在 blocking `required_information_requests`，必须暂停在 `waiting_for_input`。
- 暂停等待人工输入或审批时，`StageRunResult.artifacts` 只登记补充信息请求、HTML 审阅包和恢复点，不得登记正式阶段产物为已完成；HTML 必须通过 `validate_stage_run_result.py` 的可填写/可导出检查。
- 生成正式 Markdown 文档时必须包含 `document_number`、`document_status`、`retention_policy`、`owner` 和 `source_artifacts`。
- 输出 `StageRunResult` 后必须运行 `engineering-assistant/scripts/validate_stage_run_result.py`；校验失败视为阶段节点未遵守契约，workflow 必须 `blocked`。

# Preflight 运行门闩
- 每次运行必须先输出并维护 `preflight_input_state`，取值只能是 `ready, waiting_for_input, waiting_for_human_review, blocked`。
- 只有 `preflight_input_state == ready` 时才能进入 `formal_generation`，读取模板、填充正文、写入正式 Markdown/Excel/JSON，并登记正式 artifact。
- `waiting_for_input` 时只允许登记 `required-information-request.json`、`docs/human-review/<run-id>.html`、`workflow-trace.json` 和 `resume-point.json`；不得写入或登记正式阶段产物。
- 用户补充答案必须写回 `StageRunRequest.context`、artifact index 或 MD/JSON/YAML，并保留来源和时间，之后才能把 `preflight_input_state` 置为 `ready`。







# 模板执行协议
- 只有 `preflight_input_state == ready` 时才能进入 `formal_generation` 读取模板并生成正式 Markdown；存在 blocking 缺失信息时必须先暂停并生成补充信息入口。
- 生成正式 Markdown 文档前必须先读取对应 template asset；不得凭记忆、通用模板、聊天上下文或 `assets/artifact-template.md` 生成正文。
- 以 template 原文作为唯一正文骨架，保留 frontmatter、标题层级、章节顺序、表格列头、固定提示块和格式约定。
- 只允许替换占位符、补充空白单元格和在既有章节下填充输入事实；不得删除、压缩、合并、重命名或重排模板章节。
- 输入材料缺少事实时，保留模板章节并写明“不适用原因”，或进入 `waiting_for_input` 并输出 `required_information_requests`；不得用“待补充/待确认/TODO”通过门禁。
- 模板文件不存在、无法读取或输出无法通过模板校验时，`StageRunResult.status` 必须为 `blocked` 或 `failed`。

# 对应模板
- `redis-design.md`: 生成前读取 `assets/redis-design-template.md`；适用范围：Redis 详细设计正文；来源模板：`inputs/Redis详细设计模板 - 人人取平台总体设计 - 站点标题.html`。

# 团队 Redis 设计规则
- Redis 设计必须生成独立 `redis-design.md`，不得在主详细设计中展开。
- 文档必须按 `assets/redis-design-template.md` 组织，并覆盖历史版本信息、前言、公共配置、Redis版本、集群配置、持久化策略、过期淘汰策略、设计项、资源申请和运维监控。
- 每个设计项必须包含特性用途、业务说明、存储设计、预估数据、多团队协同；存储设计必须列出库、数据结构、ttl、key 和数据格式。
- Redis 只做加速层、协调层、短态承载层，不做事实库、不做消息队列；已使用 RabbitMQ 的项目不得设计 Redis 发布订阅或 Redis 延迟队列。
- Key 默认使用 db0，建议格式 `{服务模块}:{租户ID}:{数据结构}:{业务Key}`，长度不超过 100 字节。
- 所有 Key 必须设置 TTL，最大不超过 30 天；大批量 Key 必须有随机 TTL 抖动；Redis 不可用必须有降级策略。
- Redis 版本、拓扑、持久化、淘汰策略无法确认时，状态必须为 `waiting_for_input` 或 `waiting_for_human_review`。


# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 读取用户请求、仓库上下文、profile、上游产物和 artifact index，记录不可用来源。
3. 区分可自动推导信息与必须用户确认信息；如存在 blocking 缺失项，输出 `required_information_requests`，生成 `docs/human-review/` HTML，状态置为 `waiting_for_input` 后暂停。
4. 仅当 blocking 信息已补齐并写回 `StageRunRequest.context` 或 artifact index 后，基于来源证据执行以下检查。
- R1 Redis 只做加速层、协调层、短态承载层，不做事实库、分析库、跨服务共享源、消息队列
- R2 已用 RabbitMQ 项目禁止 Redis 发布订阅或延迟队列
- R3 Redis 统一使用 db0
- R4 Key 格式为 {服务模块}:{租户ID}:{数据结构}:{业务Key}，长度不超过 100 字节
- R5 Value 单 Key 不超过 1MB，常规 String 建议不超过 10KB
- R6 所有 Key 必须设置 TTL，最大不超过 30 天，大批量 Key 增加随机抖动
- R7 redis-design.md 必须包含文档头信息、历史版本信息、前言、公共配置、Redis 版本、集群配置、持久化策略、过期淘汰策略、设计项、安全与运维、人工评审项
- R8 每个设计项必须包含特性用途、业务说明、存储设计、库、数据结构、TTL、Key 定义、Value 数据格式、预估数据和容量、多团队协同
- R9 Redis 版本、拓扑、持久化、淘汰策略无法确认时，必须进入 waiting_for_input 或 waiting_for_human_review
- R10 Redis 不可用必须有降级策略
- R11 Spring 接入优先 StringRedisTemplate，复杂结构才使用 RedisTemplate<String,Object>
- R12 库存扣减、分布式锁、幂等、延迟双删、排行榜、Pipeline 不使用 Spring Cache 注解
- R13 Redis 部署版本、拓扑、持久化和淘汰策略由项目 profile 或 repo_context 注入
5. 确认 `preflight_input_state == ready` 后进入 `formal_generation`；按模板执行协议读取对应 `assets/*-template.md`，复制模板骨架后逐节填充输入事实，再生成全部声明产物。
6. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
7. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/redis-design/` 下生成以下产物：
- `redis-design.md`
- `redis-key-registry.yaml`
- `cache-consistency-plan.md`
- `redis-risk-report.json`

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- redis-design.md 使用团队 Redis 模板
- key 命名合规
- 所有 Key 设置 TTL 且单位明确
- 一致性策略可验证
- 穿透/击穿/雪崩有策略
- 不可用降级策略明确

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- Redis key 批量删除
- 核心链路缓存策略变化
- Redis 新 Key
- 版本/拓扑/持久化/淘汰策略无法确认

# 独立运行模式
当用户只要求执行本阶段时，直接运行该 skill。生成完整产物集和门禁决策，不调用无关阶段。

# Workflow 编排模式
通过 `StageRunRequest` 接收上游产物，保留产物血缘，并向 `workflow-orchestrator` 返回 `StageRunResult`。

# 评审检查清单
- 每个结论都有证据或已记录假设。
- 每个输出路径都已进入 artifact index。
- 每个阻断问题都已形成 finding。
- 每个高风险动作都有人工审批记录。
- 输出可通过 `output.schema.json` 校验。
- `StageRunResult` 可通过 `validate_stage_run_result.py` 校验。

# 禁止行为
- 不得在无证据时宣称门禁通过。
- 不得隐藏缺失输入。
- 不得自动批准高风险动作。
- 不得用主观判断替代确定性检查。
- 不得变更生产系统。

# 示例
独立运行："使用 `redis-design` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `redis-design` 发送给本 skill，并等待 `StageRunResult`。

# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
