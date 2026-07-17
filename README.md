# teamwork-engineering-assistant

`agent-skills` 是 `teamwork-engineering-assistant`（团队研发助手）的统一作者源。产品完整继承 `engineering-assistant` 的 11 个工程原语、运行内核和平台协议，并以默认 `rrq-yq-team` profile 扩展团队交付流程与规范。

- 当前版本：`2.0.0.0-rc.1`
- 开发者：`sunliming625@gmail.com`
- 运行平台：Codex、Hermes
- 开发语言：Python 3.9+
- 默认语言：简体中文，同时保留中英文任务路由能力
- 产品默认 profile：`rrq-yq-team`；可显式切换通用 `default`

## 项目定位

本项目不把研发流程拆成大量需要用户记忆的阶段命令，而是将能力划分为四层：

1. 公开 skill：面向用户和模型的稳定工程原语。
2. 内部 flow：组织多步骤任务的有向无环图。
3. capability/policy pack：只在相关领域进入范围时加载的专业能力和规则。
4. runtime kernel：负责路由、状态、证据、门禁、恢复和平台构建；CLI、工具名和 artifact 路径保持 `ea`、`engineering_assistant_*` 和 `.run-artifacts/engineering-assistant/` 兼容。

目标是让执行过程可预测，而不是把输出固定成模板。Agent 负责语义判断和工程工作，运行时负责确定性状态与安全边界。

## 快速开始

### 普通用户

已经安装插件时，不需要执行 `pip install` 或手动维护 `ea` 状态机，直接在 Codex App 或 Hermes 中用自然语言描述任务即可。例如：

```text
请先梳理当前仓库上下文，再给出最小充分的实现方案。
基于代码证据诊断这个问题，说明根因、影响和验证结果。
评审当前变更是否同时符合仓库规范和原始需求。
```

Codex 可以根据 skill 的名称和描述自动选择能力，也可以通过 `$repo-context`、`$diagnosing-bugs`、`$code-review` 等名称显式调用。Hermes 可以通过自然语言选择 skill，也可以使用限定名：

```bash
hermes --skills teamwork-engineering-assistant:repo-context
```

### 从仓库安装到本机

先执行无副作用预演，再显式确认本机发布：

```bash
python3 scripts/publish_local.py --platform codex --dry-run
python3 scripts/publish_local.py --platform codex --yes

python3 scripts/publish_local.py --platform hermes --dry-run
python3 scripts/publish_local.py --platform hermes --yes
```

同时安装两个平台时，将 `--platform` 改为 `all`。发布脚本会完成测试、评测、构建、摘要校验、备份、原子替换、平台注册和安装后验证。详细行为见 [本机发布](docs/operations/local-publish.md)；真实产品收益验证见 [真实产品 Canary](docs/operations/canary.md)。

### 当前平台集成边界

当前发布包会自动注册 11 个公开 skill，并将同一 Runtime 控制面接入平台：Codex 通过包内 `.mcp.json` 启动 stdio MCP，Hermes 通过插件工具注册复用相同 `RuntimeTools`。两个 adapter 也会注册共享的反馈采集器：Codex 只为本插件 namespaced MCP 工具注册 `PreToolUse` 与 `PostToolUse`，Hermes 在插件 adapter 内使用 `post_llm_call`。

| 能力 | 当前行为 |
| --- | --- |
| 发现并选择公开 skill | 平台可根据任务隐式选择，也支持用户显式指定 |
| 加载 `SKILL.md` 和按需参考资料 | 选择 skill 后由平台完成 |
| `route/start/next/complete` | 平台可作为工具调用；`start` 接收 intent 并在服务端重算路由，选择 skill 本身不会隐式启动状态机 |
| 人工审批与调研选择 | 只接受管理员固定 HTTPS broker 验证的 opaque grant；不存在自由文本 `approve` CLI |
| `RunState` 持久化、DAG 推进和 Runtime 门禁 | 平台调用 Runtime 工具后生效，状态只写入目标项目 `.run-artifacts/engineering-assistant/` |
| Hook 反馈采集 | Codex 仅从本插件 MCP Pre/Post 提升可观测的工具失败和 usage 信号；Hermes 可在插件轮次内补充纠正、阻断、返工和范围变化；两者都记录无原文 capture 元数据并支持独立审计处置 |
| `ea validate/artifact-validate/eval/build/verify-package/canary-audit/canary-prepare/canary-attestation-import/canary-assemble/canary-validate` | 由开发者、CI 或发布维护者执行 |

