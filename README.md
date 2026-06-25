# agent-skills

本仓库维护 `engineering-assistant` 插件的源码、治理资产、skills 和发布配置。仓库不保留临时发布目录，Codex 可识别插件由发布脚本生成到配置目录。

## 目录边界

- `skills/`：可触发 skill 源树，包含 `SKILL.md`、`contract.yaml`、`output.schema.json`、eval 和 workflow node。
- `engineering-assistant/`：治理与运行时资产，包含 standards、schemas、scripts、workflows、registry、runtime policy、compiled skill IR 和 eval fixtures。
- `.agent/plugins/publish-config.json`：本地发布配置，指定默认发布根目录和 marketplace 输出路径。
- 发布目录：由 `publish_plugin.py` 生成，不能手补回仓库；默认 local-root 发布到 `~/.codex/local-plugins/local-engineering/plugins/engineering-assistant/`。

## 修改方式

优先修改 `generate_engineering_assistant_assets.py` 和回归测试，然后运行：

```bash
python3 generate_engineering_assistant_assets.py
```

生成器会刷新 `skills/`、`engineering-assistant/`、发布脚本输入和本地发布配置。新增运行时能力也必须进入生成器、schema、测试，并通过发布脚本进入 Codex 插件包。

## 发布给 Codex 使用

推荐使用 Codex 官方个人 marketplace 布局：

```bash
python3 engineering-assistant/scripts/publish_plugin.py --layout personal
```

该方式生成：

- `~/plugins/engineering-assistant/.codex-plugin/plugin.json`
- `~/plugins/engineering-assistant/skills/`
- `~/plugins/engineering-assistant/engineering-assistant/`
- `~/.agents/plugins/marketplace.json`

如果 Codex App 的插件安装页不接受自定义 marketplace 根目录，优先使用该 personal 布局。

保留配置化 local-root 布局用于隔离验证：

```bash
python3 engineering-assistant/scripts/publish_plugin.py
```

local-root 会读取 `.agent/plugins/publish-config.json`，生成：

- `~/.codex/local-plugins/local-engineering/plugins/engineering-assistant/.codex-plugin/plugin.json`
- `~/.codex/local-plugins/local-engineering/plugins/engineering-assistant/skills/`
- `~/.codex/local-plugins/local-engineering/plugins/engineering-assistant/engineering-assistant/`
- `~/.codex/local-plugins/local-engineering/.agents/plugins/marketplace.json`

Codex 使用对应 marketplace 后即可识别 `engineering-assistant` 插件。仓库内仍不保留 `plugins/` 临时发布目录。

## 发布给 Hermes 使用

Hermes 使用目录插件布局，skills 以插件限定名显式加载，不进入全局 skill 列表：

```bash
python3 engineering-assistant/scripts/publish_plugin.py --layout hermes --enable
```

该方式生成：

- `~/.hermes/plugins/engineering-assistant/plugin.yaml`
- `~/.hermes/plugins/engineering-assistant/__init__.py`
- `~/.hermes/plugins/engineering-assistant/skills/`
- `~/.hermes/plugins/engineering-assistant/engineering-assistant/`

`--enable` 会把 `engineering-assistant` 幂等加入 `~/.hermes/config.yaml` 的 `plugins.enabled`；不传 `--enable` 只生成插件目录，不修改 Hermes 配置。

在 Hermes 中使用时加载限定名，例如：

```bash
hermes --skills engineering-assistant:requirement-intake
hermes --skills engineering-assistant:repo-context-miner
```

## 验证命令

```bash
PYTHONPYCACHEPREFIX=/private/tmp/agent-pycache python3 -m unittest discover -s tests -v
python3 engineering-assistant/scripts/validate_skill_contract.py skills/*/contract.yaml
python3 engineering-assistant/scripts/validate_workflow.py engineering-assistant/workflows/*.yaml
python3 engineering-assistant/scripts/run_skill_evals.py
python3 engineering-assistant/scripts/run_skill_evals.py --mode scored
python3 engineering-assistant/scripts/run_skill_evals.py --mode scored --no-write-report
python3 engineering-assistant/scripts/run_skill_effectiveness_evals.py --mode spec --no-write-report
python3 engineering-assistant/scripts/validate_skill_metadata.py
python3 engineering-assistant/scripts/validate_plugin_manifest.py
python3 engineering-assistant/scripts/publish_plugin.py --layout personal --publish-root /tmp/engineering-assistant-personal
python3 engineering-assistant/scripts/publish_plugin.py --layout hermes --publish-root /tmp/engineering-assistant-hermes --enable
python3 engineering-assistant/scripts/publish_plugin.py --publish-root /tmp/engineering-assistant-plugin --marketplace-path /tmp/engineering-assistant-plugin/.agents/plugins/marketplace.json
diff -qr skills /tmp/engineering-assistant-plugin/plugins/engineering-assistant/skills
diff -qr engineering-assistant /tmp/engineering-assistant-plugin/plugins/engineering-assistant/engineering-assistant
```

## 下游 canary

第一轮只读 canary 仓库：

`<set ENGINEERING_ASSISTANT_CANARY_ROOT to an ai-platform checkout>`

`engineering-assistant/evals/fixtures/ai-platform-v1.json` 记录允许读取的 workflow/control-plane 入口。`run_skill_evals.py --mode scored` 会验证 router、context pack 和发布包同步，不写入下游仓库。
