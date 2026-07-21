# 确定性设计输入

## 输入合同

设计或研发任务必须显式给出：

```json
{
  "requirement_id": "REQ-xxx",
  "design_source": {
    "root": "/absolute/path/to/project-inspection",
    "registry": "90-design-basis/30-document-governance/04-document-registry.yaml"
  }
}
```

`root` 必须是绝对目录，`registry` 和全部读取目标必须位于该目录内。使用 `engineering_assistant_design_source_resolve` 读取注册表，记录全部 HLD、ADR、领域设计、上下文详细设计、模板、架构影响规则和维护规范的摘要。HLD 和上下文详细设计均按 `0..N` 集合返回，不设业务数量上限；注册表总体规模仍受防滥用安全上限约束。使用 `engineering_assistant_design_source_read` 只读取返回快照中登记的路径或文档编号。

快照只绑定当前 `requirement_id`，不得跨任务复用。输入文档处于 `reviewing` 也可以作为确定性基线，但这不表示 Agent 可以把其状态提升为 `approved` 或 `final`。

## 影响判断

- 服务边界、数据主权、依赖方向或其他长期系统级架构变化：按受影响范围生成一份或多份完整 HLD 和适用 ADR 评审内容。
- 普通上下文行为变化：按受影响范围生成一份或多份完整详细设计评审稿。
- DB、MQ、Redis、IAM 等资源级变化：进入专项设计或专项差异，不写入 HLD 长期正文。

提交评审前使用 `engineering_assistant_design_source_check` 按每个目标文档的 `base_digest` 复核。同一目标摘要变化时标记 `stale` 并 rebase；其他上下文变化不阻断当前目标，但仍应在变更摘要中评估契约或不变量冲突。
