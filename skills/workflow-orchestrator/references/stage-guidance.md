# Workflow Orchestrator 阶段指引

检查项：
- 阶段选择
- 状态流转
- 错误处理
- 重试
- 审批暂停
- 断点恢复
- 产物路由
- 执行日志
- design-only 完成前运行 high-level/detailed/database/mq/redis 专项 validator
- validator-summary 汇总 stage、validator、failed_rule、error_message、suggested_repair
- 任一专项 validator 失败时 workflow 总状态不得 succeeded
- waiting_for_human_review 不得宣称 approved/final/succeeded
- defect-analysis 根因分析
- DG2-DG5 产物路由时区分 run artifact 与正式留存文档，防止中间过程文档进入正式目录
