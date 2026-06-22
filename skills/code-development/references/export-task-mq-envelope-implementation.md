# 异步导出任务 MQ 统一消息体实现要点

适用场景：已有异步导出任务 MQ 从扁平消息体迁移到统一 envelope 格式，尤其是待支付订单导出这类“MQ 只触发任务、任务事实在 DB”的实现。

## 目标消息体

```json
{
  "issueId": "消息id",
  "configType": "pendingOrderExportTask",
  "pendingOrderExportTask": {
    "taskId": "任务ID",
    "taskType": "export",
    "businessType": "pendingOrder",
    "eventTime": "事件时间"
  }
}
```

## 实现步骤

1. 先从现有代码确认链路，不要猜：
   - 生产者：`AsyncExportMqSender.send(...)`
   - 消费者：`AsyncExportTaskMqHandler.handle(...)`
   - 分发：`MqStrategyFactory.dispatch(...)` 是否按 routingKey 还是 configType 分发
   - 任务事实源：任务表写入是否先于 MQ 发送
   - 既有 MQ 消息 DTO：先搜索 `MqBasicDto`、`issueId/configType`、业务体字段 DTO（如 `InventoryBasicDto`、`VemActivationBasicDto`），判断是否已有可复用 envelope。

2. 不要为了拼出动态业务体字段继续使用 `Map`。
   - 如果既有 `MqBasicDto` 的 `cooperativeInfo` 字段不符合目标契约（例如目标要求 `pendingOrderExportTask` 字段名），不要硬套 `MqBasicDto`。
   - 采用项目已有“统一外层 + 业务体字段名”的模式，新建专用消息 DTO，例如 `PendingOrderExportTaskMqMessage` + `PendingOrderExportTaskMqBody`。
   - DTO 放在当前业务/能力包内，例如异步导出放 `asyncExport.domain.dto`，避免污染 `common`。

3. 常量集中到 MQ 常量类：
   - root fields：`issueId`, `configType`, `pendingOrderExportTask`
   - body fields：`taskId`, `taskType`, `businessType`, `eventTime`
   - configType 固定值：`pendingOrderExportTask`
   - 外部消息值：`taskType=export`, `businessType=pendingOrder` 等

4. 生产者只包 typed envelope，不把查询条件塞进 MQ：
   - 构造 `PendingOrderExportTaskMqBody` 写 `taskId/taskType/businessType/eventTime`
   - 构造 `PendingOrderExportTaskMqMessage` 写 `issueId/configType/pendingOrderExportTask`
   - `queryConditionJson/queryCondition`、权限快照、文件路径、进度、失败原因继续只落 DB 任务表
   - `eventTime` 用字符串格式输出，避免 JSON 序列化出不稳定的 Java time 对象结构

5. 消费者按 typed envelope 解析：
   - `JSON.parseObject(messageBody, PendingOrderExportTaskMqMessage.class)`
   - 校验 `configType == pendingOrderExportTask`
   - 读取 `pendingOrderExportTask.taskId`
   - 校验 `taskId/taskType/businessType/eventTime` 必填
   - 执行仍只调用 `asyncExportExecutor.execute(taskId)`，不要让 MQ 中 businessType 取代 DB 事实源

6. 保持分发边界：
   - 如果现有 `MqStrategyFactory` 已按 `routingKey=async.export.task` 分发，统一 `configType` 字段不等于要改分发方式。
   - 不要顺手新增 topic/queue；新增队列或死信策略变更应回到 MQ 专项评审。

## 单测要点

- 发送测试断言 root 有 `issueId/configType/pendingOrderExportTask`。
- 发送测试断言 root 不再有 `taskId`。
- nested body 断言四个必填字段齐全。
- 发送测试除了检查 JSON 外部契约，还应 `JSON.parseObject(..., PendingOrderExportTaskMqMessage.class)` 验证 typed DTO 可反序列化。
- 消费/分发测试用专用 DTO builder 构造消息，再 `JSON.toJSONString(dto)`，不要手写大段 JSON 字符串或用 Map 构造。
- 继续断言 `queryConditionJson/queryCondition` 不出现在 MQ 消息体中。
- 增加旧版扁平消息回归断言：root 上只有 `taskId`、没有业务体字段时，消费者不得再触发执行，防止 listener 仍兼容旧格式导致契约漂移。
- 发送端测试不只校验 JSON 结构，还要把捕获到的消息反序列化成新 DTO，验证新增 DTO 能覆盖真实发送契约。

## 常见坑

- 只改 sender 不改 listener：消费者继续从 root 读 `taskId`，上线后无法触发导出。
- 把数据库内部枚举直接暴露为消息值：设计要求小写业务语义值时，需要做边界转换，例如 `PENDING_ORDER -> pendingOrder`。
- 把 `businessType` 当事实源：MQ 是触发消息，消费者应以 taskId 读 DB 任务记录作为事实源。
- 捕获异常后只打日志：如果系统异常被吞，Rabbit 重试/死信不会发生；实现阶段要区分可忽略业务消息和系统失败。
