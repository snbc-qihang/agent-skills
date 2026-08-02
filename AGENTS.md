# AGENTS.md

## 仓库目标

- 本仓库维护 `engineering-assistant` 的平台无关协议、运行内核、公开 skills、内部 flows、按需 packs、评测和平台 adapter。
- `catalog/`、`skills/`、`packs/`、`schemas/` 与 `src/` 是作者源；仓库内不得保存发布包、生成镜像或历史过程数据。
- 产品和公开 skill 使用四段式版本，当前版本为 `2.0.0.0-rc.1`。
- 开发者信息统一为 `sunliming625@gmail.com`。

## 修改规则

- 元数据修改 `catalog/`，skill 指令修改 `skills/`，专业规则修改 `packs/`，协议修改 `schemas/` 和对应模型，执行语义修改 `src/engineering_assistant/`。
- Skill 只保留 `name` 与 `description` frontmatter；分支资料通过 `references/` 渐进加载。
- 公开 ID、JSON key、schema enum、CLI 子命令和状态值保持英文稳定；面向用户的内容使用简体中文。
- 运行状态和证据写入目标项目 `.run-artifacts/engineering-assistant/`，不得写入插件源码目录。
- 构建产物只能写到仓库外临时目录。
- 仓库只保留当前架构和当前运维文档，不新增迁移矩阵、升级记录、实施过程、审批历史或发布执行历史。

## 验证要求

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

## 风险边界

- 高风险动作、生产动作、稳定版发布、删除历史、降低安全等级和范围外实现必须人工确认。
- 本机发布必须使用 `scripts/publish_local.py`、当前发布策略和显式 `--yes`；不得手工覆盖插件目录或跳过备份、注册与安装后验证。
- 当前本机发布策略不得允许稳定版发布或产品仓库修改。
- 失败门禁必须修复，或明确标记为 `blocked` / `waiting_for_input`。