所以，当前产品体验是“平台选择 skill，必要时调用 Runtime 工具进入受治理运行，并由生命周期 Hook 采集反馈候选”。只有出现实际 Runtime 工具调用和落盘状态，才能声称状态机、证据门禁或恢复机制已运行。聊天中的“同意”不会自动转换为签名 grant。Codex 的插件 Hook 在用户审查并信任当前定义前会被跳过。

## 核心设计

- 单一事实源：skill、flow、policy、pack、provider、开源来源决策和 profile 的机器定义只存在于 `catalog/`。
- 渐进加载：公开 skill 只加载当前分支需要的 `references/` 和 pack，避免上下文膨胀。
- 可验证完成：flow 节点通过 `StepResult`、完成条件和 `EvidenceRef` 判断是否推进。
- 确定性门禁：高风险动作、审批、证据时效和状态转换由 runtime 执行。
- 可恢复运行：`RunState` 持久化当前节点、revision、审批和阻断原因，可在进程中断后继续。
- 平台无关核心：Codex 与 Hermes 共用相同 catalog、skills、packs、schemas 和 runtime，仅 adapter 不同。
- 无生成镜像：仓库不保存发布包或大面积派生副本，发布时从作者源临时构建。

## 仓库结构

```text
agent-skills/
├── catalog/                    # Product、Skill、Flow、Policy、Pack、规则目录、Provider、来源决策、Profile
├── skills/                     # 11 个公开 skill 及按需 references
├── packs/                      # 17 个专业能力与策略包
├── schemas/                    # 核心协议 JSON Schema
├── src/engineering_assistant/  # 路由、状态机、证据、编译器和平台 adapter
├── evals/                      # Routing、Behavior、State、Replay、Canary
├── tests/                      # 单元、行为、构建、发布和仓库治理测试
├── scripts/                    # 本机 Codex/Hermes 发布入口
├── config/                     # 当前本机发布策略
├── docs/architecture/          # 当前架构说明
├── docs/operations/            # 当前运维说明
├── VERSIONING.md               # 四段式版本规范
└── pyproject.toml              # Python 包与 ea CLI 配置
```

作者源职责：

| 变更内容 | 修改位置 |
| --- | --- |
| 产品身份和默认 profile | `catalog/product.json` |
| Skill 触发和完成语义 | `catalog/skills/` 与 `skills/` |
| Flow 节点和依赖 | `catalog/flows/` |
| 安全、审批和证据规则 | `catalog/policies/` |
| 专业领域能力 | `catalog/packs/` 与 `packs/` |
| 团队规则、来源和目标落点 | `catalog/rules/` |
| 能力提供方及供应链约束 | `catalog/providers/` |
| 开源能力采用决策与落点 | `catalog/sources/` |
| 公共数据协议 | `schemas/` 与 `model.py` |
| 路由和状态转换 | `router.py`、`engine.py`、`state_store.py` |
| 平台输出 | `adapters/codex.py`、`adapters/hermes.py` |
| 本机发布行为 | `local_publish.py`、`scripts/publish_local.py` |

## 公开 Skills

| Skill | 用途 |
| --- | --- |
| `engineering-assistant` | 将复杂工程请求路由到最小充分的 skill 或 flow |
| `research` | 基于一手资料研究外部项目、API、标准和技术事实 |
| `decision-interview` | 在事实调查后收敛范围、取舍和验收决策 |
| `domain-modeling` | 澄清领域术语、关系和难以逆转的决策 |
| `repo-context` | 从源码提取模块、接口、数据、依赖和影响范围 |
| `wayfinder` | 管理大型任务的目标、当前前沿和待决事项 |
| `prototype` | 用可丢弃的逻辑或界面原型回答一个设计问题 |
| `codebase-design` | 设计深模块、小接口、真实 seam 和局部化变更 |
| `tdd` | 以红绿循环和纵向切片实现已确认行为 |
| `diagnosing-bugs` | 通过复现、假设、定向观测和回归证据诊断问题 |
| `code-review` | 分别按仓库规范和原始需求评审固定 diff |

每个 skill 的 `SKILL.md` 只保留 `name`、`description` 和必要执行规则；专项资料放在同目录 `references/` 中按需加载。

## 内部 Flows

