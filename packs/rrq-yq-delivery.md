## GPT-6 适配变更说明

团队版运行、反馈和观测使用独立目录；旧共享目录不自动迁移或合并。

# RRQ/YQ 交付规范包

仅在 `rrq-yq-team` profile 的需求、文档、概要设计、详细设计、发布复盘或知识沉淀节点按需加载。

规范定义唯一来自 `rrq-yq-team-rules` 目录中目标为 `rrq-yq-delivery` 的 54 条规则：信息补全 8 条、文档治理 22 条、概要设计 11 条、详细设计 11 条、知识沉淀 2 条。本文件不复制规则正文。

执行节点必须把实际采用的规则登记到证据 `contract_refs`，格式为 `rule:<rule-id>`。任务通过显式 `requirement_id` 与外部设计注册表固定只读设计快照；完整设计评审稿只写入 `.run-artifacts/teamwork-engineering-assistant/review-packages/<REQUIREMENT-ID>/`，由外部团队评审、合并并维护唯一设计源。
