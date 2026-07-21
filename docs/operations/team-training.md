# Teamwork 团队研发培训教程（Windows/macOS）

## 1. 培训目标

本教程面向产品、架构师、上下文 Owner、研发、测试和插件维护者。培训完成后，团队成员应能使用 `teamwork-engineering-assistant`：

- 以明确的 `requirement_id` 和外部设计事实源启动研发任务；
- 基于固定设计快照产出符合模板、可直接评审的 HLD 或上下文详细设计；
- 完成需求、设计、代码、测试和发布证据的双向追踪；
- 在多人并行时识别 `stale` 评审稿并完成 rebase；
- 在 Windows、WSL2 和 macOS 上使用同一研发流程，不把平台差异带入设计合同。

建议培训时长为 90 分钟：

| 环节 | 时间 | 产出 |
| --- | ---: | --- |
| 产品定位与角色 | 10 分钟 | 明确插件与外部设计团队的边界 |
| 安装和环境检查 | 15 分钟 | 插件可见、项目可读、设计源可读 |
| 确定性设计输入 | 15 分钟 | 固定需求设计快照 |
| 需求设计与研发演练 | 30 分钟 | 独立评审包、实现和测试证据 |
| 并行冲突演练 | 10 分钟 | 识别 `stale` 并给出 rebase 顺序 |
| 复盘和验收 | 10 分钟 | 完成培训验收清单 |

## 2. 插件介绍

`teamwork-engineering-assistant` 是团队研发助手，不只是文档生成器。它把仓库事实、外部设计事实源、团队规范、工程方法和人工门禁串成完整研发流程，覆盖：

- 需求事实梳理、范围澄清和验收条件建模；
- 系统边界、领域模型、HLD、ADR 和上下文详细设计；
- DB、MQ、Redis、IAM、接口和前端等专项设计；
- 工作切片、TDD、代码实现、缺陷诊断和代码评审；
- 需求、设计、代码、测试、发布证据追踪；
- 多人并行时的设计摘要检查、`stale` 识别和 rebase 建议；
- 发布准备、发布后验证、实现偏差和外部设计基线回写建议。

插件内置 11 个公开 skills，平台可以自动选择，也可以由用户显式点名：

| Skill | 能完成的事情 |
| --- | --- |
| `engineering-assistant` | 把跨阶段任务路由到最小充分 skill 或完整 flow |
| `repo-context` | 从代码、配置和外部设计源提取影响范围与证据 |
| `domain-modeling` | 澄清领域边界、Owner、聚合、不变量和术语 |
| `codebase-design` | 设计模块、接口、依赖方向、实现 seam 和可测试结构 |
| `decision-interview` | 在事实明确后收敛产品、架构和验收决策 |
| `wayfinder` | 管理跨会话的大型任务、当前前沿和待决策事项 |
| `prototype` | 构建可丢弃原型，验证交互、状态或技术方案 |
| `tdd` | 通过红绿循环实现行为和回归覆盖 |
| `diagnosing-bugs` | 复现、最小化、验证假设并完成缺陷回归 |
| `code-review` | 按需求与仓库规范评审设计、代码和质量证据 |
| `research` | 基于一手资料研究外部 API、标准和工程事实 |

插件会输出完整评审稿和研发证据，但不会替代业务 Owner、架构师、代码 Owner 或发布负责人的批准。

## 3. 先统一三个边界

### 3.1 外部设计源是唯一事实源

现有 HLD、ADR、领域设计、上下文详细设计、模板和维护规则由外部团队统一维护。teamwork 只读这些输入，为当前需求生成 `reviewing` 评审稿；它不得覆盖外部设计源，也不得把文档自行提升为 `approved` 或 `final`。

HLD 和上下文详细设计都按 `0..N` 集合处理。实际读取和输出数量由注册表及需求影响范围决定，不限定为一份。

### 3.2 每个需求有独立评审包

评审产物只写入目标项目：

