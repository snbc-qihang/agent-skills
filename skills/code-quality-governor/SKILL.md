---
name: code-quality-governor
description: Use when the request is about 建立 Q0-Q4 多层代码质量门禁，输出可被 CI/CD、PR、workflow 消费的结构化质量报告。；Do not use when 不以 LLM 判断替代 build/test/lint；不在测试失败时输出 pass。
---

# 角色
作为研发助手 workflow 中 `code_quality` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
建立 Q0-Q4 多层代码质量门禁，输出可被 CI/CD、PR、workflow 消费的结构化质量报告。

# 非目标
- 不以 LLM 判断替代 build/test/lint
- 不在测试失败时输出 pass
- 不降级 blocker

# 输入
- `changed-files-report.json`
- `design-to-code-mapping.yaml`
- `self-test-report.md`
- `ci artifacts`

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


# 静态分析工具门禁
- 必须先发现项目已有静态检查配置：`sonar-project.properties`、`qodana.yaml|qodana.yml`、`checkstyle.xml`、`config/checkstyle/checkstyle.xml`、Maven/Gradle 中的 sonar、qodana、checkstyle 插件或 CI 配置。
- 必须优先复用项目已有配置和本机已有工具；缺失工具时可使用 `engineering-assistant/scripts/run_static_analysis_tools.py` 下载或调用 SonarScanner CLI、Qodana CLI、Checkstyle，但下载动作必须显式传入 `--allow-download`，并遵守当前环境的网络/审批限制。
- SonarScanner 运行前必须确认 `sonar.host.url` 与 token 来源；不得把 token、账号、私钥或内部地址明文写入报告。缺少 SonarQube/SonarCloud 连接信息时，记录为 `missing_input` 并阻断“完整静态分析通过”结论。
- Qodana 运行前必须确认容器模式或 Native 模式；本地缺少 Docker/Podman/qodana CLI 或项目 linter 无法确认时，记录为 `tool_unavailable` 或 `missing_input`，不得用人工主观判断替代。
- Checkstyle 必须使用项目配置；若项目没有配置，只能在报告中声明使用 `/google_checks.xml` 或 `/sun_checks.xml` 的临时基线，且该结果不得替代团队正式规则。
- 质量报告必须按 `bug`、`vulnerability`、`security_hotspot`、`code_smell`、`complexity`、`duplication`、`coverage`、`maintainability`、`reliability`、`security` 分类汇总，并把工具不可用、配置缺失、下载失败作为门禁事实输出。
- 若 Sonar/Qodana/Checkstyle 均未执行且没有可审计豁免，`gate_decision` 必须为 `block` 或 `require_human_review`，不得输出 `pass`。


# 富 HTML 报告要求
- HTML 报告是人工走查入口，不作为唯一事实源；事实源仍以 JSON、Markdown、CI 日志和工具原始输出为准。
- HTML/Markdown 人工报告默认只在 `evidence_level=formal`、人工评审、审计、合规或用户明确要求时刷新；普通控制面恢复和最小切片重构不得反复刷新长报告制造噪音。
- HTML 必须包含：门禁结论、阻断摘要、问题分级统计、质量维度统计、文件/模块分布、工具运行状态、证据与建议、人工确认区。
- HTML 中的每个 finding 必须能追溯到 `review-comments.json`、`code-quality-report.json` 或 `static-analysis-report.json` 的稳定 id。
- HTML 不得内嵌敏感 token、账号、连接串、私钥或完整内部凭据；发现敏感信息时只展示脱敏摘要和文件位置。



# 控制面质量合同
- 如果存在 `artifacts/_control/quality-contract.json`，必须执行其中 `required=true` 的质量命令，并用 `engineering-assistant/scripts/run_quality_commands.py` 生成 `quality-run-report.json`。
- 首选入口是 `engineering-assistant/scripts/run_quality_contract.py`；该报告是阻断事实源。`make validate` 通过但 `quality-contract.json.required_commands` 中任一 required 命令失败时，仍必须阻断。
- runner 必须把失败同步到 `current-task.json.active_slice`、`current-subtask.json` 和 `open-questions.json`，让后续 agent 能直接恢复到阻断点。
- 如果存在 `artifacts/_control/design-to-code-validation.json` 且状态不是 `pass`，必须阻断并先修复实现范围问题；blocker 和 major finding 均不得放行。
- 如果 `quality-contract.json` 没有 required quality commands，或命令是占位内容，必须阻断；不得用 LLM 评审替代 build/test/lint/architecture/E2E 证据。
- 普通代码质量、规范、架构边界、测试失败和设计映射问题由 agent 自动修复并重跑门禁；只在高风险审批、业务决策或修复轮次耗尽时请求人工。


# 控制面消费门禁
- 执行前必须读取目标项目 `artifacts/_control/task-context.agent.md`、`implementation-contract.json`、`quality-contract.json` 和 `artifacts/rule-governance/task-rule-packs/<task>.json`。
- 不得依赖聊天上下文记忆替代机读控制面；规则、技术栈、质量命令和停止条件必须来自控制产物。
- 进入实现、自测、质量治理或代码评审前必须先运行 `validate_control_health.py`；控制面缺失、规则包缺失或 blocking open question 必须阻断。
- 涉及代码变更后必须运行 `validate_technology_adoption.py`、`validate_design_to_code.py`、`build_traceability_report.py` 和 `validate_rule_consumption.py`。


# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 校验必填输入并记录假设。
3. 基于来源证据执行以下检查。
- 执行前必须读取 artifacts/_control/quality-contract.json、control-health-report.json、technology-adoption-report.json 和任务规则包
- build
- format
- lint
- typecheck
- unit_test
- integration_test
- coverage
- dependency_scan
- secret_scan
- migration_check
- architecture_boundary_check
- sonar_bugs_vulnerabilities_smells
- qodana_inspections_sarif
- checkstyle_style_rules
- cyclomatic_complexity
- duplication
- maintainability_reliability_security
4. 生成全部声明产物。
5. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
6. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/code-quality-governor/` 下生成以下产物：
- `code-quality-report.md`
- `code-quality-report.html`
- `code-quality-report.json`
- `gate-decision.json`
- `ci-check-summary.md`
- `static-analysis-report.md`
- `static-analysis-report.json`
- `tool-run-summary.json`
- `improvement-candidates.yaml`

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- Q0 设计一致性
- Q1 确定性工程检查
- Q1.5 Sonar/Qodana/Checkstyle 静态分析
- Q2 语义代码评审
- Q3 风险专项门禁
- Q4 发布前回归门禁

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- 高风险未审批变更
- 发布脚本变更
- 权限/认证/鉴权逻辑变更
- 支付/订单/库存/资金链路变更

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
独立运行："使用 `code-quality-governor` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `code-quality-governor` 发送给本 skill，并等待 `StageRunResult`。

# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
