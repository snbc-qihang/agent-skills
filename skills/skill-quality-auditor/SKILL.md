---
name: skill-quality-auditor
description: Use when 需要审计人工或 agent 生成的 Codex skills，判断触发、边界、SOP、资源、脚本、eval 和 workflow 是否合格时；Do not use when do not执行业务研发阶段。
---

# When To Use
- 需要审计人工或 agent 生成的 Codex skills，判断触发、边界、SOP、资源、脚本、eval 和 workflow 是否合格时。
- 需要防止空泛 prompt、同构模板、路由冲突和缺少行为评测的 skill 入库时。

# Do Not Use When
- 不要执行业务研发阶段。
- 不要替代 eval 执行。
- 不要放行缺少 gate 的高风险 skill。

# Inputs
- `skills`
- `engineering-assistant/registry/skills.yaml`
- `skill-contract.schema.json`

# Do This
- 读取 skills、registry、contract schema、agents metadata、eval cases 和 workflow nodes。
- 检查 description 的正/负触发、SKILL.md 是否短 SOP、references/scripts/assets 是否按需披露。
- 计算相似度、公共标题数、路由冲突、行为 eval 覆盖和高风险 explicit-only 策略。
- 输出 skill-quality-report、fix suggestions 和 gate decision。

# Evidence / Done
- skill-quality-report.json 包含每个 skill 的触发、SOP、eval、schema 和 workflow 检查结果。
- skill-fix-suggestions.md 只生成候选，不直接修改正式 skill。
- skill-gate-decision.json 明确 pass/block/waiting_for_human_review。

# Stop / Escalate
- 高风险 skill 缺少 explicit-only、contract、schema 或 eval 时 blocked。
- 修改高风险质量门禁或豁免 skill gate 需 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