```text
.run-artifacts/engineering-assistant/review-packages/<REQUIREMENT-ID>/
```

多份 HLD 使用 `02-<design-key>-high-level-design.review.md`；单份场景兼容 `02-high-level-design.review.md`。上下文详细设计使用 `03-<context>-detailed-design.review.md`。

### 3.3 插件不代替人工批准

产品、架构、上下文和专项 Owner 负责设计批准，代码 Owner 负责代码确认，发布负责人负责真实发布。Agent 可以校验证据并报告阻断项，不能代替这些角色批准。

## 4. 团队角色与责任

| 角色 | 启动前提供 | 评审时负责 | 完成时负责 |
| --- | --- | --- | --- |
| 产品/需求 Owner | 需求事实、范围、验收条件 | 需求与设计关联、业务规则 | 验收结论 |
| 架构师 | 系统边界和架构规则 | HLD、ADR、依赖方向 | 基线回写建议确认 |
| 上下文 Owner | 领域边界、聚合和不变量 | 上下文详细设计 | 实现偏差确认 |
| 研发 | 代码仓库、分支、实现约束 | 可实现性、接口和测试 seam | 代码、测试和提交证据 |
| 测试 | 测试范围和质量要求 | 验收条件与测试映射 | 测试结果和共同回归结论 |
| 外部文档团队 | 当前注册表和设计基线 | 合并候选评审稿 | 更新唯一设计源版本 |
| 插件维护者 | 已验证的插件版本 | 插件问题响应 | 团队 marketplace 更新 |

## 5. Windows/macOS 兼容策略

### 5.1 统一部署入口

团队从经过评审的仓库版本部署插件，统一使用 README 已有的 `scripts/publish_local.py` 命令。必须先执行 `--dry-run`，通过后再显式执行 `--yes`；不得手工复制构建产物、插件缓存或 marketplace 文件。

macOS 直接在终端执行。Windows 因官方校验器和仓库安全文件操作依赖 POSIX 语义，使用 WSL2 执行同一脚本，并通过 `--codex-home` 指向 Windows 用户的 `%USERPROFILE%\.codex`。这样脚本仍负责测试、构建、备份、平台注册和安装后摘要验证，Windows 桌面端重启后使用同一安装结果。

