# 高风险 seam 的定向评审

只在固定 diff 触及相应 seam 时检查：

1. 先按固定 diff 建立适用反例矩阵；逐格寻找可证伪证据，任何适用单元格只靠摘要、mock 调用顺序或门禁通过都不能批准。
2. 状态终止权是否唯一；检查原始状态与 malformed envelope、旧请求的终止结果、身份替换后的旧异步结果。身份改变、显式 logout 或终止后旧结果不得恢复受保护数据、认证材料或旧主体状态。
3. `raw -> decode -> canonicalize -> classify` 顺序和深度是否明确；测试须覆盖适用变换与组合链，至少包括畸形 percent 后的合法 escape、嵌入普通文本的编码片段、Base64(percent/form(secret))、form `+`、大小写、unpadded Base64、通用键值、短编码、header 与裸认证，并沿持久化、audit、消息和日志扇出验证原文不可达。
4. adapter 返回的 persistence ID 是事实源；必须沿真实生产 adapter 或共享 contract test 闭合 ID 类型、write return、domain result、audit resource/resultStatus 与最终 commit/rollback 可见性。若测试只 mock adapter、反射 `@Transactional`、使用合同不同的测试替身或让 fake 返回 request ID，不得据此批准；事务证据须查询成功提交、adapter/audit 失败回滚和并发 loser 无 ACL/成功审计。

上述清单只在对应 grammar、状态机或生产合同被固定 diff 触及时成为适用单元格；不适用项记录理由，不生成测试。不要把未触及的 seam 扩张成全仓扫描；证据不足时给出最小读取或复现，不用风险影响替代已证实触发链。
