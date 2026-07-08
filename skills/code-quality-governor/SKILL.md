---
name: code-quality-governor
description: Use when 代码变更需要通过 Q0-Q4 质量门禁、静态分析、设计一致性和发布前风险检查时；Do not use when do not以 LLM 判断替代 build/test/lint。
---

# When To Use
- 代码变更需要通过 Q0-Q4 质量门禁、静态分析、设计一致性和发布前风险检查时。
- 需要把 build/test/lint/Sonar/Qodana/Checkstyle 等确定性证据转成 gate decision 时。

# Do Not Use When
- 不要以 LLM 判断替代 build/test/lint。
- 不要在测试失败时输出 pass。
- 不要降级 blocker。

# Inputs
- `changed-files-report.json`
- `design-to-code-mapping.yaml`
- `self-test-report.md`
- `ci artifacts`

# Do This
- 读取 changed-files、design-to-code mapping、self-test、CI artifacts 和 quality-contract。
- 执行或消费 Q0 设计一致性、Q1 确定性检查、Q1.5 静态分析、Q2 语义评审、Q3 风险专项和 Q4 回归门禁。
- 统一 bug、vulnerability、code smell、security hotspot、complexity、duplication 和 coverage 证据。
- 输出 code-quality-report、HTML、JSON、gate-decision 和 improvement candidates。

# Evidence / Done
- gate-decision.json 明确 pass/block/warn 和阻断原因。
- static-analysis-report.json 包含工具、规则、位置和 severity。
- code-quality-report.html 仅供人工阅览，不作为 agent 事实源。

# Stop / Escalate
- 确定性命令失败或静态分析 blocker 存在时 blocked。
- 权限、支付、订单、库存、发布脚本等高风险变更未审批时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