| Flow | 节点 |
| --- | --- |
| `shape` | 事实调查 → 决策收敛 → 需求契约 |
| `design` | 仓库上下文 → 条件化原型 → 架构 → 实现契约 → 设计评审 |
| `implement` | 选择切片 → 红绿循环 → 实现 → 质量证据 → 代码评审 |
| `review` | 固定比较点 → 代码评审/设计评审 → 结论门禁 |
| `release` | 发布就绪 → 发布验证 → 复盘 |
| `evolve` | 反馈摄取 → 知识提炼 → 候选变更 → 质量审计 |
| `team-delivery` | 需求事实 → 决策/契约 → 架构与按需专项设计 → 可信设计审批 → 切片/TDD/实现 → 六维质量 → 可信代码确认 → 发布审批/外部验证 → 复盘 → TL 规范候选处置 |

Flow 不是提示词清单。`RuntimeEngine` 会消费 DAG、计算下一节点、检查审批和证据，并将状态持久化到目标项目。

## 能力与策略 Packs

| Pack | 激活条件 |
| --- | --- |
| `frontend-product` | 浏览器或应用用户体验发生变化 |
| `database` | Schema、查询、索引、事务或数据修复进入范围 |
| `redis` | Redis key、缓存、锁或失效逻辑发生变化 |
| `mq` | Topic、消息体、生产消费、重试或回放发生变化 |
| `quality-evidence` | 实现、评审或发布需要声明完成 |
| `document-governance` | 创建、提升或废弃正式项目文档 |
| `release-safety` | 进入发布就绪、验证、回滚或生产观察 |
| `feedback-evolution` | 反馈可能改变 skill、flow、policy 或 eval |
| `team-standards` | 仓库或项目 profile 提供团队规则 |
| `rrq-yq-delivery` | 团队需求、文档、概要/详细设计和知识沉淀规则命中 |
| `rrq-yq-architecture` | 架构、DDD、JDK、框架和萤启约束命中 |
| `rrq-yq-api` | 接口、YApi 或异常契约命中 |
| `rrq-yq-code-quality` | 研发、TDD、质量、安全、日志、监控、幂等或并发命中 |
| `rrq-yq-frontend` | 影响范围命中前端 |
| `rrq-yq-database` | 影响范围命中数据库 |
| `rrq-yq-redis` | 影响范围命中 Redis |
| `rrq-yq-mq` | 影响范围命中 MQ |

团队规则目录固定包含 105 条规则、8 个来源记录和 8 个目标 packs。每条规则只有一个规范定义；`engineering_assistant_route` 会按任务及影响范围返回启用的团队 packs、规则和来源，即使宿主降级为 `skills_only` 也不会丢失规范上下文。持久化节点只暴露与当前 capability 匹配的规则，运行证据通过 `EvidenceRef.contract_refs` 登记 `rule:<rule-id>`；仓库不保存原始站点 HTML 或附件镜像。

Policy 优先级为：不可豁免安全规则 → 项目 profile → flow → skill → task override。降低安全等级必须有明确授权，不可豁免规则不能被 override。

### 外部 UI/UX Provider

六个评估来源的当前决策由 `catalog/sources/open-source.json` 机器校验：Anthropic Skills、Superpowers、Addy Osmani Agent Skills 与 Taste Skill 只融合规范或工程原则；UI/UX Pro Max 作为固定 revision、摘要和许可证的外部 Provider；UX/UI Agent Skills 因能力重叠且没有足以抵消上下文、供应链和维护成本的独立增量而不导入。每项记录都绑定 reviewed revision、许可证证据、代表性上游路径和本仓库落点；`fuse` 不表示复制整个上游仓库，`not_adopted` 也不会在运行时加载其资产。

前端审美、反模板化规则和评审方法融合进原生 `frontend-product` pack；可执行设计知识不复制进核心，而是通过固定来源 Provider 调用。当前 `ui-ux-pro-max` Provider 固定到 MIT 许可的 revision `3da52ff1cab1be91848072ec1be5f493d730fd5f` 及 bundle 摘要，只为 `frontend-design` 和 `product-prototype-review` 提供只读建议。

