# Assistant Feedback Capture 阶段指引

检查项：
- 识别 skill 执行失败、用户纠正、反复返工、评审遗漏、第三方工具失败、上下文漂移、文档噪声和真实验收失败
- 每条事件包含来源任务、触发 skill、现象、用户纠正摘要、证据路径、影响级别、重复次数、建议动作和 regression 候选标记
- 目标项目证据写入 artifacts/_control/feedback/，中心候选写入 feedback-inbox/ 或等价生成目录
- 同类用户纠正重复次数达到阈值时，必须标记 regression_case_candidate=true
- 缺少证据时只能记录 rejected_noise 或 needs_more_evidence，不能进入正式演进候选
