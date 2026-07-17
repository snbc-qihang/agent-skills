---
name: engineering-assistant
description: 将工程任务路由到最小充分的 skill 或受治理 flow。适用于请求跨越上下文、设计、实现、评审、发布或长期任务协调的场景。
---

# 工程助手

将请求转换为结构化 `RouteIntent`，再交给运行时路由器。只加载选中的公开 skill、flow 节点和被引用的 policy。

## 操作流程

1. 在询问用户前，先调查可能改变路由的事实。
2. 单个原语能够完成任务时只选一个原语；只有存在依赖关系的多步骤任务才选择 flow。
3. 明确记录范围、风险信号、外部动作和置信度。
4. 遇到 `ask`、`confirm` 或 `block` 时立即停止，不得把它们解释为继续执行的许可。
5. 对持久化 flow，以运行时状态作为进度的唯一事实源。
6. 阶段或切片完成后按风险触发子 Agent 自动评审：先枚举固定 diff 的全部适用反例矩阵单元格和尚未闭合的可证伪风险假设。只有同时满足“固定 diff 涉及安全、事务、跨模块生产合同、发布或不可逆动作”和“未闭合假设集合非空”时，才把集合内彼此不重复的假设全部交给独立子 Agent 覆盖；可合并为一个限制证据范围和验收问题的有界任务，但不得只选择其中一个，也不得重复主 Agent 已完成的全量评审。集合为空时才使用已选 `code-review` 内联收口；平台不支持委派时逐项内联检查并把无法获得决定性证据的单元格标为 `not_evaluated`，不得据此降低标准门禁或原有人工门禁。用户或仓库明确要求多类独立评审时遵守该要求。
7. 只有自动评审发现必须由用户决定的产品取舍、风险授权、不可逆动作或无法消除的证据冲突时，才暂停并请求人工判断；将项目原有人工阶段门禁替换为自动评审时，必须已有用户授权或仓库策略依据，不得自行降低既有人工门禁。
8. 把用户明确给出的工具、查询、文件和范围限制原样传递给选中 skill；插件采集到的工具次数和输出规模只作为优化信号，不得据此停止任务、制造未知项或申请人工放行。

当前平台尚未选择具体插件 skill 且暴露 `engineering_assistant_route` 时，先调用一次该工具获得 flow、skill 和 policy，再加载选中 skill。平台已经直接选择具体的插件限定 skill 时，该选择即为本轮平台能力选择结果，内联原语不得为了确认 skill 再次调用 `engineering_assistant_route`；它不等同于 Runtime `RouteDecision`，任务确实需要持久化 flow、Runtime 门禁或超出所选原语范围时才进入 Runtime 路由。不得扫描插件目录猜测路由、工作流或 validator。阶段状态审计、自动评审通过条件、blocker 和门禁判断属于 `code-review`，不是通用 `repo-context`。只有用户明确指向历史上下文，或当前仓库事实无法解释状态时，才加载 memory/rollout。

`engineering_assistant_route` 返回的 `execution` 是宿主可信能力边界。`recommended_execution=stop` 时遵守 `ask`、`confirm` 或 `block` 并停止，不得加载或执行建议 skills。只有 `RouteDecision.decision=proceed` 且 `recommended_execution=skills_only` 时，才只执行路由给出的公开 skills，不调用任何需要 active run 的 Runtime 工具，包括 `start`、`next`、`complete`、`quality_submit`、`provider_invoke`、`investigation_*` 或证据导入，也不为未启动的 flow 构造或校验 `step-result`、`quality-snapshot`；把缺失 Host Trust/Broker 记录一次后继续完成当前工程任务，不重试同一确定性边界。只有 `persisted_flow_ready=true` 才启动持久化 flow；`complete` 已经返回下一节点时不再额外调用 `next`，确定性校验失败且输入与外部状态未变化时不得原样重试。该降级只省略当前宿主无法完成的持久化交互，不得省略已选 skill 要求的 TDD、测试、风险评审或安全门禁。

用户未明确限制时，一次 Runtime 路由、一次代码索引查询、八个证据文件和六个 shell 命令仅作为采集参考值，不是执行上限。路由结果已经给出的 flow、skill、policy 直接使用，不得再读取 catalog 验证。优先检查用户点名的阶段结果、自测、代码评审和运行证据；索引查询还应覆盖当前 diff 中的鉴权、秘密、持久化和外部动作高风险路径。超过参考值时继续以完成任务所需的最小充分证据推进，并把超出原因留作持续优化输入，不得自动阻断或要求人工批准。

只有工作超过一次会话时才读取 [references/wayfinding.md](references/wayfinding.md)。只有路由包含写入、发布、生产或外部动作时才读取 [references/authorization.md](references/authorization.md)。

只有在路由已经说明且未加载多余 skill 或参考资料时才可完成。