Codex 桌面端当前支持 macOS 和 Windows，Windows 可使用原生 PowerShell Agent 或 WSL2 Agent。官方入口见 [Windows App](https://learn.chatgpt.com/docs/windows/windows-app)、[Plugins](https://learn.chatgpt.com/docs/plugins) 和 [Windows Sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox)。

### 5.2 平台选择矩阵

| 场景 | 推荐运行方式 | 项目路径示例 | 命令行 |
| --- | --- | --- | --- |
| Windows 工具链、仓库在 Windows 盘 | Windows 原生 Agent | `D:\work\yq` | PowerShell |
| Linux 工具链、仓库在 WSL 文件系统 | WSL2 Agent | `/home/dev/work/yq` | Bash |
| Windows 盘仓库由 WSL2 Agent 使用 | WSL2 Agent | `/mnt/d/work/yq` | Bash |
| macOS | macOS Agent | `/Users/dev/work/yq` | zsh/bash |

一个任务中必须使用与当前 Agent 运行环境一致的路径。不要向原生 Windows Agent 提交 `/mnt/d/...`，也不要向 WSL2 Agent 提交 `D:\...`。切换 Windows 原生与 WSL2 Agent 后应重启应用并重新打开任务。

### 5.3 命令对照

普通研发流程主要通过自然语言调用插件。只有排查本地文件时才需要以下命令：

| 目的 | Windows PowerShell | macOS/WSL2 |
| --- | --- | --- |
| 查看当前位置 | `Get-Location` | `pwd` |
| 确认设计注册表 | `Test-Path "D:\work\yq\artifacts\project-inspection\90-design-basis\30-document-governance\04-document-registry.yaml"` | `test -f "/Users/dev/work/yq/artifacts/project-inspection/90-design-basis/30-document-governance/04-document-registry.yaml"` |
| 查看 Git 状态 | `git status --short --branch` | `git status --short --branch` |
| 查找评审包 | `Get-ChildItem ".run-artifacts\engineering-assistant\review-packages" -Recurse -File` | `find .run-artifacts/engineering-assistant/review-packages -type f` |
| Python 3 | `py -3`，或团队固定的 `python.exe` | `python3` |

教程中的 `/` 相对路径是项目协议，不要求 Windows 磁盘路径也写成 `/`。JSON 中的 Windows 反斜杠必须转义为 `\\`；在普通提示词中可以直接写 `D:\work\...`。

### 5.4 文件与 Git 兼容

- 所有 Markdown、YAML 和 JSON 使用 UTF-8；不要用系统默认编码改写设计文档。
- 不批量转换换行符。提交前检查 diff，避免把实际设计变化淹没在 CRLF/LF 噪声中。
- 项目、代码仓库和设计源可以位于不同目录，但 `design_source.root` 必须是当前 Agent 可读的绝对路径。
- Windows 网络盘或同步盘可能在任务中途更新文件。培训和正式需求优先使用本地 Git 工作副本，并记录对应 revision。
- Windows 原生与 WSL2 不要同时修改同一工作副本；需要切换时使用独立 clone 或 worktree。

## 6. 部署插件

### 6.1 部署前置依赖

部署机器必须具备：

- Git；
- Python 3.9 或更高版本，以及项目依赖 `jsonschema`；
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)，供官方 skill/plugin 校验器使用；
- 目标平台 CLI：Codex 部署需要 `codex`，Hermes 部署需要 `hermes`；
- Codex 自带的官方 `skill-creator` 校验脚本；Codex 平台部署还需要 `plugin-creator` 校验脚本；
- 访问依赖源和下载安装包所需的网络与组织代理配置。

`skill-creator`、`plugin-creator` 是部署门禁依赖，不是团队日常研发时需要主动调用的 teamwork skill。缺少任一必需校验器时，部署必须失败，不能跳过。

### 6.2 macOS 安装 Codex 版

安装基础工具；已有工具时只需确认版本：

```bash
brew install git python uv
curl -fsSL https://chatgpt.com/codex/install.sh | sh
git --version
python3 --version
uv --version
codex --version
```

进入团队提供的、已经评审并固定版本的插件仓库：

```bash
cd /absolute/path/to/agent-skills
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .

python3 scripts/publish_local.py --platform codex --dry-run
python3 scripts/publish_local.py --platform codex --yes
```

部署 Hermes 时把 `codex` 改为 `hermes`；同时部署两个平台时改为 `all`。这是 README 中的统一安装命令，不再增加另一套复制式安装流程。

### 6.3 Windows 安装 Codex 版

Windows 日常使用可以运行原生 Agent，但本仓库部署脚本必须从 WSL2 执行。先在管理员 PowerShell 安装 WSL2：

```powershell
wsl --install -d Ubuntu
```

重启 Windows，进入 Ubuntu 后安装基础工具和 Codex CLI：

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip curl
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

启动一次 `codex` 完成登录和系统 skills 初始化，然后检查部署门禁：

```bash
codex --version
uv --version
test -f "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py"
test -f "$HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py"
```

在 WSL2 中进入仓库，创建开发环境，并把 `<WindowsUser>` 替换为实际 Windows 用户目录名：

```bash
cd /mnt/d/work/agent-skills
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .

python3 scripts/publish_local.py --platform codex --dry-run \
  --codex-home "/mnt/c/Users/<WindowsUser>/.codex"
python3 scripts/publish_local.py --platform codex --yes \
  --codex-home "/mnt/c/Users/<WindowsUser>/.codex"
```

脚本成功后完全退出并重启 Windows ChatGPT/Codex 桌面端。不要从 PowerShell 原生运行该发布脚本，也不要把 WSL 的 `~/.codex` 误当成 Windows 桌面端的 `%USERPROFILE%\.codex`。