`engineering_assistant_provider_invoke` 可接收外部 bundle 路径；宿主也可通过 `ENGINEERING_ASSISTANT_UI_UX_PRO_MAX_ROOT` 固定受信路径。执行器拒绝 symlink、pyc、特殊文件、超深/超量目录和超限体积，把普通文件复制到私有快照并对快照验证摘要，再从快照执行。子进程不使用 shell、不传 HOME/代理环境、不使用 `--persist`；macOS 沙箱以 `deny default` 为基线，只放行系统运行时、固定 Python 运行时、私有快照与工作目录读取，禁止网络、fork、额外 exec 和工作目录外写入，并限制时间、进程组和输出文件；没有等价最小权限沙箱的平台安全回退原生能力。bundle 缺失、被篡改、超时或执行失败时返回 `fallback` 与明确的原生执行指令。完整 invocation claim 与结果分别不可变审计到当前 run 的 `providers/`，同 ID 不同输入会冲突，同请求并发只允许 first writer 执行；first writer 崩溃且执行租约到期后，仅一个 CAS 接管者可以恢复。Provider 输出固定标记为 `untrusted_advisory`，不是 `observed` evidence，不能直接完成节点或绕过质量门禁。

## 运行机制

```mermaid
flowchart TB
    U["用户请求"] --> A["平台 Agent"]
    A --> K["自动发现并加载 Skill"]
    K --> W["Agent 按 Skill 执行工程工作"]

    A -. "平台选择调用 Runtime 工具" .-> I["RouteIntent"]
    I --> R["确定性 Router"]
    R --> D["RouteDecision"]
    D --> E["RuntimeEngine"]
    E --> G["GateDecision"]
    G -->|推进| S["执行 Flow 节点"]
    G -->|等待| H["输入或人工审批"]
    S --> X["StepResult + EvidenceRef"]
    X --> E
    E --> P["RunState 持久化"]
    W --> F["生命周期 Hook"]
    F --> C["FeedbackCapture + FeedbackEvent + UsageEfficiencyFeedback"]
```

默认运行状态写入目标项目：

```text
.run-artifacts/engineering-assistant/
```

反馈 capture、候选事件、审计处置和去标识化效率候选分别写入该目录下的 `feedback/captures/`、`feedback/events/`、`feedback/dispositions/` 与 `feedback/efficiency-candidates/`。Hook 不保存原始 transcript、原始命令、原始工具输入输出或内容摘录；capture 会保存内容摘要、长度、脱敏计数、采集时间，以及由 session/turn 单向哈希得到的可关联伪名引用。运行期 usage ledger 还会短暂保存 task 摘要、伪名 session/turn 引用和最近 256 条工具签名哈希，用于幂等汇总。Codex 在本插件 MCP 工具的 PostToolUse 完成后尝试汇总：若仍有已跟踪调用未完成则等待后续 PostToolUse，避免把正常并发误报为缺失完成事件；全部已跟踪调用完成且出现受控效率信号并成功生成候选时，按已汇总 revision 条件清理 ledger；若其间出现并发新调用，则将新增计数与散列事件原子换入新的 observation，而不删除或重复计入已汇总快照。尚无信号时保留有界散列签名，以便同轮后续插件调用识别重复输入；任一环节失败时也保留以便重试。真正缺失的 PostToolUse 只在平台提供的可靠轮次结束边界汇总。Hermes 在插件自身轮次结束时汇总。新插件调用会机会式清理超过 24 小时的孤儿 ledger，单次最多扫描 256 个文件。效率候选使用随机 ID，只保留聚合计数和受控信号；事件与处置用于长期优化输入，处置不覆盖原事件。处置文件中的 reason、actor_ref 和 evidence_refs 是人工或 CI 明确提交的原文元数据，Runtime 不会自动脱敏，因此不得放入凭证、个人信息或业务秘密；summary 和演进导出都不回显 reason 或 actor_ref，演进导出不复制处置 evidence_refs，并把事件 ID、复发键、事件 evidence_refs 和资产引用统一转成单向 SHA-256 opaque 引用。`ea feedback-summary --project-root <目标项目>` 以有界内存流式汇总效率、问题类型、人工参与、有效处置和有限条最近事件；复发键最多保留 256 个精确计数，超出部分只计入 `recurrence_overflow_event_count`，不会导致长期事件库占用无限增长。`ea feedback-disposition --project-root <目标项目> --input <文件>` 只导入人工或 CI 明确提供的不可变处置。`ea feedback-evolution-export --project-root <目标项目>` 只把当前有效且明确接受的反馈转换为确定性、可分页、去敏的回归提案，并固定标记 `requires_review=true`、`formal_assets_modified=false`。导出只在扫描前后短暂读取 disposition snapshot revision，不会在全库扫描期间占用处置写锁；后续页必须同时提交 opaque cursor 和该 revision，若处置集合变化则丢弃本页并明确要求从第一页重启，避免静默遗漏或输出过期 accepted 项。三者都不会自动修改 skill、flow、policy、eval 或门禁；当前 adapter 尚未获得可信 workspace 绑定，因此模型工具不暴露跨项目汇总、处置或演进入口。损坏 artifact 只计数、不回显内容。企业环境应由目标项目所有者为 captures/events/dispositions/candidates 制定合规保留与归档周期；Runtime 当前不擅自删除这些长期优化资料。环境变量 `ENGINEERING_ASSISTANT_FEEDBACK_MODE` 支持：

