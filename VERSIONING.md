# 版本规范

`engineering-assistant` 使用四段式产品版本：

```text
MAJOR.MINOR.PATCH.BUILD[-PRERELEASE]
```

- `MAJOR`：公开 skill、核心协议或平台契约发生不兼容变化。
- `MINOR`：向后兼容地增加 flow、capability、pack 或平台能力。
- `PATCH`：修复行为、策略或兼容性问题。
- `BUILD`：不改变产品契约的构建、评测或发布修订。
- `PRERELEASE`：使用 `alpha.N`、`beta.N` 或 `rc.N`。

当前 canonical version 为 `2.3.0.0-rc.1`。

## 平台映射

Catalog、公开 SkillSpec 和构建清单使用完整四段式版本。平台只接受 SemVer 时，adapter 映射为：

```text
2.3.0.0-rc.1 -> 2.3.0-rc.1+build.0
1.2.3.4      -> 1.2.3+build.4
```

本机 Codex 发布会将构建元数据替换为唯一 cachebuster：

```text
2.3.0-rc.1+codex.local-YYYYMMDD-HHMMSS
```

`package-manifest.json` 必须始终记录 canonical version、全部 skill 版本和文件摘要，平台版本不能覆盖产品版本事实。

## 发布约束

- 预发布版本可以发布到本机 Codex 或 Hermes 进行验证。
- 稳定版必须通过全部仓库门禁和真实产品 canary。
- 版本变更必须同步更新 catalog、公开 skills、profile、本机发布策略和相关测试。
- 不通过递增版本号解决缓存问题；Codex 本机更新使用 cachebuster。
