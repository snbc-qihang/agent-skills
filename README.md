# Mac 候选安装与真实验收

本页提供 `1.0.0.1` 共享核心改造的固定候选，用于另一台 Mac 的新人安装实验。候选尚未取得两目标正式交付资格，Windows 11、已认证 App/CLI 和真实 Hook 验收仍待完成。不会据此创建 Release、推进正式安装入口或宣称产品 Canary 完成。

- 系统：macOS 14+，Apple Silicon（`uname -m` 为 `arm64`）。Mac Intel 不支持。
- 前置：安装并登录 Codex App 或原生 CLI，终端能执行 Git 和 uv（验证基线 uv 0.11.7）。公开下载无需 GitHub 账号或 token。
- 不需要手工安装 Python、Node、Rust、选择平台包或取得维护者的本机文件。
- 源码：`e769d7df86886532a0f62418af66cbd035ef4395`；不可变候选 tag：`candidate/codex/1.0.0.1/macos-arm64/20261020.1`。
- 包摘要：`sha256:fbaed3c1f02c2a96fab0554bbafc266db830dad8658065dc537b578036de1a90`。完整机器元数据见 [candidate.json](candidate.json)。

## 一条命令安装

在普通用户的 Terminal 执行，不使用 sudo：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@e769d7df86886532a0f62418af66cbd035ef4395" ea-setup install --agent codex --source "snbc-qihang/agent-skills@candidate/codex/1.0.0.1/macos-arm64/20261020.1" --marketplace engineering-assistant-candidate
```

安装器从 GitHub 获取固定源码和预编译插件，核对原生 Git 来源与包摘要，自动准备固定 Runtime 和需要的控制 CLI，再注册候选 marketplace、验证完整 Provider 隔离并启用插件。需要联网访问 GitHub、Python/依赖和固定官方工具下载源。运行时使用宿主临时目录，构建与分发不依赖维护者临时包。

若发现 2.x 历史安装或未知残留，安装器停止并给出确切来源和人工步骤；不会替你删除历史目录或共享缓存。新人测试请优先使用没有旧工程助手插件的 Mac。已安装旧候选时先按其原教程卸载，并依据检测结果处理旧市场来源；不要直接覆盖或手工删除宿主缓存。相同候选已安装时执行下面的检查。

## 本候选的本地目录

共享核心独立于 Codex，默认使用操作系统标准用户数据目录：

```text
~/Library/Application Support/engineering-assistant/
├── cores/<核心摘要>/              # Runtime、skills、packs、catalog、schemas
├── python/<分布摘要>/<Python标识>/ # 固定解释器
├── environments/<环境摘要>/       # Python 依赖
└── bindings/codex/                # 不可变版本绑定
```

本候选的原生插件入口：

```text
~/.codex/plugins/cache/engineering-assistant-candidate/engineering-assistant/1.0.0+codex.candidate-20261020-1/
```

`CODEX_HOME` 或 `--agent-home` 已配置时，入口位于所选宿主目录。安装输出会显示实际共享核心和宿主入口；`doctor --json` 中的 `data_home`、`shared_core`、`package` 是对应确切路径。核心按摘要固定，不使用可覆盖的全局 current-core；旧 Runtime 和其他宿主入口继续保留。项目记录位于 `<验收项目>/.run-artifacts/engineering-assistant/`。

本次 Mac 候选只提供 Codex 包。Claude Code、Cursor adapter 的源码和本地验证不等于已取得对应工具的发行与真实验收资格，不能只修改本命令的 `--agent` 来安装其他宿主。

## 信任与检查

输出提示 Runtime 已准备、等待 Hook 信任时，属于待人工步骤，退出码可能为 2。在真实 Codex 中审查并信任本插件当前 Hook 定义，关闭旧会话并打开新会话。

只读检查：

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@e769d7df86886532a0f62418af66cbd035ef4395" ea-setup doctor --agent codex --marketplace engineering-assistant-candidate --json
```

实际完成信任审查后，可加 `--hooks-trusted` 记录本次用户确认。该参数不授予信任、不持久化审查声明，也不证明真实 Hook 已执行。必须另外观察实际事件。

## 修复与卸载

```bash
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@e769d7df86886532a0f62418af66cbd035ef4395" ea-setup repair --agent codex --marketplace engineering-assistant-candidate
uvx --isolated --refresh --python 3.13.13 --from "git+https://github.com/snbc-qihang/agent-skills.git@e769d7df86886532a0f62418af66cbd035ef4395" ea-setup uninstall --agent codex --marketplace engineering-assistant-candidate
```

卸载调用原生命令移除候选插件；保留 Runtime、市场目录与共享缓存。该候选固定不变，后续候选使用维护者提供的新入口；正式更新命令仍待两目标验收后推广。

## 人工验收与结果回传

请在仓库外新建不含业务数据的验收项目，分别从真实已登录的 Codex App 和原生 CLI 执行：

1. 新会话中加载 engineering-assistant skill，观察真实 MCP 调用；执行一个小的多步骤任务，在项目 `.run-artifacts/engineering-assistant/` 中核对持久化 run。
2. 审查并信任 Hook，触发插件工具和一次明确纠正，观察实际反馈 artifact。不能只提供信任声明或 doctor。
3. 完全退出并重新打开 App/CLI，在新会话恢复上述 run；验证安装后无需额外 PATH 或 uv 配置。
4. 执行检查、修复和卸载，记录实际行为。其余跨版本 BUILD 更新、失败补偿、中文及空格路径、uv 升级或移除、缓存清理等场景继续按[源码运维合同](https://github.com/snbc-qihang/agent-skills/blob/e769d7df86886532a0f62418af66cbd035ef4395/docs/operations/local-publish.md#内部发行与推广)验收，尚未执行的项目标记待完成。

回传 macOS 版本和架构、Codex App/CLI 版本、uv/Git 版本、候选 tag、源码提交、安装命令与退出码、doctor JSON，以及每项实际结果（通过/失败/未执行）和对应证据。原始记录保存在仓库外受控目录；对外提交前去除 token、邮箱、个人路径和业务内容。故障请提供脱敏错误原文，不发送登录文件。

本候选的维护者技术验证包括 854 项仓库测试（828 通过、26 项其他平台跳过、0 失败）、四宿主共享核心一致性、核心缺失/篡改拒绝启动、显式修复保留原内容，以及完整仓库测试、核心 eval、Codex/Hermes 构建、官方格式校验、隔离 wheel，以及 Mac Runtime MCP、Hook、持久化和 Provider 隔离检查。它们不替代本节真实宿主验收，也不证明 Windows 11 已通过。
