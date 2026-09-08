# 确定性设计输入

本页适用于正式团队需求设计、领域设计 flow 或当前节点明确要求冻结设计源的任务。普通源码梳理、小接口设计和内联语义分析不要求补齐这些输入。

用户提供 requirement_id、外部源绝对根目录及可定位的注册资料后，按 v2 `DesignSourceRegistry` 组织 requirements、repository、existing-design、interfaces、data、deployment 六类输入及领域上下文。来源不全据实记录状态。

调用 `engineering_assistant_design_source_intake`，参数为 project_root、source_root、registry 对象、intake_id。它读取外部声明内容并在目标项目 `.run-artifacts/engineering-assistant/design-inputs/` 写入副本、摘要、v2 注册表和 manifest；外部源不修改。工具不是零写入操作，用户明确要求全程只读时只分析现有源并说明尚未冻结。

设计 run 使用返回的项目相对 registry 路径作为 design_source_ref。冻结输入不能表示已通过业务或架构审批。普通上下文变化只进入上下文详细设计，长期系统边界变化才生成 HLD/ADR；DB、MQ、Redis 等资源内容保留在专项设计。

提交评审前调用 `engineering_assistant_design_source_recheck`（project_root、design_source_ref），返回 current 或 stale。当前实现比较 intake 声明的全部源摘要；源范围应与本任务相关。变更项必须重新核对并建立新 intake，不凭 Git 无冲突推定业务兼容。
