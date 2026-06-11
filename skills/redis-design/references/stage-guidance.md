# Redis Design 阶段指引

检查项：
- R1 Redis 只做加速层、协调层、短态承载层，不做事实库、分析库、跨服务共享源、消息队列
- R2 已用 RabbitMQ 项目禁止 Redis 发布订阅或延迟队列
- R3 Redis 统一使用 db0
- R4 Key 格式为 {服务模块}:{租户ID}:{数据结构}:{业务Key}，长度不超过 100 字节
- R5 Value 单 Key 不超过 1MB，常规 String 建议不超过 10KB
- R6 所有 Key 必须设置 TTL，最大不超过 30 天，大批量 Key 增加随机抖动
- R7 redis-design.md 必须包含文档头信息、历史版本信息、前言、公共配置、Redis 版本、集群配置、持久化策略、过期淘汰策略、设计项、安全与运维、人工评审项
- R8 每个设计项必须包含特性用途、业务说明、存储设计、库、数据结构、TTL、Key 定义、Value 数据格式、预估数据和容量、多团队协同
- R9 Redis 版本、拓扑、持久化、淘汰策略无法确认时，必须进入 waiting_for_input 或 waiting_for_human_review
- R10 Redis 不可用必须有降级策略
- R11 Spring 接入优先 StringRedisTemplate，复杂结构才使用 RedisTemplate<String,Object>
- R12 库存扣减、分布式锁、幂等、延迟双删、排行榜、Pipeline 不使用 Spring Cache 注解
- R13 Redis 部署版本、拓扑、持久化和淘汰策略由项目 profile 或 repo_context 注入
- R14 Redis 设计术语必须业务可理解，禁止默认使用水位/终态水位；优先使用状态处理记录、消息幂等记录、短期处理记录、乱序保护记录；Redis 不可用时不得绕过记录直接写库或删库，必须进入 MQ 重试/死信、告警并说明人工回放
