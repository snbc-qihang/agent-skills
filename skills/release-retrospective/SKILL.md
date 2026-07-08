---
name: release-retrospective
description: Use when 发布完成后需要消费 feedback inbox、归纳发布问题、测试遗漏、设计遗漏和 skill 改进候选时；Do not use when do not将候选规范直接发布。
---

# When To Use
- 发布完成后需要消费 feedback inbox、归纳发布问题、测试遗漏、设计遗漏和 skill 改进候选时。
- 需要把复盘结论转为后续 action、规范候选或 eval 候选，但不直接发布规范时。

# Do Not Use When
- 不要将候选规范直接发布。
- 不要隐藏发布问题。
- 不要替代 assistant-feedback-capture 做全量反馈采集。

# Inputs
- `release-verification-report.md`
- `code-quality-report.json`
- `feedback-inbox.json`
- `incident reports`
- `release logs`

# Do This
- 读取 release verification、quality report、feedback inbox、incident reports 和 release logs。
- 按发布过程、测试遗漏、设计遗漏、代码质量、验证问题和用户纠正分类。
- 输出 lessons、follow-up actions、rule candidates、skill improvement candidates 和 reject reasons。
- 把需要演进的条目交给 skill-evolution-review，保持 candidate 状态。

# Evidence / Done
- release-lessons.yaml 每条经验有来源证据和适用范围。
- follow-up-actions.md 每项有 owner、优先级和完成条件。
- skill 改进候选不自动应用到正式 skill。

# Stop / Escalate
- feedback inbox 未消费或问题缺少证据时 blocked。
- 规范候选批准或高风险复盘结论发布需 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
