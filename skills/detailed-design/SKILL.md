---
name: detailed-design
description: Use when the request is about 将概要设计拆解为可实现的详细设计、接口契约、任务清单和测试策略。；Do not use when 不批准设计进入研发；不直接修改代码。
---

# 角色
作为研发助手 workflow 中 `detailed_design` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
将概要设计拆解为可实现的详细设计、接口契约、任务清单和测试策略。

# 非目标
- 不批准设计进入研发
- 不直接修改代码
- 不省略专项设计

# 输入
- `high-level-design.md`
- `architecture-decision-record.md`
- `module-boundary.yaml`
- `team_standards`

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
- `detailed-design.md`: 生成前读取 `assets/detailed-design-template.md`；适用范围：详细设计主文档正文；来源模板：`inputs/详细设计规范.md`。

# 团队详细设计主文档规则
- `detailed-design.md` 必须按 `assets/detailed-design-template.md` 组织，章节顺序为：1. 修订历史、2. 设计背景与目标摘要、2.1 原始需求与原型引用矩阵、3. 模块/功能详细设计、3.1. 业务流程图、3.2. UML类图、4. 数据库设计、5. 接口定义、5.1. API接口列表、5.2. 中间件设计、6. 单元测试、7. 性能与扩展性设计、8. 人工评审项。
- 主文档不得包含独立章节：来源证据、技术选型、业务规则与校验、幂等与一致性、异常与日志、发布、灰度、上线；不得展开数据库字段表、MQ 表格、Redis Key 表格。
- 来源证据只能进入 `stage-run-result.json`、repo-context 产物或评审证据；技术选型进入概要设计、技术选型评审或 repo-context，除非用户明确要求。
- `2.1 原始需求与原型引用矩阵` 必须列出 `source_id`、`source_type`、`source_path_or_url`、`prototype_page_or_section`、`requirement_item`、`design_section`、`consistency_status`；每个核心流程、接口、数据对象或规则必须可追溯到原始规格或原型。
- `数据库设计` 章节只能关联 `database-design.md` 或数据库模板；`中间件设计` 章节只能关联 `mq-design.xlsx`、`redis-design.md` 和对应规范，并登记到 `StageRunResult.artifacts`。
- 流程必须使用 Mermaid `flowchart`，禁止用 `sequenceDiagram` 替代；每个 `flowchart` 后必须紧跟“流程设计说明”。
- 每个 `3.1.x` 流程默认使用固定骨架：`触发 -> 参数/权限/状态校验 -> 核心处理 -> 外部依赖/消息协作 -> 事务/一致性处理 -> 成功终态 / 失败终态 / 重试补偿或人工处理`。
- `flowchart` 必须体现代码执行路径，覆盖正常流程、参数/权限/状态校验失败、外部依赖失败、事务/一致性失败、重试/补偿、人工处理或失败终态。
- 流程设计说明必须把业务规则、校验规则、事务边界、幂等与一致性、异常场景、日志要求以及取消、重试、补偿、文件清理等合并到对应流程下。
- 每个 `3.1.x` 流程后都必须紧跟异常场景表；异常场景必须用表格列出场景、触发条件、异常编码、异常信息、系统处理动作、数据状态、日志/告警、补偿/重试/人工处理。
- 出现 DDD、聚合根、领域服务、application/domain/infrastructure 分层、port/adapter、SDK 模板方法、Handler、Strategy、Template 等设计取向时，主文档必须补充 Mermaid `classDiagram`。
- 存在 DDL、MQ 新队列或 topic、Redis 新 Key 时，`StageRunResult.status` 必须为 `waiting_for_human_review`，不得直接 `succeeded`。


# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 读取用户请求、仓库上下文、profile、上游产物和 artifact index，记录不可用来源。
3. 区分可自动推导信息与必须用户确认信息；如存在 blocking 缺失项，输出 `required_information_requests`，生成 `docs/human-review/` HTML，状态置为 `waiting_for_input` 后暂停。
4. 仅当 blocking 信息已补齐并写回 `StageRunRequest.context` 或 artifact index 后，基于来源证据执行以下检查。
- D1 详细设计主文档必须按 `assets/detailed-design-template.md` 的章节顺序生成：修订历史、设计背景与目标摘要、模块/功能详细设计、业务流程图、UML类图、数据库设计、接口定义、API接口列表、中间件设计、单元测试、性能与扩展性设计、人工评审项
- D2 主文档不得生成来源证据、技术选型、数据库表结构展开、MQ 设计展开、Redis 设计展开、业务规则和校验独立章节、幂等和一致性独立章节、异常和日志独立章节、发布、灰度、上线章节
- D3 来源证据放入 StageRunResult、repo-context 产物或评审证据；技术选型放入概要设计、技术选型评审或 repo-context 产物，除非用户明确要求，不进入详细设计正文
- D4 数据库设计章节只能关联 `database-design.md` 或数据库模板；中间件设计章节只能关联 `mq-design.xlsx`、`redis-design.md` 和对应规范，不得在主文档重复展开字段表、消息表、Redis Key 表
- D5 详细设计流程必须使用 Mermaid flowchart，不得用 sequenceDiagram 替代流程图；每个 flowchart 下必须紧跟流程设计说明
- D6 流程设计说明必须把业务规则、校验规则、事务边界、幂等与一致性、异常场景、日志要求、取消、重试、补偿、文件清理等合并到对应流程下，不得堆到文档后半部分
- D7 出现 DDD、聚合根、领域服务、application/domain/infrastructure 分层、port/adapter、SDK 模板方法、Handler、Strategy、Template 等扩展模型时，必须补充 Mermaid classDiagram
- D8 classDiagram 至少体现聚合根或核心领域对象、application service、模板或领域服务、业务扩展接口、repository/mapper 或 port、外部适配器以及主要依赖关系
- D9 导入、批处理、异步任务必须写数据量上限、批次大小、超时时间、进度查询、失败处理
- D10 状态流转说明允许状态、终态、CAS/乐观锁控制、并发竞争处理
- D11 项目定制功能不能破坏原有通用能力，说明新增模块边界和兼容策略
- D12 详细设计必须保留原始需求规格或原型引用矩阵；每个核心流程、接口、数据对象或规则必须能追溯到 source_id，并说明与规格/原型的一致性或待确认差异
- D13 业务流程图必须体现代码执行路径，覆盖正常流程、参数/权限/状态校验失败、外部依赖失败、事务/一致性失败、重试/补偿、人工处理或失败终态
- D14 流程图后的异常场景必须用表格说明场景、触发条件、异常编码、异常信息、系统处理动作、数据状态、日志/告警、补偿/重试/人工处理
- I1 路径遵循 /api/v1、/service/v1、/console、/tapi/v1、/mapi
- I2 接口必须有充分业务理由，禁止 API 简单封装 DB CRUD
- I3 一个接口只负责一个业务功能，禁止随意加参数或合并职责不同接口
- I4 请求和响应字段使用小写驼峰，禁止拼音和无意义缩写
- I5 响应结构为 header.code/header.message/body
- I6 接口文档平台包含接口用途、适用场景、权限要求、注意事项、错误码
- I7 入参和返回参数必须有 JSR303/Javadoc 注解，必填字段使用 @NotBlank/@NotNull
- I8 废弃接口标注废弃时间、原因、替代接口
- E1 异常编码格式为 [系统]-[服务]-[模块]-[错误码]
- E2 系统编码和服务编码由项目 profile 或 repo_context 注入，错误码必须按服务归属选择
- E3 错误码范围：业务1000、参数2000、数据库3000、第三方4000、权限5000、状态6000、网络7000、系统8000、未知9000
- E4 异常包含位置、原因、建议；禁止硬编码错误消息
- E5 禁止空 catch、只打印不抛、重复打印日志、用异常控制业务流程
- E6 业务异常 INFO 不打堆栈，系统异常 ERROR 打堆栈，第三方异常 WARN 保留上下文
- E7 异常日志必须包含 TraceId，敏感信息不得进入异常消息或日志
- P1 修改核心数据接口必须评估幂等，尤其支付、订单、库存、回调、MQ 消费、表单提交
- P2 幂等依据可用全量请求体 hash 或关键业务字段排序 hash
- P3 Redis 幂等使用 SETNX + TTL；MQ 幂等使用 messageId/业务唯一键 + Redis 或 DB 记录
- P4 最终一致性只处理最新消息，旧消息基于时间戳或版本号丢弃
- P5 高竞争写使用悲观锁，低冲突场景使用乐观锁/version
- P6 分布式锁必须有超时时间和兜底方案
- P7 存在 DDL、MQ 新队列或 topic、Redis 新 Key 时，详细设计阶段状态必须为 waiting_for_human_review，不得直接 succeeded
- DG1-DG5 正式详细设计必须有文档编号、状态和留存策略；任务过程和待确认清单只作为 run artifact
5. 确认 `preflight_input_state == ready` 后进入 `formal_generation`；按模板执行协议读取对应 `assets/*-template.md`，复制模板骨架后逐节填充输入事实，再生成全部声明产物。
6. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
7. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/detailed-design/` 下生成以下产物：
- `detailed-design.md`
- `implementation-plan.md`
- `interface-contracts.yaml`
- `test-strategy.md`
- `database-design.md`
- `mq-design.xlsx`
- `redis-design.md`

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- 主详细设计只保留功能实现主线
- 专项设计独立成文并在主文档引用
- 流程使用 flowchart 且紧跟流程设计说明
- DDD/分层/扩展点方案包含 classDiagram
- 测试策略覆盖主干和异常路径

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- 核心链路事务边界变化
- 高并发路径设计
- 权限/认证/鉴权设计
- DDL
- MQ 新队列或 topic
- Redis 新 Key

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
独立运行："使用 `detailed-design` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `detailed-design` 发送给本 skill，并等待 `StageRunResult`。

# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
