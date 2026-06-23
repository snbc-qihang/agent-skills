# Code Review 自动报告与质量深度检查改进记录

## 触发信号
团队实际使用 `code-review` 时暴露两个问题：

1. 代码走查不会自动生成完整走查报告，需要用户二次提示。
2. 走查容易只聚焦功能逻辑 bug，缺少代码质量、异味、复杂度、可维护性、安全热点等系统性检查。

## 诊断结论
`code-review` 的 SKILL/contract 已经声明了深度走查、静态分析消费和 HTML 报告要求，但执行层缺少硬动作与硬校验：

- 缺少统一执行入口，例如 `engineering-assistant/scripts/run_code_review.py`，把输入读取、review-comments 生成、Markdown/HTML/blocker-list 输出串起来。
- `skills/code-review/scripts/validate_output.py` 必须强制四个声明产物真实存在。
- `output.schema.json` 必须约束高优先级 finding 的质量维度、代码证据、影响和建议。
- `render_code_review_html.py` 必须由 code-review 阶段自动调用。
- eval 和单元测试必须防止“报告没生成但评审通过”。

## 执行链路
1. 运行 `engineering-assistant/scripts/run_code_review.py`。
2. 读取或发现 `code-quality-report.json`、`static-analysis-report.json`、`changed-files-report.json`、`implementation-summary.md`。
3. 生成 `review-comments.json`、`code-review-report.md`、`blocker-list.md`。
4. 调用 `render_code_review_html.py` 生成 `code-review-report.html`。
5. 运行 `skills/code-review/scripts/validate_output.py` 阻断缺失产物、缺失质量维度、缺失静态分析且仍 succeeded 的结果。

## 验收标准
用户只说“执行代码走查”时，插件必须自动生成四个产物，并在静态分析/质量输入缺失时明确 `block` 或 `require_human_review`，不得输出通过性结论。
