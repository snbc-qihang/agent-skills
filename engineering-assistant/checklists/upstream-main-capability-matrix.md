# upstream-main-capability-matrix

## 当前分支基线

- `main`: `402fe06`（3.1.0 全量 task SOP 与行为 eval 基线）
- `teamwork`: `7871cb5`（1.0.0.4 团队插件基线）
- 公共祖先：`23b9745`

## 适用范围

- 本矩阵只覆盖当前仓库快照下，`main` 相对公共祖先的当前可见增量。
- 目标是判断哪些 upstream 能力已经被 `teamwork` 吸收，哪些属于团队硬约束不能导入。
- 本矩阵是生成器驱动的治理产物，不允许手工只改发布包镜像。

## 判定规则

- `already-covered-by-teamwork`：`teamwork` 已有等价或更强实现，可直接视为已吸收。
- `needs-backport`：`teamwork` 当前缺失 upstream 通用能力，需要补回生成器和回归护栏。
- `do-not-import`：若导入会覆盖 `teamwork-engineering-assistant` 插件身份、削弱团队 profile/团队规则、把更强门禁退化回通用门禁，或破坏 personal/local-root/compatibility alias 发布策略。

## 当前结论

- `main` 3.1.0 相对 teamwork 当前基线新增 4 个对团队有正向用途的能力：`product-prototype-design`、`prototype-review-loop`、`assistant-feedback-capture`、`skill-evolution-review`。
- 本轮将上述 4 个能力按 teamwork profile、团队规则源和发布语义团队化迁入，并把既有 21 个 skills 同步升级为短 SOP + 行为 eval 形态。
- 仍然禁止导入会覆盖 `teamwork-engineering-assistant` 插件身份、削弱 `rrq-yq-team` profile、破坏 compatibility alias、Hermes 限定名或团队发布路径的通用 main 实现。
- 后续若 `main` 再出现新的通用能力，应先更新本矩阵，再决定是否回收到生成器。

## Capability Matrix

