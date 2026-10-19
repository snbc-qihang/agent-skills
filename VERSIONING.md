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

当前 canonical version 为 `1.0.0.1`。这是当前功能的内部产品重编号，不表示回退源码、删除历史或完成产品收益验证。

## 平台映射

Catalog、公开 SkillSpec、Runtime 与构建清单使用完整四段式版本。Python 包使用 PEP 440 版本 `1.0.0.1`；平台只接受 SemVer 时，adapter 映射为：

```text
1.0.0.1      -> 1.0.0+build.1
1.0.0.1-rc.1 -> 1.0.0-rc.1+build.1
```

SemVer 的构建元数据不参与优先级比较。安装器依据 canonical version、实际原生选择和包摘要验证更新，不能仅凭 SemVer 排序判断 `1.0.0.2` 高于 `1.0.0.1`。首次内部发行须真实验收这项 BUILD 更新。

本机预发布的 Codex 包使用唯一 cachebuster：

```text
1.0.0-rc.1+codex.local-YYYYMMDD-HHMMSS
```

`package-manifest.json` 必须始终记录 canonical version、全部 skill 版本和文件摘要，平台版本不能覆盖产品版本事实。Runtime 常量、catalog、Python 元数据、本机策略和当前文档须保持一致。

## 交付资格

- 预发布版本可以通过本机发布脚本进行验证；正式编号允许执行无副作用预演，但当前本机策略禁止实际发布正式版。
- 正式内部交付只通过受控 `internal/codex/<版本>` 路径，必须通过完整仓库门禁及 macOS arm64/x64、真实 Windows 11 x64 的 App、CLI、Provider 验收，并在入口启用前验证实际私有 HTTPS 固定命令。
- 内部交付资格不等于产品稳定版或收益资格。公开稳定版和产品稳定版晋级仍须全部仓库门禁、真实产品 Canary 及人工审查，不接受 simulation 替代。
- 版本变更必须同步更新 catalog、公开 skills、profile、本机发布策略和相关测试。
- 不通过递增版本号解决缓存问题；Codex 本机更新使用 cachebuster。
- 同一产品版本不能替换不同发行内容。`internal/installer/<版本>` 与 `internal/codex/<版本>` tag 不覆盖；移动入口 `internal/installer` 只通过受控 CAS 推广到已验收源码。
- GitHub 仓库保持私有。私有 Release 提供版本说明和教程，消费者仍从不可变 Git 发行 tag 获取插件；无需 PyPI、npm 或公开插件市场。
