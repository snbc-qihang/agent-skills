---
name: engineering-knowledge-miner
description: Use when 需要从反馈事件、评审、CI、PR、发布或事故中抽取可复用工程知识和规范候选时；Do not use when do not无证据创建规范。
---

# When To Use
- 需要从反馈事件、评审、CI、PR、发布或事故中抽取可复用工程知识和规范候选时。
- 需要生成 rule candidates、checklist patches、skill suggestions 或 regression eval candidates 时。

# Do Not Use When
- 不要无证据创建规范。
- 不要未经审批修改正式规范。
- 不要把偶发低风险问题升级为强制规则。

# Inputs
- `feedback-inbox.json`
- `design reports`
- `code quality reports`
- `review reports`
- `CI logs`
- `PR comments`
- `release reports`
- `incident reports`

# Do This
- 读取 feedback inbox、设计/质量/评审/发布报告、CI logs、PR comments 和 incident reports。
- 抽取 finding，按问题模式、重复性、严重度、适用范围和证据质量聚类。
- 生成 engineering lessons、rule candidates、checklist suggestions、skill suggestions 和 regression candidates。
- 对低价值或证据不足条目写 reject reason，防止污染规范。

# Evidence / Done
- engineering-lessons.md 每条经验有来源证据。
- rule-candidates.yaml 默认 status=candidate 且 owner 明确。
- regression-case-candidates.yaml 可被 eval runner 消费。

# Stop / Escalate
- feedback event 未消费或缺少 accept/reject verdict 时 blocked。
- 修改正式团队规范或高风险 skill gate 需 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
