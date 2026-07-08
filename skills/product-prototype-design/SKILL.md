---
name: product-prototype-design
description: Use when Web/App 产品任务缺少可作为实现事实源的高保真原型时；Do not use when do not把低保真线框图、接口说明或组件清单当成产品原型通过。
---

# When To Use
- Web/App 产品任务缺少可作为实现事实源的高保真原型时。
- 需要在进入 frontend-design 或实现前冻结页面清单、信息架构、核心流、状态和视口证据时。
- 需要调用 build-web-apps、Browser、Figma 或等价设计能力并记录能力账本时。

# Do Not Use When
- 不要把低保真线框图、接口说明或组件清单当成产品原型通过。
- 不要直接生成业务代码；本 skill 只产出原型合同和视觉证据。
- 不要跳过桌面/移动截图、关键交互状态或 third-party-capability-ledger。

# Inputs
- `requirement-contract.json`
- `repo-context-report.md`
- `brand_or_design_system_context`
- `target_viewports`

# Do This
- 判定任务是否为 web/app；非 web/app 只输出 skip_reason 和 gate decision。
- 读取需求契约、仓库上下文、品牌/组件库约束和目标视口，列出必须覆盖的页面、状态和用户流。
- 优先委派成熟前端/设计能力生成高保真原型；记录能力、输入、输出、失败和回退策略。
- 生成桌面与移动截图证据，补齐 loading、empty、error、permission、validation、dirty、success 等状态。
- 输出 product-prototype-contract、interaction-state-map 和 prototype gate decision；证据缺失时 blocked。

# Evidence / Done
- product-prototype-contract.json 指向原型源、页面清单、状态矩阵和冻结输入。
- desktop-prototype-screenshot.png 与 mobile-prototype-screenshot.png 均存在且可追溯。
- third-party-capability-ledger.json 记录 build-web-apps、Browser、Figma 或等价能力调用。

# Stop / Escalate
- 缺少高保真原型、桌面/移动截图或交互状态图时停止在 blocked。
- 第三方工具失败时记录 ledger 和 feedback event，不得口头放行。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md：本阶段检查项。
- scripts/validate_output.py：校验 StageRunResult 输出契约。