### 6.4 部署验证

1. 命令结果为 `status: passed`，目标平台结果为 `published`。
2. 记录 `canonical_version`、`plugin_version` 和 `payload_digest`。
3. 打开 Plugins 页面或输入 `/plugins`，确认 `teamwork-engineering-assistant` 已安装并启用。
4. 新建任务，输入“请使用 teamwork-engineering-assistant 梳理当前仓库上下文”。
5. 确认能看到插件公开 skill，并且 Runtime MCP 工具可用。
6. 失败时使用脚本输出的 `backup` 回滚；不要手工覆盖 cache。

### 6.5 培训讲师准备

讲师应准备：

- 一个不连接生产环境的演练代码仓库；
- 一个包含 HLD、至少两个上下文详细设计、模板和注册表的演练设计源；
- 一个包含 2 至 4 个验收条目的示例需求；
- 一个可在演练中更新的目标设计文档，用于制造摘要变化；
- Windows 原生、WSL2、macOS 至少两种环境的学员配对。

## 7. 外部 Skills、Plugins 和 MCP

依赖必须按下表区分。不要把“可能增强某类任务”写成所有成员的统一前置条件。

| 类别 | 内容 | 是否必须单独安装 | 失败时处理 |
| --- | --- | --- | --- |
| 插件内置 | 11 个公开 skills、团队 flows、rules、packs、profiles、Runtime MCP | 否，随 teamwork 一起安装 | 插件部署失败，阻断使用 |
| 部署门禁 | Git、Python、`jsonschema`、`uv`、目标平台 CLI、官方 `skill-creator`/`plugin-creator` 校验器 | 是，仅插件维护者或部署机需要 | 阻断发布，禁止跳过校验 |
| 固定外部 Provider | `ui-ux-pro-max`，只用于前端设计和产品原型评审 | 否，macOS 按需配置 | 未配置或校验失败时回退插件原生能力 |
| 任务级 Skills | Draw.io、数据库设计检查、SQL 检查、可观测性影响分析、分支差异分析等 | 否，仅对应任务需要 | 声明能力不可用，使用原生证据流程或交由具备能力的成员处理 |
| 任务级 Plugins | GitHub、浏览器/Chrome、Computer Use 等 | 否，仅对应外部系统或 UI 任务需要 | 不执行依赖该系统的步骤，不影响其他研发任务 |
| 组织 MCP | CodeGraph、可观测性、浏览器自动化、数据库只读查询等 | 否，由项目和安全策略决定 | 回退到源码、日志或人工提供的受信证据，并显式记录缺口 |

### 7.1 插件内置能力无需重复安装

teamwork 的 11 个公开 skills 和 Runtime MCP 已包含在发布包中。安装插件后不应再次复制这些 skill，也不需要对 Runtime MCP 执行 `codex mcp add`。如果 `/plugins` 能看到插件但 Runtime 工具不可用，应按插件部署故障处理，而不是再注册一个同名 MCP。

产品借鉴的其他开源方法已经融合为当前 pack 或规则，不是运行时依赖，也不要求团队成员安装对应仓库。

### 7.2 按需安装外部 Skills

只有任务明确需要、组织已经审查来源时才安装外部 skill。常见组合如下：

| 任务 | 可选 Skill | 主要产物 |
| --- | --- | --- |
| 架构图、流程图、ER/UML | `drawio-skill` | 可编辑图源和渲染校验 |
| 数据库方案评审 | `db-design-check` | 模板完整性和数据库规范问题 |
| SQL 变更评审 | `sql-check` | SQL 正确性、索引和性能风险 |
| 服务调用影响分析 | `alibaba-observability-change-analysis` | 上下游调用与接口影响证据 |
| 分支测试范围分析 | `git-branch-diff-analysis` | 变更清单和测试建议 |

优先从组织批准的插件或 skill 源安装。若团队以目录方式分发，维护者必须同时提供来源、固定 revision 和摘要。macOS/WSL2 示例：

