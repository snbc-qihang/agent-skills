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
- 如果必填输入缺失或关键边界无法确认，必须主动询问用户；不得跨越未知边界猜测。

# 语言策略
- 未指定输出语言时，必须先询问用户选择 `zh-CN`（简体中文）或 `en`（English）。
- 用户确认后，将语言写入 `StageRunRequest.context.language` 和 `StageRunResult.language`。
- 未确认语言时，不得生成正式文档；状态置为 `waiting_for_input` 并输出 blocking 问题。

# 主动询问策略
- 执行前先检查输入、仓库上下文、上游产物和 profile，区分“可推导信息”和“必须用户确认信息”。
- 对必须用户确认的信息，输出 `required_information_requests`，每个问题包含 `question`、`reason`、`required`、`priority`、`expected_format` 和可选示例。
- blocking 问题未回答时，`StageRunResult.status` 必须为 `waiting_for_input`，不得继续生成通过性结论或正式文档。
- 进入 `waiting_for_input` 或 `waiting_for_human_review` 时，必须在目标项目 `docs/human-review/` 生成可填写的 HTML 人工审阅包；页面必须支持填写每个待确认项并复制或下载结构化答案 JSON；agent 不得把 HTML 作为事实输入源。
- 一次只询问完成本阶段所需的最小问题集，优先级按 `critical`、`major`、`minor` 排序。
- 用户补充后，将答案写回 `StageRunRequest.context` 或 artifact index，并保留来源。

# 技术/框架选型
- 编码、详细设计、评审和仓库上下文分析必须识别现有技术栈与技术/框架选型。
- 选型范围包括后端框架、持久化框架、前端技术栈、组件库、中间件、测试框架、构建工具、可观测性和部署方式。
- 未能从设计、repo_context 或项目 profile 确认技术选型时，必须主动询问用户。
- Java/Spring 后端持久化默认建议 `mybatis-plus`；生成直接 `JDBC` 代码前必须有明确项目约束或评审批准。
- 任何技术替换、绕过现有 mapper/repository 模式、前端技术栈/组件库变更、测试框架或构建工具替换都必须进入 `required_information_requests` 或人工评审。

# 执行门禁
- preflight 阶段必须先完成语言确认和必须信息检查。
- 若存在 blocking `required_information_requests`，必须暂停在 `waiting_for_input`。
- 暂停等待人工输入或审批时，`StageRunResult.artifacts` 必须登记 HTML 审阅包，且该 HTML 必须通过 `validate_stage_run_result.py` 的可填写/可导出检查。
- 生成正式 Markdown 文档时必须包含 `document_number`、`document_status`、`retention_policy`、`owner` 和 `source_artifacts`。
- 输出 `StageRunResult` 后必须运行 `engineering-assistant/scripts/validate_stage_run_result.py`；校验失败视为阶段节点未遵守契约，workflow 必须 `blocked`。






# 模板执行协议
- 生成正式 Markdown 文档前必须先读取对应 template asset；不得凭记忆、通用模板、聊天上下文或 `assets/artifact-template.md` 生成正文。
- 以 template 原文作为唯一正文骨架，保留 frontmatter、标题层级、章节顺序、表格列头、固定提示块和格式约定。
- 只允许替换占位符、补充空白单元格和在既有章节下填充输入事实；不得删除、压缩、合并、重命名或重排模板章节。
- 输入材料缺少事实时，保留模板章节并写明“不适用原因”，或进入 `waiting_for_input` 并输出 `required_information_requests`；不得用“待补充/待确认/TODO”通过门禁。
- 模板文件不存在、无法读取或输出无法通过模板校验时，`StageRunResult.status` 必须为 `blocked` 或 `failed`。

# 对应模板
- `high-level-design.md`: 生成前读取 `assets/high-level-design-template.md`；适用范围：概要设计正文；来源模板：`inputs/萤启运营系统概要设计 - 萤启服务商系统 - 站点标题.html`。

# 团队概要设计模板规则
- `high-level-design.md` 必须按 `assets/high-level-design-template.md` 组织，章节顺序为：0. 原始需求与原型追溯、1. 版本变更记录、2. 平台概述、3. 系统设计、3.1 系统逻辑视图、3.1.1 系统设计原则、3.3 研发视图、3.4 研发结构定义、4. 核心功能、4.1.3 跨服务服务间时序图、5.中间件设计、6.数据视图。
- 不得用通用 `证据`、`Findings`、`必须补充信息`、`门禁决策` 模板替代概要设计正文；这些内容只能进入 `StageRunResult` 或评审产物。
- `0. 原始需求与原型追溯` 必须列出原始需求规格或原型引用矩阵，字段包含 `source_id`、`source_type`、`source_path_or_url`、`prototype_page_or_section`、`requirement_item`、`design_section`、`consistency_status`；设计事实必须能追溯到规格或原型。
- `系统设计` 必须覆盖系统逻辑视图、系统设计原则、研发视图和研发结构定义。
- `核心功能` 必须按业务功能拆分，说明参与系统、职责边界、流程、状态或异常流；涉及 Redis/MQ/DB 时只在概要层说明范围，并关联专项设计。
- 概要设计允许引用详细设计或 DB/MQ/Redis 专项文档名，但不得展开接口字段、请求/响应字段、SQL/DDL、数据库字段索引、Controller/Mapper/Repository、类方法签名、伪代码或单元测试步骤。
- 跨服务核心场景必须在核心功能下补充 Mermaid `sequenceDiagram` 服务间时序图；该时序图参与者只允许服务，禁止出现用户、页面、Controller、数据库、Redis、MQ、表、Mapper、Repository 等非服务对象。
- `中间件设计` 必须声明是否涉及 Redis/MQ/定时任务/外部依赖，并引用专项文档；`数据视图` 必须声明事实表、读模型或关联数据库专项。


# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 校验必填输入并记录假设。
3. 基于来源证据执行以下检查。
- A1 设计文档必须体现系统边界、业务域、事件协作和最终一致性；不强制平台采用微服务、事件驱动或 DDD 作为技术路线
- A2 系统间交互优先通过开放能力接口或事件；不得直接调用未开放接口
- A3 目标业务系统与目标客户端系统按不同系统边界描述，跨系统协作明确接口、事件、消息体、幂等和一致性
- A4 应用层只暴露 api/tapi/mapi/console，业务层和共享层只暴露 service 能力
- A5 关键跨系统场景进入关键场景设计；简单服务内部 CRUD 不进入关键场景文档
- A6 跨库事务优先本地消息表、事件驱动、补偿机制；必要时使用 Seata 并说明事务边界
- H1 概要设计包含平台概述、系统逻辑视图、系统设计原则、研发视图、核心功能、中间件设计、数据视图
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
4. 按模板执行协议读取对应 `assets/*-template.md`，复制模板骨架后逐节填充输入事实，再生成全部声明产物。
5. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
6. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

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

# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