- `candidates`：默认模式，保存 capture 并提升有效反馈候选。
- `metadata`：只保存 capture 元数据。
- `disabled`：关闭反馈写入。

核心协议包括：

- `SkillSpec`：公开 skill 的触发、能力、完成条件和上下文指针。
- `RouteIntent` / `RouteDecision`：结构化意图和确定性路由结果。
- `FlowSpec`：节点、依赖、条件和完成标准。
- `PolicySpec`：规则、优先级、可覆盖性和违规动作。
- `RunState`：绑定 profile 的运行状态、当前节点、revision、审批和阻断信息。
- `StepResult`：节点执行结果和逐项完成条件。
- `GateDecision`：推进、等待输入、等待审批、重试或阻断。
- `EvidenceRef`：源码、测试、CI、浏览器或外部状态证据。
- `CapabilityProviderSpec`：能力提供方、执行模式、固定来源、风险、网络和失败策略。
- `FeedbackEvent`：问题、阻断、人工修正和可复用候选的结构化反馈。
- `FeedbackDisposition`：人工或 CI 对反馈事件作出的不可变、可审计处置。
- `FeedbackCapture`：插件工具或 Hermes 插件轮次的 Hook 是否执行、内容摘要、脱敏计数和候选事件引用。
- `UsageEfficiencyFeedback`：Codex 插件工具完成或 Hermes 插件轮次结束后生成的去标识化工具/输出聚合候选，仅用于离线持续优化；模型侧只能读取匿名汇总。
- `QualitySnapshot`：正确性、复杂度、冗余、性能、架构和测试质量的证据快照。
- `InvestigationRequest`：Agent 主动调研的问题、模式、成本、停止条件和证据要求。
- `InvestigationRecord`：调研的人工选择引用、状态迁移、结果证据和 revision。

## Runtime 集成与开发者 CLI

`ea` 是 Runtime、调试、评测和发布接口，不是普通 Codex App/Hermes 用户的日常操作界面。仅在开发仓库、直接调试内核或编写平台集成时安装开发包：

```bash
python3 -m pip install -e .
```

命令分为两组：

| 分组 | 命令 | 用途 |
| --- | --- | --- |
| Runtime 控制面 | `route`、`start`、`next`、`complete`、`quality-submit`、`evidence-import`、`investigation-*`、`mcp-serve` | 供平台 adapter、受信执行器和内核调试调用 |
| 研发与发布 | `validate`、`artifact-validate`、`eval`、`build`、`verify-package`、`canary-audit`、`canary-prepare`、`canary-attestation-import`、`canary-assemble`、`canary-validate` | 供开发者、CI 和发布门禁调用 |

完整命令语义：

```text
ea route             RouteIntent -> RouteDecision
ea start             创建并持久化 RunState
ea next              计算下一节点和 GateDecision
ea complete          提交 StepResult 和模型 evidence claim
ea approval-import   导入绑定 run、revision 和 scope 的外部审批 grant
ea quality-submit    提交六维代码质量快照
ea evidence-import   导入由宿主执行器签发的证据
ea investigation-propose  创建主动调研提议
ea investigation-list     查看调研队列
ea investigation-approval-import  导入外部审批 broker 的签名选择
ea investigation-start    启动已批准调研
ea investigation-finish   以已登记证据结束调研
ea mcp-serve         以 MCP stdio 暴露含受治理 Provider 调用的受限 Runtime 工具
ea validate          校验 catalog、schema、引用和作者源
ea verify-sources    离线核验六个固定 revision checkout 的许可证和代表性证据摘要
ea artifact-validate 使用当前 Runtime schema 校验 Provider、Feedback、Quality、Investigation、usage 和运行状态 artifact
ea eval              执行真实核心评测
ea build             构建 Codex 或 Hermes 包
ea verify-package    校验包文件摘要
ea canary-audit      只读审计绑定逐臂 prompt 的本地三臂实验、纳入替换和 transcript 结构；不生成可信收益证据
ea canary-prepare    在管理员固定 broker 绑定下复制真实 artifact，并生成冻结 trust provenance 的未验签 draft
ea canary-attestation-import  校验外部 broker 回执并生成不可变 run evidence
ea canary-assemble   验签 observation 并确定性组装 canary result
ea canary-validate   通过外部 evidence broker 校验真实产品 canary 结果
ea feedback-summary  只读汇总目标项目中的效率候选、反馈事件和处置
ea feedback-disposition  导入人工或 CI 明确给出的不可变反馈处置
ea feedback-evolution-export  只读导出已接受反馈的去敏回归提案，不修改正式资产
```