```bash
mkdir -p "$HOME/.codex/skills"
cp -R "<approved-skill-source>/drawio-skill" "$HOME/.codex/skills/drawio-skill"
test -f "$HOME/.codex/skills/drawio-skill/SKILL.md"
```

Windows PowerShell 示例：

```powershell
$skillRoot = "$env:USERPROFILE\.codex\skills"
New-Item -ItemType Directory -Force -Path $skillRoot
Copy-Item -Recurse -Force "<approved-skill-source>\drawio-skill" "$skillRoot\drawio-skill"
Test-Path "$skillRoot\drawio-skill\SKILL.md"
```

替换目录名即可安装其他已批准 skill。安装后重启应用，在新任务中显式点名验证。外部 skill 的输出只能作为当前任务证据，不能绕过 teamwork 的需求追踪、人工批准或质量门禁。

### 7.3 配置固定的前端设计 Provider

`ui-ux-pro-max` 是插件唯一声明的可选外部 Provider，来源固定为 [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) 的 revision `3da52ff1cab1be91848072ec1be5f493d730fd5f`。不要直接安装仓库最新版本代替固定来源。

macOS 配置示例：

```bash
git clone https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git \
  "$HOME/.local/share/teamwork-providers/ui-ux-pro-max-skill"
git -C "$HOME/.local/share/teamwork-providers/ui-ux-pro-max-skill" \
  checkout 3da52ff1cab1be91848072ec1be5f493d730fd5f
export ENGINEERING_ASSISTANT_UI_UX_PRO_MAX_ROOT="$HOME/.local/share/teamwork-providers/ui-ux-pro-max-skill"
```

Runtime 会再次校验 bundle 摘要，Provider 输出只是不可信建议，失败时自动回退 `native-engineering`。当前 Provider 只在具备受限执行沙箱的 macOS 上运行；Windows 和 WSL2 不要安装它，直接使用原生前端能力。团队若要持久配置环境变量，应使用组织批准的启动配置，不要把个人绝对路径提交进项目仓库。

### 7.4 按需安装 Plugins

通过 Codex 的 Plugins 页面安装组织批准的插件并完成对应登录：

- GitHub：读取 Issue、PR、检查结果和评审线程；
- 浏览器或 Chrome：查看真实页面、执行前端验收和渲染复核；
- Computer Use：仅在没有更窄 API/CLI 且必须操作本机 UI 时使用。

未使用 GitHub、浏览器或桌面 UI 的需求不需要这些插件。安装后新建测试任务确认只读能力和授权范围；涉及提交、合并、发布或外部消息的动作仍必须获得对应授权。

### 7.5 按需配置组织 MCP

外部 MCP 可通过 Codex 设置中的 MCP Servers 页面配置，也可由维护者使用官方 CLI：

```bash
codex mcp add <server-name> -- <approved-command> <args>
codex mcp list
```

在任务中可用 `/mcp` 检查工具是否加载。团队共享配置优先放在项目 `.codex/config.toml`，个人凭据通过环境变量或 OAuth 提供，不得写入教程、项目配置或提示词。

| MCP 类型 | 使用场景 | 建议权限 | 不可用时回退 |
| --- | --- | --- | --- |
| CodeGraph/代码索引 | 大仓库调用链、符号和影响范围 | 仓库只读 | `rg`、构建工具和目标文件证据 |
| 可观测性 | 真实调用方、错误、性能和发布验证 | 查询只读、限定环境 | 受信日志/截图/导出证据，注明时效 |
| 浏览器自动化 | 页面流程和前端回归 | 测试环境、限定域名 | 人工验收或仓库测试 |
| 数据库 | Schema、执行计划和只读核验 | 只读账号、限定库表 | DDL、迁移文件和 DBA 证据 |

