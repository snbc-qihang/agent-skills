# AGENTS.md

## 仓库目标
- 本仓库维护 `engineering-assistant` 插件的源码、治理资产、skills 和发布配置。
- `skills/` 是可触发能力源树，`engineering-assistant/` 是治理与运行时资产，发布包由 `publish_plugin.py` 写入配置目录。

## 修改规则
- 优先修改 `generate_engineering_assistant_assets.py` 和回归测试，再运行生成器刷新源树与发布脚本输入。
- 仓库内不保留 `plugins/engineering-assistant/` 临时发布目录；需要给 Codex 使用时运行发布脚本生成到配置目录。
- 所有任务控制产物写入目标项目 `artifacts/_control/`，不得写入插件目录。

## 验证要求
- 变更后运行 `python3 -m unittest discover -s tests -v`。
- 运行 `validate_skill_contract.py`、`validate_workflow.py`、`run_skill_evals.py`、`validate_skill_metadata.py` 和 `validate_plugin_manifest.py`。
- 发布脚本必须能把源树发布为 Codex 可识别插件，并通过 scored eval 的发布包同步检查。

## 风险边界
- 高风险动作、生产动作、发布、删除历史和范围外实现必须人工确认。
- 失败门禁不能被口头说明替代，必须修复或明确标记为 blocked / waiting_for_human_review。
