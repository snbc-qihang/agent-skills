## GPT-6 适配变更说明

团队版运行、反馈和观测使用独立目录；旧共享目录不自动迁移或合并。

# 反馈演进能力包

按来源、症状、范围、频率和证据接收反馈。Codex Hook 只匹配本插件 namespaced MCP 工具，Hermes Hook 只在插件 adapter 内运行；两者只保留无原文 capture 元数据，把可观测的阻断、失败、返工、人工纠正和范围追加提升为候选事件。普通任务不得启动本插件 Hook 或制造反馈噪声。

使用稳定摘要对同一平台、事件、会话、轮次和内容做精确去重。候选事件写入目标项目 `.run-artifacts/teamwork-engineering-assistant/feedback/`，不得保存原始 transcript、凭证、原始 session id 或原始 turn id；允许保存单向哈希的可关联伪名引用和时间戳，并必须在文档中披露。运行 ledger 在 Codex 插件工具完成或 Hermes 插件轮次成功汇总后删除；事件、效率候选和处置按目标项目的合规策略留存，且不得通过符号链接逃逸项目目录。

通过不可变 `FeedbackDisposition` 记录接受、解决、拒绝或延后，区分可复用知识和任务噪声，聚合复发项并导出受治理的回归提案；只有 `accepted_for_evolution` 可以标记为可复用。处置不得覆盖原事件，汇总和演进导出不得回显处置原因、actor_ref 或处置 evidence_refs；人工或 CI 输入的这些字段不会自动脱敏，不得包含凭证、个人信息或业务秘密。演进导出固定为只读评审输入，不自动添加回归案例，也不修改正式资产；改变正式 skill、flow、policy 或 eval 行为前必须人工审批。
