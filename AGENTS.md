## GPT-6 适配变更说明

澄清用户指令作用域和授权复用；保留作者源分层、质量与发布边界。

# AGENTS.md

## 仓库目标

- 本仓库维护 `engineering-assistant` 的平台无关协议、运行内核、公开 skills、内部 flows、按需 packs、评测和平台 adapter。
- `catalog/`、`skills/`、`packs/`、`schemas/` 与 `src/` 是作者源；仓库内不得保存发布包、生成镜像或历史过程数据。
- 产品和公开 skill 使用四段式版本，当前版本为 `1.0.0.1`。
- 开发者信息统一为 `sunliming625@gmail.com`。
- 仓库以 MIT 许可证公开，分发包携带许可证和第三方声明；公开源码不自动取得公开稳定版资格。

## 指令与授权

在平台系统／开发者指令和实际权限范围内，用户当前明确要求优先于项目与 Skill 中可调整的工作方式。已有授权在动作、目标、范围及风险未变时直接复用；必要人工审批仍按原合同执行。

## 修改规则

- 元数据修改 `catalog/`，skill 指令修改 `skills/`，专业规则修改 `packs/`，协议修改 `schemas/` 和对应模型，执行语义修改 `src/engineering_assistant/`。
- Skill 只保留 `name` 与 `description` frontmatter；分支资料通过 `references/` 渐进加载。
- 公开 ID、JSON key、schema enum、CLI 子命令和状态值保持英文稳定；面向用户的内容使用简体中文。
- 运行状态和证据写入目标项目 `.run-artifacts/engineering-assistant/`，不得写入插件源码目录。
- 构建产物只能写到仓库外临时目录。
- 仓库只保留当前架构和当前运维文档，不新增迁移矩阵、升级记录、实施过程、审批历史或发布执行历史。
- 首轮内部发行只包含 Codex 的 macOS 14+ arm64/x64 与 Windows 11 x64，App 与原生 CLI 使用同一完整功能及安全合同。Hermes、Claude Code 和 Linux 共享源码保留回归，不扩大首轮发行矩阵。
- 内部安装器从 `internal/installer` 或同版本不可变 `internal/installer/<版本>` 源码 tag 核对真实 Git 来源，选择同版本不可变 `internal/codex/<版本>` 发行；生成发行树只进入仓库外临时目录和专用发行 tag，不进入 `main`、`teamwork` 或作者 checkout。
- 正式内部交付仅以完整仓库门禁及三目标真实 App、CLI、Provider 验收取得资格，不宣称产品收益 Canary 完成；公开稳定版和产品稳定版晋级继续遵守真实产品 Canary 门槛。
- 历史 2.x 安装和备份由用户自行卸载与清理；安装器只读检查并提供确切位置和人工步骤，不自动接管或删除。共享 Python、其他插件、作者源码和目标项目运行证据不在清理范围内。

## 验证要求

按变更影响选择检查；Runtime、schema、adapter 或发布路径变更执行下列完整验证，纯文案调整检查相关 skill/引用与构建即可。测试使用隔离临时夹具；已授权整改可连续修复本次引入的失败并重跑受影响检查，无需逐步确认。通过后没有新增变化或未解决风险时不重复扩大验证。

```bash
python3 -m unittest discover -s tests -v
ea validate --require-sources
ea eval
ea build --platform codex --output <仓库外临时目录>
ea build --platform hermes --output <仓库外临时目录>
python3 scripts/publish_local.py --platform all --dry-run
```

- Routing eval 至少覆盖 100 条真实中英文任务，top-1 不低于 90%，无结果率不高于 5%，未确认高风险写入为 0。
- 不得使用 simulation 证明真实收益；产品 canary 必须引用真实运行证据。
- 公开 skill 必须通过官方 `quick_validate.py`。
- Codex manifest 必须通过官方插件校验。
- 内部发行必须另有绑定候选、源码与包摘要的三目标人工验收，包含真实已认证 Codex App、原生 CLI 与完整 Provider 隔离证据。Windows Server CI、`doctor`、信任声明和 simulation 不能代替 Windows 11 宿主验收；缺失时保持发行推广阻断。

## 风险边界

- 高风险动作、生产动作、稳定版发布、删除历史、降低安全等级和范围外实现必须人工确认。
- 本机发布必须使用 `scripts/publish_local.py`、当前发布策略和显式 `--yes`；不得手工覆盖插件目录或跳过备份、注册与安装后验证。
- 当前本机发布策略不得允许稳定版发布或产品仓库修改。
- 失败门禁必须修复，或明确标记为 `blocked` / `waiting_for_input`。
- 内部推广只能使用 `scripts/promote_internal_release.py`：先预演，`prepare` 阶段核对候选完整真实验收后以显式 `--yes` 推送两个不可变 tag；`activate` 阶段另核对三目标 HTTPS 固定命令验收后发布团队试用 Release 并 CAS 更新 installer alias。固定仓库必须公开且未归档；公开 tag 和 Release 只携带白名单验收摘要，原始验收、命令和宿主记录保存在仓库外受控目录。本机发布授权不能自动替代远程推广授权；此路径只允许已验收的内部交付，不授权公开或产品稳定版发布。
