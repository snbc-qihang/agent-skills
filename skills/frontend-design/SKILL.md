---
name: frontend-design
description: Use when the request is about 将需求和接口契约转化为可实现的前端设计，明确页面、组件、状态、交互、接口联调和验证策略。；Do not use when 不替代产品原型评审；不直接修改后端接口。
---

# 角色
作为研发助手 workflow 中 `frontend_design` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
将需求和接口契约转化为可实现的前端设计，明确页面、组件、状态、交互、接口联调和验证策略。

# 非目标
- 不替代产品原型评审
- 不直接修改后端接口
- 不在未确认技术栈时生成前端实现

# 输入
- `requirement-contract.json`
- `high-level-design.md`
- `interface-contracts.yaml`
- `repo_context`

# 共享治理协议
- 先读取 `engineering-assistant/shared/governance-protocol.md`；该文件是工程治理主控、能力委派、文档保留和前端验收边界的共享事实源。
- 本 skill 只覆盖 `frontend_design` 阶段；不得扩展到无关阶段或替代专业外部能力。

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
- FE1 页面结构、组件边界、状态管理、路由和交互流程明确
- FE2 技术栈、组件库、状态管理和构建工具必须来自 repo_context 或用户确认；未明确时主动询问
- FE3 接口联调契约覆盖请求、响应、错误码、权限可见性、表单校验、加载态、空态和错误态
- FE4 输出设计到 UI 映射、兼容性风险、验证方式和前后端联调清单
4. 生成全部声明产物。
5. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
6. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/frontend-design/` 下生成以下产物：
- `frontend-design.md`
- `interaction-flow.md`
- `component-contracts.yaml`
- `frontend-risk-report.json`

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- 页面和组件边界明确
- 接口联调契约明确
- 加载/空态/错误态完整
- 技术栈和组件库已确认

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- 前端技术栈变更
- 公共组件改造
- 影响核心客户端流程

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
独立运行："使用 `frontend-design` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `frontend-design` 发送给本 skill，并等待 `StageRunResult`。

# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
