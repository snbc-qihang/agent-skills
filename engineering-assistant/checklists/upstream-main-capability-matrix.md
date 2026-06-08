# upstream-main-capability-matrix

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
| manifest / distribution surface | 插件 manifest 的 `metadata_status`、`distribution_notes`、runtime policy pack 和 hooks packaging 校验 | `already-covered-by-teamwork` | 已由 `plugin_manifest()`、`validate_plugin_manifest.py`、`tests/test_plugin_distribution_surface.py` 和 `run_skill_evals.py --mode scored` 覆盖。 | 保留 upstream 的分发表面门禁，同时继续使用 teamwork 的插件身份和占位 metadata 人审策略。 |
| manifest / distribution surface | 通用 `engineering-assistant` 插件名、展示名、默认提示词和关键词集合 | `do-not-import` | 保留 `teamwork-engineering-assistant`、团队展示名、团队默认提示词、团队关键词和 `rrq-yq-team` profile 入口。 | 直接导入会覆盖 teamwork 插件身份，并削弱团队 profile、团队规则和团队发布语义。 |
| manifest / distribution surface | personal/local-root 发布布局与 published plugin sync 校验 | `already-covered-by-teamwork` | 已由 `publish_plugin.py`、`.agent/plugins/publish-config.json`、teamwork 路径回归测试和 scored eval 覆盖。 | 保留 teamwork 发布目录、marketplace entry 和 Codex 可识别插件结构。 |
| manifest / distribution surface | 仅按通用插件路径发布、不保留 `compatibility_alias=engineering-assistant` 的策略 | `do-not-import` | 继续保留 `compatibility_alias`，在 personal 布局下允许 teamwork 插件和通用别名共存。 | 删除兼容别名会破坏当前 Codex 安装兼容面和既有用户入口。 |
| traceability / implementation control | `artifacts/_control/traceability-matrix.json` 作为 agent 事实源，`docs/human-readable/traceability-report.html` 只做人读入口 | `already-covered-by-teamwork` | 已由 `compile_design_contract.py`、`build_traceability_report.py`、workflow contract、validator 和专项测试覆盖。 | 保留 upstream 追踪矩阵能力，同时确保 HTML 不反向作为 agent 事实输入。 |
| traceability / implementation control | implementation-controller / code-development 的 traceability 输出、gate 和脚本链路 | `already-covered-by-teamwork` | 已在 teamwork 的 contract、workflow、SKILL.md、runtime 脚本和 `test_team_document_design_rules.py` 中强化实现。 | teamwork 已完整吸收并扩展该能力，不需要回退到更弱的通用版本。 |
| scored eval / workflow / regression | scored eval 的 plugin manifest gate、distribution surface metric 和 published plugin sync 检查 | `already-covered-by-teamwork` | 已由 `run_skill_evals.py --mode scored` 实现，并由 runtime 回归测试和 distribution surface 测试约束。 | 保留 upstream 的 scored eval 能力，同时继续验证 teamwork 发布路径和 manifest 约束。 |
| scored eval / workflow / regression | 只保留通用强度的 preflight / required-information / eval 断言，不带团队专项规则密度 | `do-not-import` | 继续使用 teamwork 更强的 preflight、required-information、team eval 和专项设计门禁。 | 回退到通用断言会削弱 teamwork 现有更强的门禁和团队规则覆盖面。 |