不要为了“能力齐全”默认接入可部署、可变更云资源的高权限 MCP。例如 Alibaba CloudOps MCP Server 同时提供部署和运维动作，只能在组织审查后使用短期凭据、工具 allowlist 和人工批准；普通研发培训不安装它。任何 MCP 缺失都必须显式记录证据缺口，不能伪造查询结果。

### 7.6 开始任务前的依赖声明

研发在提示词中只声明本需求真正需要的附加能力：

```text
本需求使用 teamwork-engineering-assistant。
必需外部能力：CodeGraph MCP（只读）、drawio-skill。
可选外部能力：GitHub Plugin；不可用时只输出本地评审包，不创建 PR。
禁止能力：生产数据库写入、云资源部署、外部设计源写入。

请先报告上述能力是否可用和当前授权边界；缺少必需能力时停止对应步骤，
不要用推测结果替代工具证据，也不要安装未批准依赖。
```

## 8. 确定性设计输入

每次任务都要显式提供需求编号和设计源。不要说“使用上次的设计文档”，也不要让 Agent 自行猜测目录。

### 8.1 macOS 示例

```json
{
  "requirement_id": "REQ-2026-001",
  "design_source": {
    "root": "/Users/dev/work/yq/artifacts/project-inspection",
    "registry": "90-design-basis/30-document-governance/04-document-registry.yaml"
  }
}
```

### 8.2 Windows 原生示例

```json
{
  "requirement_id": "REQ-2026-001",
  "design_source": {
    "root": "D:\\work\\yq\\artifacts\\project-inspection",
    "registry": "90-design-basis/30-document-governance/04-document-registry.yaml"
  }
}
```

### 8.3 WSL2 示例

```json
{
  "requirement_id": "REQ-2026-001",
  "design_source": {
    "root": "/mnt/d/work/yq/artifacts/project-inspection",
    "registry": "90-design-basis/30-document-governance/04-document-registry.yaml"
  }
}
```

启动后检查快照至少包含：

- 注册表摘要和总体 `design_source_digest`；
- 实际登记的全部 HLD、ADR、领域设计和上下文详细设计；
- 每份输入的文档编号、状态、版本、Owner 和摘要；
- HLD、详细设计及专项模板；
- 架构影响规则和文档维护规范。

输入文档处于 `reviewing` 时仍可作为本需求的确定性输入，但必须保留原状态，不得解释成已批准。

## 9. 标准需求研发演练

### 9.1 第一步：需求事实与影响分析

复制以下提示词，并替换尖括号内容：

```text
请使用 teamwork-engineering-assistant 插件执行 team-delivery flow。

任务输入：
<粘贴 requirement_id 和 design_source JSON>

需求事实：
- 背景：<为什么要做>
- 范围：<本次必须完成什么>
- 非目标：<明确不做什么>
- 验收条件：
  - <REQ-ID>-AC-01：<可验证条件>
  - <REQ-ID>-AC-02：<可验证条件>
- 已知约束：<兼容性、性能、安全或发布日期>

请先只读固定外部设计输入，分离需求事实、代码事实、假设和未知项；识别所有受影响 HLD、上下文详细设计、接口和专项资源。HLD 与详细设计数量由实际影响范围决定，不设人为数量限制。先输出影响评估和待决策事项，不要开始编码，也不要覆盖外部设计源。
```

通过标准：

- 每条验收条件有稳定编号；
- 影响上下文和 Owner 明确；
- 未确认业务规则留在待决策事项；
- 普通上下文变化不生成 HLD；系统级影响明确后才生成 HLD/ADR。

### 9.2 第二步：生成设计评审包

```text
继续使用已固定的本需求设计快照。根据已确认的影响范围生成完整、符合外部模板、可直接评审的设计评审包。

要求：
1. 每份评审稿状态必须为 reviewing。
2. 每份评审稿声明 requirement_id、base_document_number、base_version、base_digest。
3. 按影响范围生成全部需要的 HLD 和上下文详细设计，不限制数量。
4. HLD 长期正文不得混入一次性任务步骤；DB、MQ、Redis、IAM 进入专项差异。
5. 07-requirement-design-traceability.yaml 必须逐条关联需求、设计章节，并预留代码目标和测试用例。
6. 06-design-change-summary.md 必须包含新增、修改、删除、明确不变、冲突、推荐合并顺序和共同回归范围。
7. 执行评审包完整性、模板、占位符、链接和追踪校验。

不要开始实现，等待产品、架构、上下文和专项 Owner 评审。
```

