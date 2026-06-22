---
name: workflow-orchestrator
description: Use when the request is about 支持阶段选择、全链路 workflow、状态机、错误处理、审批暂停/恢复、产物传递和 trace 记录。；Do not use when 不直接生成阶段文档；不绕过子 skill contract。
---

# 角色
作为研发助手 workflow 中 `workflow_orchestration` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
支持阶段选择、全链路 workflow、状态机、错误处理、审批暂停/恢复、产物传递和 trace 记录。

# 非目标
- 不直接生成阶段文档
- 不绕过子 skill contract
- 不自动批准高风险动作

# 输入
- `workflow.yaml`
- `stage node registry`
- `StageRunRequest`
- `approval_context`

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
- `waiting_for_input` 时只允许登记信息盘点、缺失信息、目标规划、方向确认、`required-information-request.json`、`docs/human-review/<run-id>.html`、`workflow-trace.json` 和 `resume-point.json` 等控制产物；不得写入或登记正式阶段产物。
- preflight 未 ready 时禁止生成或登记正式设计文档：`high-level-design.md`、`detailed-design.md`、`database-design.md`、`redis-design.md`、`mq-design.xlsx`、`interface-contracts.yaml`、`test-strategy.md`。
- 用户补充答案必须写回 `StageRunRequest.context`、artifact index 或 MD/JSON/YAML，并保留来源和时间，之后才能把 `preflight_input_state` 置为 `ready`。


# Workflow 运行模式
- `auto_flow`：默认模式，从 workflow 的 `start_node` 开始，按 `next_nodes` 自动流转；任何节点返回 `waiting_for_input`、`waiting_for_human_review`、`blocked` 或 `failed` 时必须暂停。
- `auto_flow` 中，节点返回 `succeeded` 且 `required_information_requests` 为空、未声明 `HUMAN_APPROVAL_REQUIRED` 时，workflow-orchestrator 必须自动确认进入 `next_node`，并在 `workflow-trace.json` 记录 auto transition decision；不得要求用户通过对话确认。
- 任一节点存在 blocking `required_information_requests` 时，workflow-orchestrator 必须先生成或确认 `docs/human-review/` HTML 审阅包并暂停；用户补充答案写回 `StageRunRequest.context`、artifact index 或可机读 MD/JSON/YAML 前，不得进入后续节点。
- human-review HTML 只作为人工填写入口；workflow-orchestrator 不得把 HTML 当作上游设计、需求、审批或实现事实源。
- `high-level-design -> detailed-design` 属于 agent 自动流转检查，不等同于解锁代码的 `design-review`；只有代码研发前的设计总评审才判断是否可以进入代码阶段。
- `from_node`：从用户指定的 `start_node` 开始继续流转；必须先校验该节点存在，并确认上游必需产物已由用户、artifact index 或仓库上下文提供。
- `single_node`：只执行用户指定的 `target_node`；不得自动触发后续节点，也不得宣称全链路完成。
- workflow 可以按任务目标裁剪或组合节点，但不得静默跳过质量门禁、人工审批、必填输入检查或产物 schema 校验。
- 每次运行必须在 `workflow-trace.json` 记录 `entry_mode`、实际执行节点、跳过节点及原因、暂停原因、恢复点和下一个建议节点。
- 每个节点必须先执行 preflight gate；`preflight_input_state != ready` 时不得进入当前节点 `formal_generation`，也不得触发下游 `next_nodes`。
- workflow 必须按状态机推进：信息收集完成判定 -> 缺口识别 -> 用户追问/方向确认 -> 正式设计生成 -> 自审 -> 自动修复 -> 人工评审 -> 反馈分类 -> 增量修正 -> 知识候选沉淀。
- 人工评审反馈必须先分类为 `fact_completion`、`direction_change`、`document_defect`、`standard_violation` 或 `team_rule_candidate`；默认增量修正受影响产物，只有架构方向、数据模型、接口边界或消息模型变化才允许整套重生并标记旧版 `superseded`。
- 自审由确定性 validator 和 reviewer-agent 两层组成；Agent 只能自动修格式、模板缺口、已知事实遗漏、术语不一致、文档路由错误和已确认方案表达问题，不能替代业务方向、风险策略、系统边界或人工审批。
- 知识沉淀只生成 `rule-candidates.json`、`prompt-optimization-candidates.md` 和 `tl-review-package.json`；未经 TL 审核不得自动写入团队插件、SKILL.md、模板或规则目录。







# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 读取用户请求、仓库上下文、profile、上游产物和 artifact index，记录不可用来源。
3. 区分可自动推导信息与必须用户确认信息；如存在 blocking 缺失项，输出 `required_information_requests`，生成 `docs/human-review/` HTML，状态置为 `waiting_for_input` 后暂停。
4. 仅当 blocking 信息已补齐并写回 `StageRunRequest.context` 或 artifact index 后，基于来源证据执行以下检查。
- 阶段选择
- 状态流转
- 信息收集完成判定
- 设计目标规划
- 缺失信息识别
- 主动沟通与方向确认
- preflight 未 ready 时不得生成正式设计文档
- 错误处理
- 重试
- 审批暂停
- 断点恢复
- 产物路由
- 执行日志
- design-only 完成前运行 high-level/detailed/database/mq/redis 专项 validator
- validator-summary 汇总 stage、validator、failed_rule、error_message、suggested_repair
- 任一专项 validator 失败时 workflow 总状态不得 succeeded
- self-review findings 驱动自动修复
- unresolved blocker 阻断 approved/final
- waiting_for_human_review 不得宣称 approved/final/succeeded
- 人工评审反馈分类后增量修正，只有核心方案变化才整套重生
- defect-analysis 根因分析
- DG2-DG11 产物路由时区分 run artifact、正式留存文档、控制面、人审入口和 TL 候选，防止中间过程文档或具体需求事实进入团队插件
5. 确认 `preflight_input_state == ready` 后进入 `formal_generation` 并生成全部声明产物。
6. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
7. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/workflow-orchestrator/` 下生成以下产物：
- `workflow-trace.json`
- `workflow-summary.md`
- `approval-requests.json`
- `artifact-index.json`
- `validator-summary.json`
- `information-inventory.json`
- `context-source-map.json`
- `missing-information-list.json`
- `design-objective-plan.md`
- `scope-and-non-goals.yaml`
- `user-confirmed-facts.json`
- `design-direction-decision.md`
- `assumption-and-decision-log.yaml`
- `self-review-findings.json`
- `auto-fix-report.json`
- `unresolved-review-findings.json`
- `human-review-package.json`
- `human-review-feedback.json`
- `feedback-classification.json`
- `next-iteration-plan.md`
- `iteration-trace.json`
- `rule-candidates.json`
- `prompt-optimization-candidates.md`
- `tl-review-package.json`

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- 节点 contract 匹配
- 信息收集完成或已暂停追问
- 方案方向已确认或已暂停确认
- 前置条件满足
- 产物 schema 合规
- 专项 validator 结果全部通过或向上冒泡为 blocked
- 自审 blocker 已修复或保留为 unresolved
- 高风险动作进入审批
- TL 规范候选未自动入库

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- 人工审批网关
- 跳过阻断节点
- 恢复 blocked workflow
- 高风险动作执行
- 设计方案方向确认
- TL 规范候选入库

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
独立运行："使用 `workflow-orchestrator` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `workflow-orchestrator` 发送给本 skill，并等待 `StageRunResult`。



# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
