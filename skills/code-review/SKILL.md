---
name: code-review
description: Use when 对代码进行人工评审辅助，按问题、证据、影响、级别、建议和阻断状态输出；Do not use when do not 替代 code-quality-governor。
---

# When To Use
- 对代码进行人工评审辅助，按问题、证据、影响、级别、建议和阻断状态输出。
- 代码走查、人工评审辅助、语义缺陷定位和 blocker 清单整理时使用。

# Do Not Use When
- 不替代 code-quality-governor。
- 不输出无证据建议。
- 不忽略测试缺口。

# Inputs
- `code-quality-report.json`
- `static-analysis-report.json`
- `changed-files-report.json`
- `implementation-summary.md`
- `repo_context`

# Do This
- 读取 code-quality-report.json, static-analysis-report.json, changed-files-report.json、项目 profile、团队规则目录和 artifact index。
- 执行 code-review preflight：确认语言、必填信息、风险、审批状态和 `code-quality-report.json` 证据。
- 执行前必须读取 artifacts/_control/quality-contract.json、任务规则包和 rule-consumption-report.json。
- 正确性。
- 边界条件。
- 异常处理。
- Bug 风险。

# Evidence / Done
- `code-review-report.md` 已生成并可追溯。
- `code-review-report.html` 已生成并可追溯。
- `review-comments.json` 已生成并可追溯。
- `blocker-list.md` 已生成并可追溯。
- blocker 清单为空 有证据、假设或 required action。
- 所有问题有证据 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `code-quality-report.json` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `blocker 清单为空` 失败时 blocked，不得降级为普通建议。
- blocker 关闭 需要人工审批或 waiting_for_human_review。
- 高风险人工豁免 需要人工审批或 waiting_for_human_review。
- 核心链路评审通过 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
