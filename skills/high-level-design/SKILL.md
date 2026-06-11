---
name: high-level-design
description: Use when the request is about 从需求契约生成概要设计，明确架构边界、数据流、异常流和发布影响。；Do not use when 不深入代码实现细节；不跳过架构风险。
---

# 角色
作为研发助手 workflow 中 `high_level_design` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
从需求契约生成概要设计，明确架构边界、数据流、异常流和发布影响。

# 非目标
- 不深入代码实现细节
- 不跳过架构风险
- 不替代设计评审审批

# 输入
- `requirement-contract.json`
- `team_standards`
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
- `high-level-design.md`: 生成前读取 `assets/high-level-design-template.md`；适用范围：概要设计正文；来源模板：`inputs/萤启运营系统概要设计 - 萤启服务商系统 - 站点标题.html`。

# 团队概要设计模板规则
- `high-level-design.md` 必须按 `assets/high-level-design-template.md` 组织，章节顺序为：0. 原始需求与原型追溯、1. 版本变更记录、2. 平台概述、3. 系统设计、3.1 系统逻辑视图、3.1.1 系统设计原则、3.3 研发视图、3.4 研发结构定义、4. 核心功能、4.1.2 关键协作摘要、4.1.3 跨服务服务间时序图、5.中间件设计、6.数据视图。
- 不得用通用 `证据`、`Findings`、`必须补充信息`、`门禁决策` 模板替代概要设计正文；这些内容只能进入 `StageRunResult` 或评审产物。
- `0. 原始需求与原型追溯` 必须列出原始需求规格或原型引用矩阵，字段包含 `source_id`、`source_type`、`source_path_or_url`、`prototype_page_or_section`、`requirement_item`、`design_section`、`consistency_status`；设计事实必须能追溯到规格或原型。
- `系统设计` 必须覆盖系统逻辑视图、系统设计原则、研发视图和研发结构定义。
- `核心功能` 必须按业务功能拆分，说明参与系统、职责边界、关键协作摘要、状态或异常流；涉及 Redis/MQ/DB 时只在概要层说明范围，并关联专项设计。
- `4.1.2 关键协作摘要` 只能使用文字描述职责边界、事件方向、异常流和最终一致性；概要设计不得生成 Mermaid `flowchart`。
- 概要设计允许引用详细设计或 DB/MQ/Redis 专项文档名，但不得展开接口字段、请求/响应字段、SQL/DDL、数据库字段索引、Controller/Mapper/Repository、类方法签名、伪代码或单元测试步骤。
- `3.3 研发视图` 和 `3.4 研发结构定义` 使用接口层、应用层、领域层、基础设施层、事件接入层等边界语言，不使用 `Controller`、`Mapper`、`Repository` 等实现标签。
- 跨服务核心场景必须在核心功能下补充 Mermaid `sequenceDiagram` 服务间时序图；该时序图参与者只允许真实系统 / 服务 / 应用边界，禁止出现用户、页面、数据库、Redis、MQ、表、Controller、Mapper、Repository 等非服务对象。
- `sequenceDiagram` 的每个 participant 必须能追溯到 repo_context 证据：代码路径、配置路径、服务注册证据、已有设计文档或用户明确补充。不得把抽象能力名直接当成真实服务写入正式时序图；找不到证据时必须进入 `waiting_for_input` / `waiting_for_human_review`，或在讨论项中标记为 proposed/unknown，不得进入正式图。
- 如果某能力由现有代码流程完成，应描述“沿用现有代码流程”，不得凭空拆出外部服务。
- 概要设计必须补充或消费 `participant-evidence-map.json`，记录 participant、display_name、status、evidence_type、repo_context、code_path、source_artifacts 等证据。缺少 evidence 或状态为 unknown/proposed/assumed/pending/unconfirmed 的 participant 视为质量门禁失败。
- 涉及 MQ / 事件 / 异步消息时，概要设计必须覆盖核心消息场景：创建 / 新增 / 产生类消息，以及状态变更 / 删除 / 失效类消息；两类消息都存在时必须分别给出核心时序。时序图只使用服务 participant，但允许服务 self-call 表达校验消息、幂等、状态/顺序判断、处理记录、本地读模型写入/移除、重试/死信等内部关键阶段；只有消息收发、没有内部处理步骤的核心链路必须阻断。
- `中间件设计` 必须声明是否涉及 Redis/MQ/定时任务/外部依赖，并引用专项文档；`数据视图` 必须声明事实表、读模型或关联数据库专项。


# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 读取用户请求、仓库上下文、profile、上游产物和 artifact index，记录不可用来源。
3. 区分可自动推导信息与必须用户确认信息；如存在 blocking 缺失项，输出 `required_information_requests`，生成 `docs/human-review/` HTML，状态置为 `waiting_for_input` 后暂停。
4. 仅当 blocking 信息已补齐并写回 `StageRunRequest.context` 或 artifact index 后，基于来源证据执行以下检查。
- A1 设计文档必须体现系统边界、业务域、事件协作和最终一致性；不强制平台采用微服务、事件驱动或 DDD 作为技术路线
- A2 系统间交互优先通过开放能力接口或事件；不得直接调用未开放接口
- A3 目标业务系统与目标客户端系统按不同系统边界描述，跨系统协作明确接口、事件、消息体、幂等和一致性
- A4 应用层只暴露 api/tapi/mapi/console，业务层和共享层只暴露 service 能力
- A5 关键跨系统场景进入关键场景设计；简单服务内部 CRUD 不进入关键场景文档
- A6 跨库事务优先本地消息表、事件驱动、补偿机制；必要时使用 Seata 并说明事务边界
- H1 概要设计包含平台概述、系统逻辑视图、系统设计原则、研发视图、核心功能、中间件设计、数据视图，核心功能只保留关键协作摘要
- H2 明确参与系统、职责边界、调用方向、事件流和异常流
- H3 声明是否涉及 Redis、MQ、DB、定时任务、权限、幂等、跨系统交互
- H4 后端业务系统研发结构按 presentation/application/domain/port/infrastructure/common 分层；如项目 profile 另有约定，以 profile 为准
- H5 application 层负责编排，不直接沉淀复杂业务判断；核心业务规则进入 domain
- H6 聚合根不通过依赖注入创建，应通过工厂创建；一次业务中聚合根创建和修改边界要清晰
- DG1-DG5 正式概要设计必须有文档编号、状态和留存策略；中间过程摘要不得作为正式文档留存
- H7 high-level-design.md 必须按 `assets/high-level-design-template.md` 的章节顺序生成，不得使用通用证据/Findings/门禁决策模板替代概要设计正文
- H8 high-level-design.md 涉及跨服务协作时必须补充 Mermaid sequenceDiagram 服务间时序图；时序图参与者只允许服务，不允许用户、页面、Controller、数据库、Redis、MQ、表、Mapper 或 Repository
- H9 high-level-design.md 必须保留原始需求规格或原型引用矩阵，使用稳定 source_id 串联 source_type、source_path_or_url、prototype_page_or_section、requirement_item、design_section 和一致性状态
- H10 high-level-design.md 聚焦跨系统/跨服务架构边界、服务间时序、调用/事件方向、异常流、最终一致性和专项文档引用；不得展开接口字段、请求/响应字段、SQL/DDL、数据库字段索引、Controller/Mapper/Repository、类方法签名、伪代码或单元测试步骤
- H11 high-level-design.md 不得包含 Mermaid flowchart；研发视图和结构定义使用接口层/应用层/领域层/基础设施层等边界语言
- H12 Mermaid sequenceDiagram 的 participant 只能是真实系统/服务/应用边界，必须有 participant-evidence-map.json 证据；抽象能力名或无证据 participant 不得进入正式图
- H13 MQ / 事件 / 异步消息场景必须覆盖创建/新增/产生类消息和状态变更/删除/失效类消息；时序图必须包含服务 self-call 表达校验、幂等、状态/顺序判断、处理记录、本地读模型写入/移除、重试/死信等内部关键阶段
5. 确认 `preflight_input_state == ready` 后进入 `formal_generation`；按模板执行协议读取对应 `assets/*-template.md`，复制模板骨架后逐节填充输入事实，再生成全部声明产物。
6. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
7. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/high-level-design/` 下生成以下产物：
- `high-level-design.md`
- `architecture-decision-record.md`
- `module-boundary.yaml`
- `risk-list.json`

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- 需求契约已准入
- 模块边界明确
- 核心数据流完整
- 架构风险有缓解方案

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- 高风险架构决策
- 跨域边界调整
- 核心链路兼容性变化

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
独立运行："使用 `high-level-design` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `high-level-design` 发送给本 skill，并等待 `StageRunResult`。

# 架构巡检 / 既有系统治理补充规则

当用户要求对既有系统做架构巡检、问题排查、重构方向、核心链路治理或服务边界梳理时，不要直接从局部代码问题进入修复建议。必须先建立业务域蓝图，再把局部问题归位。

## 最终文档与过程文档分离

架构巡检会产生大量中间草稿、机器证据、候选矩阵和 ADR。人工真正需要的是最终领域/架构梳理文档，而不是过程目录的堆叠。

执行要求：
1. 每个阶段结束时必须收敛一个 `final/` 或等价目录作为人工入口。
2. 最终人工文档只保留结论、架构图、领域边界、业务能力、数据边界、关键决策和下一阶段入口规则。
3. 过程分析、证据链、决策矩阵、open questions、扫描结果进入 `machine/`、`evidence/`、`references/` 或阶段草稿目录，不作为日常阅读入口。
4. 如果用户指出“过程文档太多”，立即停止继续扩写过程产物，生成或更新最终入口 README 和最终架构文档。
5. 最终文档必须能独立阅读，不要求读者回看前面的对话或中间分析文件。

## 既有系统架构巡检通用规则

- 先抽取业务域和限界上下文，而不是按现有服务名或代码目录直接定义架构边界。
- 按核心域 / 支撑域 / 通用域 / 外部能力标注业务能力。
- 绘制系统上下文关系：Customer/Supplier、Partnership、Shared Kernel、Conformist、Anti-Corruption Layer、Event Subscriber 等。
- 明确数据边界：上游事实服务、本地读模型、本地业务事实、集成治理数据。
- 没有代码证据、已有文档证据或用户确认的内容，只能进入 discussion / open question / ADR，不能进入最终结论。
- 不得把某个具体项目、具体系统或历史需求的架构结论写成团队通用规则。


# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
