---
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

#### 4.1.2 核心流程

```mermaid
flowchart TD
    A["跨系统触发"] --> B["来源服务确认职责边界"]
    B --> C["目标服务处理架构职责"]
    C --> D["事件或开放服务完成协作"]
```

> 概要设计只说明跨系统/跨服务职责、调用/事件方向、异常流、最终一致性和专项文档引用；详细实现、接口字段、SQL/DDL、类方法和单元测试只能引用详细设计或专项文档，不在概要设计正文展开。

#### 4.1.3 跨服务服务间时序图

```mermaid
sequenceDiagram
    participant SourceService as 来源服务
    participant TargetService as 目标服务
    SourceService->>TargetService: 服务间调用或事件协作
```

> 时序图参与者只允许服务，不允许用户、页面、Controller、数据库、Redis、MQ、表、Mapper 或 Repository。

#### 4.1.4 状态机设计

| 状态 | 条件 | 动作 |
| --- | --- | --- |
|  |  |  |

#### 4.1.5 异常流与最终一致性

## 5.中间件设计

| 类型 | 是否涉及 | 专项文档 | 说明 |
| --- | --- | --- | --- |
| Redis | 是/否 | `redis-design.md` |  |
| MQ | 是/否 | `mq-design.md` |  |
| 定时任务 | 是/否 |  |  |
| 外部依赖 | 是/否 |  |  |

## 6.数据视图

| 数据对象 | 类型 | 权威来源 | 专项文档 | 说明 |
| --- | --- | --- | --- | --- |
|  | 事实表/读模型/缓存/消息 |  | `database-design.md` |  |