| domain | upstream capability | status | teamwork handling | why |
|---|---|---|---|---|
| task SOP / skill shape | main 3.1 的短 SKILL.md、profile-driven SOP、task_sop_full 行为 eval 和低上下文噪声指标 | `needs-backport` | 本轮迁入到 teamwork 25 个 skills，但保留团队 profile、团队规则密度、preflight、人审和发布语义。 | 这是解决 teamwork skill 模板过长、同构 eval 和上下文噪声的正向能力，不会削弱团队插件身份。 |
| prototype / frontend product gate | `product-prototype-design` 与 `prototype-review-loop` 原型事实源和三轮评审硬门禁 | `needs-backport` | 本轮团队化迁入，插入 frontend-only、design-only 和 full-feature-development 的前端/web/app 路径。 | 该能力能阻断 demo 感前端、缺少高保真原型和无截图证据直接实现的问题。 |
| feedback evolution | `assistant-feedback-capture` 与 `skill-evolution-review` 反馈采集、聚类和候选审批闭环 | `needs-backport` | 本轮团队化迁入；允许自动采集和生成候选，但正式 skill/workflow/schema 修改必须人工审批。 | 该能力补齐 teamwork 对用户纠正、工具失败、文档噪声和 skill 演进候选的持续改进闭环。 |
| manifest / distribution surface | 插件 manifest 的 `metadata_status`、`distribution_notes`、runtime policy pack 和 hooks packaging 校验 | `already-covered-by-teamwork` | 已由 `plugin_manifest()`、`validate_plugin_manifest.py`、`tests/test_plugin_distribution_surface.py` 和 `run_skill_evals.py --mode scored` 覆盖。 | 保留 upstream 的分发表面门禁，同时继续使用 teamwork 的插件身份和占位 metadata 人审策略。 |
| manifest / distribution surface | 通用 `engineering-assistant` 插件名、展示名、默认提示词和关键词集合 | `do-not-import` | 保留 `teamwork-engineering-assistant`、团队展示名、团队默认提示词、团队关键词和 `rrq-yq-team` profile 入口。 | 直接导入会覆盖 teamwork 插件身份，并削弱团队 profile、团队规则和团队发布语义。 |
| manifest / distribution surface | personal/local-root 发布布局与 published plugin sync 校验 | `already-covered-by-teamwork` | 已由 `publish_plugin.py`、`.agent/plugins/publish-config.json`、teamwork 路径回归测试和 scored eval 覆盖。 | 保留 teamwork 发布目录、marketplace entry 和 Codex 可识别插件结构。 |
| manifest / distribution surface | 仅按通用插件路径发布、不保留 `compatibility_alias=engineering-assistant` 的策略 | `do-not-import` | 继续保留 `compatibility_alias`，在 personal 布局下允许 teamwork 插件和通用别名共存。 | 删除兼容别名会破坏当前 Codex 安装兼容面和既有用户入口。 |
| traceability / implementation control | `artifacts/_control/traceability-matrix.json` 作为 agent 事实源，`docs/human-readable/traceability-report.html` 只做人读入口 | `already-covered-by-teamwork` | 已由 `compile_design_contract.py`、`build_traceability_report.py`、workflow contract、validator 和专项测试覆盖。 | 保留 upstream 追踪矩阵能力，同时确保 HTML 不反向作为 agent 事实输入。 |
| traceability / implementation control | implementation-controller / code-development 的 traceability 输出、gate 和脚本链路 | `already-covered-by-teamwork` | 已在 teamwork 的 contract、workflow、SKILL.md、runtime 脚本和 `test_team_document_design_rules.py` 中强化实现。 | teamwork 已完整吸收并扩展该能力，不需要回退到更弱的通用版本。 |
| runtime governance | `runtime-route-decision.schema.json`、`assistant-run-feedback.schema.json`、`artifact-persistence-policy.schema.json` 和 `capability-health.schema.json` | `already-covered-by-teamwork` | 已由 generator 输出、schema/validator、workflow contract 和 runtime 回归测试覆盖。 | 这些属于通用控制面骨架能力，teamwork 已保留团队插件身份前提下完成吸收。 |
| runtime governance | 通用 `generic-platform` profile、通用标准源和通用技能文案 | `do-not-import` | 继续保留 teamwork 的团队 profile、团队规则目录、团队默认 prompt 和团队化技能文案。 | 直接导入会弱化团队 profile、团队规则密度和团队默认行为。 |
| scored eval / workflow / regression | scored eval 的 plugin manifest gate、distribution surface metric 和 published plugin sync 检查 | `already-covered-by-teamwork` | 已由 `run_skill_evals.py --mode scored` 实现，并由 runtime 回归测试和 distribution surface 测试约束。 | 保留 upstream 的 scored eval 能力，同时继续验证 teamwork 发布路径和 manifest 约束。 |
| scored eval / workflow / regression | 只保留通用强度的 preflight / required-information / eval 断言，不带团队专项规则密度 | `do-not-import` | 继续使用 teamwork 更强的 preflight、required-information、team eval 和专项设计门禁。 | 回退到通用断言会削弱 teamwork 现有更强的门禁和团队规则覆盖面。 |
| manifest / distribution surface | Hermes 目录插件发布、插件启用和限定名技能注册链路 | `already-covered-by-teamwork` | 吸收为共享发布能力，但 Hermes 插件名、目录和限定名前缀使用 `teamwork-engineering-assistant`。 | 这是通用发布能力，适合上收到 teamwork 的生成器和回归护栏中。 |
| manifest / distribution surface | Hermes 场景下硬编码 `engineering-assistant` 插件命名空间 | `do-not-import` | 保留 teamwork 插件名和 `teamwork-engineering-assistant:<skill>` 的 Hermes 限定名调用方式。 | 直接导入会把 Hermes 发布面退回通用插件身份，破坏 teamwork 命名一致性。 |
