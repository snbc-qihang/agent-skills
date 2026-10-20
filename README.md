# agent-skills

`engineering-assistant` 的作者仓库，为工程任务提供按需 skills、可恢复流程、证据与安全门禁。

- 版本：`1.0.0.1`；许可证：[MIT](LICENSE)。
- 首轮发行：Codex App 与原生 CLI；macOS 14+ **Apple Silicon**、原生 Windows 11 x64。
- Mac Intel 不在支持范围。Hermes、Claude Code、Linux 共享源码保留回归。
- 开发者：`sunliming625@gmail.com`。

**正式安装入口尚未发布。** Mac Apple Silicon 的验收人员使用独立的 [GitHub 候选安装教程](https://github.com/snbc-qihang/agent-skills/blob/candidate/codex/1.0.0.1/macos-arm64/20261020.2/README.md)。本候选包含共享核心目录改造，供真实验收，不表示两目标已通过。正式 tag、Release 与移动安装入口仍须在两个目标真实验收完成后推广。

## Mac 候选：一条命令安装

在另一台 macOS 14+ Apple Silicon Mac 准备并登录 Codex，确保终端已有 Git 和 uv，然后执行：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@e769d7df86886532a0f62418af66cbd035ef4395" ea-setup install --agent codex --source "snbc-qihang/agent-skills@candidate/codex/1.0.0.1/macos-arm64/20261020.2" --marketplace engineering-assistant-candidate
```

无需取得维护者本机文件或安装 Python、Node、Rust。安装后在 Codex 审查并信任 Hook，再重开会话；等待信任时退出码可能为 2，不代表安装失败。检查、修复、卸载和结果回传要求见上述候选教程。下节命令是正式推广后的入口，目前尚不可用。

## 普通用户：安装与更新

首次准备 Codex、Git、uv，并在 Codex 完成登录；不需要手工安装 Python、Rust、Node 或选择系统安装包。公开仓库下载无需 GitHub 账号或 token。

- [Codex 安装](https://developers.openai.com/codex/quickstart)
- [Git 安装](https://git-scm.com/install/)
- [uv 安装](https://docs.astral.sh/uv/getting-started/installation/)

工具已具备时，发行推广后 Mac 与 Windows 使用同一条命令：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer/1.0.0.1" ea-setup install --agent codex
```

安装后在 Codex 审查并信任 Hook，然后重新打开会话。等待信任或重开会话会单独说明，不视为环境故障。安装器自动准备固定 Runtime、注册受控本地 marketplace，并核对实际选择的版本。

发布后更新使用已验收的移动入口：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer" ea-setup update --agent codex
```

固定版本检查：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@internal/installer/1.0.0.1" ea-setup doctor --agent codex --json
```

修复、卸载、首次工具准备和旧版清理见[安装与本机发布](docs/operations/local-publish.md)。发现历史 2.x 安装时，安装器提供确切位置和人工步骤；不自动接管或删除。共享 Python、其他插件、作者源码和项目运行证据不在清理范围。

## 安装位置与多工具接入

核心使用操作系统的标准用户数据目录，独立于 Codex、Claude Code、Cursor：

| 系统 | 共享数据根目录 |
| --- | --- |
| macOS | `~/Library/Application Support/engineering-assistant/` |
| Windows | `%LOCALAPPDATA%\engineering-assistant\` |
| Linux（源码回归） | `${XDG_DATA_HOME:-~/.local/share}/engineering-assistant/` |

`cores/<摘要>/` 保存不可变的 Runtime、skills、packs、catalog 和 schemas；同一核心由多个宿主复用。`python/`、`environments/` 保存固定解释器及依赖，`bindings/<agent>/` 保存各宿主的版本绑定。安装器输出“共享核心”和“宿主入口”两个位置，`doctor --json` 提供 `data_home`、`shared_core` 与 `package`。

宿主继续管理自己的插件入口：Codex 使用原生 marketplace/cache，Claude Code 使用原生 plugin，Cursor 使用 `~/.cursor/plugins/local/engineering-assistant/`。原生缓存可保留发行包副本；日常 Runtime 从校验过的共享核心加载。卸载一个入口保留共享核心及其他宿主。项目运行证据仍位于目标项目 `.run-artifacts/engineering-assistant/`。

各工具没有统一的插件配置文件，不能只指定一个文件夹就保证全部自动加载。安装器通过 `--agent codex`、`--agent claude-code` 或 `--agent cursor` 选择宿主 adapter，保留原生发现、启用和信任流程，不改写其他插件的配置。详见[共享核心与原生入口](docs/operations/local-publish.md#共享核心与原生入口)。

**共享核心改造已进入上述 Mac 候选，真实宿主验收尚未完成。** 正式安装入口仍未启用。Cursor 当前为源码和本地资格验证入口，尚无已验收的 GitHub 发行命令；新增 adapter 不扩大首轮 Codex 两目标的发行矩阵。

## 使用方式

安装后直接描述任务，无需日常手动管理 `ea` 状态机：

```text
梳理当前仓库上下文，说明这个改动的影响范围。
复现并修复这个问题，给出相关验证结果。
按原始需求与仓库规范评审当前变更。
```

小任务直接使用原语；有依赖的多步骤任务进入持久化 flow。已有授权在范围与风险不变时复用。TDD 按行为和项目要求选择；正式质量、审批、安全和发布门禁继续生效。

## 公开 Skills

| Skill | 职责 |
| --- | --- |
| `engineering-assistant` | 选择最小充分的原语或流程 |
| `repo-context` | 源码上下文、接口和影响范围 |
| `research` | 一手资料研究与证据 |
| `decision-interview` | 收敛事实之外的重大决定 |
| `domain-modeling` | 上下文、业务规则和领域模型 |
| `wayfinder` | 跨会话目标与当前前沿 |
| `prototype` | 用可丢弃原型回答设计问题 |
| `codebase-design` | 模块边界、小接口与变化隔离 |
| `tdd` | 适用行为的真实红绿循环 |
| `diagnosing-bugs` | 复现、假设和回归证据 |
| `code-review` | 固定 diff 的需求与规范评审 |

Skill 保持独立可选；详细规则和专业知识按触发条件读取 `references/` 与 packs。保留 7 个 flows：`shape`、`design`、`implement`、`review`、`release`、`domain-design`、`evolve`。正式领域设计和基线审批继续使用完整合同。

## 源码职责

| 位置 | 内容 |
| --- | --- |
| `catalog/` | Skill、flow、policy、pack、provider 和 profile 的机器定义 |
| `skills/`、`packs/` | 按需指令与专业知识 |
| `schemas/` | 公共数据协议 |
| `src/engineering_assistant/runtime/` | 路由、状态、证据、质量、反馈、MCP 与轻量 CLI |
| `src/engineering_assistant/platforms/` | 宿主 adapter、Hook、系统进程与隔离实现 |
| `src/engineering_assistant/installer/` | 来源校验、安装、更新、修复与失败恢复 |
| `src/engineering_assistant/tools/` | 作者构建、评测、本机发布与远程推广；不进入消费者包 |
| `native/launcher/` | 固定 Runtime 的原生启动器 |
| `scripts/`、`tests/`、`evals/` | 维护入口、共享回归与行为评测 |
| `docs/architecture/`、`docs/operations/` | 当前架构和运维说明 |

运行记录只写入目标项目 `.run-artifacts/engineering-assistant/`。构建和验收产物保存在仓库外；作者分支不保存生成镜像或过程历史。内部字段、CLI 子命令与状态使用稳定英文，用户说明使用简体中文。

## 开发者：当前可执行的入口

开发者在源码 checkout 中执行作者命令。验证与构建需要固定开发工具，普通安装用户不需要这些工具。

```bash
uv run --isolated --no-project --python 3.13.13 --with-editable . ea --help
uv run --isolated --no-project --python 3.13.13 --with-editable . ea validate --require-sources
uv run --isolated --no-project --python 3.13.13 --with-editable . ea eval
```

完整单元测试、Codex/Hermes 构建、官方 validator、无副作用本机发布预演、无需付费 CI 的候选准备和两目标真实验收，统一见[维护者验证与两目标验收](docs/operations/local-publish.md#维护者验证与两目标验收)。`scripts/validate_local.py` 验证一次完整仓库合同并复用已构建包；独立本机发布预演仍使用 `scripts/publish_local.py --dry-run`。

## 验收与发布边界

- 两目标必须绑定同一源码、候选和包摘要，分别完成真实已认证 App、原生 CLI、Hook、恢复及完整 Provider 隔离验收。
- Windows Server CI、`doctor` 或 simulation 不能替代 Windows 11 宿主验收；本地记录为 `local_unattested`。
- Routing eval 至少 100 条真实中英文任务，top-1 不低于 90%，无结果率不高于 5%，未确认高风险写入为 0。
- 流程治理中的审批、证据来源、六维质量门禁与 Provider 隔离保留。Hook 反馈仅作为非阻断候选，不自动修改正式规则。
- 未验收不推广。内部推广只能使用 `scripts/promote_internal_release.py` 的预演与显式 `--yes`；不得手工覆盖插件目录、跳过备份或修改 Codex 缓存。
- 公开源码与正式内部交付均不自动取得公开稳定版或产品收益 Canary 资格。

## 文档

- [当前架构与执行合同](docs/architecture/overview.md)
- [安装、更新、排障、开发者验证与发行验收](docs/operations/local-publish.md)
- [真实产品 Canary](docs/operations/canary.md)
- [四段式版本规范](VERSIONING.md)
- [第三方声明](THIRD_PARTY_NOTICES.md)
