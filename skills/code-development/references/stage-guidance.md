# Code Development 阶段指引

检查项：
- 执行前必须读取 artifacts/_control/task-context.agent.md、implementation-contract.json、quality-contract.json 和任务规则包
- 最小必要变更
- 设计映射
- 风险标记
- 测试覆盖
- 变更摘要
- 完成实现后必须运行 build_traceability_report.py 刷新 artifacts/_control/traceability-matrix.json 和 docs/human-readable/traceability-report.html
- FW1 框架选型必须来自设计、repo_context 或用户确认；缺失时主动询问
- FW2 Java/Spring 持久化默认使用 mybatis-plus；直接 JDBC 必须有评审批准
- FW3 实现必须遵循现有仓库 mapper/repository/service 分层和依赖
