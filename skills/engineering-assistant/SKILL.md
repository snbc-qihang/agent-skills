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

只有工作超过一次会话时才读取 [references/wayfinding.md](references/wayfinding.md)。只有路由包含写入、发布、生产或外部动作时才读取 [references/authorization.md](references/authorization.md)。

只有在路由已经说明且未加载多余 skill 或参考资料时才可完成。
