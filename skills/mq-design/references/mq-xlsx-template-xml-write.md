# MQ Excel 模板 XML 写入要点

适用场景：使用 teamwork-engineering-assistant / mq-design 生成 `mq-design.xlsx`，需要填充团队模板并通过 `skills/mq-design/scripts/validate_output.py`。

## 背景

MQ 设计模板校验会比较：
- `xl/styles.xml`
- sheet 顺序
- 合并单元格
- 固定表头和样式

直接用 `openpyxl.load_workbook(...).save(...)` 很容易改写样式、合并单元格或空白占位单元格，导致：
- `mq-design.xlsx 不得修改模板样式定义 styles.xml`
- `消费者 sheet 不得修改合并单元格`
- `消费者!K1/L1/L2 不得修改模板样式`

## 推荐做法

1. 复制原始模板 zip 内容。
2. 只修改 `xl/worksheets/sheet1.xml`、`xl/worksheets/sheet2.xml` 中第 2 行已有 `<c r="A2" .../>` 单元格。
3. 将自闭合 cell 改成 inline string：

```xml
<c r="A2" s="10" t="inlineStr"><is><t>业务值</t></is></c>
```

4. 保留原 cell 的 `s="..."` 样式属性。
5. 不修改：
   - `xl/styles.xml`
   - `mergeCells`
   - sheet 顺序
   - 第 1 行表头
   - merged placeholder 单元格，例如消费者 sheet 的 `L2`

## 必填策略关键词

validator 只读取 workbook text。必须把以下中文关键词写入 Excel 单元格文本，而不只是写在 YAML/Markdown：

- `死信`
- `幂等`
- `重试`
- `回放`

建议放入：
- 生产者 sheet 的 `消息体内容` 或 `备注`
- 消费者 sheet 的 `运维监控` 或 `备注`

## 常见安全填充值位置

生产者 sheet 通常可以填：
- A2 业务用途
- B2 场景应用
- C2 业务消息key
- D2 消息类型
- E2 消息体内容
- I2 目的交换机
- J2 路由key
- K2 消息预估大小
- L2 生产服务/模块名称
- P2 备注

消费者 sheet 通常可以填：
- A2 队列名称
- B2 业务用途
- C2 场景应用
- K2 绑定的Exchange/routingKey
- M2 死信队列exchange/routeKey
- N2 消费服务
- O2 消息key
- P2 运维监控
- T2 备注

跳过合并占位列，尤其不要写消费者 sheet 的 `L2`。