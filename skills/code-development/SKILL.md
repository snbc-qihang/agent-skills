---
name: code-development
description: Use when the request is about 基于设计文档进行最小必要代码变更或生成代码修改计划。；Do not use when 不修改无关模块；不绕过测试。
---

# 角色
作为研发助手 workflow 中 `code_development` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
基于设计文档进行最小必要代码变更或生成代码修改计划。

# 非目标
- 不修改无关模块
- 不绕过测试
- 不执行未审批高风险动作

# 输入
- `coding-eligibility.json`
- `code-design-decision.json`
- `design-contract.json`
- `implementation-contract.json`
- `detailed-design.md`（L2/L3）
- `implementation-plan.md`
- `interface-contracts.yaml`
- `repo_context`

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

# 执行门禁
- preflight 阶段必须先完成语言确认和必须信息检查。
- 若存在 blocking `required_information_requests`，必须暂停在 `waiting_for_input`。
- 暂停等待人工输入或审批时，`StageRunResult.artifacts` 必须登记 HTML 审阅包，且该 HTML 必须通过 `validate_stage_run_result.py` 的可填写/可导出检查。
- 生成正式 Markdown 文档时必须包含 `document_number`、`document_status`、`retention_policy`、`owner` 和 `source_artifacts`。
- 输出 `StageRunResult` 后必须运行 `engineering-assistant/scripts/validate_stage_run_result.py`；校验失败视为阶段节点未遵守契约，workflow 必须 `blocked`。






# 控制面消费门禁
- 执行前必须读取目标项目 `artifacts/_control/coding-eligibility.json`、`code-design-decision.json`、`task-context.agent.md`、`implementation-contract.json`、`quality-contract.json` 和 `artifacts/rule-governance/task-rule-packs/<task>.json`。
- 不得依赖聊天上下文记忆替代机读控制面；规则、技术栈、质量命令和停止条件必须来自控制产物。
- 进入实现、自测、质量治理或代码评审前必须先运行 `validate_control_health.py`；控制面缺失、规则包缺失或 blocking open question 必须阻断。
- 涉及代码变更后必须运行 `validate_technology_adoption.py`、`validate_design_to_code.py`、`build_traceability_report.py` 和 `validate_rule_consumption.py`。

# 源事实优先与反偷懒门禁
- 聊天上下文、历史摘要和 agent 记忆只能作为线索，不得作为代码修改的唯一事实源；修改前必须读取当前仓库源文件、相关测试、配置、SQL/迁移、git diff/log 或外部系统当前状态。
- 当聊天上下文与源文件、测试日志、CI、git 历史或用户最新明确纠正冲突时，必须停止使用旧上下文，重新读取源事实并记录冲突处理结论。
- 不得在没有列出“已验证事实 / 未验证假设 / 待确认风险”的情况下直接改代码。
- 若任务出现“很简单、只要改一行”的倾向，也必须完成最小事实核验：定位入口、读当前实现、读对应测试或调用方、确认改动影响面。

# 资深实现协议

## Trigger
- 所有非 L0 代码变更；业务能力、共享服务和核心链路必须完整执行。

## Do
1. 编码前先复述 `changed_fact`、owner/domain、目标模块与符号、复用点、保护行为和 public test seam；这些事实只能来自控制产物与当前源码。
2. 按 public seam 做垂直切片：先建立能失败的行为测试，再只实现当前切片；测试证明行为，不绑定私有方法或内部调用次数。
3. 业务规则放在已有 owner/domain 中；Controller、DTO、Mapper、Adapter 只承担各自边界职责。仅当源码证据证明重复、职责混杂或状态流转散落时才提取抽象。
4. 每个切片通过后检查命名、职责、异常和副作用边界，再进入下一个切片；禁止一次堆入未来需求、备用分支和无调用者抽象。
5. 完成 diff 后生成 `business-code-pileup-check.json`，逐项检查重复业务规则、无关规则集中、重复状态流转和领域泄漏。检测到任一项时退回设计或调整落点，不得用测试通过掩盖结构问题。

## Checks
- 实际改动与 `code-design-decision.json` 的 owner、落点和保护行为一致。
- 测试覆盖当前行为和至少一个保护行为，TDD 证据不能替代设计证据。
- 业务堆积检查引用最终 diff 的文件、符号和测试；方法长度本身不是阻断理由。
- 未新增无调用者抽象、重复条件链、跨领域写入或与现有框架并行的自制基础设施。

## Gate
- 缺少设计决策、实现偏离 owner/domain、或未完成业务堆积检查时阻断；使用 `CODE_DESIGN_GATE_MISSING` 或 `BUSINESS_CODE_PILEUP_UNCHECKED`。

