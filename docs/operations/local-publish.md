# 本机发布

统一入口：

```bash
python3 scripts/publish_local.py --platform <codex|hermes|claude-code|all> <--dry-run|--yes>
```

## 无副作用预演

```bash
python3 scripts/publish_local.py --platform all --dry-run
```

预演会运行仓库测试、作者源强校验、真实核心 eval、公开 skill 官方 `quick_validate.py`、双平台最终 staging 构建和包摘要校验，并对最终 Codex staging 包执行官方 plugin validator、核对官方校验摘要与构建摘要，不写入插件目录、marketplace 或平台配置。preflight 报告会原样披露 `ea eval` 的 canary 状态，并把当前策略标记为 `not_required_for_local_prerelease`；这只说明本机 RC 预发布不以产品 canary 为前置条件，不代表真实收益已经验证。真实验证流程见 [真实产品 Canary](canary.md)。官方 validator 使用仓库外 `uv` 隔离环境并固定 `PyYAML==6.0.2`；缺少工具、输出超限或校验失败时预演直接失败。

GitHub CI 在临时 Runner 中从 OpenAI 官方仓库的固定提交准备 validator、核对固定摘要并安装固定版本的 `uv`，不读取开发者电脑上的 `~/.codex`。本机执行仍使用操作系统账户下已安装的官方 validator 和 `uv`。

## 实际发布

```bash
python3 scripts/publish_local.py --platform codex --yes
python3 scripts/publish_local.py --platform hermes --yes
python3 scripts/publish_local.py --platform claude-code --yes
python3 scripts/publish_local.py --platform all --yes
```

实际发布读取 `config/local-publish-policy.json`，要求目标平台已启用、版本与 catalog 一致，并且命令显式提供 `--yes`。

## 平台 CLI 发现

发布脚本按以下顺序查找平台注册命令：

1. `CODEX_CLI`、`HERMES_CLI` 或 `CLAUDE_CLI` 指定的可执行文件。
2. 当前终端的 `PATH`。
3. macOS 标准应用目录中的 Codex App 内置 CLI，包括 `ChatGPT.app` 和 `Codex.app`。

因此，从 macOS 系统 Terminal 执行时不需要手工把 App 的 `Contents/Resources` 加入 `PATH`。如果 App 或 CLI 位于自定义位置，使用环境变量显式指定：

```bash
CODEX_CLI="/自定义路径/codex" python3 scripts/publish_local.py --platform codex --yes
HERMES_CLI="/自定义路径/hermes" python3 scripts/publish_local.py --platform hermes --yes
CLAUDE_CLI="/自定义路径/claude" python3 scripts/publish_local.py --platform claude-code --yes
```

### Codex

1. 构建带唯一 cachebuster 的 Codex 包。
2. 对最终 staging 包执行官方 plugin validator，并绑定校验摘要。
3. 将现有活动 cache 快照到仓库外临时目录，仅用于本次失败补偿，并备份发布目标。
4. 原子替换插件目录并幂等维护 personal marketplace entry。
5. 已安装时先执行 `codex plugin remove`，再执行 `codex plugin add`。
6. 通过 `codex plugin list --json` 校验本次精确版本，并核对 cache manifest、payload digest 和逐文件摘要。
7. 成功后只保留本次活动 cache，删除临时快照；失败时恢复旧目标、marketplace、注册状态和 cache。

Codex 发布报告包含 `active_cache_versions`、`removed_cache_versions`、`selected_version_verified`、`restart_required` 和 `hooks_review_required`。更新后必须重启 Codex，并在新对话验证 skill、MCP 和 Hook；Hook 定义变化时需要重新审查信任。

### Hermes

1. 构建 Hermes 目录插件。
2. 备份 `~/.hermes/plugins/engineering-assistant`。
3. 原子替换插件目录。
4. 执行 `hermes plugins enable engineering-assistant`。
5. 校验安装包摘要；失败时恢复旧插件。

Hermes 可以使用限定名加载 skill：

```bash
hermes --skills engineering-assistant:repo-context
```

## 回滚

发布成功结果中的 `backup` 是直接回滚目录。脚本在注册或安装后验证失败时自动恢复；成功后的人工回滚应先停止使用该插件的新任务，再恢复备份目录并重新执行平台的 add/enable 命令。

发布结果只输出到终端，不写入仓库。

## Claude Code marketplace

Claude Code 发布会在 `~/.claude/plugins/marketplaces/engineering-assistant-local` 生成受控本地 marketplace，随后执行 `claude plugin marketplace add` 和 `claude plugin install`（已安装时改为 `update`）。市场包通过 `claude plugin validate <marketplace> --strict`，并以 `claude plugin list --json` 确认已选中插件。包内 MCP 使用 `${CLAUDE_PLUGIN_ROOT}` 启动 Runtime，Hook 将 Claude 的 `prompt_id` 映射为运行时的 `turn_id`。

```bash
# 仅构建并严格校验，不修改 ~/.claude 或 Claude 配置
python3 scripts/publish_local.py --platform claude-code --dry-run

# 注册 marketplace 并安装到当前用户 scope
python3 scripts/publish_local.py --platform claude-code --yes

# 只读确认 marketplace、严格校验和已安装状态
python3 scripts/publish_local.py --platform claude-code --verify

# 显式卸载插件并注销 marketplace；本地 marketplace 包保留，便于重新安装
python3 scripts/publish_local.py --platform claude-code --uninstall --yes
```

安装或更新后在 Claude Code 中执行 `/reload-plugins`，或启动一个新会话。`--claude-home` 仅用于指定受控 marketplace 包目录；Claude CLI 的用户 scope 仍由当前 Claude CLI 配置决定。
