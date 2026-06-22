# 导出任务列表查询契约

适用场景：异步导出创建后，前端需要展示当前用户的导出任务进度/结果列表。

## 关键契约

- 不要默认提供 `taskId` 查询详情接口；除非设计明确要求详情页。
- 列表查询入参应是导出业务类型，例如：
  - 订单维度：`PENDING_ORDER`
  - 商品维度：`PENDING_ORDER_ITEM`
- 查询范围必须来自当前 token：
  - 当前租户 `tenantId`
  - 当前用户 `userId/createUserId`
- 查询排序和数量：
  - `ORDER BY create_time DESC`
  - `LIMIT 10`
- 下载接口可以继续使用 `taskId`，因为下载文件必须定位具体任务。

## 推荐代码形态

Controller：
- `GET /console/<resource>/export/tasks/{businessType}`
- 返回 `CommonResp<List<AsyncExportTaskDetailResp>>`
- 注释明确“不提供按 taskId 查询详情功能”。

Facade：
- `listTasks(String businessType)`
- 内部读取 token 中的用户和租户，再调用通用任务服务。

Service：
- `listTasks(String businessType, String tenantId, String userId)`
- Mapper 使用 `selectLatestTasks(tenantId, createUserId, businessType)`。

Mapper SQL：

```sql
SELECT <BaseColumnList>
FROM t_async_task
WHERE tenant_id = #{tenantId}
  AND create_user_id = #{createUserId}
  AND task_type = 'EXPORT'
  AND business_type = #{businessType}
ORDER BY create_time DESC
LIMIT 10
```

## 测试检查点

- Controller contract 测试确认路径变量是 `{businessType}`，不是 `{taskId}`。
- Facade 测试确认业务类型、当前用户、当前租户被透传。
- Service/Mapper 测试或静态检查确认 `create_time DESC LIMIT 10`。
- 全局搜索确认不存在旧详情接口：
  - `getTask(...)`
  - `AsyncExportTaskDetailResp getTask`
  - `/export/tasks/{taskId}` 详情路径
