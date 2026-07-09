---
name: high-level-design
description: Use when 从需求契约生成概要设计，明确架构边界、数据流、异常流和发布影响；Do not use when do not 深入代码实现细节。
---

# When To Use
- 从需求契约生成概要设计，明确架构边界、数据流、异常流和发布影响。
- 概要设计、系统上下文、模块边界、核心流程和架构风险分析时使用。

# Do Not Use When
- 不深入代码实现细节。
- 不跳过架构风险。
- 不替代设计评审审批。

# Inputs
- `requirement-contract.json`
- `team_standards`
- `repo_context`
- `risk_policy`

# Do This
- 读取 requirement-contract.json, team_standards, repo_context、项目 profile、团队规则目录和 artifact index。
- 执行 high-level-design preflight：确认语言、必填信息、风险、审批状态和 `requirement-contract.json` 证据。
- A1 设计文档必须体现系统边界、业务域、事件协作和最终一致性；不强制平台采用微服务、事件驱动或 DDD 作为技术路线。
- A2 系统间交互优先通过开放能力接口或事件；不得直接调用未开放接口。
- A3 目标业务系统与目标客户端系统按不同系统边界描述，跨系统协作明确接口、事件、消息体、幂等和一致性。
- A4 应用层只暴露 api/tapi/mapi/console，业务层和共享层只暴露 service 能力。
- A5 关键跨系统场景进入关键场景设计；简单服务内部 CRUD 不进入关键场景文档。

# Evidence / Done
- `high-level-design.md` 已生成并可追溯。
- `architecture-decision-record.md` 已生成并可追溯。
- `module-boundary.yaml` 已生成并可追溯。
- `risk-list.json` 已生成并可追溯。
- 需求契约已准入 有证据、假设或 required action。
- 模块边界明确 有证据、假设或 required action。

# Stop / Escalate
- 缺少 `requirement-contract.json` 或其来源证据时 waiting_for_input，不得生成正式产物。
- `需求契约已准入` 失败时 blocked，不得降级为普通建议。
- 高风险架构决策 需要人工审批或 waiting_for_human_review。
- 跨域边界调整 需要人工审批或 waiting_for_human_review。
- 核心链路兼容性变化 需要人工审批或 waiting_for_human_review。

# References / Scripts
- contract.yaml、references/stage-guidance.md、scripts/validate_output.py、rrq-yq-team.yaml、team-rule-catalog.yaml、team-standard-sources.yaml：契约、团队 profile/rule/source 和输出校验；语言策略/执行门禁要求未指定输出语言时先询问，preflight_input_state == ready 后才允许 formal_generation，preflight 未通过前不得生成正式阶段产物，不得登记正式阶段产物为已完成；技术/框架选型要求前端技术栈、测试框架、mybatis-plus、JDBC 例外来自 repo_context/profile 或主动询问与评审。
- 模板执行协议：先读取 assets/high-level-design-template.md，按章节顺序生成，等待输入时停在 waiting_for_input，不得删除团队模板必需章节。团队概要设计模板规则必须保留系统逻辑视图、研发视图、核心功能、中间件设计和数据视图。
