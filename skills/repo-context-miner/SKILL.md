---
name: repo-context-miner
description: Use when the request is about 从现有仓库中提取设计和研发所需的代码上下文，形成模块地图、接口/数据/中间件使用清单和影响范围。；Do not use when 不直接修改代码；不替代业务设计。
---

# 角色
作为研发助手 workflow 中 `repo_context` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
从现有仓库中提取设计和研发所需的代码上下文，形成模块地图、接口/数据/中间件使用清单和影响范围。

# 非目标
- 不直接修改代码
- 不替代业务设计
- 不在缺少证据时推断实现细节

# 输入
- `repository_path`
- `requirement-contract.json`
- `team_standards`
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
- 生成正式 Markdown 文档时必须包含 `document_number`、`document_status`、`retention_policy`、`owner` 和 `source_artifacts`。
- 输出 `StageRunResult` 后必须运行 `engineering-assistant/scripts/validate_stage_run_result.py`；校验失败视为阶段节点未遵守契约，workflow 必须 `blocked`。

# Preflight 运行门闩
- 每次运行必须先输出并维护 `preflight_input_state`，取值只能是 `ready, waiting_for_input, waiting_for_human_review, blocked`。
- 只有 `preflight_input_state == ready` 时才能进入 `formal_generation`，读取模板、填充正文、写入正式 Markdown/Excel/JSON，并登记正式 artifact。
- `waiting_for_input` 时只允许登记 `required-information-request.json`、`docs/human-review/<run-id>.html`、`workflow-trace.json` 和 `resume-point.json`；不得写入或登记正式阶段产物。
- 用户补充答案必须写回 `StageRunRequest.context`、artifact index 或 MD/JSON/YAML，并保留来源和时间，之后才能把 `preflight_input_state` 置为 `ready`。








# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 读取用户请求、仓库上下文、profile、上游产物和 artifact index，记录不可用来源。
3. 区分可自动推导信息与必须用户确认信息；如存在 blocking 缺失项，输出 `required_information_requests`，生成 `docs/human-review/` HTML，状态置为 `waiting_for_input` 后暂停。
4. 仅当 blocking 信息已补齐并写回 `StageRunRequest.context` 或 artifact index 后，基于来源证据执行以下检查。
- 识别 controller/service/domain/mapper/repository 等现有分层结构
- 梳理已有接口、DTO、异常码、返回结构和权限控制方式
- 梳理已有表结构、Mapper、SQL、索引和事务边界使用方式
- 梳理 Redis key、MQ exchange/routingKey/queue、定时任务和外部依赖
- 识别可复用 service、工具类、领域能力和禁止改动边界
- 输出本次需求的代码影响范围、风险点和待确认问题
5. 确认 `preflight_input_state == ready` 后进入 `formal_generation` 并生成全部声明产物。
6. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
7. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/repo-context-miner/` 下生成以下产物：
- `repo-context-report.md`
- `module-map.yaml`
- `impact-scope.yaml`
- `reusable-capabilities.md`
- `repo-risk-list.json`

# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。


# 质量门禁
- 仓库路径可访问
- 模块边界有证据
- 影响范围明确
- 可复用能力已登记

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
- 读取敏感配置
- 跨仓库分析
- 高风险影响范围确认

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
独立运行："使用 `repo-context-miner` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `repo-context-miner` 发送给本 skill，并等待 `StageRunResult`。

# 既有系统架构巡检补充规则

当用户要求对整个项目/系统做巡检、问题排查、架构问题梳理、服务详细巡查报告时，不要只按代码目录、服务名、Controller/Service/Mapper 数量输出局部问题清单。必须先补一层业务域上下文。

推荐产物顺序：
1. 先生成系统级模块地图和服务调用矩阵。
2. 基于代码证据和 Feign/事件/MQ/DB 使用关系，抽取候选业务域与限界上下文。
3. 标注核心域、支撑域、通用域、外部能力，以及每个上下文当前承载服务。
4. 再把架构问题、性能问题、代码异味归属到业务域，并说明它违反了哪个目标边界或上下文关系。
5. 对后续治理建议，优先输出领域蓝图、上下文地图、统一语言、领域治理 backlog；局部重构建议必须服从这些蓝图。

常见坑：
- 把现有服务名当成领域边界。
- 一发现 MQ/Feign/事务问题就进入修复方案，缺少核心域和目标架构方向。
- 把“服务详细巡检报告”写成静态指标报表，而没有说明服务承载了哪些业务域能力。

## CodeGraph 项目巡检模式
当用户要求“借助 codegraph”对多服务仓库做总体巡检、架构/性能/代码异味排查、核心链路模块地图或 Feign 调用梳理时，优先使用本模式。详细方法见 `references/codegraph-project-inspection.md`。

### YQ / 萤启-人人取架构巡检规则

当目标是 yq/萤启/人人取相关项目时，必须同时读取并遵守 `references/yq-architecture-governance.md`。

关键要求：
- 第一阶段先定领域划分、业务划分、数据划分、萤启-人人取总体架构图和领域架构图；未确认前不要进入 MQ/Feign/表迁移/代码重构等第二阶段具体治理。
- 使用已确认基线：萤启业务系统 + 人人取基础能力平台；平台防腐层承接 API/MQ/DTO 转换/状态映射/副本同步。
- 会员和优惠券属于萤启；人人取维护标准订单、标准商品、价格策略计算与下发、支付、设备/开门基础能力等；萤启在其上扩展 SVIP/随单购卡、定制化商品/价格/场景价、经营关系和履约扩展。
- 无代码证据或文档证据的内容必须进入讨论项或 ADR，不能写成最终结论。
- 人工产物只展示结论/风险/待决策项；机器产物保留证据链和扫描过程。

YQ/萤启项目必须同时遵守 `references/yq-architecture-inspection-governance.md`：先完成萤启-人人取总体架构、领域划分、业务划分、数据划分和架构图；未定论前不得进入 MQ/Feign/表拆分/局部重构等第二阶段治理。

必须执行：
- 先用 CodeGraph 确认索引状态、服务目录和代表性源码证据，再用脚本做全量静态扫描；不得只靠抽样下结论。
- 输出 run artifacts，不修改业务源码。推荐目录：`artifacts/project-inspection/`。
- 总体报告必须包含：系统性结论、服务风险表、架构问题、性能静态迹象、代码异味、治理路线图。
- 各服务详细报告必须包含：服务概览、主要问题、架构巡查、性能巡查、代码异味和建议动作。
- 若存在 Feign 调用，必须单独生成 Feign 调用矩阵，至少包含调用方、Feign Client、目标服务、url、fallback/fallbackFactory、方法数、HTTP 方法、路径、源码文件。
- 核心链路治理不要只按服务名切；优先按业务链路切：下单/支付/退款/开门、会员权益、券活动/促销、加盟商/售货机、统计/导出。
- 对敏感配置只列文件、行号、键名，不展示值。

YQ 专项治理补充：当巡检 `/Users/sunliming/work/project/snbc/yq` 时，必须先读取 `references/yq-architecture-inspection-governance.md`。关键要求：先做萤启业务域 vs 人人取平台能力边界；会员业务归属萤启；没有代码/文档证据的内容只能进入讨论项/开放问题/ADR，不能写成最终结论；输出必须拆分人工结果视图和机器证据视图。

风险表述要求：
- 性能问题应标注为“静态迹象”，后续需要慢查询、调用耗时、MQ 积压、线程池、缓存命中率验证。
- Feign Client 未声明 fallback 时，表述为“未在 Feign Client 上显式声明，需要确认是否存在全局熔断/降级策略”，不要武断断言系统完全没有降级。
- 对大服务先建议建立模块地图和 characterization tests，再建议拆服务或大重构。
- 对 YQ 架构巡检，任何没有代码证据、已有文档或用户/负责人决策支撑的内容，只能进入讨论记录/open questions，不得作为最终结论。
- 人工产物只给结论、风险、决策项和架构图；原始扫描、代码路径、推导链和证据明细放入机器可读 JSON/YAML/CSV。

# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
