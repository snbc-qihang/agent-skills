# Skill Evolution Review 阶段指引

检查项：
- 按 skill、问题类型、严重度、重复次数和证据质量聚类 feedback events
- 用户纠正优先级高于 agent 自评；重复纠正达到阈值必须形成 regression case candidate
- 输出 accepted_candidate、rejected_noise、needs_more_evidence、merged_with_existing 或 waiting_for_human_review verdict
- skill patch proposal 只作为候选，不得自动修改正式 SKILL.md、contract、workflow 或 schema
- 低价值或偶发问题必须写明 reject reason，防止污染规范和上下文
