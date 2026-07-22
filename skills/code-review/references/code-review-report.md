# 代码走查报告契约

每次 teamwork 代码走查必须交付独立 Markdown 报告。用户指定路径时使用该路径；否则写入目标项目：

`.run-artifacts/engineering-assistant/code-reviews/<REVIEW-ID>/code-review-report.md`

优先使用用户或 Runtime 提供的 `REVIEW-ID`。没有时使用规范化的 `<repository>-<candidate-short-sha>`；非 Git 阶段审计使用稳定任务或阶段 ID。只能覆盖绑定同一 base、head 和范围的既有报告；比较点变化时使用新的 ID。

报告至少包含：

1. 结论与门禁状态。
2. 仓库、base、head、merge-base、固定 diff、变更规模、排除范围和证据边界。
3. Findings：编号、级别、位置、证据、触发条件、确定失败行为、影响和最小修复要求。
4. 代码异味专项：逐类记录 `fail`、`pass` 或 `not_evaluated`，并给出已检查文件或规则证据；不得用六维表中的复杂度/冗余两格代替专项走查。
5. 六维质量门禁：正确性、复杂度、冗余、性能、架构、测试质量。
6. 测试、构建、静态检查和未评估项；工具失败与代码缺陷分开记录。
7. 设计追踪状态：未激活时写 `not_applicable`；激活时记录 requirement、设计源、评审包、追踪矩阵和 `base_digest` 复核结果，输入不全时写 `waiting_for_input`。
8. 待确认事项、合并前最低条件和实际 Runtime 状态。

最终答复只摘要最重要 finding、门禁、验证限制和报告绝对路径，不重复粘贴整份报告。报告是本 skill 的完成产物；聊天摘要不能替代报告文件。
