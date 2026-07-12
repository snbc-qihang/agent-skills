# 反馈演进能力包

按来源、症状、范围、频率和证据接收反馈。生命周期 Hook 每轮只保留脱敏 capture 元数据，把阻断、失败、返工、人工纠正和范围追加提升为候选事件；普通成功轮次不得制造反馈噪声。

使用稳定摘要对同一平台、事件、会话、轮次和内容做精确去重。候选事件写入目标项目 `.run-artifacts/engineering-assistant/feedback/`，不得保存原始 transcript、凭证、原始 session id 或原始 turn id，也不得通过符号链接逃逸项目目录。

区分可复用知识和任务噪声，聚合复发项并添加回归案例；改变正式 skill、flow、policy 或 eval 行为前必须人工审批。
