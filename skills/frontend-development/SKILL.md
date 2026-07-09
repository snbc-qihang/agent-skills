---
name: frontend-development
description: Use when 已通过 prototype review 且 frontend-design 已冻结，需要实现页面、组件、状态和联调时；Do not use when do not凭组件文档或接口文档绕过高保真原型。
---

# When To Use
- 已通过 prototype review 且 frontend-design 已冻结，需要实现页面、组件、状态和联调时。
- 需要把设计事实源映射到代码变更、浏览器证据和前端验证时。

# Do Not Use When
- 不要凭组件文档或接口文档绕过高保真原型。
- 不要发明新的视觉布局、文案、信息架构或组件体系。
- 不要只跑构建就声明产品级前端验收通过。

# Inputs
- `frontend-design.md`
- `component-contracts.yaml`
- `interface-contracts.yaml`
- `repo_context`

# Do This
- 读取 frontend-design、component-contracts、interface-contracts、repo_context 和 prototype gate verdict。
- 按最小垂直切片实现一个可验证用户流，保持目录结构、组件库、样式系统和状态管理一致。
- 为每个 UI 变更写入 design-to-ui mapping，标明来源原型、组件契约和接口字段。
- 运行项目既有前端 build/test/lint；能使用 Browser/Playwright 时采集桌面和移动截图、console、核心交互证据。
- 能力缺失时只声明 code-level validation，并阻断 frontend_product_acceptance。

# Evidence / Done
- design-to-ui-mapping.yaml 每行变更能追溯到原型或 frontend-design。
- frontend-changed-files-report.json 只包含允许范围内文件。
- 浏览器/截图/console/viewport/interaction 证据齐全时才可声明产品级通过。

# Stop / Escalate
- 缺少 prototype gate pass 或 frontend-design 时 blocked。
- 截图、console 或交互证据缺失时不得声称产品级验收完成。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
