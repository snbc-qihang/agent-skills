# Skill Effectiveness Evals

本目录用于回答 `engineering-assistant` 插件是否真的提升交付质量。它位于仓库根目录，不在 `skills/` 或 `engineering-assistant/` 下，因此不会进入 Codex/Hermes 发布包。

本轮已经模拟完成一个极小前后端产品研发任务：`minimal-fullstack-product-task`。模拟结果用于验证评测闭环，不代表真实生产性能结论。

## Baselines
- `baseline_free_codex`：不加载本插件，只给真实任务和目标仓库上下文。
- `current_engineering_assistant`：使用当前插件 workflow、skills 和控制面脚本。
- `curated_tools`：明确复用 codegraph、build-web-apps、browser、GitHub/code-review 等现有能力。

## Commands
```bash
python3 engineering-assistant/scripts/run_skill_effectiveness_evals.py --mode spec --no-write-report
python3 engineering-assistant/scripts/run_skill_effectiveness_evals.py --mode grade
python3 engineering-assistant/scripts/run_skill_effectiveness_evals.py --mode report
```

`spec` 校验评测定义、fixture、baseline 和报告字段。`grade/report` 读取 `results/` 中的三组模拟结果，生成 `reports/effectiveness-report.json`。
