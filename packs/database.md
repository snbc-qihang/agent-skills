# 数据库能力包

明确所有权、表、字段、约束、查询模式、索引、事务边界、迁移、灰度、回滚、修复和可观测性。生产 DDL 或数据修复前必须审批。拒绝没有实际用途证据的字段和索引。

关系型 OLTP 设计必须读取团队唯一模板 `skills/codebase-design/references/relational-oltp-detailed-design-template.md`，按单表或强耦合表组生成一份完整文档。除一级标题可替换为实际文档名称外，必须保留模板全部二、三级标题、标题层级、出现顺序和表头列；不得删除、合并、改名或重排。章节不适用时仍保留，并填写“不适用”及可核验原因。所有示例值和 `{占位符}` 必须替换为项目事实，不得把模板说明或猜测冒充已确认设计。

设计文件写入目标项目 `.run-artifacts/engineering-assistant/review-packages/<REQUIREMENT-ID>/09-database-designs/`。生成或修改后逐份调用只读 `engineering_assistant_database_design_validate`；未通过时不得声明数据库设计完成，也不得进入评审批准。影响范围未命中关系型数据库时不加载模板、不生成文件，并显式标记为 `not_applicable`。
