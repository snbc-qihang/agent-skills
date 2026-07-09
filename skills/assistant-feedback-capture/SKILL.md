---
name: assistant-feedback-capture
description: Use when workflow、review、测试、用户纠正、失败重试或第三方工具调用暴露有价值问题时；Do not use when do not直接修改正式 skill、workflow、schema 或发布版本。
---

# When To Use
- workflow、review、测试、用户纠正、失败重试或第三方工具调用暴露有价值问题时。
- 需要把上下文漂移、文档噪声、反复返工和真实验收失败写入 feedback inbox 时。

# Do Not Use When
- 不要直接修改正式 skill、workflow、schema 或发布版本。
- 不要采集无证据的主观偏好作为规范候选。
- 不要忽略用户反复纠正；用户纠正优先级高于 agent 自评。

# Inputs
- `StageRunResult`
- `assistant-run-feedback.json`
- `workflow-trace.json`
- `user correction summary`
- `tool logs`

# Do This
- 从 StageRunResult、workflow trace、user correction summary、tool logs 中抽取事件。
- 为每条事件写明 source task/run、triggered skill、symptom、user correction summary、evidence paths、severity、repeat_count 和 recommended action。
- 目标项目证据写入 artifacts/_control/feedback/；中心候选写入 feedback-inbox/ 或等价生成目录。
- repeat_count >= 3 的用户纠正标记 regression_case_candidate=true。
- 低价值或证据不足事件写 rejected_noise/needs_more_evidence 和 reject_reason。

# Evidence / Done
- feedback-event.json 每条事件包含非空 evidence_paths。
- feedback-inbox-entry.json 标记 consumed_by_evolution_review=false。
- 第三方工具失败同时进入 capability ledger 和 feedback inbox。

# Stop / Escalate
- 证据路径为空时不能生成 accepted candidate。
- 涉及敏感内容或正式规范变更时 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