预期目录：

```text
.run-artifacts/engineering-assistant/review-packages/REQ-2026-001/
├── 01-impact-assessment.md
├── 02-<design-key>-high-level-design.review.md       # 仅系统级影响时，允许多份
├── 03-<context>-detailed-design.review.md            # 每个受影响上下文一份
├── 04-interface-and-specialty-delta.yaml
├── 05-implementation-and-test-plan.md
├── 06-design-change-summary.md
├── 07-requirement-design-traceability.yaml
└── 08-review-checklist.md
```

### 9.3 第三步：批准后实现

只有在受信人工设计批准已经绑定后，才使用以下提示词：

```text
设计评审已由以下 Owner 完成：<列出产品、架构、上下文和专项评审证据>。

请先重新检查所有目标设计文档的 base_digest。若任一目标已变化，停止批准流程，将对应评审稿标记为 stale，并给出 rebase 方案。若摘要未变化：

1. 按验收条件选择边界清晰的纵向切片。
2. 在确认的公共 seam 上执行 TDD 红绿循环。
3. 实现保持在批准范围内。
4. 把实际代码目标、测试用例和提交证据补入追踪矩阵。
5. 执行仓库规定的测试、构建、静态检查和代码评审门禁。

不要执行真实发布；完成后输出实现证据、未解决风险和设计偏差。
```

### 9.4 第四步：发布后闭环

```text
基于外部受信系统提供的发布和验证证据，更新本需求追踪矩阵：

- 实际代码提交；
- 测试与回归结果；
- 发布或回滚结果；
- 实现相对评审设计的偏差；
- 建议外部团队回写的文档及章节。

在外部团队更新唯一设计源并提供新文档版本前，需求保持未闭环。Agent 不得直接修改外部设计源或自行把评审稿标记为 final。
```

## 10. 多人并行与冲突处理演练

### 10.1 团队规则

- 修改不同上下文详细设计的需求可以并行。
- 修改同一 HLD 或同一上下文详细设计的需求也可以并行设计，但每份评审稿必须记录自己的 `base_digest`。
- 先合并者改变外部基线后，后续评审稿必须标记 `stale`，重新生成或 rebase。
- Git 无文本冲突不能证明聚合、不变量、状态或契约没有设计冲突。
- Owner 通过设计变更摘要决定业务冲突、合并顺序和共同回归范围。

### 10.2 培训演练

1. A、B 两组从相同设计摘要启动不同需求。
2. A 组先完成评审并由讲师更新演练设计源中的目标文档。
3. B 组提交评审前重新检查 `base_digest`。
4. B 组应得到 `stale`，不得继续批准。
5. B 组基于最新文档重新评估新增、修改、删除和明确不变内容。
6. 两组共同确认合并顺序、契约回归和跨上下文测试范围。

冲突处理提示词：

```text
重新读取本需求显式指定的外部设计注册表，并逐一比较评审稿中的 base_digest。

对每个变化目标：
- 标记 stale；
- 列出旧基线到新基线的差异；
- 判断聚合、不变量、流程、状态、接口和资源是否冲突；
- 给出保留、重写或移除本需求设计内容的建议；
- 给出推荐合并顺序和共同回归范围。

不要仅依据 Git 是否冲突下结论，不要覆盖外部设计源。
```

## 11. 培训验收清单

每位学员应独立完成以下检查：

