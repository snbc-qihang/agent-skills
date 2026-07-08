---
name: self-test
description: Use when 代码实现完成后，需要生成并执行自测方案，判断失败是否阻断发布时；Do not use when do not伪造测试结果。
---

# When To Use
- 代码实现完成后，需要生成并执行自测方案，判断失败是否阻断发布时。
- 需要把 quality-contract 中的测试命令、覆盖率、失败原因和风险形成证据时。

# Do Not Use When
- 不要伪造测试结果。
- 不要忽略失败测试或空命令。
- 不要替代发布验证。

# Inputs
- `implementation-summary.md`
- `changed-files-report.json`
- `test-strategy.md`
- `repo_context`

# Do This
- 读取 implementation-summary、changed-files、test-strategy、repo context 和 quality-contract。
- 按 required_commands 执行单元、集成、回归、边界、异常、幂等和一致性测试。
- 记录命令、退出码、关键日志、覆盖率、失败测试和影响范围。
- 输出 self-test-report、test-commands.log、coverage-summary 和 test-risk-report。

# Evidence / Done
- test-commands.log 包含实际执行命令和结果。
- failed-tests.md 对每个失败给出原因、影响和下一步。
- test-risk-report.json 明确是否阻断后续质量门禁。

# Stop / Escalate
- required_commands 缺失、占位或未执行时 blocked。
- 高风险测试豁免或关键测试无法执行时 waiting_for_human_review。

# References / Scripts
- contract.yaml：输入、输出、审批和质量门禁的机器契约。
- references/stage-guidance.md
- scripts/validate_output.py
