# Workflow Orchestrator 阶段指引

检查项：
- 阶段选择
- 状态流转
- 信息收集完成判定
- 设计目标规划
- 缺失信息识别
- 主动沟通与方向确认
- preflight 未 ready 时不得生成正式设计文档
- 错误处理
- 重试
- 审批暂停
- 断点恢复
- 产物路由
- 执行日志
- design-only 完成前运行 high-level/detailed/database/mq/redis 专项 validator
- validator-summary 汇总 stage、validator、failed_rule、error_message、suggested_repair
- 任一专项 validator 失败时 workflow 总状态不得 succeeded
- self-review findings 驱动自动修复
- unresolved blocker 阻断 approved/final
- waiting_for_human_review 不得宣称 approved/final/succeeded
- 人工评审反馈分类后增量修正，只有核心方案变化才整套重生
- defect-analysis 根因分析
- DG2-DG11 产物路由时区分 run artifact、正式留存文档、控制面、人审入口和 TL 候选，防止中间过程文档或具体需求事实进入团队插件
