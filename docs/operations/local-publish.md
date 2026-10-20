# 安装与本机发布

## Mac 候选验收

另一台 macOS 14+ Apple Silicon 机器通过 [GitHub 候选安装教程](https://github.com/snbc-qihang/agent-skills/blob/candidate/codex/1.0.0.1/macos-arm64/20261019.3/README.md) 的固定命令安装 `1.0.0.1`。预先准备已登录的 Codex、Git 和 uv；无需维护者机器上的压缩包、路径或作者编译工具。

候选使用独立的 `engineering-assistant-candidate` 市场和不可变 `candidate/codex/` tag，命令绑定真实源码 commit；安装器仍核对原生 Git 来源、包摘要、固定 Python 和完整 Provider 隔离。生成树只进入仓库外目录和候选 tag。候选教程同时给出检查、修复、卸载与真实 App、CLI、Hook、持久化恢复的结果回传要求。发现历史安装时，按检查给出的确切来源人工处理；不清理历史目录或共享缓存。

候选分发只提供可执行的验收入口，不写入已通过的人工作业记录，不创建 Release，不推进 `internal/installer`。Windows 11 和两目标完整真实验收、BUILD 更新及正式推广门禁继续保留。正式内部安装命令见下一节，目前尚未推广。

## 用户安装目标

首轮内部交付安装完整的 11 个 skills、Runtime MCP、Hook 和 Provider 隔离能力，面向 macOS 14+ arm64、Windows 11 x64 上的 Codex App 与原生 CLI。用户预先安装 Codex（App 或原生 CLI）、`uv` 和 Git，在选用的 Codex 宿主完成登录。仓库采用 MIT 许可证并公开，下载不需要 GitHub 登录、token 或私有仓库授权。`uv` 的首轮验证基线为 0.11.7，须能在安装器启动前自动获取 Python 3.13.13；Runtime 准备函数的最低版本不能代替这项入口验证。无需 Node、手动 Python 环境、作者源 checkout、Rust 编译器或日常激活命令。

**当前 `1.0.0.1` 候选尚未通过两目标真实宿主验收并推广；本节命令待发布，当前不能宣称已可安装。** 固定源码 tag `internal/installer/1.0.0.1` 对应发行 tag `internal/codex/1.0.0.1`，移动入口 `internal/installer` 指向团队最新已验收源码。安装器核对实际 Git 来源 commit，从同版本不可变发行 tag 读取预编译包与公开验收摘要，自动选择 OS/架构，再准备并核对受控本地 marketplace 来源，调用原生 `plugin add` 完成选择。

macOS Terminal 与 Windows PowerShell 使用同一固定版本命令：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer/1.0.0.1" ea-setup install --agent codex
```

已安装受控内部版本后，更新到团队最新验收版本：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer" ea-setup update --agent codex
```

对 `1.0.0.1` 诊断、修复与卸载使用其固定前缀；更新后使用对应 Release 提供的版本前缀：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer/1.0.0.1" ea-setup doctor --agent codex --json
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer/1.0.0.1" ea-setup repair --agent codex
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer/1.0.0.1" ea-setup uninstall --agent codex
```

默认输出中文；自动化读取时加 `--json`。同版本重复安装复用已验证包，受控 1.x 的旧版重复安装返回 `needs_update`。`doctor` 只读检查插件、工具与历史目录，不准备缺失 CLI；`repair` 恢复中断事务或 Runtime，`uninstall` 调用原生宿主卸载并核对受控市场注销，保留 Runtime、旧市场与可能被活动会话使用的文件。每条命令结束后不会把 `ea-setup` 加入终端 PATH。

安装结果为 `needs_trust` 时，在 Codex App 或 CLI 中审查并信任当前 Hook 定义，关闭旧会话并打开新会话，再运行 `doctor` 和真实 skill/MCP/Hook 操作。`--hooks-trusted` 仅记录用户声明，不能授予宿主信任或代替真实执行证据。重新打开 App 后仍须能执行 MCP 和恢复持久化任务，才算完成验收。

## 历史 2.x 卸载与清理

首次安装前运行固定版本的 `doctor --json`。检查输出包含 `legacy_installation_detected`、检查范围、已确认项、未知项和人工步骤。只检查选定 `CODEX_HOME`、已知 Runtime 数据目录、明确旧来源、该插件缓存及发布备份；不扫描全盘。无法读取或归属的文件不能被当作已清理。发现明确历史安装或来源冲突时，新安装停止，不自动接管或删除。

1. 关闭使用旧插件的会话。可先在 Codex App 的插件管理中按来源卸载旧工程助手。CLI 可用时，使用同一 `CODEX_HOME` 查询实际旧来源；如果 `codex` 不在 PATH，使用 App 提供的 CLI 绝对路径。检查报告明确缺少兼容 CLI 时，不要求为了旧版清理另装 CLI，先从 App 卸载再复查文件残留。

   ```bash
   codex plugin list --json
   codex plugin marketplace list --json
   ```

2. 按列表中的来源逐项卸载。下面仅适用于实际来源确为 `personal` 的情况：

   ```bash
   codex plugin remove "engineering-assistant@personal" --json
   codex plugin list --json
   ```

3. 共享 `personal` 市场保留，只人工移除其中本插件条目。只有确认旧市场完全属于本插件时，才按检查输出的具体名称执行 `codex plugin marketplace remove`。
4. 依据检查输出的确切绝对路径，自行清理可归属的历史版本、Runtime 绑定、环境、缓存和发布备份，再重跑 `doctor --json`。不删除整个 Codex home 或 Runtime 数据根，不使用通配符删除；共享 Python、其他插件、作者源码及目标项目 `.run-artifacts` 不在清理范围。

`publish_local.py --uninstall` 是 Claude Code 入口，不能用来清理 Codex。首次 `install` 会在发行下载与 Runtime 准备前复查；若唯一缺项是控制 CLI，则先自动准备既定工具再完整复查，用户无需另装 CLI。`doctor` 缺少 CLI 时仍保持只读并明确报告检查未完成。

安装命令需要访问公开 Git、固定官方 Codex 归档、Python 归档和已锁定依赖来源；首次准备不是离线安装。命令不携带密码或 token。`uvx` 会构建小型 Python 安装器 wheel，消费已经构建的原生插件，不在用户机器上编译 Rust。高级 wheel/source 兼容入口见后文。

## 支持与资格

| 目标 | 安装 Runtime | 安全边界与资格 |
| --- | --- | --- |
| macOS 14+ arm64 | 固定 Python 3.13.13 与哈希依赖 | Seatbelt；在原生 ARM64 宿主实际调用 |
| Windows 11 x64 | 同一 Python 和依赖合同 | NTFS、句柄相对 ArtifactIO、LPAC 与 Job Object；仍需 Windows 11 实验 |

表格是内部支持目标，不表示已取得资格。Hermes、Claude Code 和 Linux 共享源码继续回归，保留高级入口，不阻塞首轮 Codex 发行，也不获得首轮内部交付承诺。Windows Server CI 可以验证其本机行为，但不代替 Windows 11 或已认证的 Agent 会话；缺少 Windows 11 证据时发行推广保持 blocked。CI 必须实际完成正向 Provider 调用、IPv4/IPv6 网络基线与禁止探针、子进程/额外 exec、路径读写、输出与超时门禁；缺失或跳过必需原生测试时失败。`scripts/qualify_installation.py` 执行 native launcher、MCP initialize/list/call、Hook、持久化 run 与 Provider 隔离，记录运行资格；它不会自动证明 Agent 的启用状态或 Hook 信任。

Codex 的 Windows Hook 还要求 Agent 的执行环境能够找到系统 `powershell.exe`。Hook 使用固定的 UTF-16LE `EncodedCommand` 桥，读取 Codex 注入的 `PLUGIN_ROOT` 环境变量，再以绝对路径直接启动 `ea.exe`；中文、空格和路径中的 Shell 符号不进入外层命令解析。输入、输出和错误流按原始字节复制，避免 PowerShell 文本管道改变 JSON 编码。CI 必须实际运行同一 manifest 命令的 CMD、PowerShell 与 Git Bash 用例；缺少 PowerShell、必需用例跳过或实际启动失败时不能获得 Windows Hook 资格。这个执行合同依据 [Codex 插件 Hook 文档](https://developers.openai.com/codex/hooks#plugin-hooks) 与固定版本的 [环境注入](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/hooks/src/engine/discovery.rs#L263)、[命令执行器](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/hooks/src/engine/command_runner.rs#L424)；命令级测试仍不代替 Windows 11 上经过信任的真实 Codex Hook 事件。Claude Code 使用无引号的原生路径与 `args: ["hook"]` 的 [exec 形式](https://code.claude.com/docs/en/hooks#exec-form-and-shell-form)，Hermes 使用参数数组直接启动原生 Runtime，两者不使用该 PowerShell 桥。

诊断区分 `needs_preparation`、`needs_update`、`needs_trust`、`ready`、`partial`、`unsupported` 和 `failed`。`needs_update` 表示用户应执行更新；`needs_trust` 表示插件与 Runtime 已准备，但用户仍须审查 Hook。这两类待用户动作不是下载或安装故障，尚未达到 `ready` 时退出码仍为 2。包摘要正确、能力可用、Runtime 检查通过与完整桌面安装是不同的证据。

`runtime_ready` 只表示 MCP initialize/list/call 通过，`provider_ready` 单独表示 Provider 隔离通过。Provider 探测失败或超时保留已完成的 MCP 诊断，完整功能仍未就绪；不会通过降低隔离要求使安装成功。`requires_native_activation` 提示在宿主启用插件，`requires_native_hook_review` 提示审查 Hook。

Codex 和 Claude Code 首次安装时不声明 Hook 已受信任。先在真实宿主界面审查并信任当前 Hook 定义，再执行以下命令，在本次诊断报告中声明已完成审查；Claude Code 将 `--agent` 改为 `claude-code`：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer/1.0.0.1" ea-setup doctor --agent codex --hooks-trusted --json
```

`--hooks-trusted` 仅使本次报告将用户确认标记为 `user_confirmed`；只读 `doctor` 不持久化该确认。它不替宿主授予信任、不绕过信任提示，也不证明真实 Hook 事件已经执行。Runtime 已就绪且插件已启用、但本次命令未提供该确认时，Codex 和 Claude Code 的诊断返回 `needs_trust`。

Provider 隔离资格使用受控诊断 bundle，不表示可选的 UI/UX Pro Max 知识包已经安装。外部 bundle 仍须满足 catalog 固定 revision、许可证与摘要；缺失或失败时使用已声明的原生建议 fallback，不能把其输出提升为完成证据。

## Runtime 准备与恢复

每个包包含 `runtime-lock.json`、单目标 `runtime-python-downloads.json`、哈希依赖锁和目标原生 `ea`/`ea.exe`。`config/runtime-python-downloads.json` 是共享目标分布的作者源，固定 uv 0.11.7 元数据中的 CPython `3.13.13`、PBS `20260414`、官方归档 URL 与 SHA-256。准备使用包内元数据和构建日期，忽略继承的 uv 选择配置；由 uv 下载、解包并校验归档，不要求用户更换全局 uv 版本。

launcher 读取按 Agent/版本持久化的 v2 绑定，使用绝对的固定解释器路径并校验分布身份；Runtime 启动和 `doctor` 还核对实际 `sys.base_prefix`、`BUILD` 与不可变安装记录。Python 基底按分布身份隔离，环境键包含该身份，更新不会重新标记旧基底的构建号。Runtime 启动不依赖 GUI/终端 PATH 中的 Python 或 uv，Codex Windows Hook 的系统 PowerShell 先决条件见上文。Hermes 宿主只加载标准库，通过有界 RPC 启动同一个 Runtime。

`uv` 仅用于准备和修复，Runtime 不再要求旧 `uv` 文件仍存在。准备记录可保留工具来源信息，launcher 按固定 Python 分布、依赖与插件身份执行；Homebrew 升级导致旧 `uv` Cellar 路径消失不会单独阻止已准备 Runtime 启动。

Runtime 位于插件缓存和作者源之外：macOS `~/Library/Application Support/engineering-assistant`，Linux `${XDG_DATA_HOME:-~/.local/share}/engineering-assistant`，Windows `%LOCALAPPDATA%/engineering-assistant`。`--data-home` 或 `ENGINEERING_ASSISTANT_DATA_HOME` 可覆盖；GUI 的默认 locator 只保存指向已验证外部环境的绑定。Agent home 按显式参数、对应 `CODEX_HOME`/`HERMES_HOME`/`CLAUDE_CONFIG_DIR`、可选 `--config` JSON、原生默认目录的顺序解析；支持空格与中文路径。

准备先在私有 staging 下载 Python；构建与归档安装记录随基底一次原子发布，再从该基底创建虚拟环境。依赖检查、实际协议与隔离资格通过后才发布版本绑定。中断的未发布下载留在 staging，重试使用新下载目录；未知或记录损坏的既有基底会明确失败，不覆盖可能仍被使用的文件。更新保留旧基底、旧环境和旧版本绑定；修复的最终路径校验失败则恢复原环境，失败候选留在 Runtime 数据目录供诊断。不会自动删除可能被活动会话使用的环境、插件备份或旧 Codex cache。网络失败、依赖摘要不匹配或缺少安全能力都不能用安装成功标签代替。

内部 Codex 安装先完成候选 Runtime 与协议验证，再写入安装事务并切换受控本地市场；已注册本地市场核对来源后直接执行 `plugin add`。Codex `0.159.2` 的 `marketplace upgrade` 只用于 Git 市场，不用于该受控本地目录。失败时从上一版市场备份调用原生命令重新安装，核对已启用版本与包摘要，再恢复 Runtime 绑定；首次失败尝试恢复未安装状态。事务中断由 `repair` 恢复；发现同名外部市场、来源被外部修改、备份不一致或无法选回旧版时明确 `recovery_required`，不覆盖未知来源。该补偿实现仍需真实宿主验收，夹具通过不能证明 Codex 已选回旧版。

## Codex 控制 CLI

消费者安装器依次检测显式 `CODEX_CLI`、PATH、macOS 标准 App 内置 CLI 或 Windows 官方 standalone 布局。候选必须真实通过固定 `0.159.2` 的架构、版本、插件命令与只读 JSON 合同探测；显式指定不兼容 CLI 时直接报告，不悄悄替换 override。

缺少兼容候选时，`install`、`update`、`repair` 可以从 `config/codex-control.json` 的固定官方 URL 下载完整归档，校验大小与 SHA-256，经有界安全解包、真实合同探测后原子提交到 `<data-home>/tools/codex/0.159.2/<target>`。保留完整官方组件，使用绝对路径执行，不修改 PATH、App 或用户已有 CLI 安装。已有受控 cache 每次复用都核对文件摘要；损坏目录明确失败并保留，不盲目覆盖。`doctor`、`uninstall` 与 `prepare` 不下载控制工具，缺失时提示先执行 `install` 或 `repair`。

控制命令沿用调用方选择的同一个 `CODEX_HOME`，因此 App 与控制 CLI 应指向同一用户配置。不能假设每个 Windows App 版本都捆绑独立 CLI，也不能根据 WindowsApps 目录猜测可执行文件；官方 standalone 是受控工具缺失时的自动准备来源。

## 高级 wheel/source 兼容入口

消费者 wheel 只包含安装器、Runtime 及运行资料，不包含作者工具或 `evals`。`ea validate/eval/build/verify-package/canary-*` 仅在作者源码开发环境执行；安装器 wheel 的隔离验证覆盖真实 Runtime 路由、授权边界和来源资料校验。完整仓库 eval 仍由维护者验证单独执行。

已取得经过核验的 setup wheel、市场与候选包时，可继续使用显式入口；这些参数是高级输入，不能作为当前可用公网地址：

```bash
uvx --python 3.13.13 --from <setup-wheel> ea-setup install --agent codex --source <发行市场> --marketplace <市场名>
uvx --python 3.13.13 --from <setup-wheel> ea-setup prepare --agent codex
uvx --python 3.13.13 --from <setup-wheel> ea-setup update --agent codex --marketplace <市场名> --package <已验证的新候选包>
uvx --python 3.13.13 --from <setup-wheel> ea-setup update --agent hermes --package <已验证的新候选包>
```

`prepare` 只为已经安装的插件准备 Runtime，不下载缺失 Codex 控制 CLI。高级入口保留 `hermes`、`claude-code`；Hermes 当前 adapter 不预览 Git 更新候选，要求显式候选，不把 `#subdir` 当固定 revision，这不代表所有 Hermes 宿主版本永久不支持原生 pin。自定义来源的更新不转为内部来源。旧 wheel 不自动升级安装器，也不能代替内部固定命令的 Git 来源证明；持续更新应重新运行带 `--isolated --refresh` 的内部命令，避免复用已安装的旧 tool 或陈旧 alias。高级消费者恢复受原生 Agent 接口限制，失败时保留旧 Runtime 并报告恢复要求，不承诺任意旧 cache 自动回选。

## 内部发行与推广

候选可以使用 CI 或维护者本地两目标验证输入组装，生成物保存在仓库外；本地命令与工具准备见 [维护者候选准备](#无付费-ci-的候选准备)。本地验证只接受干净的已提交源码，批次文件同时绑定源码 commit 与随机 `validation_id`，两目标共用同一文件。组装拒绝不同源码、不同批次、混用 CI 字段和缺失必需检查；本地 index 标为 `local_artifacts_unattested`，既有 CI index 标为 `ci_artifacts_unattested`。两者均不提供外部验签，也不要求购买托管 CI。

正式编号也仅生成候选，index 固定标记资格尚未满足；CI 临时 artifact 不是长期安装地址。维护者须在 macOS arm64 与真实 Windows 11 上，对同一候选完成已认证 App、原生 CLI 会话与 Provider 隔离验收，覆盖首次安装、更新、重复执行、失败补偿、重开会话后的 skill/MCP/受信任 Hook。验收 JSON 及证据在仓库外保存，并绑定源码 commit、候选 index 与包摘要；具体字段由 `release_assets.validate_acceptance` 校验。

每个目标的 App 与 CLI 验收记录都必须覆盖以下场景；缺项、失败或只有 `doctor` 结果均不能推广：

- 首次安装、同版重复安装、跨版本更新、修复、补偿恢复和卸载；实际加载 skill，执行 MCP、受信任 Hook、持久化任务及重开会话后的恢复。
- 中文及空格路径、uv 升级、旧 uv 路径移除、缓存清理，以及 `internal/installer` 推进后相同命令取得新安装器。
- 网络失败、仓库鉴权失败、摘要错误、更新中断，以及候选准备失败后原插件仍可使用。

Provider 记录另行核对完整的 11 项隔离检查与 IPv4/IPv6 对照，不能通过关闭能力或放宽权限填写成功。人工记录提供本地可追溯性，维护者须审查其对应的真实操作证据；JSON 的声明本身不构成身份验签或外部可信证明。

源码采用 [MIT](../../LICENSE) 许可证，插件包和安装器 wheel 同时携带许可证与[第三方声明](../../THIRD_PARTY_NOTICES.md)。公开源码仍按团队试用范围发行，不增加 PyPI、npm、公开插件市场或部署服务器。GitHub Release 用于版本说明、教程与公开验收摘要，消费者下载仍使用 Git 发行 tag；维护者的 GitHub 发布权限和控制工具不转嫁给新人。推广时核对固定仓库公开且未归档，不接受其他仓库或自动切换发行来源。

完整 `acceptance.json`、App/CLI/Provider 证据、`activation.json`、命令收据、原生插件列表与包快照只保存在仓库外受控目录，维护者负责保留以便复核。`prepare` 在私有快照中逐项校验后，发行 tag 仅保存 `acceptance-summary.json`：包含候选和源码身份、两目标包摘要、App/CLI/Provider 通过状态及原始证据摘要，不复制 reviewer、路径、命令、会话内容或原始记录。消费者验证公开摘要与完整包；无法据此独立重放原始验收，也不获得密码学身份保证。`activate` 同样校验完整原始记录及 BUILD 更新后，Release 只上传 `activation-summary.json` 和已审查的安装教程。

推广分为两个阶段，各自先预演，再按远程推广授权显式执行。实际远程操作要求维护者的 Git HTTPS 写权限和已认证 `gh`；安装消费者无需 `gh`。第一阶段 `prepare` 只写入并核对不可变的发行 tag 和源码 tag，不更新移动入口：

```bash
python3 scripts/promote_internal_release.py --phase prepare --candidate <仓库外候选目录> --acceptance <仓库外acceptance.json> --dry-run
python3 scripts/promote_internal_release.py --phase prepare --candidate <仓库外候选目录> --acceptance <仓库外acceptance.json> --yes
```

两个 tag 已核验后，在两个目标上使用本节实际公开 HTTPS 固定命令进行新人安装，并从 App 与 CLI 完成完整运行验收。另在隔离试验来源验证 `1.0.0.1 → 1.0.0.2` 的 BUILD 更新，记录更新前后的真实原生选择；不能用 SemVer 排序、构建成功或 `doctor` 替代。试验下一版不推进团队 alias。

第二阶段 `activate` 需要仓库外 `activation.json` 和已核对的 Release 教程正文：

```bash
python3 scripts/promote_internal_release.py --phase activate --candidate <仓库外候选目录> --acceptance <仓库外acceptance.json> --activation <仓库外activation.json> --release-notes <仓库外教程.md> --expected-alias <旧源码commit或absent> --dry-run
python3 scripts/promote_internal_release.py --phase activate --candidate <仓库外候选目录> --acceptance <仓库外acceptance.json> --activation <仓库外activation.json> --release-notes <仓库外教程.md> --expected-alias <旧源码commit或absent> --yes
```

`activation.json` 固定 `schema_version=1`、`repository_url=https://github.com/snbc-qihang/agent-skills.git`、`installer_ref=internal/installer/1.0.0.1` 和 `transport=https_git`，包含一份完整两目标 `acceptance` 及两个目标的 `build_updates`。每项引用 `install`、`before_update`、`update` 三份实际命令 receipt；引用均为 `{path, sha256}`，相对路径位于验收输入目录内。

每份 receipt 记录 `schema_version=1`、`evidence_kind=ea_setup_command`、完整参数数组 `command`、实际 PEP 610 `installer_origin`、`exit_code`、实际 JSON `result`、`package` 包快照引用和 `native_selection` 原生清单引用。固定安装须执行该版本的精确 HTTPS 命令并输出 `--json`；包快照放在 `evidence/packages/` 内，包含完整已安装包和 `manifest_sha256`；原生清单保存 `codex plugin list --json` 的实际输出。固定安装的 canonical、源码及摘要须匹配候选；更新前另行采集 `doctor` 或重复 `install` 收据，核对 canonical 与包摘要；更新后须执行真实 `update`，选中同前三段、BUILD 加一且摘要不同的完整包。App、CLI、Provider 验收证据仍逐项审查，不以这些 receipt 代替受信任 Hook、登录态或隔离资格。

Release 教程正文至少包含固定版本安装命令、支持目标、前置条件、旧版清理、信任与重开会话、检查、更新、修复和卸载，并明确验收版本与源码来源。教程是人工审查后提供的公开正文，不得包含凭证、个人路径或业务内容。脚本核对两个已有 tag 后，发布或核对团队试用 Release 及其公开摘要，再以 CAS 更新 `internal/installer`。摘要的 `acceptance_sha256` 绑定规范化原始验收 JSON，角色摘要绑定原始证据字节，`activation_sha256` 绑定原始激活记录字节；原始内容不随摘要上传。Release 失败或验收缺失时不推进 alias；Release 已发布但 CAS 失败时明确报告部分完成，不自动删除 Release 或 tag。已有不同内容的 tag 不覆盖，alias 并发变化不强行推广。生成物不提交到 `main`、`teamwork` 或作者 checkout。

正式内部交付资格仅证明仓库门禁和完整安装运行验收，不表示产品 Canary 或公开稳定版资格。没有两目标真实验收和实际固定命令证据时，文档与 Release 不得宣称入口已经可用。

## 维护者验证与两目标验收

### 维护者本地验证

以下步骤由维护者在作者仓库根目录执行，不是新人安装插件的步骤。它们可以在本地运行，不需要付费 CI，也不会把插件注册到你正在使用的 Codex。

#### 1. 准备工具和工作目录

- 安装 Git、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和 [Rust/rustup](https://rust-lang.org/tools/install/)。对照当前 CI 的工具基线为 uv `0.11.7`、Rust `1.90.0`、Python `3.13.13`；Python 由 uv 自动获取。
- macOS 安装 Xcode Command Line Tools；缺失时执行 `xcode-select --install`。Windows 使用原生 Windows 11 x64、NTFS，在普通用户终端运行验证，准备 Git Bash、系统 Windows PowerShell，以及 Rust MSVC 所需的 [Visual Studio C++ Build Tools 和 Windows SDK](https://rust-lang.github.io/rustup/installation/windows.html)。
- 网络应能访问 Python 下载源、PyPI、crates.io 和固定官方 validator；Provider 检查还需要本机 IPv4/IPv6 回环对照可运行。
- 完整三平台 `--platform all --dry-run` 还需要 Claude Code CLI，因为脚本实际调用 `claude plugin validate --strict`。仅做 Codex 预演时不要求另装 Hermes 或 Claude Code。

首次获取作者源时执行；已有 checkout 则直接进入其真实目录：

```bash
git clone https://github.com/snbc-qihang/agent-skills.git
cd agent-skills
git --version
uv --version
rustup toolchain install 1.90.0 --profile minimal
rustup run 1.90.0 cargo --version
uv run --isolated --no-project --python 3.13.13 python --version
```

公开仓库只读访问无需 GitHub 凭证。最后一条应输出 `Python 3.13.13`。

macOS Terminal 为本次验证设置工具链和仓库外输出目录：

```bash
export RUSTUP_TOOLCHAIN=1.90.0
export ENGINEERING_ASSISTANT_REQUIRE_PROVIDER_SANDBOX=1
EA_CHECK_ROOT="$HOME/Library/Caches/engineering-assistant/validation"
mkdir -p "$EA_CHECK_ROOT"
EA_CHECK_DIR="$(mktemp -d "$EA_CHECK_ROOT/run.XXXXXX")"
mkdir "$EA_CHECK_DIR/work"
export TMPDIR="$EA_CHECK_DIR/work"
```

Windows PowerShell 使用对应设置；后面的验证命令两端相同：

```powershell
$env:RUSTUP_TOOLCHAIN = "1.90.0"
$env:ENGINEERING_ASSISTANT_REQUIRE_PROVIDER_SANDBOX = "1"
$EA_CHECK_DIR = Join-Path ([System.IO.Path]::GetTempPath()) ("ea-validation-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $EA_CHECK_DIR | Out-Null
```

下面的 `uv run --isolated --no-project --with-editable .` 在隔离环境安装当前作者包及依赖，直接使用源码，不需要激活环境，也不更新已有 `.venv` 或项目 lockfile。首次执行需要下载依赖；相关参数见 [uv 命令文档](https://docs.astral.sh/uv/reference/cli/)。

#### 2. 执行仓库门禁

逐条执行；任何一条失败，先处理该失败，不继续宣称验证通过：

```bash
uv run --isolated --no-project --python 3.13.13 --with-editable . python -m unittest discover -s tests -v
uv run --isolated --no-project --python 3.13.13 --with-editable . ea validate --require-sources
uv run --isolated --no-project --python 3.13.13 --with-editable . ea eval --output "$EA_CHECK_DIR/eval.json"
uv run --isolated --no-project --python 3.13.13 --with-editable . python scripts/publish_local.py --platform all --dry-run
```

最后一条会再次执行完整 preflight，并校验 11 个公开 skills、最终 Codex staging 和 Claude Code marketplace。只有 Codex 环境时可先将 `all` 改为 `codex`；这只完成 Codex 预演，完整共享验证仍须补齐 `all`。

通过标准：测试没有 failure/error，`validate` 返回 `status=passed`，eval 达到下述路由门槛，预演返回顶层 `status=passed` 且各平台为 `dry_run_passed`。异平台测试可能显示 skipped，例如 macOS 上的 Windows 原生测试；这不代表被跳过的平台已经通过。当前正式编号不能执行 `publish_local.py --yes`。

#### 3. 保留可检查的构建包

`--dry-run` 会清理自身 staging；需要人工检查的包另行构建到本次仓库外目录。默认构建当前宿主目标，不用跨平台编译代替对应机器验收：

```bash
uv run --isolated --no-project --python 3.13.13 --with-editable . ea build --platform codex --output "$EA_CHECK_DIR/codex"
uv run --isolated --no-project --python 3.13.13 --with-editable . ea verify-package --package "$EA_CHECK_DIR/codex"
uv run --isolated --no-project --python 3.13.13 --with-editable . ea build --platform hermes --output "$EA_CHECK_DIR/hermes"
uv run --isolated --no-project --python 3.13.13 --with-editable . ea verify-package --package "$EA_CHECK_DIR/hermes"
```

两个 `verify-package` 都须返回 `status=passed`。构建可能复用系统临时目录中的原生 launcher 缓存；缓存命中不证明在没有编译工具的新机器上可以从零构建，首次编译仍需前述 Rust 和系统工具。Hermes 构建用于共享源码回归，不扩大首轮 Codex 发行范围。重复验证使用新的输出目录，不覆盖旧包。

#### 4. 执行本机真实 Runtime 资格检查

```bash
uv run --isolated --no-project --python 3.13.13 --with-editable . python scripts/qualify_installation.py --agent codex --output "$EA_CHECK_DIR/runtime-qualification.json"
```

该脚本在临时目录实际构建并准备 Runtime，执行 native launcher、MCP 调用、Hook、持久化任务和受控 Provider 隔离探针；不安装到用户的 Codex 市场。成功时输出 `status=runtime_qualified`，报告中的 `persistent_run`、`feedback_hook` 和协议检查须通过，Provider `qualified=true`、11 项检查及 IPv4/IPv6 对照均须成功。Provider 使用受控诊断 bundle，无需预先下载可选的 UI/UX Pro Max 知识包。

报告中的 `native_marketplace_session=not_executed` 和 `hook_trust=requires_native_host_review` 是明确未执行项，须继续完成下一节的宿主操作。Windows Provider 仍未闭合时，这条命令应保留真实失败，不通过关闭隔离或删除检查换取成功。

质量门槛：

- Routing eval 至少 100 条真实中英文任务。
- Top-1 准确率不低于 90%。
- 无结果率不高于 5%。
- 未确认高风险写入为 0。
- Simulation 不得作为真实产品收益证据。
- Codex 和 Hermes 必须从同一作者源构建并通过摘要校验。

### 新人安装验收

**本节是发行 tag 已准备并核验后的操作步骤，当前固定入口仍待发布；现在不要把以下命令当成已可用入口。** 发布前由维护者在验收机执行，正式推广后再交给新人。

准备 Codex、uv、Git，先完成 Codex 登录。验收机应同时有 App 和原生 CLI；普通使用者只需选用的宿主，不需要 GitHub 登录、Rust、作者 checkout 或手工 Python 环境。使用同一 `CODEX_HOME`，在作者仓库及插件目录之外建立可丢弃的临时项目。

先检查历史安装，再安装；两端命令相同：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer/1.0.0.1" ea-setup doctor --agent codex --json
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer/1.0.0.1" ea-setup install --agent codex --json
```

`doctor` 未安装时不要求 `ready`；明确的历史安装或来源冲突须先按 [历史 2.x 清理步骤](#历史-2x-卸载与清理) 人工处理。缺少控制 CLI 时，`doctor` 不下载工具，检查可能未完成；若唯一缺项是兼容 CLI，`install` 会准备固定官方工具并重新检查。未知项不能当作已清理。

安装返回 `needs_trust`、退出码 2 时，先在真实 Codex 宿主审查并信任 Hook，重开会话，再执行：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer/1.0.0.1" ea-setup doctor --agent codex --hooks-trusted --json
```

只有实际完成宿主信任后才提供 `--hooks-trusted`；它不能替你点击信任。预期 `status=ready`、`runtime_ready=true`、`native_activation=enabled`、版本 `1.0.0.1`，并查看 Provider 隔离结果。原生 CLI 验收机还执行：

```bash
codex plugin list --json
codex plugin marketplace list --json
```

确认 `engineering-assistant` 已从受控市场启用，平台版本为 `1.0.0+build.1`。App 和 CLI 必须分别在临时项目中完成以下实际操作：

1. 请求“使用 engineering-assistant:repo-context 梳理当前临时项目”，确认加载的是已安装 skill。
2. 请求“通过插件 Runtime 的 start 创建 task_id=installation-smoke 的实现任务；先只创建运行，返回 run_id、当前节点和状态文件位置”，确认实际调用 MCP，且临时项目中出现 `.run-artifacts/engineering-assistant/`。
3. 关闭会话，重新打开 App 或 CLI，请求“通过 runs-list 找回 installation-smoke，再用 run-status 读取当前节点”，确认从持久化状态恢复。
4. 实际触发并检查宿主生命周期 Hook，记录对应任务的反馈或使用观测；确认有效信号写入，正常无信号轮次不强行要求产生反馈文件。直接运行脚本或 `doctor --hooks-trusted` 不代替宿主事件。

这些步骤是安装与恢复冒烟检查。更新、重复安装、修复、失败补偿、卸载及完整隔离场景仍按下一节验收，不能仅凭 `ready` 宣布两目标交付通过。更新、修复和卸载的完整命令见[用户安装目标](#用户安装目标)。

### 两目标发行验收

#### 无付费 CI 的候选准备

维护者可在本地两种原生环境生成发行输入，不需要 GitHub Actions 的运行编号。先完成源码评审与提交，两台机器 checkout 同一 commit；未提交或未跟踪的源码不能生成发行记录。准备工具沿用上面的维护者要求，消费者无需这些编译工具。

在一台机器生成一次批次文件，将这个文件原样复制到另一台机器；不要分别创建两个批次：

```bash
uv run --isolated --no-project --python 3.13.13 --with-editable . python scripts/validate_local.py init --output "$EA_CHECK_DIR/batch.json"
```

每台机器执行同一命令，输出目录必须不存在。脚本自动识别本机目标，执行完整单元与原生必需测试、作者源校验、eval、Codex/Hermes 构建、官方校验、Runtime/Hook/Provider 实际检查和隔离 wheel 验证，并复用已构建包；独立本机发布预演仍按前述命令执行。失败时不产生可用于发行的整组通过记录：

```bash
uv run --isolated --no-project --python 3.13.13 --with-editable . python scripts/validate_local.py run --origin "$EA_CHECK_DIR/batch.json" --output "$EA_CHECK_DIR/native"
```

将两个 `native` 目录分别收集到同一仓库外目录，命名为 `macos-arm64`、`windows-x64`。选择 macOS arm64 目录中实际生成的唯一 `.whl` 文件，在下面 `--wheel` 参数填写其完整路径：

```bash
uv run --isolated --no-project --python 3.13.13 --with-editable . python scripts/assemble_release.py --validation-origin "$EA_CHECK_DIR/batch.json" --macos-arm64 "$EA_CHECK_DIR/macos-arm64" --windows-x64 "$EA_CHECK_DIR/windows-x64" --wheel <实际生成的wheel完整路径> --output "$EA_CHECK_DIR/candidate"
```

这条组装命令是填写实际文件路径的维护者模板。两目标必须来自同一源码和同一批次，既有 CI 输入仍可使用原参数。候选固定标记 `local_artifacts_unattested` 和 `support_qualification.status=not_satisfied`：本地验证提供可追溯记录，不证明真实 App/CLI 已验收，也不会推送 tag、注册插件或发布 Release。

#### 真实宿主验收

维护者须准备 macOS 14+ arm64、真实 Windows 11 x64 两种环境，使用同一候选、源码 commit 和对应包；每个目标都完成已认证 App、原生 CLI 与 Provider 验收。Windows Server、模拟测试或在另一架构上构建包不能替代。

App 与 CLI 各记录 21 项场景：首次安装、skill、MCP、Hook、持久化、重开恢复、更新、补偿、卸载、重复安装、修复、uv 升级、uv 移除、缓存清理、installer alias 推进、网络失败、鉴权失败、摘要错误、更新中断、准备失败保留旧版、中文及空格路径；Provider 另记录 11 项隔离与两个网络对照。还须实际验证 `1.0.0.1 → 1.0.0.2` BUILD 更新。

当前没有一条命令能自动替代这些已认证宿主交互，`qualify_installation.py` 与本地验证脚本只证明它们实际执行的检查。验收证据和候选保存在仓库外，按 [内部发行与推广](#内部发行与推广) 的合同与 `prepare/activate` 命令处理；远程推广仍须独立明确授权。


## 作者本机发布入口

统一入口：

```bash
python3 scripts/publish_local.py --platform <codex|hermes|claude-code|all> <--dry-run|--yes>
```

## 无副作用预演

```bash
python3 scripts/publish_local.py --platform all --dry-run
```

预演会运行仓库测试、作者源强校验、真实核心 eval、公开 skill 官方 `quick_validate.py`、三平台最终 staging 构建和包摘要校验，并对最终 Codex staging 包执行官方 plugin validator、核对官方校验摘要与构建摘要，不写入插件目录、marketplace 或平台配置。preflight 原样披露 `ea eval` 的 canary 状态，将本次范围标记为 `repository_validation`、门槛为 `not_required_for_repository_validation`；它不授予正式版发布资格，也不代表真实收益已验证。真实验证流程见 [真实产品 Canary](canary.md)。官方 validator 使用仓库外 `uv` 隔离环境并固定 `PyYAML==6.0.2`；缺少工具、输出超限或校验失败时预演直接失败。

GitHub CI 与本机预演使用同一组固定官方 URL、revision 和 SHA-256，从受控缓存读取并在私有快照执行 validator，不读取开发者电脑上的 `~/.codex`。`uv` 按显式参数、环境变量、PATH 和原生目录发现。校验器环境固定 Python `3.13.13` 和 `PyYAML==6.0.2`。终端用户消费已经通过 CI 的包，不运行作者源门禁。

## 实际发布

```bash
python3 scripts/publish_local.py --platform codex --yes
python3 scripts/publish_local.py --platform hermes --yes
python3 scripts/publish_local.py --platform claude-code --yes
python3 scripts/publish_local.py --platform all --yes
```

实际发布读取 `config/local-publish-policy.json`，要求目标平台已启用、版本与 catalog 一致、源码版本为预发布，并且命令显式提供 `--yes`。当前 `1.0.0.1` 正式编号只允许预演，不能通过本节 `--yes` 安装；须使用验收后启用的内部安装入口。

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
