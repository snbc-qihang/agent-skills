# 本机发布

统一入口：

```bash
python3 scripts/publish_local.py --platform <codex|hermes|all> <--dry-run|--yes>
```

## 无副作用预演

```bash
python3 scripts/publish_local.py --platform all --dry-run
```

预演会运行仓库测试、真实核心 eval、双平台构建和包摘要校验，不写入插件目录、marketplace 或平台配置。

## 实际发布

```bash
python3 scripts/publish_local.py --platform codex --yes
python3 scripts/publish_local.py --platform hermes --yes
python3 scripts/publish_local.py --platform all --yes
```

实际发布读取 `config/local-publish-policy.json`，要求目标平台已启用、版本与 catalog 一致，并且命令显式提供 `--yes`。

## 平台 CLI 发现

发布脚本按以下顺序查找平台注册命令：

1. `CODEX_CLI` 或 `HERMES_CLI` 指定的可执行文件。
2. 当前终端的 `PATH`。
3. macOS 标准应用目录中的 Codex App 内置 CLI，包括 `ChatGPT.app` 和 `Codex.app`。

因此，从 macOS 系统 Terminal 执行时不需要手工把 App 的 `Contents/Resources` 加入 `PATH`。如果 App 或 CLI 位于自定义位置，使用环境变量显式指定：

```bash
CODEX_CLI="/自定义路径/codex" python3 scripts/publish_local.py --platform codex --yes
HERMES_CLI="/自定义路径/hermes" python3 scripts/publish_local.py --platform hermes --yes
```

### Codex

1. 构建带唯一 cachebuster 的 Codex 包。
2. 备份 `~/plugins/engineering-assistant`。
3. 原子替换插件目录。
4. 幂等维护 personal marketplace entry。
5. 执行 `codex plugin add engineering-assistant@personal --json`。
6. 校验安装包摘要；失败时恢复 marketplace 和旧插件。

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