自然语言到 `RouteIntent` 的理解由平台 Agent 完成；核心 Router 只消费结构化输入，`start` 必须在服务端重新计算决策，不能接受调用方构造的 `RouteDecision`。Codex MCP 与 Hermes 工具注册都调用同一个 `RuntimeTools`，不会形成并行路由器；模型工具集合不包含审批、自由文本决定或可信证据导入，后续调用必须使用 RunState 已绑定的 profile。Router 会在同一次响应中披露宿主固定 Host Trust 的执行能力；`ask`、`confirm` 或 `block` 一律返回 `recommended_execution=stop`。只有 `proceed` 的持久化 flow 在缺少外部 evidence/approval broker 时才返回 `skills_only`，Agent 继续执行已选公开 skill，但不重试必然无法完成的 `start`、`next`、`complete` 或 `quality_submit`。

Codex 插件 Hook 的 manifest 使用锚定正则 `^mcp__teamwork_engineering_assistant__engineering_assistant_.*$`，只匹配本插件工具。普通 Prompt、Stop、Bash、`apply_patch` 和其他 MCP 事件不会启动本插件 Hook，因此普通任务既无采集语义，也无本插件 Hook 进程开销。插件工具调用会建立短生命周期 `UsageObservationPlan`，只采集该次插件工具调用数、输出字节、重复输入、单次大输出和缺失 PostToolUse 等摘要信号；PostToolUse 会等待全部已跟踪调用完成后再尝试汇总匿名 `UsageEfficiencyFeedback`，成功产生信号候选后删除 ledger，无信号时保留有界散列签名供同轮后续插件调用比较。工具失败只保存受控失败分类和哈希化工具或资产引用，不保存原始输入、输出、命令或反馈摘录。12 次工具和 64 KB 输出等值仅作为趋势参考，超过参考值、重复调用或采集失败都不会拒绝工具、阻断任务或要求人工放行。工具事件哈希最多保留最近 256 条，超出后继续累计摘要并标记截断，不限制任务；超过 24 小时的孤儿 ledger 由后续插件调用机会式清理。由于 Codex 当前严格限定为插件工具 matcher，它不声称观察整轮 Bash、代码索引、用户纠正或回复末尾文本；Hermes 只观测插件 adapter 注册的 `teamwork-engineering-assistant` toolset，并在插件自身 `post_llm_call` 汇总轮次反馈。这些数据只用于持续优化分析，不作为安全门禁；观测或反馈存储失败时平台调用仍然继续。结构化产物优先通过只读 MCP 工具 `engineering_assistant_artifact_validate` 校验，CLI 仅作为开发环境回退。

实现流的强制 `quality` 节点只有在六个质量维度全部为 `pass`、没有 medium 以上 finding、没有未关闭修复项且每个判断引用宿主签发的兼容证据时才能完成。质量快照绑定 run revision、候选源码证据摘要和一小时新鲜度；候选内容改变后旧快照自动失效。模型提交的证据输入固定降级为 `claimed`，不能自行设置 `observed` 或 `verified`。

主动调研的最终模式来自 profile 预授权或外部审批 broker，而不是模型建议。`disabled` 直接拒绝；`auto_readonly` 仅在 profile 已授权的资料范围和成本内自动运行；`suggest_then_run` 使用一次 broker grant；`guided` 每次只批准一个资料范围，完成后若仍有资料源则重新进入 proposed。请求中的 `reported_blocking` 只表示发起方观察到该问题可能影响工作，用于排序和反馈分析；它不暂停、不拒绝也不阻断受治理任务。调研进入运行态后，CLI 和 MCP 都返回确定性的 `evidence_contract`：它把问题、停止条件和证据要求绑定为 subject digest，并列出调研 ID 标签、当前获批资料范围标签和最低信任级别。`investigation-finish` 只接受外部宿主已登记且满足该合同的 observed/verified 证据；无关质量证据、错误问题摘要或范围外资料不能结束调研。通用高风险审批同样只接受绑定 run、revision、flow、approval、actor 和有效期的 opaque grant。可信证据 receipt 与审批 token 必须由管理员固定的 HTTPS introspection endpoint 验证，发布包不含签发器或私钥；未配置宿主 broker 时保持等待，不回退到仓库 profile endpoint 或自由文本放行。

