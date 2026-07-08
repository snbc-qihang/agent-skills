---
name: workflow-orchestrator
description: Use when 需要选择研发 workflow、串联 stage skills、维护状态机、审批暂停/恢复和产物路由时；Do not use when do not直接生成某个阶段文档。
---

# When To Use
- 需要选择研发 workflow、串联 stage skills、维护状态机、审批暂停/恢复和产物路由时。
- 需要阻断 web/app 未过 prototype gate 或未审批 feedback candidate 的流程时。

# Do Not Use When
- 不要直接生成某个阶段文档。
- 不要绕过子 skill contract、quality gate 或人工审批。
- 不要把中间过程文档升级为正式规范。

# Inputs
- `workflow.yaml`
- `stage node registry`
- `StageRunRequest`
- `approval_context`

# Do This
- 根据任务类型选择 workflow，并验证每个节点 contract、输入、输出和依赖顺序。
- web/app 路径必须在 frontend-design/implementation 前插入 product-prototype-design 和 prototype-review-loop。
- 执行节点时只传递 StageRunRequest/StageRunResult 和 artifact index 中的必要证据。
- 遇到 missing input、quality gate failed、tool failure 或 approval required 时暂停并写 trace。
- 把 feedback capture 贯穿 review、测试、失败重试和用户纠正节点，但不自动应用演进候选。

# Evidence / Done
- workflow-trace.json 记录节点状态、输入输出、审批和失败原因。
- artifact-index.json 只登记正式证据和必要运行产物。
- approval-requests.json 明确 pending/approved/rejected。

# Stop / Escalate
- 前置节点 contract 或原型门禁不满足时 blocked。
- 正式 skill/workflow/schema 修改没有人工审批时 blocked。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
