# High Level Design 阶段指引

检查项：
- A1 设计文档必须体现系统边界、业务域、事件协作和最终一致性；不强制平台采用微服务、事件驱动或 DDD 作为技术路线
- A2 系统间交互优先通过开放能力接口或事件；不得直接调用未开放接口
- A3 目标业务系统与目标客户端系统按不同系统边界描述，跨系统协作明确接口、事件、消息体、幂等和一致性
- A4 应用层只暴露 api/tapi/mapi/console，业务层和共享层只暴露 service 能力
- A5 关键跨系统场景进入关键场景设计；简单服务内部 CRUD 不进入关键场景文档
- A6 跨库事务优先本地消息表、事件驱动、补偿机制；必要时使用 Seata 并说明事务边界
- H1 概要设计包含平台概述、系统逻辑视图、系统设计原则、研发视图、核心功能、中间件设计、数据视图，核心功能只保留关键协作摘要
- H2 明确参与系统、职责边界、调用方向、事件流和异常流
- H3 声明是否涉及 Redis、MQ、DB、定时任务、权限、幂等、跨系统交互
- H4 后端业务系统研发结构按 presentation/application/domain/port/infrastructure/common 分层；如项目 profile 另有约定，以 profile 为准
- H5 application 层负责编排，不直接沉淀复杂业务判断；核心业务规则进入 domain
- H6 聚合根不通过依赖注入创建，应通过工厂创建；一次业务中聚合根创建和修改边界要清晰
- DG1-DG5 正式概要设计必须有文档编号、状态和留存策略；中间过程摘要不得作为正式文档留存
- H7 high-level-design.md 必须按 `assets/high-level-design-template.md` 的章节顺序生成，不得使用通用证据/Findings/门禁决策模板替代概要设计正文
- H8 high-level-design.md 涉及跨服务协作时必须补充 Mermaid sequenceDiagram 服务间时序图；时序图参与者只允许服务，不允许用户、页面、Controller、数据库、Redis、MQ、表、Mapper 或 Repository
- H9 high-level-design.md 必须保留原始需求规格或原型引用矩阵，使用稳定 source_id 串联 source_type、source_path_or_url、prototype_page_or_section、requirement_item、design_section 和一致性状态
- H10 high-level-design.md 聚焦跨系统/跨服务架构边界、服务间时序、调用/事件方向、异常流、最终一致性和专项文档引用；不得展开接口字段、请求/响应字段、SQL/DDL、数据库字段索引、Controller/Mapper/Repository、类方法签名、伪代码或单元测试步骤
- H11 high-level-design.md 不得包含 Mermaid flowchart；研发视图和结构定义使用接口层/应用层/领域层/基础设施层等边界语言
- H12 Mermaid sequenceDiagram 的 participant 只能是真实系统/服务/应用边界，必须有 participant-evidence-map.json 证据；抽象能力名或无证据 participant 不得进入正式图
- H13 MQ / 事件 / 异步消息场景必须覆盖创建/新增/产生类消息和状态变更/删除/失效类消息；时序图必须包含服务 self-call 表达校验、幂等、状态/顺序判断、处理记录、本地读模型写入/移除、重试/死信等内部关键阶段
