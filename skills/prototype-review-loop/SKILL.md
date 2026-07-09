---
name: prototype-review-loop
description: Use when 已有高保真原型，需要至少三轮 agent review 后决定是否进入工程设计或实现时；Do not use when do not替代人工最终审批。
---

# When To Use
- 已有高保真原型，需要至少三轮 agent review 后决定是否进入工程设计或实现时。
- 需要关闭视觉、交互、企业级可用性、可实现性和证据链 blocker 时。

# Do Not Use When
- 不要替代人工最终审批。
- 不要在少于三轮 review 或 blocker 未关闭时放行。
- 不要修代码；只评审和冻结原型输入。

# Inputs
- `product-prototype-contract.json`
- `desktop-prototype-screenshot.png`
- `mobile-prototype-screenshot.png`
- `interaction-state-map.json`

# Do This
- 读取 product-prototype-contract、桌面/移动截图和 interaction-state-map。
- 第 1 轮评审信息架构、用户流、业务完整性和角色权限。
- 第 2 轮评审视觉层级、布局密度、响应式、状态覆盖和企业级可用性。
- 第 3 轮评审可实现性、组件契约、接口依赖、验收证据和冻结输入。
- 汇总 findings，标记 owner、状态、证据和下一轮验证结论；输出 gate decision。

# Evidence / Done
- prototype-review-report.json 至少包含 3 个 review_rounds。
- prototype-gate-decision.json 明确 pass/block/waiting_for_human_review。
- 所有 blocker 都有 closed、accepted_risk 或 human_approval_required 状态。

# Stop / Escalate
- review_rounds < 3 时 blocked。
- 原型证据缺失或与冻结输入冲突时 blocked。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
