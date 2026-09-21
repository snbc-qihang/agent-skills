---
name: diagnosing-bugs
description: 通过复现、最小化、可证伪假设、定向观测、修复和回归证据诊断疑难缺陷或性能退化。
---

本 skill 属于 `teamwork-engineering-assistant`；同名能力只使用当前插件版本。直接选中本 skill 时不为确认选择重新路由；需要 Runtime 时只使用本产品的 MCP 服务，同一目标不同时推进两个插件的运行。

# 缺陷诊断

改变行为前，先围绕用户报告的准确症状建立紧凑且可复现失败的反馈环。

## 操作流程

1. 复现症状并测量出现频率或成本。
2. 在不改变观察故障的前提下最小化反馈环。
3. 列出相互竞争且可证伪的假设。
4. 添加能够区分这些假设的定向观测或测试。
5. 修复有证据支持的根因，删除诊断沉积，并重新运行原始反馈环和回归测试。

非确定性症状读取 [references/flaky-bugs.md](references/flaky-bugs.md)；性能退化读取 [references/performance.md](references/performance.md)。只加载相关分支。

不得修复第一个看似合理的原因，也不得用大范围日志代替假设。
