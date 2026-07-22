---
name: codebase-design
description: 设计小接口、高杠杆、变更局部化的深模块和清晰 seam。适用于架构边界、可测试性或重构结构设计。
---

# 代码库设计

从仓库中有证据的调用方和变化压力出发设计。优先使用能够隐藏大量细节的小接口。

## 操作流程

1. 识别调用方、不变量、所有权，以及应保持局部化的变化；设计任务以固定的上下文详细设计评审稿和需求追踪矩阵为输入。
2. 只在真实依赖、所有权或变化边界上设置 seam。
3. 比较接口复杂度、信息泄漏、失败处理和可测试性。
4. 拒绝没有调用方或第二种变化的推测性抽象。
5. 使用接口、数据流、失败流和迁移切片表达选定设计，把实现 seam、代码目标和测试用例回填到对应设计章节及追踪矩阵。

仍有两个实质不同的接口方案可行时读取 [references/design-it-twice.md](references/design-it-twice.md)。
关系型 OLTP 数据库设计必须读取 [团队表级详细设计模板](references/relational-oltp-detailed-design-template.md)，按单表或强耦合表组完整填写；不适用章节保留并说明原因。交付前调用只读 `engineering_assistant_database_design_validate`，校验未通过不得声明完成。

DB、MQ、Redis、IAM 等资源设计保留在专项差异中并由详细设计引用，不上移到 HLD。不得把更多模块误认为更深的设计。
