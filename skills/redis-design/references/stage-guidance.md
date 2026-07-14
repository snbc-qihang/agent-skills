# Redis Design 阶段指引

检查项：
- R1 Redis 只做加速层、协调层、短态承载层，不做事实库、分析库、跨服务共享源、消息队列
- R2 已用 RabbitMQ 项目禁止 Redis 发布订阅或延迟队列
- R3 Redis 统一使用 db0
- R4 Key 格式为 {服务模块}:{租户ID}:{数据结构}:{业务Key}，长度不超过 100 字节
- R5 Value 单 Key 不超过 1MB，常规 String 建议不超过 10KB
- R6 所有 Key 必须设置 TTL，最大不超过 30 天，大批量 Key 增加随机抖动
- R7 设计说明 Redis 版本、集群、持久化、淘汰策略、Key、结构、TTL、容量、命中率、资源池、降级方案
- R8 Spring 接入优先 StringRedisTemplate，复杂结构才使用 RedisTemplate<String,Object>
- R9 库存扣减、分布式锁、幂等、延迟双删、排行榜、Pipeline 不使用 Spring Cache 注解
- R10 Redis 部署版本、拓扑、持久化和淘汰策略由项目 profile 或 repo_context 注入
