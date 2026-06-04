# Codex Runtime Policy Pack

这些文件是给目标业务项目复制启用的运行时策略模板。插件目录只提供模板，不直接替目标项目写入 `.codex/` 或 `AGENTS.md`。

安装插件不等于自动启用这些运行时策略；hooks、rules、tool policy 均不作为插件内置 hooks 自动生效。将本目录复制到目标项目并完成 trust review 后，才可按项目真实风险边界启用。

## 文件
- `config.toml`：推荐的 Codex 沙箱、审批和 profile 配置。
- `profiles/readonly_review.toml`：只读评审 profile 示例。
- `profiles/controlled_fix.toml`：受控修复 profile 示例。
- `rules/default.rules`：高风险命令规则模板。
- `policies/tool-policy.yaml`：工具调用 policy-as-code，采用 JSON/YAML 子集格式，便于脚本稳定解析。
- `hooks/pre_tool_use_policy.py`：PreToolUse 命令守卫模板。

## 使用方式
1. 将本目录内容复制到目标项目 `.codex/`。
2. 按项目真实构建、测试、发布流程调整规则。
3. 将任务运行产物写入目标项目 `artifacts/_control/`。
4. 不要把插件目录作为 `--root` 传给控制面脚本。
5. 变更 `profiles/readonly_review.toml` 或 `profiles/controlled_fix.toml` 前先完成 trust review，并记录项目审批人。