调研列表默认每页 50 条、最大 100 条，通过 `after_id`/`next_after_id` 继续读取；长生命周期 run 不会一次把全部调研记录和证据合同装入 MCP 响应。明确拒绝的 broker grant 只记录拒绝决定，不要求或消耗资料范围与成本额度。

宿主可以通过管理员固定位置的配置，为已存在的 profile 注入真实 evidence/approval introspection endpoint：macOS 使用 `/Library/Application Support/engineering-assistant/host-trust.json`，其他 POSIX 系统使用 `/etc/engineering-assistant/host-trust.json`。模型输入和进程环境不能选择或改写该路径；Windows 在具备等价 ACL 校验前安全禁用该覆盖能力。固定配置不存在时不会回退到仓库 profile 中的 endpoint，所有可信 evidence、审批和 canary 命令均 fail-closed。该文件只允许配置两个 broker，不能覆盖 policy、store、Hook 或预算，也不能把任何参考阈值变为拒绝、暂停或审批条件；文件必须由 root 持有、不是符号链接且不可被 group/world 写入，并以受限大小、无符号链接跟随和读前后元数据校验方式读取。配置中不保存私钥或业务 token，Runtime 仍只把每次收到的 opaque receipt/token 发往 HTTPS broker 验证。最小结构如下：

```json
{
  "schema_version": "1.0",
  "profiles": {
    "rrq-yq-team": {
      "evidence_broker": {
        "enabled": true,
        "id": "enterprise-evidence",
        "introspection_url": "https://broker.example/v1/evidence/introspect",
        "timeout_seconds": 5
      },
      "approval_broker": {
        "enabled": true,
        "id": "enterprise-approval",
        "audience": "teamwork-engineering-assistant",
        "introspection_url": "https://broker.example/v1/approval/introspect",
        "timeout_seconds": 5
      }
    }
  }
}
```

本地 artifact 防护面向静态路径逃逸、意外覆盖和协作进程并发，不把同一 OS 用户下的任意代码执行视为可由 JSON 存储层抵御的攻击。Runtime 会拒绝把目标项目设为 `engineering-assistant` 作者源或已安装插件目录，避免 Hook、反馈和运行状态污染插件源码；Hook 遇到该拒绝时 fail-open 且不创建 artifact。生产环境必须由平台沙箱限制 Agent 对插件、profile 和目标项目 `.run-artifacts` 的直接篡改，并由外部 broker/Provider 对真正的外部动作再次验签；未具备这些宿主条件时只能声明 Runtime 协议门禁，不能声明安全隔离。

阶段完成默认由子 Agent 分别进行需求/架构评审和代码质量/安全评审，主 Agent 自动修复并复验。只有生产、发布、提交/推送、破坏性变更、安全降级、范围扩张、不可逆产品决策或证据充分后仍无法消除的评审冲突才请求人工判断。

## 开发与验证

完整验证：

```bash
python3 -m unittest discover -s tests -v
ea validate --require-sources
ea eval
python3 scripts/publish_local.py --platform all --dry-run
```

临时构建必须输出到仓库外：

```bash
ea build --platform codex --output /tmp/engineering-assistant-codex
ea verify-package --package /tmp/engineering-assistant-codex

ea build --platform hermes --output /tmp/engineering-assistant-hermes
ea verify-package --package /tmp/engineering-assistant-hermes
```

质量门槛：

- Routing eval 至少 100 条真实中英文任务。
- Top-1 准确率不低于 90%。
- 无结果率不高于 5%。
- 未确认高风险写入为 0。
- Simulation 不得作为真实产品收益证据。
- Codex 和 Hermes 必须从同一作者源构建并通过摘要校验。

## 本机发布

无副作用预演：

```bash
python3 scripts/publish_local.py --platform codex --dry-run
python3 scripts/publish_local.py --platform hermes --dry-run
python3 scripts/publish_local.py --platform all --dry-run
```

