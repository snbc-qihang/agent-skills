---
name: repo-context-miner
description: Use when 需求需要基于现有仓库做设计或实现，必须先提取模块、接口、数据、中间件和影响范围时；Do not use when do not直接修改代码。
---

# When To Use
- 需求需要基于现有仓库做设计或实现，必须先提取模块、接口、数据、中间件和影响范围时。
- 需要找出现有模式、禁止改动边界和可复用能力，防止凭空设计时。

# Do Not Use When
- 不要直接修改代码。
- 不要替代业务设计或架构决策。
- 不要在缺少源码证据时推断实现细节。

# Inputs
- `repository_path`
- `requirement-contract.json`
- `team_standards`
- `risk_policy`

# Do This
- 优先使用 codegraph 或 rg 定位 controller/service/domain/mapper/repository、DTO、异常码和权限模式。
- 梳理数据表、Mapper/SQL、事务边界、Redis key、MQ topic、定时任务和外部依赖。
- 识别可复用 service、工具类、领域能力和禁止改动模块。
- 输出 module-map、impact-scope、reusable-capabilities 和 repo-risk-list。

# Evidence / Done
- repo-context-report.md 引用具体文件、符号、接口或配置路径。
- impact-scope.yaml 区分 allowed、forbidden、requires_review。
- repo-risk-list.json 记录证据不足和待确认点。

# Stop / Escalate
- 仓库不可访问或关键源码缺失时 waiting_for_input。
- 需要读取敏感配置或跨仓库分析时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
