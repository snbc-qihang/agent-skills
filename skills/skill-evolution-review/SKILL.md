---
name: skill-evolution-review
description: Use when 周期性消费 feedback inbox，需要聚类为 skill patch、eval regression 或治理规则候选时；Do not use when do not未经人工审批自动修改正式 SKILL.md、contract、workflow 或 schema。
---

# When To Use
- 周期性消费 feedback inbox，需要聚类为 skill patch、eval regression 或治理规则候选时。
- 需要判断反馈应 accepted、rejected、merged、needs_more_evidence 或 waiting_for_human_review 时。

# Do Not Use When
- 不要未经人工审批自动修改正式 SKILL.md、contract、workflow 或 schema。
- 不要把低价值偶发反馈写入规范。
- 不要把 agent 自评分置于用户反复纠正之上。

# Inputs
- `feedback-inbox.json`
- `feedback-event.json`
- `engineering-lessons.md`
- `skill registry`

# Do This
- 读取 feedback-inbox、feedback events、engineering lessons 和 skill registry。
- 按 skill、问题类型、严重度、repeat_count、证据质量和用户纠正优先级聚类。
- 生成 skill-evolution-candidates、skill-patch-proposals、regression-case-candidates 和 feedback-rejection-log。
- repeat_count >= 3 的同类用户纠正必须生成 regression eval candidate。
- 所有正式修改保持 candidate 状态，等待人工审批后才可落入生成器或发布版本。

# Evidence / Done
- 每个候选引用 source event id 和 evidence path。
- 每个 rejected_noise 有 reject_reason。
- skill patch proposal human_approval_required=true 且 auto_apply=false。

# Stop / Escalate
- 候选缺少来源事件或审批状态时 blocked。
- 发现 auto_apply=true 时 blocked。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
