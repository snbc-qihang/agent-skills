---
name: code-development
description: Use when 设计已审批，需要按实现合同做最小必要代码变更时；Do not use when do not做无设计依据的大范围重构。
---

# When To Use
- 设计已审批，需要按实现合同做最小必要代码变更时。
- 需要将需求、设计、代码、测试和追踪矩阵闭环时。

# Do Not Use When
- 不要做无设计依据的大范围重构。
- 不要修改 forbidden_modules 或无关文件。
- 不要用文档校准替代真实代码、测试或阻断结论。

# Inputs
- `detailed-design.md`
- `implementation-plan.md`
- `interface-contracts.yaml`
- `repo_context`

# Do This
- 读取 artifacts/_control/task-context.agent.md、implementation-contract.json、quality-contract.json 和任务规则包。
- 确认 allowed_modules、forbidden_modules、expected interfaces/services/mappers、required_tests 和 done_conditions。
- 按 thin vertical slice 实现最小功能，先改风险最高或主路径最短的一片。
- 刷新 changed-files-report、design-to-code-mapping 和 traceability-matrix。
- 运行 quality-contract 中要求的命令；失败时记录证据和 repair attempt，不得口头放行。

# Evidence / Done
- code changes 只落在允许范围，越界需人工审批。
- traceability-matrix.json 映射需求、设计、代码和测试。
- test/build/lint 命令有真实输出或明确 blocked reason。

# Stop / Escalate
- implementation-contract 缺失或质量命令为空时 blocked。
- 高风险文件、DB/Redis/MQ/权限/发布脚本变更未审批时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
