# CodeGraph 项目巡检与 Feign 调用梳理参考

适用场景：用户要求对一个多服务 Java/Spring 仓库做总体巡检、模块地图、核心链路梳理，尤其要求“借助 codegraph”或同步梳理 Feign 调用。

## 推荐产物结构

在目标仓库下生成 run artifact，避免修改业务源码：

- `artifacts/project-inspection/overall-inspection-report.md`
- `artifacts/project-inspection/raw-inspection-data.json`
- `artifacts/project-inspection/services/<service>.md`
- `artifacts/project-inspection/services/README.md`
- `artifacts/project-inspection/step1-core-map/core-module-map.md`
- `artifacts/project-inspection/step1-core-map/core-module-map.yaml`
- `artifacts/project-inspection/step1-core-map/feign-call-inventory.md`
- `artifacts/project-inspection/step1-core-map/feign-call-inventory.csv`
- `artifacts/project-inspection/step1-core-map/feign-inventory.json`

## 执行顺序

1. 先用 CodeGraph 确认可索引状态：文件数、节点数、边数、语言分布。
2. 用 `codegraph_files` 获取顶层服务目录，识别 `pom.xml` 服务边界。
3. 用 `codegraph_search` / `codegraph_explore` 抽样确认 Controller、ServiceImpl、Mapper、FeignClient、MQ listener、Redis 工具类等真实代码形态。
4. 再用脚本做全量静态扫描，输出 JSON 原始数据；不要只靠抽样判断。
5. 总体报告先给系统性结论，再给服务风险表，再列架构/性能/代码异味问题。
6. 各服务详细报告用同一模板：服务概览、主要问题、架构巡查、性能巡查、代码异味、建议动作。
7. 若用户要求“先做第一步”或“核心链路模块地图”，聚焦高风险核心服务，不继续泛扫。
8. 若存在 Feign 调用，必须单独输出 Feign 调用矩阵：调用方、Client、目标服务、url、fallback、方法数、HTTP 方法、路径、源码文件。

## 建议扫描指标

Java/Spring 服务通用指标：

- Java LOC、生产 Java 文件数、测试 Java 文件数
- Controller、Service、Mapper/Repository 数
- Mapping endpoint 数
- Feign Client 数、Feign 方法数、目标服务分布
- Redis、Redisson、MQ、RestTemplate/HttpClient、@Transactional、@Scheduled、@Async 使用迹象
- `catch (Exception)`、`printStackTrace`、`System.out`、字段注入、static mutable
- MyBatis XML：动态 SQL、`<foreach>`、`<resultMap>`、`${}`、`select *`
- 长文件、长方法、重复类名、target/.idea 仓库污染
- 配置中的疑似 password/secret/token 键位；只列位置，不展示值

## Feign 梳理要点

- 统计全仓 `@FeignClient`，解析 `name/value/url/fallback/fallbackFactory`。
- 解析接口方法上的 `@GetMapping/@PostMapping/@PutMapping/@DeleteMapping/@PatchMapping/@RequestMapping`。
- 按调用方服务统计 Client 数、方法数、目标服务。
- 按目标服务统计调用方、Client 数、方法数。
- 将 target 名称大小写不一致、新旧服务名混用列为治理风险。
- 如果 fallback/fallbackFactory 全部缺失，不要直接断言“没有降级”；表述为“未在 Feign Client 上显式声明，需要确认是否存在全局熔断/降级策略”。

## 报告判断原则

- 性能结论必须标注“静态迹象”，后续需要慢查询、调用耗时、MQ 积压、线程池、缓存命中率验证。
- 对网状调用结构，不按服务名硬切治理路线；优先按核心业务链路切：下单/支付/退款/开门、会员权益、券活动/促销、加盟商/售货机、统计/导出。
- 对高风险大服务，先建立模块地图和 characterization tests，再谈拆服务或重构。
- 不输出敏感配置值；只输出文件、行号、键名。
