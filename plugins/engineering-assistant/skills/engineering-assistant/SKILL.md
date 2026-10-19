---
name: engineering-assistant
description: 将工程任务路由到最小充分的 skill 或受治理 flow。适用于请求跨越上下文、设计、实现、评审、发布或长期任务协调的场景。
---

本 skill 仅使用当前 `engineering-assistant` 的能力与 Runtime。平台已选本 skill 时直接执行，不重复路由或跨插件推进同一运行。

# 工程助手

将请求转换为结构化 `RouteIntent`，再交给运行时路由器。只加载选中的公开 skill、flow 节点和被引用的 policy。

同项目同时安装个人版与团队版时，优先遵守用户显式指定的插件和项目已配置的产品规则；同一受治理目标只选择一个产品拥有和推进运行。不要向两个 Runtime 重复 start/complete 或交叉提交证据。目标产品确实不明且会改变正式门禁时才澄清；普通单原语任务按已选择的插件内联完成。

## 操作流程

1. 在询问用户前，先调查可能改变路由的事实。
2. 单个原语能够完成任务时只选一个原语；只有存在依赖关系的多步骤任务才选择 flow。
3. 明确记录范围、风险信号、外部动作、`confirmed_actions` 和置信度。用户明确只读分析、不写文件且不执行外部动作时设置 `read_only=true`，保留审查对象的风险信号；其他任务省略该字段或为 false，不得借只读标记绕过写入授权。
4. 遇到 `ask`、未确认的 `confirm` 或 `block` 时暂停该路由所依赖的动作；可独立完成的已授权调查继续。复用范围及风险未变化的既有授权，不能自行填写未获确认的 `confirmed_actions`。
5. `proceed + flow` 默认启动或恢复持久化运行；直接 primitive skill 保持内联，不创建 run；满足条件的局部实现也可内联完成。
6. 风险触发子 Agent 自动评审：只有同时满足高风险 diff 与尚未闭合的可证伪风险假设时，才读取 [阶段评审门禁](references/review-gates.md) 并按其要求覆盖全部假设；其余情况内联评审。
7. 只有自动评审发现必须由用户决定的产品取舍、风险授权、不可逆动作或无法消除的证据冲突时，才暂停并请求人工判断；将项目原有人工阶段门禁替换为自动评审时，必须已有用户授权或仓库策略依据，不得自行降低既有人工门禁。
8. 把用户明确给出的工具、查询、文件和范围限制原样传递给选中 skill；插件采集到的工具次数和输出规模只作为优化信号，不得据此停止任务、制造未知项或申请人工放行。

当前平台尚未选择具体插件 skill 且暴露 `engineering_assistant_route` 时，先调用一次该工具获得 flow、skill 和 policy，再加载选中 skill。平台已经直接选择具体的插件限定 skill 时，该选择即为本轮平台能力选择结果，内联原语不得为了确认 skill 再次调用 `engineering_assistant_route`；它不等同于 Runtime `RouteDecision`，任务确实需要持久化 flow、Runtime 门禁或超出所选原语范围时才进入 Runtime 路由。不得扫描插件目录猜测路由、工作流或 validator。阶段状态审计、自动评审通过条件、blocker 和门禁判断属于 `code-review`，不是通用 `repo-context`。只有用户明确指向历史上下文，或当前仓库事实无法解释状态时，才加载 memory/rollout。

`engineering_assistant_route` 返回 `recommended_execution=stop` 时遵守 `ask`、未确认的 `confirm` 或 `block`。返回 `inline` 时执行所选 primitive skill；`implement` 且 skills 为空时直接完成范围内实现和适用验证，不重新路由以补齐 skill。返回 `persisted_flow` 时固定执行 `route → start/resume → evidence-register → complete → 下一节点`：`start` 已返回首节点和 guidance，`complete` 已原子记录阶段结果并返回下一节点，只有恢复既有 run 才调用 `next`。每个节点直接遵守 Runtime 返回的 capability、skill、目标、完成标准、条件、证据合同和 policy 规则，不扫描 catalog 猜测执行方法。确定性校验失败且输入与外部状态未变化时不得原样重试。

`.run-artifacts/engineering-assistant/<run-id>/run-state.json` 是进度的唯一状态源；manifest、steps、evidence、approvals、quality、investigations 和 providers 是不可变或按合同更新的追溯记录，只在实际使用时创建。只有明确续接受治理运行时才用 `runs_list` 和 `run_status` 查找未终止 run；普通新任务不扫描历史运行。项目内文件通过 `evidence_register` 由 Runtime 校验路径并计算摘要；命令和远程状态只能记录为 `agent_reported`。本地 approval record 只证明对话中存在明确决定，不提供身份验签或抗篡改保证；生产、发布和破坏性动作仍服从平台权限确认。

工具次数和输出规模只作为非阻断优化信号，不是执行上限。路由结果已经给出的 flow、skill、policy 直接使用，不得再读取 catalog 验证。优先检查用户点名的阶段结果、自测、代码评审和运行证据；索引查询还应覆盖当前 diff 中的鉴权、秘密、持久化和外部动作高风险路径。继续以完成任务所需的最小充分证据推进，不得因工具次数或输出规模自动阻断或要求人工批准。

只有工作超过一次会话时才读取 [references/wayfinding.md](references/wayfinding.md)。只有路由包含写入、发布、生产或外部动作时才读取 [references/authorization.md](references/authorization.md)。

完成标准是交付用户选定的结果、适用的验证以及明确的证据缺口。已获授权的实现包含运行检查与必要修复，不在首版产出后停止；用户要求停留在审核或既有人工门禁处时遵守该边界。

实现任务先选择最小充分验证。仅边界明确、无风险信号、无外部动作且不要求正式流程的局部改动，才设置 `implementation_mode=inline`；其他实现保留默认 `flow`。已有人工门禁必须保留，不能通过 inline 规避。团队正式交付 profile 不因该字段降级。TDD 只在适合失败反馈或明确要求时选择，测试方法不由改动行数决定。Runtime 的 `skill=null` 表示直接执行节点合同，不是工具缺失；不得猜测替代 skill 或重复路由。
