# 真实产品 Canary

本流程用于验证 `engineering-assistant` 在真实产品仓库中的质量、成本、上下文占用、文档噪声和安全表现。它不生成模拟证据，也不允许 Runtime 自签结果。运行 artifact、broker 回执和结果必须保存在目标项目 `.run-artifacts/engineering-assistant/` 或仓库外受控证据目录，不能写入本作者源仓库。

## 前置条件

- 选择至少 5 个真实 workload；baseline 与 candidate 必须使用相同的 `workload_digest` 和环境摘要。
- 固定 baseline/candidate 的代码、插件版本、模型、工具权限和执行参数，并分别计算不同的 `treatment_digest`。
- 使用独立质量量表与评价者；保存实际 usage、账单、质量评分、文档噪声和安全审计 artifact。
- 宿主已按 README 的固定位置配置 HTTPS evidence broker。配置不存在或权限不安全时，canary 命令会安全失败，不会回退到模型或仓库提供的 endpoint。
- Broker 能核对原始 artifact 与 claims，并返回 opaque attestation；私钥和业务 token 不进入仓库或 manifest。

## 准备 manifest

manifest 必须符合 `evals/canary/preparation-manifest.schema.json`。artifact 路径相对于 manifest 所在目录；`artifact_measurements` 必须与 `artifact_paths` 一一对应，并声明每份 artifact 支撑的测量类型。所有已填写测量值都必须有对应证据类型。

```json
{
  "schema_version": "1.0",
  "product_repository": "ai-platform",
  "runs": [
    {
      "task_id": "product-task-001",
      "workload_digest": "sha256:<64 hex>",
      "variant": "candidate",
      "git_ref": "<immutable commit>",
      "treatment_digest": "sha256:<64 hex>",
      "execution_config_digest": "sha256:<64 hex>",
      "environment_digest": "sha256:<64 hex>",
      "quality_rubric_digest": "sha256:<64 hex>",
      "evaluator_id": "independent-reviewer-v1",
      "started_at": "2026-07-14T00:00:00Z",
      "finished_at": "2026-07-14T00:10:00Z",
      "input_tokens": 1000,
      "output_tokens": 200,
      "cost_usd_micros": 45000,
      "quality_score": 91.5,
      "document_noise_units": 8,
      "safety_violations": 0,
      "artifact_paths": ["evidence/task-001.json"],
      "artifact_measurements": {
        "evidence/task-001.json": [
          "usage",
          "billing",
          "quality_evaluation",
          "document_noise",
          "safety_audit"
        ]
      }
    }
  ]
}
```

| 测量类型 | 支撑字段 |
|---|---|
| `usage` | `input_tokens`、`output_tokens` |
| `billing` | `cost_usd_micros` |
| `quality_evaluation` | `quality_score` |
| `document_noise` | `document_noise_units` |
| `safety_audit` | `safety_violations` |

## 生成与验签

```bash
ea canary-prepare \
  --manifest /受控目录/canary-manifest.json \
  --output /受控目录/canary-bundle
```

`preparation-report.json` 为 `incomplete` 时，按 `incomplete_runs[].missing_fields` 补充真实测量后重新生成到新的空目录。状态为 `awaiting_attestation` 时，将每个 draft 的 canonical claims 与其 artifact 交给配置中的 evidence broker。Broker 核验后，把符合 `evals/canary/attestation-response.schema.json` 的回执放入 bundle 的受控相对路径，再逐个导入：

```bash
ea canary-attestation-import \
  --evidence-root /受控目录/canary-bundle \
  --draft-ref observations/observation-<id>-candidate.draft.json \
  --response-ref attestations/response-<id>-candidate.json \
  --output observations/run-<id>-candidate.json
```

导入具有内容幂等性：相同内容可安全重试，不同内容冲突会失败。不得修改已导入的 run evidence；应修正上游测量或 broker 回执后生成新 bundle。

## 组装与判定

收齐至少 5 对 baseline/candidate 的已验签 run evidence 后组装结果。每个 evidence 使用一个 `--evidence-ref`：

```bash
ea canary-assemble \
  --evidence-root /受控目录/canary-bundle \
  --evidence-ref observations/run-001-baseline.json \
  --evidence-ref observations/run-001-candidate.json \
  --output canary-result.json

ea canary-validate \
  --result /受控目录/canary-bundle/canary-result.json
```

只有 `canary-validate` 在当前宿主 trust binding 下返回通过，才可声明真实收益门禁通过。`ea eval` 的 `canary.status=not_run` 不能代替该证据。当前本机 RC 预发布允许 canary 未运行，但 preflight 会明确输出 `canary.status=not_run` 与 `canary_gate.status=not_required_for_local_prerelease`；稳定版发布仍由策略禁止，不能据此宣称产品收益完成。

当前通过阈值为：平均质量变化不低于 `-2` 分、实际美元成本降幅至少 `25%`、文档噪声降幅至少 `30%`、candidate 安全违规总数为 `0`。Token 降幅单独报告但不代替实际账单成本门禁。任一阈值失败时 `canary-validate` 输出 `status=failed` 并返回非零退出码。

## 失败处理

- workload、environment、execution config 或 quality rubric 摘要不匹配：重新固定同一实验条件并重跑对应配对。
- baseline 与 candidate 的 treatment 摘要相同：重新计算真实处理内容摘要，不能用分支名或 git ref 代替。
- broker 不可信、回执 inactive 或 claims 不一致：停止使用该回执，由宿主管理员修复 trust binding 或 broker；Runtime 不得降级为自签。
- 成本或质量来源缺失：保持 `incomplete`，不能以 token 推算账单，也不能由执行 Agent 自评替代独立评分。
- 某项指标未过阈值：保留原始证据并记录反馈处置，优化后以新的 treatment 和 bundle 重跑；不得覆盖失败证据。
