# RRQ/YQ 数据库规范包

仅在影响范围明确命中数据库时加载；未命中时 `team-delivery` 必须显式跳过对应节点。

规范定义唯一来自 `rrq-yq-team-rules` 目录中目标为 `rrq-yq-database` 的 3 条规则，本文件不复制规则正文。数据变更仍受现有风险审批、迁移、回滚和实际验证门禁约束。

命中关系型 OLTP 数据库设计时，必须同时加载 `skills/codebase-design/references/relational-oltp-detailed-design-template.md`，完整保留其章节顺序、层级和表头，并在交付前调用 `engineering_assistant_database_design_validate`。不适用章节保留并说明原因；校验失败视为数据库设计节点未完成。未命中数据库时维持条件跳过，不得为普通设计任务强制生成数据库文档。
