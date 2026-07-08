---
name: code-review
description: Use when 质量报告和变更文件已具备，需要做语义代码评审、定位缺陷和整理 blocker 清单时；Do not use when do not替代 code-quality-governor。
---

# When To Use
- 质量报告和变更文件已具备，需要做语义代码评审、定位缺陷和整理 blocker 清单时。
- 需要把静态分析、设计映射和人工评审 finding 汇总为可执行修复建议时。

# Do Not Use When
- 不要替代 code-quality-governor。
- 不要输出无证据建议。
- 不要忽略测试缺口。

# Inputs
- `code-quality-report.json`
- `changed-files-report.json`
- `implementation-summary.md`
- `repo_context`

# Do This
- 读取 code-quality-report、changed-files、implementation-summary、repo context 和 rule-consumption-report。
- 按正确性、边界、异常、安全、性能、复杂度、重复、可测试性和团队规范逐项评审。
- 每个 finding 必须包含证据位置、影响、级别、建议、owner 和是否阻断。
- 输出 code-review-report、HTML、review-comments 和 blocker-list。

# Evidence / Done
- review-comments.json 中每条评论有文件/符号/规则或测试证据。
- blocker-list.md 为空才允许评审通过。
- HTML 报告引用稳定 JSON id，避免人工阅览件反向污染事实源。

# Stop / Escalate
- 缺少 changed-files 或 code-quality-report 时 waiting_for_input。
- blocker 未关闭或高风险人工豁免未审批时 blocked 或 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
