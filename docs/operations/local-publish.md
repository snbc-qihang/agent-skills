# 安装与本机发布

## 用户安装目标

安装完整的 skills、Runtime MCP、Hook 和 Provider 能力。原生 Agent 管理插件发现、启用、缓存和更新；`ea-setup` 只准备固定 Runtime 并验证实际协议。首次只需公共工具 `uv`，无需 Node、作者源 Git checkout、手动 Python 环境或日常激活命令。

发行维护者从四个原生 CI Runner 的验证产物组装预编译插件、独立市场树和通用 setup wheel，所有生成物都在仓库外。当前候选没有已发布的公网地址；下列 wheel/source/marketplace 参数须用经过验证的真实发行资产替换，不是可复制的公网安装地址。

```bash
uvx --python 3.13.13 --from <setup-wheel> ea-setup install --agent codex --source <发行市场> --marketplace <市场名>
```

已由原生市场安装时使用 `prepare`；所有生命周期命令都通过同一个 setup wheel 启动 `uvx`：

```bash
uvx --python 3.13.13 --from <setup-wheel> ea-setup prepare --agent codex
uvx --python 3.13.13 --from <setup-wheel> ea-setup doctor --agent codex --json
uvx --python 3.13.13 --from <setup-wheel> ea-setup repair --agent codex
uvx --python 3.13.13 --from <setup-wheel> ea-setup update --agent codex --marketplace <市场名>
uvx --python 3.13.13 --from <setup-wheel> ea-setup update --agent hermes --package <已验证的新候选包>
uvx --python 3.13.13 --from <setup-wheel> ea-setup uninstall --agent codex --marketplace <市场名>
```

每条命令都重新通过 `uvx` 启动安装工具；单次命令结束后不会把 `ea-setup` 加入当前终端 PATH。日常 Agent 会话无需执行安装命令或激活环境。`--agent` 也接受 `hermes` 或 `claude-code`。Hermes 原生 CLI 的 Git 更新没有候选预览，必须显式提供候选；不会把它的 `#subdir` 当成固定 revision。发行维护者需要为每个 Agent/target 发布独立市场树，避免在同一插件名下猜 OS。

## 支持与资格

| 目标 | 安装 Runtime | 安全边界与资格 |
| --- | --- | --- |
| macOS 14+ arm64/x64 | 固定 Python 3.13.13 与哈希依赖 | Seatbelt；每个架构在对应 Runner 实际调用 |
| Ubuntu 24.04 x64 | 同一 Python 和依赖合同 | Landlock ABI 至少 3 与 seccomp；不可用则不能获得完整资格 |
| Windows 11 x64 | 同一 Python 和依赖合同 | NTFS、句柄相对 ArtifactIO、LPAC 与 Job Object；仍需 Windows 11 实验 |

其他系统/架构没有正式资格承诺。Windows Server CI 可以验证其本机行为，但不代替 Windows 11 或已认证的 Agent 会话。CI 必须实际完成正向 Provider 调用、IPv4/IPv6 网络基线与禁止探针、子进程/额外 exec、路径读写、输出与超时门禁；缺失或跳过必需原生测试时失败。`scripts/qualify_installation.py` 真实执行 native launcher、MCP initialize/list/call、Hook、持久化 run、Hermes 桥与 Provider 隔离，记录运行资格；它不会自动证明 Agent 的启用状态或 Hook 信任。

