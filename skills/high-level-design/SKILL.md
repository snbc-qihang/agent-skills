---
name: high-level-design
description: Use when 需求契约和仓库上下文已具备，需要确定架构边界、业务域、数据流、异常流和发布影响时；Do not use when do not深入代码实现细节。
---

# When To Use
- 需求契约和仓库上下文已具备，需要确定架构边界、业务域、数据流、异常流和发布影响时。
- 需要先形成概要设计事实源，再进入详细设计或专项设计时。

# Do Not Use When
- 不要深入代码实现细节。
- 不要跳过架构风险、跨系统一致性或发布影响。
- 不要在需求契约未准入时生成正式概要设计。

# Inputs
- `requirement-contract.json`
- `team_standards`
- `repo_context`
- `risk_policy`

# Do This
- 读取 requirement-contract、repo-context、architecture baseline 和风险策略。
- 定义系统边界、业务域、核心流程、外部依赖、数据流和异常流。
- 标记一致性、幂等、权限、性能、发布和回滚风险。
- 输出 HLD、ADR、module-boundary 和 architecture-risk-report。

# Evidence / Done
- high-level-design.md 覆盖边界、数据流、异常流和发布影响。
- architecture-decision-record.md 记录关键取舍、备选方案和理由。
- module-boundary.yaml 可供详细设计和实现合同消费。

# Stop / Escalate
- 需求契约未准入或 repo context 缺失时 waiting_for_input。
- 跨系统一致性、权限或生产发布风险未审批时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
