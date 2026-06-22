# 导出宽表字段补齐与 MQ CAS 坑位

适用场景：服务商待支付订单这类“MQ 入库形成本地读模型，再异步导出”的功能。

## 1. 字段缺失不要在导出查询阶段补 join

如果 PRD 要求导出字段，而当前导出 DTO/SQL 缺字段，先判断该字段是否属于本地读模型职责。

正确路径：
1. 查 PRD 字段和数据来源。
2. 查 DDL / schema-change-plan，确认本地宽表是否已有列。
3. 查实体、mapper resultMap、insert、update、select。
4. 查 MQ 监听处理/宽表构建代码，确认字段是否在入库时从订单详情或消息体复制。
5. 如果读模型应拥有该字段，从 DDL、实体、mapper、MQ 入库链路补齐。

禁止路径：
- 不要为了导出字段临时在导出 SQL 中 `LEFT JOIN` 订单主表/商品明细大表。
- 对千万级、分区表尤其危险：会绕过原本“导出查本地宽表”的性能边界。

示例判断：商品维度导出需要 `消费者电话`、`支付渠道`，如果 `t_franchise_order_item` 没有字段，应在商品宽表增加 `consumer_phone`、`pay_channel`，并在 MQ 订单明细构建时从订单实体复制，而不是导出时 join `t_franchise_order`。

## 2. PRD 更新后要重新校准规则，不沿用旧实现

检查项：
- Excel 表头集合和顺序。
- 文件名格式和时间精度。
- 最大导出条数。
- 空数据、并发、普通失败、超时失败文案。
- 导出任务记录返回条数：例如 PRD 写“最新一条”时，SQL 应是 `ORDER BY create_time DESC LIMIT 1`，不要保留旧的 `LIMIT 10`。

## 3. MQ 触发导出文件生成的 CAS

导出 MQ 重复消费时，领取任务的并发边界通常是状态机迁移：

```sql
UPDATE t_async_task
SET task_status = 'PROCESSING', version = version + 1
WHERE task_id = ?
  AND task_status = 'WAITING'
```

要点：
- 用 `WAITING -> PROCESSING` 状态 CAS 保证只有一个消费者生成文件。
- 不要把读取出来的 `version` 作为领取条件混入执行链路，除非设计明确要求版本级 CAS。
- 原因：任务进度更新、成功/失败更新都会递增 version；MQ 领取本质是状态机锁，不是普通表单编辑式乐观锁。

## 4. 失败原因

- 用户可见 `failReason` 按 PRD 收敛。
- 普通异常：`导出失败，请稍后重试`。
- 超时异常：`数据量过大，导出失败，请缩小筛选范围后重试`。
- 底层异常细节留日志，不直接暴露到任务记录。
