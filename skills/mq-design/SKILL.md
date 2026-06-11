---
name: mq-design
description: Use when the request is about 设计 MQ 主题、消息体、生产消费链路、幂等、重试、死信和回放策略。；Do not use when 不未经审批删除或重命名 topic；不隐藏重复消费风险。
---

# 角色
作为研发助手 workflow 中 `mq_design` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
设计 MQ 主题、消息体、生产消费链路、幂等、重试、死信和回放策略。

# 非目标
- 不未经审批删除或重命名 topic
- 不隐藏重复消费风险
- 不把不同语义消息混成单一处理流

# 输入
- `detailed-design.md`
- `mq-standard.md`
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
- 生成正式 MQ Excel 文档时必须包含 `document_number`、`document_status`、`retention_policy`、`owner` 和 `source_artifacts`。
- 输出 `StageRunResult` 后必须运行 `engineering-assistant/scripts/validate_stage_run_result.py`；校验失败视为阶段节点未遵守契约，workflow 必须 `blocked`。

# Preflight 运行门闩
- 每次运行必须先输出并维护 `preflight_input_state`，取值只能是 `ready, waiting_for_input, waiting_for_human_review, blocked`。
- 只有 `preflight_input_state == ready` 时才能进入 `formal_generation`，读取模板、填充正文、写入正式 Markdown/Excel/JSON，并登记正式 artifact。
- `waiting_for_input` 时只允许登记 `required-information-request.json`、`docs/human-review/<run-id>.html`、`workflow-trace.json` 和 `resume-point.json`；不得写入或登记正式阶段产物。
- 用户补充答案必须写回 `StageRunRequest.context`、artifact index 或 MD/JSON/YAML，并保留来源和时间，之后才能把 `preflight_input_state` 置为 `ready`。







# 模板执行协议
- 只有 `preflight_input_state == ready` 时才能进入 `formal_generation` 读取模板并生成正式 MQ Excel；存在 blocking 缺失信息时必须先暂停并生成补充信息入口。
- 生成正式 MQ Excel 文档前必须先读取对应 xlsx template asset；不得凭记忆、通用模板、聊天上下文、Markdown 文档或 `assets/artifact-template.md` 生成正文。
- 以 xlsx template 文件副本作为唯一工作簿骨架，保留工作表名称、工作表顺序、表格列头、合并单元格、已有单元格样式和格式约定。
- 只允许在模板已有单元格范围内补充空白数据单元格；不得新增 sheet、不得删除 sheet、不得追加行列、不得删除或改写模板固定文本、不得修改已有样式或重排模板 sheet。
- 输入材料缺少事实时，保留模板列头并写明“不适用原因”，或进入 `waiting_for_input` 并输出 `required_information_requests`；不得用“待补充/待确认/TODO”通过门禁。
- 模板文件不存在、无法读取或输出无法通过 xlsx 模板校验时，`StageRunResult.status` 必须为 `blocked` 或 `failed`。

# 对应模板
- `mq-design.xlsx`: 生成前读取 `assets/mq-design-template.xlsx`；适用范围：MQ 设计 Excel 工作簿；来源模板：`inputs/xxxMQ设计.xlsx`。

# 团队 MQ 设计规则
- MQ 设计必须生成独立 `mq-design.xlsx`，不得在主详细设计中展开，也不得用 `mq-design.md` 作为正式正文。
- 文档必须按 `assets/mq-design-template.xlsx` 组织，至少包含 `生产者` sheet 和 `消费者` sheet。
- MQ 只用于削峰填谷、异步执行和服务解耦；进程内异步不默认使用 MQ。
- 一个服务一个队列，一个队列可绑定多个 Exchange/routingKey；队列默认建议仲裁队列，非仲裁队列需要评审。
- 必须设计死信队列、幂等策略、重试策略、死信策略和回放策略。
- 消息体默认不超过 10KB，不得承载大查询条件、文件内容或敏感明文；超过 10KB 必须评审。
- 回放生产消息、删除或重命名 topic/queue 必须人工审批。


# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 读取用户请求、仓库上下文、profile、上游产物和 artifact index，记录不可用来源。
3. 区分可自动推导信息与必须用户确认信息；如存在 blocking 缺失项，输出 `required_information_requests`，生成 `docs/human-review/` HTML，状态置为 `waiting_for_input` 后暂停。
4. 仅当 blocking 信息已补齐并写回 `StageRunRequest.context` 或 artifact index 后，基于来源证据执行以下检查。
- M1 MQ 仅用于削峰填谷和服务解耦；进程内异步不用 MQ
- M2 服务内通信使用 MQ 必须评审
- M3 一个服务一个队列，一个队列可绑定多个 Exchange/routingKey
- M4 队列默认使用仲裁队列；非仲裁队列需要评审
- M5 必须配置死信队列，至少记录失败消息
- M6 消息体默认不超过 10KB，超过需评审；压缩后仍超过也需评审
- M7 生产者定义业务消息 key、消息体、等级、TTL、持久化、Exchange、routingKey、大小、生产服务、需求号
- M8 消费者定义队列名、用途、是否单节点消费、队列类型、TTL、绑定关系、死信、消费服务、监控阈值
- M9 消息等级：9 核心交易，7 价格/会员/促销，5 配置，3 字典权限，1 数据同步/监控/死信
- M10 等级 <=3 原则上设置 TTL；等级 >5 必须持久化
- M11 顺序消息可单消费节点，但必须评审扩展性影响
- M12 mq-design.xlsx 必须至少包含生产者 sheet 和消费者 sheet；主详细设计只引用该专项，不展开 MQ 字段
- M13 消息体不得承载大查询条件、文件内容或敏感明文
- M14 回放生产消息、删除或重命名 topic/queue 必须人工审批
5. 确认 `preflight_input_state == ready` 后进入 `formal_generation`；按模板执行协议读取对应 `assets/*-template.xlsx`，复制 Excel 工作簿文件副本，只在模板已有空白数据单元格内填充输入事实，再生成全部声明产物。
6. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
7. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/mq-design/` 下生成以下产物：
- `mq-design.xlsx`
- `mq-topic-contract.yaml`
- `message-schema.json`
- `mq-risk-report.json`


# 质量门禁
- mq-design.xlsx 使用团队 MQ Excel 模板
- 生产者表完整
- 消费者表完整
- 消息 schema 完整
- 幂等策略明确
- 重试/死信/回放策略明确
- 监控告警明确

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- MQ topic 删除或重命名
- MQ 新队列或 topic
- 核心消息链路变化
- 生产消息回放
- 消息体超过 10KB
- 非仲裁队列

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
独立运行："使用 `mq-design` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `mq-design` 发送给本 skill，并等待 `StageRunResult`。



# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
