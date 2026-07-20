# 需求设计评审包

评审包固定在 `.run-artifacts/engineering-assistant/review-packages/<REQUIREMENT-ID>/`，至少包含影响评估、专项差异、实现测试计划、设计变更摘要、需求设计追踪矩阵和评审清单，并包含一份或多份完整上下文详细设计评审稿。只有命中系统级架构影响时才包含完整 HLD 评审稿。

设计评审稿必须：

- 严格沿用外部事实源中的对应模板且无占位符；
- `document_status: reviewing`，Agent 不得改为 `approved` 或 `final`；
- 声明 `requirement_id`、`base_document_number`、`base_version`、`base_digest`；
- 在修订记录关联需求，但不把一次性需求方案写入 HLD 长期正文；
- 把 DB、MQ、Redis、IAM 等资源级内容放入专项设计或专项差异。

追踪矩阵逐条记录 `requirement_item`、`design_document`、`design_section`、`design_change`、`code_targets`、`test_cases` 和 `status`。无需求依据的设计内容必须标记为架构治理项或移除；未确认规则进入待决策事项。

先调用 `engineering_assistant_review_package_validate` 做结构校验，再调用 `engineering_assistant_design_source_check` 对每个目标文档复核 `base_digest`。目标摘要变化时状态为 `stale`，阻断批准并要求 rebase。Git 无冲突不能证明业务不变量、状态或契约无冲突。

`06-design-change-summary.md` 必须列出新增、修改、删除和明确不变内容，受影响的聚合、不变量、流程、状态、接口和资源，已知需求或最新基线冲突，推荐合并顺序与共同回归范围。研发和发布后把实际提交、测试结果、发布证据、实现偏差及外部基线新版本补回追踪矩阵。