- [ ] 能在 Windows 原生、WSL2 或 macOS 中确认当前 Agent 运行环境。
- [ ] 能使用 README 的 `publish_local.py` 命令完成 `--dry-run`，并由维护者执行显式 `--yes` 安装。
- [ ] 能区分插件内置能力、部署门禁和任务级外部依赖，不重复安装 Runtime MCP。
- [ ] 能在需要时安装一个组织批准的 skill 或 Plugin，并验证其可用性与授权范围。
- [ ] 能配置或检查一个只读组织 MCP，缺失时能声明证据缺口和降级方案。
- [ ] 能提供当前环境可读的绝对 `design_source.root`。
- [ ] 能解释 Windows JSON 路径为什么需要转义反斜杠。
- [ ] 能固定设计快照，并识别输入文档的编号、版本、状态和摘要。
- [ ] 能根据影响范围生成多份 HLD 或详细设计，而不是假设固定数量。
- [ ] 能生成无占位符、状态为 `reviewing` 的独立评审包。
- [ ] 能从需求条目追踪到设计章节、代码目标和测试用例。
- [ ] 能通过摘要变化识别 `stale`，并阻断批准。
- [ ] 能区分 Git 冲突与设计冲突。
- [ ] 能在人工批准后进行 TDD 和实现。
- [ ] 能在发布后记录实现偏差和外部基线回写建议。

## 12. 常见问题

### 插件在 Plugins 页面不可见

确认团队 marketplace 已添加、插件名称和版本正确、组织策略允许安装，然后重启桌面端或新建任务。仍不可见时把 marketplace 来源、插件版本和错误信息交给插件维护者，不要手工覆盖缓存目录。

### Windows 路径提示不存在

先确认当前使用的是 Windows 原生 Agent 还是 WSL2 Agent。原生 Agent 使用 `D:\...`，WSL2 使用 `/mnt/d/...`。JSON 中反斜杠要写成 `\\`。网络盘还需确认当前桌面应用账号具备读取权限。

### macOS 终端找不到 `codex`

普通研发人员可直接从桌面端 Plugins 页面安装。插件维护者从终端发布时，仓库脚本会依次检查显式 `CODEX_CLI`、`PATH` 和 macOS App 内置 CLI；细节见[本机发布](local-publish.md)。

### 外部 Skill、Plugin 或 MCP 不可用

先判断它是本需求的“必需”还是“可选”能力。必需能力不可用时只停止依赖它的步骤并报告阻断；可选能力按第 7 节的规则降级。不要临时安装未审查来源，也不要把推测结果写成工具证据。teamwork 内置 skill 或 Runtime MCP 不可用则属于插件部署故障，不能按外部依赖降级。

### 设计源可以读取，但评审稿被标记为 stale

这是正常的乐观并发保护，表示目标文档在任务启动后发生变化。基于最新基线 rebase，并重新进行相关 Owner 评审；不要跳过检查。

### 生成了不需要的 HLD

检查 `01-impact-assessment.md` 是否确认了服务边界、数据主权、依赖方向或其他长期系统级变化。未命中系统级影响时删除候选 HLD，只保留受影响上下文的详细设计。

### 两名研发修改同一设计文档怎么办

允许并行设计。两份评审稿分别绑定启动时摘要；先合并者更新基线，后合并者 rebase。Owner 必须审查业务不变量、状态和契约，不能只看 Git。

## 13. 培训讲师复盘模板

```text
培训批次：<日期/团队>
插件版本：<版本>
覆盖环境：Windows 原生 / WSL2 / macOS
参与角色：产品 / 架构 / 上下文 Owner / 研发 / 测试

完成情况：
- 安装与启用：<通过人数/总人数>
- 确定性设计输入：<通过人数/总人数>
- 评审包生成：<通过人数/总人数>
- stale/rebase 演练：<通过人数/总人数>
- 需求设计代码测试追踪：<通过人数/总人数>

阻断项：
- <环境、权限、路径、版本或流程问题>

后续动作：
- <责任人、动作、完成时间>
```

培训复盘只记录当前问题和改进行动，不作为设计批准、代码批准或发布批准证据。
