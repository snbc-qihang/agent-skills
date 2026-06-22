# 导出任务查询与时间 API 调整经验

适用范围：待支付订单异步导出、类似业务异步导出任务查询接口。

## 查询任务接口契约

当用户要求 `getExportTask` 不再按 `taskId` 查询详情时，接口语义要整体收口为“列表查询”：

- 入参使用导出业务类型 `businessType`，例如订单维度、商品维度。
- 返回当前用户、当前租户、当前业务类型下的任务列表。
- SQL 侧按 `create_time DESC` 排序并 `LIMIT 10`。
- 不再保留按 `taskId` 查询详情的 Controller/Facade/Service 方法。
- 下载接口仍可保留 `taskId`，因为下载必须定位具体任务；不要误删下载链路。

推荐链路：

- Controller: `getExportTask(@PathVariable("businessType") String businessType)` 返回 `CommonResp<List<AsyncExportTaskDetailResp>>`
- Facade: `listTasks(String businessType)` 注入 token 的 tenant/user 上下文
- TaskService: `listTasks(String businessType, String tenantId, String userId)`
- Mapper: `selectLatestTasks(tenantId, createUserId, businessType)`

SQL 约束：

```sql
WHERE tenant_id = #{tenantId}
  AND create_user_id = #{createUserId}
  AND task_type = 'EXPORT'
  AND business_type = #{businessType}
ORDER BY create_time DESC
LIMIT 10
```

## Date API 禁用替换

导出功能中不要继续使用过期/旧式 Date API：

- 禁用：`java.util.Date`
- 禁用：`new Date()`
- 禁用：`SimpleDateFormat`
- 禁用：`DateUtil.getSystemDateTime()`

替换方式：

- 实体、DTO、快照中的时间点字段使用 `LocalDateTime`。
- 仅日期字段才使用 `LocalDate`。
- 当前时间使用 `LocalDateTime.now()`。
- 文件名时间格式化使用：
  `LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"))`

常见字段：

- `AsyncExportTaskEntity.startTime/finishTime/createTime/updateTime` -> `LocalDateTime`
- `AsyncExportTaskDetailResp.createTime` -> `LocalDateTime`
- `PendingOrderExportQuerySnapshot.snapshotTime` -> `LocalDateTime`

## 验证建议

至少做这些确定性检查：

- 搜索导出范围内是否仍存在：
  - `java.util.Date`
  - `new Date(`
  - `SimpleDateFormat`
  - `DateUtil.getSystemDateTime()`
- 搜索生产代码是否仍存在旧详情接口：
  - `getTask(String taskId`
  - `/tasks/{taskId}` 详情路径
  - `CommonResp<AsyncExportTaskDetailResp> getExportTask`
- 保留下载接口 `/tasks/{taskId}/download`。
- 定向测试若被公司 parent POM/私服阻断，只报告真实阻断，不伪造通过。