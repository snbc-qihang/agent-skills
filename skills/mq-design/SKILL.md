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

# 共享治理协议
- 先读取 `engineering-assistant/shared/governance-protocol.md`；该文件是工程治理主控、能力委派、文档保留和前端验收边界的共享事实源。
- 本 skill 只覆盖 `mq_design` 阶段；不得扩展到无关阶段或替代专业外部能力。

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
- 编码、设计、评审和上下文分析必须确认后端框架、持久化框架、前端技术栈、组件库、测试框架和构建工具。
- Java/Spring 持久化默认遵循 `mybatis-plus`；直接 `JDBC`、前端技术栈替换、测试框架替换或绕过既有 mapper/repository/service 模式必须主动询问或进入人工评审。

# 执行门禁
- preflight 阶段必须先完成语言确认和必须信息检查。
- 若存在 blocking `required_information_requests`，必须暂停在 `waiting_for_input`。
- 暂停等待人工输入或审批时，`StageRunResult.artifacts` 必须登记 HTML 审阅包，且该 HTML 必须通过 `validate_stage_run_result.py` 的可填写/可导出检查。
- 输出 `StageRunResult` 后必须运行 `engineering-assistant/scripts/validate_stage_run_result.py`；校验失败视为阶段节点未遵守契约，workflow 必须 `blocked`。







# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 校验必填输入并记录假设。
3. 基于来源证据执行以下检查。
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
4. 生成全部声明产物。
5. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
6. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/mq-design/` 下生成以下产物：
- `mq-design.md`
- `mq-topic-contract.yaml`
- `message-schema.json`
- `mq-risk-report.json`

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- 消息 schema 完整
- 幂等策略明确
- 重试/死信策略明确
- 监控告警明确

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- MQ topic 删除或重命名
- 核心消息链路变化
- 生产消息回放

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