Codex 的 Windows Hook 还要求 Agent 的执行环境能够找到系统 `powershell.exe`。Hook 使用固定的 UTF-16LE `EncodedCommand` 桥，读取 Codex 注入的 `PLUGIN_ROOT` 环境变量，再以绝对路径直接启动 `ea.exe`；中文、空格和路径中的 Shell 符号不进入外层命令解析。输入、输出和错误流按原始字节复制，避免 PowerShell 文本管道改变 JSON 编码。CI 必须实际运行同一 manifest 命令的 CMD、PowerShell 与 Git Bash 用例；缺少 PowerShell、必需用例跳过或实际启动失败时不能获得 Windows Hook 资格。这个执行合同依据 [Codex 插件 Hook 文档](https://developers.openai.com/codex/hooks#plugin-hooks) 与固定版本的 [环境注入](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/hooks/src/engine/discovery.rs#L263)、[命令执行器](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/hooks/src/engine/command_runner.rs#L424)；命令级测试仍不代替 Windows 11 上经过信任的真实 Codex Hook 事件。Claude Code 使用无引号的原生路径与 `args: ["hook"]` 的 [exec 形式](https://code.claude.com/docs/en/hooks#exec-form-and-shell-form)，Hermes 使用参数数组直接启动原生 Runtime，两者不使用该 PowerShell 桥。

诊断区分 `needs_preparation`、`needs_trust`、`ready`、`partial`、`unsupported` 和 `failed`。包摘要正确、能力可用、Runtime 检查通过与完整桌面安装是不同的证据。

Codex 和 Claude Code 首次安装时不声明 Hook 已受信任。先在真实宿主界面审查并信任当前 Hook 定义，再执行以下命令，在本次诊断报告中声明已完成审查；Claude Code 将 `--agent` 改为 `claude-code`：

```bash
uvx --python 3.13.13 --from <setup-wheel> ea-setup doctor --agent codex --hooks-trusted --json
```

`--hooks-trusted` 仅使本次报告将用户确认标记为 `user_confirmed`；只读 `doctor` 不持久化该确认。它不替宿主授予信任、不绕过信任提示，也不证明真实 Hook 事件已经执行。Runtime 已就绪且插件已启用、但本次命令未提供该确认时，Codex 和 Claude Code 的诊断返回 `needs_trust`。

Provider 隔离资格使用受控诊断 bundle，不表示可选的 UI/UX Pro Max 知识包已经安装。外部 bundle 仍须满足 catalog 固定 revision、许可证与摘要；缺失或失败时使用已声明的原生建议 fallback，不能把其输出提升为完成证据。

## Runtime 准备与恢复

每个包包含 `runtime-lock.json`、哈希依赖锁和目标原生 `ea`/`ea.exe`。launcher 读取按 Agent/版本持久化的绑定，使用绝对的固定解释器路径；Runtime 启动不依赖 GUI/终端 PATH 中的 Python 或 uv，Codex Windows Hook 的系统 PowerShell 先决条件见上文。Hermes 宿主只加载标准库，通过有界 RPC 启动同一个 Runtime。

Runtime 位于插件缓存和作者源之外：macOS `~/Library/Application Support/engineering-assistant`，Linux `${XDG_DATA_HOME:-~/.local/share}/engineering-assistant`，Windows `%LOCALAPPDATA%/engineering-assistant`。`--data-home` 或 `ENGINEERING_ASSISTANT_DATA_HOME` 可覆盖；GUI 的默认 locator 只保存指向已验证外部环境的绑定。Agent home 按显式参数、对应 `CODEX_HOME`/`HERMES_HOME`/`CLAUDE_CONFIG_DIR`、可选 `--config` JSON、原生默认目录的顺序解析；支持空格与中文路径。

准备在私有 staging 创建环境，固定解释器及依赖检查、实际协议与隔离资格通过后才发布版本绑定。更新保留旧环境和旧版本绑定；修复的最终路径校验失败则恢复原环境，失败候选留在 Runtime 数据目录供诊断。不会自动删除可能被活动会话使用的环境、插件备份或旧 Codex cache。网络失败、依赖摘要不匹配或缺少安全能力都不能用安装成功标签代替。

消费者更新的恢复能力受原生 Agent 限制：Codex 和 Claude Code 当前 CLI 没有选择任意旧缓存版本的接口，不能承诺自动恢复旧插件选择。更新失败或选中未经验证的包时报告恢复要求，保留旧 Runtime；Hermes 禁用未验证插件也不意味着旧插件代码已恢复。需要自动恢复插件文件和注册状态时，作者本机发布路径使用下述备份与补偿事务。

## 作者本机发布入口

统一入口：

```bash
python3 scripts/publish_local.py --platform <codex|hermes|claude-code|all> <--dry-run|--yes>
```

## 无副作用预演

```bash
python3 scripts/publish_local.py --platform all --dry-run
```

预演会运行仓库测试、作者源强校验、真实核心 eval、公开 skill 官方 `quick_validate.py`、三平台最终 staging 构建和包摘要校验，并对最终 Codex staging 包执行官方 plugin validator、核对官方校验摘要与构建摘要，不写入插件目录、marketplace 或平台配置。preflight 报告会原样披露 `ea eval` 的 canary 状态，并把当前策略标记为 `not_required_for_local_prerelease`；这只说明本机 RC 预发布不以产品 canary 为前置条件，不代表真实收益已经验证。真实验证流程见 [真实产品 Canary](canary.md)。官方 validator 使用仓库外 `uv` 隔离环境并固定 `PyYAML==6.0.2`；缺少工具、输出超限或校验失败时预演直接失败。

GitHub CI 与本机预演使用同一组固定官方 URL、revision 和 SHA-256，从受控缓存读取并在私有快照执行 validator，不读取开发者电脑上的 `~/.codex`。`uv` 按显式参数、环境变量、PATH 和原生目录发现。校验器环境固定 Python `3.13.13` 和 `PyYAML==6.0.2`。终端用户消费已经通过 CI 的包，不运行作者源门禁。

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
7. 验证实际 cache 启动的 MCP、Hook 与 Provider；成功后保留既有版本 cache，失败时恢复旧目标、marketplace、注册状态和 cache。

Codex 发布报告包含 `active_cache_versions`、`removed_cache_versions`、`selected_version_verified`、`restart_required` 和 `hooks_review_required`。更新后必须重启 Codex，并在新对话验证 skill、MCP 和 Hook；Hook 定义变化时需要重新审查信任。

### Hermes

1. 构建 Hermes 目录插件。
2. 备份 `~/.hermes/plugins/engineering-assistant`。
3. 原子替换插件目录。
4. 执行 `hermes plugins enable engineering-assistant`。
5. 校验安装包摘要和 native Runtime 实际协议；失败时恢复旧插件。

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

安装或更新后在 Claude Code 中执行 `/reload-plugins`，或启动一个新会话。`--claude-home` 同时传递为 CLI 的 `CLAUDE_CONFIG_DIR`，确保市场、安装列表与被验证目录来自同一个选定 home。
