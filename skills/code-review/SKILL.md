---
name: code-review
description: Use when the request is about 对代码进行人工评审辅助，按问题、证据、影响、级别、建议和阻断状态输出。；Do not use when 不替代 code-quality-governor；不输出无证据建议。
---

# 角色
作为研发助手 workflow 中 `code_review` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
对代码进行人工评审辅助，按问题、证据、影响、级别、建议和阻断状态输出。

# 非目标
- 不替代 code-quality-governor
- 不输出无证据建议
- 不忽略测试缺口

# 输入
- `code-quality-report.json`
- `changed-files-report.json`
- `implementation-summary.md`
- `repo_context`

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



# 深度代码走查门禁
- 代码走查必须消费 `code-quality-report.json` 与 `static-analysis-report.json`；若缺失，必须主动运行或要求先运行 `code-quality-governor`，不得只做表层 diff 摘要。
- 每个高优先级问题必须映射到至少一个质量维度：`bug`、`vulnerability`、`security_hotspot`、`code_smell`、`complexity`、`duplication`、`coverage`、`maintainability`、`reliability` 或 `security`。
- 必须对复杂度、鉴权/越权、空指针、资源泄漏、事务边界、并发/幂等、异常吞噬、敏感信息、SQL/反序列化/反射、输入校验、测试断言质量进行显式检查；未覆盖项要写入假设或 required action。
- 走查报告必须生成 `code-review-report.html`，用于人工直观看问题分布、阻断项、证据片段、工具运行状态和修复优先级。


# 富 HTML 报告要求
- HTML 报告是人工走查入口，不作为唯一事实源；事实源仍以 JSON、Markdown、CI 日志和工具原始输出为准。
- HTML 必须包含：门禁结论、阻断摘要、问题分级统计、质量维度统计、文件/模块分布、工具运行状态、证据与建议、人工确认区。
- HTML 中的每个 finding 必须能追溯到 `review-comments.json`、`code-quality-report.json` 或 `static-analysis-report.json` 的稳定 id。
- HTML 不得内嵌敏感 token、账号、连接串、私钥或完整内部凭据；发现敏感信息时只展示脱敏摘要和文件位置。




# 控制面消费门禁
- 执行前必须读取目标项目 `artifacts/_control/task-context.agent.md`、`implementation-contract.json`、`quality-contract.json` 和 `artifacts/rule-governance/task-rule-packs/<task>.json`。
- 不得依赖聊天上下文记忆替代机读控制面；规则、技术栈、质量命令和停止条件必须来自控制产物。
- 进入实现、自测、质量治理或代码评审前必须先运行 `validate_control_health.py`；控制面缺失、规则包缺失或 blocking open question 必须阻断。
- 涉及代码变更后必须运行 `validate_technology_adoption.py`、`validate_design_to_code.py`、`build_traceability_report.py` 和 `validate_rule_consumption.py`。
- `code-development` 的 `design-to-code-mapping.yaml` 和 `traceability-matrix.json` 必须串联原始规格/原型 `source_id`、设计章节 `design_section`、代码文件 `code_path` 和验证证据；不能映射到原始规格/原型和设计的代码变更必须阻断。


# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 读取用户请求、仓库上下文、profile、上游产物和 artifact index，记录不可用来源。
3. 区分可自动推导信息与必须用户确认信息；如存在 blocking 缺失项，输出 `required_information_requests`，生成 `docs/human-review/` HTML，状态置为 `waiting_for_input` 后暂停。
4. 仅当 blocking 信息已补齐并写回 `StageRunRequest.context` 或 artifact index 后，基于来源证据执行以下检查。
- 执行前必须读取 artifacts/_control/quality-contract.json、任务规则包和 rule-consumption-report.json
- 正确性
- 边界条件
- 异常处理
- Bug 风险
- 漏洞/安全热点
- 代码异味
- 圈复杂度
- 重复代码
- 安全性
- 性能
- 可维护性
- 可靠性
- 可测试性
- 可观测性
- 团队规范一致性
5. 确认 `preflight_input_state == ready` 后进入 `formal_generation` 并生成全部声明产物。
6. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
7. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/code-review/` 下生成以下产物：
- `code-review-report.md`
- `code-review-report.html`
- `review-comments.json`
- `blocker-list.md`

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- blocker 清单为空
- 所有问题有证据
- 严重级别一致
- 静态分析指标已纳入评审
- 富 HTML 人工走查报告已生成
- 修复建议可执行

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- blocker 关闭
- 高风险人工豁免
- 核心链路评审通过

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
独立运行："使用 `code-review` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `code-review` 发送给本 skill，并等待 `StageRunResult`。



# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
