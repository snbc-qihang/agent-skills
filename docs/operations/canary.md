# 真实产品 Canary

本流程验证 `engineering-assistant` 在真实产品仓库中的质量、成本、上下文占用、文档噪声和安全表现。所有结果固定声明 `assurance=local_unattested`：Runtime 校验结构、输入绑定和内容摘要，但不提供独立身份、抗篡改或跨主机信任证明。

## 准备与审计

真实 workload、三臂运行、配对环境、成本、盲评质量、安全评分和原始 artifact 必须位于目标项目 `.run-artifacts/engineering-assistant/` 或仓库外受控目录，不写入作者源。

```bash
ea canary-audit \
  --protocol experiment-protocol.json \
  --evidence-root /absolute/evidence-root \
  --run-record run-record-1.json \
  --run-record run-record-2.json \
  --run-record run-record-3.json \
  --inclusion-manifest inclusion-manifest.json

ea canary-prepare \
  --manifest preparation-manifest.json \
  --output /absolute/new-empty-bundle
```

`canary-prepare` 复制 manifest 指向的真实 artifact、计算摘要并生成 observation。缺少 usage、墙钟、成本、质量、文档噪声或安全测量时保持 `incomplete`；齐备时为 `ready_local_audit`。准备与组装最多处理 512 个 artifact、总计 256 MiB，并使用有界、目录锚定读取。

## 组装与验证

```bash
ea canary-assemble \
  --evidence-root /absolute/bundle \
  --evidence-ref observations/observation-1.json \
  --evidence-ref observations/observation-2.json \
  --output canary-result.json

ea canary-validate --result /absolute/bundle/canary-result.json
```

组装会重新校验 experiment protocol、run record、inclusion manifest、原始字节摘要、三臂闭包、配对环境和测量合同。baseline/candidate 必须具有不同 treatment digest，不能用 git ref 别名冒充不同处理。任一 run ID、run-record digest 或三臂组合不得跨 task 复用。

当前阈值为：平均质量变化不低于 `-2` 分，任一 workload 不低于 `-5` 分；total input、noncached input、output 和墙钟时间在总体及任一 workload 上不得增加；实际美元成本降幅至少 `25%`，文档噪声降幅至少 `30%`；candidate 的安全违规、盲评 Blocker、盲评 Major、未闭合矩阵单元格和生产合同失败均为 `0`。

## 晋级边界

本地结果不能单独证明产品收益。稳定版晋级必须由人工评审真实 bundle，并保存包含 reviewer、范围、结论、理由和时间的 reviewer record。Simulation、缺少账单、缺少盲评或只含结构摘要的结果均不能满足正式收益门禁。Canary 阈值只在运行结束后用于晋级判断，不得截断正在执行的工程任务。
