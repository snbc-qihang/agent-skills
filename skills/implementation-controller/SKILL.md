---
name: implementation-controller
description: Use when 已审批设计需要编译成实现合同、质量合同和控制面产物，才能让代码实现安全推进时；Do not use when do not审批设计进入研发。
---

# When To Use
- 已审批设计需要编译成实现合同、质量合同和控制面产物，才能让代码实现安全推进时。
- 需要限定 allowed/forbidden modules、质量命令、追踪矩阵和修复闭环时。

# Do Not Use When
- 不要审批设计进入研发。
- 不要直接替代 code-development 写业务代码。
- 不要把 HTML 人工审阅件作为 agent 事实源。

# Inputs
- `approved design artifact`
- `target project root`
- `project profile`
- `changed-files-report.json`

# Do This
- 只接受已审批 Markdown/JSON/YAML 设计产物，HTML 仅作为人工阅览入口。
- 生成 artifacts/_control 下的 current-task、design-contract、implementation-contract、quality-contract 和 task-context。
- 定义 allowed_modules、forbidden_modules、required_tests、quality commands、done conditions 和 repair policy。
- 刷新 traceability-matrix、workflow-trace、control-health 和 repair-attempts。

# Evidence / Done
- implementation-contract.json 可机器读取且限制实现范围。
- quality-contract.json required_commands 非空且无占位。
- traceability-matrix.json 映射需求、设计、代码和测试。

# Stop / Escalate
- 设计未审批、质量命令为空或合同字段缺失时 blocked。
- 修改已审批设计范围、高风险实现豁免或修复轮次耗尽时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
