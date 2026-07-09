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
- validator-summary.json 汇总专项 validator 结果；defect-analysis 记录自审 blocker 根因和修复状态。

# Stop / Escalate
- 前置节点 contract 或原型门禁不满足时 blocked。
- 正式 skill/workflow/schema 修改没有人工审批时 blocked。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
