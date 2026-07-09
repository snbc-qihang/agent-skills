---
name: frontend-design
description: Use when 高保真原型和三轮 review verdict 已通过，需要转为可实现的前端设计合同时；Do not use when do not替代 product-prototype-design 或 prototype-review-loop。
---

# When To Use
- 高保真原型和三轮 review verdict 已通过，需要转为可实现的前端设计合同时。
- 需要明确页面、组件、状态、路由、接口联调和验证策略时。

# Do Not Use When
- 不要替代 product-prototype-design 或 prototype-review-loop。
- 不要在缺少原型截图、interaction-state-map 或 review verdict 时继续。
- 不要直接修改后端接口或选择未确认技术栈。

# Inputs
- `requirement-contract.json`
- `high-level-design.md`
- `interface-contracts.yaml`
- `repo_context`

# Do This
- 先验证 product-prototype-contract、desktop/mobile screenshot、interaction-state-map、prototype-review-report 均可用。
- 从 repo_context 读取现有前端技术栈、组件库、目录、路由、状态管理和接口客户端模式。
- 把原型冻结输入转成页面结构、组件边界、状态机、接口联调契约和验证矩阵。
- 列出必须由 frontend-development 消费的设计事实源，禁止新增未审批的视觉或信息架构变更。
- 输出 frontend-design、component-contracts 和 frontend-risk-report；缺证据时 blocked。

# Evidence / Done
- frontend-design.md 引用 prototype gate verdict 和关键截图路径。
- component-contracts.yaml 覆盖 loading/empty/error/permission/validation/dirty/success 状态。
- frontend-risk-report.json 标记技术栈、组件库、接口和响应式风险。

# Stop / Escalate
- 无 prototype review pass verdict 时不得进入设计。
- 技术栈或组件库无法从 repo_context 推导时 waiting_for_input。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
