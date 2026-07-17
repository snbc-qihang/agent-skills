# 高风险 seam 的红绿证据

仅测试变更实际触及的身份或授权状态、认证或秘密解析、编码归一化、审计或持久化 adapter 合同，不扩张为通用安全扫描。

1. 先列出只包含本次 diff 所触及单元格的适用反例矩阵；每个单元格必须有一条会因当前缺陷失败的测试，未覆盖项不能判绿，也不得扩张成通用扫描。
2. 身份或授权状态至少区分：原始 HTTP 401 + malformed envelope、旧请求的 401 在新身份建立后返回、身份替换后的旧 bootstrap 或异步结果返回。用可控延迟固定 owner 与顺序；身份改变、显式 logout 或终止后旧结果不得恢复受保护数据、认证材料或旧主体状态。
3. 秘密解析或编码归一化至少区分：畸形 percent 片段后仍含合法 escape、嵌入普通文本的编码片段、Base64(percent/form(secret)) 组合、form `+`、大小写变体、通用键值/header/裸认证，以及适用的 PEM、云凭据、短编码和 unpadded Base64。对每个适用变换与组合链保留有界参数化红灯，固定 `raw -> decode -> canonicalize -> classify` 顺序与深度并失败关闭。
4. 持久化或审计必须通过真实生产 adapter 或共享 contract test 闭合 ID 类型、adapter 返回值、resultStatus 和最终 commit/rollback 可见性。adapter 返回的 persistence ID 是事实源；用真实事务查询成功提交、adapter/audit 失败回滚和并发 loser 无 ACL/成功审计，不能用 mock 调用顺序、`@Transactional` 注解或返回相同 ID 的 fake 伪证合同。
5. 上述清单只在对应 grammar、状态机或生产合同被固定 diff 触及时成为适用单元格；不适用项记录理由，不生成测试。用同一测试完成红绿循环，并把实际发现的绕过固化为最小回归。
