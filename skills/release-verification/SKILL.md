---
name: release-verification
description: Use when 发布后需要验证核心功能、监控、日志、业务指标和回滚条件时；Do not use when do not执行未审批回滚。
---

# When To Use
- 发布后需要验证核心功能、监控、日志、业务指标和回滚条件时。
- 需要判断发布是否成功、继续观察或触发回滚审批时。

# Do Not Use When
- 不要执行未审批回滚。
- 不要忽略异常、告警或业务指标波动。
- 不要替代发布前准备审批。

# Inputs
- `release-plan.md`
- `release-checklist.md`
- `observability data`
- `risk_policy`

# Do This
- 读取 release-plan、release-checklist、observability data 和风险策略。
- 验证核心功能、错误率、延迟、日志异常、告警、业务指标和回滚条件。
- 记录每个生产检查的时间窗口、数据源、阈值、结果和证据。
- 输出 release-verification-report、production-checks 和 anomaly-list。

# Evidence / Done
- production-checks.json 包含每个检查的数据源、阈值和结果。
- anomaly-list.md 说明异常影响、owner 和处理建议。
- release-verification-report.md 明确继续观察、通过或回滚审批。

# Stop / Escalate
- 核心功能失败、阈值触发或关键数据缺失时 blocked。
- 回滚操作、生产验证豁免或延长观察窗口需 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
