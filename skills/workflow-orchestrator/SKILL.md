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
- 加载适用的团队规范和风险策略。
- 确认目标范围和运行模式。
- 如果必填输入缺失或关键边界无法确认，必须主动询问用户；不得跨越未知边界猜测。

# 语言策略
- 未指定输出语言时，沿用用户当前语言；中文请求默认 `zh-CN`，英文请求默认 `en`，不得仅为语言选择暂停任务。
- 用户确认后，将语言写入 `StageRunRequest.context.language` 和 `StageRunResult.language`。
- 当前请求语言即为已确认语言；只有混合语言导致输出目标无法判断时才询问并暂停。

# 主动询问策略
- 由 `requirement-intake` 按 bounded clarification 执行：仅实质歧义才提问，每轮一个问题，清晰后自动进入论证或执行，不要求用户确认 Skill 路由。
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
- preflight 阶段必须先完成语言推断或确认及必须信息检查。
- 若存在 blocking `required_information_requests`，必须暂停在 `waiting_for_input`。
- 暂停等待人工输入或审批时，`StageRunResult.artifacts` 必须登记 HTML 审阅包，且该 HTML 必须通过 `validate_stage_run_result.py` 的可填写/可导出检查。
- 生成正式 Markdown 文档时必须包含 `document_number`、`document_status`、`retention_policy`、`owner` 和 `source_artifacts`。
- 输出 `StageRunResult` 后必须运行 `engineering-assistant/scripts/validate_stage_run_result.py`；校验失败视为阶段节点未遵守契约，workflow 必须 `blocked`。

# 编码资格路由

## Trigger
- workflow 将进入 `coding-only`、`implementation-controller`、`code-development`，或用户显式要求直接开始编码。

## Do
1. 基于当前仓库证据把改动分为 `L0_FAST`、`L1_DIRECT`、`L2_SHARED` 或 `L3_CRITICAL`，并生成 `coding-eligibility.json`。
2. L0 只允许无运行时行为变化的本地编辑；L1 必须有已验证的 `code-design-decision.json`；L2/L3 必须有 `approved|final` 的正式设计。
3. L2/L3 缺少正式设计时路由到 `full-feature-development`，不得进入代码节点。`single_node`、显式调用和 TDD 测试均不得绕过该判断。
4. 进入代码节点前运行 `validate_code_design_gate.py`；验证器返回 block 时记录恢复点和设计流程建议。

## Checks
- 风险等级、业务能力变更标记、当前源证据、选择路径和设计证据均已登记。
- L1 紧凑设计包含变更事实、owner/domain、复用证据、代码落点、保护行为、测试 seam 和抽象理由。
- workflow trace 记录允许编码、转设计或阻断的决定；不存在“先写再补设计”。

## Gate
- 缺少资格判断或设计证据时使用 `DESIGN_BEFORE_CODE_GATE_MISSING` 或 `CODE_DESIGN_GATE_MISSING`，并阻断代码节点。

# 自悟修复触发策略
- 当用户反馈研发助手偷懒、只信错误上下文、重复修 bug、修 A 破坏 B、Git 合并丢正确代码、弱化测试或跳过验证时，workflow 必须路由到 `self-evolution-controller` 生成自悟修复证据包、skill/eval 补丁候选和验证报告。
- 同一类失败在同一项目或同一 skill 中重复出现时，不得继续普通修复循环；必须先执行 `self-evolution-controller` 的根因复盘。
- 重复失败识别键为 `skill_id + project_id + failing_test_or_file + issue_type`；同 key 第二次出现必须暂停普通执行并进入自悟修复。
- 自悟修复可以自动生成候选补丁和运行校验，但高风险 skill、自动流转、审批策略和质量门禁变更必须暂停在 `waiting_for_human_review`。

# Workflow 运行模式
- 自然语言请求先由 `route_skill.py` 解析为能力条件 DAG。只执行选中 Skill 及其硬前置；未选节点记为 `skipped` 并说明原因，旧 `next_nodes` 仅作依赖提示。
- 同一依赖层级内无写冲突的节点必须在一次并发批次中全部派发，完成屏障后统一消费输出；Skill/worker 不得递归创建 Skill/worker，只有本编排器可以组合和重规划全局 DAG。
- 复杂任务先完成 `requirement-intake` 的 bounded clarification 与 feasibility argumentation。`not_executable` 立即停止；`executable_after_conditions` 在条件补齐前暂停。
- `auto_flow`：默认模式，从 workflow 的 `start_node` 开始，按 `next_nodes` 自动流转；任何节点返回 `waiting_for_input`、`waiting_for_human_review`、`blocked` 或 `failed` 时必须暂停。
- `auto_flow` 中，节点返回 `succeeded` 且 `required_information_requests` 为空、未声明 `HUMAN_APPROVAL_REQUIRED` 时，workflow-orchestrator 必须自动确认进入 `next_node`，并在 `workflow-trace.json` 记录 auto transition decision；不得要求用户通过对话确认。
- `high-level-design -> detailed-design` 属于 agent 自动流转检查，不等同于解锁代码的 `design-review`；只有代码研发前的设计总评审才判断是否可以进入代码阶段。
- `from_node`：从用户指定的 `start_node` 开始继续流转；必须先校验该节点存在，并确认上游必需产物已由用户、artifact index 或仓库上下文提供。
- `single_node`：只执行用户指定的 `target_node`；不得自动触发后续节点，也不得宣称全链路完成。
- workflow 可以按任务目标裁剪或组合节点，但不得静默跳过质量门禁、人工审批、必填输入检查或产物 schema 校验。
- 每次运行必须在 `workflow-trace.json` 记录 `entry_mode`、实际执行节点、跳过节点及原因、暂停原因、恢复点和下一个建议节点。







# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 校验必填输入并记录假设。
3. 基于来源证据执行以下检查。
- 阶段选择
- 状态流转
- 错误处理
- 重试
- 审批暂停
- 断点恢复
- 产物路由
- 执行日志
- DG2-DG5 产物路由时区分 run artifact 与正式留存文档，防止中间过程文档进入正式目录
4. 生成全部声明产物。
5. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
6. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/workflow-orchestrator/` 下生成以下产物：
- `workflow-trace.json`
- `workflow-summary.md`
- `approval-requests.json`
- `artifact-index.json`

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- 节点 contract 匹配
- 前置条件满足
- 产物 schema 合规
- 高风险动作进入审批

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
独立运行："使用 `workflow-orchestrator` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `workflow-orchestrator` 发送给本 skill，并等待 `StageRunResult`。

# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
