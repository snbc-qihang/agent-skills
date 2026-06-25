---
name: implementation-controller
description: Use when the request is about 把已审批设计转换为机器可读实现合同和质量合同，并控制代码实现、验证、修复和最终人工审阅。；Do not use when 不审批设计进入研发；不直接替代 code-development 编写业务代码。
---

# 角色
作为研发助手 workflow 中 `implementation_control` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
把已审批设计转换为机器可读实现合同和质量合同，并控制代码实现、验证、修复和最终人工审阅。

# 非目标
- 不审批设计进入研发
- 不直接替代 code-development 编写业务代码
- 不把 HTML 人工审阅件作为 agent 事实源

# 输入
- `approved design artifact`
- `target project root`
- `project profile`
- `changed-files-report.json`

# 前置条件
- 加载适用的团队规范和风险策略。
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

# 工程治理主控
- engineering-assistant 是软件工程治理主控，不是单纯工具路由器；必须先建立需求、上下文、架构边界、实现合同、质量证据和验收状态，再选择执行能力。
- 设计阶段可以按任务裁剪，但不得裁剪掉需求边界、影响范围、open questions、质量命令、变更追踪和 gate decision。
- 默认输出模式是 `control_surface_first`：优先维护目标项目 `artifacts/_control/` 下的机读控制面；长 Markdown、阶段总结、HTML 和交接叙事只在人类评审、审计、合规、交接或用户明确要求时生成。
- 委派 Codex、Hermes、skills 或 MCP 后，本 skill 仍负责消费证据并给出工程门禁结论；被委派能力的自述成功不能直接作为通过依据。


# 能力编排与降级
- 执行前必须判断是否需要外部能力，并登记到 `artifacts/_control/capability-invocation-ledger.json`。
- 代码理解优先使用 codegraph；缺失时可降级为 `rg`、定向读文件和编译/测试反馈，但必须降低影响范围结论置信度。
- 前端产品实现和浏览器验收优先使用 build-web-apps 与 browser；缺少浏览器级能力时，不得宣称完成浏览器截图或响应式验收。
- GitHub/PR/CI 状态优先使用 GitHub 能力；缺失时只能报告本地 git diff 和本地命令结果，不得声称远端 PR 或 CI 状态。
- 安全、生产和高风险变更缺少必要能力或审批时必须阻断，不能降级为普通建议。


# 执行门禁
- preflight 阶段必须先完成语言确认和必须信息检查。
- 若存在 blocking `required_information_requests`，必须暂停在 `waiting_for_input`。
- 暂停等待人工输入或审批时，`StageRunResult.artifacts` 必须登记 HTML 审阅包，且该 HTML 必须通过 `validate_stage_run_result.py` 的可填写/可导出检查。
- 生成正式 Markdown 文档时必须包含 `document_number`、`document_status`、`retention_policy`、`owner` 和 `source_artifacts`。
- 输出 `StageRunResult` 后必须运行 `engineering-assistant/scripts/validate_stage_run_result.py`；校验失败视为阶段节点未遵守契约，workflow 必须 `blocked`。




# 实现控制面
- 所有控制产物必须写入目标项目 `artifacts/_control/`，插件目录只作为只读能力源。
- 执行前必须解析 `<plugin-root>` 和 `<target-project-root>`；所有写能力脚本必须显式传 `--root <target-project-root>`。
- 初始化控制面：`init_task.py` 生成 `current-task.json`、`artifact-index.json`、`open-questions.json` 和 `task-context.agent.md`。
- 编译设计合同：`compile_design_contract.py` 只接受已审批的 Markdown/JSON/YAML 设计产物，拒绝 HTML 作为 agent 事实源。
- 下游实现只能消费 `task-context.agent.md`、`design-contract.json`、`implementation-contract.json`、`quality-contract.json` 和 `traceability-matrix.json`；`docs/human-readable/traceability-report.html` 只给人查看。
- 变更后必须执行 `collect_changed_files.py`、`validate_design_to_code.py`、`build_traceability_report.py` 和 `run_quality_contract.py`；兼容入口 `run_quality_commands.py` 仍可用。
- `build_traceability_report.py` 必须生成机读 `artifacts/_control/traceability-matrix.json` 与人工阅览 `docs/human-readable/traceability-report.html`；HTML 是结构化追踪页面，不得由 Markdown/JSON 机械转码替代。
- 普通实现范围、测试、lint 和设计映射问题进入 `review -> repair -> validate`，最多 2 轮；业务决策、设计冲突、高风险动作、生产动作和修复耗尽才请求人工。




# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 校验必填输入并记录假设。
3. 基于来源证据执行以下检查。
- 只接受已审批 Markdown/JSON/YAML 设计产物，HTML 仅作为人工审阅入口
- 所有 `_control` 产物写入目标项目 `artifacts/_control/`，不得写入插件目录
- implementation-contract.json 必须包含 allowed_modules、forbidden_modules、expected_interfaces、expected_services、expected_repositories_or_mappers、required_tests、architecture_rules、done_conditions、technology_adoption_contract
- quality-contract.json 必须包含 required_commands 和 required_evidence，缺失或占位命令必须阻断
- 必须生成 artifacts/_control/traceability-matrix.json 作为机读事实源，并生成 docs/human-readable/traceability-report.html 作为人工阅览入口；HTML 不得反向作为 agent 事实输入
- 普通实现范围、测试、lint、设计映射失败进入 review -> repair -> validate，最多 2 轮
- 业务决策、设计冲突、高风险动作、生产动作和修复轮次耗尽才进入人工审批
4. 生成全部声明产物。
5. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
6. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/implementation-controller/` 下生成以下产物：
- `current-task.json`
- `design-contract.json`
- `implementation-contract.json`
- `quality-contract.json`
- `open-questions.json`
- `task-context.agent.md`
- `workflow-trace.json`
- `control-health-report.json`
- `technology-adoption-report.json`
- `rule-consumption-report.json`
- `traceability-matrix.json`
- `traceability-report.html`
- `repair-attempts.json`

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- 设计合同已编译
- 实现范围明确
- 质量命令非空
- 需求-设计-代码追踪关系可查看
- 修复策略明确
- 人工审阅包仅在阻断或最终审阅时生成

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- 修改已审批设计范围
- 高风险实现豁免
- 生产动作
- 修复轮次耗尽后的人工决策

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
独立运行："使用 `implementation-controller` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `implementation-controller` 发送给本 skill，并等待 `StageRunResult`。

# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