实际发布需要显式 `--yes`，并读取当前本机发布策略 `config/local-publish-policy.json`：

```bash
python3 scripts/publish_local.py --platform codex --yes
python3 scripts/publish_local.py --platform hermes --yes
python3 scripts/publish_local.py --platform all --yes
```

脚本自动执行：仓库测试 → 作者源强校验 → 真实 eval → 11 个公开 skill 的官方 `quick_validate.py` → 平台最终 staging 构建 → 最终 Codex staging 包的官方 plugin validator → 官方校验摘要与 staging 摘要绑定 → 包摘要校验 → 旧插件备份 → 原子替换 → 平台注册 → 安装后验证。官方 validator 通过仓库外 `uv` 隔离环境运行并固定 `PyYAML==6.0.2`；缺少 validator、`uv`、输出超限或校验失败都会使 preflight 失败，不会 soft-pass。失败时自动恢复旧插件。

- Codex：安装到 `~/plugins/teamwork-engineering-assistant`，维护 personal marketplace 并刷新 Codex 缓存。
- Hermes：安装到 `~/.hermes/plugins/teamwork-engineering-assistant`，调用 `hermes plugins enable teamwork-engineering-assistant`。

平台 CLI 按“显式环境变量 → `PATH` → macOS App 内置路径”的顺序发现。Codex App 安装在标准目录时，无需额外配置；自定义位置可以显式指定：

```bash
CODEX_CLI="/自定义路径/codex" python3 scripts/publish_local.py --platform codex --yes
HERMES_CLI="/自定义路径/hermes" python3 scripts/publish_local.py --platform hermes --yes
```

详细说明见 [本机发布](docs/operations/local-publish.md)。

## 版本规则

产品使用四段式版本：

```text
MAJOR.MINOR.PATCH.BUILD[-PRERELEASE]
```

平台只支持 SemVer 时，由 adapter 将四段式版本映射为 SemVer，并在 `package-manifest.json` 中保留 canonical version。详见 [VERSIONING.md](VERSIONING.md)。

## 安全边界

- 高风险写入、生产动作、发布、删除历史和降低安全等级必须由用户明确授权。
- `--dry-run` 不写入插件目录、marketplace 或平台配置。
- `--yes` 只允许本机预发布；当前策略禁止稳定版发布和产品仓库修改。
- 发布脚本始终保留直接回滚目录，不静默删除旧插件。
- 没有真实运行证据时，不得声明产品 canary 或收益目标已完成。`ea canary-prepare` 只把 manifest 指向的真实 artifact 复制到仓库外证据包，计算摘要，并在管理员固定 broker 绑定下把 broker ID 与宿主配置摘要冻结进待签 claims；缺少 usage、墙钟、成本、质量、文档噪声或安全测量时状态保持 `incomplete`，它不会自行签名或生成 canary result。准备与组装两条入口都统一限制最多 512 个 artifact、总计 256 MiB，并对 JSON、attestation 和单 artifact 做有界、目录锚定读取。Canary 至少包含 5 组 workload 摘要一致的 baseline/candidate，外部 broker 必须分别签署不同的 `treatment_digest`，不能用 git ref 别名冒充不同处理；result 固定声明两侧 treatment、execution config 摘要、evidence broker ID 与管理员配置摘要，且配对环境摘要必须一致。Broker 必须核对 total/noncached input、output、墙钟、实际账单、独立质量评分、文档噪声与安全审计来源，不能只签署调用方填写的数值；效率阈值只用于运行结束后的 RC 晋级，不得在任务执行中截断或暂停，Token 指标也不能代替实际美元成本门禁。未配置宿主 broker 时所有 canary 命令均安全拒绝，绝不回退到仓库 profile endpoint。
- 失败门禁不能用文字说明替代，必须修复或保持阻断。
- 反馈 Hook 默认不阻断任务、不自动继续 Stop，也不自动修改正式 skill、flow、policy 或 eval。
- Hook 不保存原始 transcript、原始 session id 或原始 turn id；会保存单向哈希得到的可关联伪名引用和时间戳。检测到凭证和邮箱时只记录脱敏计数，并拒绝通过符号链接把反馈写出项目目录。

## 文档

- [当前架构](docs/architecture/overview.md)
- [本机发布](docs/operations/local-publish.md)
- [真实产品 Canary](docs/operations/canary.md)
- [版本规范](VERSIONING.md)
