---
name: requirement-intake
description: Use when 需求还没有形成可进入设计的契约，需要判断目标、范围、验收标准、依赖和风险是否齐全时；Do not use when do not替产品负责人做业务取舍或批准高风险需求。
---

# When To Use
- 需求还没有形成可进入设计的契约，需要判断目标、范围、验收标准、依赖和风险是否齐全时。
- 用户给出业务想法、PRD 草稿或口头需求，需要先补齐进入设计前的缺口时。

# Do Not Use When
- 不要替产品负责人做业务取舍或批准高风险需求。
- 不要在验收标准、范围或 owner 缺失时进入概要设计。
- 不要生成代码或实现计划。

# Inputs
- `organization_context`
- `current_process`
- `requirement_materials`
- `risk_policy`

# Do This
- 读取需求材料、组织上下文、当前流程和风险策略。
- 提取业务目标、用户场景、范围、非目标、验收标准、依赖系统、接口人和排期约束。
- 把缺失信息分成 blocking 与 non-blocking，blocking 必须进入 required_information_requests。
- 生成 requirement-contract 和 risk assessment；高风险依赖必须标记 owner 和审批状态。

# Evidence / Done
- requirement-contract.json 包含目标、范围、验收标准、非目标和依赖。
- missing-information-list.md 明确每个缺口的 owner、优先级和是否阻断。
- requirement-risk-assessment.json 标明是否可以进入设计。

# Stop / Escalate
- 业务目标、验收标准或核心依赖缺失时 waiting_for_input。
- 跨系统重大依赖或数据/权限/发布风险未确认时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
