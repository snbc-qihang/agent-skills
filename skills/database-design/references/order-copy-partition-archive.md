# MQ 订单副本表分区与归档设计参考

## 适用场景

- 服务通过 MQ 维护订单副本 / 主明细读模型。
- 同一业务订单会多次变更，存在重复消息、乱序消息、多节点并发消费。
- 后台列表、导出、汇总等查询需要在本地读模型上完成。
- 表规模达到组织定义的大表阈值，例如千万级必须分区。

## 设计顺序

1. 先明确 PRD 查询字段和权限模型。
   - 不要按源订单表 1:1 复刻字段。
   - 订单表字段应来自列表、筛选、汇总、订单导出、数据隔离。
   - 商品表字段应来自商品维度导出。
   - 源订单表 / 商品表只作为取数来源，不作为字段全集。

2. 估算容量。
   - 平均明细数 = 明细总行数 / 订单总行数。
   - 年均订单 = 历史订单总行数 / 年数。
   - 年均明细 = 历史明细总行数 / 年数。
   - N年存储 = `(订单行数 * 订单行宽 + 明细行数 * 明细行宽) * 索引放大系数 * 安全冗余系数`。

3. 判断分区键。
   - 分区键必须匹配主查询路径和权限模型。
   - 不要因为表里有 tenant_id 就默认 `KEY(tenant_id)`。
   - 如果权限按售货机、运营商、城市多维交叉，tenant 分区通常不稳定。
   - 如果 PRD 强制下单时间范围，优先评估 `order_create_time` 月度 RANGE 分区。

## 权限模型影响分区键

示例：

- 点位资源商：权限直接分配售货机，主查询约束是 `vem_id` 集合。
- 非点位资源商：权限分配运营商/租户 + 城市，主查询约束是 `operator_id + city_code`。
- 页面筛选：运营商、售货机、城市。

这种模型下，查询是：

```text
权限范围 ∩ 页面筛选 ∩ 待支付状态 ∩ 下单时间范围
```

`tenant_id` 不是统一查询入口。若强制按 tenant 分区，点位商按售货机查和城市跨租户查都可能无法稳定分区裁剪。

## 推荐模式：时间 RANGE 分区 + identity 表

当同时满足：

- 千万级表必须分区；
- 查询强制下单时间范围；
- 分区字段选择 `order_create_time`；
- 仍需 DB 层保证 `tenant_id + order_id` 当前副本全局唯一；
- MQ 多节点并发消费，不能仅靠应用层查重；

使用：

```text
t_franchise_order_key      非分区，承载订单唯一身份
t_franchise_order          按 order_create_time 月度 RANGE 分区
t_franchise_order_item     按 order_create_time 月度 RANGE 分区
```

`t_franchise_order_key` 职责：

```sql
UNIQUE KEY uk_tenant_order (tenant_id, order_id)
```

并保存：

- `order_create_time`：定位分区表记录；
- `source_event_time`：判断 MQ 旧消息是否允许覆盖。

## 为什么需要 identity/key 表

MySQL 分区表要求所有唯一键包含分区字段。

如果订单表按：

```sql
PARTITION BY RANGE COLUMNS(order_create_time)
```

则下面唯一键不合法：

```sql
UNIQUE KEY uk_tenant_order (tenant_id, order_id)
```

如果改成：

```sql
UNIQUE KEY uk_tenant_order_time (tenant_id, order_id, order_create_time)
```

只能保证同一订单在同一 `order_create_time` 下唯一，不能保证 `tenant_id + order_id` 全局唯一。上游补偿、历史初始化、字段映射错误或并发消费都可能造成重复副本。

非分区 key 表用于保留真正的当前副本唯一约束。

## MQ 消费流程

1. 按 `tenant_id + order_id` 查询 / 插入 `t_franchise_order_key`。
2. 若 key 不存在，插入 key 表，写入 `order_create_time/source_event_time`。
3. 若 key 已存在，比较消息 `eventTime` 与 key 表 `source_event_time`。
4. 旧消息：幂等成功结束。
5. 新消息：更新 key 表 `source_event_time`，再按 `tenant_id + order_id + order_create_time` 更新分区订单表和商品表。
6. 主表 upsert、商品明细删除重建、key 表更新时间戳应在同一本地事务内完成。

## 查询路径

### 点位资源商

- 权限锚点：售货机。
- 小集合：`vem_id IN (...)`。
- 大集合：使用用户可见售货机范围表/临时表 join，避免超长 IN。
- 推荐索引：`(vem_id, payment_status, order_create_time)`。

### 非点位资源商

- 权限锚点：运营商 + 城市。
- 默认按交集处理，避免扩大可见范围。
- 推荐索引：
  - `(operator_id, city_code, payment_status, order_create_time)`
  - `(operator_id, payment_status, order_create_time)`
  - `(city_code, payment_status, order_create_time)`

## Pitfalls

- 不要把 Redis 当唯一事实约束。Redis 锁可以辅助削峰，但不能替代 DB 唯一键。
- 不要在分区表上只建 `(tenant_id, order_id, order_create_time)` 后声称已保证订单全局唯一。
- 不要把 `source_event_time` 用作归档分区字段；它是消息事件时间，适合旧消息判断。归档/查询裁剪优先使用业务下单时间 `order_create_time`。
- 不要用一个万能 SQL 覆盖点位商和非点位商；应按权限类型拆查询模板。