# Git 合并/冲突防丢代码门禁
- 处理 merge、rebase、cherry-pick、冲突解决或同步远端更新时，必须比较 base/ours/theirs/最终结果，禁止只接受某一侧或只凭上下文判断。
- 必须生成或更新 `merge-safety-checklist.md`，列出被删除、被覆盖、被保留的关键逻辑、测试、配置、SQL、权限/状态判断和兼容代码。
- 对“看起来重复”的代码，删除前必须证明另一处等价逻辑仍覆盖相同业务条件；无法证明时不得删除。
- 合并后必须运行相关模块测试或至少执行能证明关键逻辑仍存在的静态检查；未运行时必须标记 residual risk。

# 修改/修复专项门禁
- 任何“修 bug、改功能、兼容历史逻辑、调整字段/状态/流程”的请求，都必须先执行“完整业务上下文扫描”，不得只围绕报错行或失败断言打补丁。
- 修改前必须读取并记录：入口 Controller/Client、Service/ServiceImpl、领域模型/DTO/VO、Mapper/Repository/SQL/迁移脚本、配置开关、定时/MQ/Feign/外部接口、现有测试、最近相关 git diff/log、同字段/同状态/同业务键的所有读写点。
- 必须生成 `business-context-map.md` 与 `change-impact-matrix.json`，列出直接改动点、上游调用方、下游消费者、共享表/字段、状态机、幂等键、事务边界、并发/重试/补偿、缓存/MQ/索引/搜索/对账/审计影响。
- 若修改 A 会影响 B，必须同时列出 B 的保护性断言或回归命令；无法确认 B 是否受影响时，状态必须为 `waiting_for_input` 或 `blocked`，不得继续声称修复完成。
- 禁止“单点补丁循环”：同一缺陷第二次修复前必须先做根因复盘，读取前一次修复 diff、失败日志和相关测试，输出 `regression-root-cause.md`；不得在未解释为何前次修复遗漏的情况下继续改代码。
- 每次代码修改必须先形成“最小安全变更计划”，包含不改哪些文件/模块、为何不改、以及如何证明未破坏相邻业务；实现后用 diff 逐项核对计划。
- 对订单、支付、库存、优惠券、会员、积分、同步、权限、认证、资金、DB 迁移、消息消费、定时任务等核心链路，默认提升为高风险修改，必须覆盖主流程、异常流、重复/幂等、回滚/补偿、并发和数据一致性验证。
- 若测试失败暴露出设计/业务契约不一致，必须先判断是代码错、测试过期还是需求变更；未确认前不得简单改测试以通过。


# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 校验必填输入并记录假设。
3. 基于来源证据执行以下检查。
- 执行前必须读取 artifacts/_control/task-context.agent.md、implementation-contract.json、quality-contract.json 和任务规则包
- 最小必要变更
- 设计映射
- 风险标记
- 测试覆盖
- 变更摘要
- 完成实现后必须运行 build_traceability_report.py 刷新 artifacts/_control/traceability-matrix.json 和 docs/human-readable/traceability-report.html
- FW1 框架选型必须来自设计、repo_context 或用户确认；缺失时主动询问
- FW2 Java/Spring 持久化默认使用 mybatis-plus；直接 JDBC 必须有评审批准
- FW3 实现必须遵循现有仓库 mapper/repository/service 分层和依赖
4. 生成全部声明产物。
5. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
6. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/code-development/` 下生成以下产物：
- `code changes`
- `implementation-summary.md`
- `design-to-code-mapping.yaml`
- `changed-files-report.json`
- `traceability-matrix.json`
- `business-code-pileup-check.json`
- `business-context-map.md`
- `change-impact-matrix.json`
- `regression-root-cause.md`（仅重复缺陷或二次修复时必需）
- `merge-safety-checklist.md`（Git 合并/冲突类任务必需）

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- `coding-eligibility.json` 与 `code-design-decision.json` 已通过确定性验证
- 每个变更映射到设计
- 无无关模块修改
- 高风险文件已标记
- 测试命令已列出且覆盖直接改动、相邻业务和历史回归点
- 需求-设计-代码追踪矩阵已刷新
- 完整业务上下文扫描已完成，`business-context-map.md` 和 `change-impact-matrix.json` 已登记到 artifact index
- `business-context-map.json`、`change-impact-matrix.json` 必须通过 `validate_anti_lazy_artifacts.py`；Git 合并/冲突任务还必须校验 `merge-safety-checklist.json`
- 重复缺陷必须有根因复盘和防复发测试；缺少任一项时 gate_decision 必须为 `block`
- 测试失败时不得只修改断言；必须有证据证明测试契约过期或实现契约需要调整
- 业务能力变更的 `business-code-pileup-check.json` 已通过；检测到规则重复、无关规则集中、重复状态流转或领域泄漏时必须回到设计/落点修正

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- DB/Redis/MQ/权限/发布脚本变更
- 核心链路实现偏离设计
- 高风险重构

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
- 不得只根据报错行、单个失败测试或聊天描述直接修改代码。
- 不得为通过测试而删除/弱化业务断言，除非有已审需求或设计契约证明原断言过期。
- 不得在未跑相邻业务回归的情况下宣称“不会影响其他功能”。

# 示例
独立运行："使用 `code-development` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `code-development` 发送给本 skill，并等待 `StageRunResult`。

# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
