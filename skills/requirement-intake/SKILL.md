---
name: requirement-intake
description: Use when the request is about 判断需求是否具备进入设计阶段的条件，并输出可复用需求契约。；Do not use when 不替代产品决策；不生成代码。
---

# 角色
作为研发助手 workflow 中 `requirement_intake` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
判断需求是否具备进入设计阶段的条件，并输出可复用需求契约。

# 非目标
- 不替代产品决策
- 不生成代码
- 不直接批准高风险需求进入设计

# 输入
- `organization_context`
- `current_process`
- `requirement_materials`
- `risk_policy`

# 前置条件
- 加载适用的团队规范和风险策略。
- 确认目标范围和运行模式。
- 如果必填输入缺失或关键边界无法确认，必须主动询问用户；不得跨越未知边界猜测。

# 语言策略
- 未指定输出语言时，沿用用户当前语言；中文请求默认 `zh-CN`，英文请求默认 `en`，不得仅为语言选择暂停任务。
- 用户确认后，将语言写入 `StageRunRequest.context.language` 和 `StageRunResult.language`。
- 当前请求语言即为已确认语言；只有混合语言导致输出目标无法判断时才询问并暂停。

# 主动询问策略
- 先读取 `engineering-assistant/standards/requirement-clarification-and-argumentation-standard.md`。仅在存在会改变方案的实质歧义时提问；每轮只问一个问题，最多六个问题，清晰后无需最终确认。
- 执行前先检查输入、仓库上下文、上游产物和 profile，区分“可推导信息”和“必须用户确认信息”。
- 对必须用户确认的信息，输出只包含当前一个 blocking 问题的 `required_information_requests`；每个问题包含 `question`、`reason`、`required`、`priority`、`expected_format` 和可选示例。
- blocking 问题未回答时，`StageRunResult.status` 必须为 `waiting_for_input`，不得继续生成通过性结论或正式文档。
- 过程产物默认写入研发助手 run artifact；只有用户明确要求正式留存时才写目标项目 `docs/human-review/`。agent 不得把 HTML 作为事实输入源。
- 一次只询问完成本阶段所需的最小问题集，优先级按 `critical`、`major`、`minor` 排序。
- 用户补充后，将答案写回 `StageRunRequest.context` 或 artifact index，并保留来源。

# 技术/框架选型
- 编码、详细设计、评审和仓库上下文分析必须识别现有技术栈与技术/框架选型。
- 选型范围包括后端框架、持久化框架、前端技术栈、组件库、中间件、测试框架、构建工具、可观测性和部署方式。
- 未能从设计、repo_context 或项目 profile 确认技术选型时，必须主动询问用户。
- Java/Spring 后端持久化默认建议 `mybatis-plus`；生成直接 `JDBC` 代码前必须有明确项目约束或评审批准。
- 任何技术替换、绕过现有 mapper/repository 模式、前端技术栈/组件库变更、测试框架或构建工具替换都必须进入 `required_information_requests` 或人工评审。

# 复杂需求论证
- `L2_SHARED`、`L3_CRITICAL` 或可行性/根因不确定时，必须生成并验证 `requirement-argumentation.json`。
- 论证覆盖架构与代码、依赖与现有复用、数据与外部系统、风险与回滚、测试、成本；最多保留三个实质不同候选。
- 结论只能是 `executable`、`executable_after_conditions` 或 `not_executable`。`not_executable` 必须停止下游并给出证据与最近可行替代。
- 重复 bug、修 A 破 B 或 L3 分歧触发 fresh-context 独立审阅；审阅者只接收 artifact 与 contract，不接收作者结论或推理。

# 执行门禁
- preflight 阶段必须先完成语言推断或确认及必须信息检查。
- 若存在 blocking `required_information_requests`，必须暂停在 `waiting_for_input`。
- 暂停等待人工输入或审批时，`StageRunResult.artifacts` 必须登记 HTML 审阅包，且该 HTML 必须通过 `validate_stage_run_result.py` 的可填写/可导出检查。
- 生成正式 Markdown 文档时必须包含 `document_number`、`document_status`、`retention_policy`、`owner` 和 `source_artifacts`。
- 输出 `StageRunResult` 后必须运行 `engineering-assistant/scripts/validate_stage_run_result.py`；校验失败视为阶段节点未遵守契约，workflow 必须 `blocked`。







# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 校验必填输入并记录假设。
3. 基于来源证据执行以下检查。
- 业务目标
- 用户场景
- 需求范围
- 非目标
- 验收标准
- 依赖系统
- 影响范围
- 接口人
- 排期约束
4. 生成全部声明产物。
5. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
6. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/requirement-intake/` 下生成以下产物：
- `requirement-intake-report.md`
- `requirement-contract.json`
- `missing-information-list.md`
- `requirement-risk-assessment.json`
- `requirement-argumentation.json`（复杂或不确定任务）

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- 业务目标存在
- 验收标准存在
- 范围清晰
- 高风险事项有 owner
- 重大依赖已确认

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- 高风险需求
- 跨系统重大依赖
- 数据/权限/发布风险

# 独立运行模式
当用户只要求执行本阶段时，仍先由 `workflow-orchestrator` 生成 controller route record，再仅执行当前 skill；不调用无关阶段。没有 controller route record 时重定向到研发助手入口，不得旁路执行。

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
独立运行："使用 `requirement-intake` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `requirement-intake` 发送给本 skill，并等待 `StageRunResult`。

# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
