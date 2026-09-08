# 需求设计评审包

评审包固定在 `.run-artifacts/engineering-assistant/review-packages/<REQUIREMENT-ID>/`，至少包含影响评估、专项差异、实现测试计划、设计变更摘要、需求设计追踪矩阵和评审清单，并包含一份或多份完整上下文详细设计评审稿。只有命中系统级架构影响时才包含完整 HLD 评审稿。

设计评审稿必须：

- 严格沿用外部事实源中的对应模板且无占位符；
- `document_status: reviewing`，Agent 不得改为 `approved` 或 `final`；
- 声明 `requirement_id`、`base_document_number`、`base_version`、`base_digest`；
- 在修订记录关联需求，但不把一次性需求方案写入 HLD 长期正文；
- 把 DB、MQ、Redis、IAM 等资源级内容放入专项设计或专项差异。

追踪矩阵逐条记录 `requirement_item`、`design_document`、`design_section`、`design_change`、`code_targets`、`test_cases` 和 `status`。无需求依据的设计内容必须标记为架构治理项或移除；未确认规则进入待决策事项。

使用 `engineering_assistant_artifact_validate` 的 `kind=review-package` 做结构校验，再调用 `engineering_assistant_design_source_recheck` 复核 intake 源摘要。目标摘要变化时状态为 `stale`，阻断批准并要求 rebase。Git 无冲突不能证明业务不变量、状态或契约无冲突。

`06-design-change-summary.md` 必须列出新增、修改、删除和明确不变内容，受影响的聚合、不变量、流程、状态、接口和资源，已知需求或最新基线冲突，推荐合并顺序与共同回归范围。研发和发布后把实际提交、测试结果、发布证据、实现偏差及外部基线新版本补回追踪矩阵。


结构化输入包含 requirement_id、非空 requirement_items、documents 与 traceability。documents 每项包含 id、role、content、document_status=reviewing；context-design/hld 另含 base_document_number、base_version、base_digest 与冻结模板内容 template。必需角色为 impact、specialist-diff、implementation-test-plan、change-summary、checklist、context-design；命中数据库时增加 database-design。traceability 的 design_document 指向 document.id，design_section 使用实际二/三级 Markdown 标题（含 #），每条包含 design_change、code_targets、test_cases、status。

可用 CLI：`ea artifact-validate --kind review-package --input <JSON>`。持久化评审包节点把同一 JSON 输入登记为节点证据并增加 `artifact:review-package` scope tag；complete 会重新校验。结构通过不代表模板来源、基线语义、业务正确性或人工验收通过；源新鲜度通过 recheck 单独确认，既有 design-approval 门禁继续保留。
