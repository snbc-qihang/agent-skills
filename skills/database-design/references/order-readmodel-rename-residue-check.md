# 订单读模型表/字段改名后的残留校验

适用场景：用户要求调整数据库设计中的表名、字段名、冗余字段、分区键或乐观锁字段时。

## 本次沉淀的操作模式

1. 不只改 `database-design.md` 和 `schema-change-plan.sql`。
   同步检查并更新：
   - `migration-plan.md`
   - `rollback-plan.md`
   - `partition-archive-plan.md`
   - `database-risk-report.json`
   - 相关 stage-run / artifact index 中如有正式引用，也要评估是否需要同步。

2. 做“旧 token 残留搜索”。
   示例 token：
   - 旧表名：`t_franchise_order`、`t_franchise_order_item`
   - 删除字段：`goods_summary`、`city_code`、`city_name`、`version`
   - 改名字段：`order_status`、`order_item_no`、`sync_create_time`、`sync_update_time`

3. 删除明细表冗余字段时，不要只删字段。
   必须同步推导：
   - 唯一键是否还能包含被删字段
   - 普通索引是否失效
   - 分区方案是否仍成立
   - 归档方案是否需要改为通过主表关联控制批次
   - CRUD 契约、并发控制、风险报告是否还在引用旧字段

4. MQ 乱序控制不一定要落到每张明细表。
   如果主表保存 `source_event_time`，并且只有消息时间戳通过主表判断后才同事务更新明细，明细表可以不冗余 `source_event_time`。这时文档必须写清楚：乱序控制锚点在主表，明细更新受主表事务保护。

5. 验证建议输出机器可读结果。
   可用脚本逻辑：读取 database-design 目录关键文件，搜索旧 token；单独截取明细表 DDL，确认没有不应存在的字段；解析 JSON 风险报告。

## 注意

如果用户只是要求设计产物修改，不要执行生产 DDL。输出仍应保持 `waiting_for_human_review` 或明确 DBA/业务审批点。