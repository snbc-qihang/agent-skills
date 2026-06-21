# document-governance-standard

## 编号与分类
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
- DG23 文档必须声明或可推导 `document_class`：正式设计/决策/索引使用 `formal_design|formal_decision|formal_index`，研发过程证据、agent 工作区、trace、人工审阅包和渲染 HTML 使用 transient 类别。
- DG24 研发完成后的最终项目留存集合只允许 `document_status=approved|final`、`retention_policy=persist`、`retention_scope=final_project_record` 且 `document_class` 为 formal_* 的确定性文档。
- DG25 `artifacts/`、`artifacts/_control/`、`docs/human-review/`、`docs/human-readable/` 下的内容不得作为最终项目正式留存源；只能作为运行证据、agent 工作材料、人工确认入口或只读渲染。
- DG26 正式留存 Markdown 的 `canonical_path` 必须位于 `docs/00-index/`、`docs/architecture/`、`docs/design/`、`docs/decisions/` 或 `docs/release/`，不得指向 agent 运行目录。
- DG27 release/交付收尾必须生成 retained-vs-transient 清单：列出保留文档、运行期证据、清理策略、归档策略和人工审批状态。
