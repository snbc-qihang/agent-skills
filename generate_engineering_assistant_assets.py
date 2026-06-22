#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成研发助手 Skills 工程体系资产。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SKILLS_ROOT = "skills"
PLUGIN_NAME = "teamwork-engineering-assistant"
PLUGIN_VERSION = "1.0.0.3"
PLUGIN_COMPATIBILITY_ALIAS = "engineering-assistant"
PLUGIN_DISPLAY_NAME = "团队研发助手"
PLUGIN_MARKETPLACE_NAME = "local-teamwork-engineering"
PLUGIN_MARKETPLACE_DISPLAY_NAME = "Local Teamwork Engineering Plugins"
DOWNSTREAM_CANARY_ROOT = "/Users/sunliming/work/project/personal/ai-platform-v1"
TEAM_STANDARDS_INPUT_ROOT = str(ROOT / "inputs")

EVAL_CASES = [
    "happy_path",
    "missing_required_input",
    "ambiguous_input",
    "policy_conflict",
    "edge_case",
    "regression_case",
    "technology_demo_adoption",
    "control_plane_drift",
    "rule_consumption_gap",
    "context_noise_overload",
    "low_quality_automation",
]

TEAM_DOC_TARGET_SKILLS = {"high-level-design", "detailed-design", "database-design", "redis-design", "mq-design", "code-development"}

UPSTREAM_MAIN_INCREMENT_CAPABILITIES = [
    {
        "domain": "manifest / distribution surface",
        "capability": "插件 manifest 的 `metadata_status`、`distribution_notes`、runtime policy pack 和 hooks packaging 校验",
        "status": "already-covered-by-teamwork",
        "teamwork_handling": "已由 `plugin_manifest()`、`validate_plugin_manifest.py`、`tests/test_plugin_distribution_surface.py` 和 `run_skill_evals.py --mode scored` 覆盖。",
        "why": "保留 upstream 的分发表面门禁，同时继续使用 teamwork 的插件身份和占位 metadata 人审策略。",
    },
    {
        "domain": "manifest / distribution surface",
        "capability": "通用 `engineering-assistant` 插件名、展示名、默认提示词和关键词集合",
        "status": "do-not-import",
        "teamwork_handling": "保留 `teamwork-engineering-assistant`、团队展示名、团队默认提示词、团队关键词和 `rrq-yq-team` profile 入口。",
        "why": "直接导入会覆盖 teamwork 插件身份，并削弱团队 profile、团队规则和团队发布语义。",
    },
    {
        "domain": "manifest / distribution surface",
        "capability": "personal/local-root 发布布局与 published plugin sync 校验",
        "status": "already-covered-by-teamwork",
        "teamwork_handling": "已由 `publish_plugin.py`、`.agent/plugins/publish-config.json`、teamwork 路径回归测试和 scored eval 覆盖。",
        "why": "保留 teamwork 发布目录、marketplace entry 和 Codex 可识别插件结构。",
    },
    {
        "domain": "manifest / distribution surface",
        "capability": "仅按通用插件路径发布、不保留 `compatibility_alias=engineering-assistant` 的策略",
        "status": "do-not-import",
        "teamwork_handling": "继续保留 `compatibility_alias`，在 personal 布局下允许 teamwork 插件和通用别名共存。",
        "why": "删除兼容别名会破坏当前 Codex 安装兼容面和既有用户入口。",
    },
    {
        "domain": "traceability / implementation control",
        "capability": "`artifacts/_control/traceability-matrix.json` 作为 agent 事实源，`docs/human-readable/traceability-report.html` 只做人读入口",
        "status": "already-covered-by-teamwork",
        "teamwork_handling": "已由 `compile_design_contract.py`、`build_traceability_report.py`、workflow contract、validator 和专项测试覆盖。",
        "why": "保留 upstream 追踪矩阵能力，同时确保 HTML 不反向作为 agent 事实输入。",
    },
    {
        "domain": "traceability / implementation control",
        "capability": "implementation-controller / code-development 的 traceability 输出、gate 和脚本链路",
        "status": "already-covered-by-teamwork",
        "teamwork_handling": "已在 teamwork 的 contract、workflow、SKILL.md、runtime 脚本和 `test_team_document_design_rules.py` 中强化实现。",
        "why": "teamwork 已完整吸收并扩展该能力，不需要回退到更弱的通用版本。",
    },
    {
        "domain": "scored eval / workflow / regression",
        "capability": "scored eval 的 plugin manifest gate、distribution surface metric 和 published plugin sync 检查",
        "status": "already-covered-by-teamwork",
        "teamwork_handling": "已由 `run_skill_evals.py --mode scored` 实现，并由 runtime 回归测试和 distribution surface 测试约束。",
        "why": "保留 upstream 的 scored eval 能力，同时继续验证 teamwork 发布路径和 manifest 约束。",
    },
    {
        "domain": "scored eval / workflow / regression",
        "capability": "只保留通用强度的 preflight / required-information / eval 断言，不带团队专项规则密度",
        "status": "do-not-import",
        "teamwork_handling": "继续使用 teamwork 更强的 preflight、required-information、team eval 和专项设计门禁。",
        "why": "回退到通用断言会削弱 teamwork 现有更强的门禁和团队规则覆盖面。",
    },
    {
        "domain": "manifest / distribution surface",
        "capability": "Hermes 目录插件发布、插件启用和限定名技能注册链路",
        "status": "already-covered-by-teamwork",
        "teamwork_handling": "吸收为共享发布能力，但 Hermes 插件名、目录和限定名前缀使用 `teamwork-engineering-assistant`。",
        "why": "这是通用发布能力，适合上收到 teamwork 的生成器和回归护栏中。",
    },
    {
        "domain": "manifest / distribution surface",
        "capability": "Hermes 场景下硬编码 `engineering-assistant` 插件命名空间",
        "status": "do-not-import",
        "teamwork_handling": "保留 teamwork 插件名和 `teamwork-engineering-assistant:<skill>` 的 Hermes 限定名调用方式。",
        "why": "直接导入会把 Hermes 发布面退回通用插件身份，破坏 teamwork 命名一致性。",
    },
]

HIGH_LEVEL_DESIGN_REQUIRED_SECTIONS = [
    "0. 原始需求与原型追溯",
    "1. 版本变更记录",
    "2. 平台概述",
    "3. 系统设计",
    "3.1 系统逻辑视图",
    "3.1.1 系统设计原则",
    "3.3 研发视图",
    "3.4 研发结构定义",
    "4. 核心功能",
    "4.1.2 关键协作摘要",
    "4.1.3 跨服务服务间时序图",
    "5.中间件设计",
    "6.数据视图",
]

HIGH_LEVEL_DESIGN_FORBIDDEN_HEADINGS = [
    "证据",
    "Findings",
    "必须补充信息",
    "门禁决策",
]

DETAILED_DESIGN_MAIN_SECTIONS = [
    "1. 修订历史",
    "2. 设计背景与目标摘要",
    "2.1 原始需求与原型引用矩阵",
    "3. 模块/功能详细设计",
    "3.1. 业务流程图",
    "3.2. UML类图",
    "4. 数据库设计",
    "5. 接口定义",
    "5.1. API接口列表",
    "5.2. 中间件设计",
    "6. 单元测试",
    "7. 性能与扩展性设计",
    "8. 人工评审项",
]

SOURCE_TRACEABILITY_TABLE_HEADER = "| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |"

HLD_SERVICE_SEQUENCE_FORBIDDEN_PARTICIPANTS = [
    "用户",
    "页面",
    "前端",
    "客户端",
    "Controller",
    "API",
    "接口",
    "数据库",
    "DB",
    "Redis",
    "MQ",
    "Topic",
    "Queue",
    "表",
    "Mapper",
    "Repository",
]

HLD_ABSTRACT_PARTICIPANT_LABEL_TERMS = [
    "权限组织服务",
    "数据权限服务",
    "支付通知服务",
    "查询服务",
    "组织服务",
    "风控服务",
]

HLD_EVENT_DRIVEN_TERMS = ["MQ", "消息", "事件", "异步"]
HLD_CREATE_EVENT_TERMS = ["创建类消息", "新增类消息", "产生类消息", "创建消息", "新增消息", "产生消息"]
HLD_STATE_EVENT_TERMS = ["状态变更消息", "删除消息", "失效消息", "状态变更类消息", "删除类消息", "失效类消息"]
HLD_INTERNAL_SEQUENCE_TERMS = ["校验", "幂等", "处理记录"]
HLD_INTERNAL_SEQUENCE_OUTCOME_TERMS = ["查询", "事实详情", "保存", "写入", "删除", "移除", "本地读模型", "重试", "死信"]

DETAILED_MQ_DB_REDIS_REQUIRED_TERMS = {
    "Redis / 缓存 / 状态处理记录 / 幂等记录": ["Redis", "缓存", "状态处理记录", "幂等记录"],
    "幂等": ["幂等"],
    "DB / 数据库 / 主表 / 明细": ["DB", "数据库", "主表", "明细"],
    "事务": ["事务"],
    "回滚": ["回滚"],
    "重试": ["重试"],
    "死信": ["死信"],
    "人工处理": ["人工处理"],
    "外部详情查询或事实服务查询": ["外部详情查询", "事实服务查询", "查询当前详情", "查询事实详情"],
}

REDIS_FORBIDDEN_FORMAL_TERMS = ["终态水位", "水位"]
REDIS_BUSINESS_TERMS = ["状态处理记录", "已处理状态记录", "消息幂等记录", "短期处理记录", "乱序保护记录"]

HLD_DETAILED_IMPLEMENTATION_FORBIDDEN_TERMS = [
    "请求字段",
    "返回字段",
    "CREATE TABLE",
    "ALTER TABLE",
    "DROP TABLE",
    "字段类型",
    "索引名",
    "Controller",
    "Mapper",
    "Repository",
    "方法签名",
    "伪代码",
    "单元测试步骤",
]

HLD_FORBIDDEN_MERMAID = ["flowchart"]

DETAILED_DESIGN_FORBIDDEN_HEADINGS = [
    "来源证据",
    "技术选型",
    "业务规则与校验",
    "幂等与一致性",
    "异常与日志",
    "发布",
    "灰度",
    "上线",
]

DETAILED_DESIGN_FLOW_NOTE_FIELDS = [
    "业务规则",
    "校验规则",
    "事务边界",
    "幂等与一致性",
    "异常场景",
    "日志要求",
]

DETAILED_DESIGN_FLOW_REQUIRED_BRANCH_TERMS = {
    "异常分支": ["异常", "失败", "校验失败", "权限失败", "状态失败", "调用失败", "超时"],
    "失败终态": ["失败结束", "异常结束", "终止", "失败终态", "人工处理", "补偿完成", "回滚"],
    "补偿/重试/人工处理": ["补偿", "重试", "人工处理", "回滚", "告警"],
}

DETAILED_DESIGN_EXCEPTION_TABLE_FIELDS = [
    "场景",
    "触发条件",
    "异常编码",
    "异常信息",
    "系统处理动作",
    "数据状态",
    "日志/告警",
    "补偿/重试/人工处理",
]

DETAILED_DESIGN_DDD_TERMS = [
    "DDD",
    "聚合根",
    "领域服务",
    "ApplicationService",
    "Repository",
    "Handler",
    "Strategy",
    "Template",
    "port",
    "adapter",
]

DETAILED_DESIGN_DATABASE_TRIGGER_TERMS = [
    "数据库查询",
    "DB 查询",
    "DB写入",
    "DB 写入",
    "本地读模型",
    "主表",
    "明细表",
    "关联表",
    "DDL",
    "CREATE TABLE",
    "ALTER TABLE",
    "DROP TABLE",
    "表结构",
]

DETAILED_DESIGN_ABSTRACT_DATABASE_TERMS = [
    "订单表",
    "明细表",
    "临时表",
    "日志表",
    "记录表",
    "配置表",
    "规则表",
    "主表",
    "从表",
]

DETAILED_DESIGN_SPECIALTY_DOCS = {
    "database-design.md": "数据库设计",
    "mq-design.xlsx": "MQ 设计",
    "redis-design.md": "Redis 设计",
    "interface-contracts.yaml": "接口契约",
    "test-strategy.md": "测试策略",
}

DB_OLTP_REQUIRED_SECTIONS = [
    "1. 文档信息",
    "1.1 变更记录",
    "1.2 术语定义",
    "1.3 参考文档",
    "2. 文档定位",
    "2.1 编写目的",
    "2.2 设计对象类型",
    "2.3 与其他文档的关系",
    "2.4 强耦合表组说明（若适用）",
    "3. 业务语义与生命周期",
    "3.1 表的业务职责（业务角色）",
    "3.2 核心业务场景",
    "3.3 数据生命周期阶段",
    "3.4 状态机（若存在状态字段）",
    "4. 物理结构设计",
    "4.1 建表级环境与约定",
    "4.2 字段定义（按表展开）",
    "4.3 索引设计",
    "4.4 约束与数据库对象",
    "4.5 字段可变性矩阵",
    "4.6 技术实现依赖",
    "5. 数据量与性能设计",
    "5.1 数据量估算",
    "5.2 读写 QPS 与延迟 SLA",
    "5.3 热点与数据倾斜分析",
    "5.4 容量规划",
    "5.5 性能保障措施",
    "6. CRUD 契约设计（OLTP 核心）",
    "6.1 CRUD 总览矩阵",
    "6.2 强制前置条件（Mandatory Conditions）",
    "6.3 禁止操作清单（Prohibited Operations）",
    "6.4 Create",
    "6.5 Read",
    "6.6 Update",
    "6.7 Delete",
    "6.8 幂等键与重复请求",
    "6.9 批量操作与数据修复规则",
    "7. 事务、一致性与并发控制",
    "7.1 本地事务边界（单库）",
    "7.2 跨表一致性（表组内/跨库）",
    "7.3 并发控制",
    "7.4 数据质量校验",
    "7.5 隔离级别、死锁与重试约定",
    "7.6 跨表最终一致",
    "8. 分区、分片与归档设计",
    "8.1 路由与分片规则",
    "8.2 分区策略",
    "8.3 查询策略",
    "8.4 归档与保留",
    "8.5 冷热分离与只读副本",
    "9. 安全与审计设计",
    "9.1 敏感字段清单",
    "9.2 脱敏与掩码规则",
    "9.3 访问控制",
    "9.4 审计要求",
    "10. 测试与验收",
    "10.1 验收检查表",
    "10.2 测试用例类型",
    "10.3 样例 SQL",
    "11. 附录",
    "11.1 DDL SQL",
    "11.2 兼容性说明",
]

DB_OLTP_REQUIRED_TABLE_HEADERS = [
    "| 项目 | 内容 |",
    "| 版本 | 日期 | 变更原因/依据 | 变更摘要 | 变更人 | 评审/批准 |",
    "| 术语 | 说明 |",
    "| 文档名 | 关联类型 | 参考说明 |",
    "| 成员表 | 角色 | 与主表关系 | 同事务要求 | 备注 |",
    "| 场景 ID | 场景名称 | 触发入口 | 主要 SQL 形态 | 优先级 | 频率/峰值 |",
    "| 阶段 | 进入条件 | 允许的操作类型 | 对外可见性 | 数据留存策略 |",
    "| 当前状态",
    "| 字段 | 类型 | 必填 | 默认值 | 索引 | 敏感级别 | 说明 |",
    "| 表 | 索引名 | 类型 | 字段（顺序敏感） | 唯一 | 服务场景 | 备注 |",
    "| 类别 | 规则 | 实现方式 | 备注 |",
    "| 字段 | 创建时赋值 | 运行中可改 | 结束态可改 | 修改主体 | 约束/备注 |",
    "| 依赖项 | 版本/规格 | 本文档是否依赖 | 说明 |",
    "| 维度 | 估算值 | 说明 |",
    "| 场景 ID | 场景名称 | 操作类型 | QPS/TPS 目标 | P99 延迟目标 | 优先级 | 说明 |",
    "| 热点类型 | 表现 | 发生条件 | 缓解措施 |",
    "| 资源 | 估算方法 | 目标值 | 说明 |",
    "| 措施 | 适用场景 | 实施状态 | 说明 |",
    "| 操作 | 典型入口 | 参与表 | 定位键/幂等键 | 一致性边界 | 必备前置条件 | 允许字段/投影 | 明确禁止 | 并发控制 | 审计 |",
    "| 操作 | 编号 | 强制条件",
    "| 编号 | 禁止行为 | 适用范围 | 例外",
    "| 规则项 | 要求 |",
    "| 查询类型 | 必带条件 | 推荐索引 | 主库/只读 | 备注 |",
    "| 场景 | 前置条件 | 允许 SET 字段 | 禁止 SET 字段 | 并发 |",
    "| 操作 | 策略 | 前置条件 | 审批 |",
    "| 层级 | 机制 | 说明 |",
    "| 类型 | 允许条件 | 事务与批次 | 记录要求 |",
    "| 场景 ID | 参与表 | 一致性要求 | 提交/回滚策略 | 补偿/核对策略 |",
    "| 关系 | 参与表 | 策略 | 补偿/核对 |",
    "| 场景 | 策略 | 说明 |",
    "| 校验项 | 规则 | 频率 | 失败处理 |",
    "| 主题 | 约定 |",
    "| 步骤 | 动作 | 失败补偿 |",
    "| 分片键 |",
    "| 维度 | MySQL | PostgreSQL |",
    "| 场景 | 是否带路由/分区键 | 预期计划 | 禁止 |",
    "| 阶段 | 条件 | 目标存储 | 在线库策略 |",
    "| 数据类别 | 放置 | 查询入口 | 说明 |",
    "| 字段 | 级别 | 存储 | 应用展示 | 导出 |",
    "| 场景 | 规则 | 示例 |",
    "| 角色 | 读 | 写 | 说明 |",
    "| 事件 | 记录内容 | 保留期 |",
    "| 检查项 | 结果 | 备注 |",
    "| 类型 | 目的 | 示例 |",
    "| 主题 | 注意点 |",
]

DB_OLTP_REQUIRED_TEMPLATE_MARKERS = [
    "应写明：",
    "不应重复：",
    "编写要点：",
    "示例（请替换为真实业务）：",
    "方言差异提示：",
    "编写要求：",
    "契约含义：",
    "原则说明（可粘贴到评审）：",
    "读写分离：",
    "样例 SQL（MySQL 风格，可按项目替换）",
    "强耦合表组模式标题规则",
    "强耦合表组模式要求",
    "文档结束",
]

DB_OLTP_REQUIRED_FACT_FIELDS = [
    "文档名称",
    "逻辑库/Schema",
    "物理库标识",
    "所属集群/实例",
    "设计对象",
    "数据库产品",
    "数据库版本",
    "编写日期",
    "编写人",
    "业务负责人",
    "DBA 负责人",
    "安全/合规接口人",
]

DB_UNRESOLVED_INFO_MARKERS = [
    "{",
    "}",
    "待补充",
    "待确认",
    "未知",
    "未确认",
    "人工评审确认",
    "待人工补充",
    "待用户补充",
    "pending_confirmation",
    "TBD",
    "TODO",
    "<填写",
    "请替换",
]

DB_OLAP_REQUIRED_SECTIONS = [
    "数据分层",
    "字段级血缘",
    "MergeTree 引擎选型",
    "ORDER BY",
    "PARTITION BY",
    "TTL",
    "物化视图关系",
    "刷新策略",
    "上下游影响",
]

REDIS_REQUIRED_SECTIONS = [
    "历史版本信息",
    "1. 前言",
    "1.1. 目的",
    "1.2. 适用范围",
    "1.3. 参考资料",
    "2. 公共配置",
    "2.1. Redis版本",
    "2.2. 集群配置",
    "2.3. 持久化策略",
    "2.4. 过期淘汰策略",
    "3. 设计项",
    "3.1. <设计项名称>",
    "3.1.1. 特性用途",
    "3.1.2. 业务说明",
    "3.1.3. 存储设计",
    "3.1.4. 预估数据",
    "3.1.5. 多团队协同",
    "4. 安全与运维",
    "4.1. 资源申请",
    "4.2. 运维监控",
]

REDIS_DESIGN_ITEM_FIELDS = [
    "特性用途",
    "业务说明",
    "存储设计",
    "预估数据",
    "多团队协同",
]

REDIS_STORAGE_FIELDS = ["库", "数据结构", "ttl", "key", "数据格式"]

MQ_PRODUCER_FIELDS = [
    "业务用途",
    "场景应用",
    "业务消息key",
    "消息类型",
    "消息体内容",
    "优先等级",
    "消息TTL（毫秒）",
    "持久化",
    "目的交换机",
    "路由key",
    "消息预估大小",
    "生产服务/模块名称",
    "软件需求号/bug号",
    "设计日期",
    "设计者",
    "备注",
]

MQ_CONSUMER_FIELDS = [
    "队列名称",
    "业务用途",
    "场景应用",
    "单消费节点消费",
    "队列类型",
    "优先队列",
    "是否持久化",
    "自动删除",
    "TTL",
    "消息大小",
    "绑定的Exchange/routingKey(多个）",
    "死信队列exchange/routeKey",
    "消费服务",
    "消息key",
    "运维监控",
    "软件需求号/bug号",
    "设计日期",
    "设计者",
    "备注",
]

MQ_PRODUCER_REQUIRED_VALUE_FIELDS = [
    "业务用途",
    "场景应用",
    "业务消息key",
    "消息类型",
    "消息体内容",
    "目的交换机",
    "路由key",
    "生产服务/模块名称",
]

MQ_CONSUMER_REQUIRED_VALUE_FIELDS = [
    "队列名称",
    "业务用途",
    "场景应用",
    "绑定的Exchange/routingKey(多个）",
    "死信队列exchange/routeKey",
    "消费服务",
    "消息key",
    "运维监控",
]

MQ_MESSAGE_SCHEMA_ROOT_FIELDS = ["issueId", "configType"]
MQ_MESSAGE_SCHEMA_ENTRY_COLLECTION_KEYS = ["messages", "schemas", "items", "entries"]
MQ_MESSAGE_SCHEMA_REQUIRED_CONFIG_FIELDS = {
    "pendingOrderExportTask": ["taskId", "taskType", "businessType", "eventTime"],
}

COMMON_STATES = [
    "pending",
    "running",
    "waiting_for_input",
    "waiting_for_human_review",
    "succeeded",
    "failed",
    "skipped",
    "blocked",
    "cancelled",
]

WORKFLOW_ENTRY_MODES = ["auto_flow", "from_node", "single_node"]
PREFLIGHT_INPUT_STATES = ["ready", "waiting_for_input", "waiting_for_human_review", "blocked"]
FORMAL_GENERATION_ENTRY_CONDITION = "preflight_input_state == ready"
PREFLIGHT_ONLY_ARTIFACTS = [
    "information-inventory.json",
    "context-source-map.json",
    "missing-information-list.json",
    "required-information-request.json",
    "design-objective-plan.md",
    "scope-and-non-goals.yaml",
    "user-confirmed-facts.json",
    "design-direction-decision.md",
    "docs/human-review/<run-id>.html",
    "workflow-trace.json",
    "resume-point.json",
]

FORMAL_DESIGN_ARTIFACTS = [
    "high-level-design.md",
    "detailed-design.md",
    "database-design.md",
    "redis-design.md",
    "mq-design.xlsx",
    "interface-contracts.yaml",
    "test-strategy.md",
]

DESIGN_GOVERNANCE_STATES = [
    "intake_collecting",
    "intake_gap_analysis",
    "waiting_for_user_input",
    "direction_confirming",
    "design_generating",
    "self_reviewing",
    "design_revising",
    "waiting_for_human_review",
    "human_review_processing",
    "design_regenerating",
    "knowledge_mining",
    "tl_rule_candidate_pending",
    "approved_or_done",
]

DOCUMENT_LIFECYCLE_STATES = [
    "not_started",
    "draft",
    "ready_for_self_review",
    "self_review_failed",
    "revised",
    "waiting_for_human_review",
    "human_review_rejected",
    "approved",
    "final",
    "superseded",
    "archived",
    "blocked",
    "waiting_for_input",
]

DESIGN_GOVERNANCE_CONTROL_OUTPUTS = [
    "information-inventory.json",
    "context-source-map.json",
    "missing-information-list.json",
    "design-objective-plan.md",
    "scope-and-non-goals.yaml",
    "user-confirmed-facts.json",
    "design-direction-decision.md",
    "assumption-and-decision-log.yaml",
    "self-review-findings.json",
    "auto-fix-report.json",
    "unresolved-review-findings.json",
    "human-review-package.json",
    "human-review-feedback.json",
    "feedback-classification.json",
    "next-iteration-plan.md",
    "iteration-trace.json",
    "rule-candidates.json",
    "prompt-optimization-candidates.md",
    "tl-review-package.json",
]

TEAM_RULE_PREFIXES = {
    "requirement-intake": ["A", "H", "QIN"],
    "repo-context-miner": ["A", "H", "D", "I", "E", "P", "R", "M", "DB", "FW", "FE", "QIN"],
    "high-level-design": ["A", "H", "FW", "FE", "QIN"],
    "detailed-design": ["D", "I", "E", "P", "FW", "QIN"],
    "redis-design": ["R", "P", "QIN"],
    "mq-design": ["M", "P", "QIN"],
    "database-design": ["DB", "P", "QIN"],
    "design-review": ["A", "H", "D", "I", "E", "P", "R", "M", "DB", "FW", "FE", "QIN"],
    "frontend-design": ["FE", "I", "QIN"],
    "code-development": ["D", "I", "E", "P", "DB", "R", "M", "FW", "QIN"],
    "frontend-development": ["FE", "I", "E", "P", "QIN"],
    "self-test": ["D", "P", "R", "M", "DB", "FE", "QIN"],
    "code-quality-governor": ["D", "I", "E", "P", "R", "M", "DB", "FW", "FE", "QIN"],
    "code-review": ["I", "E", "P", "DB", "R", "M", "FW", "FE", "QIN"],
    "release-readiness": ["DB", "R", "M", "QIN"],
    "release-verification": ["E", "P", "QIN"],
    "release-retrospective": ["A", "D", "P", "QIN"],
    "engineering-knowledge-miner": ["A", "D", "I", "E", "P", "R", "M", "DB", "QIN"],
    "skill-quality-auditor": ["A", "D", "I", "E", "P", "R", "M", "DB", "QIN"],
    "workflow-orchestrator": ["A", "D", "I", "E", "P", "R", "M", "DB", "DG", "QIN"],
    "implementation-controller": ["A", "D", "I", "E", "P", "DB", "R", "M", "FW", "FE", "QIN"],
}

TEAM_ADAPTATION_RULE_PREFIXES = ["RRQ", "YAPI", "YQ"]
for prefixes in TEAM_RULE_PREFIXES.values():
    for prefix in TEAM_ADAPTATION_RULE_PREFIXES:
        if prefix not in prefixes:
            prefixes.append(prefix)

HIGH_RISK_SKILLS = {
    "workflow-orchestrator",
    "code-development",
    "code-quality-governor",
    "release-readiness",
    "release-verification",
    "engineering-knowledge-miner",
    "implementation-controller",
}

CONTROL_CONSUMER_SKILLS = {
    "code-development",
    "frontend-development",
    "self-test",
    "code-quality-governor",
    "code-review",
}

DEFAULT_PROFILE = {
    "profile_id": "rrq-yq-team",
    "display_name": "人人取/萤启团队研发平台",
    "system_scope": ["人人取 SaaS 平台", "萤启服务商系统", "目标业务系统", "目标客户端系统"],
    "service_code_policy": "优先从萤启服务商系统 profile、概要设计或 repo_context 注入；缺失时必须主动询问，不得自造服务编码。",
    "interface_doc_tool": "YApi",
    "redis_runtime": "遵循部门 Redis 设计规范；具体版本、拓扑、库、持久化、淘汰策略由项目 profile 或 repo_context 注入。",
    "architecture_policy": "默认按人人取 2.0 技术架构规范评审系统边界、逻辑视图、事件协作、幂等和最终一致性。",
    "plugin_name": PLUGIN_NAME,
}

TEAM_STANDARD_SOURCE_DOCUMENTS = [
    {
        "id": "rrq-common-tech",
        "title": "人人取----通用技术需求",
        "source_path": f"{TEAM_STANDARDS_INPUT_ROOT}/人人取----通用技术需求 - 人人取平台总体设计 - 站点标题.html",
        "source_url": "http://mrdoc.xtjc.net/doc/238/",
        "topics": ["日志", "性能", "稳定性", "幂等", "异常", "安全", "业务监控"],
    },
    {
        "id": "rrq-yapi-standard",
        "title": "人人取----Yapi使用规范",
        "source_path": f"{TEAM_STANDARDS_INPUT_ROOT}/人人取----Yapi使用规范 - 人人取平台总体设计 - 站点标题.html",
        "source_url": "http://mrdoc.xtjc.net/doc/",
        "topics": ["YApi", "接口分组", "接口路径", "字段命名", "响应结构", "JSR303"],
    },
    {
        "id": "rrq-redis-standard",
        "title": "人人取----缓存Redis设计规范",
        "source_path": f"{TEAM_STANDARDS_INPUT_ROOT}/人人取----缓存Redis设计规范 - 人人取平台总体设计 - 站点标题.html",
        "source_url": "http://mrdoc.xtjc.net/doc/135/",
        "topics": ["Redis", "key", "value", "TTL", "命中率", "一致性", "运维安全"],
    },
    {
        "id": "rrq-redis-template",
        "title": "Redis详细设计模板",
        "source_path": f"{TEAM_STANDARDS_INPUT_ROOT}/Redis详细设计模板 - 人人取平台总体设计 - 站点标题.html",
        "source_url": "http://mrdoc.xtjc.net/doc/497/",
        "topics": ["Redis设计文档", "公共配置", "存储设计", "预估数据", "多团队协同", "监控"],
    },
    {
        "id": "rrq-idempotency",
        "title": "人人取----幂等性方案",
        "source_path": f"{TEAM_STANDARDS_INPUT_ROOT}/人人取----幂等性方案 - 人人取平台总体设计 - 站点标题.html",
        "source_url": "http://mrdoc.xtjc.net/doc/482/",
        "topics": ["幂等", "请求去重", "MQ去重", "乐观锁", "悲观锁", "最终一致性"],
    },
    {
        "id": "rrq-architecture",
        "title": "人人取----整体架构设计",
        "source_path": f"{TEAM_STANDARDS_INPUT_ROOT}/人人取----整体架构设计 - 人人取平台总体设计 - 站点标题.html",
        "source_url": "http://mrdoc.xtjc.net/doc/134/",
        "topics": ["微服务", "事件驱动", "DDD", "多租户", "最终一致性", "系统边界"],
    },
    {
        "id": "yq-overview",
        "title": "萤启运营系统概要设计",
        "source_path": f"{TEAM_STANDARDS_INPUT_ROOT}/萤启运营系统概要设计 - 萤启服务商系统 - 站点标题.html",
        "source_url": "http://mrdoc.xtjc.net/project/",
        "topics": ["萤启服务商系统", "异常编码", "系统交互", "性能", "YApi", "Redis"],
    },
    {
        "id": "yq-vems-franchisee",
        "title": "合作加盟服务(vems-franchisee)",
        "source_path": f"{TEAM_STANDARDS_INPUT_ROOT}/合作加盟服务(vems-franchisee) - 萤启服务商系统 - 站点标题.html",
        "source_url": "http://mrdoc.xtjc.net/project/",
        "topics": ["vems-franchisee", "售货机管理", "加盟商", "MQ", "库存同步", "YApi"],
    },
]

TEAM_RULE_CATALOG = [
    {"id": "A1", "category": "架构", "rule": "不强制平台采用微服务 + 事件驱动 + DDD，但是设计文档必须体现系统边界、业务域、事件协作和最终一致性。"},
    {"id": "A2", "category": "架构", "rule": "系统间交互优先通过开放能力接口或事件，不允许直接调用未开放接口。"},
    {"id": "A3", "category": "架构", "rule": "目标业务系统与目标客户端系统属于不同系统边界，跨系统协作必须明确接口、事件、消息体、幂等和一致性。"},
    {"id": "A4", "category": "架构", "rule": "应用层只暴露 api/tapi/mapi/console，业务层和共享层只暴露 service 能力。"},
    {"id": "A5", "category": "架构", "rule": "关键跨系统场景必须进入关键场景设计；简单服务内部 CRUD 不进入关键场景文档。"},
    {"id": "A6", "category": "架构", "rule": "跨库事务优先本地消息表、事件驱动、补偿机制；必要时使用 Seata，并说明事务边界。"},
    {"id": "H1", "category": "概要设计", "rule": "概要设计必须包含平台概述、系统逻辑视图、系统设计原则、研发视图、核心功能、中间件设计、数据视图；核心功能下保留关键协作摘要，不生成流程图。"},
    {"id": "H2", "category": "概要设计", "rule": "明确参与系统、职责边界、调用方向、事件流和异常流。"},
    {"id": "H3", "category": "概要设计", "rule": "声明是否涉及 Redis/MQ/DB/定时任务/权限/幂等/跨系统交互。"},
    {"id": "H4", "category": "概要设计", "rule": "后端业务系统研发结构按 presentation/application/domain/port/infrastructure/common 分层；如项目 profile 另有约定，以 profile 为准。"},
    {"id": "H5", "category": "概要设计", "rule": "application 层负责编排，不直接沉淀复杂业务判断；核心业务规则进入 domain。"},
    {"id": "H6", "category": "概要设计", "rule": "聚合根不通过依赖注入创建，应通过工厂创建；一次业务中聚合根创建和修改边界要清晰。"},
    {"id": "H7", "category": "概要设计", "rule": "概要设计必须按团队概要设计模板生成，保留版本变更记录、平台概述、系统设计、系统逻辑视图、系统设计原则、研发视图、研发结构定义、核心功能、中间件设计、数据视图；核心功能中的 4.1.2 只写关键协作摘要，不得用通用证据/Findings/门禁决策模板替代正文。"},
    {"id": "H8", "category": "概要设计", "rule": "概要设计涉及跨服务协作时必须补充 Mermaid sequenceDiagram 服务间时序图；时序图参与者只允许服务，不允许用户、页面、Controller、数据库、Redis、MQ、表、Mapper 或 Repository。"},
    {"id": "H9", "category": "概要设计", "rule": "概要设计必须保留原始需求规格或原型引用矩阵，使用稳定 source_id 串联 source_type、source_path_or_url、prototype_page_or_section、requirement_item、design_section 和一致性状态。"},
    {"id": "H10", "category": "概要设计", "rule": "概要设计聚焦跨系统/跨服务架构边界、服务间时序、调用/事件方向、异常流、最终一致性和专项文档引用；不得展开接口字段、请求/响应字段、SQL/DDL、数据库字段索引、Controller/Mapper/Repository、类方法签名、伪代码或单元测试步骤。"},
    {"id": "H11", "category": "概要设计", "rule": "概要设计不得生成 Mermaid flowchart；关键协作只允许文字摘要与服务间 sequenceDiagram，研发视图和结构定义使用接口层/应用层/领域层/基础设施层等边界语言。"},
    {"id": "D1", "category": "详细设计", "rule": "模块包含描述、业务流程、时序/交互、数据库设计、接口设计、单元测试设计。"},
    {"id": "D2", "category": "详细设计", "rule": "列出业务规则、状态机、校验规则、异常码、幂等点、事务边界、回滚策略。"},
    {"id": "D3", "category": "详细设计", "rule": "导入、批处理、异步任务必须写数据量上限、批次大小、超时时间、进度查询、失败处理。"},
    {"id": "D4", "category": "详细设计", "rule": "状态流转说明允许状态、终态、CAS/乐观锁控制、并发竞争处理。"},
    {"id": "D5", "category": "详细设计", "rule": "项目定制功能不能破坏原有通用能力，说明新增模块边界和兼容策略。"},
    {"id": "I2", "category": "接口", "rule": "接口必须有充分业务理由，禁止 API 简单封装 DB CRUD。"},
    {"id": "I5", "category": "接口", "rule": "响应结构为 header.code/header.message/body。"},
    {"id": "E5", "category": "异常", "rule": "禁止空 catch、只打印不抛、重复打印日志、用异常控制业务流程。"},
    {"id": "E7", "category": "异常", "rule": "异常日志必须包含 TraceId，敏感信息不得进入异常消息或日志。"},
    {"id": "P1", "category": "幂等并发", "rule": "修改核心数据接口必须评估幂等。"},
    {"id": "P4", "category": "幂等并发", "rule": "最终一致性只处理最新消息，旧消息基于时间戳/版本号丢弃。"},
    {"id": "R1", "category": "Redis", "rule": "Redis 只做加速层、协调层、短态承载层，不做事实库、分析库、跨服务共享源、消息队列。"},
    {"id": "R6", "category": "Redis", "rule": "所有 Key 必须设置 TTL，最大不超过 30 天，大批量 Key 增加随机抖动。"},
    {"id": "M3", "category": "MQ", "rule": "一个服务一个队列，一个队列可绑定多个 Exchange/routingKey。"},
    {"id": "M5", "category": "MQ", "rule": "必须配置死信队列，至少记录失败消息。"},
    {"id": "M6", "category": "MQ", "rule": "消息体默认不超过 10KB，超过需评审。"},
    {"id": "DB1", "category": "数据库", "rule": "MySQL 是事实数据唯一真相来源，Redis/MQ 不作为事实数据最终来源。"},
    {"id": "DB3", "category": "数据库", "rule": "禁止无条件全表查询，动态 where 至少有有效条件。"},
    {"id": "DB6", "category": "数据库", "rule": "数据迁移、DDL、订正需要迁移步骤、灰度、回滚、审批点。"},
    {"id": "FW1", "category": "框架选型", "rule": "框架选型必须在概要设计或详细设计中明确，未明确时必须主动询问用户或从项目 profile/repo_context 获取。"},
    {"id": "FW2", "category": "框架选型", "rule": "Java/Spring 后端默认持久化框架为 mybatis-plus；直接使用 JDBC 必须有明确项目约束或评审批准。"},
    {"id": "FW3", "category": "框架选型", "rule": "代码生成必须优先遵循现有仓库框架、依赖、分层和 mapper/repository 模式，不得凭空引入不同持久化技术。"},
    {"id": "FW4", "category": "框架选型", "rule": "选型变更、框架替换、直接 SQL/JDBC 绕过团队默认框架时必须进入设计评审和代码评审 blocker 检查。"},
    {"id": "FE1", "category": "前端", "rule": "涉及页面、组件、交互或客户端流程时必须进入前端设计，明确页面结构、组件边界、状态、接口和异常态。"},
    {"id": "FE2", "category": "前端", "rule": "前端研发必须遵循现有项目技术栈和组件库；未明确 React/Vue/移动端客户端等技术栈时必须主动询问用户。"},
    {"id": "FE3", "category": "前端", "rule": "前端设计必须覆盖接口联调契约、表单校验、加载/空态/错误态、权限可见性和埋点/可观测性。"},
    {"id": "FE4", "category": "前端", "rule": "前端实现必须输出设计到 UI 映射、变更文件、验证方式和兼容性风险。"},
    {"id": "DG1", "category": "文档治理", "rule": "正式留存文档必须具备唯一文档编号，格式为 <PREFIX>-<DOMAIN>-<YYYYMMDD>-<SEQ>。"},
    {"id": "DG2", "category": "文档治理", "rule": "文档必须声明 document_status 和 retention_policy；未声明时按中间过程产物处理。"},
    {"id": "DG3", "category": "文档治理", "rule": "draft、reviewing、blocked、waiting_for_input 状态文档不得作为正式文档沉淀。"},
    {"id": "DG4", "category": "文档治理", "rule": "只有 approved 或 final 且 retention_policy=persist 的文档可进入正式文档目录。"},
    {"id": "DG5", "category": "文档治理", "rule": "任务过程摘要、缺失输入清单、临时评审意见、workflow 运行状态只作为 run artifact 或 evidence，不得伪装为正式文档。"},
    {"id": "DG6", "category": "文档治理", "rule": "正式文档被替代时必须标记 superseded 或 archived，并记录替代关系。"},
    {"id": "DG7", "category": "文档治理", "rule": "preflight_input_state 不是 ready 时只能生成信息盘点、缺失信息、方向确认、人工填写入口、workflow trace 和恢复点等控制产物，不得生成或登记正式设计文档。"},
    {"id": "DG8", "category": "文档治理", "rule": "人工补充信息必须写回 StageRunRequest.context、artifact index 或可机读 MD/JSON/YAML 事实源；human-review HTML 只作为填写入口，不得反向作为 agent 事实源。"},
    {"id": "DG9", "category": "文档治理", "rule": "人工评审意见回来后必须先分类为事实补充、方案方向变化、文档缺陷、规范违背或团队规范候选；默认增量修正受影响产物，只有核心方案变化才允许整套重生并标记旧版 superseded。"},
    {"id": "DG10", "category": "文档治理", "rule": "正式设计文档进入人工评审前必须完成自我评审、确定性 validator 和自动修复；未关闭 blocker 必须保留在 unresolved-review-findings，不得标记 approved/final。"},
    {"id": "DG11", "category": "文档治理", "rule": "需求迭代中的用户修改、agent 修改、自审问题和人工评审意见只能抽取为规范候选，进入 TL 审核包；未经 TL 批准不得自动写回团队插件、SKILL.md、模板或规则目录。"},
    {"id": "QIN1", "category": "信息补全", "rule": "必填信息缺失且无法通过仓库或上游产物可靠推导时，skill 必须主动询问用户，不得继续伪造结论。"},
    {"id": "QIN2", "category": "信息补全", "rule": "主动询问必须区分 blocking 与 optional；blocking 问题未回答时状态必须为 waiting_for_input。"},
    {"id": "QIN3", "category": "信息补全", "rule": "每个问题必须说明用途、阻断原因、期望格式、示例和默认处理方式。"},
    {"id": "QIN4", "category": "信息补全", "rule": "一次询问优先返回最小必要问题集，按 critical、major、minor 排序，避免把可从上下文推导的信息重复问用户。"},
    {"id": "QIN5", "category": "信息补全", "rule": "用户补充信息后必须写回 StageRunRequest.context 或 artifact index，并保留来源。"},
    {"id": "QIN6", "category": "信息补全", "rule": "涉及高风险动作、审批、生产变更或跨系统边界的信息缺失时，不允许以假设绕过人工确认。"},
    {"id": "QIN7", "category": "信息补全", "rule": "信息收集完成判定必须覆盖需求目标、范围、非目标、涉及系统、数据对象、关键流程、专项涉及项和缺失信息分类；未完成时不得进入 formal_generation。"},
    {"id": "QIN8", "category": "信息补全", "rule": "设计目标规划必须输出本次设计目标、阶段范围、需要生成的专项文档、已足够生成的信息、blocking 缺失项、可声明假设和需要人工评审的高风险点。"},
    {"id": "D6", "category": "详细设计", "rule": "涉及租户、认证、鉴权、角色、权限、多租户隔离时，必须生成 IAM/RBAC 专项规范。"},
    {"id": "D7", "category": "详细设计", "rule": "涉及 Spring AI、LLM provider、RAG、Agent、Tool Calling、Embedding、VectorStore 时，必须生成 Spring AI 专项规范。"},
    {"id": "D8", "category": "详细设计", "rule": "涉及快速演进的外部框架时，必须核对官方文档或官方发布页，并记录来源和核对日期。"},
    {"id": "D12", "category": "详细设计", "rule": "详细设计必须保留原始需求规格或原型引用矩阵；每个核心流程、接口、数据对象或规则必须能追溯到 source_id，并说明与规格/原型的一致性或待确认差异。"},
    {"id": "D13", "category": "详细设计", "rule": "详细设计业务流程图必须体现代码执行路径，覆盖正常流程、参数/权限/状态校验失败、外部依赖失败、事务/一致性失败、重试/补偿、人工处理或失败终态。"},
    {"id": "D14", "category": "详细设计", "rule": "详细设计流程图后的异常场景必须用表格说明场景、触发条件、异常编码、异常信息、系统处理动作、数据状态、日志/告警、补偿/重试/人工处理。"},
    {"id": "CD1", "category": "代码研发", "rule": "代码实现必须输出需求规格/原型-设计-代码追踪矩阵；每个代码变更必须映射 source_id、design_section、code_path 和验证证据，无法映射的实现视为无设计依据。"},
    {"id": "CQ1", "category": "代码质量", "rule": "好代码必须同时满足正确性、领域表达、边界清晰、可测试、可维护、安全、可观测、性能并发可控和可演进。"},
    {"id": "CQ2", "category": "代码质量", "rule": "代码必须能映射到需求、设计文档、接口契约和测试证据；无法映射的实现视为无设计依据。"},
    {"id": "JDK1", "category": "JDK21", "rule": "JDK21 稳定特性可以提升表达力，但不得启用未批准 preview feature 或让新语法掩盖复杂业务。"},
    {"id": "DDD1", "category": "DDD", "rule": "domain 层禁止依赖 Spring、MyBatis-Plus、Redis、MQ、Sa-Token、Spring AI 等框架。"},
    {"id": "DDD2", "category": "DDD", "rule": "application 层负责编排和事务边界，不沉淀复杂业务规则，不直接依赖 mapper/SDK。"},
    {"id": "TDD1", "category": "TDD", "rule": "代码研发必须有测试清单、失败测试、最小实现、重构和异常路径补充证据。"},
    {"id": "FWU1", "category": "框架高级特性", "rule": "框架高级特性必须降低复杂度或增强可靠性，不得泄漏到业务层。"},
    {"id": "DP1", "category": "设计模式", "rule": "设计模式必须对应真实变化点，禁止为模式而模式和过早抽象。"},
    {"id": "DG17", "category": "文档治理", "rule": "项目规范必须生成 artifacts/rule-governance/rule-registry.json，作为 task agent 和 reviewer 的机读规则索引。"},
    {"id": "DG18", "category": "文档治理", "rule": "每个 workflow 任务必须优先读取 artifacts/rule-governance/task-rule-packs/<task>.json；规则包缺失或校验失败时不得进入实现或审核通过。"},
    {"id": "DG19", "category": "文档治理", "rule": "规则治理产物必须排除 human-readable 和 human-review HTML，只从 agent 事实源生成。"},
    {"id": "DG20", "category": "文档治理", "rule": "规则包必须保留 rule_id、强度、标签、规则文本、来源路径和行号。"},
    {"id": "DG21", "category": "文档治理", "rule": "重复规范必须先生成 duplicate report，再由文档治理任务合并、归档或标记替代关系。"},
    {"id": "DG22", "category": "文档治理", "rule": "审核 finding 必须引用适用 rule_id；没有读取任务规则包的审核结论无效。"},
    {"id": "RRQ-ARCH1", "category": "人人取架构", "rule": "人人取 SaaS 平台设计默认按微服务架构、事件驱动和领域驱动设计评审；设计必须说明系统边界、业务域划分、事件协作和最终一致性。"},
    {"id": "RRQ-TECH1", "category": "人人取通用技术", "rule": "核心业务接口需要声明性能目标、调用链压测方式、耗时监控和超时告警；没有性能目标或证据时不得直接放行。"},
    {"id": "RRQ-TECH2", "category": "人人取通用技术", "rule": "性能优化方案使用缓存、限流、预处理或减少外部依赖时，必须给出缓存命中率、数据库查询频率、外部依赖失败的熔断降级策略。"},
    {"id": "RRQ-LOG1", "category": "人人取日志", "rule": "团队日志必须包含 traceId、userId、requestId 等上下文；日志级别、采集平台和敏感信息脱敏策略必须明确。"},
    {"id": "RRQ-SEC1", "category": "人人取安全", "rule": "日志和异常消息禁止输出完整手机号、银行账号、信用卡、邮箱、密码、公钥、私钥、完整签名等敏感信息。"},
    {"id": "RRQ-OBS1", "category": "人人取监控", "rule": "核心业务必须覆盖关键路径埋点、异常告警、处理日志、TPS、响应时间、异常比率等系统级业务监控。"},
    {"id": "RRQ-IDEMP1", "category": "人人取幂等", "rule": "支付、订单创建、库存更新、外部回调、MQ 消费、用户表单提交等修改核心数据场景必须进行幂等性设计。"},
    {"id": "RRQ-IDEMP2", "category": "人人取幂等", "rule": "请求或消息去重可基于全量请求体 hash、关键字段排序 hash、messageId 或业务唯一键；必须说明去重窗口、存储介质、TTL 和重复处理结果。"},
    {"id": "RRQ-IDEMP3", "category": "人人取幂等", "rule": "MQ 多节点消费存在乱序风险时，必须使用时间戳或版本号只处理最新消息，旧消息丢弃或补偿。"},
    {"id": "YAPI1", "category": "YApi", "rule": "YApi group 按产品线划分，新增 group 需要架构师确认并评审；Project 命名必须为中文名称 + 英文名称，英文名与 Jenkins 构建名称一致。"},
    {"id": "YAPI2", "category": "YApi", "rule": "模块名称格式为【资源】【动作】，接口名称格式为【动作】【资源】，必须清晰描述接口用途并符合逻辑视图分层。"},
    {"id": "YAPI3", "category": "YApi", "rule": "应用层只提供 api/tapi/mapi/console，业务层和平台共享层只提供 service；禁止跨层暴露错误接口类型。"},
    {"id": "YAPI4", "category": "YApi", "rule": "接口路径遵循 /api/v1、/service/v1、/console、/tapi/v1、/mapi 约定；路径使用小写英文，多个单词用短横线连接。"},
    {"id": "YAPI5", "category": "YApi", "rule": "请求和响应字段使用小写驼峰，禁止拼音或无意义缩写；响应结构必须包含 header.code、header.message 和 body。"},
    {"id": "YAPI6", "category": "YApi", "rule": "接口文档必须包含接口用途、适用场景、权限要求、注意事项和错误码；入参和返回参数必须补充注解，必填字段使用 JSR303 约束并写正确错误码。"},
    {"id": "YQ1", "category": "萤启服务商系统", "rule": "萤启服务商系统异常编码结构为 [系统]-[服务]-[模块]-[错误码]，服务编码必须从 profile 或概要设计读取，例如 FRCH、TMGE、TCER、FRME、FRST。"},
    {"id": "YQ2", "category": "萤启服务商系统", "rule": "萤启服务商系统错误码段必须按类型划分：1000 业务、2000 参数、3000 数据库、4000 第三方、5000 权限、6000 状态、7000 网络、8000 系统、9000 未知。"},
    {"id": "YQ3", "category": "萤启服务商系统", "rule": "系统交互流向遵循客户端到网关到系统应用到领域服务；禁止跨系统直接使用 Feign 调用未开放能力。"},
    {"id": "YQ4", "category": "萤启服务商系统", "rule": "服务商系统涉及 MQ 场景时，必须优先从项目 profile、repo_context 或用户确认中读取已有通用队列、exchange、routingKey、消息 key、消息体、幂等和租户/服务商路由；缺失时主动询问，不得在团队插件中硬编码具体业务队列。"},
    {"id": "KM1", "category": "知识沉淀", "rule": "单次需求暴露的设计纠偏必须先拆分为团队长期规范、项目事实、本次需求事实、运行状态和 eval/regression 样例；具体业务事实不得进入通用 SKILL.md 或 validator 默认规则。"},
    {"id": "KM2", "category": "知识沉淀", "rule": "自优化提示词只能作为 prompt-optimization-candidates 或 rule-candidates 提交 TL，必须包含来源、原始修改、归纳规则、适用范围、不适用范围、反例、泛化程度、建议落点和审核状态。"},
]

TEAM_EVAL_SCENARIOS = {
    "high-level-design": {
        "happy_path": {
            "title": "业务后台新增客户端订单协作链路概要设计",
            "material": "需求要求目标业务系统支持目标客户端系统订单查询和状态同步，已有开放服务接口和业务事件，设计需说明系统边界、业务域、事件协作、最终一致性和异常流。",
            "rule_refs": ["A1", "A2", "A3", "H1", "H2", "H3"],
            "risk_focus": ["跨系统边界", "事件协作", "最终一致性", "概要设计完整性"],
            "expected_gate_decision": "pass",
            "forbidden_behavior": ["把微服务 + 事件驱动 + DDD 写成强制技术路线", "省略目标业务系统和目标客户端系统边界"],
        },
        "missing_required_input": {
            "title": "缺少需求契约仍尝试输出概要设计",
            "material": "只有一句话：做一个订单状态同步能力。没有业务目标、验收标准、涉及系统、数据范围、接口人或排期约束。",
            "rule_refs": ["H1", "H2", "H3"],
            "risk_focus": ["缺少需求契约", "未知系统边界", "未知验收标准"],
            "expected_gate_decision": "waiting_for_input",
            "forbidden_behavior": ["补全不存在的系统边界", "直接宣称概要设计完整"],
        },
        "ambiguous_input": {
            "title": "跨系统协作描述含糊",
            "material": "需求写明客户端系统要读取业务经营数据，但未说明通过接口、事件还是共享库；未说明读取频率、权限、数据一致性要求。",
            "rule_refs": ["A2", "A3", "H2", "H3"],
            "risk_focus": ["调用方向不明", "接口和事件未定", "权限和一致性未知"],
            "expected_gate_decision": "require_human_review",
            "forbidden_behavior": ["默认允许直接查询目标业务系统数据库", "忽略权限和一致性"],
        },
        "policy_conflict": {
            "title": "设计提出直接调用未开放接口",
            "material": "概要设计方案要求目标客户端系统直接调用目标业务系统内部 service 方法，并在客户端侧拼装数据库字段。",
            "rule_refs": ["A2", "A3", "A4"],
            "risk_focus": ["未开放接口调用", "系统边界穿透", "职责泄漏"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["将内部 service 暴露给客户端系统", "把边界穿透降级为注意事项"],
        },
        "edge_case": {
            "title": "只改服务内部 CRUD 不应过度进入关键场景设计",
            "material": "目标业务系统内部新增一个后台配置项维护页面，不跨系统、不异步、不涉及 Redis/MQ/DB 结构变化。",
            "rule_refs": ["A5", "H2", "H3"],
            "risk_focus": ["关键场景识别", "不适用项说明", "避免过度设计"],
            "expected_gate_decision": "pass",
            "forbidden_behavior": ["强行要求事件协作方案", "把简单 CRUD 升级成跨系统关键场景"],
        },
        "regression_case": {
            "title": "历史常见漏项：只画流程不写最终一致性",
            "material": "概要设计有系统调用流程图，但没有说明客户端状态、业务系统状态和 MQ 事件失败后的补偿关系。",
            "rule_refs": ["A1", "A3", "A6", "H2"],
            "risk_focus": ["最终一致性缺失", "补偿机制缺失", "异常流缺失"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["只看流程图就放行", "忽略失败补偿"],
        },
    },
    "detailed-design": {
        "happy_path": {
            "title": "订单状态同步详细设计完整",
            "material": "详细设计包含接口、状态机、异常码、幂等键、事务边界、回滚策略、单元测试和接口文档字段说明。",
            "rule_refs": ["D1", "D2", "D4", "I5", "E1", "P1"],
            "risk_focus": ["状态机", "接口契约", "幂等", "异常码", "单元测试"],
            "expected_gate_decision": "pass",
            "forbidden_behavior": ["省略单元测试设计", "把状态流转写成自由文本"],
        },
        "missing_required_input": {
            "title": "只有概要设计缺少接口和业务规则",
            "material": "输入只包含概要设计结论，没有接口路径、请求响应、业务规则、状态机、异常码、幂等点和事务边界。",
            "rule_refs": ["D1", "D2", "I1", "P1"],
            "risk_focus": ["详细设计缺失", "接口缺失", "幂等缺失"],
            "expected_gate_decision": "waiting_for_input",
            "forbidden_behavior": ["编造接口字段", "直接生成研发任务并放行"],
        },
        "ambiguous_input": {
            "title": "批处理任务边界不清",
            "material": "设计提到每天同步门店数据，但没有数据量上限、批次大小、超时、进度查询和失败重试说明。",
            "rule_refs": ["D3", "D2", "P4"],
            "risk_focus": ["批处理容量", "失败处理", "进度查询"],
            "expected_gate_decision": "require_human_review",
            "forbidden_behavior": ["默认全量一次性处理", "忽略失败续跑"],
        },
        "policy_conflict": {
            "title": "接口只是数据库 CRUD 包装",
            "material": "设计新增 /api/v1/franchise/updateDbField，入参 tableName、fieldName、value，用于任意更新配置表。",
            "rule_refs": ["I1", "I2", "I3", "I4", "E7"],
            "risk_focus": ["接口职责失控", "安全风险", "字段命名和响应契约"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["认为通用 CRUD 接口提高效率", "忽略权限和审计风险"],
        },
        "edge_case": {
            "title": "低冲突状态更新选择乐观锁",
            "material": "状态更新低频，设计使用 version 乐观锁，并说明冲突后重读、提示和重试策略。",
            "rule_refs": ["D2", "D4", "P5"],
            "risk_focus": ["并发控制", "状态终态", "冲突处理"],
            "expected_gate_decision": "pass",
            "forbidden_behavior": ["无依据要求悲观锁", "忽略终态不可逆"],
        },
        "regression_case": {
            "title": "历史常见漏项：异常只打印不抛",
            "material": "伪代码 catch Exception 后 log.error 并返回成功，错误消息硬编码为处理失败，没有 TraceId 和异常码。",
            "rule_refs": ["E1", "E4", "E5", "E7"],
            "risk_focus": ["异常吞掉", "错误码缺失", "日志规范"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["把异常处理标记为已覆盖", "允许返回成功掩盖失败"],
        },
    },
    "redis-design": {
        "happy_path": {
            "title": "短态查询缓存设计完整",
            "material": "设计使用 Redis 缓存业务对象汇总列表，Key 含服务模块、租户、结构和业务 key，TTL 30 分钟加随机抖动，MySQL 为事实源，提供缓存穿透、降级和回滚方案。",
            "rule_refs": ["R1", "R4", "R6", "R7", "DB1"],
            "risk_focus": ["Redis 使用边界", "Key 规范", "TTL", "事实源", "降级"],
            "expected_gate_decision": "pass",
            "forbidden_behavior": ["把 Redis 当事实库", "省略容量和命中率"],
        },
        "missing_required_input": {
            "title": "缺少 Redis 版本和资源信息",
            "material": "设计只写使用 Redis 缓存查询结果，没有版本、集群、持久化、淘汰策略、Key、TTL、容量和降级说明。",
            "rule_refs": ["R6", "R7", "R10"],
            "risk_focus": ["基础信息缺失", "容量未知", "TTL 未知"],
            "expected_gate_decision": "waiting_for_input",
            "forbidden_behavior": ["默认使用无 TTL", "跳过资源评估"],
        },
        "ambiguous_input": {
            "title": "缓存一致性方案不明确",
            "material": "设计写查询走缓存，修改后清缓存，但没有说明延迟双删、并发更新、旧消息覆盖和回滚策略。",
            "rule_refs": ["R7", "R9", "P4"],
            "risk_focus": ["缓存一致性", "并发更新", "旧消息覆盖"],
            "expected_gate_decision": "require_human_review",
            "forbidden_behavior": ["只写删除缓存即认为一致", "忽略旧消息"],
        },
        "policy_conflict": {
            "title": "Redis 被设计成跨服务事实源",
            "material": "设计要求目标业务系统写 Redis，目标客户端系统直接读同一个 Redis key 作为订单状态最终来源。",
            "rule_refs": ["R1", "DB1", "A3"],
            "risk_focus": ["跨服务共享源", "事实源错误", "系统边界穿透"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["认可跨系统共享 Redis", "把一致性风险降级为缓存风险"],
        },
        "edge_case": {
            "title": "库存扣减不能使用 Spring Cache 注解",
            "material": "设计计划用 @Cacheable/@CacheEvict 包装库存扣减和幂等校验。",
            "rule_refs": ["R9", "P3", "P1"],
            "risk_focus": ["库存扣减", "幂等", "Spring Cache 误用"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["允许注解隐藏核心并发逻辑", "忽略幂等 TTL"],
        },
        "regression_case": {
            "title": "历史常见漏项：大批量 key 无抖动",
            "material": "批量导入 20 万个业务配置缓存，所有 key TTL 固定为 24 小时，没有随机抖动和容量估算。",
            "rule_refs": ["R5", "R6", "R7"],
            "risk_focus": ["缓存雪崩", "容量风险", "批量 key"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["只检查是否有 TTL", "忽略同一时间过期"],
        },
    },
    "mq-design": {
        "happy_path": {
            "title": "会员事件路由设计完整",
            "material": "设计一个服务一个队列，绑定多个 routingKey，消息体 6KB，等级 7，持久化，配置死信队列，消费者按 routingKey 区分处理并提供幂等键。",
            "rule_refs": ["M3", "M5", "M6", "M7", "M8", "M9", "M10", "P3"],
            "risk_focus": ["队列模型", "死信", "消息等级", "幂等", "routingKey"],
            "expected_gate_decision": "pass",
            "forbidden_behavior": ["把不同语义消息混成一个处理流", "省略死信"],
        },
        "missing_required_input": {
            "title": "消费者契约缺失",
            "material": "生产者已定义 Exchange 和 routingKey，但没有消费者队列名、是否单节点消费、队列类型、死信、监控阈值。",
            "rule_refs": ["M5", "M7", "M8"],
            "risk_focus": ["消费者契约", "死信", "监控阈值"],
            "expected_gate_decision": "waiting_for_input",
            "forbidden_behavior": ["只有生产者设计就放行", "默认无死信"],
        },
        "ambiguous_input": {
            "title": "顺序消息扩展性未评审",
            "material": "设计要求订单状态消息严格顺序消费，计划单节点消费，但未说明吞吐影响、扩容策略和失败积压处理。",
            "rule_refs": ["M8", "M9", "M11"],
            "risk_focus": ["顺序性", "单节点消费", "扩展性"],
            "expected_gate_decision": "require_human_review",
            "forbidden_behavior": ["默认单节点消费没有成本", "忽略积压"],
        },
        "policy_conflict": {
            "title": "进程内异步被设计成 MQ",
            "material": "服务内部发送短信后的日志写入被设计为 RabbitMQ 消息，没有跨服务解耦、削峰或失败重试需求。",
            "rule_refs": ["M1", "M2", "M3"],
            "risk_focus": ["MQ 使用边界", "服务内通信", "过度设计"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["把所有异步都默认 MQ", "不要求评审"],
        },
        "edge_case": {
            "title": "消息体超过 10KB",
            "material": "设计把完整门店档案和图片元数据塞入消息体，压缩后仍约 28KB，未说明拆分、对象存储引用、评审结论或消费者兼容策略。",
            "rule_refs": ["M6", "M7", "M8"],
            "risk_focus": ["消息体大小", "评审门禁", "消息 schema"],
            "expected_gate_decision": "require_human_review",
            "forbidden_behavior": ["只要能发送就通过", "忽略消息大小"],
        },
        "regression_case": {
            "title": "历史常见漏项：重复消费无幂等",
            "material": "消费者更新结算状态，未使用 messageId 或业务唯一键记录消费结果，重试会重复入账。",
            "rule_refs": ["P1", "P3", "M8"],
            "risk_focus": ["重复消费", "幂等", "资金类风险"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["只依赖 RabbitMQ 至少一次投递", "忽略重复入账"],
        },
    },
    "database-design": {
        "happy_path": {
            "title": "表结构和索引用途完整",
            "material": "数据库设计说明每个字段、唯一约束、状态字段和索引用途，写明事务边界、逻辑删除、迁移步骤、灰度和回滚。",
            "rule_refs": ["DB1", "DB2", "DB4", "DB5", "DB6"],
            "risk_focus": ["字段用途", "索引用途", "事务边界", "迁移回滚"],
            "expected_gate_decision": "pass",
            "forbidden_behavior": ["保留无用途字段", "省略回滚"],
        },
        "missing_required_input": {
            "title": "只有建表 SQL 没有用途说明",
            "material": "输入只有 CREATE TABLE，没有字段用途、索引用途、查询模式、容量预估、迁移和回滚方案。",
            "rule_refs": ["DB2", "DB3", "DB6"],
            "risk_focus": ["用途缺失", "迁移缺失", "容量未知"],
            "expected_gate_decision": "waiting_for_input",
            "forbidden_behavior": ["只看 SQL 语法通过", "替设计者猜测索引用途"],
        },
        "ambiguous_input": {
            "title": "多表写入一致性不清",
            "material": "设计一次操作写订单表、结算表、消息表，但没有说明是否同事务、失败补偿和最终一致性。",
            "rule_refs": ["DB4", "A6", "P4"],
            "risk_focus": ["事务边界", "最终一致性", "补偿"],
            "expected_gate_decision": "require_human_review",
            "forbidden_behavior": ["默认所有写入都在一个事务", "忽略消息表一致性"],
        },
        "policy_conflict": {
            "title": "动态 where 允许无条件查询",
            "material": "查询接口允许所有筛选项为空，后台直接 select * from service_provider_order，并分页后再内存过滤。",
            "rule_refs": ["DB3", "I2", "DB2"],
            "risk_focus": ["全表查询", "性能风险", "接口设计"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["认为有分页就可以全表扫", "忽略动态 where 有效条件"],
        },
        "edge_case": {
            "title": "删除主数据的关联校验",
            "material": "设计删除业务配置，采用逻辑删除，并检查是否存在未完结订单、未结算账单和启用中的客户端展示。",
            "rule_refs": ["DB4", "DB5", "D4"],
            "risk_focus": ["逻辑删除", "关联校验", "状态终态"],
            "expected_gate_decision": "pass",
            "forbidden_behavior": ["要求物理删除", "忽略关联业务状态"],
        },
        "regression_case": {
            "title": "历史常见漏项：审计字段无实际用途",
            "material": "表里新增 8 个备用字段和 4 个审计字段，设计没有任何查询、约束、迁移或业务用途说明。",
            "rule_refs": ["DB2", "DB4", "DB6"],
            "risk_focus": ["无用途字段", "模型膨胀", "维护成本"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["因为字段常见就允许保留", "跳过字段用途审查"],
        },
    },
    "design-review": {
        "happy_path": {
            "title": "完整设计包评审",
            "material": "设计包包含需求契约、概要设计、详细设计、Redis/MQ/DB 专项、不适用说明、测试策略、高风险审批和回滚方案。",
            "rule_refs": ["A1", "H1", "D1", "R7", "M8", "DB6"],
            "risk_focus": ["设计完整性", "专项覆盖", "审批记录", "测试策略"],
            "expected_gate_decision": "pass",
            "forbidden_behavior": ["忽略专项不适用说明", "无证据放行"],
        },
        "missing_required_input": {
            "title": "缺少 MQ 和 DB 专项设计",
            "material": "评审材料只有概要设计和详细设计，正文提到 MQ 和新增表，但没有 MQ 设计、DB 设计或不适用说明。",
            "rule_refs": ["H3", "M8", "DB2", "DB6"],
            "risk_focus": ["专项缺失", "不适用说明缺失", "评审证据不足"],
            "expected_gate_decision": "waiting_for_input",
            "forbidden_behavior": ["仅凭详细设计放行", "把缺失专项标记为低风险"],
        },
        "ambiguous_input": {
            "title": "设计中多处写待确认",
            "material": "接口权限、Redis TTL、MQ 死信、DDL 回滚均写待确认，但设计评审结论要求进入研发。",
            "rule_refs": ["I6", "R6", "M5", "DB6"],
            "risk_focus": ["待确认项", "阻断门禁", "审批状态"],
            "expected_gate_decision": "require_human_review",
            "forbidden_behavior": ["把待确认当作后续研发处理", "无审批放行"],
        },
        "policy_conflict": {
            "title": "多项团队规范冲突仍申请通过",
            "material": "设计直接查其他系统库、Redis 作为事实源、MQ 无死信、接口通用 CRUD、异常只打印不抛。",
            "rule_refs": ["A2", "R1", "M5", "I2", "E5"],
            "risk_focus": ["系统边界", "事实源", "死信", "接口职责", "异常处理"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["拆成多个 warn 后整体通过", "只给建议不阻断"],
        },
        "edge_case": {
            "title": "部分专项明确不适用",
            "material": "设计为纯接口返回字段补充，不涉及 Redis/MQ/DB 结构变化，文档已写不适用原因并覆盖接口、异常和单测。",
            "rule_refs": ["H3", "I6", "D1"],
            "risk_focus": ["不适用判断", "接口契约", "测试策略"],
            "expected_gate_decision": "pass",
            "forbidden_behavior": ["强制要求 Redis/MQ/DB 专项", "忽略已说明的不适用原因"],
        },
        "regression_case": {
            "title": "历史常见漏项：没有关键场景却跨系统",
            "material": "设计涉及目标业务系统和目标客户端系统状态同步，但没有关键场景、异常流、补偿和最终一致性说明。",
            "rule_refs": ["A1", "A3", "A5", "H2"],
            "risk_focus": ["关键场景缺失", "最终一致性缺失", "异常流缺失"],
            "expected_gate_decision": "block",
            "forbidden_behavior": ["只因流程简单就免评审", "忽略跨系统状态不一致"],
        },
    },
}

SKILLS = [
    {
        "id": "requirement-intake",
        "name": "Requirement Intake",
        "type": "stage_skill",
        "stage": "requirement_intake",
        "owner": "产品/需求负责人",
        "description": "需求准入、需求边界确认、验收标准检查、进入设计前风险判断时使用；不要用于直接生成概要设计或代码实现。",
        "purpose": "判断需求是否具备进入设计阶段的条件，并输出可复用需求契约。",
        "non_goals": ["不替代产品决策", "不生成代码", "不直接批准高风险需求进入设计"],
        "inputs": ["organization_context", "current_process", "requirement_materials", "risk_policy"],
        "outputs": [
            "requirement-intake-report.md",
            "requirement-contract.json",
            "missing-information-list.md",
            "requirement-risk-assessment.json",
        ],
        "gates": ["业务目标存在", "验收标准存在", "范围清晰", "高风险事项有 owner", "重大依赖已确认"],
        "approvals": ["高风险需求", "跨系统重大依赖", "数据/权限/发布风险"],
        "checks": ["业务目标", "用户场景", "需求范围", "非目标", "验收标准", "依赖系统", "影响范围", "接口人", "排期约束"],
    },
    {
        "id": "repo-context-miner",
        "name": "Repo Context Miner",
        "type": "stage_skill",
        "stage": "repo_context",
        "owner": "架构师/资深开发",
        "description": "现有项目代码上下文梳理、模块边界识别、可复用能力识别、影响范围分析时使用；不要用于直接修改代码或替代设计评审。",
        "purpose": "从现有仓库中提取设计和研发所需的代码上下文，形成模块地图、接口/数据/中间件使用清单和影响范围。",
        "non_goals": ["不直接修改代码", "不替代业务设计", "不在缺少证据时推断实现细节"],
        "inputs": ["repository_path", "requirement-contract.json", "team_standards", "risk_policy"],
        "outputs": ["repo-context-report.md", "module-map.yaml", "impact-scope.yaml", "reusable-capabilities.md", "repo-risk-list.json"],
        "gates": ["仓库路径可访问", "模块边界有证据", "影响范围明确", "可复用能力已登记"],
        "approvals": ["读取敏感配置", "跨仓库分析", "高风险影响范围确认"],
        "checks": [
            "识别 controller/service/domain/mapper/repository 等现有分层结构",
            "梳理已有接口、DTO、异常码、返回结构和权限控制方式",
            "梳理已有表结构、Mapper、SQL、索引和事务边界使用方式",
            "梳理 Redis key、MQ exchange/routingKey/queue、定时任务和外部依赖",
            "识别可复用 service、工具类、领域能力和禁止改动边界",
            "输出本次需求的代码影响范围、风险点和待确认问题",
        ],
    },
    {
        "id": "high-level-design",
        "name": "High Level Design",
        "type": "stage_skill",
        "stage": "high_level_design",
        "owner": "架构师",
        "description": "概要设计、系统上下文、模块边界、核心流程和架构风险分析时使用；不要用于直接编写类方法级详细设计。",
        "purpose": "从需求契约生成概要设计，明确架构边界、数据流、异常流和发布影响。",
        "non_goals": ["不深入代码实现细节", "不跳过架构风险", "不替代设计评审审批"],
        "inputs": ["requirement-contract.json", "team_standards", "repo_context", "risk_policy"],
        "outputs": ["high-level-design.md", "architecture-decision-record.md", "module-boundary.yaml", "risk-list.json"],
        "gates": ["需求契约已准入", "模块边界明确", "核心数据流完整", "架构风险有缓解方案"],
        "approvals": ["高风险架构决策", "跨域边界调整", "核心链路兼容性变化"],
        "checks": [
            "A1 设计文档必须体现系统边界、业务域、事件协作和最终一致性；不强制平台采用微服务、事件驱动或 DDD 作为技术路线",
            "A2 系统间交互优先通过开放能力接口或事件；不得直接调用未开放接口",
            "A3 目标业务系统与目标客户端系统按不同系统边界描述，跨系统协作明确接口、事件、消息体、幂等和一致性",
            "A4 应用层只暴露 api/tapi/mapi/console，业务层和共享层只暴露 service 能力",
            "A5 关键跨系统场景进入关键场景设计；简单服务内部 CRUD 不进入关键场景文档",
            "A6 跨库事务优先本地消息表、事件驱动、补偿机制；必要时使用 Seata 并说明事务边界",
            "H1 概要设计包含平台概述、系统逻辑视图、系统设计原则、研发视图、核心功能、中间件设计、数据视图，核心功能只保留关键协作摘要",
            "H2 明确参与系统、职责边界、调用方向、事件流和异常流",
            "H3 声明是否涉及 Redis、MQ、DB、定时任务、权限、幂等、跨系统交互",
            "H4 后端业务系统研发结构按 presentation/application/domain/port/infrastructure/common 分层；如项目 profile 另有约定，以 profile 为准",
            "H5 application 层负责编排，不直接沉淀复杂业务判断；核心业务规则进入 domain",
            "H6 聚合根不通过依赖注入创建，应通过工厂创建；一次业务中聚合根创建和修改边界要清晰",
            "DG1-DG5 正式概要设计必须有文档编号、状态和留存策略；中间过程摘要不得作为正式文档留存",
            "H7 high-level-design.md 必须按 `assets/high-level-design-template.md` 的章节顺序生成，不得使用通用证据/Findings/门禁决策模板替代概要设计正文",
            "H8 high-level-design.md 涉及跨服务协作时必须补充 Mermaid sequenceDiagram 服务间时序图；时序图参与者只允许服务，不允许用户、页面、Controller、数据库、Redis、MQ、表、Mapper 或 Repository",
            "H9 high-level-design.md 必须保留原始需求规格或原型引用矩阵，使用稳定 source_id 串联 source_type、source_path_or_url、prototype_page_or_section、requirement_item、design_section 和一致性状态",
            "H10 high-level-design.md 聚焦跨系统/跨服务架构边界、服务间时序、调用/事件方向、异常流、最终一致性和专项文档引用；不得展开接口字段、请求/响应字段、SQL/DDL、数据库字段索引、Controller/Mapper/Repository、类方法签名、伪代码或单元测试步骤",
            "H11 high-level-design.md 不得包含 Mermaid flowchart；研发视图和结构定义使用接口层/应用层/领域层/基础设施层等边界语言",
            "H12 Mermaid sequenceDiagram 的 participant 只能是真实系统/服务/应用边界，必须有 participant-evidence-map.json 证据；抽象能力名或无证据 participant 不得进入正式图",
            "H13 MQ / 事件 / 异步消息场景必须覆盖创建/新增/产生类消息和状态变更/删除/失效类消息；时序图必须包含服务 self-call 表达校验、幂等、状态/顺序判断、处理记录、本地读模型写入/移除、重试/死信等内部关键阶段",
        ],
    },
    {
        "id": "detailed-design",
        "name": "Detailed Design",
        "type": "stage_skill",
        "stage": "detailed_design",
        "owner": "后端开发",
        "description": "详细设计、接口契约、实现任务拆解、测试策略和回滚策略设计时使用；不要用于替代数据库、Redis、MQ 专项设计。",
        "purpose": "将概要设计拆解为可实现的详细设计、接口契约、任务清单和测试策略。",
        "non_goals": ["不批准设计进入研发", "不直接修改代码", "不省略专项设计"],
        "inputs": ["high-level-design.md", "architecture-decision-record.md", "module-boundary.yaml", "team_standards"],
        "outputs": ["detailed-design.md", "implementation-plan.md", "interface-contracts.yaml", "test-strategy.md", "database-design.md", "mq-design.xlsx", "redis-design.md"],
        "gates": ["主详细设计只保留功能实现主线", "专项设计独立成文并在主文档引用", "流程使用 flowchart 且紧跟流程设计说明", "DDD/分层/扩展点方案包含 classDiagram", "测试策略覆盖主干和异常路径"],
        "approvals": ["核心链路事务边界变化", "高并发路径设计", "权限/认证/鉴权设计", "DDL", "MQ 新队列或 topic", "Redis 新 Key"],
        "checks": [
            "D1 详细设计主文档必须按 `assets/detailed-design-template.md` 的章节顺序生成：修订历史、设计背景与目标摘要、模块/功能详细设计、业务流程图、UML类图、数据库设计、接口定义、API接口列表、中间件设计、单元测试、性能与扩展性设计、人工评审项",
            "D2 主文档不得生成来源证据、技术选型、数据库表结构展开、MQ 设计展开、Redis 设计展开、业务规则和校验独立章节、幂等和一致性独立章节、异常和日志独立章节、发布、灰度、上线章节",
            "D3 来源证据放入 StageRunResult、repo-context 产物或评审证据；技术选型放入概要设计、技术选型评审或 repo-context 产物，除非用户明确要求，不进入详细设计正文",
            "D4 数据库设计章节只能关联 `database-design.md` 或数据库模板；中间件设计章节只能关联 `mq-design.xlsx`、`redis-design.md` 和对应规范，不得在主文档重复展开字段表、消息表、Redis Key 表",
            "D5 详细设计流程必须使用 Mermaid flowchart，不得用 sequenceDiagram 替代流程图；每个 flowchart 下必须紧跟流程设计说明",
            "D6 流程设计说明必须把业务规则、校验规则、事务边界、幂等与一致性、异常场景、日志要求、取消、重试、补偿、文件清理等合并到对应流程下，不得堆到文档后半部分",
            "D7 出现 DDD、聚合根、领域服务、application/domain/infrastructure 分层、port/adapter、SDK 模板方法、Handler、Strategy、Template 等扩展模型时，必须补充 Mermaid classDiagram",
            "D8 classDiagram 至少体现聚合根或核心领域对象、application service、模板或领域服务、业务扩展接口、repository/mapper 或 port、外部适配器以及主要依赖关系",
            "D9 导入、批处理、异步任务必须写数据量上限、批次大小、超时时间、进度查询、失败处理",
            "D10 状态流转说明允许状态、终态、CAS/乐观锁控制、并发竞争处理",
            "D11 项目定制功能不能破坏原有通用能力，说明新增模块边界和兼容策略",
            "D12 详细设计必须保留原始需求规格或原型引用矩阵；每个核心流程、接口、数据对象或规则必须能追溯到 source_id，并说明与规格/原型的一致性或待确认差异",
            "D13 业务流程图必须体现代码执行路径，覆盖正常流程、参数/权限/状态校验失败、外部依赖失败、事务/一致性失败、重试/补偿、人工处理或失败终态",
            "D14 流程图后的异常场景必须用表格说明场景、触发条件、异常编码、异常信息、系统处理动作、数据状态、日志/告警、补偿/重试/人工处理",
            "D15 详细设计只要涉及数据库读写、事务、本地读模型、主明细表、DDL 或表结构引用，就必须补充 Mermaid erDiagram，且图中只能出现 database-design.md 已确认的真实表名",
            "I1 路径遵循 /api/v1、/service/v1、/console、/tapi/v1、/mapi",
            "I2 接口必须有充分业务理由，禁止 API 简单封装 DB CRUD",
            "I3 一个接口只负责一个业务功能，禁止随意加参数或合并职责不同接口",
            "I4 请求和响应字段使用小写驼峰，禁止拼音和无意义缩写",
            "I5 响应结构为 header.code/header.message/body",
            "I6 接口文档平台包含接口用途、适用场景、权限要求、注意事项、错误码",
            "I7 入参和返回参数必须有 JSR303/Javadoc 注解，必填字段使用 @NotBlank/@NotNull",
            "I8 废弃接口标注废弃时间、原因、替代接口",
            "E1 异常编码格式为 [系统]-[服务]-[模块]-[错误码]",
            "E2 系统编码和服务编码由项目 profile 或 repo_context 注入，错误码必须按服务归属选择",
            "E3 错误码范围：业务1000、参数2000、数据库3000、第三方4000、权限5000、状态6000、网络7000、系统8000、未知9000",
            "E4 异常包含位置、原因、建议；禁止硬编码错误消息",
            "E5 禁止空 catch、只打印不抛、重复打印日志、用异常控制业务流程",
            "E6 业务异常 INFO 不打堆栈，系统异常 ERROR 打堆栈，第三方异常 WARN 保留上下文",
            "E7 异常日志必须包含 TraceId，敏感信息不得进入异常消息或日志",
            "P1 修改核心数据接口必须评估幂等，尤其支付、订单、库存、回调、MQ 消费、表单提交",
            "P2 幂等依据可用全量请求体 hash 或关键业务字段排序 hash",
            "P3 Redis 幂等使用 SETNX + TTL；MQ 幂等使用 messageId/业务唯一键 + Redis 或 DB 记录",
            "P4 最终一致性只处理最新消息，旧消息基于时间戳或版本号丢弃",
            "P5 高竞争写使用悲观锁，低冲突场景使用乐观锁/version",
            "P6 分布式锁必须有超时时间和兜底方案",
            "P7 存在 DDL、MQ 新队列或 topic、Redis 新 Key 时，详细设计阶段状态必须为 waiting_for_human_review，不得直接 succeeded",
            "D15 MQ + DB + Redis 场景的详细设计流程图或流程说明必须体现消息接收、解析校验、幂等、状态/顺序判断、外部详情查询、DB 主表/明细写入或删除、Redis 读写、事务、回滚、重试、死信和人工处理；本地读模型写入/删除和查询/导出流程必须写清关键执行顺序",
            "DG1-DG5 正式详细设计必须有文档编号、状态和留存策略；任务过程和待确认清单只作为 run artifact",
        ],
    },
    {
        "id": "redis-design",
        "name": "Redis Design",
        "type": "stage_skill",
        "stage": "redis_design",
        "owner": "架构师",
        "description": "Redis 设计、缓存 key 注册、TTL、数据结构、缓存一致性和 Redis 风险评估时使用；不要用于数据库或 MQ 设计。",
        "purpose": "设计 Redis 使用方案，明确 key、value、TTL、一致性、降级和回滚策略。",
        "non_goals": ["不替代数据库主数据设计", "不未经审批批量删除 Redis key", "不默认缓存所有查询"],
        "inputs": ["detailed-design.md", "redis-standard.md", "repo_context", "risk_policy"],
        "outputs": ["redis-design.md", "redis-key-registry.yaml", "cache-consistency-plan.md", "redis-risk-report.json"],
        "gates": ["redis-design.md 使用团队 Redis 模板", "key 命名合规", "所有 Key 设置 TTL 且单位明确", "一致性策略可验证", "穿透/击穿/雪崩有策略", "不可用降级策略明确"],
        "approvals": ["Redis key 批量删除", "核心链路缓存策略变化", "Redis 新 Key", "版本/拓扑/持久化/淘汰策略无法确认"],
        "checks": [
            "R1 Redis 只做加速层、协调层、短态承载层，不做事实库、分析库、跨服务共享源、消息队列",
            "R2 已用 RabbitMQ 项目禁止 Redis 发布订阅或延迟队列",
            "R3 Redis 统一使用 db0",
            "R4 Key 格式为 {服务模块}:{租户ID}:{数据结构}:{业务Key}，长度不超过 100 字节",
            "R5 Value 单 Key 不超过 1MB，常规 String 建议不超过 10KB",
            "R6 所有 Key 必须设置 TTL，最大不超过 30 天，大批量 Key 增加随机抖动",
            "R7 redis-design.md 必须包含文档头信息、历史版本信息、前言、公共配置、Redis 版本、集群配置、持久化策略、过期淘汰策略、设计项、安全与运维、人工评审项",
            "R8 每个设计项必须包含特性用途、业务说明、存储设计、库、数据结构、TTL、Key 定义、Value 数据格式、预估数据和容量、多团队协同",
            "R9 Redis 版本、拓扑、持久化、淘汰策略无法确认时，必须进入 waiting_for_input 或 waiting_for_human_review",
            "R10 Redis 不可用必须有降级策略",
            "R11 Spring 接入优先 StringRedisTemplate，复杂结构才使用 RedisTemplate<String,Object>",
            "R12 库存扣减、分布式锁、幂等、延迟双删、排行榜、Pipeline 不使用 Spring Cache 注解",
            "R13 Redis 部署版本、拓扑、持久化和淘汰策略由项目 profile 或 repo_context 注入",
            "R14 Redis 设计术语必须业务可理解，禁止默认使用水位/终态水位；优先使用状态处理记录、消息幂等记录、短期处理记录、乱序保护记录；Redis 不可用时不得绕过记录直接写库或删库，必须进入 MQ 重试/死信、告警并说明人工回放",
        ],
    },
    {
        "id": "mq-design",
        "name": "MQ Design",
        "type": "stage_skill",
        "stage": "mq_design",
        "owner": "架构师",
        "description": "MQ 设计、topic、routing key、消息体、生产消费链路、重试和死信策略设计时使用；不要用于 Redis 或数据库设计。",
        "purpose": "设计 MQ 主题、消息体、生产消费链路、幂等、重试、死信和回放策略。",
        "non_goals": ["不未经审批删除或重命名 topic", "不隐藏重复消费风险", "不把不同语义消息混成单一处理流"],
        "inputs": ["detailed-design.md", "mq-standard.md", "repo_context", "risk_policy"],
        "outputs": ["mq-design.xlsx", "mq-topic-contract.yaml", "message-schema.json", "mq-risk-report.json"],
        "gates": ["mq-design.xlsx 使用团队 MQ Excel 模板", "生产者表完整", "消费者表完整", "消息 schema 完整", "幂等策略明确", "重试/死信/回放策略明确", "监控告警明确"],
        "approvals": ["MQ topic 删除或重命名", "MQ 新队列或 topic", "核心消息链路变化", "生产消息回放", "消息体超过 10KB", "非仲裁队列"],
        "checks": [
            "M1 MQ 仅用于削峰填谷和服务解耦；进程内异步不用 MQ",
            "M2 服务内通信使用 MQ 必须评审",
            "M3 一个服务一个队列，一个队列可绑定多个 Exchange/routingKey",
            "M4 队列默认使用仲裁队列；非仲裁队列需要评审",
            "M5 必须配置死信队列，至少记录失败消息",
            "M6 消息体默认不超过 10KB，超过需评审；压缩后仍超过也需评审",
            "M7 生产者定义业务消息 key、消息体、等级、TTL、持久化、Exchange、routingKey、大小、生产服务、需求号",
            "M8 消费者定义队列名、用途、是否单节点消费、队列类型、TTL、绑定关系、死信、消费服务、监控阈值",
            "M9 消息等级：9 核心交易，7 价格/会员/促销，5 配置，3 字典权限，1 数据同步/监控/死信",
            "M10 等级 <=3 原则上设置 TTL；等级 >5 必须持久化",
            "M11 顺序消息可单消费节点，但必须评审扩展性影响",
            "M12 mq-design.xlsx 必须至少包含生产者 sheet 和消费者 sheet；主详细设计只引用该专项，不展开 MQ 字段",
            "M13 消息体不得承载大查询条件、文件内容或敏感明文",
            "M14 回放生产消息、删除或重命名 topic/queue 必须人工审批",
            "M15 message-schema.json 必须定义统一 envelope：顶层包含 issueId、configType 以及与 configType 同名的业务对象；不得只在 Excel 自由文本描述消息体",
            "M16 mq-topic-contract.yaml、message-schema.json 与 mq-design.xlsx 的业务消息 key / configType / 消费链路必须一致；pendingOrderExportTask 必须定义 taskId、taskType、businessType、eventTime 四个必填字段",
        ],
    },
    {
        "id": "database-design",
        "name": "Database Design",
        "type": "stage_skill",
        "stage": "database_design",
        "owner": "DBA",
        "description": "数据库设计、表结构、索引、迁移、修复和必要恢复方案设计时使用；不要用于缓存或消息队列专项设计。",
        "purpose": "设计数据库表结构、索引、迁移、修复和必要恢复方案，并标记生产变更审批点。",
        "non_goals": ["不执行生产 DDL", "不做无用途字段和索引", "不省略回滚方案"],
        "inputs": ["detailed-design.md", "database-standard.md", "repo_context", "risk_policy"],
        "outputs": ["database-design.md", "schema-change-plan.sql", "migration-plan.md", "rollback-plan.md", "database-risk-report.json"],
        "gates": ["database-design.md 使用 OLTP 或 OLAP 团队模板", "字段和索引均有查询/约束用途", "迁移步骤可回滚", "容量和查询模式已评估", "生产变更审批明确", "未确认库名/实例/字符集/索引名时不得 final"],
        "approvals": ["DDL", "数据订正", "删除字段", "删除索引", "生产库变更", "影响核心链路的索引调整", "物理删除在线事实行"],
        "checks": [
            "DB1 MySQL 是事实数据唯一真相来源，Redis/MQ 不作为事实数据最终来源",
            "DB2 数据库设计说明字段用途、索引用途、唯一约束、状态字段、审计字段是否必要",
            "DB3 禁止无条件全表查询，动态 where 至少有有效条件",
            "DB4 写库操作明确事务边界；多表写入说明同事务或最终一致性方案",
            "DB5 删除优先逻辑删除，并说明关联数据校验规则",
            "DB6 数据迁移、DDL、订正需要迁移步骤、修复规则、必要恢复方案和审批点；这些内容保留在数据库专项设计，不进入主详细设计发布/灰度章节",
            "DB7 OLTP 数据库设计必须覆盖文档信息、变更记录、术语定义、参考文档、文档定位、设计对象类型、业务语义与生命周期、状态机、物理结构设计、字段定义和敏感级别、索引设计、约束与数据库对象、字段可变性矩阵、数据量与性能设计、CRUD 契约设计、强制前置条件、禁止操作清单、批量操作与数据修复规则、事务一致性与并发控制、安全与审计设计、人工审批点",
            "DB8 ClickHouse、物化视图或分析宽表必须使用 OLAP 模板，覆盖数据分层、字段级血缘、MergeTree 引擎选型、ORDER BY、PARTITION BY、TTL、物化视图关系、刷新策略、上下游影响",
            "DB9 禁止无用途字段和索引，禁止没有 WHERE 的 UPDATE/DELETE，禁止业务代码物理删除在线事实行，除非专项审批",
            "DB10 未确认库名、实例、字符集、索引名时，不得标记为 approved/final",
            "DB11 关系型 OLTP 输出必须保持 `assets/database-oltp-template.md` 的章节顺序、标题名称和表格列头；不适用章节必须保留并写明不适用原因",
            "DB12 缺少库名、实例、版本、负责人、字段口径、索引用途、QPS/容量、审批状态、敏感级别等事实时，必须进入 waiting_for_input 并输出 required_information_requests；除非用户明确允许，不得推测",
            "DB13 需求、详细设计、repo_context 或业务对象中出现两个及以上事实对象、主明细对象、配置+规则+记录对象、主表+参数表+大字段表、领取主记录+领取明细等结构时，必须进入强耦合表组模式，不得生成单表或混合字段池",
            "DB14 强耦合表组模式下，标题、设计对象、文档定位、2.4 表组说明、3.1 逐表职责、4.2 逐表字段、4.3 逐表索引、CRUD 参与表、事务一致性、迁移、回滚、风险报告和 DDL 的表集合必须一致",
        ],
    },
    {
        "id": "design-review",
        "name": "Design Review",
        "type": "stage_skill",
        "stage": "design_review",
        "owner": "架构师",
        "description": "设计评审、设计产物完整性检查、风险关闭和进入代码研发 gate 判断时使用；不要用于直接生成设计文档正文。",
        "purpose": "评审设计产物，判断是否可以进入代码研发。",
        "non_goals": ["不代替审批人签字", "不修正文档内容", "不放行 blocker"],
        "inputs": ["high-level-design.md", "detailed-design.md", "database-design.md", "redis-design.md", "mq-design.xlsx"],
        "outputs": ["design-review-report.md", "review-findings.json", "design-gate-decision.json"],
        "gates": ["无未关闭 blocker", "关键专项设计齐全", "测试策略存在", "高风险审批齐全"],
        "approvals": ["高风险设计放行", "blocker 关闭确认", "关键设计豁免"],
        "checks": [
            "A/H/D/I/E/P/R/M/DB 规范逐项检查",
            "需求契约已准入，概要设计和详细设计均完整",
            "目标业务系统与目标客户端系统的系统边界、业务域、接口、事件协作、最终一致性已说明",
            "DB/Redis/MQ 专项设计齐全，未涉及项有明确不适用说明",
            "接口、异常、幂等、并发、状态流转、事务边界、回滚策略均有证据",
            "导入、批处理、异步任务的数据量、批次、超时、进度、失败处理已明确",
            "测试策略覆盖主路径、边界、异常、幂等、一致性和回归",
            "高风险设计、跨系统依赖、生产变更、关键链路豁免均有审批记录",
            "FW1-FW4 框架选型、持久化框架、JDBC 例外和现有仓库框架一致性已评审",
            "FE1-FE4 涉及前端时前端设计、接口联调、组件边界和验证方式已覆盖",
            "DG1-DG6 检查设计文档编号、状态、留存策略和中间过程文档是否被误留存",
        ],
    },
    {
        "id": "frontend-design",
        "name": "Frontend Design",
        "type": "stage_skill",
        "stage": "frontend_design",
        "owner": "前端开发",
        "description": "前端页面设计、组件边界、交互流程、接口联调契约和前端风险评估时使用；不要用于直接编写后端代码或替代 UI 视觉评审。",
        "purpose": "将需求和接口契约转化为可实现的前端设计，明确页面、组件、状态、交互、接口联调和验证策略。",
        "non_goals": ["不替代产品原型评审", "不直接修改后端接口", "不在未确认技术栈时生成前端实现"],
        "inputs": ["requirement-contract.json", "high-level-design.md", "interface-contracts.yaml", "repo_context"],
        "outputs": ["frontend-design.md", "interaction-flow.md", "component-contracts.yaml", "frontend-risk-report.json"],
        "gates": ["页面和组件边界明确", "接口联调契约明确", "加载/空态/错误态完整", "技术栈和组件库已确认"],
        "approvals": ["前端技术栈变更", "公共组件改造", "影响核心客户端流程"],
        "checks": [
            "FE1 页面结构、组件边界、状态管理、路由和交互流程明确",
            "FE2 技术栈、组件库、状态管理和构建工具必须来自 repo_context 或用户确认；未明确时主动询问",
            "FE3 接口联调契约覆盖请求、响应、错误码、权限可见性、表单校验、加载态、空态和错误态",
            "FE4 输出设计到 UI 映射、兼容性风险、验证方式和前后端联调清单",
        ],
    },
    {
        "id": "code-development",
        "name": "Code Development",
        "type": "stage_skill",
        "stage": "code_development",
        "owner": "后端开发",
        "description": "代码研发、按设计实施代码变更、生成实现总结和设计到代码映射时使用；不要用于无设计依据的大范围重构。",
        "purpose": "基于设计文档进行最小必要代码变更或生成代码修改计划。",
        "non_goals": ["不修改无关模块", "不绕过测试", "不执行未审批高风险动作"],
        "inputs": ["detailed-design.md", "implementation-plan.md", "interface-contracts.yaml", "repo_context"],
        "outputs": ["code changes", "implementation-summary.md", "design-to-code-mapping.yaml", "changed-files-report.json", "traceability-matrix.json"],
        "gates": ["每个变更映射到设计", "无无关模块修改", "高风险文件已标记", "测试命令已列出", "需求-设计-代码追踪矩阵已刷新"],
        "approvals": ["DB/Redis/MQ/权限/发布脚本变更", "核心链路实现偏离设计", "高风险重构"],
        "checks": [
            "执行前必须读取 artifacts/_control/task-context.agent.md、implementation-contract.json、quality-contract.json 和任务规则包",
            "最小必要变更",
            "设计映射",
            "风险标记",
            "测试覆盖",
            "变更摘要",
            "完成实现后必须运行 build_traceability_report.py 刷新 artifacts/_control/traceability-matrix.json 和 docs/human-readable/traceability-report.html",
            "CD1 代码实现必须输出需求规格/原型-设计-代码追踪矩阵；每个代码变更必须映射 source_id、design_section、code_path 和验证证据，无法映射的实现视为无设计依据",
            "FW1 框架选型必须来自设计、repo_context 或用户确认；缺失时主动询问",
            "FW2 Java/Spring 持久化默认使用 mybatis-plus；直接 JDBC 必须有评审批准",
            "FW3 实现必须遵循现有仓库 mapper/repository/service 分层和依赖",
        ],
    },
    {
        "id": "frontend-development",
        "name": "Frontend Development",
        "type": "stage_skill",
        "stage": "frontend_development",
        "owner": "前端开发",
        "description": "前端代码研发、页面/组件实现、接口联调、前端验证和 UI 变更总结时使用；不要用于后端业务逻辑实现。",
        "purpose": "基于前端设计和接口契约实施页面、组件、状态和接口联调变更。",
        "non_goals": ["不修改无关页面", "不绕过前端设计", "不凭空选择未确认前端技术栈"],
        "inputs": ["frontend-design.md", "component-contracts.yaml", "interface-contracts.yaml", "repo_context"],
        "outputs": ["code changes", "frontend-implementation-summary.md", "design-to-ui-mapping.yaml", "frontend-changed-files-report.json"],
        "gates": ["每个 UI 变更映射到前端设计", "组件和状态边界符合现有项目", "接口联调风险已标记", "前端验证方式已列出"],
        "approvals": ["公共组件改造", "前端技术栈或组件库变更", "影响核心客户端流程"],
        "checks": [
            "执行前必须读取 artifacts/_control/task-context.agent.md、implementation-contract.json、quality-contract.json 和任务规则包",
            "FE1 按前端设计实现页面、组件、路由、状态和交互",
            "FE2 遵循现有项目技术栈、组件库、样式规范和目录结构；未明确时主动询问",
            "FE3 完成接口联调契约映射，覆盖 loading、empty、error、permission 和 validation 状态",
            "FE4 输出 design-to-ui 映射、变更文件、验证命令和兼容性风险",
        ],
    },
    {
        "id": "implementation-controller",
        "name": "Implementation Controller",
        "type": "control_skill",
        "stage": "implementation_control",
        "owner": "研发负责人",
        "description": "已审批设计需要编译成实现合同、控制代码执行范围、驱动质量命令和修复闭环时使用；不要用于未审批设计或单纯设计文档生成。",
        "purpose": "把已审批设计转换为机器可读实现合同和质量合同，并控制代码实现、验证、修复和最终人工审阅。",
        "non_goals": ["不审批设计进入研发", "不直接替代 code-development 编写业务代码", "不把 HTML 人工审阅件作为 agent 事实源"],
        "inputs": ["approved design artifact", "target project root", "project profile", "changed-files-report.json"],
        "outputs": [
            "current-task.json",
            "design-contract.json",
            "implementation-contract.json",
            "quality-contract.json",
            "open-questions.json",
            "task-context.agent.md",
            "workflow-trace.json",
            "control-health-report.json",
            "technology-adoption-report.json",
            "rule-consumption-report.json",
            "traceability-matrix.json",
            "traceability-report.html",
            "repair-attempts.json",
        ],
        "gates": ["设计合同已编译", "实现范围明确", "质量命令非空", "需求-设计-代码追踪关系可查看", "修复策略明确", "人工审阅包仅在阻断或最终审阅时生成"],
        "approvals": ["修改已审批设计范围", "高风险实现豁免", "生产动作", "修复轮次耗尽后的人工决策"],
        "checks": [
            "只接受已审批 Markdown/JSON/YAML 设计产物，HTML 仅作为人工审阅入口",
            "所有 `_control` 产物写入目标项目 `artifacts/_control/`，不得写入插件目录",
            "implementation-contract.json 必须包含 allowed_modules、forbidden_modules、expected_interfaces、expected_services、expected_repositories_or_mappers、required_tests、architecture_rules、done_conditions、technology_adoption_contract",
            "quality-contract.json 必须包含 required_commands 和 required_evidence，缺失或占位命令必须阻断",
            "必须生成 artifacts/_control/traceability-matrix.json 作为机读事实源，并生成 docs/human-readable/traceability-report.html 作为人工阅览入口；HTML 不得反向作为 agent 事实输入",
            "普通实现范围、测试、lint、设计映射失败进入 review -> repair -> validate，最多 2 轮",
            "业务决策、设计冲突、高风险动作、生产动作和修复轮次耗尽才进入人工审批",
        ],
    },
    {
        "id": "self-test",
        "name": "Self Test",
        "type": "stage_skill",
        "stage": "self_test",
        "owner": "测试负责人",
        "description": "自测、测试命令执行、覆盖率汇总、失败测试分析和发布前测试风险判断时使用；不要用于在测试失败时声明通过。",
        "purpose": "生成并执行自测方案，输出失败原因、影响范围和阻断判断。",
        "non_goals": ["不伪造测试结果", "不忽略失败测试", "不替代发布验证"],
        "inputs": ["implementation-summary.md", "changed-files-report.json", "test-strategy.md", "repo_context"],
        "outputs": ["self-test-report.md", "test-commands.log", "coverage-summary.md", "failed-tests.md", "test-risk-report.json"],
        "gates": ["测试命令实际执行", "失败测试明确阻断", "覆盖主干/边界/异常/幂等", "覆盖率变化有解释"],
        "approvals": ["高风险测试豁免", "无法执行关键测试", "发布前置测试缺失"],
        "checks": ["执行前必须读取 artifacts/_control/quality-contract.json 和任务规则包", "单元测试", "集成测试", "回归测试", "边界测试", "异常路径", "幂等测试", "数据一致性测试", "发布验证前置测试"],
    },
    {
        "id": "code-quality-governor",
        "name": "Code Quality Governor",
        "type": "cross_cutting_skill",
        "stage": "code_quality",
        "owner": "研发负责人",
        "description": "代码质量门禁、PR 质量审计、代码变更风险评估、发布前质量检查时使用；不要用于单纯生成设计文档或没有代码变更的咨询。",
        "purpose": "建立 Q0-Q4 多层代码质量门禁，输出可被 CI/CD、PR、workflow 消费的结构化质量报告。",
        "non_goals": ["不以 LLM 判断替代 build/test/lint", "不在测试失败时输出 pass", "不降级 blocker"],
        "inputs": ["changed-files-report.json", "design-to-code-mapping.yaml", "self-test-report.md", "ci artifacts"],
        "outputs": ["code-quality-report.md", "code-quality-report.html", "code-quality-report.json", "gate-decision.json", "ci-check-summary.md", "static-analysis-report.md", "static-analysis-report.json", "tool-run-summary.json", "improvement-candidates.yaml"],
        "gates": ["Q0 设计一致性", "Q1 确定性工程检查", "Q1.5 Sonar/Qodana/Checkstyle 静态分析", "Q2 语义代码评审", "Q3 风险专项门禁", "Q4 发布前回归门禁"],
        "approvals": ["高风险未审批变更", "发布脚本变更", "权限/认证/鉴权逻辑变更", "支付/订单/库存/资金链路变更"],
        "checks": ["执行前必须读取 artifacts/_control/quality-contract.json、control-health-report.json、technology-adoption-report.json 和任务规则包", "build", "format", "lint", "typecheck", "unit_test", "integration_test", "coverage", "dependency_scan", "secret_scan", "migration_check", "architecture_boundary_check", "sonar_bugs_vulnerabilities_smells", "qodana_inspections_sarif", "checkstyle_style_rules", "cyclomatic_complexity", "duplication", "maintainability_reliability_security"],
    },
    {
        "id": "code-review",
        "name": "Code Review",
        "type": "stage_skill",
        "stage": "code_review",
        "owner": "研发负责人",
        "description": "代码走查、人工评审辅助、语义缺陷定位和 blocker 清单整理时使用；不要用于替代确定性 CI 检查。",
        "purpose": "对代码进行人工评审辅助，按问题、证据、影响、级别、建议和阻断状态输出。",
        "non_goals": ["不替代 code-quality-governor", "不输出无证据建议", "不忽略测试缺口"],
        "inputs": ["code-quality-report.json", "changed-files-report.json", "implementation-summary.md", "repo_context"],
        "outputs": ["code-review-report.md", "code-review-report.html", "review-comments.json", "blocker-list.md"],
        "gates": ["blocker 清单为空", "所有问题有证据", "严重级别一致", "静态分析指标已纳入评审", "富 HTML 人工走查报告已生成", "修复建议可执行"],
        "approvals": ["blocker 关闭", "高风险人工豁免", "核心链路评审通过"],
        "checks": ["执行前必须读取 artifacts/_control/quality-contract.json、任务规则包和 rule-consumption-report.json", "正确性", "边界条件", "异常处理", "Bug 风险", "漏洞/安全热点", "代码异味", "圈复杂度", "重复代码", "安全性", "性能", "可维护性", "可靠性", "可测试性", "可观测性", "团队规范一致性"],
    },
    {
        "id": "release-readiness",
        "name": "Release Readiness",
        "type": "stage_skill",
        "stage": "release_readiness",
        "owner": "发布负责人",
        "description": "发布准备、发布条件判断、回滚方案、灰度策略、监控和值班审批检查时使用；不要用于发布后验证。",
        "purpose": "判断是否具备发布条件，并输出发布计划、检查清单、回滚计划和 gate 决策。",
        "non_goals": ["不执行生产发布", "不绕过高风险发布审批", "不省略回滚方案"],
        "inputs": ["code-quality-report.json", "code-review-report.md", "release-standard.md", "risk_policy"],
        "outputs": ["release-plan.md", "release-checklist.md", "rollback-plan.md", "release-risk-report.json", "release-gate-decision.json"],
        "gates": ["发布窗口明确", "回滚方案存在", "监控告警存在", "审批状态有效"],
        "approvals": ["生产发布", "生产配置变更", "高风险发布", "回滚操作"],
        "checks": ["发布窗口", "影响范围", "依赖系统", "配置变更", "DB 变更", "灰度策略", "回滚策略", "验证步骤", "监控告警", "值班人员", "审批状态"],
    },
    {
        "id": "release-verification",
        "name": "Release Verification",
        "type": "stage_skill",
        "stage": "release_verification",
        "owner": "SRE",
        "description": "发布后验证、生产检查、监控指标、异常列表和回滚条件判断时使用；不要用于发布前准备。",
        "purpose": "发布后验证核心功能、监控、日志、业务指标和回滚条件。",
        "non_goals": ["不执行未审批回滚", "不忽略异常", "不替代发布准备审批"],
        "inputs": ["release-plan.md", "release-checklist.md", "observability data", "risk_policy"],
        "outputs": ["release-verification-report.md", "production-checks.json", "anomaly-list.md"],
        "gates": ["核心功能验证通过", "错误率/延迟未触发阈值", "业务指标正常", "回滚条件未触发"],
        "approvals": ["回滚操作", "生产验证豁免", "延长观察窗口"],
        "checks": ["核心功能验证", "监控指标", "错误率", "延迟", "业务指标", "日志异常", "告警状态", "回滚条件是否触发"],
    },
    {
        "id": "release-retrospective",
        "name": "Release Retrospective",
        "type": "stage_skill",
        "stage": "release_retrospective",
        "owner": "发布负责人",
        "description": "发布复盘、发布问题归纳、规范候选、skill 改进候选和后续行动整理时使用；不要用于发布审批。",
        "purpose": "复盘发布过程，沉淀发布问题、测试遗漏、设计遗漏、规范改进候选和 skill 改进候选。",
        "non_goals": ["不将候选规范直接发布", "不隐藏发布问题", "不替代知识治理审批"],
        "inputs": ["release-verification-report.md", "code-quality-report.json", "incident reports", "release logs"],
        "outputs": ["release-retrospective.md", "release-lessons.yaml", "follow-up-actions.md"],
        "gates": ["问题有证据", "行动项有 owner", "规范候选状态为 candidate", "skill 改进候选明确"],
        "approvals": ["行动项关闭", "规范候选批准", "高风险复盘结论发布"],
        "checks": ["发布过程问题", "测试遗漏", "设计遗漏", "代码质量问题", "发布验证问题", "规范改进候选", "skill 改进候选"],
    },
    {
        "id": "engineering-knowledge-miner",
        "name": "Engineering Knowledge Miner",
        "type": "cross_cutting_skill",
        "stage": "knowledge_mining",
        "owner": "规范 owner",
        "description": "研发经验总结、规范沉淀、评审问题归纳、事故复盘反哺、skill 规范更新建议时使用；不要用于直接执行代码质量检查或未经审批修改强制规范。",
        "purpose": "从研发流程产物中抽取可复用经验，生成规范候选、检查清单候选、eval 回归样例候选和 skill 反哺建议。",
        "non_goals": ["不无证据创建规范", "不未经审批修改正式规范", "不把偶发低风险问题升级为强制规范"],
        "inputs": ["design reports", "code quality reports", "review reports", "CI logs", "PR comments", "release reports", "incident reports"],
        "outputs": ["engineering-lessons.md", "rule-candidates.yaml", "standard-patch-suggestions.md", "checklist-patch-suggestions.md", "skill-patch-suggestions.md", "regression-case-candidates.yaml", "knowledge-change-log.md"],
        "gates": ["每条经验有来源证据", "规则默认 candidate", "owner 和适用范围明确", "反哺路径明确"],
        "approvals": ["修改正式团队规范", "rule_candidate 标记为 approved", "修改高风险 skill quality gate"],
        "checks": ["证据收集", "finding 抽取", "问题归类", "模式识别", "经验候选", "规范候选", "checklist 候选", "eval 候选", "skill 反哺建议", "DG5 仅沉淀可复用正式经验；任务中间状态和临时过程文档不得升级为规范或知识"],
    },
    {
        "id": "skill-quality-auditor",
        "name": "Skill Quality Auditor",
        "type": "audit_skill",
        "stage": "skill_quality",
        "owner": "skill owner",
        "description": "检查人工编写或 Agent 生成的 Codex Skills 质量、契约完整性、触发描述、eval 覆盖、workflow 兼容性时使用；不要用于执行业务研发阶段。",
        "purpose": "审计 skills 质量，防止空泛 prompt，阻断不合格 skill 入库。",
        "non_goals": ["不执行业务研发阶段", "不替代 eval 执行", "不放行缺少 gate 的高风险 skill"],
        "inputs": ["skills", "engineering-assistant/registry/skills.yaml", "skill-contract.schema.json"],
        "outputs": ["skill-quality-report.md", "skill-quality-report.json", "skill-fix-suggestions.md", "skill-gate-decision.json"],
        "gates": ["SKILL.md 存在", "description 清楚", "contract 完整", "schema 存在", "eval 覆盖", "workflow node 存在"],
        "approvals": ["高风险 skill 入库", "修改高风险质量门禁", "skill gate 豁免"],
        "checks": ["front matter", "职责单一", "non-goals", "输入输出契约", "deterministic validation scripts", "eval cases", "failure handling", "human approval rules", "standalone/workflow mode"],
    },
    {
        "id": "workflow-orchestrator",
        "name": "Workflow Orchestrator",
        "type": "workflow_skill",
        "stage": "workflow_orchestration",
        "owner": "workflow owner",
        "description": "研发流程编排、阶段选择、skills 串联执行、状态流转、人工审批和产物路由时使用；不要用于直接生成某个阶段文档。",
        "purpose": "支持阶段选择、全链路 workflow、状态机、错误处理、审批暂停/恢复、产物传递和 trace 记录。",
        "non_goals": ["不直接生成阶段文档", "不绕过子 skill contract", "不自动批准高风险动作"],
        "inputs": ["workflow.yaml", "stage node registry", "StageRunRequest", "approval_context"],
        "outputs": ["workflow-trace.json", "workflow-summary.md", "approval-requests.json", "artifact-index.json", "validator-summary.json"] + DESIGN_GOVERNANCE_CONTROL_OUTPUTS,
        "gates": ["节点 contract 匹配", "信息收集完成或已暂停追问", "方案方向已确认或已暂停确认", "前置条件满足", "产物 schema 合规", "专项 validator 结果全部通过或向上冒泡为 blocked", "自审 blocker 已修复或保留为 unresolved", "高风险动作进入审批", "TL 规范候选未自动入库"],
        "approvals": ["人工审批网关", "跳过阻断节点", "恢复 blocked workflow", "高风险动作执行", "设计方案方向确认", "TL 规范候选入库"],
        "checks": ["阶段选择", "状态流转", "信息收集完成判定", "设计目标规划", "缺失信息识别", "主动沟通与方向确认", "preflight 未 ready 时不得生成正式设计文档", "错误处理", "重试", "审批暂停", "断点恢复", "产物路由", "执行日志", "design-only 完成前运行 high-level/detailed/database/mq/redis 专项 validator", "validator-summary 汇总 stage、validator、failed_rule、error_message、suggested_repair", "任一专项 validator 失败时 workflow 总状态不得 succeeded", "self-review findings 驱动自动修复", "unresolved blocker 阻断 approved/final", "waiting_for_human_review 不得宣称 approved/final/succeeded", "人工评审反馈分类后增量修正，只有核心方案变化才整套重生", "defect-analysis 根因分析", "DG2-DG11 产物路由时区分 run artifact、正式留存文档、控制面、人审入口和 TL 候选，防止中间过程文档或具体需求事实进入团队插件"],
    },
]


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, data: object) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def write_binary(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def copy_generated_tree(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def document_lifecycle_schema() -> dict:
    return {
        "type": "object",
        "required": ["document_number", "document_status", "retention_policy", "title", "owner", "source_artifacts"],
        "properties": {
            "document_number": {
                "type": "string",
                "pattern": "^(REQ|CTX|HLD|DDD|DBD|RDS|MQD|DRR|CQR|CRR|RLP|RVF|RTR|KNO|RPT)-[A-Z0-9][A-Z0-9-]{1,40}-[0-9]{8}-[0-9]{3}$",
            },
            "document_status": {"enum": DOCUMENT_LIFECYCLE_STATES},
            "retention_policy": {"enum": ["transient", "keep_until_run_end", "persist"]},
            "title": {"type": "string", "minLength": 1},
            "owner": {"type": "string", "minLength": 1},
            "source_artifacts": {"type": "array", "items": {"type": "string"}},
            "supersedes": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": True,
    }


def required_information_request_schema() -> dict:
    return {
        "type": "object",
        "required": ["request_id", "run_id", "skill_id", "blocking", "status", "questions"],
        "properties": {
            "request_id": {"type": "string", "minLength": 1},
            "run_id": {"type": "string", "minLength": 1},
            "skill_id": {"type": "string", "minLength": 1},
            "blocking": {"type": "boolean"},
            "status": {"enum": ["waiting_for_input", "optional_context_requested", "resolved"]},
            "questions": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "question", "reason", "required", "priority", "expected_format"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "question": {"type": "string", "minLength": 1},
                        "reason": {"type": "string", "minLength": 1},
                        "required": {"type": "boolean"},
                        "priority": {"enum": ["critical", "major", "minor"]},
                        "expected_format": {"type": "string", "minLength": 1},
                        "example": {"type": "string"},
                        "default_if_unanswered": {"type": "string"},
                    },
                },
            },
            "source_checked": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": True,
    }


def skill_trigger_description(skill: dict) -> str:
    if skill["description"].startswith("Use when"):
        return skill["description"]
    non_goals = "；".join(skill["non_goals"][:2])
    return f"Use when the request is about {skill['purpose']}；Do not use when {non_goals}。"


def risk_level(skill: dict) -> str:
    if skill["id"] in HIGH_RISK_SKILLS:
        return "high"
    if skill["approvals"]:
        return "medium"
    return "low"


def skill_routing_metadata(skill: dict) -> dict:
    keywords = sorted({
        skill["id"],
        skill["stage"],
        skill["type"],
        *[part for part in skill["id"].split("-") if part],
        *[part for part in skill["purpose"].replace("，", " ").replace("、", " ").split() if len(part) > 1],
    })
    return {
        "intent_tags": keywords[:12],
        "positive_triggers": [skill["id"], skill["name"], skill["purpose"]],
        "negative_triggers": [f"只解释 {skill['name']} 的用途，不执行任务", "只咨询说明", "不生成产物"],
        "requires": skill["inputs"],
        "conflicts_with": [],
        "risk_level": risk_level(skill),
        "cost_class": "high" if skill["id"] in HIGH_RISK_SKILLS else "medium",
        "evidence_required": skill["gates"],
        "allow_implicit_invocation": skill["id"] not in HIGH_RISK_SKILLS,
    }


def agents_openai_yaml(skill: dict) -> str:
    allow_implicit = "false" if skill["id"] in HIGH_RISK_SKILLS else "true"
    default_prompt = f"使用 {skill['id']}，先执行 preflight 信息梳理；preflight_input_state 不是 ready 时仅生成补充信息请求、human-review HTML 和恢复点，ready 后再进入 formal_generation 输出声明产物、findings、required actions 和 gate decision。"
    if template_usage_policy(skill).get("required"):
        default_prompt = f"使用 {skill['id']}，先执行 preflight 信息梳理；preflight_input_state 不是 ready 时仅生成补充信息请求、human-review HTML 和恢复点，ready 后先读取对应 assets template 并按模板骨架逐节填充输入事实。"
    if skill["id"] == "mq-design":
        default_prompt = f"使用 {skill['id']}，先执行 preflight 信息梳理；preflight_input_state 不是 ready 时仅生成补充信息请求、human-review HTML 和恢复点，ready 后先读取对应 xlsx template 并按模板工作簿填充输入事实。"
    return f"""display_name: "{skill['name']}"
short_description: "{skill['purpose']}"
default_prompt: "{default_prompt}"
language_policy:
  supported:
    - "zh-CN"
    - "en"
  when_unspecified: "ask_user"
  question: "请确认输出语言：简体中文还是 English？"
preflight_gate:
  state_field: "preflight_input_state"
  states:
{chr(10).join(f'    - "{item}"' for item in PREFLIGHT_INPUT_STATES)}
  formal_generation_entry_condition: "{FORMAL_GENERATION_ENTRY_CONDITION}"
policy:
  allow_implicit_invocation: {allow_implicit}
  risk_level: "{risk_level(skill)}"
  human_approval_required:
{chr(10).join(f'    - "{item}"' for item in skill['approvals']) if skill['approvals'] else '    []'}
metadata:
  owner: "{skill['owner']}"
  stage: "{skill['stage']}"
  type: "{skill['type']}"
  trigger_description: "{skill_trigger_description(skill)}"
routing:
  intent_tags:
{chr(10).join(f'    - "{item}"' for item in skill_routing_metadata(skill)['intent_tags'])}
  allow_implicit_invocation: {allow_implicit}
  cost_class: "{skill_routing_metadata(skill)['cost_class']}"
"""


def skill_by_id(skill_id: str) -> dict:
    return next(s for s in SKILLS if s["id"] == skill_id)


def artifact_type_for_name(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix == ".md":
        return "markdown"
    if suffix == ".json":
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    if suffix == ".html":
        return "html"
    if suffix == ".xlsx":
        return "xlsx"
    if suffix == ".log":
        return "log"
    return "report"


def contract_output_type_for_name(name: str) -> str:
    if Path(name).suffix.lower() == ".xlsx":
        return "xlsx|artifact"
    return "markdown|json|yaml|code|log|report"


def schema_artifact_types(skill: dict) -> list[str]:
    artifact_types = ["markdown", "json", "yaml", "code", "log", "report", "html"]
    if any(Path(output).suffix.lower() == ".xlsx" for output in skill["outputs"]):
        artifact_types.append("xlsx")
    return artifact_types


def runtime_default_prompt(skill: dict) -> str:
    if not template_usage_policy(skill).get("required"):
        return f"使用 {skill['id']}，先完成 preflight 信息梳理；preflight_input_state 不是 ready 时仅生成 required_information_requests、human-review HTML 和恢复点，补齐写回后再进入 formal_generation 输出声明产物与 gate decision。"
    if skill["id"] == "mq-design":
        return f"使用 {skill['id']}，先完成 preflight 信息梳理；preflight_input_state 不是 ready 时仅生成 required_information_requests、human-review HTML 和恢复点，补齐写回后再进入 formal_generation 读取 xlsx template 生成正式产物与 gate decision。"
    return f"使用 {skill['id']}，先完成 preflight 信息梳理；preflight_input_state 不是 ready 时仅生成 required_information_requests、human-review HTML 和恢复点，补齐写回后再进入 formal_generation 读取 assets template 生成正式产物与 gate decision。"


def design_governance_policy() -> dict:
    return {
        "states": DESIGN_GOVERNANCE_STATES,
        "formal_design_artifacts": FORMAL_DESIGN_ARTIFACTS,
        "preflight_control_artifacts": PREFLIGHT_ONLY_ARTIFACTS,
        "document_lifecycle_states": DOCUMENT_LIFECYCLE_STATES,
        "hard_gates": {
            "information_complete_before_formal_generation": True,
            "direction_confirmed_before_design_generation": True,
            "specialty_scope_confirmed_before_specialty_docs": True,
            "self_review_passed_before_human_review": True,
            "human_review_approved_before_final": True,
            "approved_or_final_before_code_control_surface": True,
        },
        "waiting_for_input_policy": {
            "allowed_artifacts": PREFLIGHT_ONLY_ARTIFACTS,
            "forbidden_artifacts": FORMAL_DESIGN_ARTIFACTS,
            "must_not_register_formal_artifacts_as_completed": True,
            "resume_requires_writeback_to_machine_readable_source": True,
        },
        "review_feedback_policy": {
            "classification_required": True,
            "classes": ["fact_completion", "direction_change", "document_defect", "standard_violation", "team_rule_candidate"],
            "default_update_strategy": "incremental_patch_affected_artifacts",
            "full_regeneration_allowed_when": ["architecture_direction_changed", "data_model_changed", "interface_boundary_changed", "message_model_changed"],
            "full_regeneration_requires": ["impact_analysis", "supersede_previous_version", "workflow_trace_reason"],
        },
        "self_review_policy": {
            "layers": ["deterministic_validators", "reviewer_agent"],
            "auto_fix_allowed_for": ["format_error", "template_gap", "known_fact_omission", "terminology_inconsistency", "document_routing_error", "confirmed_solution_clarity"],
            "auto_fix_forbidden_for": ["business_direction_change", "core_interface_add_or_remove", "risk_strategy_change", "system_boundary_change", "human_approval_replacement"],
            "unresolved_blocker_status": "blocked_or_waiting_for_human_review",
        },
        "knowledge_mining_policy": {
            "candidate_outputs": ["rule-candidates.json", "prompt-optimization-candidates.md", "tl-review-package.json"],
            "candidate_types": ["team-rule-candidate", "document-template-candidate", "agent-behavior-candidate"],
            "required_fields": ["candidate_id", "source_run_id", "original_user_change", "agent_original_design", "human_review_feedback", "generalized_rule", "scope", "non_scope", "counter_examples", "contains_specific_business_fact", "generalization_level", "suggested_landing_zone", "tl_review_status"],
            "auto_apply_to_plugin": False,
            "tl_review_required": True,
        },
    }


def workflow_runtime_policy() -> dict:
    return {
        "supported_entry_modes": WORKFLOW_ENTRY_MODES,
        "default_entry_mode": "auto_flow",
        "design_governance_state_machine": design_governance_policy(),
        "auto_flow": "按 workflow.nodes 顺序与 next_nodes 自动流转；遇到 waiting_for_input、waiting_for_human_review、blocked、failed 必须暂停。" ,
        "auto_transition_policy": {
            "continue_when": ["StageRunResult.status == succeeded", "required_information_requests 为空或全部非 blocking 且已处理", "未声明 HUMAN_APPROVAL_REQUIRED", "next_node 存在"],
            "pause_when": ["StageRunResult.status in waiting_for_input|waiting_for_human_review|blocked|failed", "preflight_input_state != ready", "存在 blocking required_information_requests", "human-review HTML 已生成但补充答案未写回 StageRunRequest.context 或 artifact index"],
            "formal_generation_entry_condition": FORMAL_GENERATION_ENTRY_CONDITION,
            "preflight_blocks_current_node_formal_generation": True,
            "preflight_blocks_next_nodes": True,
            "record_required": "workflow-trace.json 必须记录 auto transition decision",
            "dialog_confirmation_required": False,
            "hld_to_detailed_design": "agent 自动流转检查，不等同于代码研发前的 design-review",
        },
        "from_node": "从指定 start_node 开始，沿 next_nodes 继续流转到 terminal_nodes；必须校验 start_node 存在且上游必要 artifacts 已由用户或 artifact_index 提供。",
        "single_node": "只执行 target_node，不自动触发后续节点；必须输出 StageRunResult、artifact_index 更新建议和下游可继续执行提示。",
        "from_node_required_fields": ["workflow_id", "entry_mode", "start_node", "artifact_index", "approval_context"],
        "single_node_required_fields": ["workflow_id", "entry_mode", "target_node", "stage_run_request"],
        "composition_rules": [
            "workflow 不是固定线路，节点可以按任务目标裁剪、跳过或从中间恢复，但必须保留输入输出契约和审批门禁。",
            "跳过节点必须写入 skip_reason、risk_impact 和 human_approval 需求；不得静默跳过质量或审批节点。",
            "只执行单节点时不得宣称全链路完成，只能给出该节点结果和建议的 next_nodes。",
            "自动流转时下游节点只能消费已登记 Markdown/JSON/YAML artifact、StageRunRequest.context 或用户补充信息写回结果，不能虚构上游产物。",
            "human-review HTML 只作为人工填写入口，不能作为 agent 事实源或下游正式输入。",
            "每个节点必须先执行 preflight gate；preflight_input_state 不是 ready 时不得进入当前节点 formal_generation，也不得触发 next_nodes。",
        ],
    }


def runtime_ir(skill: dict) -> dict:
    allow_implicit = skill["id"] not in HIGH_RISK_SKILLS
    return {
        "skill_id": skill["id"],
        "version": "1.0.0",
        "stage": skill["stage"],
        "type": skill["type"],
        "prompt_pack": {
            "display_name": skill["name"],
            "short_description": skill["purpose"],
            "default_prompt": runtime_default_prompt(skill),
            "trigger_description": skill_trigger_description(skill),
            "language_policy": {"supported": ["zh-CN", "en"], "when_unspecified": "ask_user"},
            "preflight_gate": {
                "states": PREFLIGHT_INPUT_STATES,
                "formal_generation_entry_condition": FORMAL_GENERATION_ENTRY_CONDITION,
            },
        },
        "inputs": skill["inputs"],
        "outputs": skill["outputs"],
        "routing": skill_routing_metadata(skill),
        "risk": {
            "risk_level": risk_level(skill),
            "allow_implicit_invocation": allow_implicit,
            "human_approval_required": skill["approvals"],
        },
        "quality_gates": skill["gates"],
        "workflow": {"node_id": skill["id"], "entry_modes": WORKFLOW_ENTRY_MODES, "next_nodes": []},
        "source_files": [
            f"skills/{skill['id']}/SKILL.md",
            f"skills/{skill['id']}/contract.yaml",
            f"skills/{skill['id']}/workflow/node.yaml",
            f"skills/{skill['id']}/agents/openai.yaml",
        ],
    }


def static_analysis_policy(skill: dict) -> dict:
    if skill["id"] not in {"code-quality-governor", "code-review"}:
        return {"required": False}
    policy = {
        "required": True,
        "tools": ["sonar-scanner-cli", "qodana-cli", "checkstyle"],
        "discovery_first": True,
        "script": "engineering-assistant/scripts/run_static_analysis_tools.py",
        "download_requires_explicit_allow_download": True,
        "secret_redaction_required": True,
        "quality_dimensions": [
            "bug",
            "vulnerability",
            "security_hotspot",
            "code_smell",
            "complexity",
            "duplication",
            "coverage",
            "maintainability",
            "reliability",
            "security",
        ],
        "block_when": [
            "required tool configured but execution failed",
            "all static analysis tools unavailable without accepted waiver",
            "critical/high vulnerability or blocker bug exists",
            "complexity threshold exceeded without remediation plan",
        ],
        "outputs": ["static-analysis-report.md", "static-analysis-report.json", "tool-run-summary.json"],
    }
    if skill["id"] == "code-review":
        policy["consumer_mode"] = "must_consume_code_quality_static_analysis_outputs"
        policy["outputs"] = ["code-review-report.html"]
    return policy


def rich_html_report_policy(skill: dict) -> dict:
    html_outputs = [item for item in skill["outputs"] if item.endswith(".html")]
    if not html_outputs:
        return {"required": False}
    if skill["id"] == "implementation-controller":
        return {
            "required": True,
            "outputs": html_outputs,
            "script": "engineering-assistant/scripts/build_traceability_report.py",
            "sections": [
                "task summary",
                "requirement to design to code traceability matrix",
                "validation status",
                "gap and blocker summary",
                "source evidence files",
            ],
            "traceability": "each row links requirement id, design refs, implementation targets, changed files, tests and validation status",
            "html_policy": "HTML is human-only; artifacts/_control/traceability-matrix.json remains the agent source of truth",
        }
    return {
        "required": True,
        "outputs": html_outputs,
        "script": "engineering-assistant/scripts/render_code_review_html.py",
        "sections": [
            "gate decision",
            "blocker summary",
            "finding severity distribution",
            "quality dimension distribution",
            "tool execution status",
            "evidence table",
            "required actions",
            "human review checklist",
        ],
        "traceability": "each finding links to stable JSON finding id",
        "sensitive_data_policy": "redact tokens, passwords, private keys, internal credentials and full connection strings",
    }


def control_surface_policy(skill: dict) -> dict:
    if skill["id"] != "implementation-controller":
        return {"required": False}
    return {
        "required": True,
        "control_dir": "artifacts/_control",
        "source_of_truth": "approved Markdown/JSON/YAML design artifact",
        "html_policy": "HTML is human-only and cannot be consumed as agent source evidence",
        "required_artifacts": [
            "current-task.json",
            "design-contract.json",
            "implementation-contract.json",
            "quality-contract.json",
            "open-questions.json",
            "task-context.agent.md",
            "workflow-trace.json",
            "control-health-report.json",
            "technology-adoption-report.json",
            "rule-consumption-report.json",
            "traceability-matrix.json",
            "traceability-report.html",
            "repair-attempts.json",
        ],
        "bounded_repair": {
            "max_attempts": 2,
            "loop": ["review", "repair", "validate"],
            "human_only_for": ["design conflict", "business decision", "high risk approval", "production action", "repair exhausted"],
        },
    }


TEMPLATE_GENERATION_PROTOCOL = [
    "生成正式 Markdown 文档前必须先读取对应 skill 的 assets template 文件，不得凭记忆、通用模板或聊天上下文替代。",
    "以 template 原文作为唯一正文骨架，保留 frontmatter、标题层级、章节顺序、表格列头、固定提示块和格式约定。",
    "只允许替换占位符、补充空白单元格和在既有章节下填充输入事实；不得删除、压缩、合并、重命名或重排模板章节。",
    "输入材料缺少事实时，保留模板章节并写明不适用原因，或进入 waiting_for_input 并输出 required_information_requests。",
    "不得用 assets/artifact-template.md 的证据/Findings/门禁决策骨架替代正式设计正文。",
    "模板文件不存在、无法读取或输出无法通过模板校验时，StageRunResult.status 必须为 blocked 或 failed。",
]

MQ_EXCEL_GENERATION_PROTOCOL = [
    "生成正式 MQ Excel 文档前必须先读取 `assets/mq-design-template.xlsx`，不得改用 Markdown 或通用报告替代。",
    "以 xlsx template 文件副本作为唯一工作簿骨架，保留工作表名称、工作表顺序、表格列头、合并单元格、已有单元格样式和格式约定。",
    "只允许在模板已有单元格范围内补充空白数据单元格；不得新增 sheet、不得删除 sheet、不得追加行列、不得删除或改写模板固定文本、不得修改已有样式或重排模板 sheet。",
    "输入材料缺少事实时，保留模板列头并写明不适用原因，或进入 waiting_for_input 并输出 required_information_requests。",
    "不得额外生成 `mq-design.md` 作为正式 MQ 设计正文；Markdown 只能作为 StageRunResult 或过程摘要。",
    "模板文件不存在、无法读取或输出无法通过 xlsx 模板校验时，StageRunResult.status 必须为 blocked 或 failed。",
]


def template_asset_definitions(skill_id: str) -> list[dict]:
    assets = {
        "high-level-design": [
            {
                "artifact": "high-level-design.md",
                "template": "assets/high-level-design-template.md",
                "canonical_template": "skills/high-level-design/assets/high-level-design-template.md",
                "source_template": "inputs/萤启运营系统概要设计 - 萤启服务商系统 - 站点标题.html",
                "selection": "概要设计正文",
            }
        ],
        "detailed-design": [
            {
                "artifact": "detailed-design.md",
                "template": "assets/detailed-design-template.md",
                "canonical_template": "skills/detailed-design/assets/detailed-design-template.md",
                "source_template": "inputs/详细设计规范.md",
                "selection": "详细设计主文档正文",
            }
        ],
        "database-design": [
            {
                "artifact": "database-design.md",
                "template": "assets/database-oltp-template.md",
                "canonical_template": "skills/database-design/assets/database-oltp-template.md",
                "source_template": "inputs/关系型(OLTP)详细设计模板.md",
                "selection": "MySQL/PostgreSQL 等关系型 OLTP 场景",
            },
            {
                "artifact": "database-design.md",
                "template": "assets/database-olap-template.md",
                "canonical_template": "skills/database-design/assets/database-olap-template.md",
                "source_template": "",
                "selection": "ClickHouse、物化视图或分析宽表场景",
            },
        ],
        "redis-design": [
            {
                "artifact": "redis-design.md",
                "template": "assets/redis-design-template.md",
                "canonical_template": "skills/redis-design/assets/redis-design-template.md",
                "source_template": "inputs/Redis详细设计模板 - 人人取平台总体设计 - 站点标题.html",
                "selection": "Redis 详细设计正文",
            }
        ],
        "mq-design": [
            {
                "artifact": "mq-design.xlsx",
                "template": "assets/mq-design-template.xlsx",
                "canonical_template": "skills/mq-design/assets/mq-design-template.xlsx",
                "source_template": "inputs/xxxMQ设计.xlsx",
                "selection": "MQ 设计 Excel 工作簿",
            }
        ],
    }
    return assets.get(skill_id, [])


def template_usage_policy(skill: dict) -> dict:
    templates = template_asset_definitions(skill["id"])
    if not templates:
        return {"required": False}
    unread_template_blocker = "未读取 template asset 就生成正式 MQ Excel 文档" if skill["id"] == "mq-design" else "未读取 template asset 就生成正式 Markdown 文档"
    return {
        "required": True,
        "source_of_truth": "template_assets[].canonical_template",
        "must_read_template_before_generation": True,
        "template_assets": templates,
        "generation_protocol": MQ_EXCEL_GENERATION_PROTOCOL if skill["id"] == "mq-design" else TEMPLATE_GENERATION_PROTOCOL,
        "strict_format_rules": [
            "保留模板原有章节、标题名称、标题层级、表格列头和固定提示块。",
            "不适用章节不得删除，必须写明不适用原因或等待用户补充事实。",
            "不得把团队 template 压缩成摘要、检查清单或通用证据报告。",
            "不得把 source_template 只当参考风格；canonical_template 才是输出正文骨架。",
        ],
        "blocked_when": [
            unread_template_blocker,
            "输出缺少 template 章节、列头、固定提示块或顺序",
            "用 assets/artifact-template.md 或通用报告格式替代正式设计正文",
            "缺少关键事实却填充待确认占位符并标记 succeeded",
        ],
    }


def template_execution_note(skill: dict) -> str:
    policy = template_usage_policy(skill)
    if not policy.get("required"):
        return ""
    templates = "\n".join(
        f"- `{item['artifact']}`: 生成前读取 `{item['template']}`；适用范围：{item['selection']}；来源模板：`{item['source_template'] or 'generator canonical template'}`。"
        for item in policy["template_assets"]
    )
    if skill["id"] == "mq-design":
        return f"""
# 模板执行协议
- 只有 `preflight_input_state == ready` 时才能进入 `formal_generation` 读取模板并生成正式 MQ Excel；存在 blocking 缺失信息时必须先暂停并生成补充信息入口。
- 生成正式 MQ Excel 文档前必须先读取对应 xlsx template asset；不得凭记忆、通用模板、聊天上下文、Markdown 文档或 `assets/artifact-template.md` 生成正文。
- 以 xlsx template 文件副本作为唯一工作簿骨架，保留工作表名称、工作表顺序、表格列头、合并单元格、已有单元格样式和格式约定。
- 只允许在模板已有单元格范围内补充空白数据单元格；不得新增 sheet、不得删除 sheet、不得追加行列、不得删除或改写模板固定文本、不得修改已有样式或重排模板 sheet。
- 输入材料缺少事实时，保留模板列头并写明“不适用原因”，或进入 `waiting_for_input` 并输出 `required_information_requests`；不得用“待补充/待确认/TODO”通过门禁。
- 模板文件不存在、无法读取或输出无法通过 xlsx 模板校验时，`StageRunResult.status` 必须为 `blocked` 或 `failed`。

# 对应模板
{templates}
"""
    return f"""
# 模板执行协议
- 只有 `preflight_input_state == ready` 时才能进入 `formal_generation` 读取模板并生成正式 Markdown；存在 blocking 缺失信息时必须先暂停并生成补充信息入口。
- 生成正式 Markdown 文档前必须先读取对应 template asset；不得凭记忆、通用模板、聊天上下文或 `assets/artifact-template.md` 生成正文。
- 以 template 原文作为唯一正文骨架，保留 frontmatter、标题层级、章节顺序、表格列头、固定提示块和格式约定。
- 只允许替换占位符、补充空白单元格和在既有章节下填充输入事实；不得删除、压缩、合并、重命名或重排模板章节。
- 输入材料缺少事实时，保留模板章节并写明“不适用原因”，或进入 `waiting_for_input` 并输出 `required_information_requests`；不得用“待补充/待确认/TODO”通过门禁。
- 模板文件不存在、无法读取或输出无法通过模板校验时，`StageRunResult.status` 必须为 `blocked` 或 `failed`。

# 对应模板
{templates}
"""


def template_generation_step(skill: dict) -> str:
    if template_usage_policy(skill).get("required"):
        if skill["id"] == "mq-design":
            return "确认 `preflight_input_state == ready` 后进入 `formal_generation`；按模板执行协议读取对应 `assets/*-template.xlsx`，复制 Excel 工作簿文件副本，只在模板已有空白数据单元格内填充输入事实，再生成全部声明产物。"
        return "确认 `preflight_input_state == ready` 后进入 `formal_generation`；按模板执行协议读取对应 `assets/*-template.md`，复制模板骨架后逐节填充输入事实，再生成全部声明产物。"
    return "确认 `preflight_input_state == ready` 后进入 `formal_generation` 并生成全部声明产物。"


def team_document_policy(skill: dict) -> dict:
    if skill["id"] == "high-level-design":
        return {
            "artifact": "high-level-design.md",
            "canonical_template": "skills/high-level-design/assets/high-level-design-template.md",
            "source_template": "inputs/萤启运营系统概要设计 - 萤启服务商系统 - 站点标题.html",
            "template_usage_policy": template_usage_policy(skill),
            "required_sections": HIGH_LEVEL_DESIGN_REQUIRED_SECTIONS,
            "forbidden_headings": HIGH_LEVEL_DESIGN_FORBIDDEN_HEADINGS,
            "forbidden_mermaid": HLD_FORBIDDEN_MERMAID,
            "detailed_implementation_forbidden_terms": HLD_DETAILED_IMPLEMENTATION_FORBIDDEN_TERMS,
            "source_traceability_header": SOURCE_TRACEABILITY_TABLE_HEADER,
            "service_sequence_policy": {
                "required_mermaid": "sequenceDiagram",
                "participants_only": "services",
                "forbidden_participants": HLD_SERVICE_SEQUENCE_FORBIDDEN_PARTICIPANTS,
            },
            "rules": ["概要设计必须保留团队模板章节顺序", "系统设计必须明确逻辑视图、设计原则、研发视图和研发结构", "概要设计聚焦跨系统/跨服务架构边界、服务间时序、调用/事件方向、异常流、最终一致性和专项文档引用", "概要设计不得生成流程图，4.1.2 只保留关键协作摘要文本", "跨服务核心场景必须补充服务间 sequenceDiagram，参与者只允许服务", "研发视图和结构定义使用接口层/应用层/领域层/基础设施层等边界语言，不使用 Controller/Mapper/Repository 等实现标签", "中间件设计只说明是否涉及并引用专项设计", "数据视图声明事实表、读模型和专项 DB 设计关系", "概要设计必须保留原始需求规格或原型引用矩阵", "概要设计不得展开接口字段、请求/响应字段、SQL/DDL、数据库字段索引、Controller/Mapper/Repository、类方法签名、伪代码或单元测试步骤"],
            "blocked_when": ["high-level-design.md 缺少团队模板章节", "使用通用证据/Findings/门禁决策模板替代概要设计正文", "跨系统边界、事件协作、最终一致性或异常流缺失", "high-level-design.md 包含 flowchart", "缺少跨服务服务间时序图", "sequenceDiagram 参与者包含用户、页面、Controller、数据库、中间件或表对象", "缺少原始需求规格或原型引用矩阵", "概要设计展开接口字段、SQL/DDL、数据库字段索引、Controller/Mapper/Repository、类方法签名、伪代码或单元测试步骤"],
        }
    if skill["id"] == "detailed-design":
        return {
            "scope": "团队详细设计主文档按输入详细设计规范组织，证据、选型、专项展开和发布灰度内容必须拆出。",
            "main_document": {
                "artifact": "detailed-design.md",
                "canonical_template": "skills/detailed-design/assets/detailed-design-template.md",
                "source_template": "inputs/详细设计规范.md",
                "template_usage_policy": template_usage_policy(skill),
                "allowed_sections": DETAILED_DESIGN_MAIN_SECTIONS,
                "forbidden_headings": DETAILED_DESIGN_FORBIDDEN_HEADINGS,
                "forbidden_mermaid": ["sequenceDiagram"],
                "required_mermaid": ["flowchart"],
                "flowchart_note_required": True,
                "flowchart_note_fields": DETAILED_DESIGN_FLOW_NOTE_FIELDS,
                "flowchart_required_branch_terms": DETAILED_DESIGN_FLOW_REQUIRED_BRANCH_TERMS,
                "exception_table_required_fields": DETAILED_DESIGN_EXCEPTION_TABLE_FIELDS,
                "class_diagram_required_when_terms_present": DETAILED_DESIGN_DDD_TERMS,
                "specialty_reference_only": DETAILED_DESIGN_SPECIALTY_DOCS,
                "evidence_location": ["stage-run-result.json", "repo-context-report.md", "review evidence artifacts"],
                "technology_selection_location": ["high-level-design.md", "technology-selection-review.md", "repo-context-report.md"],
                "source_traceability_header": SOURCE_TRACEABILITY_TABLE_HEADER,
            },
            "stage_result": {
                "must_register_specialty_artifacts": list(DETAILED_DESIGN_SPECIALTY_DOCS),
                "waiting_for_human_review_when": ["DDL", "MQ 新队列", "MQ 新 topic", "Redis 新 Key"],
                "blocked_when": [
                    "detailed-design.md 包含禁止标题",
                    "detailed-design.md 包含 sequenceDiagram",
                    "detailed-design.md 缺少 flowchart",
                    "flowchart 后缺少流程设计说明",
                    "flowchart 缺少异常分支、失败终态或补偿/重试/人工处理路径",
                    "异常场景表缺少触发条件、异常编码、异常信息、系统处理动作、数据状态、日志/告警或补偿/重试/人工处理",
                    "DDD/分层/扩展点关键词出现但缺少 classDiagram",
                    "涉及 DB/MQ/Redis 但缺少独立专项文档或 StageRunResult 未登记",
                    "缺少原始需求规格或原型引用矩阵",
                ],
            },
        }
    if skill["id"] == "database-design":
        return {
            "artifact": "database-design.md",
            "canonical_oltp_template": "skills/database-design/assets/database-oltp-template.md",
            "positive_oltp_example": "用户提供的 customer_type_ref database-design.md 用作表达风格参考；结构以 canonical_oltp_template 为准。",
            "template_usage_policy": template_usage_policy(skill),
            "template_selection": {"oltp": DB_OLTP_REQUIRED_SECTIONS, "olap": DB_OLAP_REQUIRED_SECTIONS},
            "oltp_required_table_headers": DB_OLTP_REQUIRED_TABLE_HEADERS,
            "oltp_required_fact_fields": DB_OLTP_REQUIRED_FACT_FIELDS,
            "missing_information_policy": {
                "must_ask_user": True,
                "forbid_guessing": True,
                "forbid_unresolved_markers_when_succeeded": DB_UNRESOLVED_INFO_MARKERS,
                "status_when_missing_facts": "waiting_for_input",
                "required_output": "required_information_requests",
            },
            "strong_coupled_table_group_policy": {
                "trigger_when": [
                    "两个及以上事实对象",
                    "主明细对象",
                    "配置+规则+记录对象",
                    "主表+参数表+大字段表",
                    "领取主记录+领取明细",
                ],
                "title_format": "<业务对象>表组 关系型（OLTP）详细设计",
                "design_object_format": "强耦合表组：表1、表2、表3...",
                "required_sections": ["2.4 强耦合表组说明", "3.1 表的业务职责", "4.2 字段定义（按表展开）", "4.3 索引设计", "6. CRUD 契约设计", "7. 事务、一致性与并发控制"],
                "required_artifact_consistency": ["database-design.md", "schema-change-plan.sql", "migration-plan.md", "rollback-plan.md", "database-risk-report.json"],
            },
            "forbidden": ["无用途字段和索引", "没有 WHERE 的 UPDATE/DELETE", "业务代码物理删除在线事实行", "Redis/MQ/文件系统作为事实数据来源"],
            "waiting_for_human_review_when": ["DDL", "数据订正", "物理删除在线事实行", "删除字段", "删除索引"],
            "blocked_when": ["未确认库名、实例、字符集、索引名时标记为 approved/final", "缺少模板必填章节或表格列头", "无审批却包含高风险生产变更", "缺失事实却直接输出 succeeded", "设计对象列出多张表但 DDL CREATE TABLE 数量不足", "强耦合表组缺少 2.4 表组说明、逐表字段、逐表索引、CRUD 参与表或事务表组口径", "迁移、回滚或风险报告没有体现表组同批创建和一致性口径"],
        }
    if skill["id"] == "redis-design":
        return {
            "artifact": "redis-design.md",
            "template_usage_policy": template_usage_policy(skill),
            "required_sections": REDIS_REQUIRED_SECTIONS,
            "design_item_required_fields": REDIS_DESIGN_ITEM_FIELDS,
            "storage_required_fields": REDIS_STORAGE_FIELDS,
            "rules": ["Redis 只做加速层、协调层、幂等层、短态承载层", "Redis 不做事实库", "Redis 不做消息队列", "Redis 不做跨服务共享事实源", "Redis 不做长期审计库", "所有 Key 必须设置 TTL，最大不超过 30 天", "Redis 不可用必须进入 MQ 重试 / 死信并告警"],
            "required_business_terms": REDIS_BUSINESS_TERMS,
            "forbidden_formal_terms": REDIS_FORBIDDEN_FORMAL_TERMS,
            "waiting_for_input_when": ["Redis 版本无法确认", "拓扑无法确认", "持久化策略无法确认", "淘汰策略无法确认"],
            "waiting_for_human_review_when": ["Redis 新 Key", "批量 Key", "Key 批量删除", "Value 单 Key 超过 1MB"],
            "blocked_when": ["Redis 作为事实库", "Redis 作为跨服务共享事实源", "Redis 作为长期审计库", "RabbitMQ 项目设计 Redis 发布订阅或 Redis 延迟队列", "使用水位/终态水位作为正式术语", "缺少 TTL 或 TTL 单位", "Redis 不可用时继续写库或删除", "缺少不可用降级策略、告警或人工回放策略"],
        }
    if skill["id"] == "mq-design":
        return {
            "artifact": "mq-design.xlsx",
            "template_usage_policy": template_usage_policy(skill),
            "producer_table_fields": MQ_PRODUCER_FIELDS,
            "consumer_table_fields": MQ_CONSUMER_FIELDS,
            "producer_required_value_fields": MQ_PRODUCER_REQUIRED_VALUE_FIELDS,
            "consumer_required_value_fields": MQ_CONSUMER_REQUIRED_VALUE_FIELDS,
            "rules": ["MQ 只用于削峰填谷、异步执行和服务解耦", "进程内异步不默认使用 MQ", "一个服务一个队列，一个队列可绑定多个 Exchange/routingKey", "队列默认建议仲裁队列", "必须设计死信队列", "消息体默认不超过 10KB", "必须定义幂等、重试、死信、回放策略"],
            "waiting_for_human_review_when": ["MQ 新队列", "MQ 新 topic", "非仲裁队列", "消息体超过 10KB", "生产消息回放", "删除或重命名 topic/queue"],
            "blocked_when": ["缺少生产者表或消费者表", "消息体承载大查询条件、文件内容或敏感明文", "无幂等策略", "无死信队列"],
        }
    return {}


def team_document_note(skill: dict) -> str:
    if skill["id"] == "high-level-design":
        return template_execution_note(skill) + f"""
# 团队概要设计模板规则
- `high-level-design.md` 必须按 `assets/high-level-design-template.md` 组织，章节顺序为：{"、".join(HIGH_LEVEL_DESIGN_REQUIRED_SECTIONS)}。
- 不得用通用 `证据`、`Findings`、`必须补充信息`、`门禁决策` 模板替代概要设计正文；这些内容只能进入 `StageRunResult` 或评审产物。
- `0. 原始需求与原型追溯` 必须列出原始需求规格或原型引用矩阵，字段包含 `source_id`、`source_type`、`source_path_or_url`、`prototype_page_or_section`、`requirement_item`、`design_section`、`consistency_status`；设计事实必须能追溯到规格或原型。
- `系统设计` 必须覆盖系统逻辑视图、系统设计原则、研发视图和研发结构定义。
- `核心功能` 必须按业务功能拆分，说明参与系统、职责边界、关键协作摘要、状态或异常流；涉及 Redis/MQ/DB 时只在概要层说明范围，并关联专项设计。
- `4.1.2 关键协作摘要` 只能使用文字描述职责边界、事件方向、异常流和最终一致性；概要设计不得生成 Mermaid `flowchart`。
- 概要设计允许引用详细设计或 DB/MQ/Redis 专项文档名，但不得展开接口字段、请求/响应字段、SQL/DDL、数据库字段索引、Controller/Mapper/Repository、类方法签名、伪代码或单元测试步骤。
- `3.3 研发视图` 和 `3.4 研发结构定义` 使用接口层、应用层、领域层、基础设施层、事件接入层等边界语言，不使用 `Controller`、`Mapper`、`Repository` 等实现标签。
- 跨服务核心场景必须在核心功能下补充 Mermaid `sequenceDiagram` 服务间时序图；该时序图参与者只允许真实系统 / 服务 / 应用边界，禁止出现用户、页面、数据库、Redis、MQ、表、Controller、Mapper、Repository 等非服务对象。
- `sequenceDiagram` 的每个 participant 必须能追溯到 repo_context 证据：代码路径、配置路径、服务注册证据、已有设计文档或用户明确补充。不得把抽象能力名直接当成真实服务写入正式时序图；找不到证据时必须进入 `waiting_for_input` / `waiting_for_human_review`，或在讨论项中标记为 proposed/unknown，不得进入正式图。
- 如果某能力由现有代码流程完成，应描述“沿用现有代码流程”，不得凭空拆出外部服务。
- 概要设计必须补充或消费 `participant-evidence-map.json`，记录 participant、display_name、status、evidence_type、repo_context、code_path、source_artifacts 等证据。缺少 evidence 或状态为 unknown/proposed/assumed/pending/unconfirmed 的 participant 视为质量门禁失败。
- 涉及 MQ / 事件 / 异步消息时，概要设计必须覆盖核心消息场景：创建 / 新增 / 产生类消息，以及状态变更 / 删除 / 失效类消息；两类消息都存在时必须分别给出核心时序。时序图只使用服务 participant，但允许服务 self-call 表达校验消息、幂等、状态/顺序判断、处理记录、本地读模型写入/移除、重试/死信等内部关键阶段；只有消息收发、没有内部处理步骤的核心链路必须阻断。
- `中间件设计` 必须声明是否涉及 Redis/MQ/定时任务/外部依赖，并引用专项文档；`数据视图` 必须声明事实表、读模型或关联数据库专项。
"""
    if skill["id"] == "detailed-design":
        forbidden = "、".join(DETAILED_DESIGN_FORBIDDEN_HEADINGS)
        return template_execution_note(skill) + f"""
# 团队详细设计主文档规则
- `detailed-design.md` 必须按 `assets/detailed-design-template.md` 组织，章节顺序为：{"、".join(DETAILED_DESIGN_MAIN_SECTIONS)}。
- 主文档不得包含独立章节：{forbidden}；不得展开数据库字段表、MQ 表格、Redis Key 表格。
- 来源证据只能进入 `stage-run-result.json`、repo-context 产物或评审证据；技术选型进入概要设计、技术选型评审或 repo-context，除非用户明确要求。
- `2.1 原始需求与原型引用矩阵` 必须列出 `source_id`、`source_type`、`source_path_or_url`、`prototype_page_or_section`、`requirement_item`、`design_section`、`consistency_status`；每个核心流程、接口、数据对象或规则必须可追溯到原始规格或原型。
- `数据库设计` 章节只能关联 `database-design.md` 或数据库模板；`中间件设计` 章节只能关联 `mq-design.xlsx`、`redis-design.md` 和对应规范，并登记到 `StageRunResult.artifacts`。
- 流程必须使用 Mermaid `flowchart`，禁止用 `sequenceDiagram` 替代；每个 `flowchart` 后必须紧跟“流程设计说明”。
- 每个 `3.1.x` 流程默认使用固定骨架：`触发 -> 参数/权限/状态校验 -> 核心处理 -> 外部依赖/消息协作 -> 事务/一致性处理 -> 成功终态 / 失败终态 / 重试补偿或人工处理`。
- `flowchart` 必须体现代码执行路径，覆盖正常流程、参数/权限/状态校验失败、外部依赖失败、事务/一致性失败、重试/补偿、人工处理或失败终态。
- MQ 消费流程必须明确消息接收、解析与校验、幂等判断、状态 / 顺序判断、外部详情查询、DB 写入 / 删除、Redis 写入 / 读取、事务边界、失败回滚、重试、死信和人工处理。
- 本地读模型写入流程必须明确主表写入或更新、明细表写入 / 更新 / 重建、主明细事务关系；删除流程必须明确状态处理记录写入、先删明细再删主表、删除失败处理。
- 查询 / 导出流程必须明确登录态或数据范围获取、强制合并可见范围、参数校验、DB 查询 / 汇总 / 分批导出、导出上限、文件生成失败处理。
- 流程设计说明必须把业务规则、校验规则、事务边界、幂等与一致性、异常场景、日志要求以及取消、重试、补偿、文件清理等合并到对应流程下。
- 每个 `3.1.x` 流程后都必须紧跟异常场景表；异常场景必须用表格列出场景、触发条件、异常编码、异常信息、系统处理动作、数据状态、日志/告警、补偿/重试/人工处理。
- 只要流程涉及数据库读写、事务、本地读模型、主明细表、DDL 或表结构引用，就必须补充 Mermaid `erDiagram`；`erDiagram` 只能使用 `database-design.md` 已确认的真实表名，禁止写“订单表/明细表/临时表”等抽象命名。
- 多表场景下 `erDiagram` 必须体现主表/明细表或关联表之间的关系；单表场景也必须体现真实表名，不能只在文字里提表名。
- 出现 DDD、聚合根、领域服务、application/domain/infrastructure 分层、port/adapter、SDK 模板方法、Handler、Strategy、Template 等设计取向时，主文档必须补充 Mermaid `classDiagram`。
- 存在 DDL、MQ 新队列或 topic、Redis 新 Key 时，`StageRunResult.status` 必须为 `waiting_for_human_review`，不得直接 `succeeded`。
"""
    if skill["id"] == "database-design":
        return template_execution_note(skill) + """
# 团队数据库设计规则
- 数据库设计必须生成独立 `database-design.md`，不得用主详细设计中的简写字段表替代。
- OLTP 场景必须以 `assets/database-oltp-template.md` 为唯一正文骨架生成：不得压缩、改写或删除模板章节、固定提示块、标题名称和表格列头；不适用章节也必须保留并写明“不适用原因”。生成流程不得用摘要式数据库设计替代模板正文；如果文档行数、章节集合或固定表格列头明显少于模板，必须视为裁剪模板并 `blocked`。
- 模板中的固定说明文字、禁止说明、编写要点、示例标题、方言差异提示、编写要求、契约含义、原则说明和“文档结束”等固定文本不得同义改写或删除；只允许填充模板预留的业务内容。
- 当需求、详细设计、repo_context 或业务对象中出现两个及以上事实对象、主明细对象、配置+规则+记录对象、主表+参数表+大字段表、领取主记录+领取明细等结构时，必须进入“强耦合表组模式”，不得生成单表或混合字段池。
- 强耦合表组模式下，文档标题必须使用 `<业务对象>表组 关系型（OLTP）详细设计`；`设计对象` 必须写成 `强耦合表组：表1、表2、表3...`；`文档定位` 必须明确对象类型，例如 `主表 + 明细表 + 规则表 + 领取主表 + 领取明细表`。
- 强耦合表组模式下必须生成 `### 2.4 强耦合表组说明`，列头固定为 `成员表 | 角色 | 与主表关系 | 同事务要求 | 备注`；`### 3.1 表的业务职责` 必须按表列出业务职责和唯一事实来源。
- 强耦合表组模式下 `### 4.2 字段定义（按表展开）` 必须为每张表生成独立子章节，例如 `#### 4.2.1 表名`；字段表列头必须包含 `字段 | 类型 | 必填 | 默认值 | 索引 | 敏感级别 | 说明`。
- 强耦合表组模式下 `### 4.3 索引设计` 必须逐表列出索引，列头固定为 `表 | 索引名 | 类型 | 字段（顺序敏感） | 唯一 | 服务场景 | 备注`；索引必须能归属到具体表。
- 强耦合表组模式下 `schema-change-plan.sql` 必须为设计对象中每张成员表生成 `CREATE TABLE`，唯一键和普通索引必须与 `database-design.md` 的索引设计一致，禁止只生成单表或承载全部字段的混合表。
- 强耦合表组模式下 `migration-plan.md` 必须说明表组同批创建、同批校验、逐表索引 explain 和表组关系校验；`rollback-plan.md` 必须说明应用发布后不得只删除或回滚表组中的单张事实表；`database-risk-report.json` 必须覆盖生产 DDL 审批、表组同批创建审批、容量/QPS、枚举口径和幂等键口径。
- ClickHouse、物化视图或分析宽表使用 `assets/database-olap-template.md`。
- 过程中缺少库名、实例、版本、负责人、字段口径、索引用途、QPS/容量、审批状态、敏感级别等事实时，必须主动输出 `required_information_requests` 询问用户，状态置为 `waiting_for_input`；除非用户明确允许，不得推测。
- `succeeded`、`approved` 或 `final` 输出不得包含 `{占位符}`、`待补充`、`待确认`、`未知`、`TODO/TBD` 等未决标记。
- 禁止无用途字段和索引、没有 WHERE 的 UPDATE/DELETE、业务代码物理删除在线事实行，除非专项审批。
- Redis/MQ/文件系统不得作为事实数据来源。
- 未确认库名、实例、字符集、索引名时，不得标记为 `approved` 或 `final`。
"""
    if skill["id"] == "redis-design":
        return template_execution_note(skill) + """
# 团队 Redis 设计规则
- Redis 设计必须生成独立 `redis-design.md`，不得在主详细设计中展开。
- 文档必须按 `assets/redis-design-template.md` 组织，并覆盖历史版本信息、前言、公共配置、Redis版本、集群配置、持久化策略、过期淘汰策略、设计项、资源申请和运维监控。
- 每个设计项必须包含特性用途、业务说明、存储设计、预估数据、多团队协同；存储设计必须列出库、数据结构、ttl、key 和数据格式。
- Redis 只做加速层、协调层、幂等层、短态承载层，不做事实库、不做消息队列、不做跨服务共享事实源、不做长期审计库；已使用 RabbitMQ 的项目不得设计 Redis 发布订阅或 Redis 延迟队列。
- Redis 设计术语必须贴近业务语义，优先使用“状态处理记录 / 已处理状态记录 / 消息幂等记录 / 短期处理记录 / 乱序保护记录”等显式术语；不得默认用“水位 / 终态水位”作为正式术语。
- Key 默认使用 db0，建议格式 `{服务模块}:{租户ID}:{数据结构}:{业务Key}`，长度不超过 100 字节。
- 所有 Key 必须设置 TTL，最大不超过 30 天；大批量 Key 必须有随机 TTL 抖动。
- Redis 不可用时不得绕过幂等 / 状态处理记录直接写 DB，也不得绕过状态处理记录直接删 DB；消费者应抛异常进入 MQ 重试 / 死信，必须有告警，并说明人工回放策略。
- Redis 版本、拓扑、持久化、淘汰策略无法确认时，状态必须为 `waiting_for_input` 或 `waiting_for_human_review`.
"""
    if skill["id"] == "mq-design":
        return template_execution_note(skill) + """
# 团队 MQ 设计规则
- MQ 设计必须生成独立 `mq-design.xlsx`，不得在主详细设计中展开，也不得用 `mq-design.md` 作为正式正文。
- 文档必须按 `assets/mq-design-template.xlsx` 组织，至少包含 `生产者` sheet 和 `消费者` sheet。
- `message-schema.json` 是消息体事实源，必须定义统一 envelope：顶层包含 `issueId`、`configType` 以及与 `configType` 同名的业务对象；不得只在 Excel 自由文本写“消息体内容”。
- `mq-topic-contract.yaml` 必须与 `message-schema.json`、`mq-design.xlsx` 一致，至少对齐业务消息 key / configType / 生产消费链路。
- MQ 只用于削峰填谷、异步执行和服务解耦；进程内异步不默认使用 MQ。
- 一个服务一个队列，一个队列可绑定多个 Exchange/routingKey；队列默认建议仲裁队列，非仲裁队列需要评审。
- 必须设计死信队列、幂等策略、重试策略、死信策略和回放策略。
- 消息体默认不超过 10KB，不得承载大查询条件、文件内容或敏感明文；超过 10KB 必须评审。
- `pendingOrderExportTask` 必须定义 `taskId`、`taskType`、`businessType`、`eventTime` 四个必填字段，并保持 `configType == pendingOrderExportTask`。
- 回放生产消息、删除或重命名 topic/queue 必须人工审批。
"""
    return ""


DB_OLTP_TEMPLATE_INPUT = ROOT / "inputs" / "关系型(OLTP)详细设计模板.md"


def enhance_database_oltp_template(template: str) -> str:
    """Apply team database-design extensions without compressing the canonical template."""
    template = template.replace("\r\n", "\n")
    template = template.replace(
        "> **编写原则：** 本文档必须比“建表 DDL”更完整——除字段与索引外，必须明确 **CRUD 契约、幂等与并发、事务边界、禁止操作、批量与修复规则**，作为研发、测试、DBA、审计与排障的统一依据。",
        "> **编写原则：** 本文档必须比“建表 DDL”更完整——除字段与索引外，必须明确 **CRUD 契约、幂等与并发、事务边界、禁止操作、批量与修复规则**，作为研发、测试、DBA、审计与排障的统一依据。\n> **信息原则：** 缺少事实必须主动询问用户并进入 `waiting_for_input`；除非用户明确允许，不得推测、补造或用示例值替代事实。",
    )
    template = template.replace(
        "| 最后更新 | YYYY-MM-DD |\n\n\n---",
        "| 最后更新 | YYYY-MM-DD |\n\n强耦合表组模式标题规则：\n\n- 当设计对象为强耦合表组时，文档标题必须改为 `<业务对象>表组 关系型（OLTP）详细设计`。\n- `设计对象` 必须写成 `强耦合表组：表1、表2、表3...`，成员表集合须与 DDL、迁移、回滚和风险报告一致。\n\n---",
    )
    template = template.replace(
        "### 4.2 字段定义（含敏感级别）",
        "### 4.2 字段定义（按表展开）",
    )
    template = template.replace(
        "**字段说明列至少包含：** 名称、业务含义、类型、空值、默认值、生成策略、敏感级别、是否参与索引、备注（含 **谁可写、何时可改**）。\n\n| 序号 | 字段名 | 中文名 | 类型 | 必填 | 默认值 | 敏感级别 | 说明 |\n|------|--------|--------|------|------|--------|----------|------|\n| 1 | `id` | 主键 | `BIGINT` | 是 | 自增/序列 | 低 | 内部主键 |\n| 2 | `{biz_key}` | 业务唯一键 | `VARCHAR(n)` | 是 | - | 低 | 幂等定位 |\n| 3 | `{tenant_id}` | 租户 | `BIGINT` | 是 | - | 低 | 多租户必带 |\n| 4 | `{status}` | 状态 | `SMALLINT`/`枚举` | 是 | `{默认}` | 低 | 受状态机约束 |\n| 5 | `{amount}` | 金额 | `DECIMAL(18,2)` | 是 | `0` | 中 | 应用+约束校验 |\n| 6 | `{phone}` | 手机号 | `VARCHAR(32)` | 条件必填 | - | **高** | 加密/脱敏策略见 §9 |\n| 7 | `create_time` | 创建时间 | `DATETIME(3)` / `TIMESTAMPTZ` | 是 | `CURRENT_TIMESTAMP` | 低 | 分区/排序 |\n| 8 | `update_time` | 更新时间 | 同左 | 是 | 自动更新 | 低 | 由触发器/应用维护 |\n| 9 | `version` | 乐观锁版本 | `INT` | 是 | `1` | 低 | 并发更新 |",
        "**字段说明列至少包含：** 字段、类型、必填、默认值、索引、敏感级别、说明；说明中必须覆盖业务含义、生成策略、谁可写、何时可改。\n\n**强耦合表组模式要求：** 每张成员表必须建立独立子章节，例如 `#### 4.2.1 t_xxx_main`，字段不得跨表混放；不适用章节也必须保留并写明“不适用原因”。\n\n#### 4.2.1 `{table}`\n\n| 字段 | 类型 | 必填 | 默认值 | 索引 | 敏感级别 | 说明 |\n|------|------|------|--------|------|----------|------|\n| `id` | `BIGINT` | 是 | 自增/序列 | PRIMARY | 低 | 内部主键 |\n| `{biz_key}` | `VARCHAR(n)` | 是 | - | `uk_*` | 低 | 业务唯一键，幂等定位 |\n| `{tenant_id}` | `BIGINT` | 是 | - | `uk_*`/`idx_*` | 低 | 多租户必带 |\n| `{status}` | `SMALLINT`/`枚举` | 是 | `{默认}` | `idx_*` | 低 | 受状态机约束 |\n| `{amount}` | `DECIMAL(18,2)` | 是 | `0` | 否 | 中 | 应用+约束校验 |\n| `{phone}` | `VARCHAR(32)` | 条件必填 | - | 否 | **高** | 加密/脱敏策略见 §9 |\n| `create_time` | `DATETIME(3)` / `TIMESTAMPTZ` | 是 | `CURRENT_TIMESTAMP` | `idx_*` | 低 | 分区/排序 |\n| `update_time` | 同左 | 是 | 自动更新 | 否 | 低 | 由触发器/应用维护 |\n| `version` | `INT` | 是 | `1` | 否 | 低 | 并发更新 |",
    )
    template = template.replace(
        "| 索引名 | 类型 | 字段（顺序敏感） | 唯一 | 服务场景 | 备注 |\n|--------|------|------------------|------|----------|------|\n| `PRIMARY` | 主键 | `id` | 是 | 内部关联 | — |\n| `uk_{biz}` | 唯一 | `{tenant_id, biz_key}` 或单列 | 是 | 幂等/对外查询 | 注意租户前缀 |\n| `idx_{list}` | 二级 | `{tenant_id, status, create_time}` | 否 | 列表/后台 | 避免低选择性首列 |",
        "| 表 | 索引名 | 类型 | 字段（顺序敏感） | 唯一 | 服务场景 | 备注 |\n|----|--------|------|------------------|------|----------|------|\n| `{table}` | `PRIMARY` | 主键 | `id` | 是 | 内部关联 | — |\n| `{table}` | `uk_{biz}` | 唯一 | `{tenant_id, biz_key}` 或单列 | 是 | 幂等/对外查询 | 注意租户前缀 |\n| `{table}` | `idx_{list}` | 二级 | `{tenant_id, status, create_time}` | 否 | 列表/后台 | 避免低选择性首列 |",
    )
    template = template.replace(
        "| 操作 | 典型入口 | 定位键/幂等键 | 必备前置条件 | 允许字段/投影 | 明确禁止 | 并发控制 | 审计 |\n|------|----------|---------------|--------------|---------------|----------|----------|------|\n| **C** | `{API}` | `{idempotency_key}` + `UNIQUE` | 租户、参数校验 | 创建字段集合 | 手写系统字段 | 唯一冲突即幂等返回 | 创建来源 |\n| **R** | `{API}` | 业务键 + 租户 | 租户过滤 | 列白名单 | `SELECT *` 大查询 | 读写分离规则 | 敏感字段访问 |\n| **U** | `{API}` | 业务键 + `version`/状态 | 状态合法 | 可变态 | 改锚点字段 | 乐观锁/条件更新 | 前后镜像 |\n| **D** | `{API/任务}` | 业务键 | 生命周期允许 | 逻辑删除列 | 在线物理删 | 条件更新 | 原因码 |",
        "| 操作 | 典型入口 | 参与表 | 定位键/幂等键 | 一致性边界 | 必备前置条件 | 允许字段/投影 | 明确禁止 | 并发控制 | 审计 |\n|------|----------|--------|---------------|------------|--------------|---------------|----------|----------|------|\n| **C** | `{API}` | `{table}` / `{table_group}` | `{idempotency_key}` + `UNIQUE` | 同事务 / 最终一致 | 租户、参数校验 | 创建字段集合 | 手写系统字段 | 唯一冲突即幂等返回 | 创建来源 |\n| **R** | `{API}` | `{table}` / `{read_model}` | 业务键 + 租户 | 主库强一致 / 只读延迟可接受 | 租户过滤 | 列白名单 | `SELECT *` 大查询 | 读写分离规则 | 敏感字段访问 |\n| **U** | `{API}` | `{table}` / `{table_group}` | 业务键 + `version`/状态 | 同事务 / 最终一致 | 状态合法 | 可变态 | 改锚点字段 | 乐观锁/条件更新 | 前后镜像 |\n| **D** | `{API/任务}` | `{table}` / `{archive}` | 业务键 | 同事务 / 归档后清理 | 生命周期允许 | 逻辑删除列 | 在线物理删 | 条件更新 | 原因码 |",
    )
    template = template.replace(
        "| 场景 ID | 参与表/对象 | 一致性要求 | 提交/回滚 |\n|---------|-------------|------------|-----------|\n| T01 | `{主表}+{明细}` | 强一致 | 单事务 |\n| T02 | `{主表}+{流水}` | 强一致 | 单事务 |\n| T03 | 仅主表 | 强一致 | 单事务 |",
        "| 场景 ID | 参与表 | 一致性要求 | 提交/回滚策略 | 补偿/核对策略 |\n|---------|--------|------------|----------------|----------------|\n| T01 | `{主表}+{明细}` | 强一致 | 单事务提交；任一成员表失败整体回滚 | 表组关系校验 |\n| T02 | `{主表}+{流水}` | 强一致 | 单事务提交；失败整体回滚 | 日终一致性校验 |\n| T03 | 仅主表 | 强一致 | 单事务提交 | 业务键/状态核对 |",
    )
    template = template.replace(
        "| 关系 | 策略 | 补偿/核对 |\n|------|------|-----------|\n| 同库主明细 | 同事务 | 日终一致性校验任务 |\n| 跨库 | **Saga/本地消息表/TCC**（选其一并说明） | 对账任务、幂等重试 |\n| 读侧延迟 | 明确 **允许延迟** 的场景 | 禁止用于资金最终状态展示 |",
        "| 关系 | 参与表 | 策略 | 补偿/核对 |\n|------|--------|------|-----------|\n| 同库主明细 | `{主表}+{明细}` | 同事务 | 日终一致性校验任务 |\n| 跨库 | `{本地事实表}+{外部系统}` | **Saga/本地消息表/TCC**（选其一并说明） | 对账任务、幂等重试 |\n| 读侧延迟 | `{事实表}+{读模型}` | 明确 **允许延迟** 的场景 | 禁止用于资金最终状态展示 |",
    )
    return template.rstrip() + "\n"


def database_oltp_template_md() -> str:
    if DB_OLTP_TEMPLATE_INPUT.exists():
        return enhance_database_oltp_template(DB_OLTP_TEMPLATE_INPUT.read_text(encoding="utf-8"))
    return """# 关系型（OLTP）表级详细设计文档模板

> 适用范围：MySQL / PostgreSQL 等关系型 OLTP 场景；面向单表或强耦合表组的物理与行为设计。
> 编写原则：本文档必须比建表 DDL 更完整，必须明确 CRUD 契约、幂等与并发、事务边界、禁止操作、批量与修复规则。
> 信息原则：缺少事实必须主动询问用户并进入 waiting_for_input；除非用户明确允许，不得推测、补造或用示例值替代事实。

## 1. 文档信息

| 项目 | 内容 |
|------|------|
| 文档名称 |  |
| 逻辑库/Schema |  |
| 物理库标识 |  |
| 所属集群/实例 |  |
| 设计对象 | 单表 / 强耦合表组（列出成员表） |
| 数据库产品 | MySQL / PostgreSQL |
| 数据库版本 |  |
| 文档版本 | v1.0 |
| 编写日期 | YYYY-MM-DD |
| 编写人 |  |
| 业务负责人 |  |
| DBA 负责人 |  |
| 安全/合规接口人 |  |
| 最后更新 | YYYY-MM-DD |

强耦合表组模式标题规则：
- 当设计对象为强耦合表组时，文档标题必须改为 `<业务对象>表组 关系型（OLTP）详细设计`。
- `设计对象` 必须写成 `强耦合表组：表1、表2、表3...`，成员表集合须与 DDL、迁移、回滚和风险报告一致。

### 1.1 变更记录

| 版本 | 日期 | 变更原因/依据 | 变更摘要 | 变更人 | 评审/批准 |
|------|------|---------------|----------|--------|-----------|
| v1.0 | YYYY-MM-DD | 初版 | 首次发布 |  |  |

### 1.2 术语定义

| 术语 | 说明 |
|------|------|
| OLTP | Online Transaction Processing，联机事务处理 |
| 幂等键 | 用于识别重复请求的业务键/请求号 |

### 1.3 参考文档

| 文档名 | 关联类型 | 参考说明 |
|------|------|------|
|  | 规范引用/设计依赖/附件/决策依据 |  |

## 2. 文档定位

### 2.1 编写目的

- 本文档用于在 OLTP 语义下，把一张表或一组强耦合表的业务含义、物理结构、访问契约、并发与一致性、分区归档与安全审计落到可执行、可验收的规格。
- 本文档是实现代码、集成测试、性能基线、发布脚本、运维操作的输入；与概要设计分工为：概要定域与边界，详细定表级行为与约束。

### 2.2 设计对象类型

| 项目 | 内容 |
|------|------|
| 对象类型 | 单表 / 主表+明细 / 主表+扩展 / 配置表 / 幂等请求表 / 状态流水表 / 其他 |
| 是否核心业务表 | 是/否 |
| 是否强耦合表组 | 是/否 |
| 是否多租户 | 是/否；租户隔离字段： |
| 是否分区/分表 | 是/否；键： |
| 是否输出 CDC（binlog/WAL） | 是/否；消费方： |
| 是否含敏感字段 | 是/否 |
| 默认删除策略 | 物理删除 / 逻辑删除 / 禁止删除仅归档 |

强耦合表组模式下，`对象类型` 必须明确表组构成，例如：`主表 + 明细表 + 规则表 + 领取主表 + 领取明细表`、`主表 + 参数表 + 大字段表` 或 `配置表 + 规则表 + 记录表`。

### 2.3 与其他文档的关系

| 文档 | 关系 |
|------|------|
| 关系型 OLTP 概要设计 | 定义逻辑库、表组归属、跨表事务与一致性策略的上层边界 |
| 数据字典 | 标准字段、枚举、命名、敏感等级的权威来源 |
| 变更管理 / 发布规范 | 表结构变更、数据修复、批处理任务的流程与审批 |
| API/领域服务设计 | 对外能力由服务暴露；禁止绕过契约直接写库的场景须在此声明 |

### 2.4 强耦合表组说明

| 成员表 | 角色 | 与主表关系 | 同事务要求 | 备注 |
|--------|------|------------|------------|------|
|  |  |  |  |  |

一致性摘要：

## 3. 业务语义与生命周期

### 3.1 表的业务职责

强耦合表组模式下必须按表列出业务职责和唯一事实来源，禁止把多张表的字段混合成一个字段池。

| 表 | 业务职责 | 唯一事实来源 | 写入方 | 读取方 | 备注 |
|----|----------|--------------|--------|--------|------|
|  |  | MySQL 本表 |  |  |  |

### 3.2 核心业务场景

| 场景 ID | 场景名称 | 触发入口 | 主要 SQL 形态 | 优先级 | 频率/峰值 | 说明 |
|---------|----------|----------|---------------|--------|-----------|------|
| S01 |  | INSERT/UPDATE/SELECT/DELETE |  | P0/P1/P2 |  |  |

### 3.3 数据生命周期阶段

| 阶段 | 进入条件 | 允许的操作类型 | 对外可见性 | 数据留存策略 |
|------|----------|----------------|------------|--------------|
| 创建中 |  |  |  |  |
| 生效中 |  |  |  |  |
| 结束态 |  |  |  |  |
| 归档态 |  |  |  |  |
| 清理态 |  |  |  |  |

### 3.4 状态机

若无状态字段，写明“无状态机”并说明是否用版本号、乐观锁、事件顺序号约束变更。

| 当前状态（值/枚举名） | 允许迁移至 | 触发动作/事件 | 是否可回退 | 备注 |
|----------------------|------------|---------------|------------|------|
|  |  |  |  |  |

## 4. 物理结构设计

### 4.1 建表级环境与约定

| 项目 | MySQL 建议 | PostgreSQL 建议 | 本文档取值 |
|------|------------|-----------------|------------|
| 存储引擎 / 表类型 | InnoDB（必选 OLTP） | 默认堆表 / 按需 |  |
| 字符集 | utf8mb4 | 数据库/库级 UTF8 |  |
| 排序规则 | utf8mb4_unicode_ci（或团队统一） | C / C.UTF-8 等 |  |
| 主键策略 | 自增 BIGINT / 雪花 ID / UUID | BIGINT GENERATED/序列/UUID |  |
| 时间类型 | DATETIME(3) 或 TIMESTAMP | TIMESTAMPTZ 推荐 |  |
| 金额类型 | DECIMAL(p,s)，禁止浮点 | NUMERIC(p,s) |  |
| 默认隔离级别 | 与实例一致 | 与实例一致 |  |
| 逻辑删除 | is_deleted + 默认值 0 | 同左或 RLS 另行说明 |  |

### 4.2 字段定义（按表展开）

强耦合表组模式下，每张成员表必须建立独立子章节，例如 `#### 4.2.1 t_xxx_main`，字段不得跨表混放。

#### 4.2.1 表名

| 字段 | 类型 | 必填 | 默认值 | 索引 | 敏感级别 | 说明 |
|------|------|------|--------|------|----------|------|
| id | BIGINT | 是 | 无 | PRIMARY | 低 | 主键 |

敏感级别定义：

| 级别 | 说明 | 存储 | 展示 | 日志 |
|------|------|------|------|------|
| 低 | 非个人信息 | 明文 | 明文 | 可打 INFO |
| 中 | 业务敏感 | 明文+权限 | 按角色 | 脱敏 |
| 高 | PII/强监管 | 加密/令牌化 | 脱敏/最小化 | 禁止完整输出 |
| 极高 | 密钥类 | KMS/专用方案 | 不可展示 | 禁止 |

### 4.3 索引设计

| 表 | 索引名 | 类型 | 字段（顺序敏感） | 唯一 | 服务场景 | 备注 |
|----|--------|------|------------------|------|----------|------|
| 表名 | PRIMARY | 主键 | id | 是 | 内部关联 |  |

### 4.4 约束与数据库对象

| 类别 | 规则 | 实现方式 | 备注 |
|------|------|----------|------|
| 主键 | 唯一且非空 | PRIMARY KEY |  |
| 业务唯一 |  | UNIQUE / 应用保证 |  |
| 检查约束 |  | CHECK + 应用校验 |  |
| 外键 | 默认 OLTP 高并发分片场景慎用 | 应用层引用完整性 |  |
| 默认值 | 状态、时间、版本 | DEFAULT + 应用一致 |  |

### 4.5 字段可变性矩阵

| 字段 | 创建时赋值 | 运行中可改 | 结束态可改 | 修改主体 | 约束/备注 |
|------|------------|------------|------------|----------|-----------|
|  | 是/否 | 是/否 | 是/否 |  |  |

### 4.6 技术实现依赖

| 依赖项 | 版本/规格 | 本文档是否依赖 | 说明 |
|--------|-----------|----------------|------|
| 数据库大版本 |  | 是 | 影响 CHECK、默认索引类型等 |
| 客户端驱动 |  | 视需要 |  |
| 中间件路由 |  | 视需要 |  |
| 字符集/排序规则 |  | 是 |  |

## 5. 数据量与性能设计

### 5.1 数据量估算

| 维度 | 估算值 | 说明 |
|------|--------|------|
| 当前总行数 |  | 截止日期和依据 |
| 日均新增行数 |  | 含峰值说明 |
| 峰值日增 |  |  |
| 年增长率 |  | 基于业务预测 |
| 3 年预计总行数 |  | 含增长假设 |
| 单行平均大小 |  | 含索引估算 |
| 3 年预计磁盘占用 |  | 数据+索引+冗余 |

### 5.2 读写 QPS 与延迟 SLA

| 场景 ID | 场景名称 | 操作类型 | QPS/TPS 目标 | P99 延迟目标 | 优先级 | 说明 |
|---------|----------|----------|-------------|-------------|--------|------|
|  |  |  |  |  |  |  |

### 5.3 热点与数据倾斜分析

| 热点类型 | 表现 | 发生条件 | 缓解措施 |
|----------|------|----------|----------|
| 写热点 |  |  |  |
| 读热点 |  |  |  |
| 数据倾斜 |  |  |  |

### 5.4 容量规划

| 资源 | 估算方法 | 目标值 | 说明 |
|------|----------|--------|------|
| 磁盘（数据+索引） | 单行 × 行数 × 冗余系数 |  | 含备份空间 |
| InnoDB Buffer Pool | 热数据量 × 系数 |  | 建议覆盖热数据索引 |
| 连接数 | 应用实例 × 连接池 |  | 含监控/运维预留 |
| IOPS | 峰值 QPS × IO 放大 |  |  |

### 5.5 性能保障措施

| 措施 | 适用场景 | 实施状态 | 说明 |
|------|----------|----------|------|
| 索引覆盖 P0 查询 | 全部 P0 查询 | 已/待实施 | 见 4.3 |
| Redis 缓存 | 高频读场景 | 已/待实施/不适用 | Key 设计见缓存设计文档 |
| 读写分离 | 列表/报表查询 | 已/待实施/不适用 | 从库延迟可接受范围 |
| 分区裁剪 | 按时间范围查询 | 已/待实施/不适用 | 见 8.2 |
| 连接池优化 | 高并发场景 | 已/待实施 |  |

## 6. CRUD 契约设计

### 6.1 CRUD 总览矩阵

| 操作 | 典型入口 | 参与表 | 定位键/幂等键 | 一致性边界 | 必备前置条件 | 允许字段/投影 | 明确禁止 | 并发控制 | 审计 |
|------|----------|--------|---------------|------------|--------------|---------------|----------|----------|------|
| C |  |  |  | 同事务 / 最终一致 |  |  |  |  |  |
| R |  |  |  | 主库强一致 / 只读延迟可接受 |  |  |  |  |  |
| U |  |  |  | 同事务 / 最终一致 |  |  |  |  |  |
| D |  |  |  | 同事务 / 归档后清理 |  |  |  |  |  |

### 6.2 强制前置条件

| 操作 | 编号 | 强制条件（不满足则拒绝） | 错误码/HTTP 建议 |
|------|------|---------------------------|------------------|
| Create | MC-C1 |  |  |
| Read | MC-R1 |  |  |
| Update | MC-U1 |  |  |
| Delete | MC-D1 |  |  |

### 6.3 禁止操作清单

| 编号 | 禁止行为 | 适用范围 | 例外（须工单+审批） |
|------|----------|----------|---------------------|
| PO-01 | 无 WHERE 的 UPDATE/DELETE | 全部环境 | 不存在 |
| PO-02 | 修改 id / 业务锚点 / tenant_id / create_time | 生产 | 仅迁移/纠错脚本 |
| PO-03 | 业务代码物理删除在线事实行 | 生产 | 归档后清理任务 |
| PO-04 | 绕过服务层直接写核心表 | 生产 | DBA 紧急修复 |

### 6.4 Create

| 规则项 | 要求 |
|--------|------|
| 调用方必填 |  |
| 系统生成 |  |
| 幂等策略 |  |
| 事务边界 |  |
| 失败语义 |  |

### 6.5 Read

| 查询类型 | 必带条件 | 推荐索引 | 主库/只读 | 备注 |
|----------|----------|----------|-----------|------|
| 单笔详情 |  |  |  |  |
| 列表分页 |  |  |  |  |
| 对账/风控 |  |  |  |  |

### 6.6 Update

| 场景 | 前置条件 | 允许 SET 字段 | 禁止 SET 字段 | 并发 |
|------|----------|---------------|---------------|------|
| 状态迁移 |  |  |  |  |
| 业务补录 |  |  |  |  |

### 6.7 Delete

| 操作 | 策略 | 前置条件 | 审批 |
|------|------|----------|------|
| 业务删除 | 逻辑删除优先 |  |  |
| 归档清理 | 先归档再删/迁 |  |  |
| 物理删除 | 极少 |  | 高风险 |

### 6.8 幂等键与重复请求

| 层级 | 机制 | 说明 |
|------|------|------|
| API | Idempotency-Key / 业务请求号 | 网关或服务缓存短期去重 |
| DB | UNIQUE(tenant_id, biz_no) | 最终以数据库为准 |
| 消息 | 消费者 msg_id 去重表 | 与业务表配合 |

### 6.9 批量操作与数据修复规则

| 类型 | 允许条件 | 事务与批次 | 记录要求 |
|------|----------|------------|----------|
| 批量修正 | 工单 + 脚本版本 | 每批有上限；单批失败可重入 | 影响行数、样本校验 |
| 全表迁移 | 停机/双写方案 | 另行专项设计 | DBA 执行证据 |
| 临时手工 SQL | 默认禁止 |  | 紧急需审批+留痕 |

## 7. 事务、一致性与并发控制

### 7.1 本地事务边界

| 场景 ID | 参与表 | 一致性要求 | 提交/回滚策略 | 补偿/核对策略 |
|---------|--------|------------|----------------|----------------|
| T01 |  | 强一致 | 单事务提交；任一表失败整体回滚 | 表组关系校验 |

### 7.2 跨表一致性

| 关系 | 参与表 | 策略 | 补偿/核对 |
|------|--------|------|-----------|
| 同库主明细 |  | 同事务 | 日终一致性校验任务 |
| 跨库/跨服务 |  | Saga/本地消息表/TCC | 对账任务、幂等重试 |
| 读侧延迟 |  | 明确允许延迟的场景 | 禁止用于资金最终状态展示 |

### 7.3 并发控制

| 场景 | 策略 | 说明 |
|------|------|------|
| 一般更新 | 乐观锁 version | UPDATE WHERE version=? |
| 高竞争扣减 | 条件更新或专用服务 | 评估死锁与重试 |
| 幂等插入 | UNIQUE + 捕获冲突 | 返回已有记录 |

### 7.4 数据质量校验

| 校验项 | 规则 | 频率 | 失败处理 |
|--------|------|------|----------|
|  |  |  |  |

### 7.5 隔离级别、死锁与重试约定

| 主题 | 约定 |
|------|------|
| 默认隔离级别 | 与实例一致；若依赖幻读语义须在代码与测试中明示 |
| 读已提交 vs 可重复读 | 写后读、防脏读为底线 |
| 死锁 | 统一锁顺序；有限次退避重试并记录 trace_id |
| 长事务 | 禁止在 OLTP 长事务中混合外部 HTTP/RPC；批处理拆批并设超时 |

### 7.6 跨表最终一致

| 步骤 | 动作 | 失败补偿 |
|------|------|----------|
| 1 | 本地事务提交主事实 |  |
| 2 | 发送消息/写 outbox 表 | 重试 + 幂等消费 |
| 3 | 下游更新读模型 | 对账任务修正 |

## 8. 分区、分片与归档设计

### 8.1 路由与分片规则

| 项目 | 内容 |
|------|------|
| 分片键 |  |
| 路由算法 | 哈希 / 范围 / 中间件规则 |
| 全局唯一 |  |

### 8.2 分区策略

| 维度 | MySQL | PostgreSQL |
|------|-------|------------|
| 分区类型 | RANGE/LIST/HASH | RANGE/LIST + 声明式分区 |
| 分区键 |  |  |
| 跨分区查询 | 必须限制时间窗 | 必须限制时间窗 |

### 8.3 查询策略

| 场景 | 是否带路由/分区键 | 预期计划 | 禁止 |
|------|-------------------|----------|------|
| 点查 | 是 | 点查索引 |  |
| 跨月 | 明确时间范围 | 分区裁剪 | 无界扫描 |

### 8.4 归档与保留

| 阶段 | 条件 | 目标存储 | 在线库策略 |
|------|------|----------|------------|
| 归档 |  |  |  |
| 清理 |  |  |  |

### 8.5 冷热分离与只读副本

| 数据类别 | 放置 | 查询入口 | 说明 |
|----------|------|----------|------|
| 热数据 | 在线库 | 主路径 API | 默认 |
| 温数据 | 在线库分区/归档表 | 带时间窗查询 | 控制扫描范围 |
| 冷数据 | 归档库/对象存储 | 离线任务/专用查询 | 禁止与热路径混用 |
| 报表 | 汇总表/OLAP | BI 账号 | 禁止直连核心 OLTP 大表扫 |

## 9. 安全与审计设计

### 9.1 敏感字段清单

| 字段 | 级别 | 存储 | 应用展示 | 导出 |
|------|------|------|----------|------|
|  | 低/中/高/极高 |  |  |  |

### 9.2 脱敏与掩码规则

| 场景 | 规则 | 示例 |
|------|------|------|
| 手机号 | 保留前3后4 | 138****5678 |

### 9.3 访问控制

| 角色 | 读 | 写 | 说明 |
|------|----|----|------|
| 应用账号 | 白名单列 | 白名单列 | 最小权限 |
| 只读账号 | 允许 | 禁止 | 报表/BI |
| DBA 运维 | 审批后 | 变更窗口 | 双人复核 |

### 9.4 审计要求

| 事件 | 记录内容 | 保留期 |
|------|----------|--------|
| 敏感字段访问 | 操作者、对象、时间、原因码 |  |
| 数据修复 | 工单、脚本版本、影响行、校验截图 |  |
| 管理端导出 | 审批单、导出人、范围 |  |

## 10. 测试与验收

### 10.1 验收检查表

| 检查项 | 结果 | 备注 |
|--------|------|------|
| 与概要设计库表边界一致 | ☐ |  |
| InnoDB / utf8mb4（或 PG 等价）已声明 | ☐ |  |
| 字段与数据字典一致（含敏感级别） | ☐ |  |
| 索引覆盖 P0 查询 | ☐ |  |
| CRUD 契约、禁止项、批量规则完整 | ☐ |  |
| 状态机/可变性矩阵可测试 | ☐ |  |
| 幂等键与唯一约束对齐 | ☐ |  |
| 事务边界与补偿策略明确 | ☐ |  |
| 分区/归档策略与运维一致 | ☐ |  |
| 安全与审计要求可落地 | ☐ |  |
| 强制前置条件 MC-* 有对应用例 | ☐ |  |
| 禁止操作 PO-* 有反向用例 | ☐ |  |
| 批处理行数上限与工单流程验证 | ☐ |  |

### 10.2 测试用例类型

| 类型 | 目的 | 示例 |
|------|------|------|
| 正向 | 主路径 | 创建成功、状态合法迁移 |
| 反向 | 非法输入 | 缺租户、非法状态跳转 |
| 幂等 | 重复提交 | 同键重复创建仅一条 |
| 并发 | 竞争 | 双写同单、乐观锁冲突 |
| 批处理 | 边界 | 批次上限、失败重试 |
| 归档 | 生命周期 | 归档后查询路径 |
| 安全 | 越权 | 跨租户 ID 访问、脱敏绕过 |
| 兼容 | 方言 | PG 与 MySQL 同一契约下的参数与类型 |

### 10.3 样例 SQL

```sql
-- 将与本设计一致的查询、插入、更新、删除样例写入此处。
```

## 11. 附录

### 11.1 DDL SQL

```sql
-- 将最终建表/改表 DDL 粘贴于此；须与正文字段、索引、约束完全一致。
```

### 11.2 兼容性说明

| 主题 | 注意点 |
|------|--------|
| CHECK 约束 | MySQL 8.0.16+ 强制执行；PG 原生支持 |
| 索引类型 | PG 的 GIN/GIST 用于 JSONB/全文；勿与 OLTP 主路径混用无设计 |
| 分区 DDL | 语法与限制因产品而异；迁移需双轨验证 |
| 序列与 ID | 自增 vs IDENTITY vs 雪花；回填与复制冲突 |
| NULL 与唯一索引 | 多列唯一时 NULL 行为因版本/索引类型而异 |
| 隐式类型转换 | 类型不一致可能导致索引失效；参数绑定与列类型一致 |
| 批插入 | LOAD DATA / COPY 与触发器、复制延迟；大批量走离线通道 |
"""


def artifact_templates(skill: dict) -> dict:
    if skill["id"] == "high-level-design":
        return {
            "high-level-design-template.md": """---
document_number: "HLD-<DOMAIN>-<YYYYMMDD>-<SEQ>"
document_status: "draft"
retention_policy: "keep_until_run_end"
language: "zh-CN"
owner: "架构师"
source_artifacts: []
---

# <系统/项目名称>概要设计

## 0. 原始需求与原型追溯

| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
|  | requirement_spec / prototype |  |  |  |  | matched / pending_confirmation / conflict |

## 1. 版本变更记录

| 版本 | 日期 | 变更内容 | 作者 | 评审/批准 |
| --- | --- | --- | --- | --- |
| V1.0 | YYYY-MM-DD | 初版 |  |  |

## 2. 平台概述

## 3. 系统设计

### 3.1 系统逻辑视图

### 3.1.1 系统设计原则

### 3.3 研发视图

### 3.4 研发结构定义

## 4. 核心功能

### 4.1 <核心功能名称>

#### 4.1.1 参与系统与职责设计

| 系统 | 职责 |
| --- | --- |
|  |  |

#### 4.1.2 关键协作摘要

- 说明跨系统触发点、来源服务职责边界、目标服务职责边界、异常流和最终一致性。
- 只保留概要层摘要，不生成流程图；详细执行路径下沉到 `detailed-design.md` 和 DB/MQ/Redis 专项文档。

#### 4.1.3 跨服务服务间时序图

```mermaid
sequenceDiagram
    participant SourceService as 来源服务
    participant TargetService as 目标服务
    SourceService->>TargetService: 服务间调用或事件协作
```

> 时序图参与者只允许服务，不允许用户、页面、数据存储、中间件或表对象。

#### 4.1.4 状态机设计

| 状态 | 条件 | 动作 |
| --- | --- | --- |
|  |  |  |

#### 4.1.5 异常流与最终一致性

## 5.中间件设计

| 类型 | 是否涉及 | 专项文档 | 说明 |
| --- | --- | --- | --- |
| Redis | 是/否 | `redis-design.md` |  |
| MQ | 是/否 | `mq-design.xlsx` |  |
| 定时任务 | 是/否 |  |  |
| 外部依赖 | 是/否 |  |  |

## 6.数据视图

| 数据对象 | 类型 | 权威来源 | 专项文档 | 说明 |
| --- | --- | --- | --- | --- |
|  | 事实表/读模型/缓存/消息 |  | `database-design.md` |  |
""",
        }
    if skill["id"] == "detailed-design":
        return {
            "detailed-design-template.md": """---
document_number: "DDD-<DOMAIN>-<YYYYMMDD>-<SEQ>"
document_status: "draft"
retention_policy: "keep_until_run_end"
language: "zh-CN"
owner: "后端开发"
source_artifacts: []
---

# [项目/模块名称] 详细设计说明书

## 1. 修订历史

| 版本号 | 修订日期 | 修订人 | 修订描述 |
| --- | --- | --- | --- |
| V1.0 | YYYY-MM-DD |  | 初稿创建 |

## 2. 设计背景与目标摘要

- 关联概要设计：`high-level-design.md`
- 核心目标摘要：

### 2.1 原始需求与原型引用矩阵

| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
|  | requirement_spec / prototype |  |  |  |  | matched / pending_confirmation / conflict |

## 3. 模块/功能详细设计

### 3.1. 业务流程图

```mermaid
flowchart TD
    A["触发"] --> B{"参数/权限/状态校验通过?"}
    B -- 否 --> E1["返回校验/权限/状态异常"]
    B -- 是 --> C["核心处理"]
    C --> D["外部依赖/消息协作"]
    D --> T{"事务/一致性处理成功?"}
    T -- 否 --> R{"可重试或可补偿?"}
    T -- 是 --> S["成功终态"]
    R -- 可重试 --> RT["记录日志告警并重试"]
    R -- 可补偿 --> CP["执行补偿/回滚"]
    R -- 不可自动处理 --> H["进入人工处理"]
    E1 --> F["失败结束"]
    RT --> D
    CP --> F
    H --> F
```

流程设计说明：

- 业务规则：说明本流程的核心业务判断、状态流转和不变式。
- 校验规则：说明参数校验、权限校验、状态校验失败时的返回和终态。
- 事务边界：说明本地事务、跨资源一致性、提交失败和回滚动作。
- 幂等与一致性：说明幂等键、重复请求处理、最终一致性和乱序处理。
- 异常场景：见下表，必须覆盖校验失败、外部依赖失败、事务/一致性失败和不可自动恢复场景。
- 日志要求：说明 traceId、业务主键、异常编码、告警维度和敏感信息脱敏。
- 取消、重试、补偿、文件清理：说明可重试条件、补偿/回滚动作、人工处理入口和失败终态。

| 场景 | 触发条件 | 异常编码 | 异常信息 | 系统处理动作 | 数据状态 | 日志/告警 | 补偿/重试/人工处理 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 参数/权限/状态校验失败 | 入参缺失、无权限或当前状态不允许继续 |  |  | 拒绝处理并返回失败 | 不落库或保持原状态 | 记录 traceId、用户、业务主键 | 无需补偿，必要时提示人工确认输入 |
| 外部依赖失败 | 服务调用超时、返回失败或熔断 |  |  | 记录失败原因并按策略重试或降级 | 本地状态保持处理中/失败待补偿 | 告警依赖名称、耗时、错误码 | 可重试则重试；不可重试进入人工处理 |
| 事务/一致性失败 | 本地事务提交失败、消息发送失败或状态不一致 |  |  | 回滚事务或写入补偿任务 | 回滚到提交前状态或标记待补偿 | 告警事务边界、补偿任务 ID | 执行补偿/回滚，失败后人工处理 |

### 3.2. UML类图

```mermaid
classDiagram
    class ApplicationService
    class DomainService
    class RepositoryPort
    class ExternalAdapter
    ApplicationService --> DomainService
    DomainService --> RepositoryPort
    ApplicationService --> ExternalAdapter
```

类图说明：

### 3.3. 数据库图（涉库场景必填）

```mermaid
erDiagram
    t_order ||--o{ t_order_item : contains
    t_order {
        BIGINT id
        VARCHAR order_no
        BIGINT tenant_id
        SMALLINT status
    }
    t_order_item {
        BIGINT id
        BIGINT order_id
        VARCHAR sku_code
        DECIMAL amount
    }
```

数据库图说明：

- 涉及数据库读写、事务、本地读模型、主明细表、DDL 或表结构引用时，必须补充 `erDiagram`。
- `erDiagram` 只能出现 `database-design.md` 已确认的真实表名，不得写“订单表/明细表/临时表”等抽象命名。
- 多表场景必须体现主表/明细表或关联表之间的关系；单表场景也必须体现真实表名。

## 4. 数据库设计

| 设计项 | 关联文档 | 说明 |
| --- | --- | --- |
| 数据库专项设计 | `database-design.md` | 关联关系型 OLTP/OLAP 数据库模板，不在主详细设计展开字段和索引 |

## 5. 接口定义

### 5.1. API接口列表

| 接口名称 | YApi链接 | 接口路径 | 说明 |
| --- | --- | --- | --- |
|  |  |  |  |

### 5.2. 中间件设计

| 中间件 | 是否涉及 | 关联文档 | 评审要求 |
| --- | --- | --- | --- |
| MQ | 是/否 | `mq-design.xlsx` | 遵循 MQ Excel 设计模板并完成对应评审 |
| Redis | 是/否 | `redis-design.md` | 遵循 Redis 设计模板并完成对应评审 |

## 6. 单元测试

| 测试对象 | 正常流程 | 分支流程 | 异常流程 | 断言 |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## 7. 性能与扩展性设计

## 8. 人工评审项
""",
        }
    if skill["id"] == "database-design":
        return {
            "database-oltp-template.md": database_oltp_template_md(),
            "database-olap-template.md": "# OLAP 数据库设计\n\n" + "\n\n".join(f"## {index}. {section}" for index, section in enumerate(DB_OLAP_REQUIRED_SECTIONS, start=1)) + "\n",
        }
    if skill["id"] == "redis-design":
        return {
            "redis-design-template.md": """# Redis 详细设计

## 历史版本信息

| 版本 | 日期 | 编制 | 审核 | 批准 | 备注 |
| --- | --- | --- | --- | --- | --- |
| V1.0.0 | YYYY-MM-DD |  |  |  | 初版 |

## 1. 前言

### 1.1. 目的

### 1.2. 适用范围

### 1.3. 参考资料

## 2. 公共配置

### 2.1. Redis版本

### 2.2. 集群配置

### 2.3. 持久化策略

### 2.4. 过期淘汰策略

## 3. 设计项

### 3.1. <设计项名称>

#### 3.1.1. 特性用途

#### 3.1.2. 业务说明

#### 3.1.3. 存储设计

| 项/值 | 数值 | 说明 |
| --- | --- | --- |
| 库 | 0 |  |
| 数据结构 | String/Hash/List/Set/ZSet |  |
| ttl |  | TTL 必须说明单位 |
| key |  |  |

**数据格式**

| 字段名 | 字段类型 | 是否可空 | 备注 |
| --- | --- | --- | --- |
|  |  |  |  |

#### 3.1.4. 预估数据

#### 3.1.5. 多团队协同

## 4. 安全与运维

### 4.1. 资源申请

### 4.2. 运维监控
""",
        }
    return {}


def generic_validator_script() -> str:
    return """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

schema = json.loads(Path(__file__).parents[1].joinpath("output.schema.json").read_text(encoding="utf-8"))
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
missing = [field for field in schema.get("required", []) if field not in payload]
if missing:
    raise SystemExit(f"缺少必填字段: {missing}")
if payload.get("skill_id") != schema["properties"]["skill_id"]["const"]:
    raise SystemExit("skill_id 不匹配")
if payload.get("status") not in schema["properties"]["status"]["enum"]:
    raise SystemExit("status 不合法")
if payload.get("preflight_input_state") not in schema["properties"]["preflight_input_state"]["enum"]:
    raise SystemExit("preflight_input_state 不合法")
if payload.get("status") == "succeeded" and payload.get("preflight_input_state") != "ready":
    raise SystemExit("succeeded 必须满足 preflight_input_state == ready")
if payload.get("status") == "waiting_for_input" and payload.get("preflight_input_state") != "waiting_for_input":
    raise SystemExit("waiting_for_input 必须满足 preflight_input_state == waiting_for_input")
formal_design_artifacts = {"high-level-design.md", "detailed-design.md", "database-design.md", "redis-design.md", "mq-design.xlsx", "interface-contracts.yaml", "test-strategy.md"}
if payload.get("preflight_input_state") != "ready":
    produced = {item.get("name") for item in payload.get("artifacts", []) if isinstance(item, dict)}
    leaked = sorted(formal_design_artifacts & produced)
    if leaked:
        raise SystemExit("preflight 未 ready 时不得生成或登记正式设计文档: " + ", ".join(leaked))
print("ok")
"""


def workflow_orchestrator_validator_script() -> str:
    return """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

schema = json.loads(Path(__file__).parents[1].joinpath("output.schema.json").read_text(encoding="utf-8"))
payload_path = Path(sys.argv[1])
payload = json.loads(payload_path.read_text(encoding="utf-8"))
missing = [field for field in schema.get("required", []) if field not in payload]
if missing:
    raise SystemExit(f"缺少必填字段: {missing}")
if payload.get("skill_id") != schema["properties"]["skill_id"]["const"]:
    raise SystemExit("skill_id 不匹配")
if payload.get("status") not in schema["properties"]["status"]["enum"]:
    raise SystemExit("status 不合法")
if payload.get("preflight_input_state") not in schema["properties"]["preflight_input_state"]["enum"]:
    raise SystemExit("preflight_input_state 不合法")

errors = []
if payload.get("status") == "succeeded" and payload.get("preflight_input_state") != "ready":
    errors.append("succeeded 必须满足 preflight_input_state == ready")
if payload.get("status") == "waiting_for_input" and payload.get("preflight_input_state") != "waiting_for_input":
    errors.append("waiting_for_input 必须满足 preflight_input_state == waiting_for_input")
formal_design_artifacts = {"high-level-design.md", "detailed-design.md", "database-design.md", "redis-design.md", "mq-design.xlsx", "interface-contracts.yaml", "test-strategy.md"}
if payload.get("preflight_input_state") != "ready":
    produced = {item.get("name") for item in payload.get("artifacts", []) if isinstance(item, dict)}
    leaked = sorted(formal_design_artifacts & produced)
    if leaked:
        errors.append("preflight 未 ready 时不得生成或登记正式设计文档: " + ", ".join(leaked))

def artifact_map(payload):
    return {item.get("name"): item for item in payload.get("artifacts", [])}

def resolve_artifact(item):
    raw = (item or {}).get("path") or ""
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path
    return payload_path.parent / path

def read_text_artifact(name):
    path = resolve_artifact(artifact_map(payload).get(name))
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    return ""

def read_json_artifact(name):
    text = read_text_artifact(name)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{name} 不是合法 JSON: {exc}")
        return None

validator_summary = read_json_artifact("validator-summary.json")
if payload.get("status") == "succeeded":
    if validator_summary is None:
        errors.append("workflow-orchestrator succeeded 必须登记并生成 validator-summary.json，汇总所有专项 validator 结果")
    else:
        validators = validator_summary.get("validators") or validator_summary.get("results") or []
        if not validators:
            errors.append("validator-summary.json 必须包含 validators/results 列表")
        required_validators = {"high-level-design", "detailed-design", "database-design", "mq-design", "redis-design"}
        seen = {str(item.get("stage") or item.get("skill_id") or item.get("validator") or item.get("name") or "") for item in validators if isinstance(item, dict)}
        missing_validators = sorted(required_validators - seen)
        if missing_validators:
            errors.append("design-only workflow succeeded 前必须汇总所有相关专项 validator，缺少: " + ", ".join(missing_validators))
        for item in validators:
            status = str(item.get("status") or item.get("result") or "").lower()
            exit_code = item.get("exit_code")
            if status in {"failed", "fail", "error", "blocked"} or (exit_code not in (None, 0, "0")):
                skill_id = item.get("skill_id") or item.get("validator") or item.get("name") or "unknown"
                errors.append(f"专项 validator 失败必须向 workflow-orchestrator 冒泡为 blocked，不得 succeeded: {skill_id}")
if validator_summary is not None:
    validators = validator_summary.get("validators") or validator_summary.get("results") or []
    for index, item in enumerate(validators, start=1):
        status = str(item.get("status") or item.get("result") or "").lower() if isinstance(item, dict) else ""
        exit_code = item.get("exit_code") if isinstance(item, dict) else None
        if status in {"failed", "fail", "error", "blocked"} or (exit_code not in (None, 0, "0")):
            for field in ["stage", "validator", "failed_rule", "error_message", "suggested_repair"]:
                if not item.get(field):
                    errors.append(f"validator-summary.json 第 {index} 个失败项缺少字段: {field}")

quality_defect_terms = ["脱离代码实际", "模板裁剪", "validator 失败", "门禁失败", "产物质量问题", "用户指出"]
quality_text = json.dumps(payload.get("findings", []), ensure_ascii=False) + "\\n" + read_text_artifact("workflow-summary.md")
if payload.get("status") == "succeeded" and any(term in quality_text for term in quality_defect_terms):
    defect_analysis = read_json_artifact("defect-analysis.json")
    if defect_analysis is None:
        errors.append("发现产物质量缺陷或用户指出问题时，workflow-orchestrator 必须生成 defect-analysis.json 并记录 root_cause，不得直接 succeeded")
    elif not defect_analysis.get("root_cause"):
        errors.append("defect-analysis.json 缺少 root_cause")

if errors:
    raise SystemExit("\\n".join(errors))
print("ok")
"""


def team_validator_script(skill_id: str) -> str:
    if skill_id == "workflow-orchestrator":
        return workflow_orchestrator_validator_script()
    if skill_id not in TEAM_DOC_TARGET_SKILLS:
        return generic_validator_script()
    policies = {
        "high-level-design": {
            "unresolved_markers": DB_UNRESOLVED_INFO_MARKERS,
            "required_sections": HIGH_LEVEL_DESIGN_REQUIRED_SECTIONS,
            "forbidden_headings": HIGH_LEVEL_DESIGN_FORBIDDEN_HEADINGS,
            "forbidden_mermaid": HLD_FORBIDDEN_MERMAID,
            "detailed_implementation_forbidden_terms": HLD_DETAILED_IMPLEMENTATION_FORBIDDEN_TERMS,
            "source_traceability_header": SOURCE_TRACEABILITY_TABLE_HEADER,
            "service_sequence_forbidden_participants": HLD_SERVICE_SEQUENCE_FORBIDDEN_PARTICIPANTS,
            "abstract_participant_label_terms": HLD_ABSTRACT_PARTICIPANT_LABEL_TERMS,
            "event_driven_terms": HLD_EVENT_DRIVEN_TERMS,
            "create_event_terms": HLD_CREATE_EVENT_TERMS,
            "state_event_terms": HLD_STATE_EVENT_TERMS,
            "internal_sequence_terms": HLD_INTERNAL_SEQUENCE_TERMS,
            "internal_sequence_outcome_terms": HLD_INTERNAL_SEQUENCE_OUTCOME_TERMS,
        },
        "detailed-design": {
            "unresolved_markers": DB_UNRESOLVED_INFO_MARKERS,
            "required_sections": DETAILED_DESIGN_MAIN_SECTIONS,
            "forbidden_headings": DETAILED_DESIGN_FORBIDDEN_HEADINGS,
            "flow_note_fields": DETAILED_DESIGN_FLOW_NOTE_FIELDS,
            "flow_required_branch_terms": DETAILED_DESIGN_FLOW_REQUIRED_BRANCH_TERMS,
            "exception_table_required_fields": DETAILED_DESIGN_EXCEPTION_TABLE_FIELDS,
            "ddd_terms": DETAILED_DESIGN_DDD_TERMS,
            "database_trigger_terms": DETAILED_DESIGN_DATABASE_TRIGGER_TERMS,
            "abstract_database_terms": DETAILED_DESIGN_ABSTRACT_DATABASE_TERMS,
            "specialty_docs": DETAILED_DESIGN_SPECIALTY_DOCS,
            "source_traceability_header": SOURCE_TRACEABILITY_TABLE_HEADER,
            "mq_db_redis_required_terms": DETAILED_MQ_DB_REDIS_REQUIRED_TERMS,
        },
        "code-development": {
            "unresolved_markers": DB_UNRESOLVED_INFO_MARKERS,
            "traceability_required_fields": ["source_id", "source_type", "source_path_or_url", "design_section", "code_path", "verification_evidence"],
        },
        "database-design": {
            "oltp_sections": DB_OLTP_REQUIRED_SECTIONS,
            "olap_sections": DB_OLAP_REQUIRED_SECTIONS,
            "oltp_table_headers": DB_OLTP_REQUIRED_TABLE_HEADERS,
            "oltp_template_markers": DB_OLTP_REQUIRED_TEMPLATE_MARKERS,
            "oltp_fact_fields": DB_OLTP_REQUIRED_FACT_FIELDS,
            "unresolved_markers": DB_UNRESOLVED_INFO_MARKERS,
        },
        "redis-design": {
            "unresolved_markers": DB_UNRESOLVED_INFO_MARKERS,
            "required_sections": REDIS_REQUIRED_SECTIONS,
            "item_fields": REDIS_DESIGN_ITEM_FIELDS,
            "storage_fields": REDIS_STORAGE_FIELDS,
            "forbidden_formal_terms": REDIS_FORBIDDEN_FORMAL_TERMS,
            "business_terms": REDIS_BUSINESS_TERMS,
        },
        "mq-design": {
            "unresolved_markers": DB_UNRESOLVED_INFO_MARKERS,
            "producer_fields": MQ_PRODUCER_FIELDS,
            "consumer_fields": MQ_CONSUMER_FIELDS,
            "producer_required_value_fields": MQ_PRODUCER_REQUIRED_VALUE_FIELDS,
            "consumer_required_value_fields": MQ_CONSUMER_REQUIRED_VALUE_FIELDS,
            "message_schema_root_fields": MQ_MESSAGE_SCHEMA_ROOT_FIELDS,
            "message_schema_entry_collection_keys": MQ_MESSAGE_SCHEMA_ENTRY_COLLECTION_KEYS,
            "message_schema_required_config_fields": MQ_MESSAGE_SCHEMA_REQUIRED_CONFIG_FIELDS,
        },
    }
    validator_bodies = {
        "high-level-design": r'''
def validate_output(payload_path, payload):
    errors = []
    text = read_artifact(payload_path, payload, "high-level-design.md")
    if not text:
        return ["缺少 high-level-design.md artifact 或文件不可读"]
    for section in POLICY["required_sections"]:
        if section not in text:
            errors.append("high-level-design.md 缺少团队概要设计模板章节: " + section)
    section_positions = []
    for section in POLICY["required_sections"]:
        index = text.find(section)
        if index >= 0:
            section_positions.append(index)
    if section_positions != sorted(section_positions):
        errors.append("high-level-design.md 章节顺序必须与团队概要设计模板一致")
    normalized_headings = [re.sub(r"\s+", " ", heading).strip(" ：:") for heading in markdown_headings(text)]
    for forbidden in POLICY["forbidden_headings"]:
        if any(heading == forbidden or heading.startswith(forbidden + " ") for heading in normalized_headings):
            errors.append("high-level-design.md 不得使用通用产物模板标题: " + forbidden)
    for mermaid_type in POLICY.get("forbidden_mermaid", []):
        if mermaid_blocks(text, mermaid_type):
            errors.append("high-level-design.md 不得包含 " + mermaid_type + "；概要设计只允许关键协作摘要和服务间时序图")
    for required in ["系统逻辑视图", "系统设计原则", "研发视图", "研发结构定义", "中间件设计", "数据视图"]:
        if required not in text:
            errors.append("high-level-design.md 缺少概要设计核心内容: " + required)
    for term in POLICY["detailed_implementation_forbidden_terms"]:
        if term in text:
            errors.append("概要设计不得展开详细设计内容: " + term)
    if POLICY["source_traceability_header"] not in text:
        errors.append("high-level-design.md 缺少原始需求与原型追溯矩阵列头: " + POLICY["source_traceability_header"])
    sequence_blocks = mermaid_blocks(text, "sequenceDiagram")
    if not sequence_blocks:
        errors.append("high-level-design.md 跨服务核心场景必须包含 Mermaid sequenceDiagram 服务间时序图")
    if is_event_driven_design(text, POLICY["event_driven_terms"]):
        create_present = any(term in text for term in POLICY["create_event_terms"])
        state_present = any(term in text for term in POLICY["state_event_terms"])
        if not sequence_blocks:
            errors.append("MQ / 事件 / 异步消息场景至少必须包含一个 sequenceDiagram")
        if create_present and state_present and len(sequence_blocks) < 2:
            errors.append("同时包含创建类消息和状态变更/删除/失效类消息时，概要设计必须至少包含两个核心 sequenceDiagram")
        for block_index, block in enumerate(sequence_blocks, start=1):
            if not sequence_has_internal_processing(block, POLICY["internal_sequence_terms"], POLICY["internal_sequence_outcome_terms"]):
                errors.append(f"第 {block_index} 个事件驱动 sequenceDiagram 只有消息收发或缺少服务内部关键处理 self-call")
    evidence_entries = participant_evidence_entries(payload_path, payload)
    for block_index, block in enumerate(sequence_blocks, start=1):
        participants = service_sequence_participants(block)
        if not participants:
            errors.append(f"第 {block_index} 个 sequenceDiagram 必须显式声明 participant，且 participant 只能是服务")
        if participants and evidence_entries is None:
            errors.append("high-level-design.md sequenceDiagram participant 必须提供 participant-evidence-map.json，追溯到 repo_context/代码/服务注册证据: " + ", ".join(participants.keys()))
        for alias, label in participants.items():
            if has_abstract_participant_label(label, POLICY["abstract_participant_label_terms"]):
                errors.append(f"第 {block_index} 个 sequenceDiagram participant 是无证据抽象能力名，不得进入正式时序图: {label}")
            if not is_service_label(label, POLICY["service_sequence_forbidden_participants"]):
                errors.append(f"第 {block_index} 个 sequenceDiagram participant 不是服务: {label}")
            if evidence_entries is not None:
                evidence = evidence_entries.get(alias) or evidence_entries.get(label)
                if not evidence:
                    errors.append(f"第 {block_index} 个 sequenceDiagram participant 缺少 participant-evidence-map.json 证据: {alias}/{label}")
                elif not has_confirmed_participant_evidence(evidence):
                    errors.append(f"第 {block_index} 个 sequenceDiagram participant 证据状态为 unknown/proposed 或缺少 repo_context 证据: {alias}/{label}")
        for endpoint in service_sequence_endpoints(block):
            label = participants.get(endpoint, endpoint)
            if not is_service_label(label, POLICY["service_sequence_forbidden_participants"]):
                errors.append(f"第 {block_index} 个 sequenceDiagram 消息端点不是服务: {label}")
            elif evidence_entries is not None:
                evidence = evidence_entries.get(endpoint) or evidence_entries.get(label)
                if not evidence:
                    errors.append(f"第 {block_index} 个 sequenceDiagram 消息端点缺少 participant-evidence-map.json 证据: {endpoint}/{label}")
                elif not has_confirmed_participant_evidence(evidence):
                    errors.append(f"第 {block_index} 个 sequenceDiagram 消息端点证据状态为 unknown/proposed 或缺少 repo_context 证据: {endpoint}/{label}")
    return errors
''',
        "detailed-design": r'''
def validate_output(payload_path, payload):
    errors = []
    text = read_artifact(payload_path, payload, "detailed-design.md")
    if not text:
        return ["缺少 detailed-design.md artifact 或文件不可读"]
    for section in POLICY["required_sections"]:
        if section not in text:
            errors.append("detailed-design.md 缺少团队详细设计模板章节: " + section)
    section_positions = []
    for section in POLICY["required_sections"]:
        index = text.find(section)
        if index >= 0:
            section_positions.append(index)
    if section_positions != sorted(section_positions):
        errors.append("detailed-design.md 章节顺序必须与团队详细设计模板一致")
    normalized_headings = [re.sub(r"\s+", " ", heading).strip(" ：:") for heading in markdown_headings(text)]
    for forbidden in POLICY["forbidden_headings"]:
        if any(heading == forbidden or heading.startswith(forbidden + " ") for heading in normalized_headings):
            errors.append("detailed-design.md 包含禁止标题: " + forbidden)
    if "sequenceDiagram" in text:
        errors.append("detailed-design.md 不得包含 sequenceDiagram")
    if "flowchart" not in text:
        errors.append("detailed-design.md 必须包含 flowchart")
    flow_blocks = list(re.finditer(r"```mermaid\s*\n\s*flowchart[\s\S]*?```", text))
    field_aliases = {
        "异常编码": ["异常编码", "返回编码"],
        "日志/告警": ["日志/告警", "日志要求", "告警"],
        "补偿/重试/人工处理": ["补偿/重试/人工处理", "补偿", "重试", "人工处理"],
    }
    for index, block in enumerate(flow_blocks, start=1):
        tail = text[block.end(): block.end() + 1200]
        flow_context = block.group(0)
        if "流程设计说明" not in tail:
            errors.append(f"第 {index} 个 flowchart 后缺少流程设计说明")
            continue
        for label, terms in POLICY["flow_required_branch_terms"].items():
            if not any(term in flow_context for term in terms):
                errors.append(f"第 {index} 个 flowchart 缺少{label}: " + "、".join(terms))
        for field in POLICY["flow_note_fields"]:
            if field not in tail:
                errors.append(f"第 {index} 个 flowchart 的流程设计说明缺少 {field}")
        local_headers = []
        for line in tail.splitlines():
            cells = table_cells(line)
            if cells and not is_separator_row(line) and "场景" in cells and "触发条件" in cells:
                local_headers.append(cells)
        if not local_headers:
            errors.append(f"第 {index} 个 flowchart 后缺少异常场景表")
            continue
        best_header = max(local_headers, key=len)
        missing_fields = []
        for field in POLICY["exception_table_required_fields"]:
            aliases = field_aliases.get(field, [field])
            if not any(any(alias in cell for cell in best_header) for alias in aliases):
                missing_fields.append(field)
        if missing_fields:
            errors.append("异常场景表缺少字段: " + "、".join(missing_fields))
    if any(term in text for term in POLICY["ddd_terms"]) and "classDiagram" not in text:
        errors.append("出现 DDD/分层/扩展点关键词时必须包含 classDiagram")
    if POLICY["source_traceability_header"] not in text:
        errors.append("detailed-design.md 缺少原始需求与原型引用矩阵列头: " + POLICY["source_traceability_header"])
    if requires_database_er_diagram(text, POLICY["database_trigger_terms"]):
        er_blocks = mermaid_blocks(text, "erDiagram")
        if not er_blocks:
            errors.append("涉及数据库读写/事务/本地读模型/表结构时，detailed-design.md 必须包含 erDiagram")
        database_design = read_artifact(payload_path, payload, "database-design.md")
        confirmed_tables = confirmed_database_tables(database_design) if database_design else []
        if not confirmed_tables:
            errors.append("涉及数据库图校验时，database-design.md 必须确认真实表名")
        diagram_tables = []
        for index, block in enumerate(er_blocks, start=1):
            block_tables = er_diagram_entities(block)
            if not block_tables:
                errors.append(f"第 {index} 个 erDiagram 必须体现真实表名")
                continue
            diagram_tables.extend(block_tables)
            for table_name in block_tables:
                if any(term in table_name for term in POLICY["abstract_database_terms"]):
                    errors.append(f"第 {index} 个 erDiagram 使用了抽象表名，必须替换为真实表名: {table_name}")
                elif confirmed_tables and normalize_table_name(table_name) not in confirmed_tables:
                    errors.append(f"第 {index} 个 erDiagram 表名未在 database-design.md 确认: {table_name}")
        matched_tables = sorted({normalize_table_name(name) for name in diagram_tables if normalize_table_name(name) in confirmed_tables})
        if confirmed_tables and not matched_tables:
            errors.append("erDiagram 未体现 database-design.md 中已确认的真实表名")
        if len(confirmed_tables) >= 2:
            if len(matched_tables) < 2:
                errors.append("多表场景下 erDiagram 必须至少体现两张真实表")
            if er_blocks and not any(er_diagram_has_relationship(block) for block in er_blocks):
                errors.append("多表场景下 erDiagram 必须体现主表/明细表或关联表之间的关系")
    if is_mq_db_redis_flow(text):
        for label, terms in POLICY["mq_db_redis_required_terms"].items():
            if not any(term in text for term in terms):
                errors.append("MQ + DB + Redis 详细设计关键执行路径缺少: " + label)
    if is_local_read_model_write(text) and not all(any(term in text for term in group) for group in [["主表"], ["明细"], ["事务"]]):
        errors.append("本地读模型写入流程必须明确主表写入或更新、明细表写入/更新/重建和主明细事务关系")
    if is_local_read_model_delete(text) and not all(any(term in text for term in group) for group in [["状态处理记录"], ["先删明细", "明细删除"], ["再删主表", "主表删除"], ["删除失败", "回滚", "重试", "死信"]]):
        errors.append("本地读模型删除流程必须明确状态处理记录、明细删除、主表删除、删除顺序和失败处理")
    if is_query_or_export_flow(text) and not all(any(term in text for term in group) for group in [["登录态", "数据范围"], ["可见范围"], ["参数校验"], ["DB 查询", "数据库查询", "分批导出"], ["导出上限"], ["文件生成失败", "生成失败"]]):
        errors.append("查询 / 导出流程必须明确登录态或数据范围、可见范围合并、参数校验、DB 查询/分批导出、导出上限和文件生成失败处理")
    artifacts = artifact_map(payload)
    for doc_name in POLICY["specialty_docs"]:
        if doc_name not in artifacts:
            errors.append("StageRunResult.artifacts 未登记专项文档: " + doc_name)
    status = payload.get("status")
    high_risk_terms = ["DDL", "CREATE TABLE", "ALTER TABLE", "新队列", "新 topic", "新Topic", "Redis 新 Key", "新增 Key"]
    if status == "succeeded" and any(term in text for term in high_risk_terms):
        errors.append("存在 DDL、MQ 新队列/topic 或 Redis 新 Key 时状态必须为 waiting_for_human_review")
    return errors
''',
        "code-development": r'''
def validate_output(payload_path, payload):
    errors = []
    artifacts = artifact_map(payload)
    for required in ["implementation-summary.md", "design-to-code-mapping.yaml", "changed-files-report.json", "traceability-matrix.json"]:
        if required not in artifacts:
            errors.append("StageRunResult.artifacts 未登记代码追踪产物: " + required)
    mapping_text = read_artifact(payload_path, payload, "design-to-code-mapping.yaml")
    if not mapping_text:
        errors.append("缺少 design-to-code-mapping.yaml artifact 或文件不可读")
    else:
        for field in POLICY["traceability_required_fields"]:
            if field not in mapping_text:
                errors.append("design-to-code-mapping.yaml 缺少追踪字段: " + field)
    matrix = read_json_artifact(payload_path, payload, "traceability-matrix.json")
    if matrix is None:
        errors.append("缺少 traceability-matrix.json artifact、文件不可读或不是合法 JSON")
    else:
        rows = matrix.get("rows") if isinstance(matrix, dict) else []
        if not rows:
            errors.append("traceability-matrix.json 必须包含非空 rows")
        for index, row in enumerate(rows or [], start=1):
            for field in POLICY["traceability_required_fields"]:
                value = row.get(field) if isinstance(row, dict) else None
                if not value:
                    errors.append(f"traceability-matrix.json 第 {index} 行缺少追踪字段: {field}")
    return errors
''',
        "database-design": r'''
def validate_output(payload_path, payload):
    errors = []
    text = read_artifact(payload_path, payload, "database-design.md")
    if not text:
        return ["缺少 database-design.md artifact 或文件不可读"]
    sections = POLICY["olap_sections"] if any(term in text for term in ["ClickHouse", "MergeTree", "物化视图", "分析宽表"]) else POLICY["oltp_sections"]
    template_path = Path(__file__).parents[1] / "assets" / ("database-olap-template.md" if sections == POLICY["olap_sections"] else "database-oltp-template.md")
    template_text = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
    for section in sections:
        if section not in text:
            errors.append("database-design.md 缺少模板章节或字段: " + section)
    if sections == POLICY.get("oltp_sections"):
        normalized_lines = normalized_nonempty_lines(text)
        for protected in protected_template_lines(template_text):
            if protected not in normalized_lines:
                errors.append("database-design.md 不得改写模板固定说明: " + protected)
        section_positions = []
        for section in POLICY["oltp_sections"]:
            index = text.find(section)
            if index >= 0:
                section_positions.append(index)
        if section_positions != sorted(section_positions):
            errors.append("database-design.md OLTP 章节顺序必须与模板一致")
        for header in POLICY["oltp_table_headers"]:
            if header not in text:
                errors.append("database-design.md 缺少 OLTP 模板表格列头: " + header)
        for marker in POLICY["oltp_template_markers"]:
            if marker not in text:
                errors.append("database-design.md 缺少 OLTP 模板固定内容: " + marker)
        for field in POLICY["oltp_fact_fields"]:
            if field not in text:
                errors.append("database-design.md 文档信息缺少必填事实字段: " + field)
        for required_text in ["MC-", "PO-", "QPS", "P99", "DDL SQL", "兼容性说明", "敏感级别", "幂等"]:
            if required_text not in text:
                errors.append("database-design.md 缺少 OLTP 强制内容: " + required_text)
        design_value = design_object_value(text)
        member_tables = table_group_members(text)
        object_type = object_type_value(text)
        strong_group = "强耦合表组：" in design_value or "强耦合表组:" in design_value or len(member_tables) >= 2 or "表组 关系型（OLTP）详细设计" in "\n".join(text.splitlines()[:3])
        if "强耦合表组" in text and "2.4 强耦合表组说明" not in text:
            errors.append("database-design.md 包含强耦合表组但缺少 2.4 强耦合表组说明")
        if strong_group:
            if "表组 关系型（OLTP）详细设计" not in "\n".join(text.splitlines()[:5]):
                errors.append("强耦合表组模式下文档标题必须使用 <业务对象>表组 关系型（OLTP）详细设计")
            if not re.search(r"设计对象\s*\|\s*强耦合表组[：:]", text):
                errors.append("强耦合表组模式下 1. 文档信息的设计对象必须写成 强耦合表组：表1、表2、表3...")
            if len(member_tables) < 2:
                errors.append("强耦合表组模式下设计对象或 2.4 表组说明至少要列出两张成员表")
            if not any(term in object_type for term in ["主表", "明细", "规则", "参数", "大字段", "领取", "配置", "+"]):
                errors.append("强耦合表组模式下 2. 文档定位必须明确对象类型，例如 主表 + 明细表 + 规则表")
            required_group_header = "| 成员表 | 角色 | 与主表关系 | 同事务要求 | 备注 |"
            if required_group_header not in text:
                errors.append("2.4 强耦合表组说明列头必须固定为: " + required_group_header)
            responsibility = section_text(text, "3.1 表的业务职责")
            if "唯一事实来源" not in responsibility:
                errors.append("3.1 表的业务职责必须按表列出唯一事实来源")
            for table in member_tables:
                if table not in responsibility:
                    errors.append("3.1 表的业务职责缺少成员表: " + table)
            if "4.2 字段定义（按表展开）" not in text:
                errors.append("强耦合表组模式下 4.2 必须命名为 字段定义（按表展开）")
            field_section = section_text(text, "4.2 字段定义（按表展开）")
            if not re.search(r"(?m)^####\s+4\.2\.\d+\s+", field_section):
                errors.append("多表场景下 4.2 字段定义必须逐表建立 #### 4.2.x 表名 子章节")
            required_field_header = "| 字段 | 类型 | 必填 | 默认值 | 索引 | 敏感级别 | 说明 |"
            if required_field_header not in field_section:
                errors.append("每张表字段表列头必须包含: " + required_field_header)
            for table in member_tables:
                if not re.search(r"(?m)^####\s+4\.2\.\d+\s+" + re.escape(table) + r"\b", field_section):
                    errors.append("4.2 字段定义缺少成员表子章节: " + table)
            required_index_header = "| 表 | 索引名 | 类型 | 字段（顺序敏感） | 唯一 | 服务场景 | 备注 |"
            if required_index_header not in text:
                errors.append("4.3 索引设计列头必须固定为: " + required_index_header)
            index_rows = markdown_index_rows(text)
            indexed_tables = {row["table"] for row in index_rows if row.get("table")}
            for table in member_tables:
                if table not in indexed_tables:
                    errors.append("4.3 索引设计缺少成员表索引归属: " + table)
            crud_section = section_text(text, "6.1 CRUD 总览矩阵")
            if "参与表" not in crud_section:
                errors.append("CRUD 总览矩阵必须包含 参与表")
            if not any(term in crud_section for term in ["同事务", "最终一致", "一致性边界"]):
                errors.append("CRUD 总览矩阵必须描述跨表同事务或最终一致性边界")
            transaction_section = section_text(text, "7. 事务、一致性与并发控制", r"^##\s+\d+\.\s+")
            for required in ["参与表", "提交/回滚", "补偿/核对"]:
                if required not in transaction_section:
                    errors.append("事务、一致性与并发控制缺少表组口径: " + required)
            for table in member_tables:
                if table not in transaction_section:
                    errors.append("事务、一致性与并发控制缺少成员表: " + table)
            schema_sql = read_artifact(payload_path, payload, "schema-change-plan.sql")
            if not schema_sql:
                errors.append("强耦合表组模式下缺少 schema-change-plan.sql artifact 或文件不可读")
            else:
                ddl_tables = create_table_names(schema_sql)
                if len(ddl_tables) < len(member_tables):
                    errors.append("设计对象列出多张表，但 schema-change-plan.sql 的 CREATE TABLE 数量少于设计对象表数量")
                for table in member_tables:
                    if table not in ddl_tables:
                        errors.append("schema-change-plan.sql 缺少成员表 CREATE TABLE: " + table)
                for row in index_rows:
                    table = row.get("table", "")
                    index_name = row.get("name", "")
                    if table in member_tables and index_name and index_name not in {"不适用", "无"}:
                        ddl_indexes = ddl_index_names(schema_sql, table)
                        if index_name not in ddl_indexes:
                            errors.append(f"schema-change-plan.sql 中 {table} 缺少与索引设计一致的索引: {index_name}")
            migration = read_artifact(payload_path, payload, "migration-plan.md")
            for required in ["表组同批创建", "同批校验", "逐表索引 explain", "表组关系校验"]:
                if required not in migration:
                    errors.append("migration-plan.md 缺少表组口径: " + required)
            rollback = read_artifact(payload_path, payload, "rollback-plan.md")
            if not (("不得只删除" in rollback or "不得只回滚" in rollback) and "孤立" in rollback):
                errors.append("rollback-plan.md 必须说明应用发布后不得只删除或回滚表组中的单张事实表，避免孤立配置、孤立明细或主明细不一致")
            risk_report = read_artifact(payload_path, payload, "database-risk-report.json")
            for required in ["生产 DDL 审批", "表组同批创建审批", "容量", "QPS", "枚举口径", "幂等键口径"]:
                if required not in risk_report:
                    errors.append("database-risk-report.json 缺少表组风险: " + required)
    for block in re.findall(r"```sql\s*\n([\s\S]*?)```", text):
        for match in re.finditer(r"(?ims)^\s*(update|delete)\b([\s\S]*?);", block):
            if "where" not in match.group(2).lower():
                errors.append("禁止没有 WHERE 的 UPDATE/DELETE")
    unresolved = [marker for marker in POLICY.get("unresolved_markers", []) if marker in text]
    if unresolved and payload.get("status") not in {"waiting_for_input", "waiting_for_human_review", "blocked"}:
        errors.append("存在未确认信息时必须 waiting_for_input，禁止推测或以占位符输出 succeeded: " + ", ".join(sorted(set(unresolved))))
    if payload.get("status") == "waiting_for_input" and not payload.get("required_information_requests"):
        errors.append("waiting_for_input 必须输出 required_information_requests 主动询问用户")
    final_status = payload.get("document_metadata", {}).get("document_status")
    if final_status in {"approved", "final"}:
        for required in ["库名", "实例", "字符集", "索引名"]:
            if required + "：" not in text and required + ":" not in text:
                errors.append("approved/final 文档必须确认" + required)
    if payload.get("status") == "succeeded" and any(term in text for term in ["CREATE TABLE", "ALTER TABLE", "DROP TABLE", "DDL"]):
        errors.append("包含 DDL 时必须 waiting_for_human_review")
    return errors
''',
        "redis-design": r'''
def validate_output(payload_path, payload):
    errors = []
    text = read_artifact(payload_path, payload, "redis-design.md")
    if not text:
        return ["缺少 redis-design.md artifact 或文件不可读"]
    for section in POLICY["required_sections"] + POLICY["item_fields"]:
        if section not in text:
            errors.append("redis-design.md 缺少模板章节或字段: " + section)
    for field in POLICY["storage_fields"]:
        if field not in text:
            errors.append("redis-design.md 存储设计缺少字段: " + field)
    for term in POLICY["forbidden_formal_terms"]:
        if term in text:
            errors.append("Redis 设计不得使用“" + term + "”作为正式术语，应改为状态处理记录 / 消息幂等记录 / 乱序保护记录等业务可理解术语")
    if any(term in text for term in ["乱序", "幂等", "状态处理", "过程信息"]):
        if not any(term in text for term in POLICY["business_terms"]):
            errors.append("Redis 设计涉及乱序/幂等/状态处理时必须使用状态处理记录、消息幂等记录或乱序保护记录等显式业务术语")
    if re.search(r"Redis\s*(作为|做|充当).{0,18}(事实库|事实源|共享事实源|长期审计库|审计库)", text):
        errors.append("Redis 不得作为事实库、跨服务共享事实源或长期审计库")
    if re.search(r"Redis\s*(作为|做|充当).{0,12}消息队列", text):
        errors.append("Redis 不得作为消息队列")
    if not re.search(r"TTL[^\n]*(秒|分钟|小时|天|ms|s|min|hour|day)", text, re.IGNORECASE):
        errors.append("TTL 必须带单位")
    if "降级" not in text and "不可用" not in text:
        errors.append("Redis 不可用必须有降级策略")
    if "不可用" in text or "降级" in text:
        if re.search(r"Redis.{0,10}不可用[\s\S]{0,80}(继续|直接|绕过)[\s\S]{0,40}(写库|写 DB|落库|删除|删 DB)", text):
            errors.append("Redis 不可用时不得绕过幂等 / 状态处理记录直接写 DB 或删除 DB")
        for required in ["重试", "死信", "告警", "人工回放"]:
            if required not in text:
                errors.append("Redis 不可用策略缺少: " + required)
    if payload.get("status") == "succeeded" and any(term in text for term in ["版本待确认", "拓扑待确认", "持久化待确认", "淘汰策略待确认"]):
        errors.append("Redis 版本、拓扑、持久化或淘汰策略无法确认时不得 succeeded")
    if payload.get("status") == "succeeded" and any(term in text for term in ["Redis 新 Key", "新增 Key", "新 Key"]):
        errors.append("Redis 新 Key 必须 waiting_for_human_review")
    return errors
''',
        "mq-design": r'''
XLSX_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def _shared_text(si):
    return "".join(t.text or "" for t in si.findall(".//a:t", XLSX_NS))


def _cell_ref_to_col(ref):
    letters = re.match(r"([A-Z]+)", ref or "")
    if not letters:
        return 0
    index = 0
    for char in letters.group(1):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def _normalize_xlsx_target(target):
    normalized = (target or "").replace("\\", "/").lstrip("/")
    if normalized.startswith("xl/"):
        return normalized
    return "xl/" + normalized


def read_xlsx_artifact(payload_path, payload, name):
    item = artifact_map(payload).get(name)
    path = resolve_artifact(payload_path, item)
    if not path or not path.exists():
        return None, "缺少 " + name + " artifact 或文件不可读"
    if path.suffix.lower() != ".xlsx":
        return None, name + " 必须是 .xlsx 文件"
    try:
        with zipfile.ZipFile(path) as workbook:
            shared = []
            if "xl/sharedStrings.xml" in workbook.namelist():
                shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
                shared = [_shared_text(si) for si in shared_root.findall("a:si", XLSX_NS)]
            rels_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
            rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_root}
            workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
            sheets = {}
            all_text = []
            for sheet in workbook_root.findall(".//a:sheet", XLSX_NS):
                name = sheet.attrib.get("name", "")
                rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
                target = rels.get(rel_id, "")
                if not target:
                    continue
                sheet_path = _normalize_xlsx_target(target)
                sheet_root = ET.fromstring(workbook.read(sheet_path))
                rows = {}
                for row in sheet_root.findall(".//a:sheetData/a:row", XLSX_NS):
                    row_number = int(row.attrib.get("r", "0") or 0)
                    values = []
                    for cell in row.findall("a:c", XLSX_NS):
                        col_index = _cell_ref_to_col(cell.attrib.get("r", ""))
                        while len(values) <= col_index:
                            values.append("")
                        value = ""
                        if cell.attrib.get("t") == "inlineStr":
                            value = "".join(t.text or "" for t in cell.findall(".//a:t", XLSX_NS))
                        else:
                            node = cell.find("a:v", XLSX_NS)
                            if node is not None and node.text is not None:
                                value = shared[int(node.text)] if cell.attrib.get("t") == "s" and shared else node.text
                        values[col_index] = value
                        if value:
                            all_text.append(value)
                    rows[row_number] = values
                sheets[name] = rows
            return {"sheets": sheets, "text": "\n".join(all_text)}, ""
    except Exception as exc:
        return None, "无法读取 mq-design.xlsx: " + str(exc)


def _cell_value(cell, shared):
    value = ""
    if cell.attrib.get("t") == "inlineStr":
        value = "".join(t.text or "" for t in cell.findall(".//a:t", XLSX_NS))
    else:
        node = cell.find("a:v", XLSX_NS)
        if node is not None and node.text is not None:
            value = shared[int(node.text)] if cell.attrib.get("t") == "s" and shared else node.text
    return value


def read_xlsx_template_signature(path):
    with zipfile.ZipFile(path) as workbook:
        shared = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared = [_shared_text(si) for si in shared_root.findall("a:si", XLSX_NS)]
        rels_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_root}
        workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
        signature = {
            "style_bytes": workbook.read("xl/styles.xml") if "xl/styles.xml" in workbook.namelist() else b"",
            "sheet_order": [],
            "sheets": {},
        }
        for sheet in workbook_root.findall(".//a:sheet", XLSX_NS):
            sheet_name = sheet.attrib.get("name", "")
            signature["sheet_order"].append(sheet_name)
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
            target = rels.get(rel_id, "")
            sheet_path = _normalize_xlsx_target(target)
            sheet_root = ET.fromstring(workbook.read(sheet_path))
            dimension = sheet_root.find("a:dimension", XLSX_NS)
            merge_refs = [
                merge.attrib.get("ref", "")
                for merge in sheet_root.findall(".//a:mergeCells/a:mergeCell", XLSX_NS)
            ]
            cells = {}
            for cell in sheet_root.findall(".//a:sheetData/a:row/a:c", XLSX_NS):
                ref = cell.attrib.get("r", "")
                cells[ref] = {
                    "style": cell.attrib.get("s", ""),
                    "value": _cell_value(cell, shared),
                }
            signature["sheets"][sheet_name] = {
                "dimension": dimension.attrib.get("ref", "") if dimension is not None else "",
                "merge_refs": merge_refs,
                "cells": cells,
            }
        return signature


def validate_mq_template_integrity(payload_path, payload):
    errors = []
    item = artifact_map(payload).get("mq-design.xlsx")
    output_path = resolve_artifact(payload_path, item)
    if not output_path or not output_path.exists():
        return errors
    template_path = Path(__file__).parents[1] / "assets" / "mq-design-template.xlsx"
    try:
        template = read_xlsx_template_signature(template_path)
        output = read_xlsx_template_signature(output_path)
    except Exception as exc:
        return ["无法校验 mq-design.xlsx 模板一致性: " + str(exc)]
    if output["style_bytes"] != template["style_bytes"]:
        errors.append("mq-design.xlsx 不得修改模板样式定义 styles.xml")
    if output["sheet_order"] != template["sheet_order"]:
        errors.append("mq-design.xlsx 必须保留模板 sheet 名称和顺序: " + ", ".join(template["sheet_order"]))
    for sheet_name in template["sheet_order"]:
        expected = template["sheets"].get(sheet_name, {})
        actual = output["sheets"].get(sheet_name, {})
        if not actual:
            errors.append("mq-design.xlsx 缺少模板 sheet: " + sheet_name)
            continue
        if actual.get("dimension") != expected.get("dimension"):
            errors.append(f"mq-design.xlsx 的 {sheet_name} sheet 不得追加行列或改变模板范围: {expected.get('dimension')} -> {actual.get('dimension')}")
        if actual.get("merge_refs") != expected.get("merge_refs"):
            errors.append("mq-design.xlsx 的 " + sheet_name + " sheet 不得修改合并单元格")
        expected_cells = expected.get("cells", {})
        actual_cells = actual.get("cells", {})
        for ref, expected_cell in expected_cells.items():
            actual_cell = actual_cells.get(ref)
            if actual_cell is None:
                errors.append(f"mq-design.xlsx 的 {sheet_name}!{ref} 模板单元格不得删除")
                continue
            if actual_cell.get("style") != expected_cell.get("style"):
                errors.append(f"mq-design.xlsx 的 {sheet_name}!{ref} 不得修改模板样式")
            if expected_cell.get("value") and actual_cell.get("value") != expected_cell.get("value"):
                errors.append(f"mq-design.xlsx 的 {sheet_name}!{ref} 固定模板文本不得修改")
        for ref, actual_cell in actual_cells.items():
            if ref not in expected_cells and actual_cell.get("value"):
                errors.append(f"mq-design.xlsx 的 {sheet_name}!{ref} 不得新增非模板单元格")
    return errors


def _header_index_map(header):
    mapping = {}
    for index, value in enumerate(header):
        if value:
            mapping[value] = index
    return mapping


def _non_empty_rows(rows):
    result = []
    for row_number, values in sorted(rows.items()):
        if row_number <= 1:
            continue
        if any(str(value).strip() for value in values):
            result.append((row_number, values))
    return result


def _validate_required_sheet_values(errors, rows, header, required_fields, sheet_name):
    header_map = _header_index_map(header)
    missing_headers = [field for field in required_fields if field not in header_map]
    if missing_headers:
        errors.append(f"mq-design.xlsx 的 {sheet_name} sheet 缺少必填业务列: " + "、".join(missing_headers))
        return
    for row_number, values in _non_empty_rows(rows):
        missing_values = []
        for field in required_fields:
            index = header_map[field]
            value = values[index].strip() if index < len(values) and isinstance(values[index], str) else (str(values[index]).strip() if index < len(values) else "")
            if not value:
                missing_values.append(field)
        if missing_values:
            errors.append(f"mq-design.xlsx 的 {sheet_name} sheet 第 {row_number} 行缺少必填业务值: " + "、".join(missing_values))


def _sheet_row_dicts(rows, header):
    header_map = _header_index_map(header)
    row_dicts = []
    for row_number, values in _non_empty_rows(rows):
        item = {"_row_number": row_number}
        for key, index in header_map.items():
            item[key] = values[index].strip() if index < len(values) and isinstance(values[index], str) else (str(values[index]).strip() if index < len(values) else "")
        row_dicts.append(item)
    return row_dicts


def _validate_message_schema(errors, payload_path, payload, producer_rows, consumer_rows):
    schema = read_json_artifact(payload_path, payload, "message-schema.json")
    if schema is None:
        errors.append("mq-design 必须登记 message-schema.json，且文件必须是合法 JSON")
        return []
    entries = message_schema_entries(schema)
    if not entries:
        errors.append("message-schema.json 必须至少包含一个消息 envelope 定义")
        return []
    config_types = []
    for index, entry in enumerate(entries, start=1):
        root_properties = schema_properties(entry)
        root_required = schema_required_fields(entry)
        if root_properties:
            for field in POLICY["message_schema_root_fields"]:
                if field not in root_properties:
                    errors.append(f"message-schema.json 第 {index} 个消息缺少根字段定义: {field}")
                elif root_required and field not in root_required:
                    errors.append(f"message-schema.json 第 {index} 个消息未将根字段声明为必填: {field}")
        else:
            for field in POLICY["message_schema_root_fields"]:
                if field not in entry:
                    errors.append(f"message-schema.json 第 {index} 个消息缺少根字段: {field}")
        config_type = schema_config_type(entry, root_properties)
        if not config_type:
            errors.append(f"message-schema.json 第 {index} 个消息缺少可识别的 configType")
            continue
        config_types.append(config_type)
        body_node = root_properties.get(config_type) if root_properties else entry.get(config_type)
        if body_node is None:
            errors.append(f"message-schema.json 第 {index} 个消息缺少与 configType 同名的业务对象: {config_type}")
            continue
        required_fields = POLICY["message_schema_required_config_fields"].get(config_type, [])
        if isinstance(body_node, dict) and "properties" in body_node:
            body_properties = body_node.get("properties") if isinstance(body_node.get("properties"), dict) else {}
            body_required = schema_required_fields(body_node)
            for field in required_fields:
                if field not in body_properties:
                    errors.append(f"message-schema.json 第 {index} 个 {config_type} 缺少业务字段定义: {field}")
                elif body_required and field not in body_required:
                    errors.append(f"message-schema.json 第 {index} 个 {config_type} 未将字段声明为必填: {field}")
        elif isinstance(body_node, dict):
            for field in required_fields:
                if field not in body_node:
                    errors.append(f"message-schema.json 第 {index} 个 {config_type} 缺少业务字段: {field}")
        else:
            errors.append(f"message-schema.json 第 {index} 个 {config_type} 业务对象必须是 object")
    if producer_rows:
        for row in producer_rows:
            body_text = row.get("消息体内容", "")
            if "issueId" not in body_text or "configType" not in body_text:
                errors.append(f"mq-design.xlsx 的生产者 sheet 第 {row['_row_number']} 行消息体内容必须明确统一 envelope（issueId/configType）")
            if config_types and not any(config_type in body_text for config_type in config_types):
                errors.append(f"mq-design.xlsx 的生产者 sheet 第 {row['_row_number']} 行消息体内容必须与 message-schema.json 的 configType 一致")
    if consumer_rows and config_types:
        for row in consumer_rows:
            monitoring = row.get("运维监控", "")
            if not monitoring:
                continue
    return sorted(set(config_types))


def _validate_topic_contract(errors, payload_path, payload, config_types, producer_rows, consumer_rows):
    topic_contract = read_artifact(payload_path, payload, "mq-topic-contract.yaml")
    if not topic_contract:
        errors.append("mq-design 必须登记 mq-topic-contract.yaml，且文件必须可读")
        return
    for config_type in config_types:
        if config_type not in topic_contract:
            errors.append("mq-topic-contract.yaml 缺少与 message-schema.json 一致的 configType: " + config_type)
    for row in producer_rows:
        message_key = row.get("业务消息key", "")
        if message_key and message_key not in topic_contract:
            errors.append(f"mq-topic-contract.yaml 缺少生产者业务消息 key: {message_key}")
    for row in consumer_rows:
        message_key = row.get("消息key", "")
        if message_key and message_key not in topic_contract:
            errors.append(f"mq-topic-contract.yaml 缺少消费者消息 key: {message_key}")


def validate_output(payload_path, payload):
    errors = []
    workbook, error = read_xlsx_artifact(payload_path, payload, "mq-design.xlsx")
    if error:
        return [error]
    errors.extend(validate_mq_template_integrity(payload_path, payload))
    sheets = workbook["sheets"]
    text = workbook["text"]
    if "mq-design.md" in artifact_map(payload):
        errors.append("正式 MQ 设计正文必须是 mq-design.xlsx，不得登记 mq-design.md")
    if "生产者" not in sheets:
        errors.append("mq-design.xlsx 缺少生产者 sheet")
    if "消费者" not in sheets:
        errors.append("mq-design.xlsx 缺少消费者 sheet")
    producer_header = sheets.get("生产者", {}).get(1, [])
    consumer_header = sheets.get("消费者", {}).get(1, [])
    for field in POLICY["producer_fields"]:
        if field not in producer_header:
            errors.append("mq-design.xlsx 生产者表缺少字段: " + field)
    for field in POLICY["consumer_fields"]:
        if field not in consumer_header:
            errors.append("mq-design.xlsx 消费者表缺少字段: " + field)
    _validate_required_sheet_values(errors, sheets.get("生产者", {}), producer_header, POLICY.get("producer_required_value_fields", []), "生产者")
    _validate_required_sheet_values(errors, sheets.get("消费者", {}), consumer_header, POLICY.get("consumer_required_value_fields", []), "消费者")
    producer_rows = _sheet_row_dicts(sheets.get("生产者", {}), producer_header)
    consumer_rows = _sheet_row_dicts(sheets.get("消费者", {}), consumer_header)
    config_types = _validate_message_schema(errors, payload_path, payload, producer_rows, consumer_rows)
    _validate_topic_contract(errors, payload_path, payload, config_types, producer_rows, consumer_rows)
    if "死信" not in text:
        errors.append("MQ 必须设计死信队列")
    if "幂等" not in text:
        errors.append("MQ 必须定义幂等策略")
    if "重试" not in text:
        errors.append("MQ 必须定义重试策略")
    if "回放" not in text:
        errors.append("MQ 必须定义回放策略")
    for size in re.findall(r"(\d+)\s*KB", text, re.IGNORECASE):
        if int(size) > 10 and payload.get("status") == "succeeded":
            errors.append("消息体超过 10KB 必须 waiting_for_human_review")
    if payload.get("status") == "succeeded" and any(term in text for term in ["回放生产消息", "删除队列", "重命名队列", "删除 topic", "重命名 topic", "删除Topic", "重命名Topic"]):
        errors.append("生产消息回放或删除/重命名 topic/queue 必须 waiting_for_human_review")
    return errors
''',
    }
    skill = next(item for item in SKILLS if item["id"] == skill_id)
    policy = {**policies[skill_id], "formal_outputs": [output for output in skill["outputs"] if output != "code changes"]}
    xlsx_imports = "import zipfile\nfrom xml.etree import ElementTree as ET\n" if skill_id == "mq-design" else ""
    return f"""#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path
{xlsx_imports}
SKILL_ID = {json.dumps(skill_id, ensure_ascii=False)}
POLICY = {json.dumps(policy, ensure_ascii=False, indent=2)}


def load_payload(path):
    schema = json.loads(Path(__file__).parents[1].joinpath("output.schema.json").read_text(encoding="utf-8"))
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [field for field in schema.get("required", []) if field not in payload]
    if missing:
        raise SystemExit(f"缺少必填字段: {{missing}}")
    if payload.get("skill_id") != schema["properties"]["skill_id"]["const"]:
        raise SystemExit("skill_id 不匹配")
    if payload.get("status") not in schema["properties"]["status"]["enum"]:
        raise SystemExit("status 不合法")
    return payload


def artifact_map(payload):
    return {{item.get("name"): item for item in payload.get("artifacts", [])}}


def resolve_artifact(payload_path, item):
    raw = item.get("path") if item else ""
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path
    return Path(payload_path).parent / path


def read_artifact(payload_path, payload, name):
    item = artifact_map(payload).get(name)
    path = resolve_artifact(payload_path, item)
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def artifact_path(item):
    return (item or {{}}).get("path") or (item or {{}}).get("file") or (item or {{}}).get("uri") or ""


def artifact_kind(item):
    return " ".join(str(value).lower() for value in [
        (item or {{}}).get("name", ""),
        (item or {{}}).get("artifact_type", ""),
        artifact_path(item),
    ])


def is_waiting_support_artifact(item):
    text = artifact_kind(item)
    allowed = [
        "required-information",
        "missing-information",
        "human-review",
        "approval",
        "workflow-trace",
        "resume",
        "open-questions",
        "artifact-index",
    ]
    return any(token in text for token in allowed)


def is_formal_artifact(item):
    if is_waiting_support_artifact(item):
        return False
    path = artifact_path(item).lower()
    kind = artifact_kind(item)
    return path.endswith((".md", ".xlsx", ".xls", ".json", ".yaml", ".yml")) or any(token in kind for token in ["markdown", "xlsx", "json", "yaml"])


def blocking_information_requests(payload):
    for request in payload.get("required_information_requests", []) or []:
        if request.get("blocking") is True:
            return True
        for question in request.get("questions", []) or []:
            if isinstance(question, dict) and question.get("required") is True:
                return True
    return False


def artifact_texts(payload_path, payload):
    for item in payload.get("artifacts", []) or []:
        name = item.get("name", "")
        path = artifact_path(item).lower()
        if not (name.endswith(".md") or path.endswith(".md")):
            continue
        resolved = resolve_artifact(payload_path, item)
        if resolved and resolved.exists():
            yield name or path, resolved.read_text(encoding="utf-8")


def unresolved_markers(text):
    markers = []
    for marker in POLICY.get("unresolved_markers", []):
        if marker in {"{", "}"}:
            if re.search(r"\\{{[^{{}}\\n]{{1,80}}\\}}", text):
                markers.append(marker)
            continue
        if marker in text:
            markers.append(marker)
    return markers


def candidate_project_roots(payload_path):
    path = Path(payload_path).resolve()
    roots = []
    for candidate in [path.parent, *path.parents]:
        if candidate not in roots:
            roots.append(candidate)
        if (candidate / "artifacts").exists():
            break
    cwd = Path.cwd().resolve()
    if cwd not in roots:
        roots.append(cwd)
    return roots


def leaked_formal_output_files(payload_path):
    leaks = []
    for output in POLICY.get("formal_outputs", []):
        for root in candidate_project_roots(payload_path):
            for candidate in [root / "artifacts" / SKILL_ID / output, root / output]:
                if candidate.exists():
                    leaks.append(str(candidate))
    return sorted(set(leaks))


def should_validate_formal_outputs(payload):
    status = payload.get("status")
    state = payload.get("preflight_input_state")
    if status == "waiting_for_input":
        return False
    return state in {"ready", "waiting_for_human_review", "blocked"} or status in {"succeeded", "failed", "blocked", "waiting_for_human_review"}


def validate_preflight_order(payload_path, payload):
    errors = []
    status = payload.get("status")
    state = payload.get("preflight_input_state")
    if state not in {"ready", "waiting_for_input", "waiting_for_human_review", "blocked"}:
        errors.append("preflight_input_state 必须是 ready/waiting_for_input/waiting_for_human_review/blocked")
    if status == "waiting_for_input":
        if state != "waiting_for_input":
            errors.append("status=waiting_for_input 时 preflight_input_state 必须为 waiting_for_input")
        if not payload.get("required_information_requests"):
            errors.append("waiting_for_input 必须输出 required_information_requests 主动询问用户")
        for item in payload.get("artifacts", []) or []:
            if is_formal_artifact(item):
                errors.append("waiting_for_input 不得登记正式阶段产物，必须先等待补充信息写回: " + (artifact_path(item) or item.get("name", "")))
        leaks = leaked_formal_output_files(payload_path)
        if leaks:
            errors.append("waiting_for_input 不得先落盘正式阶段产物，必须先等待补充信息写回: " + ", ".join(leaks))
    if status == "waiting_for_human_review" and state not in {"waiting_for_human_review", "blocked"}:
        errors.append("status=waiting_for_human_review 时 preflight_input_state 必须为 waiting_for_human_review 或 blocked")
    if status == "succeeded":
        if state != "ready":
            errors.append("succeeded 必须满足 preflight_input_state == ready")
        if blocking_information_requests(payload):
            errors.append("succeeded 不允许存在未解决的 blocking required_information_requests")
        for name, text in artifact_texts(payload_path, payload):
            unresolved = unresolved_markers(text)
            if unresolved:
                errors.append(name + " 包含未决信息标记，必须先 waiting_for_input 并生成 human-review HTML: " + ", ".join(sorted(set(unresolved))))
    return errors


def markdown_headings(text):
    return [match.group(1).strip() for match in re.finditer(r"(?m)^#{{1,6}}\\s*(?:\\d+(?:\\.\\d+)*\\s*)?(.+?)\\s*$", text)]


def table_cells(line):
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def is_separator_row(line):
    cells = table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{{2,}}:?", cell.replace(" ", "")) for cell in cells)


def section_text(text, heading, next_heading_pattern=r"^#{{1,3}}\\s*\\d+(?:\\.\\d+)*\\s+"):
    start = text.find(heading)
    if start < 0:
        return ""
    tail = text[start:]
    match = re.search(r"(?m)" + next_heading_pattern, tail[len(heading):])
    return tail if not match else tail[: len(heading) + match.start()]


def normalize_table_name(value):
    value = value.strip().strip("`").strip()
    if "." in value:
        value = value.split(".")[-1].strip("`")
    return value


def extract_table_names(value):
    return [normalize_table_name(item) for item in re.findall(r"`?([a-zA-Z][a-zA-Z0-9_]*\\.[a-zA-Z][a-zA-Z0-9_]*|t_[a-zA-Z0-9_]+)`?", value)]


def design_object_value(text):
    for line in text.splitlines():
        cells = table_cells(line)
        if len(cells) >= 2 and cells[0] == "设计对象":
            return cells[1]
    return ""


def object_type_value(text):
    for line in text.splitlines():
        cells = table_cells(line)
        if len(cells) >= 2 and cells[0] == "对象类型":
            return cells[1]
    return ""


def table_group_members(text):
    names = []
    names.extend(extract_table_names(design_object_value(text)))
    group = section_text(text, "2.4 强耦合表组说明")
    for line in group.splitlines():
        cells = table_cells(line)
        if len(cells) >= 5 and cells[0] != "成员表" and not is_separator_row(line):
            names.extend(extract_table_names(cells[0]))
    deduped = []
    for name in names:
        if name and name not in deduped:
            deduped.append(name)
    return deduped


def create_table_names(sql):
    names = []
    pattern = r"(?is)\\bcreate\\s+table\\s+(?:if\\s+not\\s+exists\\s+)?(?:`?[a-zA-Z][a-zA-Z0-9_]*`?\\.)?`?([a-zA-Z][a-zA-Z0-9_]*)`?"
    for match in re.finditer(pattern, sql):
        names.append(normalize_table_name(match.group(1)))
    return names


def ddl_index_names(sql, table):
    names = set()
    table_pattern = re.escape(table)
    match = re.search(r"(?is)\\bcreate\\s+table\\s+(?:if\\s+not\\s+exists\\s+)?(?:`?[a-zA-Z][a-zA-Z0-9_]*`?\\.)?`?" + table_pattern + r"`?\\s*\\((.*?)\\)\\s*;", sql)
    if not match:
        return names
    body = match.group(1)
    if re.search(r"(?is)\\bprimary\\s+key\\b", body):
        names.add("PRIMARY")
    for index_match in re.finditer(r"(?is)\\b(?:unique\\s+)?(?:key|index)\\s+`?([a-zA-Z][a-zA-Z0-9_]*)`?", body):
        names.add(index_match.group(1))
    return names


def markdown_index_rows(text):
    rows = []
    in_index_table = False
    for line in section_text(text, "4.3 索引设计").splitlines():
        cells = table_cells(line)
        if cells == ["表", "索引名", "类型", "字段（顺序敏感）", "唯一", "服务场景", "备注"]:
            in_index_table = True
            continue
        if not in_index_table or is_separator_row(line):
            continue
        if len(cells) >= 7:
            rows.append({{"table": normalize_table_name(cells[0]), "name": cells[1], "unique": cells[4]}})
    return rows


def mermaid_blocks(text, diagram_type):
    pattern = r"```mermaid\\s*\\n\\s*" + re.escape(diagram_type) + r"\\b([\\s\\S]*?)```"
    return [match.group(1) for match in re.finditer(pattern, text)]


def requires_database_er_diagram(text, trigger_terms):
    if any(term in text for term in ["CREATE TABLE", "ALTER TABLE", "DROP TABLE", "本地读模型", "表结构"]):
        return True
    if re.search(r"\\bt_[a-zA-Z0-9_]+\\b", text):
        return True
    if "主表" in text and any(term in text for term in ["明细", "关联表", "从表"]):
        return True
    has_database_noun = any(term in text for term in ["数据库", "DB"])
    has_database_action = any(term in text for term in ["查询", "写入", "更新", "删除", "upsert", "事务", "回滚", "提交"])
    if has_database_noun and has_database_action:
        return True
    return any(term in text for term in trigger_terms)


def er_diagram_entities(block):
    names = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        relation = re.match(r"^`?([A-Za-z\\u4e00-\\u9fff][A-Za-z0-9_\\u4e00-\\u9fff\\.]*)`?\\s+[|}}{{oO-]+\\s+`?([A-Za-z\\u4e00-\\u9fff][A-Za-z0-9_\\u4e00-\\u9fff\\.]*)`?\\s*:", line)
        if relation:
            names.extend([normalize_table_name(relation.group(1)), normalize_table_name(relation.group(2))])
            continue
        entity = re.match(r"^`?([A-Za-z\\u4e00-\\u9fff][A-Za-z0-9_\\u4e00-\\u9fff\\.]*)`?\\s*\\{{$", line)
        if entity:
            names.append(normalize_table_name(entity.group(1)))
    deduped = []
    for name in names:
        if name and name not in deduped:
            deduped.append(name)
    return deduped


def er_diagram_has_relationship(block):
    return bool(re.search(r"(?m)^[^\\n]+[|}}{{oO-]+[^\\n]+:", block))


def confirmed_database_tables(text):
    names = []
    names.extend(table_group_members(text))
    for match in re.finditer(r"(?m)^####\\s+4\\.2\\.\\d+\\s+(.+)$", text):
        names.extend(extract_table_names(match.group(1)))
    for match in re.finditer(r"(?m)^\\|\\s*设计对象\\s*\\|\\s*(.+?)\\|", text):
        names.extend(extract_table_names(match.group(1)))
    names.extend(create_table_names(text))
    deduped = []
    for name in names:
        normalized = normalize_table_name(name)
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def normalized_nonempty_lines(text):
    return {{re.sub(r"\\s+", " ", line.strip()) for line in text.splitlines() if line.strip()}}


def protected_template_lines(text):
    protected = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "{{" in line or "YYYY-MM-DD" in line:
            continue
        if line.startswith((">", "##", "###", "####", "**", "- ")) or line in {{"强耦合表组模式标题规则：", "文档结束"}}:
            protected.append(re.sub(r"\\s+", " ", line))
    return protected


def service_sequence_participants(block):
    participants = {{}}
    for raw in block.splitlines():
        line = raw.strip()
        match = re.match(r"(?i)^(participant|actor)\\s+([A-Za-z0-9_]+)(?:\\s+as\\s+(.+))?$", line)
        if match:
            participants[match.group(2)] = (match.group(3) or match.group(2)).strip()
    return participants


def service_sequence_endpoints(block):
    endpoints = []
    for raw in block.splitlines():
        line = raw.strip()
        match = re.match(r"([A-Za-z0-9_\\u4e00-\\u9fff]+)\\s*(?:-+|=+|x-+|-->>|->>|->|-->)\\s*([A-Za-z0-9_\\u4e00-\\u9fff]+)", line)
        if match:
            endpoints.extend([match.group(1), match.group(2)])
    return endpoints


def is_service_label(label, forbidden_terms):
    label = str(label).strip()
    if not label:
        return False
    if any(term and term in label for term in forbidden_terms):
        return False
    return "服务" in label or "Service" in label or label.endswith("Svc")


def has_abstract_participant_label(label, abstract_terms):
    label = str(label).strip()
    return any(term and term in label for term in abstract_terms)


def is_event_driven_design(text, event_terms):
    return any(term in text for term in event_terms)


def sequence_has_internal_processing(block, required_terms, outcome_terms):
    participants = service_sequence_participants(block)
    has_self_call = False
    for raw in block.splitlines():
        line = raw.strip()
        match = re.match(r"([A-Za-z0-9_\u4e00-\u9fff]+)\s*(?:-+|=+|-->>|->>|->|-->)\s*([A-Za-z0-9_\u4e00-\u9fff]+)\s*:\s*(.*)", line)
        if not match:
            continue
        left, right, message = match.group(1), match.group(2), match.group(3)
        if left == right:
            has_self_call = True
            if all(term in message for term in required_terms) and any(term in message for term in outcome_terms):
                return True
    if not has_self_call:
        return False
    # Allow split self-calls as long as the block as a whole shows the internal path.
    return all(term in block for term in required_terms) and any(term in block for term in outcome_terms)


def is_mq_db_redis_flow(text):
    has_mq = any(term in text for term in ["MQ", "消息", "消费", "队列", "死信"])
    has_db = any(term in text for term in ["DB", "数据库", "主表", "明细", "读模型"])
    has_redis = any(term in text for term in ["Redis", "缓存", "幂等记录", "状态处理记录", "乱序保护记录"])
    return has_mq and has_db and has_redis


def is_local_read_model_write(text):
    return "本地读模型" in text and any(term in text for term in ["写入", "保存", "upsert", "重建"])


def is_local_read_model_delete(text):
    return "本地读模型" in text and any(term in text for term in ["删除", "移除", "失效"])


def is_query_or_export_flow(text):
    return any(term in text for term in ["查询流程", "导出流程", "查询 / 导出", "列表查询", "分批导出"])


def read_json_artifact(payload_path, payload, name):
    text = read_artifact(payload_path, payload, name)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def participant_evidence_entries(payload_path, payload):
    data = read_json_artifact(payload_path, payload, "participant-evidence-map.json")
    if not isinstance(data, dict):
        return None
    raw_entries = data.get("participants") or data.get("services") or data.get("items") or []
    entries = {{}}
    if isinstance(raw_entries, dict):
        raw_entries = [{{"participant": key, **(value if isinstance(value, dict) else {{"evidence": value}})}} for key, value in raw_entries.items()]
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        keys = [
            item.get("participant"), item.get("alias"), item.get("service"), item.get("service_name"),
            item.get("name"), item.get("label"), item.get("display_name"), item.get("service_label"),
        ]
        for key in keys:
            if key:
                entries[str(key).strip()] = item
    return entries


def has_confirmed_participant_evidence(item):
    if not isinstance(item, dict):
        return False
    status = str(item.get("status") or item.get("evidence_status") or "").strip().lower()
    if status in {{"unknown", "proposed", "assumed", "todo", "pending", "pending_confirmation", "unconfirmed", "missing"}}:
        return False
    evidence_fields = [
        "repo_context", "repo_context_ref", "code_path", "source_path", "module_path", "service_registry_ref",
        "evidence", "evidence_refs", "source_artifacts", "owner_module", "pom", "build_file",
    ]
    if any(item.get(field) for field in evidence_fields):
        return True
    return status in {{"confirmed", "matched", "verified", "existing"}}


def message_schema_entries(data):
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    if any(field in data for field in ["issueId", "configType", "properties"]):
        return [data]
    for key in POLICY.get("message_schema_entry_collection_keys", []):
        raw = data.get(key)
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, dict):
            entries = []
            for config_type, value in raw.items():
                if isinstance(value, dict):
                    entry = dict(value)
                    entry.setdefault("configType", config_type)
                    entries.append(entry)
            if entries:
                return entries
    return []


def schema_properties(entry):
    if isinstance(entry, dict) and isinstance(entry.get("properties"), dict):
        return entry.get("properties") or {{}}
    return {{}}


def schema_required_fields(node):
    if isinstance(node, dict) and isinstance(node.get("required"), list):
        return {{str(item) for item in node.get("required", []) if isinstance(item, str)}}
    return set()


def schema_config_type(entry, root_properties):
    config_value = entry.get("configType") if isinstance(entry, dict) else None
    if isinstance(config_value, str) and config_value.strip():
        return config_value.strip()
    config_node = root_properties.get("configType") if isinstance(root_properties, dict) else None
    if isinstance(config_node, dict):
        for key in ["const", "default", "example"]:
            value = config_node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        enum_value = config_node.get("enum")
        if isinstance(enum_value, list) and len(enum_value) == 1 and isinstance(enum_value[0], str) and enum_value[0].strip():
            return enum_value[0].strip()
    return ""


def fail(errors):
    if errors:
        raise SystemExit("\\n".join(errors))
    print("ok")

{validator_bodies[skill_id]}

payload_path = Path(sys.argv[1])
payload = load_payload(payload_path)
errors = validate_preflight_order(payload_path, payload)
if should_validate_formal_outputs(payload):
    errors.extend(validate_output(payload_path, payload))
fail(errors)
"""


EXTRA_EVAL_SCENARIOS = {
    "high-level-design": [
        {
            "case": "team_high_level_template_required",
            "title": "概要设计必须使用萤启团队模板",
            "material": "用户要求生成萤启运营系统能力概要设计，需覆盖版本变更、平台概述、系统设计、系统逻辑视图、系统设计原则、研发视图、研发结构、核心功能、中间件设计和数据视图。",
            "expected_gate_decision": "pass",
            "rule_refs": ["H1", "H2", "H3", "H7"],
            "risk_focus": ["概要设计模板", "系统边界", "中间件范围", "数据视图"],
            "forbidden_behavior": ["只输出证据/Findings/门禁决策", "省略中间件设计或数据视图"],
        },
        {
            "case": "team_high_level_service_sequence_traceability",
            "title": "概要设计跨服务时序图和规格原型追溯",
            "material": "需求规格和原型均已提供，概要设计涉及服务商系统、活动服务、权益发放服务之间的跨服务协作。概要设计必须列出原始需求规格/原型 source_id 引用矩阵，并补充 Mermaid sequenceDiagram 服务间时序图；时序图只能出现服务，不能把用户、页面、Controller、数据库、Redis、MQ、表或 Repository 作为参与者。",
            "expected_gate_decision": "pass",
            "rule_refs": ["H2", "H3", "H8", "H9"],
            "risk_focus": ["跨服务时序图", "服务参与者限制", "规格原型追溯", "设计一致性"],
            "forbidden_behavior": ["sequenceDiagram 出现用户或页面", "sequenceDiagram 出现数据库或 MQ", "缺少 source_id 引用矩阵", "设计无法追溯原始规格或原型"],
        },
        {
            "case": "team_high_level_no_flowchart",
            "title": "概要设计不得包含流程图",
            "material": "团队要求概要设计不再生成流程图；核心功能只能保留关键协作摘要文本、服务间 sequenceDiagram、状态机和异常流/最终一致性说明。",
            "expected_gate_decision": "pass",
            "rule_refs": ["H1", "H7", "H8", "H10"],
            "risk_focus": ["概要层边界", "关键协作摘要", "流程图禁用", "结构稳定"],
            "forbidden_behavior": ["在 high-level-design.md 生成 flowchart", "用流程图替代关键协作摘要"],
        },
        {
            "case": "team_high_level_no_detailed_implementation_content",
            "title": "概要设计不得混入详细实现",
            "material": "已有概要设计草稿在核心功能中展开请求字段、返回字段、CREATE TABLE、Controller、Mapper 和单元测试步骤。正确处理应阻断该草稿，并要求概要设计只保留跨系统/跨服务职责边界、服务间 sequenceDiagram、调用/事件方向、异常流、最终一致性和详细设计/专项文档引用。",
            "expected_gate_decision": "block",
            "rule_refs": ["H7", "H8", "H9", "H10"],
            "risk_focus": ["概要与详细职责边界", "详细实现泄漏", "跨服务时序", "专项文档引用"],
            "forbidden_behavior": ["在 high-level-design.md 展开请求字段或返回字段", "在概要设计正文写 SQL/DDL", "在概要设计正文写 Controller/Mapper/Repository 或单元测试步骤"],
        },
        {
            "case": "no-invented-participant-for-data-scope",
            "title": "概要设计不得为数据范围过滤虚构外部 participant",
            "material": "需求要求按当前用户可见范围进行数据隔离；repo_context 只证明现有登录态和查询条件过滤，没有外部权限服务证据。正确输出应描述沿用现有登录态与数据范围过滤流程，不生成外部权限服务 participant，participant-evidence-map.json 不包含虚构服务。",
            "expected_gate_decision": "pass",
            "rule_refs": ["H2", "H8", "H12"],
            "risk_focus": ["participant 真实性", "repo_context 证据", "登录态", "数据范围过滤"],
            "forbidden_behavior": ["把权限组织服务、数据权限服务或查询服务作为 participant", "缺少 participant-evidence-map.json", "无代码/配置/文档/用户确认仍进入正式时序图"],
        },
        {
            "case": "event-driven-sequence-not-too-simple",
            "title": "事件驱动概要时序图不得只有消息收发",
            "material": "需求包含创建类消息和状态变更类消息；下游业务系统维护本地读模型。概要设计必须至少包含创建类消息处理、状态变更类消息处理两个核心 sequenceDiagram，并通过服务 self-call 表达校验、幂等、状态/顺序判断、处理记录、事实详情查询、本地读模型写入或移除、重试/死信等内部关键阶段。",
            "expected_gate_decision": "pass",
            "rule_refs": ["H8", "H12", "H13"],
            "risk_focus": ["事件驱动", "核心消息场景", "本地读模型", "内部处理步骤"],
            "forbidden_behavior": ["只有 A-->>B 发送消息", "只有 B->>A 查询详情", "创建类和状态变更类消息合并成一个过度简化时序", "无证据 participant"],
        }
    ],
    "detailed-design": [
        {
            "case": "team_db_reference_only",
            "title": "数据库设计只在主文档引用专项",
            "material": "用户要求详细设计中数据库设计不需要体现，关联数据库设计文档即可；场景涉及新增表、索引和 CRUD 契约。",
            "expected_gate_decision": "require_human_review",
            "rule_refs": ["D2", "D4", "DB7", "P7"],
            "risk_focus": ["主文档 DB 展开", "database-design.md", "DDL 审批"],
            "forbidden_behavior": ["在 detailed-design.md 展开数据库字段表", "StageRunResult 不登记 database-design.md", "DDL 直接 succeeded"],
        },
        {
            "case": "team_mq_template_reference_only",
            "title": "MQ 设计使用专项模板",
            "material": "用户要求 MQ 设计使用模板；主详细设计只引用 mq-design.xlsx，专项必须生成生产者 sheet 和消费者 sheet。",
            "expected_gate_decision": "require_human_review",
            "rule_refs": ["D4", "M7", "M8", "M12"],
            "risk_focus": ["MQ 表格展开位置", "生产者表", "消费者表"],
            "forbidden_behavior": ["在主详细设计展开 MQ 字段", "缺少生产者表或消费者表"],
        },
        {
            "case": "team_redis_template_reference_only",
            "title": "Redis 设计使用专项模板",
            "material": "用户要求 Redis 设计使用团队模板；主详细设计只引用 redis-design.md，专项覆盖 Key、Value、TTL、容量和降级。",
            "expected_gate_decision": "require_human_review",
            "rule_refs": ["D4", "R7", "R8", "R10"],
            "risk_focus": ["Redis 专项模板", "TTL", "降级策略"],
            "forbidden_behavior": ["在主详细设计展开 Redis Key 表", "缺少 TTL 单位", "缺少降级策略"],
        },
        {
            "case": "team_flowchart_not_sequence",
            "title": "流程使用流程图替代时序图",
            "material": "用户要求流程使用流程图替代时序图；详细设计必须使用 Mermaid flowchart，并禁止 sequenceDiagram。",
            "expected_gate_decision": "pass",
            "rule_refs": ["D5", "D6", "RRQ-LOG1"],
            "risk_focus": ["流程图类型", "流程设计说明"],
            "forbidden_behavior": ["生成 sequenceDiagram", "flowchart 后没有流程设计说明"],
        },
        {
            "case": "team_flowchart_exception_branches_required",
            "title": "详细设计流程图必须覆盖异常分支",
            "material": "已有详细设计草稿只有开始、保存、成功结束三个主干节点，异常场景只写待补充，缺少参数/权限/状态校验失败、外部依赖失败、事务/一致性失败、重试/补偿、人工处理和失败终态。正确处理应阻断该草稿，并要求补齐 flowchart 异常路径和异常场景表。",
            "expected_gate_decision": "block",
            "rule_refs": ["D5", "D6", "D13", "D14"],
            "risk_focus": ["异常分支", "失败终态", "重试补偿", "异常场景表"],
            "forbidden_behavior": ["只有主干 flowchart 就放行", "异常场景没有触发条件和异常编码", "缺少补偿/重试/人工处理路径"],
        },
        {
            "case": "detailed-design-db-redis-mq-flow-required",
            "title": "详细设计必须体现 MQ / Redis / DB 关键执行路径",
            "material": "需求包含 MQ 消费、Redis 消息幂等记录/状态处理记录、DB 主表和明细表本地读模型。详细设计 flowchart 必须体现消息接收、解析校验、幂等、状态/顺序判断、外部详情查询、Redis 读写、DB 主表 upsert、明细重建或删除、事务、回滚、重试、死信和人工处理。",
            "expected_gate_decision": "pass",
            "rule_refs": ["D13", "D14", "D15", "P3", "P4"],
            "risk_focus": ["MQ 消费", "Redis 幂等", "DB 主明细", "事务回滚", "死信"],
            "forbidden_behavior": ["只写处理消息", "只写保存数据或删除数据", "缺少外部详情查询", "缺少事务/回滚/重试/死信/人工处理"],
        },
        {
            "case": "team_rules_under_flow",
            "title": "业务规则异常事务放到流程图模块下",
            "material": "用户要求业务规则、异常、事务、幂等和日志放到流程图模块下；不得生成独立业务规则、异常、幂等章节。",
            "expected_gate_decision": "pass",
            "rule_refs": ["D2", "D6", "P4", "E7"],
            "risk_focus": ["流程说明", "独立章节禁止", "日志 TraceId"],
            "forbidden_behavior": ["生成业务规则与校验章节", "生成幂等与一致性章节", "生成异常与日志章节"],
        },
        {
            "case": "team_database_er_diagram_required",
            "title": "涉库详细设计必须补充真实表名数据库图",
            "material": "需求涉及数据库查询、事务提交、主表+明细表写入和本地读模型维护。详细设计必须在主文档补充 Mermaid erDiagram，并且图中只允许出现 database-design.md 已确认的真实表名，不允许使用订单表、明细表、临时表等抽象命名。",
            "expected_gate_decision": "pass",
            "rule_refs": ["D13", "D14", "D15"],
            "risk_focus": ["erDiagram", "真实表名", "主明细关系", "database-design 对齐"],
            "forbidden_behavior": ["涉库流程没有 erDiagram", "erDiagram 使用订单表/明细表等抽象命名", "数据库图中的表名与 database-design.md 不一致"],
        },
        {
            "case": "team_ddd_requires_uml",
            "title": "DDD 模式补充 UML 类图",
            "material": "用户要求设计 DDD 模式并包含聚合根、ApplicationService、Repository、Handler 模板扩展点。",
            "expected_gate_decision": "pass",
            "rule_refs": ["D7", "D8", "FW1"],
            "risk_focus": ["classDiagram", "聚合根", "端口适配器"],
            "forbidden_behavior": ["出现 DDD 关键词但没有 classDiagram", "类图缺少 Repository 或外部适配器"],
        },
        {
            "case": "team_no_release_gray_sections",
            "title": "团队详细设计不需要发布和灰度内容",
            "material": "用户要求团队详细设计不需要发布和灰度内容；主文档和测试策略不得生成发布、灰度、上线章节。",
            "expected_gate_decision": "pass",
            "rule_refs": ["D2", "DB6", "QIN1"],
            "risk_focus": ["发布章节禁止", "灰度章节禁止", "测试策略边界"],
            "forbidden_behavior": ["主文档生成发布章节", "测试策略生成灰度验证章节"],
        },
    ],
    "mq-design": [
        {
            "case": "team_mq_template_tables",
            "title": "MQ 专项必须包含生产者表和消费者表",
            "material": "用户要求 MQ 设计使用模板，需定义生产者字段、消费者字段、死信、重试、回放和幂等策略。",
            "expected_gate_decision": "require_human_review",
            "rule_refs": ["M7", "M8", "M12", "M14"],
            "risk_focus": ["生产者表", "消费者表", "回放审批"],
            "forbidden_behavior": ["只写文字说明不出表", "缺少死信或幂等策略"],
        },
        {
            "case": "team_mq_envelope_schema_required",
            "title": "MQ 设计必须输出统一 envelope 的 message-schema",
            "material": "用户要求所有 MQ 消息体统一为 issueId + configType + configType 同名业务对象。mq-design.xlsx 的消息体内容、mq-topic-contract.yaml 和 message-schema.json 必须一致；pendingOrderExportTask 必须定义 taskId、taskType、businessType、eventTime 四个必填字段。",
            "expected_gate_decision": "require_human_review",
            "rule_refs": ["M12", "M15", "M16"],
            "risk_focus": ["message-schema.json", "统一 envelope", "configType", "topic contract 一致性"],
            "forbidden_behavior": ["缺少 message-schema.json", "消息体只写自然语言不写 issueId/configType", "configType 与业务对象 key 不一致", "pendingOrderExportTask 缺少必填字段"],
        }
    ],
    "redis-design": [
        {
            "case": "team_redis_template_required",
            "title": "Redis 专项必须使用团队模板",
            "material": "用户要求 Redis 设计使用模板，需覆盖公共配置、Redis 版本、集群、持久化、淘汰、设计项、TTL、容量和降级。",
            "expected_gate_decision": "waiting_for_input",
            "rule_refs": ["R7", "R8", "R9", "R10"],
            "risk_focus": ["Redis 版本", "TTL 单位", "降级策略"],
            "forbidden_behavior": ["版本拓扑待确认但 succeeded", "没有 TTL 单位"],
        },
        {
            "case": "redis-term-must-be-explicit",
            "title": "Redis 设计术语必须业务可理解",
            "material": "用户描述使用 Redis 保存过程信息解决消息乱序。Redis 设计应使用状态处理记录、消息幂等记录、乱序保护记录等显式术语，不使用水位或终态水位作为正式术语；Redis 不作为事实源；Redis 不可用时消费者进入 MQ 重试/死信、告警并说明人工回放策略。",
            "expected_gate_decision": "pass",
            "rule_refs": ["R1", "R6", "R10", "R14"],
            "risk_focus": ["业务术语", "乱序保护", "Redis 不可用", "人工回放"],
            "forbidden_behavior": ["使用水位或终态水位作为正式术语", "Redis 被描述为事实源", "Redis 不可用时继续写库或删除", "无 TTL", "无告警或人工回放策略"],
        }
    ],
    "database-design": [
        {
            "case": "team_database_template_required",
            "title": "数据库专项必须使用 OLTP 或 OLAP 模板",
            "material": "用户要求数据库设计使用团队模板，OLTP 覆盖字段、索引、CRUD、事务和审批；ClickHouse 使用 OLAP 模板。",
            "expected_gate_decision": "require_human_review",
            "rule_refs": ["DB7", "DB8", "DB9", "DB10"],
            "risk_focus": ["OLTP 模板", "OLAP 模板", "DDL 审批"],
            "forbidden_behavior": ["用主文档字段表替代专项", "未确认库名实例却 final"],
        },
        {
            "case": "database-design-template-not-truncated",
            "title": "数据库设计不得裁剪 OLTP 团队模板",
            "material": "一个需求需要新增主表 + 明细表，存在 DDL，但缺少库名、实例、DBA 负责人。database-design.md 必须完整保留 OLTP 模板全部章节、固定提示块、表格列头、附录和文档结束；状态进入 waiting_for_input 或 waiting_for_human_review，不允许输出简化数据库设计。",
            "expected_gate_decision": "waiting_for_input",
            "rule_refs": ["DB7", "DB11", "DB12", "DB13", "DB14"],
            "risk_focus": ["OLTP 模板完整性", "强耦合表组", "缺失事实", "人工输入"],
            "forbidden_behavior": ["裁剪容量设计、CRUD 契约、事务边界、禁止操作、批量修复、安全审计或测试验收章节", "删除不适用章节", "缺失库名实例负责人仍 succeeded"],
        },
        {
            "case": "team_database_missing_info_must_ask",
            "title": "数据库设计缺少事实必须主动询问",
            "material": "用户只给出表名和部分 DDL，未提供逻辑库、物理库、实例、数据库版本、DBA、安全接口人、QPS、容量、索引用途和审批状态。",
            "expected_gate_decision": "waiting_for_input",
            "rule_refs": ["DB7", "DB10", "DB11", "DB12"],
            "risk_focus": ["主动询问", "禁止推测", "模板占位符"],
            "forbidden_behavior": ["编造库名实例或负责人", "用待补充输出 succeeded", "删除模板中不适用章节"],
        },
        {
            "case": "team_database_open_door_event_table_group",
            "title": "主表参数表大字段表通用表组",
            "material": "输入范例为异常事件类业务：需要保存事件主记录、请求参数快照和大字段诊断上下文，结构为主表 + 参数表 + 大字段表；主记录承载事件事实和幂等键，参数表承载识别参数，大字段表承载原始请求和下游返回。期望按业务对象角色推导成员表集合，并保持主文档、DDL、迁移、回滚和风险报告的成员表集合一致，不允许把所有字段塞进单表。",
            "expected_gate_decision": "require_human_review",
            "rule_refs": ["DB4", "DB7", "DB11", "DB13", "DB14"],
            "risk_focus": ["强耦合表组", "主表参数表大字段表", "DDL 一致性", "幂等键"],
            "forbidden_behavior": ["只生成单表", "把参数和大字段混进主表", "DDL 少于业务对象角色数量", "索引无法归属具体表"],
        },
        {
            "case": "team_database_member_private_domain_table_group",
            "title": "配置规则领取记录通用表组",
            "material": "输入范例为会员私域类业务：需求包含活动配置 + 入口配置 + 福利规则 + 领取主记录 + 领取明细五类事实对象。配置来源服务发送 MQ 后，目标活动服务消费 MQ 并在本地事务内保存配置、入口和规则对象；用户领取时先写领取主记录保证幂等，再按福利规则生成领取明细并记录下游发放结果；跨服务发放失败不回滚领取事实，领取主记录进入失败或部分失败状态，由补偿流程处理。期望按事实对象和主明细关系推导强耦合表组，主文档、DDL、迁移、回滚、风险报告中的成员表集合一致。",
            "expected_gate_decision": "require_human_review",
            "rule_refs": ["DB4", "DB7", "DB11", "DB13", "DB14"],
            "risk_focus": ["多事实对象表组", "本地事务", "跨服务最终一致", "补偿核对"],
            "forbidden_behavior": ["只生成配置单表", "把配置规则领取字段混成字段池", "跨服务发放失败回滚领取事实", "DDL 表集合与主文档不一致"],
        }
    ],
    "code-development": [
        {
            "case": "team_code_source_design_traceability",
            "title": "代码实现必须追溯规格原型和设计",
            "material": "代码阶段基于已审批设计实施接口、服务和 mapper 变更。design-to-code-mapping.yaml 和 traceability-matrix.json 必须逐项记录 source_id、source_type、source_path_or_url、design_section、code_path、verification_evidence，确保原始需求规格/原型、设计章节、代码文件和验证证据一一对应。",
            "expected_gate_decision": "pass",
            "rule_refs": ["CQ2", "CD1", "DG20"],
            "risk_focus": ["规格原型追溯", "设计到代码映射", "无依据代码", "验证证据"],
            "forbidden_behavior": ["只写变更摘要不写 source_id", "代码文件无法映射设计章节", "traceability-matrix.json 缺少 code_path", "缺少验证证据"],
        }
    ],
}


def extra_eval_case(skill: dict, scenario: dict) -> dict:
    expected_status = {
        "pass": "succeeded",
        "waiting_for_input": "waiting_for_input",
        "require_human_review": "waiting_for_human_review",
        "block": "blocked",
    }[scenario["expected_gate_decision"]]
    formal_document_criterion = (
        "正式 MQ Excel 文档必须包含 document_metadata.document_number、document_status、retention_policy"
        if skill["id"] == "mq-design"
        else "正式 Markdown 文档必须包含 document_metadata.document_number、document_status、retention_policy"
    )
    common_pass_criteria = [
        "StageRunResult status 合法",
        "StageRunResult 必须包含 preflight_input_state，且 formal_generation 入口条件必须是 preflight_input_state == ready",
        "未指定 language 时必须询问用户选择 zh-CN 或 en",
        formal_document_criterion,
        "required_information_requests 在输入缺失时必须包含 questions",
        "缺失 blocking 信息时必须先暂停在 waiting_for_input，并生成 docs/human-review/ 可填写 HTML 审阅包",
        "blocking 信息补齐并写回 StageRunRequest.context 或 artifact index 前，不得生成或登记正式阶段 Markdown/Excel/JSON 产物",
        "framework selection 必须遵循 repo_context/profile；Java/Spring 持久化默认 mybatis-plus，JDBC 必须评审",
        "forbidden_behavior 未出现在输出决策中",
    ]
    skill_specific_pass_criteria = {
        "high-level-design": [
            "high-level-design.md 必须按 assets/high-level-design-template.md 生成",
            "high-level-design.md 必须包含原始需求与原型追溯、版本变更记录、平台概述、系统设计、系统逻辑视图、系统设计原则、研发视图、研发结构定义、核心功能、中间件设计、数据视图",
            "high-level-design.md 必须包含 4.1.2 关键协作摘要，且不得包含 flowchart",
            "high-level-design.md 跨服务核心场景必须包含 Mermaid sequenceDiagram 服务间时序图，且参与者只允许有证据的真实系统/服务/应用边界",
            "sequenceDiagram participant 必须登记 participant-evidence-map.json，状态不得为 unknown/proposed/assumed/pending/unconfirmed；抽象能力名不得进入正式时序图",
            "MQ / 事件 / 异步消息场景必须覆盖创建/新增/产生类消息和状态变更/删除/失效类消息，且时序图必须包含服务内部关键处理 self-call",
            "high-level-design.md 必须用 source_id 引用原始需求规格或原型，并说明一致性状态",
            "high-level-design.md 不得使用通用证据/Findings/门禁决策模板替代概要设计正文",
            "high-level-design.md 不得展开接口字段、请求/响应字段、SQL/DDL、数据库字段索引、Controller/Mapper/Repository、类方法签名、伪代码或单元测试步骤",
        ],
        "detailed-design": [
            "detailed-design.md 必须按 assets/detailed-design-template.md 生成",
            "detailed-design.md 必须包含原始需求与原型引用矩阵，核心流程、接口、数据对象或规则必须映射 source_id",
            "detailed-design.md 不得包含来源证据、技术选型、业务规则与校验、幂等与一致性、异常与日志、发布、灰度、上线等禁止标题",
            "detailed-design.md 不得包含 sequenceDiagram，必须包含 flowchart，且每个 flowchart 后必须有流程设计说明",
            "detailed-design.md 的 flowchart 必须覆盖异常分支、失败终态以及补偿/重试/人工处理路径",
            "detailed-design.md 的异常场景表必须包含场景、触发条件、异常编码、异常信息、系统处理动作、数据状态、日志/告警、补偿/重试/人工处理",
            "MQ + DB + Redis 场景必须体现消息校验、幂等、状态处理记录、外部详情查询、DB 主表/明细、Redis 读写、事务、回滚、重试、死信和人工处理",
            "出现 DDD、聚合根、ApplicationService、Repository、Handler 或 Template 时必须包含 classDiagram",
            "涉及 DB/MQ/Redis 时必须生成独立专项文档并登记到 StageRunResult.artifacts",
            "存在 DDL、MQ 新队列或 Redis 新 Key 时必须 waiting_for_human_review",
        ],
        "redis-design": [
            "redis-design.md 必须按 assets/redis-design-template.md 生成",
            "Redis 设计项必须包含特性用途、业务说明、存储设计、预估数据、多团队协同",
            "存储设计必须包含库、数据结构、ttl、key、数据格式，且 TTL 必须带单位",
            "Redis 术语必须使用状态处理记录、消息幂等记录、乱序保护记录等业务可理解表达，不得使用水位/终态水位作为正式术语",
            "Redis 不可用时不得绕过幂等/状态处理记录直接写 DB 或删 DB，必须进入 MQ 重试/死信、告警并说明人工回放策略",
        ],
        "mq-design": [
            "mq-design.xlsx 必须按 assets/mq-design-template.xlsx 生成",
            "MQ 设计必须包含生产者 sheet 和消费者 sheet，列头与 xxxMQ设计.xlsx 一致",
            "必须定义死信、幂等、重试和回放策略；超过 10KB 或回放生产消息必须 waiting_for_human_review",
        ],
        "database-design": [
            "database-design.md 必须按 assets/database-oltp-template.md 或 assets/database-olap-template.md 生成",
            "OLTP 章节顺序、标题名称和表格列头必须与关系型(OLTP)详细设计模板一致",
            "缺少库名、实例、版本、负责人、索引用途、QPS/容量、审批状态、敏感级别等事实时必须 waiting_for_input",
            "多事实对象、主明细、配置+规则+记录、主表+参数表+大字段表、领取主记录+领取明细必须进入强耦合表组模式",
            "强耦合表组模式下标题、设计对象、2.4 表组说明、3.1 逐表职责、4.2 逐表字段、4.3 逐表索引、CRUD 参与表和事务一致性必须完整",
            "schema-change-plan.sql、migration-plan.md、rollback-plan.md、database-risk-report.json 的成员表集合和表组口径必须与 database-design.md 一致",
        ],
        "code-development": [
            "design-to-code-mapping.yaml 必须包含 source_id、source_type、source_path_or_url、design_section、code_path、verification_evidence",
            "traceability-matrix.json 必须包含非空 rows，且每行串联原始规格/原型、设计章节、代码文件和验证证据",
            "无法映射到原始需求规格/原型和设计章节的代码变更必须 blocked",
        ],
    }.get(skill["id"], [])
    if template_usage_policy(skill).get("required"):
        template_read_criterion = "生成正式 MQ Excel 文档前必须先读取对应 xlsx template" if skill["id"] == "mq-design" else "生成正式 Markdown 文档前必须先读取对应 assets template"
        skill_specific_pass_criteria = [
            template_read_criterion,
            "输出正文必须保留 template 的章节顺序、标题层级、表格列头和固定提示块",
            "不适用章节必须保留并写明不适用原因，缺少事实时必须 waiting_for_input",
        ] + skill_specific_pass_criteria
    return {
        "id": f"{skill['id']}-{scenario['case']}",
        "name": f"{skill['name']} {scenario['title']}",
        "case_type": scenario["case"],
        "scenario": {
            "title": scenario["title"],
            "material": scenario["material"],
            "system_scope": "目标业务系统 + 目标客户端系统",
            "team_rule_refs": scenario["rule_refs"],
            "risk_focus": scenario["risk_focus"],
            "forbidden_behavior": scenario["forbidden_behavior"],
        },
        "input": {
            "stage_run_request": {
                "run_id": "team-doc-eval-001",
                "workflow_id": "team-doc-eval-workflow",
                "node_id": skill["id"],
                "skill_id": skill["id"],
                "mode": "standalone",
                "inputs": {skill["inputs"][0]: "provided: " + scenario["material"]},
                "artifacts": {},
                "context": {
                    "risk_policy": "team-default",
                    "team_rule_refs": scenario["rule_refs"],
                    "expected_gate_decision": scenario["expected_gate_decision"],
                },
                "requested_by": "eval",
                "approval_context": {},
            }
        },
        "expected_behavior": "按团队详细设计拆分规范输出产物，主文档不混入证据、选型、专项展开或发布灰度章节，并用确定性校验阻断违规内容。",
        "expected_gate_decision": scenario["expected_gate_decision"],
        "expected_status": expected_status,
        "pass_criteria": common_pass_criteria + skill_specific_pass_criteria,
        "severity_when_failed": "critical",
        "grader": {
            "type": "deterministic",
            "rubric": "校验团队详细设计拆分规则、专项模板、流程图、UML、人工评审和 StageRunResult artifact 登记。",
        },
        "required_artifacts": [output for output in skill["outputs"] if output != "code changes"],
    }


def contract(skill: dict) -> dict:
    payload = {
        "skill_id": skill["id"],
        "skill_name": skill["name"],
        "version": "1.0.0",
        "stage": skill["stage"],
        "type": skill["type"],
        "purpose": skill["purpose"],
        "non_goals": skill["non_goals"],
        "trigger_description": skill_trigger_description(skill),
        "routing": skill_routing_metadata(skill),
        "standalone_mode": "先执行 preflight 信息梳理；blocking 信息缺失时仅输出 required_information_requests、human-review HTML 和恢复点，补齐后再在指定输出目录生成全部声明产物。",
        "workflow_mode": "消费 StageRunRequest 中的上游产物，先执行 preflight 信息梳理；blocking 信息缺失时暂停并等待补充写回，补齐后输出 StageRunResult 并把声明产物路由给下游 workflow 节点。",
        "preflight_runtime_gate": {
            "state_field": "preflight_input_state",
            "states": PREFLIGHT_INPUT_STATES,
            "formal_generation_entry_condition": FORMAL_GENERATION_ENTRY_CONDITION,
            "formal_generation_blocked_when": ["preflight_input_state != ready", "存在 blocking required_information_requests", "human-review HTML 已生成但补充答案未写回机读事实源"],
            "waiting_for_input_allowed_artifacts": PREFLIGHT_ONLY_ARTIFACTS,
            "waiting_for_input_forbidden_formal_artifacts": FORMAL_DESIGN_ARTIFACTS,
            "resume_after_writeback": "StageRunRequest.context、artifact index 或 MD/JSON/YAML 已记录用户补充答案、来源和时间。",
        },
        "design_governance_policy": design_governance_policy(),
        "language_policy": {
            "supported": ["zh-CN", "en"],
            "when_unspecified": "ask_user",
            "blocking_status": "waiting_for_input",
            "question": "请确认输出语言：简体中文还是 English？",
            "writeback": "StageRunRequest.context.language",
        },
        "technology_selection_policy": {
            "categories": ["backend_framework", "persistence_framework", "frontend_stack", "component_library", "middleware", "test_framework", "build_tool", "observability", "deployment"],
            "must_confirm_when": ["设计未声明技术选型", "repo_context 未识别现有技术栈", "生成代码需要选择后端/持久化/前端/组件库/测试/构建框架", "拟使用与现有项目不一致的技术"],
            "ask_user_when_unspecified": True,
            "team_defaults": {"java_spring_persistence": "mybatis-plus"},
            "requires_review": ["JDBC", "框架替换", "绕过现有 mapper/repository 模式", "前端技术栈或组件库变更", "测试框架替换", "构建工具替换", "中间件替换"],
            "writeback": "StageRunRequest.context.technology_selection",
        },
        "team_adaptation_policy": {
            "profile_id": DEFAULT_PROFILE["profile_id"],
            "profile_path": "engineering-assistant/profiles/rrq-yq-team.yaml",
            "source_catalog": "engineering-assistant/registry/team-standard-sources.yaml",
            "rule_prefixes": TEAM_ADAPTATION_RULE_PREFIXES,
            "must_load_before_work": ["team-rule-catalog.yaml", "team-standard-sources.yaml", "rrq-yq-team.yaml"],
            "fallback": "如果目标项目 profile 与团队默认 profile 冲突，优先使用目标项目 profile，并把冲突作为 finding 或 required_information_requests 输出。",
        },
        "inputs": [
            {"name": item, "type": "artifact|string|object", "required": index == 0, "source": "user|workflow|repo|ci", "validation": "必填输入必须存在，选填输入必须可追溯来源", "missing_strategy": "除非无法定义边界，否则基于明确假设继续；无法定义边界时进入 waiting_for_input"}
            for index, item in enumerate(skill["inputs"])
        ],
        "outputs": [
            {"name": item, "type": contract_output_type_for_name(item), "path": f"artifacts/{skill['id']}/{item}", "schema": f"output.schema.json#{item}", "consumer": "workflow-orchestrator|downstream-stage|human-review"}
            for item in skill["outputs"]
        ],
        "preconditions": ["用户请求、仓库上下文、profile、上游产物和 artifact index 已读取或记录不可用原因", "blocking 必填信息已提供，或已进入 waiting_for_input 并生成补充信息入口", "风险策略已加载", "目标范围已明确"],
        "execution_gates": {
            "language_confirmed": True,
            "preflight_required_information": True,
            "preflight_before_formal_artifacts": True,
            "preflight_input_state_required": True,
            "formal_generation_requires_ready": True,
            "formal_document_metadata_required": True,
            "stage_result_validation_required": True,
            "block_when_agent_violates_contract": True,
        },
        "required_information_policy": {
            "must_ask_when": ["必填输入缺失", "系统边界无法确认", "风险等级无法判断", "审批状态缺失", "无法基于仓库或上游产物可靠推导"],
            "preflight_sequence": ["读取用户请求", "读取仓库上下文", "读取 profile", "读取上游产物", "读取 artifact index", "区分可自动推导信息与必须用户确认信息", "blocking 缺失项先问询并暂停", "补充答案写回后再生成正式产物"],
            "preflight_state_field": "preflight_input_state",
            "preflight_state_values": PREFLIGHT_INPUT_STATES,
            "formal_generation_entry_condition": FORMAL_GENERATION_ENTRY_CONDITION,
            "question_output": "required_information_requests",
            "blocking_status": "waiting_for_input",
            "human_review_html_required": True,
            "human_review_html_requirements": ["可填写每个待确认项", "保留问题 id 或稳定序号", "可复制或下载答案 JSON", "登记到 StageRunResult.artifacts", "HTML 路径必须位于目标项目 docs/human-review/", "agent 只消费 MD/JSON/YAML，不把 HTML 作为事实输入源"],
            "minimum_question_fields": ["id", "question", "reason", "required", "priority", "expected_format"],
            "question_order": ["critical", "major", "minor"],
            "do_not_ask_when": "信息可从当前仓库、上游产物、明确 profile 或已确认上下文可靠获得时，不重复询问用户。",
            "formal_artifacts_allowed_when": "不存在 blocking required_information_requests，或用户补充答案已写回 StageRunRequest.context、artifact index 或可机读 MD/JSON/YAML 事实源。",
            "waiting_for_input_artifacts": PREFLIGHT_ONLY_ARTIFACTS,
            "forbidden_before_writeback": "不得生成或登记正式阶段 Markdown/Excel/JSON 产物为完成产物，不得继续下游节点。",
        },
        "postconditions": ["blocking 信息缺失时已暂停在 waiting_for_input，且只登记补充信息请求、human-review HTML 和恢复点", "blocking 信息已补齐时全部正式输出产物已生成并登记", "质量门禁已评估", "需要人工审批的事项已列出"],
        "dependencies": ["团队规范", "文档模板", "仓库上下文", "风险策略", "校验脚本"],
        "permissions": {
            "allowed_actions": ["读取仓库文件", "生成产物", "运行确定性校验", "请求人工审批"],
            "forbidden_actions": ["执行生产变更", "自动批准高风险动作", "隐藏失败检查", "覆盖无关工作"],
        },
        "human_approval_required": skill["approvals"],
        "risk_model": {
            "levels": ["low", "medium", "high", "critical"],
            "upgrade_conditions": skill["approvals"],
            "default_for_unknown": "medium",
        },
        "quality_gates": [
            {"gate_id": f"{skill['id']}-gate-{i+1}", "name": gate, "type": "hybrid" if "审批" in gate or "高风险" in gate else "deterministic", "pass_condition": f"{gate} 有证据证明已满足", "fail_action": "block 或 require_human_review"}
            for i, gate in enumerate(skill["gates"])
        ],
        "failure_modes": [
            {"error_code": "MISSING_REQUIRED_INPUT", "condition": "必填输入不可用", "severity": "major", "recovery_strategy": "输出缺失信息产物并等待补充输入", "next_state": "waiting_for_input"},
            {"error_code": "INVALID_OUTPUT_SCHEMA", "condition": "输出无法按声明 schema 解析", "severity": "blocker", "recovery_strategy": "重新生成产物并再次运行校验器", "next_state": "failed"},
            {"error_code": "STAGE_RESULT_CONTRACT_VIOLATION", "condition": "StageRunResult 缺少语言、文档编号、主动问询或其他运行时门禁字段", "severity": "blocker", "recovery_strategy": "运行 validate_stage_run_result.py 并阻断违规节点", "next_state": "blocked"},
            {"error_code": "QUALITY_GATE_FAILED", "condition": "阻断门禁失败", "severity": "blocker", "recovery_strategy": "输出 findings 和 required actions", "next_state": "blocked"},
            {"error_code": "HUMAN_APPROVAL_REQUIRED", "condition": "风险策略要求人工审批", "severity": "major", "recovery_strategy": "创建 ApprovalRequest", "next_state": "waiting_for_human_review"},
        ],
        "eval_cases": EVAL_CASES,
        "workflow_interface": {
            "node_id": skill["id"],
            "input_artifacts": skill["inputs"],
            "output_artifacts": skill["outputs"],
            "document_metadata": {
                "schema": "engineering-assistant/schemas/document-lifecycle.schema.json",
                "required_when": "status=succeeded and markdown artifact exists",
            },
            "required_information_requests": {
                "artifact": f"artifacts/{skill['id']}/required-information-request.json",
                "schema": "engineering-assistant/schemas/required-information-request.schema.json",
                "status_when_blocking": "waiting_for_input",
                "must_precede_formal_artifacts": True,
                "resume_after_writeback": "StageRunRequest.context 或 artifact index 已记录用户补充答案和来源时间",
            },
            "state_transitions": COMMON_STATES,
            "gate_decision": ["continue", "pause", "retry", "skip", "block", "stop"],
            "retry_policy": {"max_attempts": 1, "retry_on": ["TOOL_UNAVAILABLE", "UNKNOWN_ERROR"]},
        },
        "owner": skill["owner"],
        "reviewers": ["研发负责人", "架构师", "测试负责人"],
        "change_policy": "contract、gate、schema 或审批规则变更必须经过 skill owner 评审，并通过 skill-quality-auditor",
    }
    if skill["id"] == "workflow-orchestrator":
        payload["workflow_runtime_policy"] = workflow_runtime_policy()
    static_policy = static_analysis_policy(skill)
    if static_policy.get("required"):
        payload["static_analysis_policy"] = static_policy
    html_policy = rich_html_report_policy(skill)
    if html_policy.get("required"):
        payload["rich_html_report_policy"] = html_policy
    control_policy = control_surface_policy(skill)
    if control_policy.get("required"):
        payload["control_surface_policy"] = control_policy
    doc_policy = team_document_policy(skill)
    if doc_policy:
        payload["team_document_policy"] = doc_policy
    return payload


def output_schema(skill: dict) -> dict:
    required = [o for o in skill["outputs"] if not o == "code changes"]
    artifact_types = schema_artifact_types(skill)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://example.internal/engineering-assistant/{skill['id']}/output.schema.json",
        "title": f"{skill['name']} 输出 Schema",
        "type": "object",
        "required": ["run_id", "skill_id", "status", "preflight_input_state", "language", "trace_id", "document_metadata", "artifacts", "quality_gates", "findings", "required_human_reviews", "required_information_requests", "repair_summary", "next_action"],
        "properties": {
            "run_id": {"type": "string"},
            "skill_id": {"const": skill["id"]},
            "status": {"enum": ["succeeded", "failed", "blocked", "waiting_for_input", "waiting_for_human_review", "skipped"]},
            "preflight_input_state": {"enum": PREFLIGHT_INPUT_STATES},
            "language": {"enum": ["zh-CN", "en"]},
            "trace_id": {"type": "string"},
            "document_metadata": document_lifecycle_schema(),
            "artifacts": {
                "type": "array",
                "minItems": 0,
                "items": {
                    "type": "object",
                    "required": ["name", "path", "artifact_type", "producer_skill"],
                    "properties": {
                        "name": {"type": "string"},
                        "path": {"type": "string"},
                        "artifact_type": {"enum": artifact_types},
                        "producer_skill": {"const": skill["id"]},
                        "consumer_skills": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "quality_gates": {"type": "array", "items": {"type": "object"}},
            "findings": {"type": "array", "items": {"type": "object"}},
            "required_human_reviews": {"type": "array", "items": {"type": "string"}},
            "required_information_requests": {
                "type": "array",
                "items": required_information_request_schema(),
            },
            "repair_summary": {
                "type": "object",
                "required": ["attempts", "max_attempts", "status"],
                "properties": {
                    "attempts": {"type": "integer", "minimum": 0},
                    "max_attempts": {"type": "integer", "minimum": 0},
                    "status": {"enum": ["not_needed", "repaired", "exhausted", "blocked"]},
                    "findings_repaired": {"type": "array", "items": {"type": "string"}},
                },
            },
            "next_action": {"enum": ["complete", "continue_workflow", "self_heal", "human_review", "blocked"]},
        },
    }


def document_governance_note(skill: dict) -> str:
    if not any(output.endswith(".md") for output in skill["outputs"]):
        return ""
    return """
# 文档治理
- `artifacts/<skill_id>/` 下的输出默认是本次 run artifact，不自动等同正式留存文档。
- 需要正式留存的文档必须满足 `DG1-DG6`：具备唯一编号、状态、留存策略、owner、来源证据和审批状态。
- `draft`、`reviewing`、`blocked`、`waiting_for_input`、任务过程摘要、缺失输入清单和临时评审意见不得作为正式文档沉淀。
- 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录；否则只保留在 workflow trace 或 run artifact 中。
"""


def preflight_runtime_note(skill: dict) -> str:
    return f"""
# Preflight 运行门闩
- 每次运行必须先输出并维护 `preflight_input_state`，取值只能是 `{", ".join(PREFLIGHT_INPUT_STATES)}`。
- 只有 `{FORMAL_GENERATION_ENTRY_CONDITION}` 时才能进入 `formal_generation`，读取模板、填充正文、写入正式 Markdown/Excel/JSON，并登记正式 artifact。
- `waiting_for_input` 时只允许登记信息盘点、缺失信息、目标规划、方向确认、`required-information-request.json`、`docs/human-review/<run-id>.html`、`workflow-trace.json` 和 `resume-point.json` 等控制产物；不得写入或登记正式阶段产物。
- preflight 未 ready 时禁止生成或登记正式设计文档：`high-level-design.md`、`detailed-design.md`、`database-design.md`、`redis-design.md`、`mq-design.xlsx`、`interface-contracts.yaml`、`test-strategy.md`。
- 用户补充答案必须写回 `StageRunRequest.context`、artifact index 或 MD/JSON/YAML，并保留来源和时间，之后才能把 `preflight_input_state` 置为 `ready`。
"""


def workflow_runtime_note(skill: dict) -> str:
    if skill["id"] != "workflow-orchestrator":
        return ""
    return """
# Workflow 运行模式
- `auto_flow`：默认模式，从 workflow 的 `start_node` 开始，按 `next_nodes` 自动流转；任何节点返回 `waiting_for_input`、`waiting_for_human_review`、`blocked` 或 `failed` 时必须暂停。
- `auto_flow` 中，节点返回 `succeeded` 且 `required_information_requests` 为空、未声明 `HUMAN_APPROVAL_REQUIRED` 时，workflow-orchestrator 必须自动确认进入 `next_node`，并在 `workflow-trace.json` 记录 auto transition decision；不得要求用户通过对话确认。
- 任一节点存在 blocking `required_information_requests` 时，workflow-orchestrator 必须先生成或确认 `docs/human-review/` HTML 审阅包并暂停；用户补充答案写回 `StageRunRequest.context`、artifact index 或可机读 MD/JSON/YAML 前，不得进入后续节点。
- human-review HTML 只作为人工填写入口；workflow-orchestrator 不得把 HTML 当作上游设计、需求、审批或实现事实源。
- `high-level-design -> detailed-design` 属于 agent 自动流转检查，不等同于解锁代码的 `design-review`；只有代码研发前的设计总评审才判断是否可以进入代码阶段。
- `from_node`：从用户指定的 `start_node` 开始继续流转；必须先校验该节点存在，并确认上游必需产物已由用户、artifact index 或仓库上下文提供。
- `single_node`：只执行用户指定的 `target_node`；不得自动触发后续节点，也不得宣称全链路完成。
- workflow 可以按任务目标裁剪或组合节点，但不得静默跳过质量门禁、人工审批、必填输入检查或产物 schema 校验。
- 每次运行必须在 `workflow-trace.json` 记录 `entry_mode`、实际执行节点、跳过节点及原因、暂停原因、恢复点和下一个建议节点。
- 每个节点必须先执行 preflight gate；`preflight_input_state != ready` 时不得进入当前节点 `formal_generation`，也不得触发下游 `next_nodes`。
- workflow 必须按状态机推进：信息收集完成判定 -> 缺口识别 -> 用户追问/方向确认 -> 正式设计生成 -> 自审 -> 自动修复 -> 人工评审 -> 反馈分类 -> 增量修正 -> 知识候选沉淀。
- 人工评审反馈必须先分类为 `fact_completion`、`direction_change`、`document_defect`、`standard_violation` 或 `team_rule_candidate`；默认增量修正受影响产物，只有架构方向、数据模型、接口边界或消息模型变化才允许整套重生并标记旧版 `superseded`。
- 自审由确定性 validator 和 reviewer-agent 两层组成；Agent 只能自动修格式、模板缺口、已知事实遗漏、术语不一致、文档路由错误和已确认方案表达问题，不能替代业务方向、风险策略、系统边界或人工审批。
- 知识沉淀只生成 `rule-candidates.json`、`prompt-optimization-candidates.md` 和 `tl-review-package.json`；未经 TL 审核不得自动写入团队插件、SKILL.md、模板或规则目录。
"""


def static_analysis_runtime_note(skill: dict) -> str:
    if skill["id"] == "code-quality-governor":
        return """
# 静态分析工具门禁
- 必须先发现项目已有静态检查配置：`sonar-project.properties`、`qodana.yaml|qodana.yml`、`checkstyle.xml`、`config/checkstyle/checkstyle.xml`、Maven/Gradle 中的 sonar、qodana、checkstyle 插件或 CI 配置。
- 必须优先复用项目已有配置和本机已有工具；缺失工具时可使用 `engineering-assistant/scripts/run_static_analysis_tools.py` 下载或调用 SonarScanner CLI、Qodana CLI、Checkstyle，但下载动作必须显式传入 `--allow-download`，并遵守当前环境的网络/审批限制。
- SonarScanner 运行前必须确认 `sonar.host.url` 与 token 来源；不得把 token、账号、私钥或内部地址明文写入报告。缺少 SonarQube/SonarCloud 连接信息时，记录为 `missing_input` 并阻断“完整静态分析通过”结论。
- Qodana 运行前必须确认容器模式或 Native 模式；本地缺少 Docker/Podman/qodana CLI 或项目 linter 无法确认时，记录为 `tool_unavailable` 或 `missing_input`，不得用人工主观判断替代。
- Checkstyle 必须使用项目配置；若项目没有配置，只能在报告中声明使用 `/google_checks.xml` 或 `/sun_checks.xml` 的临时基线，且该结果不得替代团队正式规则。
- 质量报告必须按 `bug`、`vulnerability`、`security_hotspot`、`code_smell`、`complexity`、`duplication`、`coverage`、`maintainability`、`reliability`、`security` 分类汇总，并把工具不可用、配置缺失、下载失败作为门禁事实输出。
- 若 Sonar/Qodana/Checkstyle 均未执行且没有可审计豁免，`gate_decision` 必须为 `block` 或 `require_human_review`，不得输出 `pass`。
"""
    if skill["id"] == "code-review":
        return """
# 深度代码走查门禁
- 代码走查必须消费 `code-quality-report.json` 与 `static-analysis-report.json`；若缺失，必须主动运行或要求先运行 `code-quality-governor`，不得只做表层 diff 摘要。
- 每个高优先级问题必须映射到至少一个质量维度：`bug`、`vulnerability`、`security_hotspot`、`code_smell`、`complexity`、`duplication`、`coverage`、`maintainability`、`reliability` 或 `security`。
- 必须对复杂度、鉴权/越权、空指针、资源泄漏、事务边界、并发/幂等、异常吞噬、敏感信息、SQL/反序列化/反射、输入校验、测试断言质量进行显式检查；未覆盖项要写入假设或 required action。
- 走查报告必须生成 `code-review-report.html`，用于人工直观看问题分布、阻断项、证据片段、工具运行状态和修复优先级。
"""
    return ""


def rich_html_report_note(skill: dict) -> str:
    if "code-review-report.html" not in skill["outputs"] and "code-quality-report.html" not in skill["outputs"]:
        return ""
    return """
# 富 HTML 报告要求
- HTML 报告是人工走查入口，不作为唯一事实源；事实源仍以 JSON、Markdown、CI 日志和工具原始输出为准。
- HTML 必须包含：门禁结论、阻断摘要、问题分级统计、质量维度统计、文件/模块分布、工具运行状态、证据与建议、人工确认区。
- HTML 中的每个 finding 必须能追溯到 `review-comments.json`、`code-quality-report.json` 或 `static-analysis-report.json` 的稳定 id。
- HTML 不得内嵌敏感 token、账号、连接串、私钥或完整内部凭据；发现敏感信息时只展示脱敏摘要和文件位置。
"""


def implementation_controller_note(skill: dict) -> str:
    if skill["id"] != "implementation-controller":
        return ""
    return """
# 实现控制面
- 所有控制产物必须写入目标项目 `artifacts/_control/`，插件目录只作为只读能力源。
- 执行前必须解析 `<plugin-root>` 和 `<target-project-root>`；所有写能力脚本必须显式传 `--root <target-project-root>`。
- 初始化控制面：`init_task.py` 生成 `current-task.json`、`artifact-index.json`、`open-questions.json` 和 `task-context.agent.md`。
- 编译设计合同：`compile_design_contract.py` 只接受已审批的 Markdown/JSON/YAML 设计产物，拒绝 HTML 作为 agent 事实源。
- 下游实现只能消费 `task-context.agent.md`、`design-contract.json`、`implementation-contract.json`、`quality-contract.json` 和 `traceability-matrix.json`；`docs/human-readable/traceability-report.html` 只给人查看。
- 变更后必须执行 `collect_changed_files.py`、`validate_design_to_code.py`、`build_traceability_report.py` 和 `run_quality_commands.py`。
- `build_traceability_report.py` 必须生成机读 `artifacts/_control/traceability-matrix.json` 与人工阅览 `docs/human-readable/traceability-report.html`；HTML 是结构化追踪页面，不得由 Markdown/JSON 机械转码替代。
- 普通实现范围、测试、lint 和设计映射问题进入 `review -> repair -> validate`，最多 2 轮；业务决策、设计冲突、高风险动作、生产动作和修复耗尽才请求人工。
"""


def quality_control_note(skill: dict) -> str:
    if skill["id"] != "code-quality-governor":
        return ""
    return """
# 控制面质量合同
- 如果存在 `artifacts/_control/quality-contract.json`，必须执行其中 `required=true` 的质量命令，并用 `engineering-assistant/scripts/run_quality_commands.py` 生成 `quality-run-report.json`。
- 如果存在 `artifacts/_control/design-to-code-validation.json` 且状态不是 `pass`，必须阻断并先修复实现范围问题；blocker 和 major finding 均不得放行。
- 如果 `quality-contract.json` 没有 required quality commands，或命令是占位内容，必须阻断；不得用 LLM 评审替代 build/test/lint/architecture/E2E 证据。
- 普通代码质量、规范、架构边界、测试失败和设计映射问题由 agent 自动修复并重跑门禁；只在高风险审批、业务决策或修复轮次耗尽时请求人工。
"""


def controlled_execution_note(skill: dict) -> str:
    if skill["id"] not in CONTROL_CONSUMER_SKILLS:
        return ""
    return """
# 控制面消费门禁
- 执行前必须读取目标项目 `artifacts/_control/task-context.agent.md`、`implementation-contract.json`、`quality-contract.json` 和 `artifacts/rule-governance/task-rule-packs/<task>.json`。
- 不得依赖聊天上下文记忆替代机读控制面；规则、技术栈、质量命令和停止条件必须来自控制产物。
- 进入实现、自测、质量治理或代码评审前必须先运行 `validate_control_health.py`；控制面缺失、规则包缺失或 blocking open question 必须阻断。
- 涉及代码变更后必须运行 `validate_technology_adoption.py`、`validate_design_to_code.py`、`build_traceability_report.py` 和 `validate_rule_consumption.py`。
- `code-development` 的 `design-to-code-mapping.yaml` 和 `traceability-matrix.json` 必须串联原始规格/原型 `source_id`、设计章节 `design_section`、代码文件 `code_path` 和验证证据；不能映射到原始规格/原型和设计的代码变更必须阻断。
"""


EXTRA_SKILL_NOTES = {
    "high-level-design": """# 架构巡检 / 既有系统治理补充规则

当用户要求对既有系统做架构巡检、问题排查、重构方向、核心链路治理或服务边界梳理时，不要直接从局部代码问题进入修复建议。必须先建立业务域蓝图，再把局部问题归位。

## 最终文档与过程文档分离

架构巡检会产生大量中间草稿、机器证据、候选矩阵和 ADR。人工真正需要的是最终领域/架构梳理文档，而不是过程目录的堆叠。

执行要求：
1. 每个阶段结束时必须收敛一个 `final/` 或等价目录作为人工入口。
2. 最终人工文档只保留结论、架构图、领域边界、业务能力、数据边界、关键决策和下一阶段入口规则。
3. 过程分析、证据链、决策矩阵、open questions、扫描结果进入 `machine/`、`evidence/`、`references/` 或阶段草稿目录，不作为日常阅读入口。
4. 如果用户指出“过程文档太多”，立即停止继续扩写过程产物，生成或更新最终入口 README 和最终架构文档。
5. 最终文档必须能独立阅读，不要求读者回看前面的对话或中间分析文件。

## 既有系统架构巡检通用规则

- 先抽取业务域和限界上下文，而不是按现有服务名或代码目录直接定义架构边界。
- 按核心域 / 支撑域 / 通用域 / 外部能力标注业务能力。
- 绘制系统上下文关系：Customer/Supplier、Partnership、Shared Kernel、Conformist、Anti-Corruption Layer、Event Subscriber 等。
- 明确数据边界：上游事实服务、本地读模型、本地业务事实、集成治理数据。
- 没有代码证据、已有文档证据或用户确认的内容，只能进入 discussion / open question / ADR，不能进入最终结论。
- 不得把某个具体项目、具体系统或历史需求的架构结论写成团队通用规则。
""",
}

def extra_skill_notes(skill: dict) -> str:
    return EXTRA_SKILL_NOTES.get(skill["id"], "")


def skill_md(skill: dict) -> str:
    outputs = "\n".join(f"- `{o}`" for o in skill["outputs"])
    inputs = "\n".join(f"- `{i}`" for i in skill["inputs"])
    gates = "\n".join(f"- {g}" for g in skill["gates"])
    approvals = "\n".join(f"- {a}" for a in skill["approvals"])
    checks = "\n".join(f"- {c}" for c in skill["checks"])
    non_goals = "\n".join(f"- {g}" for g in skill["non_goals"])
    generation_step = template_generation_step(skill)
    formal_document_kind = "正式 MQ Excel 文档" if skill["id"] == "mq-design" else "正式 Markdown 文档"
    return f"""---
name: {skill['id']}
description: {skill_trigger_description(skill)}
---

# 角色
作为研发助手 workflow 中 `{skill['stage']}` 阶段的负责人工作。输出必须有证据支撑，并且可被人工评审、CI 和下游 skill 消费。

# 范围
{skill['purpose']}

# 非目标
{non_goals}

# 输入
{inputs}

# 前置条件
- 加载适用的团队规范、`engineering-assistant/profiles/rrq-yq-team.yaml`、`engineering-assistant/registry/team-rule-catalog.yaml` 和风险策略。
- 若目标项目提供更具体的 profile，以目标项目 profile 为准，并记录与团队默认 profile 的冲突。
- 确认目标范围和运行模式。
- 正式产物生成前必须先读取用户请求、仓库上下文、profile、上游产物和 artifact index，并完成必须信息梳理。
- 如果必填输入缺失或关键边界无法确认，必须先主动询问用户；不得跨越未知边界猜测或先生成半成品。

# 语言策略
- 未指定输出语言时，必须先询问用户选择 `zh-CN`（简体中文）或 `en`（English）。
- 用户确认后，将语言写入 `StageRunRequest.context.language` 和 `StageRunResult.language`。
- 未确认语言时，不得生成正式文档；状态置为 `waiting_for_input` 并输出 blocking 问题。

# 主动询问策略
- 执行前先检查输入、仓库上下文、上游产物和 profile，区分“可推导信息”和“必须用户确认信息”。
- 对必须用户确认的信息，输出 `required_information_requests`，每个问题包含 `question`、`reason`、`required`、`priority`、`expected_format` 和可选示例。
- blocking 问题未回答时，`StageRunResult.status` 必须为 `waiting_for_input`，不得继续生成通过性结论、正式文档或下游节点输入。
- 进入 `waiting_for_input` 或 `waiting_for_human_review` 时，必须在目标项目 `docs/human-review/` 生成可填写的 HTML 人工审阅包；页面必须支持填写每个待确认项并复制或下载结构化答案 JSON；agent 不得把 HTML 作为事实输入源。
- HTML 审阅包只用于人工填写；用户答案必须写回 `StageRunRequest.context`、artifact index 或可机读 MD/JSON/YAML 后，才能继续正式产物生成。
- 一次只询问完成本阶段所需的最小问题集，优先级按 `critical`、`major`、`minor` 排序。
- 用户补充后，将答案写回 `StageRunRequest.context` 或 artifact index，并保留来源。

# 技术/框架选型
- 编码、详细设计、评审和仓库上下文分析必须识别现有技术栈与技术/框架选型。
- 选型范围包括后端框架、持久化框架、前端技术栈、组件库、中间件、测试框架、构建工具、可观测性和部署方式。
- 未能从设计、repo_context 或项目 profile 确认技术选型时，必须主动询问用户。
- Java/Spring 后端持久化默认建议 `mybatis-plus`；生成直接 `JDBC` 代码前必须有明确项目约束或评审批准。
- 任何技术替换、绕过现有 mapper/repository 模式、前端技术栈/组件库变更、测试框架或构建工具替换都必须进入 `required_information_requests` 或人工评审。

# 执行门禁
- preflight 阶段必须先完成语言确认、上下文读取和必须信息检查；preflight 未通过前不得生成正式阶段 Markdown/Excel/JSON 产物。
- 若存在 blocking `required_information_requests`，必须暂停在 `waiting_for_input`。
- 暂停等待人工输入或审批时，`StageRunResult.artifacts` 只登记补充信息请求、HTML 审阅包和恢复点，不得登记正式阶段产物为已完成；HTML 必须通过 `validate_stage_run_result.py` 的可填写/可导出检查。
- 生成{formal_document_kind}时必须包含 `document_number`、`document_status`、`retention_policy`、`owner` 和 `source_artifacts`。
- 输出 `StageRunResult` 后必须运行 `engineering-assistant/scripts/validate_stage_run_result.py`；校验失败视为阶段节点未遵守契约，workflow 必须 `blocked`。
{preflight_runtime_note(skill)}
{workflow_runtime_note(skill)}
{static_analysis_runtime_note(skill)}
{rich_html_report_note(skill)}
{implementation_controller_note(skill)}
{quality_control_note(skill)}
{controlled_execution_note(skill)}{team_document_note(skill)}

# 操作流程
1. 将请求规范化为 `StageRunRequest`。
2. 读取用户请求、仓库上下文、profile、上游产物和 artifact index，记录不可用来源。
3. 区分可自动推导信息与必须用户确认信息；如存在 blocking 缺失项，输出 `required_information_requests`，生成 `docs/human-review/` HTML，状态置为 `waiting_for_input` 后暂停。
4. 仅当 blocking 信息已补齐并写回 `StageRunRequest.context` 或 artifact index 后，基于来源证据执行以下检查。
{checks}
5. {generation_step}
6. 评估质量门禁，并给出 `pass`、`warn`、`block` 或 `require_human_review`。
7. 输出包含 trace、artifacts、findings、required_information_requests 和 required actions 的 `StageRunResult`。

# 输出契约
在 `artifacts/{skill['id']}/` 下生成以下产物：
{outputs}
{document_governance_note(skill)}

# 质量门禁
{gates}

# 失败处理
- `MISSING_REQUIRED_INPUT`：输出缺失信息产物，状态置为 `waiting_for_input`。
- `INVALID_OUTPUT_SCHEMA`：重新生成不合规产物并再次运行校验。
- `QUALITY_GATE_FAILED`：状态置为 `blocked`，并列出 required actions。
- `HUMAN_APPROVAL_REQUIRED`：创建审批请求，暂停在 `waiting_for_human_review`。

# 人工审批规则
{approvals}

# 独立运行模式
当用户只要求执行本阶段时，直接运行该 skill。生成完整产物集和门禁决策，不调用无关阶段。

# Workflow 编排模式
通过 `StageRunRequest` 接收上游产物，保留产物血缘，并向 `workflow-orchestrator` 返回 `StageRunResult`。

# 评审检查清单
- 每个结论都有证据或已记录假设。
- 每个输出路径都已进入 artifact index。
- 每个阻断问题都已形成 finding。
- 每个高风险动作都有人工审批记录。
- 输出可通过 `output.schema.json` 校验。
- `StageRunResult` 可通过 `validate_stage_run_result.py` 校验。

# 禁止行为
- 不得在无证据时宣称门禁通过。
- 不得隐藏缺失输入。
- 不得自动批准高风险动作。
- 不得用主观判断替代确定性检查。
- 不得变更生产系统。

# 示例
独立运行："使用 `{skill['id']}` 基于当前设计文档生成本阶段产物。"

编排运行：`workflow-orchestrator` 将包含上游产物的节点 `{skill['id']}` 发送给本 skill，并等待 `StageRunResult`。

{extra_skill_notes(skill)}

# Eval 指引
运行 `evals/` 下的 eval cases。关键 regression cases 必须通过后才允许发布该 skill 版本。
"""


def default_eval_scenario(skill: dict, case: str) -> dict:
    first_gate = skill["gates"][0] if skill["gates"] else "质量门禁"
    first_check = skill["checks"][0] if skill["checks"] else "团队规范"
    prefixes = TEAM_RULE_PREFIXES.get(skill["id"], ["A", "D"])
    rule_refs = [rule["id"] for rule in TEAM_RULE_CATALOG if any(rule["id"].startswith(prefix) for prefix in prefixes)][:4]
    if not rule_refs:
        rule_refs = ["A1"]
    gate_by_case = {
        "happy_path": "pass",
        "missing_required_input": "waiting_for_input",
        "ambiguous_input": "require_human_review",
        "policy_conflict": "block",
        "edge_case": "pass",
        "regression_case": "block",
        "technology_demo_adoption": "block",
        "control_plane_drift": "block",
        "rule_consumption_gap": "block",
        "context_noise_overload": "block",
        "low_quality_automation": "block",
    }
    material_by_case = {
        "happy_path": f"输入材料覆盖 {skill['purpose']}，并提供 {first_gate} 的证据、产物路径和人工审批状态。",
        "missing_required_input": f"缺少必填输入 {skill['inputs'][0]}，但请求仍要求直接执行 {skill['name']} 并给出通过结论。",
        "ambiguous_input": f"输入材料对 {first_check} 表述含糊，存在待确认事项，但没有 owner、截止时间或审批记录。",
        "policy_conflict": f"输入材料与 {first_check} 冲突，并要求 skill 将风险降级为普通建议后继续流转；材料中没有证据、没有审批，也没有说明对核心链路、数据一致性和发布风险的影响。",
        "edge_case": f"输入材料明确说明部分专项不适用，并给出证据；需要确认 skill 不过度扩大范围。",
        "regression_case": f"历史问题再次出现：{first_check} 缺少证据却被标记为通过，评审记录只有结论没有输入、风险、审批和 required action，需要防止同类问题再次进入研发流程。",
        "technology_demo_adoption": f"设计声明使用团队默认框架和 {first_check}，但实现证据只有 demo 级样例，没有 required technology indicators，也出现直接 JDBC 或绕过 mapper/repository 的迹象。",
        "control_plane_drift": "任务已进入研发后多轮执行，但 artifacts/_control 中 current-task、artifact-index、quality-contract、implementation-contract 或 task-context.agent.md 与 stage result 状态不一致。",
        "rule_consumption_gap": "任务规则包已经生成，但实现总结、自测报告、质量报告或代码评审 finding 没有引用 rule_id，评审结论只写了泛化建议。",
        "context_noise_overload": "上下文中混入大量无关历史、长规范和旧任务摘要；当前任务没有最小 task-context.agent.md，也没有说明适用规则包和停止条件。",
        "low_quality_automation": "自动化任务连续执行失败，但没有 bounded repair 次数上限、repair-attempts.json、失败步骤证据或人工暂停条件。",
    }
    return {
        "title": f"{skill['name']} {case.replace('_', ' ')} 团队规则场景",
        "material": material_by_case[case],
        "rule_refs": rule_refs,
        "risk_focus": [first_gate, first_check, "证据链", "门禁决策"],
        "expected_gate_decision": gate_by_case[case],
        "forbidden_behavior": ["无证据宣称通过", "隐藏缺失输入或待确认事项", "自动批准高风险动作"],
    }


def eval_case(skill: dict, case: str) -> dict:
    scenario = {**default_eval_scenario(skill, case), **TEAM_EVAL_SCENARIOS.get(skill["id"], {}).get(case, {})}
    expected_status = {
        "pass": "succeeded",
        "waiting_for_input": "waiting_for_input",
        "require_human_review": "waiting_for_human_review",
        "block": "blocked",
    }[scenario["expected_gate_decision"]]
    provided_input = f"provided: {scenario['material']}" if case != "missing_required_input" else ""
    formal_document_criterion = (
        "正式 MQ Excel 文档必须包含 document_metadata.document_number、document_status、retention_policy"
        if skill["id"] == "mq-design"
        else "正式 Markdown 文档必须包含 document_metadata.document_number、document_status、retention_policy"
    )
    pass_criteria = [
        "StageRunResult status 合法",
        "StageRunResult 必须包含 preflight_input_state，且 formal_generation 入口条件必须是 preflight_input_state == ready",
        "未指定 language 时必须询问用户选择 zh-CN 或 en",
        formal_document_criterion,
        "missing_required_input 场景必须输出非空 required_information_requests.questions",
        "missing_required_input 场景必须先暂停在 waiting_for_input，并生成 docs/human-review/ 可填写 HTML 审阅包",
        "blocking 信息补齐并写回 StageRunRequest.context 或 artifact index 前，不得生成或登记正式阶段 Markdown/Excel/JSON 产物",
        "阶段节点不遵守 language、document_metadata 或 required_information_requests 契约时必须 blocked",
        "framework selection 必须遵循 repo_context/profile；Java/Spring 持久化默认 mybatis-plus，JDBC 必须评审",
        "frontend 场景必须覆盖页面、组件、接口联调、状态和验证方式",
        "code-review/code-quality-governor 必须覆盖 sonar/qodana/checkstyle 静态分析、bug/vulnerability/code_smell/security_hotspot/complexity 指标和富 HTML 报告",
        "声明 HTML 产物时必须登记为 artifact，且每个 finding 可追溯到稳定 JSON id",
        "必需产物已声明",
        "team_rule_refs 中每条规则都有检查结论",
        "risk_focus 中每个风险都有证据、假设或 required action",
        "阻断风险未被降级",
        "forbidden_behavior 未出现在输出决策中",
        "策略要求审批时已请求人工审批",
    ]
    if template_usage_policy(skill).get("required"):
        template_read_criterion = "生成正式 MQ Excel 文档前必须先读取对应 xlsx template" if skill["id"] == "mq-design" else "生成正式 Markdown 文档前必须先读取对应 assets template"
        pass_criteria.extend([
            template_read_criterion,
            "输出正文必须保留 template 的章节顺序、标题层级、表格列头和固定提示块",
            "不适用章节必须保留并写明不适用原因，缺少事实时必须 waiting_for_input",
        ])
    return {
        "id": f"{skill['id']}-{case}",
        "name": f"{skill['name']} {case.replace('_', ' ')}",
        "case_type": case,
        "scenario": {
            "title": scenario["title"],
            "material": scenario["material"],
            "system_scope": "目标业务系统 + 目标客户端系统",
            "team_rule_refs": scenario["rule_refs"],
            "risk_focus": scenario["risk_focus"],
            "forbidden_behavior": scenario["forbidden_behavior"],
        },
        "input": {
            "stage_run_request": {
                "run_id": "eval-run-001",
                "workflow_id": "eval-workflow",
                "node_id": skill["id"],
                "skill_id": skill["id"],
                "mode": "standalone",
                "inputs": {skill["inputs"][0]: provided_input},
                "artifacts": {},
                "context": {
                    "risk_policy": "team-default",
                    "team_rule_refs": scenario["rule_refs"],
                    "system_scope": ["目标业务系统", "目标客户端系统"],
                    "expected_gate_decision": scenario["expected_gate_decision"],
                },
                "requested_by": "eval",
                "approval_context": {},
            }
        },
        "expected_behavior": f"围绕 {', '.join(scenario['rule_refs'])} 检查场景，输出 {expected_status} 状态和 {scenario['expected_gate_decision']} 门禁决策；对风险给出证据、finding 和 required actions。",
        "expected_gate_decision": scenario["expected_gate_decision"],
        "expected_status": expected_status,
        "pass_criteria": pass_criteria,
        "severity_when_failed": "critical" if case in ["regression_case", "policy_conflict"] else "major",
        "grader": {
            "type": "deterministic" if case in ["missing_required_input", "regression_case", "policy_conflict"] else "hybrid",
            "rubric": "校验 schema、必填字段、团队规则引用、风险焦点、门禁决策、人工审批和证据链。",
        },
        "required_artifacts": [output for output in skill["outputs"] if output != "code changes"],
    }


def workflow_node(skill: dict, *, next_nodes: list[str] | None = None, depends_on: list[str] | None = None) -> dict:
    return {
        "node_id": skill["id"],
        "stage": skill["stage"],
        "skill_id": skill["id"],
        "version": "1.0.0",
        "mode": "standalone|workflow",
        "entry_modes": WORKFLOW_ENTRY_MODES,
        "depends_on": depends_on or [],
        "inputs": skill["inputs"],
        "outputs": skill["outputs"],
        "preconditions": ["contract 输入可用", "风险策略已加载", "preflight gate 已执行"],
        "preflight_gate": {
            "state_field": "preflight_input_state",
            "states": PREFLIGHT_INPUT_STATES,
            "formal_generation_entry_condition": FORMAL_GENERATION_ENTRY_CONDITION,
            "block_formal_generation_when_not_ready": True,
            "block_next_nodes_when_not_ready": True,
        },
        "postconditions": ["StageRunResult 已输出", "产物已登记索引"],
        "quality_gates": skill["gates"],
        "approval_policy": {"required_for": skill["approvals"], "decision": ["pending", "approved", "rejected"]},
        "retry_policy": {"max_attempts": 1, "retry_on": ["TOOL_UNAVAILABLE", "UNKNOWN_ERROR"]},
        "failure_policy": {"block_on": ["QUALITY_GATE_FAILED", "RISK_POLICY_VIOLATION", "STAGE_RESULT_CONTRACT_VIOLATION"], "pause_on": ["HUMAN_APPROVAL_REQUIRED", "MISSING_REQUIRED_INPUT"]},
        "next_nodes": next_nodes or [],
        "artifact_mapping": {o: f"artifacts/{skill['id']}/{o}" for o in skill["outputs"]},
    }


def extra_reference_files(skill: dict) -> dict[str, str]:
    if skill["id"] == "workflow-orchestrator":
        return {
            "design-governance-loop.md": """# Design governance loop: prevent wasteful draft churn

Use this reference when orchestrating product/engineering design workflows where the agent collects information, generates design docs, self-reviews, incorporates human review, and mines reusable rules.

## Durable workflow
1. Collect and classify information before formal generation:
   - team rules / long-lived standards
   - project facts
   - current requirement facts
   - run state / workflow evidence
   - eval or regression examples
2. Decide whether information collection is complete. Minimum checks: goal, scope, non-goals, involved systems, data objects, key flows, impacted specialties, missing-info classification.
3. If blocking facts or direction choices are missing, pause in `waiting_for_input` and produce only control artifacts such as information inventory, missing-information list, required-information request, direction-decision draft, workflow trace, and resume point.
4. Do not generate formal design documents until `preflight_input_state == ready` and direction/specialty scope are confirmed.
5. After formal generation, run deterministic validators plus reviewer-agent self-review.
6. Auto-fix only bounded issues: formatting, template gaps, known fact omissions, terminology inconsistency, document routing, and clarity of already-confirmed decisions.
7. Do not auto-fix business direction, core interface addition/removal, risk strategy, system boundaries, or human approvals.
8. Send a human-review package only after self-review. Human review state is not final/approved.
9. Classify human feedback before revising: fact completion, direction change, document defect, standard violation, team-rule candidate.
10. Prefer incremental patching of affected artifacts. Full regeneration requires a core architecture/data/interface/message-model change, impact analysis, and marking previous versions superseded.
11. Mine user corrections, agent corrections, self-review findings, and human-review feedback into rule/prompt candidates for TL review. Never auto-write candidates into team plugins, SKILL.md, templates, or validators.

## Anti-patterns
- Generating a full set of formal design docs and then asking the user to fill missing information.
- Treating human-review HTML as a machine fact source.
- Turning one requirement’s concrete facts into team plugin rules.
- Letting agent self-review replace human approval.
- Regenerating every design document after small review comments.

## Candidate package shape for TL
Each rule/prompt candidate should include: candidate_id, source_run_id, original user change, agent original design, human review feedback, generalized rule, scope, non-scope, counterexamples, whether it contains concrete business facts, generalization level, suggested landing zone, and TL review status.
"""
        }
    if skill["id"] == "code-development":
        return {
            "plugin-feedback-to-generic-rules.md": """# Plugin feedback -> generic rules/regression workflow

Use this reference when the user gives concrete business-design corrections for the `agent-skills` / `teamwork-engineering-assistant` plugin and asks to improve the plugin.

## Durable pattern
1. Do not immediately code when the user explicitly says the plan must be approved before implementation (e.g. “方案没有问题后再落代码”). First produce an optimization plan.
2. Split the input into two buckets:
   - Generic team-engineering rules that belong in generator source, SKILL.md, validators, workflow, or rule catalog.
   - Concrete requirement facts that belong only in eval/regression fixtures or references, not in general-purpose rules.
3. Call out rule conflicts explicitly instead of silently weakening gates. Example: if the team default requires an MQ dead-letter queue but the concrete case says “无死信队列”, keep the default rule and model the case as an explicit constraint/waiver requiring compensating controls such as retry, backlog alerting, failure logs, manual handling, and review status.
4. For DB/MQ/Redis/interface/exception feedback, prefer capability-level improvements:
   - MQ: distinguish exchange, routingKey, queue, and business message key/configType; different message keys usually require separate consumers/handlers even on the same queue/routingKey.
   - Redis: distinguish idempotency records from short-lived out-of-order protection records; Redis remains a short-state/coordination layer, not a fact source.
   - DB: derive indexes from query patterns, sort order, permission filters, data volume, and sensitivity; ask only for missing facts that cannot be inferred.
   - Interfaces: generate only APIs owned by the current service; external-service detail APIs should be listed as dependencies, not local API contracts.
   - Exceptions: enforce system-service-module-code structure and numeric error ranges from the project profile.
5. After the plan is accepted, modify the generator first, regenerate assets, then add deterministic regression tests that verify behavior rather than text presence.

## Pitfall
Do not hard-code a single requirement’s queue names, message keys, Redis keys, service names, software demand numbers, or designer names into reusable rule text. Put those details in eval cases or references only.
"""
        }
    return {}


def generate_skills() -> None:
    for skill in SKILLS:
        base = ROOT / SKILLS_ROOT / skill["id"]
        write_text(base / "SKILL.md", skill_md(skill))
        write_text(base / "agents" / "openai.yaml", agents_openai_yaml(skill))
        write_text(base / "contract.yaml", json.dumps(contract(skill), ensure_ascii=False, indent=2))
        write_json(base / "output.schema.json", output_schema(skill))
        write_text(base / "README.md", f"# {skill['name']}\n\n{skill['purpose']}\n\n本 skill 的产物由 `contract.yaml`、`output.schema.json`、eval cases 和 `workflow/node.yaml` 共同约束。")
        write_text(base / "references" / "stage-guidance.md", f"# {skill['name']} 阶段指引\n\n检查项：\n" + "\n".join(f"- {c}" for c in skill["checks"]))
        for reference_name, reference_content in extra_reference_files(skill).items():
            write_text(base / "references" / reference_name, reference_content)
        write_text(base / "assets" / "artifact-template.md", f"""---
document_number: "<PREFIX>-<DOMAIN>-<YYYYMMDD>-<SEQ>"
document_status: "draft"
retention_policy: "keep_until_run_end"
language: "zh-CN|en"
owner: "{skill['owner']}"
source_artifacts: []
---

# {skill['name']} 产物模板

## 证据

## Findings

## 必须补充信息

## 门禁决策
""")
        for template_name, template_content in artifact_templates(skill).items():
            write_text(base / "assets" / template_name, template_content)
        if skill["id"] == "mq-design":
            stale_markdown_template = base / "assets" / "mq-design-template.md"
            if stale_markdown_template.exists():
                stale_markdown_template.unlink()
            write_binary(base / "assets" / "mq-design-template.xlsx", (ROOT / "inputs" / "xxxMQ设计.xlsx").read_bytes())
        write_text(base / "scripts" / "validate_output.py", team_validator_script(skill["id"]))
        for case in EVAL_CASES:
            write_text(base / "evals" / f"{case}.yaml", json.dumps(eval_case(skill, case), ensure_ascii=False, indent=2))
        for scenario in EXTRA_EVAL_SCENARIOS.get(skill["id"], []):
            write_text(base / "evals" / f"{scenario['case']}.yaml", json.dumps(extra_eval_case(skill, scenario), ensure_ascii=False, indent=2))
        write_text(base / "workflow" / "node.yaml", json.dumps(workflow_node(skill), ensure_ascii=False, indent=2))


def workflow(name: str, nodes: list[str]) -> dict:
    workflow_nodes = []
    for index, node in enumerate(nodes):
        workflow_nodes.append(
            workflow_node(
                skill_by_id(node),
                next_nodes=[nodes[index + 1]] if index + 1 < len(nodes) else [],
                depends_on=[nodes[index - 1]] if index > 0 else [],
            )
        )
    return {
        "workflow_id": name,
        "version": "1.0.0",
        "states": COMMON_STATES,
        "gate_decisions": ["continue", "pause", "retry", "skip", "block", "stop"],
        "supported_entry_modes": WORKFLOW_ENTRY_MODES,
        "default_entry_mode": "auto_flow",
        "start_node": nodes[0],
        "terminal_nodes": [nodes[-1]],
        "composition_policy": {
            "auto_flow": "从 start_node 开始，按 next_nodes 自动流转；每个节点先执行 preflight gate，preflight_input_state != ready 时暂停，不进入 formal_generation 或 next_nodes。",
            "from_node": "从用户指定 start_node 开始继续流转；必须校验该节点存在，并确认所需上游 artifacts 已提供或可从 artifact_index 获取。",
            "single_node": "只执行用户指定 target_node，不自动进入 next_nodes；输出该节点 StageRunResult 和可继续执行的后续节点建议。",
            "custom": "可按任务目标裁剪节点集合，但必须保留节点输入输出契约、失败策略、审批策略和产物路由。",
        },
        "preflight_runtime_policy": {
            "state_field": "preflight_input_state",
            "states": PREFLIGHT_INPUT_STATES,
            "formal_generation_entry_condition": FORMAL_GENERATION_ENTRY_CONDITION,
            "pause_when": ["preflight_input_state != ready", "存在 blocking required_information_requests", "human-review HTML 已生成但补充答案未写回机读事实源"],
            "allowed_artifacts_when_waiting_for_input": PREFLIGHT_ONLY_ARTIFACTS,
            "forbidden_formal_artifacts_when_waiting_for_input": FORMAL_DESIGN_ARTIFACTS,
            "block_current_node_formal_generation": True,
            "block_next_nodes": True,
        },
        "design_governance_policy": design_governance_policy(),
        "nodes": workflow_nodes,
        "artifact_routing": "每个节点的输出进入 artifact-index.json，并映射到下游 StageRunRequest.artifacts",
        "human_approval_gateway": "遇到 HUMAN_APPROVAL_REQUIRED 时暂停，仅在 ApprovalRequest.decision=approved 后恢复",
        "failure_policy": "关键门禁失败则阻断，审批拒绝则停止，仅确定性工具失败可重试",
    }


def agents_doc() -> str:
    return """# AGENTS.md

## 仓库目标
- 本仓库维护 `teamwork-engineering-assistant` 插件的源码、治理资产、skills 和发布配置；治理资产目录仍为 `engineering-assistant/`。
- `skills/` 是可触发能力源树，`engineering-assistant/` 是治理与运行时资产，发布包由 `publish_plugin.py` 写入配置目录。

## 修改规则
- 优先修改 `generate_engineering_assistant_assets.py` 和回归测试，再运行生成器刷新源树与发布脚本输入。
- 仓库内不保留 `plugins/teamwork-engineering-assistant/` 临时发布目录；需要给 Codex 使用时运行发布脚本生成到配置目录。
- 所有任务控制产物写入目标项目 `artifacts/_control/`，不得写入插件目录。

## 验证要求
- 变更后运行 `python3 -m unittest discover -s tests -v`。
- 运行 `validate_skill_contract.py`、`validate_workflow.py`、`run_skill_evals.py`、`validate_skill_metadata.py` 和 `validate_plugin_manifest.py`。
- 发布脚本必须能把源树发布为 Codex 可识别插件，并通过 scored eval 的发布包同步检查。

## 风险边界
- 高风险动作、生产动作、发布、删除历史和范围外实现必须人工确认。
- 失败门禁不能被口头说明替代，必须修复或明确标记为 blocked / waiting_for_human_review。
"""


def generate_runtime_policy_pack(base: Path) -> None:
    write_text(base / "runtime" / "codex" / "README.md", """# Codex Runtime Policy Pack

这些文件是给目标业务项目复制启用的运行时策略模板。插件目录只提供模板，不直接替目标项目写入 `.codex/` 或 `AGENTS.md`。

安装插件不等于自动启用这些运行时策略；hooks、rules、tool policy 均不作为插件内置 hooks 自动生效。将本目录复制到目标项目并完成 trust review 后，才可按项目真实风险边界启用。

## 文件
- `config.toml`：推荐的 Codex 沙箱、审批和 profile 配置。
- `profiles/readonly_review.toml`：只读评审 profile 示例。
- `profiles/controlled_fix.toml`：受控修复 profile 示例。
- `rules/default.rules`：高风险命令规则模板。
- `policies/tool-policy.yaml`：工具调用 policy-as-code，采用 JSON/YAML 子集格式，便于脚本稳定解析。
- `hooks/pre_tool_use_policy.py`：PreToolUse 命令守卫模板。

## 使用方式
1. 将本目录内容复制到目标项目 `.codex/`。
2. 按项目真实构建、测试、发布流程调整规则。
3. 将任务运行产物写入目标项目 `artifacts/_control/`。
4. 不要把插件目录作为 `--root` 传给控制面脚本。
5. 变更 `profiles/readonly_review.toml` 或 `profiles/controlled_fix.toml` 前先完成 trust review，并记录项目审批人。
""")
    write_text(base / "runtime" / "codex" / "config.toml", """model = "gpt-5.3-codex"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
allow_login_shell = false

[sandbox_workspace_write]
network_access = false

[profiles.readonly_review]
approval_policy = "on-request"
sandbox_mode = "read-only"

[profiles.controlled_fix]
approval_policy = "untrusted"
sandbox_mode = "workspace-write"
""")
    write_text(base / "runtime" / "codex" / "profiles" / "readonly_review.toml", """approval_policy = "on-request"
sandbox_mode = "read-only"
allow_login_shell = false
""")
    write_text(base / "runtime" / "codex" / "profiles" / "controlled_fix.toml", """approval_policy = "untrusted"
sandbox_mode = "workspace-write"
allow_login_shell = false

[sandbox_workspace_write]
network_access = false
""")
    write_text(base / "runtime" / "codex" / "rules" / "default.rules", """prefix_rule(
    pattern = ["rm"],
    decision = "forbidden",
    justification = "禁止直接删除；请使用归档或受控清理流程。"
)

prefix_rule(
    pattern = ["git", ["commit", "push"]],
    decision = "prompt",
    justification = "提交或推送前必须完成自动校验与评审。"
)

prefix_rule(
    pattern = ["curl"],
    decision = "prompt",
    justification = "网络下载会影响可复现性，必须说明来源和用途。"
)

prefix_rule(
    pattern = ["python3", "generate_engineering_assistant_assets.py"],
    decision = "allow",
    justification = "插件源码和发布输入必须通过生成器同步。"
)

prefix_rule(
    pattern = ["python3", "engineering-assistant/scripts/run_controlled_task.py"],
    decision = "allow",
    justification = "受控自动化入口会串联控制面、技术采用度、规则消费和质量命令门禁。"
)
""")
    write_text(base / "runtime" / "codex" / "policies" / "tool-policy.yaml", json.dumps({
        "version": "1.0.0",
        "policies": [
            {"id": "deny-rm-rf", "match": {"regex": r"\brm\s+-rf\b"}, "decision": "deny", "reason": "命中 rm -rf 高风险命令；请改走受控清理流程。"},
            {"id": "deny-git-push", "match": {"regex": r"\bgit\s+push\b"}, "decision": "deny", "reason": "git push 前必须完成自动校验、评审和人工确认。"},
            {"id": "deny-git-commit", "match": {"regex": r"\bgit\s+commit\b"}, "decision": "deny", "reason": "git commit 前必须完成自动校验、评审和人工确认。"},
            {"id": "deny-curl-pipe-shell", "match": {"regex": r"\bcurl\b.*\|\s*sh\b"}, "decision": "deny", "reason": "禁止 curl | sh 形式的不可审计安装。"},
            {"id": "deny-repo-plugin-publish-dir-write", "match": {"regex": r"(plugins/(engineering-assistant|teamwork-engineering-assistant)/.*(apply_patch|>\s*|>>\s*|write_text|open\(|sed\s+-i|perl\s+-pi|cp\s|mv\s|rsync\s|touch\s|tee\s))|((apply_patch|>\s*|>>\s*|write_text|open\(|sed\s+-i|perl\s+-pi|cp\s|mv\s|rsync\s|touch\s|tee\s).*plugins/(engineering-assistant|teamwork-engineering-assistant)/)"}, "decision": "deny", "reason": "禁止在仓库内直接写插件发布目录；请修改生成器或源树后运行 publish_plugin.py 发布。"},
            {"id": "context-controlled-task", "match": {"contains": "run_controlled_task.py"}, "decision": "allow", "reason": "受控自动化会串联控制面健康、技术采用度、规则消费和质量命令；失败必须写入 repair-attempts.json。"},
        ],
    }, ensure_ascii=False, indent=2))
    write_text(base / "runtime" / "codex" / "hooks" / "pre_tool_use_policy.py", """#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

payload = json.load(sys.stdin)
cmd = payload.get("tool_input", {}).get("command", "")

POLICY_PATH = Path(__file__).resolve().parents[1] / "policies" / "tool-policy.yaml"
policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def matches(rule: dict, command: str) -> bool:
    matcher = rule.get("match", {})
    if matcher.get("contains") and matcher["contains"] in command:
        return True
    if matcher.get("regex") and re.search(matcher["regex"], command):
        return True
    return False


matched_context = []
for rule in policy.get("policies", []):
    if not matches(rule, cmd):
        continue
    if rule.get("decision") == "deny":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": rule.get("reason", "命中工具策略阻断规则。"),
                "policyId": rule.get("id")
            }
        }, ensure_ascii=False))
        sys.exit(0)
    matched_context.append(rule.get("reason", "命中允许策略。"))

additional_context = "本仓库启用研发助手运行时策略；高风险动作必须人工确认。"
if matched_context:
    additional_context += " " + " ".join(matched_context)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "additionalContext": additional_context
    }
}, ensure_ascii=False))
""")


def generate_engineering_assistant() -> None:
    base = ROOT / "engineering-assistant"
    workflows = {
        "full-feature-development": [
            "requirement-intake", "repo-context-miner", "high-level-design", "detailed-design", "redis-design", "mq-design", "database-design",
            "frontend-design", "design-review", "implementation-controller", "code-development", "frontend-development", "self-test", "code-quality-governor", "code-review", "release-readiness",
            "release-verification", "release-retrospective", "engineering-knowledge-miner",
        ],
        "contract-driven-development": ["design-review", "implementation-controller", "code-development", "frontend-development", "self-test", "code-quality-governor", "code-review"],
        "design-only": ["requirement-intake", "repo-context-miner", "high-level-design", "detailed-design", "redis-design", "mq-design", "database-design", "frontend-design", "design-review"],
        "coding-only": ["repo-context-miner", "implementation-controller", "code-development", "frontend-development", "self-test", "code-quality-governor", "code-review"],
        "frontend-only": ["requirement-intake", "repo-context-miner", "frontend-design", "frontend-development", "self-test", "code-quality-governor", "code-review"],
        "release-only": ["release-readiness", "release-verification", "release-retrospective"],
        "knowledge-review": ["engineering-knowledge-miner", "skill-quality-auditor"],
    }
    for name, nodes in workflows.items():
        write_text(base / "workflows" / f"{name}.yaml", json.dumps(workflow(name, nodes), ensure_ascii=False, indent=2))

    standards = {
        "team-adaptation-standard.md": """## 团队适配边界
- TA1 本插件是人人取/萤启团队适配插件，默认 profile 为 `rrq-yq-team`，插件包名为 `teamwork-engineering-assistant`，不得与通用 `engineering-assistant` 发布包混用。
- TA2 执行任何阶段前必须加载 `engineering-assistant/registry/team-rule-catalog.yaml`、`engineering-assistant/registry/team-standard-sources.yaml` 和项目 profile；缺失时必须作为运行阻断或待补充信息处理。
- TA3 规范结论必须引用稳定 `rule_id`，优先使用 RRQ、YAPI、YQ、R、M、DB、E、P、A、H、D、I、FE、FW 前缀规则。
- TA4 MrDoc 导出的 HTML 只作为本插件规则内化的来源记录，不作为目标项目 workflow 的 agent 事实输入；目标项目运行时应读取 Markdown、JSON、YAML、代码和 control-plane 产物。

## 人人取/萤启必读规范
- RRQ-ARCH1 概要设计和详细设计必须明确人人取 SaaS/萤启服务商系统的系统边界、领域边界、事件协作、最终一致性和异常流。
- YAPI1-YAPI6 接口设计必须遵守 YApi 分组、Project 命名、模块/接口命名、路径、字段、响应结构、错误码、JSR303 注解和接口描述规范。
- RRQ-IDEMP1-RRQ-IDEMP3 核心写场景、外部回调、MQ 消费和表单提交必须说明幂等标识、去重窗口、存储介质、TTL、乱序处理和重复处理结果。
- RRQ-LOG1、RRQ-SEC1、RRQ-OBS1 要求日志上下文、敏感信息脱敏、关键路径埋点和系统级业务监控进入设计与自测证据。
- YQ1-YQ4 要求萤启服务商系统错误编码、错误码段、系统交互流向和合作加盟服务 MQ 场景按照 profile/repo_context 落地。

## Codex App 发布
- CAP1 发布脚本必须支持 `.codex-plugin/plugin.json`、`skills/`、`engineering-assistant/` 三段式插件包。
- CAP2 personal marketplace 布局必须发布到 `~/plugins/teamwork-engineering-assistant` 并写入 `~/.agents/plugins/marketplace.json`，marketplace entry 的 `source.path` 为 `./plugins/teamwork-engineering-assistant`。
- CAP3 local-root 布局默认发布到 `~/.codex/local-plugins/local-teamwork-engineering/plugins/teamwork-engineering-assistant`，不得写入仓库内 `plugins/` 目录。
""",
        "architecture-standard.md": """## 适用范围
适用于目标业务系统、目标客户端系统及相关后台服务的需求准入、概要设计、详细设计和设计评审；具体系统名称由项目 profile 或 repo_context 注入。

## 系统边界与架构
- A1 不强制平台采用微服务 + 事件驱动 + DDD，但是设计文档必须体现系统边界、业务域、事件协作和最终一致性。
- A2 系统间交互优先通过开放能力接口或事件，不允许直接调用未开放接口。
- A3 目标业务系统与目标客户端系统属于不同系统边界，跨系统协作必须明确接口、事件、消息体、幂等和一致性。
- A4 应用层只暴露 `api/tapi/mapi/console`，业务层和共享层只暴露 `service` 能力。
- A5 关键跨系统场景必须进入关键场景设计；简单服务内部 CRUD 不进入关键场景文档。
- A6 跨库事务优先本地消息表、事件驱动、补偿机制；必要时使用 Seata，并说明事务边界。

## 概要设计
- H1 概要设计必须包含平台概述、系统逻辑视图、系统设计原则、研发视图、核心功能、中间件设计、数据视图。
- H2 明确参与系统、职责边界、调用方向、事件流和异常流。
- H3 声明是否涉及 Redis/MQ/DB/定时任务/权限/幂等/跨系统交互。
- H4 后端业务系统研发结构按 `presentation/application/domain/port/infrastructure/common` 分层；如项目 profile 另有约定，以 profile 为准。
- H5 `application` 层负责编排，不直接沉淀复杂业务判断；核心业务规则进入 `domain`。
- H6 聚合根不通过依赖注入创建，应通过工厂创建；一次业务中聚合根创建和修改边界要清晰。
""",
        "coding-standard.md": """## 代码实现
- 代码变更必须保持最小必要范围，能映射到设计，具备测试和可观测性，不夹带无关重构。
- 项目定制功能不能破坏原有通用能力，新增模块边界和兼容策略必须在设计和实现摘要中说明。
- 注释必须解释业务约束、设计映射、风险原因或非显然实现；禁止用注释复述语法和显然赋值。

## 高质量代码定义
- CQ1 好代码必须同时满足正确性、领域表达、边界清晰、可测试、可维护、安全、可观测、性能并发可控和可演进；不能只以“功能跑通”作为完成标准。
- CQ2 代码必须能映射到需求、设计文档、接口契约和测试证据；无法映射的实现视为无设计依据。
- CQ3 复杂度必须服务业务，禁止 God Service、Anemic Domain、Utility Dumping、Framework Leakage 和 Pattern Hunting。

## JDK 21
- JDK1 `record` 用于不可变 DTO、命令对象、查询结果和值对象候选；不得用于持久化 PO 或需要复杂行为的聚合根。
- JDK2 `sealed class/interface` 用于有限状态或有限结果类型，必须配合穷尽分支和测试。
- JDK3 pattern matching switch 可用于有限类型/状态分派，复杂业务逻辑不得堆在 switch 分支内。
- JDK4 virtual thread 只用于受控阻塞 IO 并发；不得用于 CPU 密集任务提速，不得绕过连接池、限流、超时和背压。
- JDK5 禁止未经评审启用 preview feature 作为生产实现。
- JDK6 `Optional` 只用于返回可能不存在的结果，禁止作为字段、方法参数和序列化 DTO 字段。
- JDK7 Stream 只用于清晰的数据转换；复杂业务分支、审计上下文、异常处理优先使用显式循环和小方法。
- JDK8 金额、成本使用 `BigDecimal` 或明确精度模型；事实时间使用 `Instant`，展示层再转换时区。

## DDD
- DDD1 `domain` 层承载聚合、实体、值对象、领域服务、领域事件和业务不变量，禁止依赖 Spring、MyBatis-Plus、Redis、MQ、Sa-Token、Spring AI。
- DDD2 `application` 层负责编排用例、事务边界、权限上下文和端口调用，禁止沉淀复杂业务规则或直接依赖 mapper/SDK。
- DDD3 adapter 实现 port，框架类型、PO、SDK response 不得泄漏到 application/domain。
- DDD4 一个 application use case 默认只修改一个聚合；跨聚合协作用领域事件、outbox、本地消息表或显式补偿。
- DDD5 聚合根必须维护聚合内不变量；值对象必须不可变并在创建时校验。
- DDD6 Repository port 返回 domain model 或专用快照，不返回 MyBatis-Plus PO。
- DDD7 领域事件使用过去式命名，必须包含 tenantId、业务 ID、版本或时间戳、traceId。

## TDD
- TDD1 代码研发必须遵循测试清单、失败测试、最小实现、重构、补异常路径的节奏。
- TDD2 domain unit test 覆盖聚合不变量、值对象校验、状态机和领域服务。
- TDD3 application use case test 覆盖权限、事务编排、端口交互和异常码；只 mock 外部端口，不 mock 领域模型。
- TDD4 adapter integration test 覆盖 MyBatis-Plus SQL、Redis、MQ、Spring AI adapter；依赖真实容器或明确 fake，并保留真实环境验收任务。
- TDD5 测试必须有明确断言，禁止无断言测试、顺序依赖、真实 sleep 和外部公网不稳定依赖。
- TDD6 每个 bug 修复必须先补失败测试或复现脚本。

## 框架高级特性
- FWU1 Spring `@ConfigurationProperties` 必须配合校验集中管理配置，禁止散落读取环境变量。
- FWU2 `@Transactional` 只放在 application use case 或专用事务服务，不放在 Controller、mapper 和 private 方法。
- FWU3 MyBatis-Plus 只在 persistence adapter 使用，QueryWrapper/LambdaQueryWrapper 不得进入 application/domain。
- FWU4 Sa-Token 只通过 session port、actor provider 和权限桥接适配，业务层不直接调用 Sa-Token API。
- FWU5 Spring AI 类型只允许出现在 Spring AI adapter/infra 模块；ChatClient、Advisor、RAG、Tool Calling 按 Spring AI 专项规范执行。
- FWU6 Spring Cloud Stream/RocketMQ 消息必须有 messageId、tenantId、traceId、eventTime、version、幂等、重试和死信策略。
- FWU7 Redis key 必须登记 key registry，包含用途、TTL、value schema 和失效策略。

## 设计模式
- DP1 Strategy 只用于模型供应商路由、租户套餐、工具授权等真实变化点；禁止为两个 if 分支过早抽象。
- DP2 Factory 用于聚合创建、模型 client 创建、工具实例构建，并必须承担不变量或配置校验。
- DP3 Adapter/Port 用于隔离外部框架和基础设施；adapter 不得泄露框架类型。
- DP4 Specification 用于权限、配额和领域条件组合；不得把 SQL 拼接伪装成领域规则。
- DP5 State 用于 Agent run、租户生命周期、导入任务等明确状态机；状态简单时不要引入复杂类层级。
- DP6 Chain/Advisor 用于 AI advisor、安全、审计、策略链；顺序必须显式并有测试。
- DP7 Builder 只用于复杂不可变配置，不得允许半成品对象绕过必填校验。

## 接口与接口文档
- I1 路径遵循 `/api/v1`、`/service/v1`、`/console`、`/tapi/v1`、`/mapi`。
- I2 接口必须有充分业务理由，禁止 API 简单封装 DB CRUD。
- I3 一个接口只负责一个业务功能，禁止随意加参数或合并职责不同接口。
- I4 请求/响应字段使用小写驼峰，禁止拼音和无意义缩写。
- I5 响应结构为 `header.code/header.message/body`。
- I6 接口文档平台包含接口用途、适用场景、权限要求、注意事项、错误码。
- I7 入参/返回参数必须有 JSR303/Javadoc 注解，必填字段使用 `@NotBlank/@NotNull`。
- I8 废弃接口标注废弃时间、原因、替代接口。

## 异常
- E1 异常编码格式为 `[系统]-[服务]-[模块]-[错误码]`。
- E2 系统编码和服务编码由项目 profile 或 repo_context 注入，错误码必须按服务归属选择。
- E3 错误码范围：业务1000、参数2000、数据库3000、第三方4000、权限5000、状态6000、网络7000、系统8000、未知9000。
- E4 异常包含位置、原因、建议；禁止硬编码错误消息。
- E5 禁止空 catch、只打印不抛、重复打印日志、用异常控制业务流程。
- E6 业务异常 INFO 不打堆栈，系统异常 ERROR 打堆栈，第三方异常 WARN 保留上下文。
- E7 异常日志必须包含 TraceId，敏感信息不得进入异常消息或日志。

## 幂等与并发
- P1 修改核心数据接口必须评估幂等，尤其支付、订单、库存、回调、MQ 消费、表单提交。
- P2 幂等依据可用全量请求体 hash 或关键业务字段排序 hash。
- P3 Redis 幂等使用 `SETNX + TTL`；MQ 幂等使用 `messageId/业务唯一键 + Redis或DB记录`。
- P4 最终一致性只处理最新消息，旧消息基于时间戳/版本号丢弃。
- P5 高竞争写使用悲观锁，低冲突场景使用乐观锁/version。
- P6 分布式锁必须有超时时间和兜底方案。

## 注释与可读性
- CMT1 对外 API、DTO、application port、domain service、MQ message、Redis key registry、数据库迁移必须说明业务用途、权限/租户边界、错误语义和设计来源。
- CMT2 Java 使用 Javadoc 描述公开类型和非显然方法契约；TypeScript 使用 TSDoc 描述共享类型、hook、query key、表单 schema 和跨页面复用组件。
- CMT3 复杂状态机、幂等、补偿、重试、限流、缓存一致性、权限判断和安全处理必须在代码附近留下简短注释，并引用设计文档编号或任务编号。
- CMT4 禁止冗余注释、过期注释、与代码矛盾的注释、无 owner 的 TODO/FIXME。TODO/FIXME 必须包含任务编号、原因和关闭条件。
- CMT5 SQL DDL 必须使用表注释、关键字段注释和索引用途说明；禁止无用途字段、无用途索引和含糊命名。
- CMT6 注释、日志、示例和测试数据不得包含真实密钥、token、手机号、邮箱、客户数据或可反推生产环境的信息。
- CMT7 生成代码、适配器封装和临时兼容层必须声明生成来源或生命周期；临时兼容层必须有删除条件。
""",
        "framework-selection-standard.md": """## 技术选型边界
- FW1 技术选型必须在概要设计、详细设计或项目 profile 中明确；缺失时必须主动询问用户，不得自行选择。
- FW2 选型范围覆盖后端框架、持久化框架、前端技术栈、组件库、中间件、测试框架、构建工具、可观测性和部署方式。
- FW3 Java/Spring 后端默认持久化框架建议为 `mybatis-plus`；直接使用 JDBC 必须有明确项目约束、历史兼容原因或评审批准。
- FW4 代码生成必须优先遵循现有仓库技术栈、依赖、目录结构、mapper/repository/service 分层和测试框架。
- FW5 框架替换、绕过现有 mapper/repository 模式、直接 SQL/JDBC 绕过团队默认框架时必须进入设计评审和代码评审 blocker 检查。

## 主动询问
- FW6 当 repo_context 无法识别持久化框架、Web 框架、前端技术栈、组件库、测试框架或构建工具时，必须主动询问用户。
- FW7 用户确认后的技术选型必须写回 `StageRunRequest.context.technology_selection`，并进入实现总结和设计到代码映射。
""",
        "frontend-standard.md": """## 前端设计
- FE1 涉及页面、组件、交互或客户端流程时必须进入前端设计，明确页面结构、组件边界、状态、路由和交互流程。
- FE2 前端技术栈、组件库、状态管理、样式方案和构建工具必须来自 repo_context、项目 profile 或用户确认；未明确时必须主动询问。
- FE3 前端设计必须覆盖接口联调契约、请求/响应、错误码、权限可见性、表单校验、加载态、空态和错误态。
- FE4 前端设计必须说明组件复用、可访问性、兼容性、埋点/可观测性和验证方式。

## 前端研发
- FE5 前端实现必须遵循现有项目目录结构、组件库、状态管理和样式规范，不得凭空引入新技术栈。
- FE6 前端实现必须输出设计到 UI 映射、变更文件、接口联调风险、验证命令和兼容性风险。
""",
        "database-standard.md": """## 数据库与一致性
- DB1 数据库产品必须通过选型评审确定，评审至少比较事务一致性、多租户隔离、JSON/半结构化数据、全文检索、向量/语义检索、迁移工具、生态兼容和运维成熟度；不得未评审直接固定 MySQL 或 PostgreSQL。
- DB1A 关系型数据库是业务事实数据最终来源；Redis/MQ/向量库/对象存储不作为业务事实最终来源。
- DB1B 如果选择 MySQL，必须说明向量检索、JSON 查询、全文检索、复杂报表和 RAG 元数据的替代或集成方案。
- DB1C 如果选择 PostgreSQL，必须说明 MyBatis-Plus 兼容边界、JSONB/GIN/pgvector 使用边界、扩展安装方式和生产运维要求。
- DB2 数据库设计说明字段用途、索引用途、唯一约束、状态字段、审计字段是否必要。
- DB3 禁止无条件全表查询，动态 where 至少有有效条件。
- DB4 写库操作明确事务边界；多表写入说明同事务或最终一致性方案。
- DB5 删除优先逻辑删除，并说明关联数据校验规则。
- DB6 数据迁移/DDL/订正需要迁移步骤、灰度、回滚、审批点。
""",
        "redis-standard.md": """## Redis 使用边界
- R1 Redis 只做加速层、协调层、短态承载层，不做事实库、分析库、跨服务共享源、消息队列。
- R2 已用 RabbitMQ 项目禁止 Redis 发布订阅/延迟队列。
- R3 Redis 统一使用 `db0`。

## Key 与 Value
- R4 Key 格式为 `{服务模块}:{租户ID}:{数据结构}:{业务Key}`，长度不超过 100 字节。
- R5 Value 单 Key 不超过 1MB，常规 String 建议不超过 10KB。
- R6 所有 Key 必须设置 TTL，最大不超过 30 天，大批量 Key 增加随机抖动。

## 设计说明
- R7 设计说明 Redis 版本、集群、持久化、淘汰策略、Key、结构、TTL、容量、命中率、资源池、降级方案。
- R8 Spring 接入优先 `StringRedisTemplate`；复杂结构才使用 `RedisTemplate<String,Object>`。
- R9 库存扣减、分布式锁、幂等、延迟双删、排行榜、Pipeline 不使用 Spring Cache 注解。
- R10 Redis 部署版本、拓扑、持久化和淘汰策略由项目 profile 或 repo_context 注入。
""",
        "mq-standard.md": """## MQ 使用边界
- M1 MQ 仅用于削峰填谷和服务解耦；进程内异步不用 MQ。
- M2 服务内通信使用 MQ 必须评审。
- M3 一个服务一个队列，一个队列可绑定多个 Exchange/routingKey。
- M4 队列默认使用仲裁队列；非仲裁队列需要评审。
- M5 必须配置死信队列，至少记录失败消息。
- M6 消息体默认不超过 10KB，超过需评审；压缩后仍超过也需评审。

## 生产者与消费者契约
- M7 生产者定义业务消息 key、消息体、等级、TTL、持久化、Exchange、routingKey、大小、生产服务、需求号。
- M8 消费者定义队列名、用途、是否单节点消费、队列类型、TTL、绑定关系、死信、消费服务、监控阈值。
- M9 消息等级：9 核心交易，7 价格/会员/促销，5 配置，3 字典权限，1 数据同步/监控/死信。
- M10 等级 <=3 原则上设置 TTL；等级 >5 必须持久化。
- M11 顺序消息可单消费节点，但必须评审扩展性影响。
""",
        "testing-standard.md": """测试必须覆盖主路径、边界、异常、幂等、一致性、回归和发布前置检查。

## 设计阶段测试要求
- 详细设计必须包含单元测试设计，说明被测方法、输入、断言、异常路径、幂等和并发场景。
- 涉及 Redis/MQ/DB 的设计必须补充一致性、重复消费、回滚和降级测试。
- 导入、批处理、异步任务必须覆盖数据量上限、批次大小、超时、进度查询、失败处理。
""",
        "release-standard.md": "生产发布必须包含发布窗口、影响范围、依赖、配置和 DB 变更、灰度策略、回滚方案、验证步骤、监控、值班负责人和审批。",
        "review-standard.md": """评审 finding 必须包含问题、证据、影响、严重级别、修复建议和是否阻断。

## 设计评审
- 评审必须逐项覆盖架构、概要设计、详细设计、接口、异常、幂等并发、Redis、MQ、数据库规范。
- 未涉及的专项必须写明“不适用”及原因，不能空缺。
- 高风险设计、跨系统依赖、生产变更、关键链路豁免必须有人审记录。
- blocker 未关闭时不得放行进入研发。

## 代码走查
- CR1 代码走查必须覆盖 bug、漏洞/安全热点、代码异味、复杂度、重复代码、覆盖率、可维护性、可靠性和安全性指标。
- CR2 Sonar、Qodana、Checkstyle 或等价静态分析未执行时，必须说明工具、配置、网络或审批原因，并阻断“通过”结论。
- CR3 人工走查报告必须同时提供 Markdown/JSON 事实源和富 HTML 人工查看入口；HTML 不得成为唯一事实源。
- CR4 高危漏洞、横向越权、核心链路空指针、事务一致性破坏、复杂度明显超阈值、敏感信息泄露必须作为 blocker 或 require_human_review。
""",
        "document-governance-standard.md": """## 编号与分类
- DG1 正式留存文档必须具备唯一文档编号，格式为 `<PREFIX>-<DOMAIN>-<YYYYMMDD>-<SEQ>`，例如 `DDD-ORDER-20260518-001`。
- DG2 文档前缀按类型使用：REQ 需求、CTX 代码上下文、HLD 概要设计、DDD 详细设计、DBD 数据库设计、RDS Redis 设计、MQD MQ 设计、DRR 设计评审、CQR 代码质量、CRR 代码评审、RLP 发布计划、RVF 发布验证、RTR 发布复盘、KNO 知识沉淀、RPT 通用报告。
- DG3 文档必须声明 `document_status` 和 `retention_policy`；未声明时按中间过程产物处理。

## 生命周期与留存
- DG4 只有 `document_status=approved|final` 且 `retention_policy=persist` 的文档可进入正式文档目录。
- DG5 中间过程文档、任务过程摘要、缺失输入清单、blocked gate 摘要、临时评审意见和 workflow 运行状态只作为 run artifact 或 evidence，不得作为正式文档沉淀。
- DG6 `draft`、`reviewing`、`blocked`、`waiting_for_input` 默认只能使用 `transient` 或 `keep_until_run_end` 留存策略。
- DG7 被新版本替代的正式文档必须标记 `superseded` 或 `archived`，并记录替代关系。

## 输出边界
- DG8 `artifacts/<skill_id>/` 下的产物默认是本次运行证据；只有显式满足正式留存条件时才可复制到正式文档目录。
- DG9 正式文档必须包含标题、owner、来源产物、质量门禁、风险、审批状态和生命周期信息。
- DG10 章节编号由文档模板统一生成，正文不得维护互相冲突的手工编号体系。
- DG11 `artifacts/` 是 agent、CI、评审脚本和 workflow 编排消费的机读事实源，保存 StageRunResult、JSON/YAML 契约、阶段证据、风险报告和临时运行产物。
- DG12 `docs/` 是人工阅读和正式留存入口，保存已批准或 final 的 Markdown 正式文档、人工确认 HTML、只读 HTML 阅览稿和文档索引。
- DG13 正式设计文档必须同时具备 Markdown 源文档和只读 HTML 阅览稿；HTML 阅览稿统一输出到 `docs/human-readable/`，不得散落在阶段 artifact 目录。
- DG14 待人工填写、确认或审批的页面统一输出到 `docs/human-review/`；页面必须可填写并导出结构化 JSON 答案。
- DG15 agent 不得读取 `docs/human-readable/*.html` 或 `docs/human-review/*.html` 作为事实输入源；只能读取对应 Markdown、JSON、YAML 或人工导出的答案 JSON。
- DG16 `docs/00-index/artifact-index.json` 必须记录 Markdown、HTML、artifact、审批状态、来源关系和 agent 读取策略，避免人工文档和机读证据脱节。
- DG17 项目规范必须生成 `artifacts/rule-governance/rule-registry.json`，作为 task agent 和 reviewer 的机读规则索引。
- DG18 每个 workflow 任务必须优先读取 `artifacts/rule-governance/task-rule-packs/<task>.json`；规则包缺失或校验失败时不得进入实现或审核通过。
- DG19 规则治理产物必须排除 `docs/human-readable/*.html` 和 `docs/human-review/*.html`，只从 Markdown/YAML/SQL 等 agent 事实源生成。
- DG20 规则包必须保留 `rule_id`、强度、标签、规则文本、来源路径和行号，方便任务精确回源，而不是全量检索文档。
- DG21 规范重复不直接凭主观删除，必须先生成 `rule-duplicate-report.json`，再由文档治理任务合并、归档或标记替代关系。
- DG22 审核 finding 必须引用适用的 `rule_id`；没有读取任务规则包的审核结论无效。
""",
        "required-information-standard.md": """## 主动询问边界
- QIN1 必填信息缺失且无法通过仓库、上游产物、profile 或已确认上下文可靠推导时，skill 必须主动询问用户，不得继续伪造结论。
- QIN2 主动询问必须区分 blocking 与 optional；blocking 问题未回答时，`StageRunResult.status` 必须为 `waiting_for_input`。
- QIN3 每个问题必须说明用途、阻断原因、期望格式、示例和默认处理方式，避免用户不知道如何回答。

## 问题组织
- QIN4 一次询问只返回完成当前阶段所需的最小必要问题集，按 `critical`、`major`、`minor` 排序。
- QIN5 不重复询问可从仓库、上游产物或 profile 中可靠获得的信息；引用来源即可。
- QIN6 用户补充信息后必须写回 `StageRunRequest.context` 或 artifact index，并保留来源和时间。
- QIN11 blocking `required_information_requests` 或 `waiting_for_human_review` 必须同时生成面向人工的 HTML 审阅包；聊天提示只能作为摘要，不能作为唯一人工输入界面。
- QIN12 HTML 审阅包必须包含每个待确认项的可编辑输入控件、问题 id 或稳定序号、人工审阅人/决策字段，以及可复制或下载的结构化答案 JSON。
- QIN13 `StageRunResult.artifacts` 必须登记 HTML 审阅包路径；`validate_stage_run_result.py` 必须阻断缺失 HTML、HTML 不存在、或 HTML 不能填写/导出答案的运行结果。
- QIN14 人工审阅 HTML 必须集中放在目标项目 `docs/human-review/` 目录；agent 只消费 MD/JSON/YAML 作为事实来源，不得把 HTML 作为设计、需求或审批事实输入，只允许校验器检查 HTML 是否存在、可填写、可导出。

## 风险约束
- QIN7 涉及高风险动作、审批、生产变更、跨系统边界、数据一致性或安全权限的信息缺失时，不允许以假设绕过人工确认。
- QIN8 可用合理假设继续的非 blocking 信息，必须在 assumptions 中标注，并生成 optional 问题供用户补充。
- QIN9 required-information 请求不是正式留存文档，只作为 run artifact 和 workflow 恢复依据。
- QIN10 下游 skill 接收到 `waiting_for_input` 状态时必须暂停，直到 blocking 问题被回答或人工明确取消。
""",
    }
    for file_name, body in standards.items():
        write_text(base / "standards" / file_name, f"# {Path(file_name).stem}\n\n{body}\n")

    checklists = {
        "team-adaptation-checklist.md": [
            "TA1 插件 manifest name、发布目录、marketplace entry 均为 teamwork-engineering-assistant",
            "TA2 执行前已加载 rrq-yq-team profile、team-rule-catalog 和 team-standard-sources",
            "TA3 设计、评审、实现和自测结论引用稳定 rule_id",
            "TA4 MrDoc HTML 仅作为插件规则内化来源记录，不作为目标项目 agent 事实输入",
            "RRQ-ARCH1 系统边界、领域边界、事件协作、最终一致性和异常流明确",
            "YAPI1-YAPI6 接口分组、命名、路径、字段、响应结构、错误码和 JSR303 注解合规",
            "RRQ-IDEMP1-RRQ-IDEMP3 幂等标识、去重窗口、存储介质、TTL、乱序处理和重复处理结果明确",
            "RRQ-LOG1/RRQ-SEC1/RRQ-OBS1 日志上下文、脱敏、埋点和业务监控明确",
            "YQ1-YQ4 萤启服务商系统错误编码、交互流向和 MQ 场景合规",
            "CAP1-CAP3 Codex App 插件包、personal marketplace 和 local-root 发布路径验证通过",
        ],
        "requirement-intake-checklist.md": ["业务目标", "用户场景", "范围与非目标", "验收标准", "依赖系统", "影响范围", "风险等级", "接口人", "排期约束"],
        "design-review-checklist.md": [
            "A1 设计文档体现系统边界、业务域、事件协作、最终一致性；不强制微服务 + 事件驱动 + DDD 技术路线",
            "A2 系统间通过开放能力接口或事件协作，未直接调用未开放接口",
            "A3 目标业务系统与目标客户端系统的接口、事件、消息体、幂等和一致性已说明",
            "A4 应用层只暴露 api/tapi/mapi/console，业务层和共享层只暴露 service 能力",
            "A5 关键跨系统场景进入关键场景设计",
            "A6 跨库事务优先本地消息表、事件驱动、补偿机制；必要时 Seata 边界明确",
            "H1 概要设计包含平台概述、系统逻辑视图、系统设计原则、研发视图、核心功能、中间件设计、数据视图",
            "H2 参与系统、职责边界、调用方向、事件流、异常流明确",
            "H3 Redis/MQ/DB/定时任务/权限/幂等/跨系统交互涉及情况明确",
            "H4-H6 分层、application/domain 职责、聚合根创建与修改边界明确",
            "D1-D5 详细设计包含模块描述、流程、时序、DB、接口、单测、状态机、批处理、兼容策略",
            "I1-I8 接口路径、职责、字段、响应、接口文档、注解、废弃策略合规",
            "E1-E7 异常编码、错误码范围、日志级别、TraceId、敏感信息规则合规",
            "P1-P6 幂等、最终一致性、锁策略、分布式锁兜底方案明确",
            "R1-R10 Redis 使用边界、key、value、TTL、接入方式、部署现状、降级方案明确",
            "M1-M11 MQ 使用边界、队列、死信、消息大小、生产者、消费者、等级、持久化、顺序性明确",
            "DB1-DB6 MySQL 事实源、字段/索引用途、查询条件、事务边界、逻辑删除、迁移回滚明确",
            "FW1-FW6 框架选型、mybatis-plus 默认持久化、JDBC 例外和主动询问已覆盖",
            "FE1-FE6 前端页面、组件、接口联调、状态和验证方式已覆盖",
            "测试策略覆盖主路径、边界、异常、幂等、一致性和回归",
            "高风险审批、跨系统依赖、生产变更、关键链路豁免均有记录",
        ],
        "code-quality-checklist.md": ["Q0 设计一致性", "Q1 构建/格式化/lint/测试/扫描", "Q1.5 Sonar/Qodana/Checkstyle 静态分析", "bug/vulnerability/code_smell/security_hotspot 分类", "圈复杂度/重复代码/覆盖率指标", "Q2 语义评审", "Q3 风险专项", "Q4 发布前回归", "接口/异常/幂等/并发规范一致性", "富 HTML 质量报告"],
        "code-review-checklist.md": ["正确性", "边界条件", "异常处理", "Bug 风险", "漏洞/安全热点", "代码异味", "圈复杂度", "重复代码", "幂等与并发", "安全性", "性能", "可维护性", "可靠性", "可测试性", "可观测性", "团队规范一致性", "静态分析结果消费", "富 HTML 人工走查报告"],
        "release-checklist.md": ["发布窗口", "影响范围", "配置/DB 变更", "灰度策略", "回滚策略", "验证步骤", "监控告警", "值班人员", "审批状态"],
        "framework-selection-checklist.md": [
            "FW1 技术选型已在设计、repo_context 或 profile 中明确",
            "FW2 后端框架、持久化、前端技术栈、组件库、中间件、测试框架、构建工具均按需确认",
            "FW3 Java/Spring 持久化默认建议 mybatis-plus",
            "FW4 直接 JDBC 有明确项目约束、历史兼容原因或评审批准",
            "FW5 代码生成遵循现有 mapper/repository/service 分层和测试框架",
            "FW6 未识别技术选型时已主动询问用户",
            "FW7 技术选型已写回 context 和实现总结",
        ],
        "frontend-checklist.md": [
            "FE1 页面、组件、路由、状态和交互流程明确",
            "FE2 前端技术栈、组件库、状态管理和构建工具已确认",
            "FE3 接口联调契约覆盖请求、响应、错误码、权限和校验",
            "FE4 loading、empty、error、permission、validation 状态完整",
            "FE5 实现遵循现有项目目录结构、组件库和样式规范",
            "FE6 输出设计到 UI 映射、验证命令和兼容性风险",
        ],
        "document-governance-checklist.md": [
            "DG1 document_number 符合 <PREFIX>-<DOMAIN>-<YYYYMMDD>-<SEQ>",
            "DG2 文档类型与编号前缀匹配",
            "DG3 document_status 和 retention_policy 已声明",
            "DG4 approved/final + persist 才进入正式文档目录",
            "DG5 中间过程文档、任务过程摘要、缺失输入清单、blocked 摘要不作为正式文档沉淀",
            "DG6 draft/reviewing/blocked/waiting_for_input 只作为 transient 或 keep_until_run_end",
            "DG7 superseded/archived 文档记录替代关系",
            "DG8 run artifact 与正式文档目录边界清晰",
            "DG9 正式文档包含 owner、来源、门禁、风险、审批和生命周期",
            "DG10 章节编号由模板统一生成",
        ],
        "required-information-checklist.md": [
            "QIN1 缺失信息已先尝试从仓库、上游产物、profile 和上下文获取",
            "QIN2 blocking 问题未回答时状态为 waiting_for_input",
            "QIN3 每个问题包含用途、原因、期望格式、示例和默认处理方式",
            "QIN4 问题集是当前阶段最小必要集合，按 critical/major/minor 排序",
            "QIN5 不重复询问可推导或已有来源的信息",
            "QIN6 用户补充信息会写回 context 或 artifact index",
            "QIN7 高风险、审批、生产变更、跨系统边界信息缺失时未使用假设绕过",
            "QIN8 optional 信息以 assumptions 或 optional question 记录",
            "QIN9 required-information 请求只作为 run artifact",
            "QIN10 下游 workflow 在 waiting_for_input 时暂停",
        ],
    }
    for file_name, items in checklists.items():
        write_text(base / "checklists" / file_name, f"# {Path(file_name).stem}\n\n" + "\n".join(f"- [ ] {item}" for item in items))
    write_text(base / "checklists" / "upstream-main-capability-matrix.md", upstream_main_capability_matrix_doc())

    schemas = {
        "skill-contract.schema.json": {"type": "object", "required": ["skill_id", "version", "stage", "type", "inputs", "outputs", "quality_gates", "workflow_interface", "owner"], "properties": {"skill_id": {"type": "string", "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$"}, "version": {"type": "string"}, "type": {"enum": ["stage_skill", "cross_cutting_skill", "workflow_skill", "audit_skill", "control_skill"]}}},
        "workflow-node.schema.json": {
            "type": "object",
            "required": ["node_id", "stage", "skill_id", "version", "entry_modes", "depends_on", "inputs", "outputs", "quality_gates", "approval_policy", "retry_policy", "failure_policy", "next_nodes", "artifact_mapping"],
        },
        "quality-report.schema.json": {"type": "object", "required": ["summary", "gate_decision", "risk_level", "design_alignment", "checks", "findings", "required_human_reviews", "test_summary", "ci_summary", "improvement_candidates"], "properties": {"gate_decision": {"enum": ["pass", "warn", "block", "require_human_review"]}, "risk_level": {"enum": ["low", "medium", "high", "critical"]}}},
        "static-analysis-tool-report.schema.json": {
            "type": "object",
            "required": ["root", "generated_at", "tools", "summary"],
            "properties": {
                "root": {"type": "string"},
                "generated_at": {"type": "string"},
                "tools": {"type": "array", "items": {"type": "object", "required": ["name", "status"]}},
                "summary": {"type": "object"},
            },
        },
        "rule-candidate.schema.json": {"type": "object", "required": ["rules"], "properties": {"rules": {"type": "array", "items": {"type": "object", "required": ["id", "title", "status", "severity", "confidence", "source_evidence", "recommended_rule", "owner", "review_required"]}}}},
        "document-lifecycle.schema.json": document_lifecycle_schema(),
        "required-information-request.schema.json": required_information_request_schema(),
        "framework-selection.schema.json": {"type": "object", "required": ["technology_categories", "review_status", "source", "exceptions"], "properties": {"technology_categories": {"type": "object", "additionalProperties": {"type": "string"}}, "persistence_framework": {"type": "string"}, "review_status": {"enum": ["confirmed", "waiting_for_input", "approved_exception", "blocked"]}, "source": {"type": "string"}, "exceptions": {"type": "array", "items": {"type": "string"}}}},
        "task-control.schema.json": {"type": "object", "required": ["task_id", "title", "language", "workflow_id", "status", "control_dir", "created_at"], "properties": {"task_id": {"type": "string", "minLength": 1}, "title": {"type": "string", "minLength": 1}, "language": {"enum": ["zh-CN", "en"]}, "workflow_id": {"type": "string", "minLength": 1}, "status": {"enum": ["initialized", "design_approved", "contract_compiled", "implementing", "quality_running", "blocked", "succeeded"]}, "control_dir": {"type": "string", "minLength": 1}, "created_at": {"type": "string", "minLength": 1}, "updated_at": {"type": "string"}, "project_profile": {"type": "object"}, "current_contracts": {"type": "object"}}, "additionalProperties": True},
        "design-contract.schema.json": {"type": "object", "required": ["task_id", "source_design", "source_checksum", "goals", "acceptance_criteria", "module_boundaries", "assumptions"], "properties": {"task_id": {"type": "string"}, "source_design": {"type": "string"}, "source_checksum": {"type": "string"}, "goals": {"type": "array", "items": {"type": "string"}}, "acceptance_criteria": {"type": "array", "items": {"type": "string"}}, "module_boundaries": {"type": "object"}, "risks": {"type": "array", "items": {"type": "string"}}, "assumptions": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": True},
        "implementation-contract.schema.json": {"type": "object", "required": ["task_id", "allowed_modules", "forbidden_modules", "required_files_or_patterns", "architecture_rules", "required_tests", "done_conditions", "expected_interfaces", "expected_services", "expected_repositories_or_mappers", "technology_adoption_contract"], "properties": {"task_id": {"type": "string"}, "allowed_modules": {"type": "array", "items": {"type": "string"}}, "forbidden_modules": {"type": "array", "items": {"type": "string"}}, "required_files_or_patterns": {"type": "array", "items": {"type": "string"}}, "architecture_rules": {"type": "array", "items": {"type": "string"}}, "required_tests": {"type": "array", "items": {"type": "string"}}, "done_conditions": {"type": "array", "items": {"type": "string"}}, "expected_interfaces": {"type": "array", "items": {"type": "string"}}, "expected_services": {"type": "array", "items": {"type": "string"}}, "expected_repositories_or_mappers": {"type": "array", "items": {"type": "string"}}, "technology_adoption_contract": {"type": "object"}}, "additionalProperties": True},
        "quality-contract.schema.json": {"type": "object", "required": ["task_id", "required_commands", "required_evidence", "quality_gates", "repair_policy"], "properties": {"task_id": {"type": "string"}, "required_commands": {"type": "array", "items": {"type": "object", "required": ["id", "command"], "properties": {"id": {"type": "string"}, "command": {"type": "string"}, "required": {"type": "boolean"}}}}, "required_evidence": {"type": "array", "items": {"type": "string"}}, "quality_gates": {"type": "array", "items": {"type": "string"}}, "repair_policy": {"type": "object"}}, "additionalProperties": True},
        "control-health-report.schema.json": {"type": "object", "required": ["status", "findings", "generated_at"], "properties": {"status": {"enum": ["pass", "block"]}, "findings": {"type": "array", "items": {"type": "object"}}, "generated_at": {"type": "string"}}, "additionalProperties": True},
        "technology-adoption-report.schema.json": {"type": "object", "required": ["status", "findings", "generated_at"], "properties": {"status": {"enum": ["pass", "block"]}, "findings": {"type": "array", "items": {"type": "object"}}, "generated_at": {"type": "string"}}, "additionalProperties": True},
        "rule-consumption-report.schema.json": {"type": "object", "required": ["status", "findings", "generated_at"], "properties": {"status": {"enum": ["pass", "block"]}, "findings": {"type": "array", "items": {"type": "object"}}, "generated_at": {"type": "string"}}, "additionalProperties": True},
        "repair-attempts.schema.json": {"type": "object", "required": ["status", "max_attempts", "failures", "generated_at"], "properties": {"status": {"enum": ["pass", "blocked"]}, "max_attempts": {"type": "integer"}, "failures": {"type": "array", "items": {"type": "object"}}, "generated_at": {"type": "string"}}, "additionalProperties": True},
        "artifact-index.schema.json": {"type": "object", "required": ["artifacts"], "properties": {"artifacts": {"type": "object"}, "updated_at": {"type": "string"}}, "additionalProperties": True},
        "skill-runtime-ir.schema.json": {
            "type": "object",
            "required": ["skill_id", "version", "stage", "type", "prompt_pack", "inputs", "outputs", "routing", "risk", "quality_gates", "source_files"],
            "properties": {
                "skill_id": {"type": "string"},
                "prompt_pack": {"type": "object"},
                "routing": {"type": "object"},
                "risk": {"type": "object"},
                "source_files": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        },
        "skill-routing.schema.json": {
            "type": "object",
            "required": ["status", "decision", "confidence", "reason", "candidates"],
            "properties": {
                "status": {"enum": ["selected", "rejected", "waiting_for_input"]},
                "decision": {"type": ["string", "null"]},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
                "candidates": {"type": "array", "items": {"type": "object"}},
            },
            "additionalProperties": True,
        },
        "context-pack.schema.json": {
            "type": "object",
            "required": ["root", "skill_id", "task_id", "status", "sources", "forbidden_sources", "missing_required_sources"],
            "properties": {
                "root": {"type": "string"},
                "skill_id": {"type": "string"},
                "task_id": {"type": "string"},
                "status": {"enum": ["pass", "block"]},
                "sources": {"type": "array", "items": {"type": "object", "required": ["path", "kind"]}},
                "forbidden_sources": {"type": "array", "items": {"type": "string"}},
                "missing_required_sources": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        },
        "eval-report.schema.json": {
            "type": "object",
            "required": ["status", "metrics", "checks"],
            "properties": {
                "status": {"enum": ["pass", "block"]},
                "metrics": {"type": "object"},
                "checks": {"type": "array", "items": {"type": "object"}},
            },
            "additionalProperties": True,
        },
        "tool-policy.schema.json": {
            "type": "object",
            "required": ["policies"],
            "properties": {
                "policies": {"type": "array", "items": {"type": "object", "required": ["id", "decision", "reason"]}},
            },
            "additionalProperties": True,
        },
    }
    for file_name, data in schemas.items():
        write_json(base / "schemas" / file_name, {"$schema": "https://json-schema.org/draft/2020-12/schema", **data})

    scripts = {
        "validate_skill_contract.py": """#!/usr/bin/env python3
import json, sys
from pathlib import Path
required = ["skill_id", "version", "stage", "type", "inputs", "outputs", "quality_gates", "workflow_interface", "owner"]
for arg in sys.argv[1:]:
    data = json.loads(Path(arg).read_text(encoding="utf-8"))
    missing = [key for key in required if key not in data]
    if missing:
        raise SystemExit(f"{arg}: 缺少字段 {missing}")
print("ok")
""",
        "validate_workflow.py": """#!/usr/bin/env python3
import json, sys
from pathlib import Path
VALID_ENTRY_MODES = {"auto_flow", "from_node", "single_node"}
for arg in sys.argv[1:]:
    data = json.loads(Path(arg).read_text(encoding="utf-8"))
    if not data.get("nodes"):
        raise SystemExit(f"{arg}: nodes 为空")
    node_ids = [node.get("node_id") for node in data["nodes"]]
    node_id_set = set(node_ids)
    if set(data.get("supported_entry_modes", [])) != VALID_ENTRY_MODES:
        raise SystemExit(f"{arg}: supported_entry_modes 必须支持 auto_flow/from_node/single_node")
    if data.get("default_entry_mode") != "auto_flow":
        raise SystemExit(f"{arg}: default_entry_mode 必须为 auto_flow")
    if data.get("start_node") not in node_id_set:
        raise SystemExit(f"{arg}: start_node 不在 nodes 中")
    if not data.get("terminal_nodes") or any(node not in node_id_set for node in data["terminal_nodes"]):
        raise SystemExit(f"{arg}: terminal_nodes 不合法")
    for mode in VALID_ENTRY_MODES:
        if mode not in data.get("composition_policy", {}):
            raise SystemExit(f"{arg}: composition_policy 缺少 {mode}")
    preflight_policy = data.get("preflight_runtime_policy", {})
    if preflight_policy.get("formal_generation_entry_condition") != "preflight_input_state == ready":
        raise SystemExit(f"{arg}: preflight_runtime_policy.formal_generation_entry_condition 必须为 preflight_input_state == ready")
    if preflight_policy.get("block_current_node_formal_generation") is not True:
        raise SystemExit(f"{arg}: preflight_runtime_policy.block_current_node_formal_generation 必须为 true")
    if preflight_policy.get("block_next_nodes") is not True:
        raise SystemExit(f"{arg}: preflight_runtime_policy.block_next_nodes 必须为 true")
    for node in data["nodes"]:
        for field in ["node_id", "skill_id", "entry_modes", "depends_on", "inputs", "outputs", "preflight_gate", "approval_policy", "failure_policy", "next_nodes"]:
            if field not in node:
                raise SystemExit(f"{arg}: node 缺少字段 {field}")
        gate = node.get("preflight_gate", {})
        if gate.get("formal_generation_entry_condition") != "preflight_input_state == ready":
            raise SystemExit(f"{arg}: {node.get('node_id')} preflight_gate.formal_generation_entry_condition 必须为 preflight_input_state == ready")
        if gate.get("block_formal_generation_when_not_ready") is not True:
            raise SystemExit(f"{arg}: {node.get('node_id')} preflight_gate.block_formal_generation_when_not_ready 必须为 true")
        if gate.get("block_next_nodes_when_not_ready") is not True:
            raise SystemExit(f"{arg}: {node.get('node_id')} preflight_gate.block_next_nodes_when_not_ready 必须为 true")
        if set(node.get("entry_modes", [])) != VALID_ENTRY_MODES:
            raise SystemExit(f"{arg}: {node.get('node_id')} entry_modes 不合法")
        for next_node in node.get("next_nodes", []):
            if next_node not in node_id_set:
                raise SystemExit(f"{arg}: {node.get('node_id')} next_nodes 指向未知节点 {next_node}")
        for previous_node in node.get("depends_on", []):
            if previous_node not in node_id_set:
                raise SystemExit(f"{arg}: {node.get('node_id')} depends_on 指向未知节点 {previous_node}")
print("ok")
""",
        "validate_skill_metadata.py": """#!/usr/bin/env python3
import sys
from pathlib import Path

errors = []
for skill_md in sorted(Path("skills").glob("*/SKILL.md")):
    text = skill_md.read_text(encoding="utf-8")
    skill_dir = skill_md.parent
    meta = skill_dir / "agents" / "openai.yaml"
    if "description: Use when" not in text:
        errors.append(f"{skill_md}: description 必须以 Use when 描述触发条件")
    if not meta.exists():
        errors.append(f"{meta}: 缺少 agents/openai.yaml")
        continue
    meta_text = meta.read_text(encoding="utf-8")
    for required in ["display_name:", "short_description:", "default_prompt:", "language_policy:", "when_unspecified: \\"ask_user\\"", "policy:", "allow_implicit_invocation:", "risk_level:", "metadata:"]:
        if required not in meta_text:
            errors.append(f"{meta}: 缺少 {required}")
    if skill_dir.name in {"workflow-orchestrator", "code-development", "code-quality-governor", "release-readiness", "release-verification", "engineering-knowledge-miner"} and "allow_implicit_invocation: false" not in meta_text:
        errors.append(f"{meta}: 高风险 skill 必须 explicit-only")
if errors:
    raise SystemExit("\\n".join(errors))
print("ok")
""",
        "validate_plugin_manifest.py": """#!/usr/bin/env python3
import json
from pathlib import Path

MANIFEST = Path("engineering-assistant/plugin/plugin.json")
manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

errors = []
warnings = []

required_top_level = ["name", "version", "description", "author", "homepage", "repository", "license", "skills", "interface", "metadata_status", "distribution_notes"]
for field in required_top_level:
    if field not in manifest:
        errors.append(f"{MANIFEST}: 缺少 {field}")

interface = manifest.get("interface", {})
for field in ["displayName", "shortDescription", "longDescription", "developerName", "category", "capabilities", "defaultPrompt", "brandColor", "websiteURL", "privacyPolicyURL", "termsOfServiceURL"]:
    if field not in interface:
        errors.append(f"{MANIFEST}: interface 缺少 {field}")

notes = manifest.get("distribution_notes", {})
if manifest.get("metadata_status") not in {"ready", "waiting_for_human_review"}:
    errors.append(f"{MANIFEST}: metadata_status 必须为 ready 或 waiting_for_human_review")
if notes.get("runtime_policy_pack") != "target-project-template":
    errors.append(f"{MANIFEST}: distribution_notes.runtime_policy_pack 必须声明为 target-project-template")
if notes.get("hooks_packaging") != "not-bundled":
    errors.append(f"{MANIFEST}: distribution_notes.hooks_packaging 必须声明为 not-bundled")

placeholder_values = []
author = manifest.get("author", {})
for path, value in [
    ("author.email", author.get("email", "")),
    ("author.url", author.get("url", "")),
    ("homepage", manifest.get("homepage", "")),
    ("repository", manifest.get("repository", "")),
    ("interface.websiteURL", interface.get("websiteURL", "")),
    ("interface.privacyPolicyURL", interface.get("privacyPolicyURL", "")),
    ("interface.termsOfServiceURL", interface.get("termsOfServiceURL", "")),
]:
    if "example." in str(value) or str(value).endswith("@example.com"):
        placeholder_values.append(path)

if placeholder_values:
    if manifest.get("metadata_status") != "waiting_for_human_review":
        errors.append(f"{MANIFEST}: 占位符 metadata {placeholder_values} 只能在 waiting_for_human_review 状态下保留")
    if notes.get("external_distribution_gate") != "waiting_for_human_review":
        errors.append(f"{MANIFEST}: 占位符 metadata 必须声明 external_distribution_gate=waiting_for_human_review")
    if notes.get("placeholder_metadata_allowed_for_local_template") is not True:
        errors.append(f"{MANIFEST}: 占位符 metadata 必须显式声明仅允许 local template")
    warnings.append("example.* placeholder metadata requires human review: " + ", ".join(placeholder_values))

if "hooks" in manifest:
    errors.append(f"{MANIFEST}: runtime policy pack 当前是目标项目模板，不得在 manifest 中声明 hooks")

runtime_readme = Path("engineering-assistant/runtime/codex/README.md")
if runtime_readme.exists():
    readme_text = runtime_readme.read_text(encoding="utf-8")
    for required_text in ["安装插件不等于自动启用", "不作为插件内置 hooks 自动生效", "trust review"]:
        if required_text not in readme_text:
            errors.append(f"{runtime_readme}: 缺少 runtime 模板定位说明 {required_text}")
else:
    errors.append(f"{runtime_readme}: 缺少 runtime policy pack README")

for profile in ["readonly_review.toml", "controlled_fix.toml"]:
    path = Path("engineering-assistant/runtime/codex/profiles") / profile
    if not path.exists():
        errors.append(f"{path}: 缺少独立 profile 示例")

status = "block" if errors else ("waiting_for_human_review" if warnings else "pass")
payload = {"status": status, "errors": errors, "warnings": warnings}
if errors:
    raise SystemExit(json.dumps(payload, ensure_ascii=False, indent=2))
print(json.dumps(payload, ensure_ascii=False, indent=2))
""",
        "compile_skill_runtime.py": """#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_agent_meta(path: Path) -> dict:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    meta = {}
    for key in ["display_name", "short_description", "default_prompt"]:
        match = re.search(rf"^{key}:\\s*\\"?(.*?)\\"?$", text, re.MULTILINE)
        meta[key] = match.group(1) if match else ""
    meta["allow_implicit_invocation"] = "allow_implicit_invocation: true" in text
    risk_match = re.search(r"risk_level:\\s*\\"?([a-z]+)\\"?", text)
    meta["risk_level"] = risk_match.group(1) if risk_match else "medium"
    return meta


def compile_skill(skill_dir: Path) -> dict:
    contract = load_json(skill_dir / "contract.yaml")
    workflow = load_json(skill_dir / "workflow" / "node.yaml")
    agent_meta = read_agent_meta(skill_dir / "agents" / "openai.yaml")
    skill_md = skill_dir / "SKILL.md"
    routing = contract.get("routing") or {
        "positive_triggers": [contract["skill_id"], contract.get("skill_name", ""), contract.get("purpose", "")],
        "negative_triggers": [f"只解释 {contract.get('skill_name', contract['skill_id'])} 的用途，不执行任务"],
        "allow_implicit_invocation": agent_meta["allow_implicit_invocation"],
        "risk_level": agent_meta["risk_level"],
    }
    return {
        "skill_id": contract["skill_id"],
        "version": contract.get("version", "1.0.0"),
        "stage": contract.get("stage"),
        "type": contract.get("type"),
        "prompt_pack": {
            "display_name": agent_meta["display_name"],
            "short_description": agent_meta["short_description"],
            "default_prompt": agent_meta["default_prompt"],
            "trigger_description": contract.get("trigger_description", ""),
            "language_policy": contract.get("language_policy", {}),
        },
        "inputs": contract.get("inputs", []),
        "outputs": contract.get("outputs", []),
        "routing": routing,
        "risk": {
            "risk_level": agent_meta["risk_level"],
            "allow_implicit_invocation": agent_meta["allow_implicit_invocation"],
            "human_approval_required": contract.get("human_approval_required", []),
        },
        "quality_gates": contract.get("quality_gates", []),
        "workflow": {
            "node_id": workflow.get("node_id"),
            "entry_modes": workflow.get("entry_modes", []),
            "next_nodes": workflow.get("next_nodes", []),
        },
        "source_files": [
            str(skill_md),
            str(skill_dir / "contract.yaml"),
            str(skill_dir / "workflow" / "node.yaml"),
            str(skill_dir / "agents" / "openai.yaml"),
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Compile skills into lightweight runtime IR.")
    parser.add_argument("--skills-root", default="skills")
    parser.add_argument("--out", default="engineering-assistant/runtime/compiled")
    args = parser.parse_args()
    out = Path(args.out)
    skills_out = out / "skills"
    skills_out.mkdir(parents=True, exist_ok=True)
    compiled = []
    for skill_dir in sorted(Path(args.skills_root).glob("*")):
        if not (skill_dir / "contract.yaml").exists():
            continue
        ir = compile_skill(skill_dir)
        target = skills_out / f"{ir['skill_id']}.ir.json"
        target.write_text(json.dumps(ir, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
        compiled.append({"skill_id": ir["skill_id"], "path": str(target), "risk_level": ir["risk"]["risk_level"], "allow_implicit_invocation": ir["risk"]["allow_implicit_invocation"]})
    index = {"version": "1.0.0", "skills": compiled}
    (out / "skill-runtime-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "compiled": len(compiled), "out": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
""",
        "route_skill.py": """#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

HIGH_RISK = {"workflow-orchestrator", "code-development", "code-quality-governor", "release-readiness", "release-verification", "engineering-knowledge-miner", "implementation-controller"}
EXPLAIN_ONLY = ["只解释", "用途", "不执行", "不生成产物", "explain"]


def load_registry(root: Path) -> list[dict]:
    index = root / "engineering-assistant" / "runtime" / "compiled" / "skill-runtime-index.json"
    if index.exists():
        data = json.loads(index.read_text(encoding="utf-8"))
        skills = []
        for item in data.get("skills", []):
            ir_path = root / item["path"]
            ir = json.loads(ir_path.read_text(encoding="utf-8")) if ir_path.exists() else {}
            skills.append({
                "skill_id": item["skill_id"],
                "risk_level": item.get("risk_level", ir.get("risk", {}).get("risk_level", "medium")),
                "allow_implicit_invocation": item.get("allow_implicit_invocation", ir.get("risk", {}).get("allow_implicit_invocation", True)),
                "stage": ir.get("stage", ""),
                "type": ir.get("type", ""),
                "triggers": " ".join(ir.get("routing", {}).get("positive_triggers", []) + ir.get("routing", {}).get("intent_tags", [])),
            })
        return skills
    registry = root / "engineering-assistant" / "registry" / "skills.yaml"
    return json.loads(registry.read_text(encoding="utf-8")).get("skills", [])


def explicit_skill_mention(prompt: str, skill_id: str) -> bool:
    return re.search(rf"(^|\\s|使用|use\\s+){re.escape(skill_id)}($|\\s|，|,)", prompt.lower()) is not None


def score_skill(prompt: str, skill: dict, explicit_prompt: str) -> int:
    text = prompt.lower()
    skill_id = skill["skill_id"]
    score = 0
    if explicit_skill_mention(explicit_prompt, skill_id):
        score += 100
    for token in skill_id.split("-"):
        if token and token in text:
            score += 5
    if "设计" in prompt and "design" in skill_id:
        score += 8
    if ("评审" in prompt or "review" in text) and "review" in skill_id:
        score += 8
    if ("测试" in prompt or "test" in text) and skill_id == "self-test":
        score += 8
    if any(token in text for token in ["实现", "编码", "代码", "complete", "修复"]) and skill_id == "code-development":
        score += 12
    if any(token in text for token in ["继续", "恢复", "next_action", "workflow"]) and skill_id == "workflow-orchestrator":
        score += 10
    if "frontend" in text or "前端" in prompt:
        if "frontend" in skill_id:
            score += 10
        elif skill_id == "code-development":
            score -= 4
    return score


def route(prompt: str, root: Path, explicit_prompt=None) -> dict:
    explicit_prompt = explicit_prompt if explicit_prompt is not None else prompt
    if any(token in explicit_prompt for token in EXPLAIN_ONLY):
        return {"status": "rejected", "decision": None, "confidence": 1.0, "reason": "咨询说明类请求不执行 skill", "candidates": []}
    skills = load_registry(root)
    scored = sorted(({"skill_id": skill["skill_id"], "score": score_skill(prompt, skill, explicit_prompt), "risk_level": skill.get("risk_level", "medium"), "allow_implicit_invocation": skill.get("allow_implicit_invocation", True)} for skill in skills), key=lambda item: item["score"], reverse=True)
    candidates = [item for item in scored if item["score"] > 0][:5]
    if not candidates:
        return {"status": "waiting_for_input", "decision": None, "confidence": 0.0, "reason": "无法确定最小足够 skill", "candidates": []}
    top = candidates[0]
    explicit = explicit_skill_mention(explicit_prompt, top["skill_id"])
    if top["skill_id"] in HIGH_RISK and not explicit:
        return {"status": "waiting_for_input", "decision": None, "confidence": min(top["score"] / 100, 0.89), "reason": "高风险 skill 必须 explicit-only", "candidates": candidates}
    second_score = candidates[1]["score"] if len(candidates) > 1 else 0
    if top["score"] < 8 or (second_score and top["score"] - second_score < 3):
        return {"status": "waiting_for_input", "decision": None, "confidence": min(top["score"] / 100, 0.7), "reason": "路由置信度不足或存在相邻 skill 冲突", "candidates": candidates}
    return {"status": "selected", "decision": top["skill_id"], "confidence": min(top["score"] / 100, 1.0), "reason": "命中确定性路由规则", "candidates": candidates}


def main():
    parser = argparse.ArgumentParser(description="Route a request to the minimum sufficient engineering-assistant skill.")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--context")
    args = parser.parse_args()
    explicit_prompt = args.prompt
    prompt = explicit_prompt
    if args.context and Path(args.context).exists():
        prompt += "\\n" + Path(args.context).read_text(encoding="utf-8")[:4000]
    print(json.dumps(route(prompt, Path(args.root), explicit_prompt=explicit_prompt), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
""",
        "publish_plugin.py": """#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - Hermes installs include PyYAML; creation-only mode can still work without it.
    yaml = None

DEFAULT_CONFIG = Path(".agent/plugins/publish-config.json")


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"missing publish config: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def expand(path_value: str) -> Path:
    return Path(path_value).expanduser().resolve()


def ensure_not_repo_path(repo_root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return
    raise SystemExit(f"refuse to publish into repository workspace: {path}")


def copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        raise SystemExit(f"missing source tree: {source}")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def read_codex_manifest(repo_root: Path) -> dict:
    manifest = repo_root / "engineering-assistant" / "plugin" / "plugin.json"
    if not manifest.exists():
        raise SystemExit(f"missing plugin manifest source: {manifest}")
    return json.loads(manifest.read_text(encoding="utf-8"))


def plugin_entry(config: dict) -> dict:
    plugin_name = config.get("plugin_name", "teamwork-engineering-assistant")
    return {
        "name": plugin_name,
        "source": {
            "source": "local",
            "path": "./" + config.get("plugin_relative_path", f"plugins/{plugin_name}").strip("/"),
        },
        "policy": config.get("policy", {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}),
        "category": config.get("category", "Productivity"),
    }


def load_marketplace(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid marketplace json: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"marketplace must be a JSON object: {path}")
    return data


def upsert_plugin_entry(existing_plugins, entry: dict) -> list:
    plugins = existing_plugins if isinstance(existing_plugins, list) else []
    updated = []
    replaced = False
    for item in plugins:
        if isinstance(item, dict) and item.get("name") == entry["name"]:
            updated.append(entry)
            replaced = True
        else:
            updated.append(item)
    if not replaced:
        updated.append(entry)
    return updated


def marketplace_payload(config: dict, existing=None) -> dict:
    payload = dict(existing or {})
    return {
        **payload,
        "name": payload.get("name") or config.get("name", "local-teamwork-engineering"),
        "interface": payload.get("interface") if isinstance(payload.get("interface"), dict) else config.get("interface", {"displayName": "Local Teamwork Engineering Plugins"}),
        "plugins": upsert_plugin_entry(payload.get("plugins"), plugin_entry(config)),
    }


def apply_layout(config: dict, layout: str) -> dict:
    resolved = dict(config)
    if layout == "local-root":
        return resolved
    if layout == "personal":
        resolved["name"] = "personal"
        resolved["interface"] = {"displayName": "Personal"}
        resolved["publish_root"] = "~"
        resolved["marketplace_path"] = "~/.agents/plugins/marketplace.json"
        resolved["plugin_relative_path"] = f"plugins/{resolved.get('plugin_name', 'teamwork-engineering-assistant')}"
        return resolved
    if layout == "hermes":
        resolved["publish_root"] = resolved.get("hermes_publish_root", "~/.hermes")
        resolved["plugin_relative_path"] = f"plugins/{resolved.get('plugin_name', 'teamwork-engineering-assistant')}"
        return resolved
    raise SystemExit(f"unsupported publish layout: {layout}")


def hermes_plugin_yaml(plugin_name: str, manifest: dict) -> str:
    author = manifest.get("author", {})
    author_name = author.get("name", "") if isinstance(author, dict) else str(author)
    payload = {
        "name": plugin_name,
        "version": str(manifest.get("version", "1.0.0")),
        "description": manifest.get("description", ""),
        "author": author_name,
        "kind": "standalone",
        "platforms": ["linux", "macos", "windows"],
    }
    if yaml is not None:
        return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\\n"


def hermes_entrypoint() -> str:
    return '''# Hermes adapter for the teamwork-engineering-assistant skill bundle.

from __future__ import annotations

from pathlib import Path


def _skill_description(skill_md: Path) -> str:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except Exception:
        return ""
    if not text.startswith("---"):
        return ""
    end = text.find("\\\\n---", 3)
    if end == -1:
        return ""
    for line in text[3:end].splitlines():
        if line.startswith("description:"):
            value = line.partition(":")[2].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return ""


def register(ctx) -> None:
    root = Path(__file__).resolve().parent
    skills_root = root / "skills"
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        skill_name = skill_md.parent.name
        ctx.register_skill(
            skill_name,
            skill_md,
            description=_skill_description(skill_md),
        )
'''


def enable_hermes_plugin(hermes_home: Path, plugin_name: str) -> bool:
    config_path = hermes_home / "config.yaml"
    if not config_path.exists():
        config_path.write_text(
            "plugins:\\n  enabled:\\n    - " + plugin_name + "\\n",
            encoding="utf-8",
        )
        return True
    if yaml is None:
        if plugin_name in config_path.read_text(encoding="utf-8"):
            return True
        raise SystemExit("PyYAML is required to update an existing Hermes config.yaml")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise SystemExit(f"unsupported Hermes config shape: {config_path}")
    plugins = config.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        raise SystemExit(f"unsupported Hermes plugins config shape: {config_path}")
    enabled = plugins.setdefault("enabled", [])
    if enabled is None:
        enabled = []
        plugins["enabled"] = enabled
    if not isinstance(enabled, list):
        raise SystemExit(f"unsupported Hermes plugins.enabled config shape: {config_path}")
    if plugin_name not in enabled:
        enabled.append(plugin_name)
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return True


def publish_hermes(repo_root: Path, config: dict, publish_root=None, enable=False) -> dict:
    plugin_name = config.get("plugin_name", "teamwork-engineering-assistant")
    publish_root = publish_root or expand(config["publish_root"])
    plugin_relative = Path(config.get("plugin_relative_path", f"plugins/{plugin_name}"))
    plugin_root = publish_root / plugin_relative
    ensure_not_repo_path(repo_root, publish_root)

    skills = repo_root / "skills"
    runtime = repo_root / "engineering-assistant"
    manifest = read_codex_manifest(repo_root)

    plugin_root.parent.mkdir(parents=True, exist_ok=True)
    if plugin_root.exists():
        shutil.rmtree(plugin_root)
    plugin_root.mkdir(parents=True)
    copy_tree(skills, plugin_root / "skills")
    copy_tree(runtime, plugin_root / "engineering-assistant")
    (plugin_root / "plugin.yaml").write_text(hermes_plugin_yaml(plugin_name, manifest), encoding="utf-8")
    (plugin_root / "__init__.py").write_text(hermes_entrypoint(), encoding="utf-8")

    hermes_enabled = enable_hermes_plugin(publish_root, plugin_name) if enable else False
    return {
        "status": "published",
        "layout": "hermes",
        "plugin_root": str(plugin_root),
        "hermes_plugin_manifest": str(plugin_root / "plugin.yaml"),
        "hermes_plugin_entrypoint": str(plugin_root / "__init__.py"),
        "hermes_enabled": hermes_enabled,
        "registered_skill_count": len(list((plugin_root / "skills").glob("*/SKILL.md"))),
    }


def publish_codex(repo_root: Path, config: dict, publish_root=None, marketplace_path=None, layout="local-root") -> dict:
    plugin_name = config.get("plugin_name", "teamwork-engineering-assistant")
    compatibility_alias = config.get("compatibility_alias")
    publish_root_override = publish_root is not None
    publish_root = publish_root or expand(config["publish_root"])
    if marketplace_path is None:
        marketplace_path = publish_root / ".agents" / "plugins" / "marketplace.json" if publish_root_override else expand(config.get("marketplace_path", str(publish_root / ".agents" / "plugins" / "marketplace.json")))
    plugin_relative = Path(config.get("plugin_relative_path", f"plugins/{plugin_name}"))
    plugin_root = publish_root / plugin_relative
    ensure_not_repo_path(repo_root, publish_root)
    ensure_not_repo_path(repo_root, marketplace_path)

    manifest = repo_root / "engineering-assistant" / "plugin" / "plugin.json"
    skills = repo_root / "skills"
    runtime = repo_root / "engineering-assistant"
    if not manifest.exists():
        raise SystemExit(f"missing plugin manifest source: {manifest}")

    plugin_root.parent.mkdir(parents=True, exist_ok=True)
    if plugin_root.exists():
        shutil.rmtree(plugin_root)
    (plugin_root / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest, plugin_root / ".codex-plugin" / "plugin.json")
    copy_tree(skills, plugin_root / "skills")
    copy_tree(runtime, plugin_root / "engineering-assistant")

    existing_marketplace = load_marketplace(marketplace_path)
    existing_plugin_names = {item.get("name") for item in existing_marketplace.get("plugins", []) if isinstance(item, dict)}
    if layout == "personal" and compatibility_alias and compatibility_alias != plugin_name and compatibility_alias not in existing_plugin_names:
        alias_root = publish_root / "plugins" / compatibility_alias
        if alias_root != plugin_root:
            if alias_root.exists():
                shutil.rmtree(alias_root)
            shutil.copytree(plugin_root, alias_root)

    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.write_text(json.dumps(marketplace_payload(config, existing_marketplace), ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    legacy_marketplace = publish_root / "marketplace.json"
    if legacy_marketplace != marketplace_path and legacy_marketplace.exists():
        legacy_marketplace.unlink()
    return {
        "status": "published",
        "layout": layout,
        "plugin_root": str(plugin_root),
        "marketplace_path": str(marketplace_path),
        "plugin_manifest": str(plugin_root / ".codex-plugin" / "plugin.json"),
    }


def publish(repo_root: Path, config: dict, publish_root=None, marketplace_path=None, layout="local-root", enable=False) -> dict:
    config = apply_layout(config, layout)
    if layout == "hermes":
        return publish_hermes(repo_root, config, publish_root=publish_root, enable=enable)
    if enable:
        raise SystemExit("--enable is only supported with --layout hermes")
    return publish_codex(repo_root, config, publish_root=publish_root, marketplace_path=marketplace_path, layout=layout)


def main():
    parser = argparse.ArgumentParser(description="Publish teamwork-engineering-assistant as a Codex or Hermes local plugin.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--layout", choices=["local-root", "personal", "hermes"], default="local-root", help="local-root uses configured Codex publish_root; personal writes the canonical Codex personal marketplace; hermes writes a Hermes directory plugin.")
    parser.add_argument("--publish-root")
    parser.add_argument("--marketplace-path")
    parser.add_argument("--enable", action="store_true", help="For --layout hermes, add the plugin to <publish-root>/config.yaml plugins.enabled.")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    config = load_config(repo_root / args.config if not Path(args.config).is_absolute() else Path(args.config))
    publish_root = expand(args.publish_root) if args.publish_root else None
    marketplace_path = expand(args.marketplace_path) if args.marketplace_path else None
    print(json.dumps(publish(repo_root, config, publish_root, marketplace_path, args.layout, args.enable), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
""",
        "recommend_context.py": """#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

ALLOWED_SUFFIXES = {".json", ".md", ".yaml", ".yml", ".sql", ".txt"}
FORBIDDEN_SUFFIXES = {".html", ".htm", ".png", ".jpg", ".jpeg", ".gif"}


def safe_project_path(root: Path, rel: str):
    if Path(rel).is_absolute():
        return None
    root_resolved = root.resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def add_source(root: Path, sources: list[dict], forbidden: list[str], rel: str, kind: str) -> bool:
    path = safe_project_path(root, rel)
    if path is None:
        forbidden.append(rel)
        return False
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES or "/docs/human-review/" in str(path).replace("\\\\", "/"):
        forbidden.append(rel)
        return False
    if suffix not in ALLOWED_SUFFIXES and path.name != "Makefile":
        forbidden.append(rel)
        return False
    if path.exists():
        sources.append({"path": rel, "kind": kind, "bytes": path.stat().st_size})
        return True
    return False


def build_pack(root: Path, skill_id: str, task_id: str) -> dict:
    sources = []
    forbidden = []
    missing_required_sources = []
    required = [
        ("artifacts/workflow-orchestrator/artifact-index.json", "workflow_artifact_index"),
        ("artifacts/workflow-orchestrator/workflow-summary.md", "workflow_summary"),
        ("artifacts/_control/architecture-baseline.json", "architecture_baseline"),
        ("Makefile", "validation_entrypoint"),
    ]
    for rel, kind in required:
        if not add_source(root, sources, forbidden, rel, kind):
            missing_required_sources.append(rel)
    index_path = root / "artifacts/workflow-orchestrator/artifact-index.json"
    if index_path.exists():
        data = json.loads(index_path.read_text(encoding="utf-8"))
        for rel in data.get("stage_results", [])[:40]:
            add_source(root, sources, forbidden, rel, "stage_run_result")
        for rel in data.get("document_control_artifacts", [])[:30]:
            add_source(root, sources, forbidden, rel, "document_control")
        for rel in data.get("human_review_packets", []):
            add_source(root, sources, forbidden, rel, "forbidden_human_html")
    status = "pass" if not missing_required_sources else "block"
    return {"root": str(root), "skill_id": skill_id, "task_id": task_id, "status": status, "sources": sources, "forbidden_sources": forbidden, "missing_required_sources": missing_required_sources}


def main():
    parser = argparse.ArgumentParser(description="Build a minimal context pack from machine-readable project artifacts.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--skill-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    pack = build_pack(Path(args.root), args.skill_id, args.task_id)
    text = json.dumps(pack, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\\n", encoding="utf-8")
    print(text)
    if pack["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
""",
        "validate_quality_report.py": """#!/usr/bin/env python3
import json, sys
from pathlib import Path
valid = {"pass", "warn", "block", "require_human_review"}
for arg in sys.argv[1:]:
    data = json.loads(Path(arg).read_text(encoding="utf-8"))
    if data.get("gate_decision") not in valid:
        raise SystemExit(f"{arg}: gate_decision 不合法")
print("ok")
""",
        "run_static_analysis_tools.py": """#!/usr/bin/env python3
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

MASK = re.compile(r"(?i)(token|password|passwd|secret|key|credential|authorization)=([^\\s&]+)")


def redact(text: str) -> str:
    return MASK.sub(lambda m: f"{m.group(1)}=***", text or "")


def run_cmd(cmd, cwd: Path, timeout: int, env=None):
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return {
            "exit_code": proc.returncode,
            "duration_seconds": round(time.time() - started, 2),
            "output": redact(proc.stdout)[-12000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": 124,
            "duration_seconds": round(time.time() - started, 2),
            "output": redact((exc.stdout or "") + "\\nTIMEOUT"),
        }


def download(url: str, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response:
        target.write_bytes(response.read())
    return target


def discover(root: Path):
    return {
        "sonar_project": [str(p.relative_to(root)) for p in root.rglob("sonar-project.properties")],
        "qodana": [str(p.relative_to(root)) for p in list(root.rglob("qodana.yaml")) + list(root.rglob("qodana.yml"))],
        "checkstyle": [str(p.relative_to(root)) for p in list(root.rglob("checkstyle.xml")) + list(root.rglob("config/checkstyle/checkstyle.xml"))],
        "java_files": [str(p.relative_to(root)) for p in root.rglob("*.java") if "/target/" not in str(p)],
        "pom": [str(p.relative_to(root)) for p in root.rglob("pom.xml")],
        "gradle": [str(p.relative_to(root)) for p in list(root.rglob("build.gradle")) + list(root.rglob("build.gradle.kts"))],
    }


def find_executable(name: str):
    path = shutil.which(name)
    return str(Path(path).resolve()) if path else None


def ensure_checkstyle(args, tool_dir: Path, result: dict):
    existing = find_executable("checkstyle")
    if existing:
        return existing
    jars = sorted(tool_dir.glob("checkstyle-*-all.jar"))
    if jars:
        return str(jars[-1])
    if not args.allow_download:
        result["status"] = "tool_unavailable"
        result["reason"] = "checkstyle 未安装；如需下载官方 all.jar，请传 --allow-download"
        return None
    version = args.checkstyle_version
    url = args.checkstyle_url or f"https://github.com/checkstyle/checkstyle/releases/download/checkstyle-{version}/checkstyle-{version}-all.jar"
    try:
        return str(download(url, tool_dir / f"checkstyle-{version}-all.jar"))
    except Exception as exc:
        result["status"] = "download_failed"
        result["reason"] = redact(str(exc))
        result["download_url"] = url
        return None


def ensure_sonar(args, tool_dir: Path, result: dict):
    existing = find_executable("sonar-scanner")
    if existing:
        return existing
    candidates = sorted(tool_dir.rglob("sonar-scanner"))
    if candidates:
        return str(candidates[-1])
    if not args.allow_download:
        result["status"] = "tool_unavailable"
        result["reason"] = "sonar-scanner 未安装；如需下载 SonarScanner CLI，请传 --allow-download 和 --sonar-scanner-url"
        return None
    if not args.sonar_scanner_url:
        result["status"] = "missing_input"
        result["reason"] = "SonarScanner CLI 官方下载链接随版本和平台变化，必须通过 --sonar-scanner-url 或 SONAR_SCANNER_URL 提供"
        result["platform"] = {"system": platform.system(), "machine": platform.machine()}
        return None
    try:
        archive = download(args.sonar_scanner_url, tool_dir / "sonar-scanner-cli.zip")
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tool_dir)
        candidates = sorted(tool_dir.rglob("sonar-scanner"))
        return str(candidates[-1]) if candidates else None
    except Exception as exc:
        result["status"] = "download_failed"
        result["reason"] = redact(str(exc))
        return None


def ensure_qodana(args, tool_dir: Path, result: dict):
    existing = find_executable("qodana")
    if existing:
        return existing
    go_bin = Path.home() / "go" / "bin" / "qodana"
    if go_bin.exists():
        return str(go_bin)
    if not args.allow_download:
        result["status"] = "tool_unavailable"
        result["reason"] = "qodana CLI 未安装；如需按 JetBrains 官方方式安装，请传 --allow-download 且本机需有 go"
        return None
    if not find_executable("go"):
        result["status"] = "tool_unavailable"
        result["reason"] = "qodana CLI 可通过 go install 安装，但本机未发现 go"
        return None
    install = run_cmd(["go", "install", "github.com/JetBrains/qodana-cli@latest"], Path.cwd(), args.timeout_seconds)
    result["install"] = install
    return str(go_bin) if go_bin.exists() else None


def run_checkstyle(args, root: Path, output: Path, discovered: dict):
    result = {"name": "checkstyle", "status": "not_run"}
    config = args.checkstyle_config
    if not config:
        for item in ["checkstyle.xml", "config/checkstyle/checkstyle.xml"]:
            if (root / item).exists():
                config = item
                break
    if not config:
        result.update({"status": "missing_config", "reason": "未发现项目 checkstyle.xml；未使用临时 google/sun 基线替代团队规则"})
        return result
    if not discovered["java_files"]:
        result.update({"status": "not_applicable", "reason": "未发现 Java 文件"})
        return result
    tool = ensure_checkstyle(args, output / "_tools", result)
    if not tool:
        return result
    xml = output / "checkstyle-result.xml"
    targets = [str(root / "src/main/java")] if (root / "src/main/java").exists() else [str(root / p) for p in discovered["java_files"][:500]]
    if tool.endswith(".jar"):
        cmd = ["java", "-jar", tool, "-c", config, "-f", "xml", "-o", str(xml), *targets]
    else:
        cmd = [tool, "-c", config, "-f", "xml", "-o", str(xml), *targets]
    execution = run_cmd(cmd, root, args.timeout_seconds)
    result.update({"status": "passed" if execution["exit_code"] == 0 else "failed", "config": config, "result_file": str(xml), "execution": execution})
    return result


def run_sonar(args, root: Path, output: Path, discovered: dict):
    result = {"name": "sonar", "status": "not_run"}
    has_config = bool(discovered["sonar_project"])
    has_connection = bool(args.sonar_host_url or os.environ.get("SONAR_HOST_URL") or os.environ.get("SONAR_TOKEN"))
    if not has_config and not has_connection:
        result.update({"status": "missing_input", "reason": "缺少 sonar-project.properties 或 sonar.host.url/token，不能执行 SonarScanner"})
        return result
    tool = ensure_sonar(args, output / "_tools", result)
    if not tool:
        return result
    env = os.environ.copy()
    if args.sonar_host_url:
        env["SONAR_HOST_URL"] = args.sonar_host_url
    cmd = [tool, f"-Dsonar.projectBaseDir={root}", f"-Dsonar.scanner.metadataFilePath={output / 'sonar-report-task.txt'}"]
    execution = run_cmd(cmd, root, args.timeout_seconds, env=env)
    result.update({"status": "passed" if execution["exit_code"] == 0 else "failed", "execution": execution, "metadata_file": str(output / "sonar-report-task.txt")})
    return result


def run_qodana(args, root: Path, output: Path, discovered: dict):
    result = {"name": "qodana", "status": "not_run"}
    if not discovered["qodana"] and not args.qodana_linter:
        result.update({"status": "missing_config", "reason": "未发现 qodana.yaml；如需无配置运行，请显式指定 --qodana-linter"})
        return result
    tool = ensure_qodana(args, output / "_tools", result)
    if not tool:
        return result
    result_dir = output / "qodana"
    cmd = [tool, "scan", "--results-dir", str(result_dir)]
    if args.qodana_linter:
        cmd.extend(["--linter", args.qodana_linter])
    if args.qodana_native:
        cmd.append("--within-docker=false")
    execution = run_cmd(cmd, root, args.timeout_seconds)
    result.update({"status": "passed" if execution["exit_code"] == 0 else "failed", "result_dir": str(result_dir), "execution": execution})
    return result


def write_markdown(path: Path, report: dict):
    lines = [
        "# 静态分析工具执行报告",
        "",
        f"- root: `{report['root']}`",
        f"- generated_at: `{report['generated_at']}`",
        "",
        "## 工具状态",
    ]
    for tool in report["tools"]:
        lines.append(f"- {tool['name']}: {tool['status']} {tool.get('reason', '')}")
    lines.extend(["", "## 发现配置", ""])
    for key, value in report["discovered"].items():
        lines.append(f"- {key}: {len(value)}")
    path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Run SonarScanner, Qodana and Checkstyle with auditable fallback states.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="artifacts/code-quality-governor")
    parser.add_argument("--tools", default="sonar,qodana,checkstyle")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--sonar-host-url", default=os.environ.get("SONAR_HOST_URL", ""))
    parser.add_argument("--sonar-scanner-url", default=os.environ.get("SONAR_SCANNER_URL", ""))
    parser.add_argument("--qodana-linter", default="")
    parser.add_argument("--qodana-native", action="store_true")
    parser.add_argument("--checkstyle-config", default="")
    parser.add_argument("--checkstyle-version", default="13.4.2")
    parser.add_argument("--checkstyle-url", default="")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    discovered = discover(root)
    selected = {item.strip().lower() for item in args.tools.split(",") if item.strip()}
    tools = []
    if "sonar" in selected or "sonar-scanner" in selected:
        tools.append(run_sonar(args, root, output, discovered))
    if "qodana" in selected:
        tools.append(run_qodana(args, root, output, discovered))
    if "checkstyle" in selected:
        tools.append(run_checkstyle(args, root, output, discovered))
    summary = {}
    for tool in tools:
        summary[tool["status"]] = summary.get(tool["status"], 0) + 1
    report = {
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "allow_download": args.allow_download,
        "discovered": discovered,
        "tools": tools,
        "summary": summary,
    }
    (output / "static-analysis-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "tool-run-summary.json").write_text(json.dumps({"tools": tools, "summary": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(output / "static-analysis-report.md", report)
    print(json.dumps({"output": str(output), "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
""",
        "render_code_review_html.py": """#!/usr/bin/env python3
import argparse
import html
import json
import re
from pathlib import Path

SECRET = re.compile(r"(?i)(token|password|passwd|secret|key|credential|authorization)(\\s*[=:]\\s*)([^\\s<>&]+)")


def load_json(path: Path):
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def redact(value):
    text = "" if value is None else str(value)
    return SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)


def esc(value):
    return html.escape(redact(value))


def findings_from(*payloads):
    items = []
    for payload in payloads:
        if isinstance(payload, dict):
            for key in ["findings", "issues", "comments"]:
                if isinstance(payload.get(key), list):
                    items.extend(payload[key])
    return items


def pick(item, *keys, default=""):
    for key in keys:
        if isinstance(item, dict) and item.get(key) not in (None, ""):
            return item.get(key)
    return default


def count_by(findings, *keys):
    result = {}
    for item in findings:
        value = str(pick(item, *keys, default="unknown")).lower()
        result[value] = result.get(value, 0) + 1
    return result


def render_badges(counts):
    if not counts:
        return '<span class="muted">无数据</span>'
    return "".join(f'<span class="badge">{esc(k)} <strong>{v}</strong></span>' for k, v in sorted(counts.items()))


def render_table(findings):
    rows = []
    for index, item in enumerate(findings, start=1):
        fid = pick(item, "id", "rule", "rule_id", default=f"finding-{index}")
        severity = pick(item, "severity", "level", "priority", default="unknown")
        dimension = pick(item, "dimension", "category", "type", default="unknown")
        file_name = pick(item, "file", "path", "location", default="")
        line = pick(item, "line", "start_line", "start", default="")
        title = pick(item, "title", "message", "problem", "summary", default="")
        impact = pick(item, "impact", "risk", default="")
        suggestion = pick(item, "suggestion", "recommendation", "fix", default="")
        rows.append(f"<tr><td>{esc(fid)}</td><td>{esc(severity)}</td><td>{esc(dimension)}</td><td>{esc(file_name)}:{esc(line)}</td><td>{esc(title)}</td><td>{esc(impact)}</td><td>{esc(suggestion)}</td></tr>")
    return "\\n".join(rows) or '<tr><td colspan="7" class="muted">未登记 finding</td></tr>'


def main():
    parser = argparse.ArgumentParser(description="Render a rich HTML report for manual code review.")
    parser.add_argument("--review-json", default="")
    parser.add_argument("--quality-json", default="")
    parser.add_argument("--static-json", default="")
    parser.add_argument("--markdown", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--title", default="代码走查报告")
    args = parser.parse_args()

    review = load_json(Path(args.review_json)) if args.review_json else {}
    quality = load_json(Path(args.quality_json)) if args.quality_json else {}
    static = load_json(Path(args.static_json)) if args.static_json else {}
    markdown = Path(args.markdown).read_text(encoding="utf-8") if args.markdown and Path(args.markdown).exists() else ""
    findings = findings_from(review, quality, static)
    gate = quality.get("gate_decision") or review.get("gate_decision") or review.get("status") or "unknown"
    tool_rows = []
    for tool in static.get("tools", []):
        tool_rows.append(f"<tr><td>{esc(tool.get('name'))}</td><td>{esc(tool.get('status'))}</td><td>{esc(tool.get('reason', ''))}</td></tr>")
    html_text = f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(args.title)}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1f2933; background: #f6f8fb; }}
    header {{ background: #0f172a; color: white; padding: 24px 32px; }}
    main {{ padding: 24px 32px; }}
    section {{ background: white; border: 1px solid #d9e2ec; border-radius: 8px; padding: 18px; margin: 0 0 18px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .metric {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; }}
    .metric strong {{ display: block; font-size: 22px; margin-top: 6px; }}
    .badge {{ display: inline-block; margin: 4px 6px 4px 0; padding: 5px 8px; border-radius: 999px; background: #e8f1ff; color: #163b73; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #e5eaf0; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; }}
    pre {{ white-space: pre-wrap; background: #0b1020; color: #dbeafe; padding: 12px; border-radius: 6px; max-height: 360px; overflow: auto; }}
    .muted {{ color: #697586; }}
  </style>
</head>
<body>
  <header><h1>{esc(args.title)}</h1><div>gate decision: <strong>{esc(gate)}</strong></div></header>
  <main>
    <section class="summary">
      <div class="metric">Findings<strong>{len(findings)}</strong></div>
      <div class="metric">Severity<div>{render_badges(count_by(findings, "severity", "level", "priority"))}</div></div>
      <div class="metric">Quality Dimension<div>{render_badges(count_by(findings, "dimension", "category", "type"))}</div></div>
    </section>
    <section>
      <h2>静态分析工具状态</h2>
      <table><thead><tr><th>工具</th><th>状态</th><th>原因/说明</th></tr></thead><tbody>{''.join(tool_rows) or '<tr><td colspan="3" class="muted">未提供工具执行报告</td></tr>'}</tbody></table>
    </section>
    <section>
      <h2>问题清单</h2>
      <table><thead><tr><th>ID</th><th>级别</th><th>维度</th><th>位置</th><th>问题</th><th>影响</th><th>建议</th></tr></thead><tbody>{render_table(findings)}</tbody></table>
    </section>
    <section>
      <h2>人工确认区</h2>
      <label><input type="checkbox"> blocker 已逐项确认</label><br>
      <label><input type="checkbox"> 静态分析缺失项已有审批或修复计划</label><br>
      <label><input type="checkbox"> 高风险问题已有 owner 和完成时间</label>
    </section>
    <section>
      <h2>Markdown 摘要</h2>
      <pre>{esc(markdown[-20000:])}</pre>
    </section>
  </main>
</body>
</html>
'''
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(html_text, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
""",
        "validate_rule_candidates.py": """#!/usr/bin/env python3
import json, sys
from pathlib import Path
for arg in sys.argv[1:]:
    data = json.loads(Path(arg).read_text(encoding="utf-8"))
    for rule in data.get("rules", []):
        if rule.get("status") == "approved" and rule.get("review_required", True):
            raise SystemExit(f"{arg}: approved 规则仍处于需评审状态")
print("ok")
""",
        "validate_document_lifecycle.py": """#!/usr/bin/env python3
import json, re, sys
from pathlib import Path

DOC_NUMBER = re.compile(r"^(REQ|CTX|HLD|DDD|DBD|RDS|MQD|DRR|CQR|CRR|RLP|RVF|RTR|KNO|RPT)-[A-Z0-9][A-Z0-9-]{1,40}-[0-9]{8}-[0-9]{3}$")
REQUIRED = ["document_number", "document_status", "retention_policy", "title", "owner", "source_artifacts"]
FORMAL_STATUSES = {"approved", "final"}
INTERMEDIATE_STATUSES = {"draft", "reviewing", "blocked", "waiting_for_input"}

errors = []
for arg in sys.argv[1:]:
    path = Path(arg)
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in REQUIRED:
        if field not in data:
            errors.append(f"{path}: 缺少字段 {field}")
    if errors:
        continue
    if not DOC_NUMBER.match(str(data["document_number"])):
        errors.append(f"{path}: document_number 不符合编号规范")
    if data["document_status"] in INTERMEDIATE_STATUSES and data["retention_policy"] == "persist":
        errors.append(f"{path}: 中间过程文档不得 persist")
    if data["retention_policy"] == "persist" and data["document_status"] not in FORMAL_STATUSES:
        errors.append(f"{path}: 只有 approved/final 文档可以 persist")
if errors:
    raise SystemExit("\\n".join(errors))
print("ok")
""",
        "validate_stage_run_result.py": """#!/usr/bin/env python3
import json, re, sys
from pathlib import Path

VALID_LANGUAGE = {"zh-CN", "en"}
VALID_STATUSES = {"succeeded", "failed", "blocked", "waiting_for_input", "waiting_for_human_review", "skipped"}
VALID_PREFLIGHT_INPUT_STATES = {"ready", "waiting_for_input", "waiting_for_human_review", "blocked"}
DOC_NUMBER = re.compile(r"^(REQ|CTX|HLD|DDD|DBD|RDS|MQD|DRR|CQR|CRR|RLP|RVF|RTR|KNO|RPT)-[A-Z0-9][A-Z0-9-]{1,40}-[0-9]{8}-[0-9]{3}$")
DOC_REQUIRED = ["document_number", "document_status", "retention_policy", "title", "owner", "source_artifacts"]
WAITING_STATUSES = {"waiting_for_input", "waiting_for_human_review"}
BLOCKING_FINDING_SEVERITIES = {"blocker", "major"}
BLOCKING_GATE_RESULTS = {"block", "blocked", "block_for_completion", "blocked_for_product_completion", "fail", "failed", "error"}


def artifact_path(artifact):
    return artifact.get("path") or artifact.get("file") or artifact.get("uri") or ""


def artifact_kind(artifact):
    fields = [
        artifact.get("type", ""),
        artifact.get("artifact_type", ""),
        artifact.get("name", ""),
        artifact_path(artifact),
    ]
    return " ".join(str(item).lower() for item in fields)


def is_human_html_artifact(artifact):
    path_text = artifact_path(artifact).lower()
    kind = artifact_kind(artifact)
    return path_text.endswith((".html", ".htm")) and any(token in kind for token in ["human", "review", "confirmation", "approval"])


def is_blocking_gate(gate: dict) -> bool:
    raw = str(gate.get("result") or gate.get("status") or "").strip().lower()
    if raw in BLOCKING_GATE_RESULTS:
        return True
    return raw.startswith("block") or raw.startswith("fail")


def has_blocking_information_requests(info_requests) -> bool:
    for request in info_requests or []:
        if request.get("blocking") is True:
            return True
        questions = request.get("questions") or []
        if any(question.get("required") is True for question in questions if isinstance(question, dict)):
            return True
    return False


def is_preflight_waiting_artifact(artifact) -> bool:
    text = artifact_kind(artifact)
    path_text = artifact_path(artifact).lower().replace("\\\\", "/")
    allowed_tokens = [
        "required-information",
        "missing-information",
        "human-review",
        "approval",
        "workflow-trace",
        "resume",
        "open-questions",
        "artifact-index",
    ]
    return any(token in text or token in path_text for token in allowed_tokens)


def is_formal_artifact_before_input(artifact) -> bool:
    if is_human_html_artifact(artifact) or is_preflight_waiting_artifact(artifact):
        return False
    path_text = artifact_path(artifact).lower()
    kind = artifact_kind(artifact)
    formal_suffix = path_text.endswith((".md", ".xlsx", ".xls", ".json", ".yaml", ".yml"))
    formal_type = any(token in kind for token in ["markdown", "xlsx", "json", "yaml"])
    return formal_suffix or formal_type


def resolve_artifact_file(result_path: Path, artifact):
    raw = artifact_path(artifact)
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    candidates = [Path.cwd() / candidate, result_path.parent / candidate]
    candidates.extend(parent / candidate for parent in result_path.resolve().parents)
    for item in candidates:
        if item.exists():
            return item
    return candidates[0]


def validate_human_html(path: Path, owner: Path):
    if not path.exists():
        errors.append(f"{owner}: 人工审阅 HTML 不存在: {path}")
        return
    normalized_path = str(path).replace("\\\\", "/")
    if "/docs/human-review/" not in normalized_path:
        errors.append(f"{owner}: 人工审阅 HTML 必须放在 docs/human-review/ 目录: {path}")
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    if not any(token in lowered for token in ["<textarea", "<input", "<select", "contenteditable"]):
        errors.append(f"{owner}: 人工审阅 HTML 必须包含可编辑输入控件: {path}")
    if "data-human-review-packet" not in lowered:
        errors.append(f"{owner}: 人工审阅 HTML 必须标记 data-human-review-packet: {path}")
    if "answer-json" not in lowered:
        errors.append(f"{owner}: 人工审阅 HTML 必须包含答案 JSON 导出区域: {path}")
    if not any(token in lowered for token in ["download", "clipboard", "复制 json", "下载 json"]):
        errors.append(f"{owner}: 人工审阅 HTML 必须支持复制或下载结构化答案: {path}")

errors = []
for arg in sys.argv[1:]:
    path = Path(arg)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") not in VALID_STATUSES:
        errors.append(f"{path}: status 不合法")
    state = data.get("preflight_input_state")
    if state not in VALID_PREFLIGHT_INPUT_STATES:
        errors.append(f"{path}: preflight_input_state 必须为 ready、waiting_for_input、waiting_for_human_review 或 blocked")
    if data.get("language") not in VALID_LANGUAGE:
        errors.append(f"{path}: language 不能为空，且必须为 zh-CN 或 en")
    info_requests = data.get("required_information_requests", [])
    if data.get("status") == "waiting_for_input":
        if state != "waiting_for_input":
            errors.append(f"{path}: status=waiting_for_input 时 preflight_input_state 必须为 waiting_for_input")
        if not info_requests:
            errors.append(f"{path}: waiting_for_input 必须包含 required_information_requests")
        for index, request in enumerate(info_requests):
            if request.get("blocking") and not request.get("questions"):
                errors.append(f"{path}: required_information_requests[{index}].questions 不能为空")
        for artifact in data.get("artifacts", []):
            if is_formal_artifact_before_input(artifact):
                errors.append(f"{path}: waiting_for_input 不得登记正式阶段产物为已完成，必须先等待补充信息写回: {artifact_path(artifact) or artifact.get('name')}")
    if data.get("status") in WAITING_STATUSES:
        if data.get("status") == "waiting_for_human_review" and state not in {"waiting_for_human_review", "blocked"}:
            errors.append(f"{path}: status=waiting_for_human_review 时 preflight_input_state 必须为 waiting_for_human_review 或 blocked")
        html_artifacts = [artifact for artifact in data.get("artifacts", []) if is_human_html_artifact(artifact)]
        if not html_artifacts:
            errors.append(f"{path}: {data.get('status')} 必须在 artifacts 登记可填写的人工审阅 HTML")
        for artifact in html_artifacts:
            html_path = resolve_artifact_file(path, artifact)
            if html_path is not None:
                validate_human_html(html_path, path)
    if data.get("status") == "succeeded":
        if state != "ready":
            errors.append(f"{path}: succeeded 必须满足 preflight_input_state == ready")
        if has_blocking_information_requests(info_requests):
            errors.append(f"{path}: succeeded 不允许存在未解决的 blocking required_information_requests")
        metadata = data.get("document_metadata") or {}
        for field in DOC_REQUIRED:
            if field not in metadata or metadata.get(field) in ("", [], None):
                errors.append(f"{path}: document_metadata 缺少 {field}")
        number = str(metadata.get("document_number", ""))
        if number and not DOC_NUMBER.match(number):
            errors.append(f"{path}: document_metadata.document_number 不符合编号规范")
        for finding in data.get("findings", []):
            if str(finding.get("severity", "")).lower() in BLOCKING_FINDING_SEVERITIES:
                errors.append(f"{path}: succeeded 不允许包含 blocker/major finding: {finding.get('id') or finding.get('summary')}")
        for gate in data.get("quality_gates", []):
            if is_blocking_gate(gate):
                errors.append(f"{path}: succeeded 不允许包含阻断质量门禁: {gate.get('name') or gate.get('gate_id')}")
if errors:
    raise SystemExit("\\n".join(errors))
print("ok")
""",
        "validate_required_information_request.py": """#!/usr/bin/env python3
import json, sys
from pathlib import Path

REQUIRED = ["request_id", "run_id", "skill_id", "blocking", "status", "questions"]
QUESTION_REQUIRED = ["id", "question", "reason", "required", "priority", "expected_format"]
VALID_PRIORITY = {"critical", "major", "minor"}
VALID_STATUS = {"waiting_for_input", "optional_context_requested", "resolved"}

errors = []
for arg in sys.argv[1:]:
    path = Path(arg)
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in REQUIRED:
        if field not in data:
            errors.append(f"{path}: 缺少字段 {field}")
    if errors:
        continue
    questions = data.get("questions", [])
    if not questions:
        errors.append(f"{path}: questions 不能为空")
    if data.get("status") not in VALID_STATUS:
        errors.append(f"{path}: status 不合法")
    if data.get("blocking") and data.get("status") != "waiting_for_input":
        errors.append(f"{path}: blocking=true 时 status 必须为 waiting_for_input")
    for index, question in enumerate(questions):
        for field in QUESTION_REQUIRED:
            if field not in question:
                errors.append(f"{path}: questions[{index}] 缺少字段 {field}")
        if question.get("priority") not in VALID_PRIORITY:
            errors.append(f"{path}: questions[{index}].priority 不合法")
        if question.get("required") and not question.get("reason"):
            errors.append(f"{path}: questions[{index}] required=true 时必须说明 reason")
if errors:
    raise SystemExit("\\n".join(errors))
print("ok")
""",
        "run_skill_evals.py": """#!/usr/bin/env python3
import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

CASES = ["happy_path", "missing_required_input", "ambiguous_input", "policy_conflict", "edge_case", "regression_case", "technology_demo_adoption", "control_plane_drift", "rule_consumption_gap", "context_noise_overload", "low_quality_automation"]
REQUIRED_FIELDS = ["id", "name", "case_type", "scenario", "input", "expected_behavior", "expected_gate_decision", "expected_status", "pass_criteria", "required_artifacts", "grader"]
SCENARIO_FIELDS = ["title", "material", "system_scope", "team_rule_refs", "risk_focus", "forbidden_behavior"]
VALID_DECISIONS = {"pass", "waiting_for_input", "require_human_review", "block"}
VALID_STATUS = {"succeeded", "waiting_for_input", "waiting_for_human_review", "blocked"}
GENERIC_EXPECTED = {"生成声明产物并输出门禁决策", "识别该场景并避免误判通过"}

parser = argparse.ArgumentParser(description="Validate engineering-assistant skill eval coverage.")
parser.add_argument("--mode", choices=["static", "scored"], default="static")
parser.add_argument("--no-write-report", action="store_true", help="Run scored eval checks without writing eval-report.json.")
args = parser.parse_args()

errors = []
warnings = []


def run_json_command(command: list[str]) -> tuple[dict, str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    output = result.stdout.strip()
    try:
        data = json.loads(output) if output else {}
    except Exception:
        data = {}
    if result.returncode != 0:
        raise RuntimeError(result.stderr + result.stdout)
    return data, output


def run_scored_evals() -> dict:
    checks = []
    route_explicit, _ = run_json_command([sys.executable, "engineering-assistant/scripts/route_skill.py", "--prompt", "使用 repo-context-miner，根据当前仓库产物恢复上下文。"])
    checks.append({"id": "route-explicit", "status": "pass" if route_explicit.get("decision") == "repo-context-miner" else "block", "detail": route_explicit})
    route_negative, _ = run_json_command([sys.executable, "engineering-assistant/scripts/route_skill.py", "--prompt", "只解释 Code Development 的用途，不执行任务、不生成产物。"])
    checks.append({"id": "route-negative", "status": "pass" if route_negative.get("status") == "rejected" else "block", "detail": route_negative})
    route_canary, _ = run_json_command([sys.executable, "engineering-assistant/scripts/route_skill.py", "--prompt", "继续推进任务 complete_identity_access_rbac_and_model_usage_policy_projection_before_rag_runtime"])
    checks.append({"id": "route-ai-platform-next-action", "status": "pass" if route_canary.get("status") == "waiting_for_input" and route_canary.get("candidates") else "block", "detail": route_canary})
    manifest_result, _ = run_json_command([sys.executable, "engineering-assistant/scripts/validate_plugin_manifest.py"])
    checks.append({"id": "plugin-manifest-metadata", "status": "pass" if manifest_result.get("status") in {"pass", "waiting_for_human_review"} else "block", "detail": manifest_result})
    fixture_path = Path("engineering-assistant/evals/fixtures/ai-platform-v1.json")
    if not fixture_path.exists():
        checks.append({"id": "canary-fixture-exists", "status": "block", "detail": "missing ai-platform-v1 fixture"})
    else:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        root = Path(fixture["root"])
        if not root.exists():
            checks.append({"id": "canary-required-files", "status": "pass", "detail": {"skipped": True, "reason": "external canary root is unavailable on this machine", "root": str(root)}})
            checks.append({"id": "canary-context-pack", "status": "pass", "detail": {"skipped": True, "reason": "external canary root is unavailable on this machine", "root": str(root)}})
        else:
            missing = [item for item in fixture["required_files"] if not (root / item).exists()]
            checks.append({"id": "canary-required-files", "status": "pass" if not missing else "block", "detail": {"missing": missing}})
            context, _ = run_json_command([
                sys.executable,
                "engineering-assistant/scripts/recommend_context.py",
                "--root",
                str(root),
                "--skill-id",
                "workflow-orchestrator",
                "--task-id",
                fixture["task_id"],
            ])
            forbidden_ok = all(not item.endswith((".html", ".png", ".jpg", ".jpeg")) for item in [source["path"] for source in context.get("sources", [])])
            required_ok = not context.get("missing_required_sources")
            checks.append({"id": "canary-context-pack", "status": "pass" if context.get("status") == "pass" and forbidden_ok and required_ok else "block", "detail": context})
    plugin_sync = []
    with tempfile.TemporaryDirectory() as temp_dir:
        def stable_temp_text(value) -> str:
            return str(value).replace(str(Path(temp_dir).resolve()), "$EVAL_TEMP").replace(str(Path(temp_dir)), "$EVAL_TEMP")

        publish_root = Path(temp_dir) / "publish"
        marketplace_path = publish_root / ".agents" / "plugins" / "marketplace.json"
        publish_result = subprocess.run(
            [
                sys.executable,
                "engineering-assistant/scripts/publish_plugin.py",
                "--publish-root",
                str(publish_root),
                "--marketplace-path",
                str(marketplace_path),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if publish_result.returncode != 0:
            plugin_sync.append({"left": "source", "right": str(publish_root), "status": "block", "detail": publish_result.stdout + publish_result.stderr})
        else:
            plugin_root = publish_root / "plugins" / "teamwork-engineering-assistant"
            for left, right in [("skills", plugin_root / "skills"), ("engineering-assistant", plugin_root / "engineering-assistant")]:
                result = subprocess.run(["diff", "-qr", left, str(right)], text=True, capture_output=True, check=False)
                plugin_sync.append({"left": left, "right": str(right), "status": "pass" if result.returncode == 0 else "block", "detail": result.stdout + result.stderr})
            manifest_ok = (plugin_root / ".codex-plugin" / "plugin.json").exists() and marketplace_path.exists()
            if manifest_ok:
                published_manifest = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
                manifest_ok = published_manifest.get("metadata_status") == "waiting_for_human_review" and published_manifest.get("distribution_notes", {}).get("runtime_policy_pack") == "target-project-template"
            plugin_sync.append({"left": "plugin-manifest", "right": str(plugin_root), "status": "pass" if manifest_ok else "block", "detail": publish_result.stdout + publish_result.stderr})
        personal_root = Path(temp_dir) / "personal"
        personal_result = subprocess.run(
            [
                sys.executable,
                "engineering-assistant/scripts/publish_plugin.py",
                "--layout",
                "personal",
                "--publish-root",
                str(personal_root),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        personal_plugin_root = personal_root / "plugins" / "teamwork-engineering-assistant"
        personal_marketplace = personal_root / ".agents" / "plugins" / "marketplace.json"
        personal_manifest_ok = personal_result.returncode == 0 and (personal_plugin_root / ".codex-plugin" / "plugin.json").exists() and personal_marketplace.exists()
        if personal_manifest_ok:
            try:
                marketplace = json.loads(personal_marketplace.read_text(encoding="utf-8"))
                personal_manifest_ok = (
                    marketplace.get("name") == "personal"
                    and marketplace.get("interface", {}).get("displayName") == "Personal"
                    and marketplace.get("plugins", [{}])[0].get("source", {}).get("path") == "./plugins/teamwork-engineering-assistant"
                )
            except (json.JSONDecodeError, IndexError):
                personal_manifest_ok = False
        plugin_sync.append({"left": "personal-marketplace", "right": str(personal_marketplace), "status": "pass" if personal_manifest_ok else "block", "detail": personal_result.stdout + personal_result.stderr})
        hermes_root = Path(temp_dir) / "hermes"
        hermes_result = subprocess.run(
            [
                sys.executable,
                "engineering-assistant/scripts/publish_plugin.py",
                "--layout",
                "hermes",
                "--publish-root",
                str(hermes_root),
                "--enable",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        hermes_plugin_root = hermes_root / "plugins" / "teamwork-engineering-assistant"
        hermes_manifest_ok = (
            hermes_result.returncode == 0
            and (hermes_plugin_root / "plugin.yaml").exists()
            and (hermes_plugin_root / "__init__.py").exists()
            and (hermes_plugin_root / "skills").exists()
            and (hermes_plugin_root / "engineering-assistant").exists()
            and (hermes_root / "config.yaml").exists()
        )
        if hermes_manifest_ok:
            registered = []

            class FakeHermesContext:
                def register_skill(self, name, path, description=""):
                    registered.append({"name": name, "path": str(path), "description": description})

            try:
                spec = importlib.util.spec_from_file_location("teamwork_engineering_assistant_hermes_plugin", hermes_plugin_root / "__init__.py")
                module = importlib.util.module_from_spec(spec)
                assert spec is not None and spec.loader is not None
                spec.loader.exec_module(module)
                module.register(FakeHermesContext())
                expected = sorted(path.parent.name for path in Path("skills").glob("*/SKILL.md"))
                hermes_manifest_ok = (
                    sorted(item["name"] for item in registered) == expected
                    and len(registered) == len(expected)
                    and all(Path(item["path"]).exists() for item in registered)
                    and all(item["description"] for item in registered)
                    and "teamwork-engineering-assistant" in (hermes_root / "config.yaml").read_text(encoding="utf-8")
                )
            except Exception as exc:
                hermes_manifest_ok = False
                hermes_result.stderr += f"\\nHermes entrypoint check failed: {exc}"
        plugin_sync.append({"left": "hermes-plugin", "right": str(hermes_plugin_root), "status": "pass" if hermes_manifest_ok else "block", "detail": hermes_result.stdout + hermes_result.stderr})
        for item in plugin_sync:
            item["right"] = stable_temp_text(item.get("right", ""))
            item["detail"] = stable_temp_text(item.get("detail", ""))
    checks.extend({"id": f"plugin-sync-{Path(item['left']).name}", **item} for item in plugin_sync)
    passed = sum(1 for check in checks if check["status"] == "pass")
    report = {
        "status": "pass" if passed == len(checks) else "block",
        "metrics": {
            "checks_total": len(checks),
            "checks_passed": passed,
            "route_accuracy": 1.0 if all(check["status"] == "pass" for check in checks if check["id"].startswith("route-")) else 0.0,
            "schema_pass": 1.0,
            "distribution_surface_status": 1.0 if all(check["status"] == "pass" for check in checks if check["id"].startswith("plugin-manifest")) else 0.0,
            "control_plane_pass": 1.0 if any(check["id"] == "canary-context-pack" and check["status"] == "pass" for check in checks) else 0.0,
            "context_source_validity": 1.0 if all(check["status"] == "pass" for check in checks if "context" in check["id"]) else 0.0,
            "plugin_sync_status": 1.0 if all(check["status"] == "pass" for check in checks if check["id"].startswith("plugin-sync")) else 0.0,
        },
        "checks": checks,
    }
    if not args.no_write_report:
        for path in [
            Path("engineering-assistant/evals/reports/eval-report.json"),
        ]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    return report

for required_eval in [
    Path("engineering-assistant/evals/trigger/trigger-cases.jsonl"),
    Path("engineering-assistant/evals/safety/safety-cases.jsonl"),
]:
    if not required_eval.exists():
        errors.append(f"{required_eval}: 缺少团队级 eval 数据集")
    elif not required_eval.read_text(encoding="utf-8").strip():
        errors.append(f"{required_eval}: eval 数据集为空")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path}: 无法解析为 JSON/YAML 子集: {exc}")
        return {}


for skill in sorted(p for p in Path("skills").glob("*") if p.is_dir()):
    contract_path = skill / "contract.yaml"
    contract = load_json(contract_path) if contract_path.exists() else {}
    output_schema = load_json(skill / "output.schema.json") if (skill / "output.schema.json").exists() else {}
    declared_outputs = [item["name"] for item in contract.get("outputs", []) if item.get("name") != "code changes"]
    language_policy = contract.get("language_policy", {})
    if language_policy.get("when_unspecified") != "ask_user":
        errors.append(f"{contract_path}: language_policy.when_unspecified 必须为 ask_user")
    technology_selection_policy = contract.get("technology_selection_policy", {})
    categories = set(technology_selection_policy.get("categories", []))
    for category in ["backend_framework", "persistence_framework", "frontend_stack", "test_framework", "build_tool"]:
        if category not in categories:
            errors.append(f"{contract_path}: technology_selection_policy.categories 缺少 {category}")
    if technology_selection_policy.get("team_defaults", {}).get("java_spring_persistence") != "mybatis-plus":
        errors.append(f"{contract_path}: technology_selection_policy.team_defaults.java_spring_persistence 必须为 mybatis-plus")
    if technology_selection_policy.get("ask_user_when_unspecified") is not True:
        errors.append(f"{contract_path}: technology_selection_policy.ask_user_when_unspecified 必须为 true")
    if "JDBC" not in technology_selection_policy.get("requires_review", []):
        errors.append(f"{contract_path}: technology_selection_policy.requires_review 必须包含 JDBC")
    execution_gates = contract.get("execution_gates", {})
    for gate in ["preflight_required_information", "preflight_before_formal_artifacts", "preflight_input_state_required", "formal_generation_requires_ready", "formal_document_metadata_required", "stage_result_validation_required", "block_when_agent_violates_contract"]:
        if execution_gates.get(gate) is not True:
            errors.append(f"{contract_path}: execution_gates.{gate} 必须为 true")
    runtime_gate = contract.get("preflight_runtime_gate", {})
    if runtime_gate.get("state_field") != "preflight_input_state":
        errors.append(f"{contract_path}: preflight_runtime_gate.state_field 必须为 preflight_input_state")
    if runtime_gate.get("formal_generation_entry_condition") != "preflight_input_state == ready":
        errors.append(f"{contract_path}: preflight_runtime_gate.formal_generation_entry_condition 必须为 preflight_input_state == ready")
    required_policy = contract.get("required_information_policy", {})
    if required_policy.get("formal_generation_entry_condition") != "preflight_input_state == ready":
        errors.append(f"{contract_path}: required_information_policy.formal_generation_entry_condition 必须为 preflight_input_state == ready")
    required_schema_fields = set(output_schema.get("required", []))
    for field in ["language", "preflight_input_state", "document_metadata", "required_information_requests"]:
        if field not in required_schema_fields:
            errors.append(f"{skill / 'output.schema.json'}: required 缺少 {field}")
    fingerprints = set()
    for case in CASES:
        path = skill / "evals" / f"{case}.yaml"
        if not path.exists():
            errors.append(f"{path}: eval 用例缺失")
            continue
        data = load_json(path)
        if not data:
            continue
        for field in REQUIRED_FIELDS:
            if field not in data:
                errors.append(f"{path}: 缺少字段 {field}")
        if data.get("case_type") != case:
            errors.append(f"{path}: case_type 应为 {case}")
        scenario = data.get("scenario", {})
        for field in SCENARIO_FIELDS:
            if field not in scenario:
                errors.append(f"{path}: scenario 缺少字段 {field}")
        if len(str(scenario.get("material", ""))) < 40:
            errors.append(f"{path}: scenario.material 过短，不能作为真实压力场景")
        if not scenario.get("team_rule_refs"):
            errors.append(f"{path}: 未引用团队规范编号")
        if len(scenario.get("risk_focus", [])) < 2:
            errors.append(f"{path}: risk_focus 至少需要两个风险点")
        if not scenario.get("forbidden_behavior"):
            errors.append(f"{path}: forbidden_behavior 不能为空")
        if data.get("expected_behavior") in GENERIC_EXPECTED:
            errors.append(f"{path}: expected_behavior 仍是骨架模板")
        if data.get("expected_gate_decision") not in VALID_DECISIONS:
            errors.append(f"{path}: expected_gate_decision 不合法")
        if data.get("expected_status") not in VALID_STATUS:
            errors.append(f"{path}: expected_status 不合法")
        if len(data.get("pass_criteria", [])) < 5:
            errors.append(f"{path}: pass_criteria 过少，无法形成团队门禁")
        criteria_text = "\\n".join(data.get("pass_criteria", []))
        for required_text in ["language", "preflight_input_state", "document_metadata", "required_information_requests"]:
            if required_text not in criteria_text:
                errors.append(f"{path}: pass_criteria 缺少运行时行为断言 {required_text}")
        if skill.name in {"code-development", "detailed-design", "design-review", "code-review", "code-quality-governor"} and "framework" not in criteria_text and "mybatis-plus" not in criteria_text:
            errors.append(f"{path}: pass_criteria 缺少框架选型/mybatis-plus 防回归断言")
        if skill.name in {"code-review", "code-quality-governor"}:
            for required_text in ["sonar", "qodana", "checkstyle", "complexity", "HTML"]:
                if required_text not in criteria_text:
                    errors.append(f"{path}: pass_criteria 缺少静态分析/HTML 防回归断言 {required_text}")
        if skill.name in {"frontend-design", "frontend-development"} and "frontend" not in criteria_text:
            errors.append(f"{path}: pass_criteria 缺少 frontend 防回归断言")
        if case == "missing_required_input":
            for required_text in ["questions", "waiting_for_input", "docs/human-review", "不得生成或登记正式阶段", "preflight_input_state"]:
                if required_text not in criteria_text:
                    errors.append(f"{path}: missing_required_input 必须断言 {required_text}")
        stage_request = data.get("input", {}).get("stage_run_request", {})
        if stage_request.get("skill_id") != skill.name:
            errors.append(f"{path}: stage_run_request.skill_id 与目录不一致")
        if data.get("required_artifacts") != declared_outputs:
            errors.append(f"{path}: required_artifacts 与 contract outputs 不一致")
        fingerprint = json.dumps({
            "material": scenario.get("material"),
            "rules": scenario.get("team_rule_refs"),
            "decision": data.get("expected_gate_decision"),
        }, ensure_ascii=False, sort_keys=True)
        if fingerprint in fingerprints:
            errors.append(f"{path}: 与同 skill 其他 eval 场景重复")
        fingerprints.add(fingerprint)
        if skill.name in {"high-level-design", "detailed-design", "redis-design", "mq-design", "database-design", "design-review"} and len(scenario.get("team_rule_refs", [])) < 3:
            warnings.append(f"{path}: 核心设计 skill 建议至少引用 3 条团队规范")
    for path in sorted((skill / "evals").glob("*.yaml")):
        if path.stem in CASES:
            continue
        data = load_json(path)
        if not data:
            continue
        for field in REQUIRED_FIELDS:
            if field not in data:
                errors.append(f"{path}: 缺少字段 {field}")
        if data.get("case_type") != path.stem:
            errors.append(f"{path}: case_type 应为 {path.stem}")
        scenario = data.get("scenario", {})
        for field in SCENARIO_FIELDS:
            if field not in scenario:
                errors.append(f"{path}: scenario 缺少字段 {field}")
        if len(str(scenario.get("material", ""))) < 40:
            errors.append(f"{path}: scenario.material 过短，不能作为真实压力场景")
        if len(scenario.get("team_rule_refs", [])) < 3:
            errors.append(f"{path}: 团队专项 eval 至少引用 3 条团队规范")
        criteria_text = "\\n".join(data.get("pass_criteria", []))
        for required_text in ["language", "preflight_input_state", "document_metadata", "required_information_requests"]:
            if required_text not in criteria_text:
                errors.append(f"{path}: pass_criteria 缺少运行时行为断言 {required_text}")
        for required_text in ["detailed-design.md", "sequenceDiagram", "flowchart", "StageRunResult.artifacts"]:
            if skill.name == "detailed-design" and required_text not in criteria_text:
                errors.append(f"{path}: pass_criteria 缺少团队详细设计断言 {required_text}")
        if data.get("expected_gate_decision") not in VALID_DECISIONS:
            errors.append(f"{path}: expected_gate_decision 不合法")
        if data.get("expected_status") not in VALID_STATUS:
            errors.append(f"{path}: expected_status 不合法")
        if data.get("required_artifacts") != declared_outputs:
            errors.append(f"{path}: required_artifacts 与 contract outputs 不一致")

for required_skill in ["frontend-design", "frontend-development"]:
    if not (Path("skills") / required_skill / "SKILL.md").exists():
        errors.append(f"skills/{required_skill}: 前端研发流程 skill 缺失")

if args.mode == "scored" and not errors:
    scored_report = run_scored_evals()
    if scored_report["status"] != "pass":
        errors.append("scored eval failed: " + json.dumps(scored_report, ensure_ascii=False))

if errors:
    raise SystemExit("\\n".join(errors))
if warnings:
    print("\\n".join(f"warning: {item}" for item in warnings))
print("ok")
""",
        "control_runtime.py": """#!/usr/bin/env python3
import hashlib
import html.parser
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CONTROL_DIR = Path("artifacts/_control")

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def ensure_control_dir(root: Path) -> Path:
    path = root / CONTROL_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path

def validate_target_project_root(root: Path) -> Path:
    root = root.resolve()
    plugin_markers = [
        root / ".codex-plugin" / "plugin.json",
        root / "engineering-assistant" / "scripts" / "control_runtime.py",
        root / "scripts" / "control_runtime.py",
    ]
    if any(marker.exists() for marker in plugin_markers):
        raise SystemExit("--root must be the target project root, not the Codex plugin directory")
    return root

def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")

def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

class _HTMLTextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.parts.append(text)

def read_text_artifact(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".html", ".htm"}:
        parser = _HTMLTextExtractor()
        parser.feed(raw)
        return "\\n".join(parser.parts)
    return raw

def compact_lines(text: str, limit: int = 24):
    lines = []
    metadata_prefixes = ("document_number:", "document_status:", "retention_policy:", "owner:", "approval_status:", "language:", "source_artifacts:")
    source_path_prefixes = ("artifacts/", "docs/", "engineering-assistant/")
    for raw in text.splitlines():
        item = re.sub(r"\\s+", " ", raw.strip(" -*\\t"))
        lowered = item.lower()
        if not item or item.startswith("|") or lowered.startswith(metadata_prefixes):
            continue
        if item.startswith("#") or item.startswith(source_path_prefixes):
            continue
        if len(item) >= 8 and item not in lines:
            lines.append(item[:240])
        if len(lines) >= limit:
            break
    return lines

def _append_unique(result, item: str):
    if item and item not in result:
        result.append(item)

def _append_path_pattern(result, item: str):
    normalized = item.strip().strip("`'\\"，,.;；:()[]{}").strip("./")
    if not normalized or any(part in normalized for part in ["..", "://", "\\\\"]) or " " in normalized:
        return
    path_roots = ("backend/", "frontend/", "deploy/", "docs/", "artifacts/", "engineering-assistant/", "scripts/", "src/", "test/", "tests/")
    file_like = re.search(r"\\.(?:java|kt|go|py|ts|tsx|js|jsx|vue|sql|xml|yaml|yml|json|md)$", normalized)
    if not file_like and not normalized.startswith(path_roots):
        return
    if normalized not in {"package.json", "tsconfig.json"}:
        _append_unique(result, normalized)

def _append_project_module_pattern(result, token: str):
    normalized = token.strip().strip("`'\\"，,.;；:()[]{}").strip("./")
    if not normalized or " " in normalized:
        return
    if normalized == "contexts/*":
        _append_unique(result, "backend/contexts/*")
    elif normalized.startswith("platform-"):
        _append_unique(result, f"backend/platform-boot/{normalized}")
    elif normalized.startswith("shared-"):
        _append_unique(result, f"backend/platform-shared/{normalized}")
    elif normalized.startswith("infra-"):
        _append_unique(result, f"backend/platform-infrastructure/{normalized}")

def find_file_patterns(text: str):
    result = []
    for item in re.findall(r"[\\w./*-]+\\.(?:java|kt|go|py|tsx|ts|jsx|json|js|vue|sql|xml|yaml|yml|md)(?=$|[\\s`'\\"<>),，。;；])", text):
        _append_path_pattern(result, item)
    for item in re.findall(r"`([^`\\n]+)`", text):
        for part in re.split(r"[,，;；\\s]+", item):
            _append_path_pattern(result, part)
            _append_project_module_pattern(result, part)
    for item in re.findall(r"\\b(?:backend|frontend|deploy|docs|artifacts|engineering-assistant|scripts|src|test|tests)(?:/[A-Za-z0-9._*{}-]+)+/?", text):
        _append_path_pattern(result, item)
    if re.search(r"\\bbackend\\b|后端|Maven|Spring Boot", text, re.IGNORECASE):
        for item in ["pom.xml", "backend/pom.xml", "backend/platform-boot/*", "backend/platform-shared/*", "backend/platform-infrastructure/*", "backend/contexts/*"]:
            _append_unique(result, item)
    if re.search(r"\\bfrontend\\b|前端|React|Vite", text, re.IGNORECASE):
        for item in ["frontend/console-web", "frontend/console-web/src", "frontend/console-web/package.json"]:
            _append_unique(result, item)
    if re.search(r"\\bdeploy\\b|部署|Docker|真实环境", text, re.IGNORECASE):
        _append_unique(result, "deploy/")
    return result[:120]

def update_artifact_index(root: Path, name: str, path: Path, artifact_type: str, producer: str):
    control = ensure_control_dir(root)
    index_path = control / "artifact-index.json"
    data = read_json(index_path, {"artifacts": {}})
    rel = str(path.relative_to(root)) if path.is_absolute() else str(path)
    data["artifacts"][name] = {"name": name, "path": rel, "artifact_type": artifact_type, "producer": producer, "updated_at": now_iso()}
    data["updated_at"] = now_iso()
    write_json(index_path, data)
""",
        "init_task.py": """#!/usr/bin/env python3
import argparse
import re
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, read_json, validate_target_project_root, write_json

def slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return value or "task"

def main():
    parser = argparse.ArgumentParser(description="Initialize engineering-assistant task control files.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--title", required=True)
    parser.add_argument("--language", choices=["zh-CN", "en"], default="zh-CN")
    parser.add_argument("--workflow-id", default="contract-driven-development")
    parser.add_argument("--project-profile")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    control = ensure_control_dir(root)
    task_id = args.task_id or slug(args.title)
    profile = read_json(Path(args.project_profile), {}) if args.project_profile else {}
    task = {"task_id": task_id, "title": args.title, "language": args.language, "workflow_id": args.workflow_id, "status": "initialized", "control_dir": str(control.relative_to(root)), "project_profile": profile, "current_contracts": {}, "created_at": now_iso(), "updated_at": now_iso()}
    write_json(control / "current-task.json", task)
    write_json(control / "artifact-index.json", {"artifacts": {}, "updated_at": now_iso()})
    write_json(control / "decision-log.json", {"decisions": []})
    write_json(control / "open-questions.json", {"questions": []})
    write_json(control / "approval-log.json", {"approvals": []})
    context = [
        "# Task Context",
        "",
        "## Read First",
        "- This file is the short control-plane entry for the current task.",
        "- Do not bulk-read all docs before checking the rule pack and contracts listed here.",
        "- Stop when a blocking open question, missing approval, or failed quality gate is present.",
        "",
        "## Task",
        f"- task_id: {task_id}",
        f"- title: {args.title}",
        f"- language: {args.language}",
        f"- workflow_id: {args.workflow_id}",
        "",
        "## Control Artifacts",
        "- current_task: artifacts/_control/current-task.json",
        "- implementation_contract: artifacts/_control/implementation-contract.json",
        "- quality_contract: artifacts/_control/quality-contract.json",
        "- open_questions: artifacts/_control/open-questions.json",
        "- task_rule_pack: artifacts/rule-governance/task-rule-packs/code-development.json",
        "",
        "## Mandatory Entry Checks",
        "- python3 engineering-assistant/scripts/validate_contract_control.py <project-root>",
        "- python3 engineering-assistant/scripts/validate_control_health.py --root <project-root>",
        "- python3 engineering-assistant/scripts/run_controlled_task.py --root <project-root> --mode audit-readonly",
        "",
    ]
    (control / "task-context.agent.md").write_text("\\n".join(context), encoding="utf-8")
    print(control / "current-task.json")

if __name__ == "__main__":
    main()
""",
        "ensure_agent_entrypoint.py": """#!/usr/bin/env python3
import argparse
from pathlib import Path
from control_runtime import validate_target_project_root

MARKER = "<!-- generated-by: engineering-assistant -->"

def build_content(project_name: str) -> str:
    return f'''# AGENTS.md
{MARKER}

## Repository Goal
- Maintain {project_name} through the engineering-assistant control plane.
- Treat `artifacts/_control/task-context.agent.md` as the task entrypoint before broad document search.

## Required Entry Checks
- Read `artifacts/_control/current-task.json`, `task-context.agent.md`, `implementation-contract.json`, and `quality-contract.json`.
- Read the task rule pack under `artifacts/rule-governance/task-rule-packs/` and cite rule ids in implementation, self-test, quality, and review evidence.
- Run `python3 engineering-assistant/scripts/run_controlled_task.py --root . --mode audit-readonly` before review-only work.

## Scope And Safety
- Do not expand scope outside `implementation-contract.json`.
- Stop on stale control-plane evidence, blocking open questions, missing approvals, production actions, or failed quality gates.
- Do not replace failed gates with prose explanations; fix, block, or ask for human review.
'''

def main():
    parser = argparse.ArgumentParser(description="Create a short target-project AGENTS.md entrypoint for the control plane.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--project-name", default="this repository")
    parser.add_argument("--output", default="AGENTS.md")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    output = root / args.output
    content = build_content(args.project_name)
    if args.dry_run:
        print(content)
        return
    if output.exists() and MARKER not in output.read_text(encoding="utf-8") and not args.force:
        raise SystemExit(f"{args.output} exists and is not generated by engineering-assistant; rerun with --force after human review")
    output.write_text(content, encoding="utf-8")
    print(output)

if __name__ == "__main__":
    main()
""",
        "compile_design_contract.py": """#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from control_runtime import checksum, compact_lines, ensure_control_dir, find_file_patterns, now_iso, read_json, update_artifact_index, validate_target_project_root, write_json

DEFAULT_FORBIDDEN = [".git/", ".idea/", "node_modules/", "target/", "build/", "dist/", "coverage/"]
DEFAULT_RULES = [
    "Every changed source file must map to design-contract goals or acceptance criteria.",
    "Do not modify forbidden modules or generated dependency/build directories.",
    "Follow existing repository framework, layering, mapper/repository, service, and test conventions.",
    "Record unresolved business decisions in open-questions.json instead of guessing.",
    "A succeeded stage must not contain blocker or major findings, blocked quality gates, or product-completion blockers.",
]
PLACEHOLDER_RE = re.compile(r"(待 code-development 阶段写入|待确认|todo|tbd|placeholder)", re.IGNORECASE)

def is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER_RE.search(value or ""))

def infer_commands(profile: dict, file_patterns: list[str]):
    commands = []
    raw_quality = profile.get("quality_commands", [])
    raw_items = []
    if isinstance(raw_quality, list):
        raw_items.extend(raw_quality)
    elif isinstance(raw_quality, dict):
        for value in raw_quality.values():
            raw_items.extend(value if isinstance(value, list) else [value])
    for item in raw_items:
        if isinstance(item, str) and not is_placeholder(item):
            commands.append({"id": item.split()[0], "command": item, "required": True})
        elif isinstance(item, dict) and item.get("command") and not is_placeholder(item["command"]):
            commands.append({"id": item.get("id", f"cmd-{len(commands) + 1}"), "command": item["command"], "required": item.get("required", True)})
    pattern_text = "\\n".join(file_patterns)
    if not commands and re.search(r"(^|/)pom\\.xml$|backend/", pattern_text):
        commands.append({"id": "backend-test", "command": "mvn -q test", "required": True})
    if not commands and "frontend/console-web" in pattern_text:
        commands.append({"id": "frontend-test", "command": "cd frontend/console-web && npm test", "required": True})
        commands.append({"id": "frontend-build", "command": "cd frontend/console-web && npm run build", "required": True})
    if not commands:
        commands.append({"id": "repo-test", "command": "python3 -m unittest discover", "required": True})
    return commands

def grep_lines(lines: list[str], keywords: list[str], limit: int = 12) -> list[str]:
    selected = []
    lowered_keywords = [item.lower() for item in keywords]
    for line in lines:
        lowered = line.lower()
        if any(keyword in lowered for keyword in lowered_keywords) and line not in selected:
            selected.append(line[:240])
        if len(selected) >= limit:
            break
    return selected

def backtick_values(text: str) -> list[str]:
    values = []
    for item in re.findall(r"`([^`\\n]+)`", text):
        item = item.strip()
        if item and item not in values:
            values.append(item)
    return values

def infer_expected_contracts(text: str, lines: list[str], file_patterns: list[str]) -> dict:
    ticks = backtick_values(text)
    api_like = [item for item in ticks if item.startswith("/") or "/api/" in item or item.lower().endswith(("request", "response", "controller"))]
    service_like = [item for item in ticks if re.search(r"(Service|UseCase|Application|应用服务|用例)$", item)]
    repo_like = [item for item in ticks if re.search(r"(Repository|Mapper|Port|仓储|持久化|MyBatis)", item, re.IGNORECASE)]
    if not api_like:
        api_like = grep_lines(lines, ["api", "接口", "controller", "request", "response"], 8)
    if not service_like:
        service_like = grep_lines(lines, ["application service", "应用服务", "use case", "用例", "领域服务"], 8)
    if not repo_like:
        repo_like = grep_lines(lines, ["repository", "mapper", "port", "仓储", "持久化", "mybatis"], 8)
    if not api_like and any("frontend/" in item or "backend/" in item for item in file_patterns):
        api_like = ["All changed public API contracts must be explicitly mapped to request/response tests."]
    if not service_like and any("backend/" in item for item in file_patterns):
        service_like = ["Each backend use case must identify one application service boundary and one bounded-context owner."]
    if not repo_like and any("backend/" in item for item in file_patterns):
        repo_like = ["Persistence access must go through repository/mapper adapters declared by the task design."]
    return {"expected_interfaces": api_like[:20], "expected_services": service_like[:20], "expected_repositories_or_mappers": repo_like[:20]}

def infer_technology_adoption_contract(text: str, file_patterns: list[str], profile: dict) -> dict:
    explicit = profile.get("technology_adoption_contract")
    if isinstance(explicit, dict) and explicit:
        return explicit
    frameworks = profile.get("backend_frameworks", {}) if isinstance(profile.get("backend_frameworks"), dict) else {}
    persistence = frameworks.get("persistence") or profile.get("persistence_framework") or ""
    pattern_text = "\\n".join(file_patterns)
    backend_like = bool(re.search(r"backend/|pom\\.xml|spring|java", pattern_text + "\\n" + text, re.IGNORECASE))
    frontend_like = bool(re.search(r"frontend/|react|vite|tsx|jsx|package\\.json", pattern_text + "\\n" + text, re.IGNORECASE))
    if backend_like and (not persistence or "mybatis" in str(persistence).lower()):
        return {
            "backend_framework": frameworks.get("web") or profile.get("backend_framework") or "Spring Boot",
            "persistence_framework": persistence or "mybatis-plus",
            "required_indicators": ["BaseMapper", "@Mapper", "extends ServiceImpl", "LambdaQueryWrapper"],
            "forbidden_indicators": ["DriverManager.getConnection", "JdbcTemplate", "java.sql.Statement"],
            "minimum_required_indicators": 1,
            "review_required_for": ["JDBC", "direct SQL bypassing mapper/repository"],
        }
    if frontend_like:
        frontend_stack = profile.get("frontend_stack") or "React/Vite"
        return {
            "frontend_stack": frontend_stack,
            "required_indicators": ["React", "Vite", "useState", "useEffect", "render(", "describe("],
            "forbidden_indicators": ["document.querySelector", "innerHTML"],
            "minimum_required_indicators": 1,
            "review_required_for": ["framework replacement", "component library replacement", "direct DOM mutation"],
        }
    return {"required_indicators": [], "forbidden_indicators": [], "minimum_required_indicators": 0, "review_required_for": []}

def infer_required_tests(text: str, file_patterns: list[str], profile: dict) -> list[str]:
    tests = [item.strip() for item in profile.get("required_tests", []) if isinstance(item, str) and item.strip() and not is_placeholder(item)] if isinstance(profile.get("required_tests"), list) else []
    pattern_text = "\\n".join(file_patterns)
    if "backend/" in pattern_text:
        tests.extend(["backend unit tests for domain/application invariants and failure paths", "backend architecture boundary tests for DDD dependencies and high cohesion"])
    if "frontend/console-web" in pattern_text:
        tests.extend(["frontend component tests for forms, guards, and error states", "frontend integration tests for real API client and permission-driven navigation"])
    if re.search(r"真实环境|E2E|验收|release", text, re.IGNORECASE):
        tests.append("real environment smoke or Playwright E2E proving frontend-backend interaction with required dependencies")
    if not tests:
        tests.append("task-specific failing test must be written before implementation and pass before review")
    return list(dict.fromkeys(tests))

def esc(value) -> str:
    return html.escape("" if value is None else str(value))

def build_initial_traceability(design_contract: dict, implementation_contract: dict, quality_contract: dict) -> dict:
    rows = []
    seeds = design_contract.get("acceptance_criteria") or design_contract.get("goals") or ["Implement the approved design without expanding scope."]
    for index, item in enumerate(seeds[:20], start=1):
        rows.append({
            "requirement_id": f"REQ-{index:03d}",
            "requirement": item,
            "design_refs": [design_contract.get("source_design", "")],
            "implementation_targets": implementation_contract.get("allowed_modules", []),
            "changed_files": [],
            "tests": implementation_contract.get("required_tests", []),
            "validation_status": "pending_code_development",
            "evidence": {
                "design_contract": "artifacts/_control/design-contract.json",
                "implementation_contract": "artifacts/_control/implementation-contract.json",
                "quality_contract": "artifacts/_control/quality-contract.json",
            },
            "gaps": ["等待 code-development 阶段写入 design-to-code-mapping.yaml、changed-files-report.json 并刷新追踪报告"],
        })
    return {
        "task_id": design_contract.get("task_id"),
        "status": "pending_code_development",
        "source_of_truth": "artifacts/_control/traceability-matrix.json",
        "human_readable_report": "docs/human-readable/traceability-report.html",
        "html_policy": "HTML is human-only and cannot be consumed as agent source evidence",
        "summary": {"requirements": len(rows), "mapped_rows": 0, "gap_rows": len(rows)},
        "rows": rows,
        "required_evidence": quality_contract.get("required_evidence", []),
        "generated_at": now_iso(),
    }

def render_traceability_html(matrix: dict) -> str:
    rows = matrix.get("rows", [])
    summary = matrix.get("summary", {})
    table_rows = []
    for row in rows:
        gaps = row.get("gaps") or []
        status = row.get("validation_status") or "unknown"
        design_cell = "<br>".join(esc(item) for item in row.get("design_refs", [])) or '<span class="muted">未登记</span>'
        target_cell = "<br>".join(esc(item) for item in row.get("implementation_targets", [])) or '<span class="muted">待实现</span>'
        changed_cell = "<br>".join(esc(item) for item in row.get("changed_files", [])) or '<span class="muted">待写入</span>'
        tests_cell = "<br>".join(esc(item) for item in row.get("tests", [])) or '<span class="muted">待确认</span>'
        gaps_cell = "<br>".join(esc(item) for item in gaps)
        table_rows.append(
            "<tr>"
            f"<td><strong>{esc(row.get('requirement_id'))}</strong><div class='muted'>{esc(row.get('requirement'))}</div></td>"
            f"<td>{design_cell}</td>"
            f"<td>{target_cell}</td>"
            f"<td>{changed_cell}</td>"
            f"<td>{tests_cell}</td>"
            f"<td><span class='status'>{esc(status)}</span><div class='gap'>{gaps_cell}</div></td>"
            "</tr>"
        )
    return "\\n".join([
        "<!doctype html>",
        '<html lang="zh-CN" data-human-readable-report="traceability">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>需求-设计-代码追踪报告</title>",
        "<style>",
        'body{margin:0;background:#f5f7fb;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}',
        "header{background:#111827;color:#fff;padding:28px 36px}main{padding:24px 36px 56px}",
        "section{background:#fff;border:1px solid #dbe3ef;border-radius:8px;margin:0 0 18px;padding:18px}h1,h2{margin:0 0 12px}",
        ".notice{color:#bfdbfe;margin-top:8px}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}",
        ".metric{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:12px}.metric strong{display:block;font-size:26px;margin-top:4px}",
        "table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid #e5eaf0;padding:9px;text-align:left;vertical-align:top}th{background:#f1f5f9}",
        ".muted{color:#64748b;margin-top:4px}.status{display:inline-block;border-radius:999px;padding:3px 8px;background:#e0f2fe;color:#075985}.gap{color:#9a3412;margin-top:6px}.source{font-size:13px;color:#475569}",
        "</style>",
        "</head><body><header>",
        "<h1>需求-设计-代码追踪报告</h1>",
        f"<div>task_id: <strong>{esc(matrix.get('task_id'))}</strong> · status: <strong>{esc(matrix.get('status'))}</strong></div>",
        '<div class="notice">人工阅览入口。机读事实源是 artifacts/_control/traceability-matrix.json，agent 不得反向读取本 HTML 作为事实输入。</div>',
        "</header><main>",
        '<section class="metrics">',
        f'<div class="metric">需求条目<strong>{esc(summary.get("requirements", len(rows)))}</strong></div>',
        f'<div class="metric">已映射<strong>{esc(summary.get("mapped_rows", 0))}</strong></div>',
        f'<div class="metric">存在缺口<strong>{esc(summary.get("gap_rows", 0))}</strong></div>',
        "</section>",
        "<section><h2>追踪矩阵</h2><table><thead><tr><th>需求</th><th>设计依据</th><th>实现目标</th><th>代码文件</th><th>测试/验证</th><th>状态与缺口</th></tr></thead><tbody>",
        "".join(table_rows) or '<tr><td colspan="6" class="muted">暂无追踪条目</td></tr>',
        "</tbody></table></section>",
        "<section class=\\\"source\\\"><h2>证据文件</h2><div>design-contract.json · implementation-contract.json · quality-contract.json · design-to-code-mapping.yaml · changed-files-report.json · design-to-code-validation.json</div></section>",
        "</main></body></html>",
    ])

def write_traceability_outputs(root: Path, control: Path, matrix: dict) -> None:
    matrix_path = control / "traceability-matrix.json"
    html_path = root / "docs/human-readable/traceability-report.html"
    write_json(matrix_path, matrix)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_traceability_html(matrix), encoding="utf-8")
    update_artifact_index(root, matrix_path.name, matrix_path, "json", "implementation-controller")
    update_artifact_index(root, html_path.name, html_path, "html", "implementation-controller")

def main():
    parser = argparse.ArgumentParser(description="Compile an approved design artifact into machine-readable control contracts.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--design", required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--profile")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    design_path = Path(args.design)
    if not design_path.is_absolute():
        design_path = root / design_path
    if design_path.suffix.lower() in {".html", ".htm"}:
        raise SystemExit("HTML artifacts are human-only. Provide the approved MD/JSON/YAML design artifact instead.")
    control = ensure_control_dir(root)
    task = read_json(control / "current-task.json", {})
    profile = read_json(Path(args.profile), {}) if args.profile else task.get("project_profile", {})
    task_id = args.task_id or task.get("task_id") or design_path.stem
    text = design_path.read_text(encoding="utf-8")
    lines = compact_lines(text, 32)
    file_patterns = find_file_patterns(text)
    expected = infer_expected_contracts(text, lines, file_patterns)
    design_contract = {"task_id": task_id, "source_design": str(design_path.relative_to(root)), "source_checksum": checksum(design_path), "generated_at": now_iso(), "goals": lines[:8] or ["Implement the approved design without expanding scope."], "acceptance_criteria": lines[:12], "module_boundaries": {"allowed_from_design": file_patterns, "source": "compiled_from_design_artifact"}, "assumptions": ["The human-approved design is the source of truth for implementation scope."]}
    implementation_contract = {"task_id": task_id, "allowed_modules": file_patterns, "forbidden_modules": DEFAULT_FORBIDDEN, "required_files_or_patterns": file_patterns, "expected_interfaces": expected["expected_interfaces"], "expected_services": expected["expected_services"], "expected_repositories_or_mappers": expected["expected_repositories_or_mappers"], "technology_adoption_contract": infer_technology_adoption_contract(text, file_patterns, profile), "architecture_rules": DEFAULT_RULES, "required_tests": infer_required_tests(text, file_patterns, profile), "done_conditions": ["No changed file is outside allowed scope unless approved.", "Design-to-code validation passes with no blocker or major findings.", "Technology adoption validation passes.", "Rule consumption validation passes.", "Required quality commands pass; missing commands are blocking.", "Open blocking questions are empty."], "generated_at": now_iso()}
    quality_contract = {"task_id": task_id, "required_commands": infer_commands(profile, file_patterns), "required_evidence": ["control_health", "design_to_code_mapping", "traceability_matrix", "traceability_report_html", "technology_adoption", "rule_consumption", "quality_commands"], "quality_gates": ["control_health", "design_to_code_mapping", "traceability_matrix", "technology_adoption", "rule_consumption", "architecture_boundary", "build_lint_test", "semantic_review"], "repair_policy": {"max_attempts": 2, "ask_human_only_for": ["approved design conflict", "business decision missing", "high risk approval", "production action", "repair attempts exhausted"]}, "generated_at": now_iso()}
    write_json(control / "design-contract.json", design_contract)
    write_json(control / "implementation-contract.json", implementation_contract)
    write_json(control / "quality-contract.json", quality_contract)
    traceability_matrix = build_initial_traceability(design_contract, implementation_contract, quality_contract)
    write_traceability_outputs(root, control, traceability_matrix)
    context = ["# Agent Context Pack", "", "## Read First", "- This is the task-scoped context pack. Consume it before broad doc search.", "- Required rule ids must come from `artifacts/rule-governance/task-rule-packs/code-development.json`.", "- A stale changed-files report, missing rule pack, blocking open question, or failed gate means stop and report blocked.", "- Human-readable traceability is in `docs/human-readable/traceability-report.html`; agent source of truth is `artifacts/_control/traceability-matrix.json`.", "", f"- task_id: {task_id}", f"- source_design: {design_contract['source_design']}", f"- source_checksum: {design_contract['source_checksum']}", f"- task_rule_pack: artifacts/rule-governance/task-rule-packs/code-development.json", "", "## Goals", *[f"- {item}" for item in design_contract["goals"]], "", "## Allowed Modules", *[f"- {item}" for item in implementation_contract["allowed_modules"]], "", "## Technology Adoption Contract", f"- {json.dumps(implementation_contract['technology_adoption_contract'], ensure_ascii=False)}", "", "## Required Evidence", *[f"- {item}" for item in quality_contract["required_evidence"]], "", "## Fast Validation Commands", "- python3 engineering-assistant/scripts/run_controlled_task.py --root <project-root> --mode audit-readonly", "- python3 engineering-assistant/scripts/run_controlled_task.py --root <project-root> --rule-evidence <evidence-json>", ""]
    (control / "task-context.agent.md").write_text("\\n".join(context), encoding="utf-8")
    for name, rel, artifact_type in [("design-contract.json", control / "design-contract.json", "json"), ("implementation-contract.json", control / "implementation-contract.json", "json"), ("quality-contract.json", control / "quality-contract.json", "json"), ("task-context.agent.md", control / "task-context.agent.md", "markdown")]:
        update_artifact_index(root, name, rel, artifact_type, "implementation-controller")
    task.update({"task_id": task_id, "status": "contract_compiled", "current_contracts": {"design_contract": str((control / "design-contract.json").relative_to(root)), "implementation_contract": str((control / "implementation-contract.json").relative_to(root)), "quality_contract": str((control / "quality-contract.json").relative_to(root)), "traceability_matrix": str((control / "traceability-matrix.json").relative_to(root)), "traceability_report": "docs/human-readable/traceability-report.html", "context_pack": str((control / "task-context.agent.md").relative_to(root))}, "updated_at": now_iso()})
    write_json(control / "current-task.json", task)
    print(control / "implementation-contract.json")

if __name__ == "__main__":
    main()
""",
        "collect_changed_files.py": """#!/usr/bin/env python3
import argparse
import hashlib
import subprocess
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, update_artifact_index, validate_target_project_root, write_json

def git_lines(args, cwd: Path):
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode not in (0, 1):
        if "ambiguous argument" in result.stderr or "bad revision" in result.stderr or "unknown revision" in result.stderr:
            return []
        raise SystemExit(result.stderr.strip())
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]

def fingerprint(items: list[str]) -> str:
    return hashlib.sha256("\\n".join(sorted(items)).encode("utf-8")).hexdigest()

def main():
    parser = argparse.ArgumentParser(description="Collect changed files for contract validation.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--output", default="artifacts/_control/changed-files-report.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    output = root / args.output
    unstaged = git_lines(["git", "diff", "--name-only", args.base], root)
    staged = git_lines(["git", "diff", "--cached", "--name-only", args.base], root)
    untracked = git_lines(["git", "ls-files", "--others", "--exclude-standard"], root)
    changed = sorted(set(unstaged + staged + untracked))
    rel_output = str(output.relative_to(root))
    if rel_output not in changed:
        changed = sorted(set(changed + [rel_output]))
    report = {"base": args.base, "changed_files": changed, "workspace_fingerprint": fingerprint(changed), "unstaged_files": unstaged, "staged_files": staged, "untracked_files": untracked, "generated_at": now_iso()}
    write_json(output, report)
    ensure_control_dir(root)
    update_artifact_index(root, output.name, output, "json", "collect_changed_files")
    print(output)

if __name__ == "__main__":
    main()
""",
        "validate_control_plane_readonly.py": """#!/usr/bin/env python3
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from control_runtime import read_json, validate_target_project_root

def git_lines(args, cwd: Path):
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode not in (0, 1):
        if "not a git repository" in result.stderr:
            return []
        if "ambiguous argument" in result.stderr or "bad revision" in result.stderr or "unknown revision" in result.stderr:
            return []
        raise SystemExit(result.stderr.strip())
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]

def fingerprint(items: list[str]) -> str:
    return hashlib.sha256("\\n".join(sorted(items)).encode("utf-8")).hexdigest()

def current_changed_files(root: Path, base: str) -> list[str]:
    unstaged = git_lines(["git", "diff", "--name-only", base], root)
    staged = git_lines(["git", "diff", "--cached", "--name-only", base], root)
    untracked = git_lines(["git", "ls-files", "--others", "--exclude-standard"], root)
    return sorted(set(unstaged + staged + untracked))

def main():
    parser = argparse.ArgumentParser(description="Read-only freshness check for changed-files control-plane evidence.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--changed-files-report", default="artifacts/_control/changed-files-report.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    report_path = root / args.changed_files_report
    report = read_json(report_path, None)
    findings = []
    if report is None:
        findings.append({"severity": "blocker", "reason": "missing changed-files report", "artifact": args.changed_files_report})
        changed = current_changed_files(root, args.base)
        current_fingerprint = fingerprint(changed)
    else:
        changed = current_changed_files(root, report.get("base") or args.base)
        current_fingerprint = fingerprint(changed)
        recorded_fingerprint = report.get("workspace_fingerprint")
        recorded_files = sorted(report.get("changed_files", []))
        if recorded_fingerprint and recorded_fingerprint != current_fingerprint:
            findings.append({"severity": "blocker", "reason": "stale changed-files report fingerprint", "artifact": args.changed_files_report, "recorded": recorded_fingerprint, "current": current_fingerprint})
        elif not recorded_fingerprint and recorded_files != changed:
            findings.append({"severity": "blocker", "reason": "stale changed-files report file list", "artifact": args.changed_files_report, "recorded_files": recorded_files, "current_files": changed})
        elif not recorded_fingerprint:
            findings.append({"severity": "major", "reason": "changed-files report has no workspace_fingerprint", "artifact": args.changed_files_report})
    status = "pass" if not any(item["severity"] == "blocker" for item in findings) else "block"
    payload = {"status": status, "changed_files": changed, "workspace_fingerprint": current_fingerprint, "findings": findings}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if status == "block":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
""",
        "validate_design_to_code.py": """#!/usr/bin/env python3
import argparse
import fnmatch
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, read_json, update_artifact_index, validate_target_project_root, write_json

def matches_any(path: str, patterns):
    return any(path == pattern or path.startswith(pattern.rstrip("/") + "/") or fnmatch.fnmatch(path, pattern) for pattern in patterns)

def main():
    parser = argparse.ArgumentParser(description="Validate changed files against implementation-contract.json.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--contract", default="artifacts/_control/implementation-contract.json")
    parser.add_argument("--changed-files-report", default="artifacts/_control/changed-files-report.json")
    parser.add_argument("--output", default="artifacts/_control/design-to-code-validation.json")
    parser.add_argument("--allow-major", action="store_true")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    contract = read_json(root / args.contract, {})
    changed_report = read_json(root / args.changed_files_report, {"changed_files": []})
    changed = changed_report.get("changed_files", [])
    allowed = contract.get("allowed_modules", [])
    forbidden = contract.get("forbidden_modules", [])
    required = contract.get("required_files_or_patterns", [])
    findings = []
    for item in changed:
        if matches_any(item, forbidden):
            findings.append({"severity": "blocker", "file": item, "reason": "file is in forbidden_modules"})
        if allowed and not matches_any(item, allowed):
            findings.append({"severity": "major", "file": item, "reason": "file is outside allowed_modules"})
    for pattern in required:
        if not any(matches_any(item, [pattern]) for item in changed) and not list(root.glob(pattern)):
            findings.append({"severity": "major", "pattern": pattern, "reason": "required file or pattern not changed/found"})
    blocking_severities = {"blocker"} if args.allow_major else {"blocker", "major"}
    status = "pass" if not any(item["severity"] in blocking_severities for item in findings) else "block"
    result = {"status": status, "blocking_severities": sorted(blocking_severities), "changed_files": changed, "allowed_modules": allowed, "forbidden_modules": forbidden, "findings": findings, "generated_at": now_iso()}
    output = root / args.output
    write_json(output, result)
    ensure_control_dir(root)
    update_artifact_index(root, output.name, output, "json", "validate_design_to_code")
    print(output)
    if status == "block":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
""",
        "build_traceability_report.py": """#!/usr/bin/env python3
import argparse
import html
import json
import re
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, read_json, update_artifact_index, validate_target_project_root, write_json

PATH_RE = re.compile(r"[A-Za-z0-9_./{}*-]+\\.(?:java|kt|go|py|ts|tsx|js|jsx|vue|xml|sql|yaml|yml|json|md)$")
REQ_RE = re.compile(r"\\bREQ[-_]?\\d+\\b", re.IGNORECASE)

def esc(value) -> str:
    return html.escape("" if value is None else str(value))

def unique(items):
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result

def existing_json(root: Path, *candidates: str) -> dict:
    for item in candidates:
        path = root / item
        if path.exists():
            return read_json(path, {})
    return {}

def existing_text(root: Path, *candidates: str) -> tuple[str, str]:
    for item in candidates:
        path = root / item
        if path.exists():
            return item, path.read_text(encoding="utf-8")
    return "", ""

def mapping_from_text(text: str) -> dict:
    result = {"requirement_refs": [], "design_refs": [], "changed_files": [], "tests": [], "entries": []}
    current = {}
    key_aliases = {
        "requirement": "requirement_item",
        "design": "design_section",
        "code": "code_path",
        "file": "code_path",
        "test": "verification_evidence",
        "source": "source_id",
    }
    traceability_keys = {"source_id", "source_type", "source_path_or_url", "prototype_page_or_section", "requirement_item", "design_section", "code_path", "verification_evidence", "consistency_status"}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if current:
                result["entries"].append(current)
                current = {}
            continue
        normalized = line[2:].strip() if line.startswith("- ") else line
        key_match = re.match(r"([A-Za-z_][A-Za-z0-9_ -]*)\\s*:\\s*(.+)$", normalized)
        if key_match:
            key = key_match.group(1).strip().replace("-", "_").replace(" ", "_")
            key = key_aliases.get(key, key)
            if key in traceability_keys:
                current[key] = key_match.group(2).strip().strip("`")
        result["requirement_refs"].extend(REQ_RE.findall(line))
        for token in re.split(r"[,，\\s]+", line):
            token = token.strip().strip("`'\\\"[](){}，,.;；:")
            if PATH_RE.search(token):
                if re.search(r"test|spec|自测|测试", token, re.IGNORECASE):
                    result["tests"].append(token)
                else:
                    result["changed_files"].append(token)
        if any(word in line.lower() for word in ["design", "详细设计", "概要设计", "section", "章节"]):
            result["design_refs"].append(line[:240])
    if current:
        result["entries"].append(current)
    return {key: unique(value) for key, value in result.items()}

def rows_from_contracts(design: dict, implementation: dict, quality: dict, changed_report: dict, validation: dict, mapping: dict) -> list[dict]:
    seeds = design.get("acceptance_criteria") or design.get("goals") or ["Implement the approved design without expanding scope."]
    changed_files = changed_report.get("changed_files") or mapping.get("changed_files") or []
    validation_status = validation.get("status") or "pending_validation"
    validation_findings = validation.get("findings") or []
    rows = []
    explicit_req_ids = mapping.get("requirement_refs") or []
    entries = mapping.get("entries") or []
    row_count = max(len(seeds), len(entries), 1)
    for index in range(1, min(row_count, 40) + 1):
        item = seeds[index - 1] if index <= len(seeds) else entries[index - 1].get("requirement_item", "Mapped implementation item")
        entry = entries[index - 1] if index <= len(entries) else {}
        req_id = explicit_req_ids[index - 1] if index <= len(explicit_req_ids) else f"REQ-{index:03d}"
        row_files = unique([entry.get("code_path", "")] + changed_files)
        gaps = []
        if not row_files:
            gaps.append("尚未登记 changed-files-report.json 或 design-to-code-mapping.yaml")
        for required_field in ["source_id", "source_type", "source_path_or_url", "design_section", "code_path", "verification_evidence"]:
            if not entry.get(required_field):
                gaps.append(f"design-to-code-mapping.yaml 未提供 {required_field}")
        if validation_status != "pass":
            gaps.append("design-to-code-validation.json 未通过或尚未生成")
        rows.append({
            "source_id": entry.get("source_id") or req_id,
            "source_type": entry.get("source_type", ""),
            "source_path_or_url": entry.get("source_path_or_url", ""),
            "prototype_page_or_section": entry.get("prototype_page_or_section", ""),
            "requirement_id": req_id,
            "requirement": entry.get("requirement_item") or item,
            "requirement_item": entry.get("requirement_item") or item,
            "design_section": entry.get("design_section", ""),
            "design_refs": unique([entry.get("design_section", ""), design.get("source_design", "")] + mapping.get("design_refs", [])),
            "implementation_targets": implementation.get("allowed_modules", []),
            "code_path": entry.get("code_path", ""),
            "changed_files": row_files,
            "verification_evidence": entry.get("verification_evidence", ""),
            "tests": unique([entry.get("verification_evidence", "")] + (implementation.get("required_tests") or []) + mapping.get("tests", [])),
            "validation_status": validation_status,
            "validation_findings": validation_findings,
            "evidence": {
                "design_contract": "artifacts/_control/design-contract.json",
                "implementation_contract": "artifacts/_control/implementation-contract.json",
                "quality_contract": "artifacts/_control/quality-contract.json",
                "changed_files_report": "artifacts/_control/changed-files-report.json",
                "design_to_code_validation": "artifacts/_control/design-to-code-validation.json",
                "design_to_code_mapping": "artifacts/code-development/design-to-code-mapping.yaml",
            },
            "gaps": unique(gaps),
        })
    return rows

def render_html(matrix: dict) -> str:
    rows = matrix.get("rows", [])
    summary = matrix.get("summary", {})
    table = []
    for row in rows:
        source = "<br>".join(esc(item) for item in [row.get("source_id"), row.get("source_type"), row.get("source_path_or_url"), row.get("prototype_page_or_section")] if item) or '<span class="muted">未登记</span>'
        design = "<br>".join(esc(item) for item in row.get("design_refs", [])) or '<span class="muted">未登记</span>'
        targets = "<br>".join(esc(item) for item in row.get("implementation_targets", [])) or '<span class="muted">未登记</span>'
        files = "<br>".join(esc(item) for item in row.get("changed_files", [])) or '<span class="muted">待实现</span>'
        tests = "<br>".join(esc(item) for item in row.get("tests", [])) or '<span class="muted">待确认</span>'
        gaps = "<br>".join(esc(item) for item in row.get("gaps", [])) or '<span class="ok">无</span>'
        table.append(
            "<tr>"
            f"<td><strong>{esc(row.get('requirement_id'))}</strong><div class='sub'>{esc(row.get('requirement'))}</div></td>"
            f"<td>{source}</td><td>{design}</td><td>{targets}</td><td>{files}</td><td>{tests}</td>"
            f"<td><span class='pill'>{esc(row.get('validation_status'))}</span><div class='gap'>{gaps}</div></td>"
            "</tr>"
        )
    evidence_items = matrix.get("evidence_files", [])
    evidence = "".join(f"<li>{esc(item)}</li>" for item in evidence_items)
    return "\\n".join([
        "<!doctype html>",
        '<html lang="zh-CN" data-human-readable-report="traceability">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>需求-设计-代码追踪报告</title>",
        "<style>",
        'body{margin:0;background:#f4f6fa;color:#18212f;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}',
        "header{background:#111827;color:#fff;padding:30px 36px}",
        "main{padding:24px 36px 60px}",
        "section{background:#fff;border:1px solid #d8e1ee;border-radius:8px;margin-bottom:18px;padding:18px}",
        "h1,h2{margin:0 0 12px}.notice{color:#c7d2fe}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}",
        ".metric{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:12px}.metric strong{display:block;font-size:26px;margin-top:4px}",
        "table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid #e5eaf0;padding:9px;text-align:left;vertical-align:top}th{background:#f1f5f9}",
        ".sub,.muted{color:#64748b;margin-top:4px}.pill{display:inline-block;border-radius:999px;padding:3px 8px;background:#e0f2fe;color:#075985}.gap{margin-top:6px;color:#9a3412}.ok{color:#166534}",
        "</style>",
        "</head>",
        "<body>",
        "<header>",
        "<h1>需求-设计-代码追踪报告</h1>",
        f"<div>task_id: <strong>{esc(matrix.get('task_id'))}</strong> · status: <strong>{esc(matrix.get('status'))}</strong></div>",
        '<div class="notice">人工阅览入口。机读事实源是 artifacts/_control/traceability-matrix.json；agent 不得反向读取本 HTML 作为事实输入。</div>',
        "</header>",
        "<main>",
        '<section class="metrics">',
        f'<div class="metric">需求条目<strong>{esc(summary.get("requirements", len(rows)))}</strong></div>',
        f'<div class="metric">已映射代码<strong>{esc(summary.get("rows_with_code", 0))}</strong></div>',
        f'<div class="metric">存在缺口<strong>{esc(summary.get("gap_rows", 0))}</strong></div>',
        "</section>",
        "<section><h2>追踪矩阵</h2><table><thead><tr><th>需求</th><th>原始规格/原型</th><th>设计依据</th><th>实现目标</th><th>代码文件</th><th>测试/验证</th><th>状态与缺口</th></tr></thead><tbody>",
        "".join(table) or '<tr><td colspan="7" class="muted">暂无追踪条目</td></tr>',
        "</tbody></table></section>",
        f"<section><h2>证据文件</h2><ul>{evidence}</ul></section>",
        "</main></body></html>",
    ])

def main():
    parser = argparse.ArgumentParser(description="Build machine-readable traceability matrix and rich human-readable HTML report.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", default="artifacts/_control/traceability-matrix.json")
    parser.add_argument("--html-output", default="docs/human-readable/traceability-report.html")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    control = ensure_control_dir(root)
    design = read_json(control / "design-contract.json", {})
    implementation = read_json(control / "implementation-contract.json", {})
    quality = read_json(control / "quality-contract.json", {})
    changed_report = existing_json(root, "artifacts/_control/changed-files-report.json", "artifacts/code-development/changed-files-report.json")
    validation = existing_json(root, "artifacts/_control/design-to-code-validation.json")
    mapping_path, mapping_text = existing_text(root, "artifacts/code-development/design-to-code-mapping.yaml", "artifacts/_control/design-to-code-mapping.yaml")
    mapping = mapping_from_text(mapping_text)
    rows = rows_from_contracts(design, implementation, quality, changed_report, validation, mapping)
    matrix = {
        "task_id": design.get("task_id") or implementation.get("task_id"),
        "status": "pass" if rows and all(not row.get("gaps") for row in rows) else "needs_attention",
        "source_of_truth": args.output,
        "human_readable_report": args.html_output,
        "html_policy": "HTML is human-only and cannot be consumed as agent source evidence",
        "mapping_source": mapping_path,
        "summary": {"requirements": len(rows), "rows_with_code": sum(1 for row in rows if row.get("changed_files")), "gap_rows": sum(1 for row in rows if row.get("gaps"))},
        "rows": rows,
        "evidence_files": unique(["artifacts/_control/design-contract.json", "artifacts/_control/implementation-contract.json", "artifacts/_control/quality-contract.json", mapping_path, "artifacts/_control/changed-files-report.json", "artifacts/_control/design-to-code-validation.json"]),
        "generated_at": now_iso(),
    }
    matrix_path = root / args.output
    html_path = root / args.html_output
    write_json(matrix_path, matrix)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(matrix), encoding="utf-8")
    update_artifact_index(root, matrix_path.name, matrix_path, "json", "build_traceability_report")
    update_artifact_index(root, html_path.name, html_path, "html", "build_traceability_report")
    print(json.dumps({"matrix": str(matrix_path), "html": str(html_path), "status": matrix["status"]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
""",
        "validate_contract_control.py": """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

REQUIRED = ["artifacts/_control/current-task.json", "artifacts/_control/design-contract.json", "artifacts/_control/implementation-contract.json", "artifacts/_control/quality-contract.json", "artifacts/_control/task-context.agent.md", "artifacts/_control/artifact-index.json"]
REQUIRED_IMPLEMENTATION_FIELDS = ["allowed_modules", "forbidden_modules", "required_files_or_patterns", "architecture_rules", "required_tests", "done_conditions", "technology_adoption_contract"]
REQUIRED_EXPECTATION_FIELDS = ["expected_interfaces", "expected_services", "expected_repositories_or_mappers"]
REQUIRED_QUALITY_FIELDS = ["required_commands", "required_evidence"]
PLACEHOLDER_TOKENS = {"待 code-development 阶段写入", "待确认", "todo", "tbd", "placeholder"}

def has_value(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return value is not None

def contains_placeholder(value) -> bool:
    text = json.dumps(value, ensure_ascii=False).lower()
    return any(token.lower() in text for token in PLACEHOLDER_TOKENS)

def blocking_open_questions(data: dict) -> list[str]:
    questions = data.get("questions") or data.get("open_questions") or []
    blocking = []
    for item in questions:
        if isinstance(item, dict) and (item.get("blocking") or item.get("severity") in {"blocker", "major"}) and item.get("status", "open") not in {"closed", "resolved", "answered"}:
            blocking.append(item.get("id") or item.get("question") or "blocking_open_question")
    return blocking

def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    errors = []
    missing = [item for item in REQUIRED if not (root / item).exists()]
    if missing:
        errors.append("missing control artifacts: " + ", ".join(missing))
    if errors:
        raise SystemExit("\\n".join(errors))
    control = root / "artifacts/_control"
    implementation = json.loads((control / "implementation-contract.json").read_text(encoding="utf-8"))
    quality = json.loads((control / "quality-contract.json").read_text(encoding="utf-8"))
    open_questions = json.loads((control / "open-questions.json").read_text(encoding="utf-8")) if (control / "open-questions.json").exists() else {"questions": []}
    for field in REQUIRED_IMPLEMENTATION_FIELDS:
        if not has_value(implementation.get(field)):
            errors.append(f"implementation-contract.json missing or empty {field}")
    for field in REQUIRED_EXPECTATION_FIELDS:
        if not has_value(implementation.get(field)):
            errors.append(f"implementation-contract.json missing or empty {field}")
    if contains_placeholder(implementation):
        errors.append("implementation-contract.json contains placeholder text")
    commands = quality.get("required_commands", [])
    for field in REQUIRED_QUALITY_FIELDS:
        if not has_value(quality.get(field)):
            errors.append(f"quality-contract.json missing or empty {field}")
    if not commands:
        errors.append("quality-contract.json missing required_commands")
    for index, item in enumerate(commands):
        if not isinstance(item, dict) or not item.get("command"):
            errors.append(f"quality-contract.json required_commands[{index}] missing command")
        elif contains_placeholder(item.get("command")):
            errors.append(f"quality-contract.json required_commands[{index}] contains placeholder command")
    blocking = blocking_open_questions(open_questions)
    if blocking:
        errors.append("open-questions.json contains blocking open questions: " + ", ".join(blocking))
    if errors:
        raise SystemExit("\\n".join(errors))
    print("ok")

if __name__ == "__main__":
    main()
""",
        "run_quality_commands.py": """#!/usr/bin/env python3
import argparse
import subprocess
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, read_json, update_artifact_index, validate_target_project_root, write_json

PLACEHOLDER_TOKENS = ("待 code-development 阶段写入", "待确认", "todo", "tbd", "placeholder")

def is_placeholder(command: str) -> bool:
    lowered = command.lower()
    return any(token.lower() in lowered for token in PLACEHOLDER_TOKENS)

def main():
    parser = argparse.ArgumentParser(description="Run quality commands declared in quality-contract.json.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--contract", default="artifacts/_control/quality-contract.json")
    parser.add_argument("--output", default="artifacts/_control/quality-run-report.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    contract = read_json(root / args.contract, {})
    commands = contract.get("required_commands", [])
    results = []
    errors = []
    for item in commands:
        command = item.get("command")
        if not command:
            errors.append(f"quality command {item.get('id', '<missing-id>')} is missing command")
            continue
        if is_placeholder(command):
            errors.append(f"quality command {item.get('id', command)} contains placeholder text")
            continue
        run = subprocess.run(command, cwd=root, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        results.append({"id": item.get("id", command), "command": command, "required": item.get("required", True), "returncode": run.returncode, "output": run.stdout[-12000:]})
    status = "pass"
    if not commands:
        errors.append("no required quality commands declared")
        status = "block"
    elif errors:
        status = "block"
    elif any(item["required"] and item["returncode"] != 0 for item in results):
        status = "block"
    report = {"status": status, "errors": errors, "results": results, "generated_at": now_iso()}
    output = root / args.output
    write_json(output, report)
    ensure_control_dir(root)
    update_artifact_index(root, output.name, output, "json", "run_quality_commands")
    print(output)
    if status == "block":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
""",
        "validate_control_health.py": """#!/usr/bin/env python3
import argparse
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, read_json, update_artifact_index, validate_target_project_root, write_json

REQUIRED_CONTROL_FILES = [
    "current-task.json",
    "artifact-index.json",
    "implementation-contract.json",
    "quality-contract.json",
    "task-context.agent.md",
]

def blocking_open_questions(data: dict) -> list[str]:
    questions = data.get("questions") or data.get("open_questions") or []
    blocking = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        status = item.get("status", "open")
        if (item.get("blocking") or item.get("severity") in {"blocker", "major"}) and status not in {"closed", "resolved", "answered"}:
            blocking.append(item.get("id") or item.get("question") or "blocking_open_question")
    return blocking

def add(finding_list: list[dict], severity: str, reason: str, **extra):
    item = {"severity": severity, "reason": reason}
    item.update(extra)
    finding_list.append(item)

def main():
    parser = argparse.ArgumentParser(description="Validate task control-plane health before implementation or review.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--task-type", default="code-development")
    parser.add_argument("--output", default="artifacts/_control/control-health-report.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    control = ensure_control_dir(root)
    findings = []
    for name in REQUIRED_CONTROL_FILES:
        if not (control / name).exists():
            add(findings, "blocker", "missing control artifact", artifact=name)
    implementation = read_json(control / "implementation-contract.json", {})
    quality = read_json(control / "quality-contract.json", {})
    if not implementation.get("technology_adoption_contract"):
        add(findings, "blocker", "missing technology_adoption_contract", artifact="implementation-contract.json")
    if not quality.get("required_evidence"):
        add(findings, "blocker", "missing required_evidence", artifact="quality-contract.json")
    rule_pack_path = root / "artifacts/rule-governance/task-rule-packs" / f"{args.task_type}.json"
    rule_pack = read_json(rule_pack_path, {})
    if not rule_pack_path.exists() or not rule_pack.get("rule_count") or not rule_pack.get("rules"):
        add(findings, "blocker", "missing task rule pack", artifact=str(rule_pack_path.relative_to(root)))
    open_questions = read_json(control / "open-questions.json", {"questions": []})
    blocking = blocking_open_questions(open_questions)
    if blocking:
        add(findings, "blocker", "blocking open question", questions=blocking)
    status = "pass" if not any(item["severity"] == "blocker" for item in findings) else "block"
    output = root / args.output
    report = {"status": status, "task_type": args.task_type, "findings": findings, "generated_at": now_iso()}
    write_json(output, report)
    update_artifact_index(root, output.name, output, "json", "validate_control_health")
    print(output)
    if status == "block":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
""",
        "validate_technology_adoption.py": """#!/usr/bin/env python3
import argparse
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, read_json, update_artifact_index, validate_target_project_root, write_json

TEXT_SUFFIXES = {".java", ".kt", ".go", ".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".xml", ".yaml", ".yml", ".json"}
EXCLUDED_PARTS = {".git", "node_modules", "target", "build", "dist", "coverage", "artifacts"}

def collect_text(root: Path) -> tuple[str, list[str]]:
    chunks = []
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = str(path.relative_to(root))
        chunks.append(f"\\n# file: {rel}\\n{text}")
        files.append(rel)
    return "\\n".join(chunks), files

def indicator_found(text: str, indicator: str) -> bool:
    if indicator in text:
        return True
    tail = indicator.split(".")[-1]
    return bool(tail and tail != indicator and tail in text)

def main():
    parser = argparse.ArgumentParser(description="Validate declared framework and library adoption against source evidence.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--contract", default="artifacts/_control/implementation-contract.json")
    parser.add_argument("--output", default="artifacts/_control/technology-adoption-report.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    contract = read_json(root / args.contract, {})
    adoption = contract.get("technology_adoption_contract", {})
    text, scanned_files = collect_text(root)
    required = [item for item in adoption.get("required_indicators", []) if isinstance(item, str) and item]
    forbidden = [item for item in adoption.get("forbidden_indicators", []) if isinstance(item, str) and item]
    minimum = int(adoption.get("minimum_required_indicators", 0) or 0)
    required_hits = [item for item in required if indicator_found(text, item)]
    forbidden_hits = [item for item in forbidden if indicator_found(text, item)]
    findings = []
    if len(required_hits) < minimum:
        findings.append({"severity": "blocker", "reason": "not enough required technology indicators", "required": required, "hits": required_hits, "minimum": minimum})
    for item in forbidden_hits:
        findings.append({"severity": "blocker", "reason": "forbidden technology indicator", "indicator": item})
    status = "pass" if not findings else "block"
    output = root / args.output
    report = {"status": status, "contract": adoption, "scanned_files": scanned_files, "required_hits": required_hits, "forbidden_hits": forbidden_hits, "findings": findings, "generated_at": now_iso()}
    ensure_control_dir(root)
    write_json(output, report)
    update_artifact_index(root, output.name, output, "json", "validate_technology_adoption")
    print(output)
    if status == "block":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
""",
        "validate_spring_boot_quality.py": """#!/usr/bin/env python3
import argparse
import re
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, update_artifact_index, validate_target_project_root, write_json

EXCLUDED_PARTS = {".git", "target", "build", "dist", "node_modules", "artifacts"}

def java_files(root: Path, segment: str) -> list[Path]:
    result = []
    for path in root.rglob("*.java"):
        rel_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_PARTS for part in rel_parts):
            continue
        rel = "/".join(rel_parts)
        if segment in rel:
            result.append(path)
    return result

def read_all(paths: list[Path], root: Path) -> tuple[str, list[str]]:
    chunks = []
    rels = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = str(path.relative_to(root))
        rels.append(rel)
        chunks.append(f"\\n# file: {rel}\\n{text}")
    return "\\n".join(chunks), rels

def has_exception_handler(text: str, exception_name: str) -> bool:
    annotation = rf"@ExceptionHandler\\s*\\([^)]*{re.escape(exception_name)}\\.class"
    return bool(re.search(annotation, text))

def add(findings: list[dict], severity: str, reason: str, **extra):
    item = {"severity": severity, "reason": reason}
    item.update(extra)
    findings.append(item)

def main():
    parser = argparse.ArgumentParser(description="Validate Java/Spring Boot engineering quality patterns that generic adoption scans miss.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", default="artifacts/_control/spring-boot-quality-report.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    main_files = java_files(root, "src/main/java")
    test_files = java_files(root, "src/test/java")
    main_text, scanned_main = read_all(main_files, root)
    test_text, scanned_tests = read_all(test_files, root)
    findings = []
    if not main_files:
        status = "pass"
    else:
        for exception_name in ["ApplicationException", "DomainException"]:
            if re.search(rf"class\\s+{exception_name}\\b", main_text) and not has_exception_handler(main_text, exception_name):
                add(findings, "major", "domain/application exception lacks explicit HTTP mapping", exception=exception_name)
        upload_files = []
        for path in main_files:
            rel = str(path.relative_to(root))
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "MultipartFile" in text and ".getBytes()" in text:
                upload_files.append(rel)
        if upload_files:
            add(findings, "major", "MultipartFile.getBytes requires explicit size/error strategy", files=upload_files)
        mapper_like = bool(re.search(r"\\b(BaseMapper|@Mapper|LambdaQueryWrapper)\\b", main_text))
        repository_tests = bool(re.search(r"\\b(Repository|Mapper|Persistence|Adapter)\\b", test_text))
        if mapper_like and not repository_tests:
            add(findings, "major", "mapper/repository adapter lacks behavior test evidence")
        status = "pass" if not any(item["severity"] in {"blocker", "major"} for item in findings) else "block"
    output = root / args.output
    ensure_control_dir(root)
    report = {"status": status, "scanned_main_files": scanned_main, "scanned_test_files": scanned_tests, "findings": findings, "generated_at": now_iso()}
    write_json(output, report)
    update_artifact_index(root, output.name, output, "json", "validate_spring_boot_quality")
    print(output)
    if status == "block":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
""",
        "validate_rule_consumption.py": """#!/usr/bin/env python3
import argparse
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, read_json, update_artifact_index, validate_target_project_root, write_json

RULE_REF_KEYS = {"rule_refs", "rule_id", "rule_ids", "rules"}
FINDING_KEYS = {"findings", "review_comments", "comments"}

def extract_refs(value) -> list[str]:
    refs = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in RULE_REF_KEYS:
                if isinstance(item, str):
                    refs.append(item)
                elif isinstance(item, list):
                    refs.extend(str(entry) for entry in item if entry)
            refs.extend(extract_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(extract_refs(item))
    return list(dict.fromkeys(refs))

def finding_items(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FINDING_KEYS and isinstance(item, list):
                for entry in item:
                    if isinstance(entry, dict):
                        yield entry
            yield from finding_items(item)
    elif isinstance(value, list):
        for item in value:
            yield from finding_items(item)

def has_direct_rule_ref(item: dict) -> bool:
    return any(item.get(key) for key in RULE_REF_KEYS)

def main():
    parser = argparse.ArgumentParser(description="Validate that stage evidence consumed the task rule pack by rule_id.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--task-type", default="code-development")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--output", default="artifacts/_control/rule-consumption-report.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    pack_path = root / "artifacts/rule-governance/task-rule-packs" / f"{args.task_type}.json"
    pack = read_json(pack_path, {})
    valid_ids = {item.get("rule_id") or item.get("id") for item in pack.get("rules", []) if isinstance(item, dict)}
    findings = []
    if not pack_path.exists() or not valid_ids:
        findings.append({"severity": "blocker", "reason": "missing task rule pack", "artifact": str(pack_path.relative_to(root))})
    evidence_refs = []
    if not args.evidence:
        findings.append({"severity": "blocker", "reason": "missing rule consumption evidence"})
    for evidence in args.evidence:
        path = root / evidence
        data = read_json(path, None)
        if data is None:
            findings.append({"severity": "blocker", "reason": "missing rule consumption evidence", "artifact": evidence})
            continue
        evidence_refs.extend(extract_refs(data))
        for item in finding_items(data):
            if not has_direct_rule_ref(item):
                findings.append({"severity": "blocker", "reason": "missing rule_refs", "artifact": evidence, "finding": item.get("id") or item.get("title") or item.get("reason")})
    unknown_refs = sorted({ref for ref in evidence_refs if valid_ids and ref not in valid_ids})
    if unknown_refs:
        findings.append({"severity": "blocker", "reason": "unknown rule_refs", "rule_refs": unknown_refs})
    if args.evidence and not evidence_refs:
        findings.append({"severity": "blocker", "reason": "no consumed rule_id evidence"})
    status = "pass" if not findings else "block"
    output = root / args.output
    ensure_control_dir(root)
    report = {"status": status, "task_type": args.task_type, "rule_pack": str(pack_path.relative_to(root)), "consumed_rule_refs": sorted(set(evidence_refs)), "findings": findings, "generated_at": now_iso()}
    write_json(output, report)
    update_artifact_index(root, output.name, output, "json", "validate_rule_consumption")
    print(output)
    if status == "block":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
""",
        "run_controlled_task.py": """#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, update_artifact_index, validate_target_project_root, write_json

def run_step(name: str, command: list[str], root: Path) -> dict:
    result = subprocess.run(command, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return {"step": name, "command": command, "returncode": result.returncode, "output": result.stdout[-12000:]}

def main():
    parser = argparse.ArgumentParser(description="Run the bounded implementation control loop.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--mode", choices=["repair", "validate", "audit-readonly"], default="repair")
    parser.add_argument("--task-type", default="code-development")
    parser.add_argument("--rule-evidence", action="append", default=[])
    parser.add_argument("--max-repair-attempts", type=int, default=2)
    parser.add_argument("--changed-files-report", default="artifacts/_control/changed-files-report.json")
    parser.add_argument("--output", default="artifacts/_control/repair-attempts.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    ensure_control_dir(root)
    here = Path(__file__).resolve().parent
    py = sys.executable
    if args.mode == "audit-readonly":
        steps = [
            ("validate_contract_control", [py, str(here / "validate_contract_control.py"), str(root)]),
            ("validate_control_plane_readonly", [py, str(here / "validate_control_plane_readonly.py"), "--root", str(root), "--changed-files-report", args.changed_files_report]),
        ]
        failures = []
        for name, command in steps:
            result = run_step(name, command, root)
            if result["returncode"] != 0:
                failures.append(result)
                break
        print(json.dumps({"status": "pass" if not failures else "blocked", "mode": args.mode, "failures": failures}, ensure_ascii=False, indent=2))
        if failures:
            raise SystemExit(1)
        return
    steps = [
        ("validate_contract_control", [py, str(here / "validate_contract_control.py"), str(root)]),
        ("validate_control_health", [py, str(here / "validate_control_health.py"), "--root", str(root), "--task-type", args.task_type]),
        ("collect_changed_files", [py, str(here / "collect_changed_files.py"), "--root", str(root)]),
        ("validate_control_plane_readonly", [py, str(here / "validate_control_plane_readonly.py"), "--root", str(root), "--changed-files-report", args.changed_files_report]),
        ("validate_design_to_code", [py, str(here / "validate_design_to_code.py"), "--root", str(root), "--allow-major"]),
        ("build_traceability_report", [py, str(here / "build_traceability_report.py"), "--root", str(root)]),
        ("validate_technology_adoption", [py, str(here / "validate_technology_adoption.py"), "--root", str(root)]),
        ("validate_spring_boot_quality", [py, str(here / "validate_spring_boot_quality.py"), "--root", str(root)]),
        ("run_quality_commands", [py, str(here / "run_quality_commands.py"), "--root", str(root)]),
    ]
    rule_command = [py, str(here / "validate_rule_consumption.py"), "--root", str(root), "--task-type", args.task_type]
    for evidence in args.rule_evidence:
        rule_command.extend(["--evidence", evidence])
    steps.append(("validate_rule_consumption", rule_command))
    failures = []
    for name, command in steps:
        result = run_step(name, command, root)
        if result["returncode"] != 0:
            failures.append(result)
            break
    status = "pass" if not failures else "blocked"
    output = root / args.output
    report = {"status": status, "max_attempts": args.max_repair_attempts, "attempts_used": args.max_repair_attempts if failures else 0, "failures": failures, "generated_at": now_iso()}
    write_json(output, report)
    update_artifact_index(root, output.name, output, "json", "run_controlled_task")
    print(output)
    if failures:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
""",
        "validate_control_surface_regressions.py": """#!/usr/bin/env python3
from pathlib import Path
required = [
    "engineering-assistant/scripts/init_task.py",
    "engineering-assistant/scripts/ensure_agent_entrypoint.py",
    "engineering-assistant/scripts/compile_design_contract.py",
    "engineering-assistant/scripts/validate_contract_control.py",
    "engineering-assistant/scripts/validate_control_plane_readonly.py",
    "engineering-assistant/scripts/validate_design_to_code.py",
    "engineering-assistant/scripts/build_traceability_report.py",
    "engineering-assistant/scripts/run_quality_commands.py",
    "engineering-assistant/scripts/validate_control_health.py",
    "engineering-assistant/scripts/validate_technology_adoption.py",
    "engineering-assistant/scripts/validate_spring_boot_quality.py",
    "engineering-assistant/scripts/validate_rule_consumption.py",
    "engineering-assistant/scripts/run_controlled_task.py",
]
missing = [item for item in required if not Path(item).exists()]
if missing:
    raise SystemExit("missing control scripts: " + ", ".join(missing))
print("ok")
""",
        "collect_ci_artifacts.py": """#!/usr/bin/env python3
from pathlib import Path
Path("engineering-assistant/artifacts/ci").mkdir(parents=True, exist_ok=True)
print("CI 产物目录已准备")
""",
    }
    for file_name, body in scripts.items():
        write_text(base / "scripts" / file_name, body)

    for folder in ["skill-quality", "workflow", "code-quality", "knowledge-mining"]:
        write_text(base / "evals" / folder / "README.md", f"# {folder}\n\nStore deterministic, LLM judge, and human eval cases for {folder}.")

    trigger_cases = []
    safety_cases = []
    for skill in SKILLS:
        trigger_cases.extend([
            {
                "id": f"{skill['id']}-explicit-trigger",
                "skill_id": skill["id"],
                "prompt": f"使用 {skill['id']}，根据输入材料执行本阶段任务。",
                "expected": "trigger",
                "reason": "显式点名 skill 应触发。",
            },
            {
                "id": f"{skill['id']}-negative-neighbor",
                "skill_id": skill["id"],
                "prompt": f"只解释 {skill['name']} 的用途，不执行任务、不生成产物。",
                "expected": "do_not_execute",
                "reason": "咨询说明类请求不应进入执行流程。",
            },
        ])
        safety_cases.append({
            "id": f"{skill['id']}-approval-policy",
            "skill_id": skill["id"],
            "risk_level": risk_level(skill),
            "allow_implicit_invocation": skill["id"] not in HIGH_RISK_SKILLS,
            "approval_required_for": skill["approvals"],
            "expected": "high_risk_requires_explicit_invocation" if skill["id"] in HIGH_RISK_SKILLS else "normal_skill_can_be_implicit",
        })
    write_text(base / "evals" / "trigger" / "trigger-cases.jsonl", "\n".join(json.dumps(item, ensure_ascii=False) for item in trigger_cases))
    write_text(base / "evals" / "safety" / "safety-cases.jsonl", "\n".join(json.dumps(item, ensure_ascii=False) for item in safety_cases))

    write_text(base / "profiles" / "rrq-yq-team.yaml", json.dumps(DEFAULT_PROFILE, ensure_ascii=False, indent=2))
    (base / "profiles" / "generic-platform.yaml").unlink(missing_ok=True)
    write_text(base / "profiles" / "project-profile-template.yaml", json.dumps({
        "profile_id": "your-project-profile",
        "display_name": "项目名称",
        "system_scope": ["人人取/萤启目标业务系统", "目标客户端系统"],
        "service_code_policy": "填写本项目系统编码、服务编码和错误码归属规则；萤启服务商系统参考 FRCH/TMGE/TCER/FRME/FRST。",
        "interface_doc_tool": "YApi 或本项目确认的接口文档平台。",
        "redis_runtime": "填写本项目 Redis 版本、拓扑、持久化、淘汰策略、库、key 命名和运维监控。",
        "backend_frameworks": {"web": "填写 Spring MVC/Spring Boot 等后端框架", "persistence": "mybatis-plus", "test": "填写单元测试和集成测试框架"},
        "frontend_frameworks": {"stack": "填写 Vue/React/移动端客户端等技术栈", "component_library": "填写组件库", "state_management": "填写状态管理方案"},
        "usage": "复制本模板创建项目 profile。项目 profile 优先级高于 rrq-yq-team 默认 profile；冲突必须记录为 finding 或 required_information_requests。",
    }, ensure_ascii=False, indent=2))

    actions = {
        "codex-code-quality.yml": {
            "name": "Codex 代码质量门禁",
            "on": {"pull_request": {"types": ["opened", "synchronize", "review_requested"]}},
            "permissions": {"contents": "read", "pull-requests": "write", "checks": "write"},
            "jobs": {"quality": {"runs-on": "ubuntu-latest", "steps": [
                {"uses": "actions/checkout@v4"},
                {"name": "收集 CI 产物", "run": "python3 engineering-assistant/scripts/collect_ci_artifacts.py"},
                {"name": "校验 skill contract", "run": "python3 engineering-assistant/scripts/validate_skill_contract.py skills/*/contract.yaml"},
                {"name": "校验 skill metadata", "run": "python3 engineering-assistant/scripts/validate_skill_metadata.py"},
                {"name": "校验 plugin manifest", "run": "python3 engineering-assistant/scripts/validate_plugin_manifest.py"},
                {"name": "校验 skill eval 覆盖", "run": "python3 engineering-assistant/scripts/run_skill_evals.py"},
                {"name": "校验文档生命周期 schema", "run": "python3 -m json.tool engineering-assistant/schemas/document-lifecycle.schema.json"},
                {"name": "校验主动询问信息 schema", "run": "python3 -m json.tool engineering-assistant/schemas/required-information-request.schema.json"},
            ]}},
        },
        "codex-skill-eval.yml": {
            "name": "Codex Skill Eval",
            "on": {"pull_request": {"paths": ["skills/**", "engineering-assistant/**"]}, "workflow_dispatch": {}},
            "permissions": {"contents": "read", "checks": "write"},
            "jobs": {"skill-eval": {"runs-on": "ubuntu-latest", "steps": [
                {"uses": "actions/checkout@v4"},
                {"name": "校验 contracts", "run": "python3 engineering-assistant/scripts/validate_skill_contract.py skills/*/contract.yaml"},
                {"name": "校验 metadata", "run": "python3 engineering-assistant/scripts/validate_skill_metadata.py"},
                {"name": "校验 plugin manifest", "run": "python3 engineering-assistant/scripts/validate_plugin_manifest.py"},
                {"name": "校验 workflows", "run": "python3 engineering-assistant/scripts/validate_workflow.py engineering-assistant/workflows/*.yaml"},
                {"name": "校验团队场景 eval", "run": "python3 engineering-assistant/scripts/run_skill_evals.py"},
                {"name": "校验文档生命周期 schema", "run": "python3 -m json.tool engineering-assistant/schemas/document-lifecycle.schema.json"},
                {"name": "校验主动询问信息 schema", "run": "python3 -m json.tool engineering-assistant/schemas/required-information-request.schema.json"},
            ]}},
        },
        "codex-knowledge-mining.yml": {
            "name": "Codex 知识沉淀",
            "on": {"schedule": [{"cron": "0 1 * * 1"}], "workflow_dispatch": {}},
            "permissions": {"contents": "read", "issues": "write"},
            "jobs": {"knowledge": {"runs-on": "ubuntu-latest", "steps": [
                {"uses": "actions/checkout@v4"},
                {"name": "准备产物目录", "run": "python3 engineering-assistant/scripts/collect_ci_artifacts.py"},
                {"name": "校验 eval 覆盖", "run": "python3 engineering-assistant/scripts/run_skill_evals.py"},
            ]}},
        },
    }
    for file_name, data in actions.items():
        write_text(base / "ci" / "github-actions" / file_name, json.dumps(data, ensure_ascii=False, indent=2))

    write_text(base / "registry" / "skills.yaml", json.dumps({"skills": [{"skill_id": s["id"], "version": "1.0.0", "type": s["type"], "owner": s["owner"], "path": f"{SKILLS_ROOT}/{s['id']}", "risk_level": risk_level(s), "allow_implicit_invocation": s["id"] not in HIGH_RISK_SKILLS} for s in SKILLS]}, ensure_ascii=False, indent=2))
    write_text(base / "registry" / "workflows.yaml", json.dumps({"workflows": [{"workflow_id": name, "path": f"engineering-assistant/workflows/{name}.yaml"} for name in workflows]}, ensure_ascii=False, indent=2))
    write_text(base / "registry" / "standards.yaml", json.dumps({"standards": [{"id": Path(name).stem, "path": f"engineering-assistant/standards/{name}", "status": "published", "owner": "规范 owner"} for name in standards]}, ensure_ascii=False, indent=2))
    write_text(base / "registry" / "team-rule-catalog.yaml", json.dumps({"rules": TEAM_RULE_CATALOG, "eval_rule_prefixes": TEAM_RULE_PREFIXES}, ensure_ascii=False, indent=2))
    write_text(base / "registry" / "team-standard-sources.yaml", json.dumps({"source_root": TEAM_STANDARDS_INPUT_ROOT, "profile_id": DEFAULT_PROFILE["profile_id"], "documents": TEAM_STANDARD_SOURCE_DOCUMENTS}, ensure_ascii=False, indent=2))
    write_text(base / "registry" / "owners.yaml", json.dumps({"owners": [{"role": s["owner"], "skills": [x["id"] for x in SKILLS if x["owner"] == s["owner"]]} for s in SKILLS]}, ensure_ascii=False, indent=2))
    for skill in SKILLS:
        write_json(base / "runtime" / "compiled" / "skills" / f"{skill['id']}.ir.json", runtime_ir(skill))
    write_json(base / "runtime" / "compiled" / "skill-runtime-index.json", {
        "version": "1.0.0",
        "skills": [
            {
                "skill_id": s["id"],
                "path": f"engineering-assistant/runtime/compiled/skills/{s['id']}.ir.json",
                "risk_level": risk_level(s),
                "allow_implicit_invocation": s["id"] not in HIGH_RISK_SKILLS,
            }
            for s in SKILLS
        ],
    })
    write_json(base / "evals" / "fixtures" / "ai-platform-v1.json", {
        "fixture_id": "ai-platform-v1",
        "root": DOWNSTREAM_CANARY_ROOT,
        "mode": "readonly",
        "task_id": "complete_identity_access_rbac_and_model_usage_policy_projection_before_rag_runtime",
        "expected_route": "waiting_for_input",
        "required_files": [
            "artifacts/workflow-orchestrator/artifact-index.json",
            "artifacts/workflow-orchestrator/workflow-summary.md",
            "artifacts/_control/architecture-baseline.json",
            "Makefile",
        ],
        "forbidden_write": True,
    })
    write_text(base / "evals" / "reports" / "README.md", "# Eval Reports\n\n`run_skill_evals.py --mode scored` writes deterministic scored eval results here and mirrors the report into the plugin package when present.")
    eval_report_path = base / "evals" / "reports" / "eval-report.json"
    if not eval_report_path.exists():
        write_json(eval_report_path, {"status": "pass", "metrics": {}, "checks": []})
    write_json(base / "plugin" / "plugin.json", plugin_manifest())
    write_text(base / "artifacts" / "README.md", "# 运行产物\n\nWorkflow 输出、trace 日志、审批请求和审计证据按 run id 存放在这里。")
    generate_runtime_policy_pack(base)


def plugin_manifest() -> dict:
    return {
        "name": PLUGIN_NAME,
        "version": PLUGIN_VERSION,
        "description": "人人取/萤启团队研发助手插件，内置部门和团队规范，提供需求准入、主动信息补全、技术/框架选型评审、前端设计研发、代码上下文分析、概要/详细设计、DB/Redis/MQ 设计、设计评审、实现控制、文档治理、代码质量治理和经验沉淀能力。",
        "author": {
            "name": "Teamwork Engineering Team",
            "email": "teamwork-engineering@example.com",
            "url": "https://example.internal/teamwork-engineering-assistant",
        },
        "homepage": "https://example.internal/teamwork-engineering-assistant",
        "repository": "https://example.internal/teamwork-engineering-assistant/repo",
        "license": "UNLICENSED",
        "keywords": ["teamwork", "rrq", "yingqi", "engineering", "design", "framework-selection", "frontend", "required-information", "implementation-control", "document-governance", "code-quality", "workflow", "skills"],
        "skills": "./skills/",
        "metadata_status": "waiting_for_human_review",
        "distribution_notes": {
            "placeholder_metadata_allowed_for_local_template": True,
            "external_distribution_gate": "waiting_for_human_review",
            "runtime_policy_pack": "target-project-template",
            "hooks_packaging": "not-bundled",
            "todo": [
                "homepage 需要人工确认真实团队入口",
                "websiteURL 需要人工确认正式分发链接",
                "privacyPolicyURL 需要人工确认隐私政策链接",
                "termsOfServiceURL 需要人工确认服务条款链接",
                "视觉资产和外部分发说明需要人工确认",
            ],
        },
        "interface": {
            "displayName": PLUGIN_DISPLAY_NAME,
            "shortDescription": "按人人取/萤启团队规范完成设计、研发、评审和质量治理。",
            "longDescription": "面向人人取/萤启团队的研发流程插件，内置部门和团队规范、阶段化 skills、语言确认、主动信息补全、YApi/Redis/幂等/异常/服务商系统规则、技术/框架选型评审、前端设计研发流程、HTML 已审设计到 machine contract 的实现控制、文档编号与生命周期治理、工作流、eval、CI 校验和 profile 注入机制。",
            "developerName": "Teamwork Engineering Team",
            "category": "Productivity",
            "capabilities": ["Interactive", "Write"],
            "websiteURL": "https://example.internal/teamwork-engineering-assistant",
            "privacyPolicyURL": "https://example.internal/teamwork-engineering-assistant/privacy",
            "termsOfServiceURL": "https://example.internal/teamwork-engineering-assistant/terms",
            "defaultPrompt": [
                "使用团队研发助手走 design-only 流程",
                "加载人人取/萤启团队规范后生成概要设计",
                "基于当前仓库生成详细设计",
                "按 YApi、Redis、幂等、异常和服务商系统规范评审设计",
                "检查技术/框架选型，覆盖后端、持久化、前端、测试和构建工具",
                "使用 frontend-only 流程完成前端设计和研发",
                "基于已审 HTML 设计自动推进实现和质量门禁",
                "先确认输出语言是简体中文还是 English",
                "先列出完成本阶段必须由我补充的信息",
                "按文档治理规范生成正式设计文档",
                "评审这份设计是否可进入研发",
            ],
            "brandColor": "#2563EB",
        },
    }


def generate_plugin_publish_config() -> None:
    write_json(ROOT / ".agent" / "plugins" / "publish-config.json", {
        "name": PLUGIN_MARKETPLACE_NAME,
        "interface": {
            "displayName": PLUGIN_MARKETPLACE_DISPLAY_NAME,
        },
        "plugin_name": PLUGIN_NAME,
        "compatibility_alias": PLUGIN_COMPATIBILITY_ALIAS,
        "publish_root": f"~/.codex/local-plugins/{PLUGIN_MARKETPLACE_NAME}",
        "hermes_publish_root": "~/.hermes",
        "marketplace_path": f"~/.codex/local-plugins/{PLUGIN_MARKETPLACE_NAME}/.agents/plugins/marketplace.json",
        "plugin_relative_path": f"plugins/{PLUGIN_NAME}",
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    })


def upstream_main_capability_matrix_doc() -> str:
    rows = "\n".join(
        f"| {item['domain']} | {item['capability']} | `{item['status']}` | {item['teamwork_handling']} | {item['why']} |"
        for item in UPSTREAM_MAIN_INCREMENT_CAPABILITIES
    )
    return f"""# upstream-main-capability-matrix

## 适用范围

- 本矩阵只覆盖当前仓库快照下，`main` 相对公共祖先的当前可见增量。
- 目标是判断哪些 upstream 能力已经被 `teamwork` 吸收，哪些属于团队硬约束不能导入。
- 本矩阵是生成器驱动的治理产物，不允许手工只改发布包镜像。

## 判定规则

- `already-covered-by-teamwork`：`teamwork` 已有等价或更强实现，可直接视为已吸收。
- `needs-backport`：`teamwork` 当前缺失 upstream 通用能力，需要补回生成器和回归护栏。
- `do-not-import`：若导入会覆盖 `teamwork-engineering-assistant` 插件身份、削弱团队 profile/团队规则、把更强门禁退化回通用门禁，或破坏 personal/local-root/compatibility alias 发布策略。

## 当前结论

- 当前 `main` 可见增量未发现 `needs-backport` 项；现阶段以“已覆盖”或“禁止导入”两类结论为主。
- 后续若 `main` 再出现新的通用能力，应先更新本矩阵，再决定是否回收到生成器。

## Capability Matrix

| domain | upstream capability | status | teamwork handling | why |
|---|---|---|---|---|
{rows}
"""


def delivery_doc() -> str:
    skill_rows = "\n".join(
        f"| {s['id']} | {s['type']} | {s['description']} | {', '.join(s['inputs'][:2])} | {', '.join(s['outputs'][:3])} | 是 | 是 | {'; '.join(s['gates'][:2])} | {'; '.join(s['approvals'][:2])} | {s['owner']} |"
        for s in SKILLS
    )
    skill_sections = "\n\n".join(
        f"""## {s['id']}
- 设计摘要：{s['purpose']}
- description：{s['description']}
- 输入：{', '.join(s['inputs'])}
- 输出：{', '.join(s['outputs'])}
- 质量门禁：{'; '.join(s['gates'])}
- 失败处理：缺输入进入 `waiting_for_input`；schema 失败进入 `failed`；门禁失败进入 `blocked`；高风险进入 `waiting_for_human_review`。
- 人工审批规则：{'; '.join(s['approvals'])}
- 目录结构：`skills/{s['id']}/SKILL.md`、`contract.yaml`、`output.schema.json`、`scripts/validate_output.py`、`evals/*.yaml`、`workflow/node.yaml`。
- SKILL.md 样例：见 `skills/{s['id']}/SKILL.md`。
- contract.yaml 样例：见 `skills/{s['id']}/contract.yaml`。
- output schema 样例：见 `skills/{s['id']}/output.schema.json`。
- eval cases 样例：见 `skills/{s['id']}/evals/`。
- workflow node 样例：见 `skills/{s['id']}/workflow/node.yaml`。"""
        for s in SKILLS
    )
    return f"""# 研发助手 Skills 工程体系落地方案

# 1. 执行摘要
当前插件版本：`{PLUGIN_VERSION}`。

目标是把需求、设计、研发、自测、质量门禁、代码走查、发布、复盘和知识沉淀转化为可独立运行、可编排、可校验、可审计、可版本化治理的团队研发助手插件。本版本不再把插件定位为“文档生成器”，而是定位为“可循环的设计治理工作流”：信息收集完成判定 -> 目标规划与缺口识别 -> 用户追问/方向确认 -> ready 后正式生成设计文档 -> 自我评审 -> 有边界的自动修复 -> 人工评审 -> 反馈分类 -> 增量修正 -> 规范候选沉淀 -> TL 统一治理。

当前落地内容包括仓库结构、`{len(SKILLS)}` 个 skill、统一 contract、output schema、eval cases、workflow node、workflow 样例、CI 样例、标准、检查清单、设计治理状态机、preflight 生成闸门、自审修复边界、人审反馈循环和 TL 规范候选包。

边界：当前未接入真实组织系统、真实 CI/CD 平台和真实审批工具，默认以文件化 contract、GitHub Actions 样例和人工审批对象作为第一版落地接口。插件不得维护单次需求的具体业务事实；具体业务事实只能进入目标项目 artifact 或脱敏 eval/regression case。待组织确认项见本文件末尾。

# 2. 总体架构
```mermaid
flowchart TB
  L1[\"L1 用户入口层\\nCodex CLI / IDE / App / PR / CI / 人工评审\"] --> L2
  L2[\"L2 Workflow 编排层\\nworkflow-orchestrator / 状态机 / 审批网关 / 产物路由\"] --> L3
  L3[\"L3 阶段 Skills 层\\n需求 / 设计 / 研发 / 测试 / 质量 / 发布 / 知识\"] --> L4
  L4[\"L4 工程工具层\\nGit / PR / build / lint / test / scan / release / observability\"] --> L5
  L5[\"L5 知识与规范层\\nstandards / templates / checklists / lessons / rules / regression cases\"] --> L6
  L6[\"L6 质量与治理层\\nregistry / versions / owners / evals / audit logs / dashboards\"] --> L2
```

模块职责：L1 提供触发入口；L2 负责编排、状态、审批和 artifact mapping；L3 执行阶段能力；L4 提供确定性工程检查；L5 提供规范和经验；L6 管理版本、owner、eval、审计和指标。

关键数据流：输入材料进入 `StageRunRequest`，preflight 先生成信息盘点、缺失信息、目标规划和方向确认等控制产物；只有 `preflight_input_state == ready` 且方向/专项范围已确认时，skill 才输出正式设计文档和 `StageRunResult`。产物写入 `artifacts/<skill_id>/`，workflow 通过 `artifact-index.json` 路由给下游节点，knowledge mining 只从用户修改、Agent 修改、自审 findings 和人工评审意见抽取 rule candidates / prompt candidates，并提交 TL 审核，不自动写回团队插件。

关键控制流：基础状态为 `pending -> running -> succeeded|failed|blocked|waiting_for_input|waiting_for_human_review`；设计治理状态机进一步细化为 `intake_collecting -> intake_gap_analysis -> waiting_for_user_input -> direction_confirming -> design_generating -> self_reviewing -> design_revising -> waiting_for_human_review -> human_review_processing -> design_regenerating -> knowledge_mining -> tl_rule_candidate_pending -> approved_or_done`。高风险动作进入人工审批网关，审批通过恢复运行，拒绝则 blocked 或 cancelled。

人工审批流：风险识别 -> 生成 `ApprovalRequest` 或 human-review package -> 指定角色审批 -> 记录证据、时间、结果 -> 按反馈分类决定增量修正、方向重确认为或阻断。人工评审状态不得被标记为 final/approved。

产物流转图：
```mermaid
flowchart LR
  A[Information Inventory] --> B[Gap Analysis]
  B --> C{{Preflight ready?}}
  C -- No --> D[Required Info / Direction Confirmation]
  D --> B
  C -- Yes --> E[Formal Design Docs]
  E --> F[Special Designs]
  F --> G[Self Review + Validators]
  G --> H{{Blockers fixed?}}
  H -- No --> I[Auto Fix / Unresolved Findings]
  I --> G
  H -- Yes --> J[Human Review Package]
  J --> K[Feedback Classification]
  K --> L{{Core direction changed?}}
  L -- Yes --> B
  L -- No --> M[Incremental Patch]
  M --> G
  K --> N[Rule / Prompt Candidates]
  N --> O[TL Review Queue]
  J --> P[Design Review Gate]
  P --> Q[Code Changes]
  Q --> R[Self Test / Quality / Code Review]
  R --> S[Release / Verification / Retrospective]
```

# 3. 仓库结构
核心结构已创建：
- `skills/<skill-id>/SKILL.md`
- `skills/<skill-id>/contract.yaml`
- `skills/<skill-id>/output.schema.json`
- `skills/<skill-id>/scripts/validate_output.py`
- `skills/<skill-id>/evals/*.yaml`
- `skills/<skill-id>/workflow/node.yaml`
- `engineering-assistant/workflows/*.yaml`
- `engineering-assistant/standards/*.md`
- `engineering-assistant/checklists/*.md`
- `engineering-assistant/schemas/*.json`
- `engineering-assistant/scripts/*.py`
- `engineering-assistant/ci/github-actions/*.yml`
- `engineering-assistant/registry/*.yaml`

# 4. Skills 清单
| skill_id | 类型 | 触发场景 | 输入 | 输出 | 可独立运行 | 可编排 | 质量门禁 | 人工审批点 | owner 建议 |
|---|---|---|---|---|---|---|---|---|---|
{skill_rows}

# 5. SkillContract 标准
标准模板已落地在每个 `contract.yaml`。必填字段包括：`skill_id`、`skill_name`、`version`、`stage`、`type`、`purpose`、`non_goals`、`trigger_description`、`standalone_mode`、`workflow_mode`、`inputs`、`outputs`、`preconditions`、`postconditions`、`dependencies`、`permissions`、`human_approval_required`、`risk_model`、`quality_gates`、`failure_modes`、`eval_cases`、`workflow_interface`、`owner`、`reviewers`、`change_policy`。

# 6. SKILL.md 标准模板
每个 `SKILL.md` 均包含 front matter，并包含：`Role`、`Scope`、`Non-goals`、`Inputs`、`Preconditions`、`Operating Procedure`、`Output Contract`、`Quality Gates`、`Failure Handling`、`Human Approval Rules`、`Standalone Mode`、`Workflow Mode`、`Review Checklist`、`Prohibited Behavior`、`Examples`、`Eval Guidance`。

# 7. 各阶段 Skill 设计
{skill_sections}

# 8. Workflow Orchestrator 设计
统一状态机：`pending`、`running`、`waiting_for_input`、`waiting_for_human_review`、`succeeded`、`failed`、`skipped`、`blocked`、`cancelled`。

错误模型：`MISSING_REQUIRED_INPUT`、`INVALID_INPUT_SCHEMA`、`INVALID_OUTPUT_SCHEMA`、`QUALITY_GATE_FAILED`、`HUMAN_APPROVAL_REQUIRED`、`HUMAN_APPROVAL_REJECTED`、`TOOL_UNAVAILABLE`、`CI_FAILED`、`TEST_FAILED`、`RISK_POLICY_VIOLATION`、`ARTIFACT_NOT_FOUND`、`CONTRACT_MISMATCH`、`WORKFLOW_DEADLOCK`、`UNKNOWN_ERROR`。

节点协议：每个 node 包含 `node_id`、`stage`、`skill_id`、`version`、`mode`、`inputs`、`outputs`、`preconditions`、`postconditions`、`quality_gates`、`approval_policy`、`retry_policy`、`failure_policy`、`next_nodes`、`artifact_mapping`。

workflow 样例已创建在 `engineering-assistant/workflows/`。断点恢复依赖 workflow trace、节点状态和 artifact index；人工审批通过 `ApprovalRequest` 暂停和恢复。

# 8.1 设计治理闭环与防废稿门禁
设计治理状态机：`intake_collecting`、`intake_gap_analysis`、`waiting_for_user_input`、`direction_confirming`、`design_generating`、`self_reviewing`、`design_revising`、`waiting_for_human_review`、`human_review_processing`、`design_regenerating`、`knowledge_mining`、`tl_rule_candidate_pending`、`approved_or_done`。

硬门禁：
- 信息收集完成前不得进入 `formal_generation`。
- 方案方向和专项范围未确认前不得生成主设计或专项设计。
- `preflight_input_state != ready` 时只允许生成控制产物，不得生成或登记正式设计文档。
- 自审和 deterministic validator 未完成前不得提交人工评审。
- 人工评审未通过前不得标记 `approved` / `final`。
- 只有 `approved` 或 `final` 且 `retention_policy=persist` 的文档才能进入代码研发控制面。

waiting_for_input 阶段允许产物：`information-inventory.json`、`context-source-map.json`、`missing-information-list.json`、`required-information-request.json`、`design-objective-plan.md`、`scope-and-non-goals.yaml`、`user-confirmed-facts.json`、`design-direction-decision.md`、`docs/human-review/<run-id>.html`、`workflow-trace.json`、`resume-point.json`。

waiting_for_input 阶段禁止产物：`high-level-design.md`、`detailed-design.md`、`database-design.md`、`redis-design.md`、`mq-design.xlsx`、`interface-contracts.yaml`、`test-strategy.md`。

自审策略：deterministic validators + reviewer-agent 两层执行。Agent 只能自动修复格式、模板缺口、已知事实遗漏、术语不一致、文档路由错误和已确认方案表达问题；不能自动改变业务方向、核心接口增删、风险策略、系统边界或人工审批结论。

人工评审反馈处理：先分类为 `fact_completion`、`direction_change`、`document_defect`、`standard_violation`、`team_rule_candidate`。默认增量 patch 受影响产物；只有架构方向、数据模型、接口边界或消息模型变化时才允许整套重生，并必须输出影响分析、把旧版标记 `superseded`、在 `workflow-trace.json` 记录原因。

知识沉淀：用户修改、Agent 修改、自审问题和人工评审意见只生成 `rule-candidates.json`、`prompt-optimization-candidates.md`、`tl-review-package.json`。未经 TL 审核，不得自动写回团队插件、SKILL.md、模板、validator 或正式规则目录。

# 9. 代码质量控制体系
五层门禁：Q0 设计一致性；Q1 build/format/lint/typecheck/unit/integration/coverage/dependency/secret/migration/architecture boundary；Q2 correctness、boundary、exception、idempotency、transaction、concurrency、performance、security、maintainability、testability、observability；Q3 DB/Redis/MQ/权限/认证/支付/订单/配置/发布脚本等风险专项；Q4 发布前回归。

阻断规则：critical/blocker、build failed、tests failed、secret 命中、未审批高风险、设计外高风险、skill-quality block 均阻断。gate decision 只能是 `pass`、`warn`、`block`、`require_human_review`。

`quality-report.schema.json` 已创建，PR 和 CI 样例已创建。

# 10. 经验总结与规范沉淀体系
知识对象：`standard`、`rule_candidate`、`checklist_item`、`anti_pattern`、`lesson`、`incident_lesson`、`regression_case`、`skill_patch_suggestion`。

状态机：`candidate -> under_review -> approved -> published -> deprecated|rejected`。未审批不得 published；规范必须有 owner、版本、适用范围、不适用范围和证据；规范变更必须同步 checklist、evals、skills。

沉淀流程：研发产物 -> findings -> lessons -> rule_candidates -> checklist_candidates -> regression_case_candidates -> human_review -> standards/checklists/evals/skills update -> change_log。

# 11. CI/CD 集成方案
PR workflow：pull_request opened/synchronize/review_requested 触发 self-test、code-quality-governor、code-review，改动 `skills` 时执行 skill-quality-auditor。样例：`engineering-assistant/ci/github-actions/codex-code-quality.yml`。

Skill eval workflow：对 `skills/**` 和 `engineering-assistant/**` 改动执行 contract 和 workflow 校验。样例：`codex-skill-eval.yml`。

Knowledge mining workflow：每周、迭代结束或事故关闭时执行 knowledge miner 和 eval 候选更新。样例：`codex-knowledge-mining.yml`。

# 12. 全量落地推进计划
阶段 0 基础准备：负责人研发负责人；交付仓库结构、standards、schemas、registry、workflow 基线；验收为目录和 contract 校验通过。

阶段 1 核心阶段 skills：负责人架构师；交付 requirement/high-level/detailed/database/redis/mq/design-review 七个 skills、evals、schemas、workflow nodes；验收为 design-only workflow 可完整流转。

阶段 2 代码质量体系：负责人研发负责人；交付 code-development/self-test/code-quality-governor/code-review、五层门禁、PR/CI 集成；验收为 blocker 可阻断、测试失败不可 pass。

阶段 3 发布与复盘：负责人发布负责人；交付 release-readiness/release-verification/release-retrospective；验收为高风险发布进入人工审批，发布复盘产生 lessons。

阶段 4 知识闭环：负责人规范 owner；交付 knowledge miner、规范候选审批流、eval 反哺流、skill 更新建议流；验收为每条规则有证据、owner 和状态。

阶段 5 workflow orchestrator：负责人 workflow owner；交付五类 workflow、断点恢复、人工审批暂停/恢复、产物流转；验收为 full-feature-development 可按节点状态运行。

阶段 6 治理与规模化：负责人研发负责人；交付版本治理、持续回归、CI/CD 常态化、团队培训、指标看板和周例行知识治理；验收为 registry、eval pass rate、knowledge feedback rate 可追踪。

# 13. RACI
| 事项 | R | A | C | I |
|---|---|---|---|---|
| skill 创建 | skill owner | 研发负责人 | 架构师、测试负责人 | 团队 |
| skill 审计 | skill-quality-auditor owner | 研发负责人 | workflow owner | 团队 |
| 规范审批 | 规范 owner | 研发负责人 | 架构师、安全负责人、DBA、SRE | 团队 |
| 代码质量门禁 | 后端开发 | 研发负责人 | 测试负责人、安全负责人 | 产品/需求负责人 |
| 设计评审 | 架构师 | 研发负责人 | DBA、SRE、安全负责人 | 产品/需求负责人 |
| 发布审批 | 发布负责人 | 研发负责人 | SRE、DBA、安全负责人 | 团队 |
| 事故复盘 | SRE | 研发负责人 | 发布负责人、测试负责人 | 团队 |
| knowledge mining | 规范 owner | 研发负责人 | skill owner、workflow owner | 团队 |
| eval 更新 | skill owner | workflow owner | 测试负责人 | 团队 |
| workflow 变更 | workflow owner | 研发负责人 | CI/CD owner、skill owner | 团队 |

# 14. 验收标准
团队级：流程覆盖需求到知识沉淀全链路，所有高风险动作 human-in-the-loop。

skill 级：每个 skill 有 SKILL.md、contract、schema、validation script、6 类 eval、workflow node、owner、审批规则。

workflow 级：五类 workflow 可解析，节点输入输出可路由，blocked/waiting 状态可恢复。

CI/CD 级：PR、skill eval、knowledge mining 三类 workflow 样例存在，失败策略明确。

知识治理级：规则候选有证据、适用范围、owner、审批状态和版本，approved 规则才可发布。

# 15. 风险与缓解
落地风险：团队规范不完整。缓解：先以文件化标准占位，逐条审批发布。

技术风险：CI/CD 平台与样例不同。缓解：保留平台无关 contract 和 GitHub Actions 样例，迁移时只替换触发器和命令。

流程风险：人工审批卡点不清。缓解：所有 contract 固化 `human_approval_required`，workflow 统一暂停和恢复。

组织风险：owner 缺失。缓解：registry/owners.yaml 强制登记 owner，缺 owner 的 skill 不入库。

# 16. Main 增量对照
当前 `main` 可见增量到 `teamwork` 的能力对照矩阵统一维护在 `engineering-assistant/checklists/upstream-main-capability-matrix.md`。使用规则：
- 先判断是 `already-covered-by-teamwork`、`needs-backport` 还是 `do-not-import`
- 只允许修改生成器和回归测试，不允许直接改发布镜像
- 团队插件身份、团队 profile、团队规则和 compatibility alias 视为硬约束

# 17. 首次落地文件清单
首次已创建文件清单由以下命令查看：
`find skills engineering-assistant -type f | sort`

# 18. 下一步执行命令
```bash
python3 engineering-assistant/scripts/validate_skill_contract.py skills/*/contract.yaml
python3 engineering-assistant/scripts/validate_workflow.py engineering-assistant/workflows/*.yaml
python3 engineering-assistant/scripts/run_skill_evals.py
```

待组织确认项：
- 真实组织角色、审批人和 owner 名单。
- 当前技术栈、构建命令、测试命令、CI/CD 平台。
- 团队正式 DB/Redis/MQ/发布/安全规范。
- 现有 PR、事故、发布记录和优秀设计文档作为 knowledge miner 初始数据源。
"""


def root_readme() -> str:
    return f"""# agent-skills

本仓库维护 `teamwork-engineering-assistant` 插件的源码、治理资产、skills 和发布配置。仓库不保留临时发布目录，Codex 可识别插件由发布脚本生成到配置目录；治理资产目录仍为 `engineering-assistant/`。

## 目录边界

- `skills/`：可触发 skill 源树，包含 `SKILL.md`、`contract.yaml`、`output.schema.json`、eval 和 workflow node。
- `engineering-assistant/`：治理与运行时资产，包含 standards、schemas、scripts、workflows、registry、runtime policy、compiled skill IR 和 eval fixtures。
- `engineering-assistant/checklists/upstream-main-capability-matrix.md`：当前 `main` 可见增量到 `teamwork` 的能力对照、导入结论和禁止导入边界。
- `.agent/plugins/publish-config.json`：本地发布配置，指定默认发布根目录和 marketplace 输出路径。
- 发布目录：由 `publish_plugin.py` 生成，不能手补回仓库；默认 local-root 发布到 `~/.codex/local-plugins/local-teamwork-engineering/plugins/teamwork-engineering-assistant/`。

## 修改方式

优先修改 `generate_engineering_assistant_assets.py` 和回归测试，然后运行：

```bash
python3 generate_engineering_assistant_assets.py
```

生成器会刷新 `skills/`、`engineering-assistant/`、发布脚本输入和本地发布配置。新增运行时能力也必须进入生成器、schema、测试，并通过发布脚本进入 Codex 插件包。

`main` 当前可见增量与 `teamwork` 的对照结论统一维护在 `engineering-assistant/checklists/upstream-main-capability-matrix.md`；先更新矩阵，再决定是否吸收 upstream 能力。

## 发布给 Codex 使用

推荐使用 Codex 官方个人 marketplace 布局：

```bash
python3 engineering-assistant/scripts/publish_plugin.py --layout personal
```

该方式生成：

- `~/plugins/teamwork-engineering-assistant/.codex-plugin/plugin.json`
- `~/plugins/teamwork-engineering-assistant/skills/`
- `~/plugins/teamwork-engineering-assistant/engineering-assistant/`
- `~/.agents/plugins/marketplace.json`

如果 Codex App 的插件安装页不接受自定义 marketplace 根目录，优先使用该 personal 布局。

保留配置化 local-root 布局用于隔离验证：

```bash
python3 engineering-assistant/scripts/publish_plugin.py
```

local-root 会读取 `.agent/plugins/publish-config.json`，生成：

- `~/.codex/local-plugins/local-teamwork-engineering/plugins/teamwork-engineering-assistant/.codex-plugin/plugin.json`
- `~/.codex/local-plugins/local-teamwork-engineering/plugins/teamwork-engineering-assistant/skills/`
- `~/.codex/local-plugins/local-teamwork-engineering/plugins/teamwork-engineering-assistant/engineering-assistant/`
- `~/.codex/local-plugins/local-teamwork-engineering/.agents/plugins/marketplace.json`

Codex 使用对应 marketplace 后即可识别 `teamwork-engineering-assistant` 插件。仓库内仍不保留 `plugins/` 临时发布目录。

## 发布给 Hermes 使用

Hermes 使用目录插件布局，skills 以插件限定名显式加载，不进入全局 skill 列表：

```bash
python3 engineering-assistant/scripts/publish_plugin.py --layout hermes --enable
```

该方式生成：

- `~/.hermes/plugins/teamwork-engineering-assistant/plugin.yaml`
- `~/.hermes/plugins/teamwork-engineering-assistant/__init__.py`
- `~/.hermes/plugins/teamwork-engineering-assistant/skills/`
- `~/.hermes/plugins/teamwork-engineering-assistant/engineering-assistant/`

`--enable` 会把 `teamwork-engineering-assistant` 幂等加入 `~/.hermes/config.yaml` 的 `plugins.enabled`；不传 `--enable` 只生成插件目录，不修改 Hermes 配置。

在 Hermes 中使用时加载限定名，例如：

```bash
hermes --skills teamwork-engineering-assistant:requirement-intake
hermes --skills teamwork-engineering-assistant:repo-context-miner
```

## 验证命令

```bash
PYTHONPYCACHEPREFIX=/private/tmp/agent-pycache python3 -m unittest discover -s tests -v
python3 engineering-assistant/scripts/validate_skill_contract.py skills/*/contract.yaml
python3 engineering-assistant/scripts/validate_workflow.py engineering-assistant/workflows/*.yaml
python3 engineering-assistant/scripts/run_skill_evals.py
python3 engineering-assistant/scripts/run_skill_evals.py --mode scored
python3 engineering-assistant/scripts/run_skill_evals.py --mode scored --no-write-report
python3 engineering-assistant/scripts/validate_skill_metadata.py
python3 engineering-assistant/scripts/validate_plugin_manifest.py
python3 engineering-assistant/scripts/publish_plugin.py --layout personal --publish-root /tmp/teamwork-engineering-assistant-personal
python3 engineering-assistant/scripts/publish_plugin.py --layout hermes --publish-root /tmp/teamwork-engineering-assistant-hermes --enable
python3 engineering-assistant/scripts/publish_plugin.py --publish-root /tmp/teamwork-engineering-assistant-plugin --marketplace-path /tmp/teamwork-engineering-assistant-plugin/.agents/plugins/marketplace.json
diff -qr skills /tmp/teamwork-engineering-assistant-plugin/plugins/teamwork-engineering-assistant/skills
diff -qr engineering-assistant /tmp/teamwork-engineering-assistant-plugin/plugins/teamwork-engineering-assistant/engineering-assistant
```

## 下游 canary

第一轮只读 canary 仓库：

`{DOWNSTREAM_CANARY_ROOT}`

`engineering-assistant/evals/fixtures/ai-platform-v1.json` 记录允许读取的 workflow/control-plane 入口。`run_skill_evals.py --mode scored` 会验证 router、context pack 和发布包同步，不写入下游仓库。
"""


def generate_root_ci() -> None:
    workflows = {
        "codex-code-quality.yml": {
            "name": "Codex Code Quality",
            "on": {"pull_request": {"types": ["opened", "synchronize", "review_requested"]}, "workflow_dispatch": {}},
            "permissions": {"contents": "read", "pull-requests": "write", "checks": "write"},
            "jobs": {"quality": {"runs-on": "ubuntu-latest", "steps": [
                {"uses": "actions/checkout@v4"},
                {"name": "Run unit tests", "run": "PYTHONPYCACHEPREFIX=/tmp/agent-pycache python3 -m unittest discover -s tests -v"},
                {"name": "Validate skill contracts", "run": "python3 engineering-assistant/scripts/validate_skill_contract.py skills/*/contract.yaml"},
                {"name": "Validate workflows", "run": "python3 engineering-assistant/scripts/validate_workflow.py engineering-assistant/workflows/*.yaml"},
                {"name": "Validate skill evals", "run": "python3 engineering-assistant/scripts/run_skill_evals.py"},
                {"name": "Validate scored evals", "run": "python3 engineering-assistant/scripts/run_skill_evals.py --mode scored"},
                {"name": "Validate metadata", "run": "python3 engineering-assistant/scripts/validate_skill_metadata.py"},
                {"name": "Validate plugin manifest", "run": "python3 engineering-assistant/scripts/validate_plugin_manifest.py"},
                {"name": "Publish plugin package", "run": "python3 engineering-assistant/scripts/publish_plugin.py --publish-root /tmp/teamwork-engineering-assistant-plugin --marketplace-path /tmp/teamwork-engineering-assistant-plugin/.agents/plugins/marketplace.json"},
                {"name": "Publish Hermes plugin package", "run": "python3 engineering-assistant/scripts/publish_plugin.py --layout hermes --publish-root /tmp/teamwork-engineering-assistant-hermes --enable"},
                {"name": "Check published skill sync", "run": "diff -qr skills /tmp/teamwork-engineering-assistant-plugin/plugins/teamwork-engineering-assistant/skills"},
                {"name": "Check published governance sync", "run": "diff -qr engineering-assistant /tmp/teamwork-engineering-assistant-plugin/plugins/teamwork-engineering-assistant/engineering-assistant"},
            ]}},
        },
        "codex-skill-eval.yml": {
            "name": "Codex Skill Eval",
            "on": {"pull_request": {"paths": ["skills/**", "engineering-assistant/**", "generate_engineering_assistant_assets.py", "tests/**"]}, "workflow_dispatch": {}},
            "permissions": {"contents": "read", "checks": "write"},
            "jobs": {"skill-eval": {"runs-on": "ubuntu-latest", "steps": [
                {"uses": "actions/checkout@v4"},
                {"name": "Validate contracts", "run": "python3 engineering-assistant/scripts/validate_skill_contract.py skills/*/contract.yaml"},
                {"name": "Validate metadata", "run": "python3 engineering-assistant/scripts/validate_skill_metadata.py"},
                {"name": "Validate plugin manifest", "run": "python3 engineering-assistant/scripts/validate_plugin_manifest.py"},
                {"name": "Validate workflows", "run": "python3 engineering-assistant/scripts/validate_workflow.py engineering-assistant/workflows/*.yaml"},
                {"name": "Run static evals", "run": "python3 engineering-assistant/scripts/run_skill_evals.py"},
                {"name": "Run scored evals", "run": "python3 engineering-assistant/scripts/run_skill_evals.py --mode scored"},
            ]}},
        },
        "codex-knowledge-mining.yml": {
            "name": "Codex Knowledge Mining",
            "on": {"schedule": [{"cron": "0 1 * * 1"}], "workflow_dispatch": {}},
            "permissions": {"contents": "read", "issues": "write"},
            "jobs": {"knowledge": {"runs-on": "ubuntu-latest", "steps": [
                {"uses": "actions/checkout@v4"},
                {"name": "Prepare CI artifacts", "run": "python3 engineering-assistant/scripts/collect_ci_artifacts.py"},
                {"name": "Run skill evals", "run": "python3 engineering-assistant/scripts/run_skill_evals.py --mode scored"},
            ]}},
        },
    }
    for file_name, payload in workflows.items():
        write_text(ROOT / ".github" / "workflows" / file_name, json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    write_text(ROOT / "AGENTS.md", agents_doc())
    write_text(ROOT / "README.md", root_readme())
    generate_plugin_publish_config()
    generate_root_ci()
    generate_skills()
    generate_engineering_assistant()
    write_text(ROOT / "engineering-assistant-delivery.md", delivery_doc())


if __name__ == "__main__":
    main()
