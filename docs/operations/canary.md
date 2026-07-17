# 真实产品 Canary

本流程用于验证 `engineering-assistant` 在真实产品仓库中的质量、成本、上下文占用、文档噪声和安全表现。它不生成模拟证据，也不允许 Runtime 自签结果。运行 artifact、broker 回执和结果必须保存在目标项目 `.run-artifacts/engineering-assistant/` 或仓库外受控证据目录，不能写入本作者源仓库。

## 前置条件

- 选择至少 5 个真实 workload；baseline 与 candidate 必须使用相同的 `workload_digest` 和环境摘要。
- 固定 baseline/candidate 的代码、插件版本、模型、工具权限和执行参数，并分别计算不同的 `treatment_digest`。
- 使用独立质量量表与评价者；保存实际 usage、墙钟计时、账单、质量评分、文档噪声和安全审计 artifact。
- 宿主已按 README 的固定位置配置 HTTPS evidence broker。配置不存在或权限不安全时，canary 命令会安全失败，不会回退到模型或仓库提供的 endpoint。
- Broker 能核对原始 artifact 与 claims，并返回 opaque attestation；私钥和业务 token 不进入仓库或 manifest。

## 无 Broker 时的本地结构审计

没有真实 Broker 或不采集账单时，可以先在目标项目 `.run-artifacts/engineering-assistant/` 或仓库外受控目录准备 `experiment-protocol`、每次运行的 `run-record` 和 `inclusion-manifest`，再执行只读审计：

```bash
ea canary-audit \
  --protocol /受控目录/experiment-protocol.json \
  --evidence-root /受控目录 \
  --run-record runs/run-001.json \
  --inclusion-manifest /受控目录/inclusion-manifest.json
```

`experiment_kind=routing_ablation` 固定 `route_only`、`minimum_skills`、`full_local` 三臂；`experiment_kind=delegation_ablation` 固定 `minimum_matrix_inline`、`minimum_matrix_risk_delegation`、`full_local_control` 三臂，使 matrix-only 与风险委派的因果比较可由同一审计器表达。root 主 prompt artifact 的原始 bytes 摘要必须出现在实际平台 transcript 的 user message 中。风险委派臂的未闭合假设必须来自绑定 run/root 的 `hypothesis_artifact`，该 JSON artifact 自身的原始 bytes 摘要也必须出现在平台 user message 中，不能用 artifact 内另一个任意消息摘要间接指向；每个 descendant 必须一对一绑定实际委派 prompt artifact，该 artifact 的摘要还必须出现在对应原生 child transcript 的 user message 中。审计再从 prompt 中的 `delegation_scope`、假设批次和证据引用派生委派结论；宿主未暴露这些消息时不得形成 `local_structural`。没有未闭合假设时必须零委派；存在未闭合假设时，批次必须无重复地覆盖全部假设，委派事件数必须等于批次数。每个 thread 的证据引用都会重新哈希，共享身份按内容摘要而不是路径判断，别名不能规避共享检测；只有 `fixed_workload_input`、`fixed_diff`、`adapter_contract`、`security_regression_fixture`、`quality_rubric` 五类封闭代码允许主/子共享。重复全量评审数量由绑定 prompt 的 scope 派生且必须为零，不能用自报零值通过。每个 workload/repeat 必须形成交错的完整三臂 block，并冻结每臂实际输入 prompt 摘要；`treatment_digest` 同时绑定该 `prompt_digest` 与三臂 conformance，避免错传或改写 treatment 后仍归入原实验。每份 `run-record` 必须同时绑定实际 prompt 文件、主进程退出码、平台 transcript、标准门禁日志和 usage；审计会重新读取 prompt bytes。证据总量预算按唯一引用累计；审计不常驻缓存所有 payload，只按 `(reference, parser_role)` 缓存小型派生对象。hypothesis/delegation 控制 JSON 超过 `256 KiB`、正式 canary 结构化 JSON 超过 `2 MiB` 时都在解码前失败关闭，避免解析器内存放大；单文件和事件数量仍受硬上限约束。

每个 workload 还必须在 protocol 中预注册 `deliverable_capture`。`final_response` 只接受平台 transcript 中唯一且为最后一个 `item.completed/agent_message` 的 `content`，按原始 UTF-8 bytes 重放摘要；outcome 的 capture artifact、盲评 asset 和正式 evidence closure 必须绑定同一 bytes。`workspace_patch` 与 `workspace_tree` 是稳定的预注册契约，但当前没有 runner-bound 前后 workspace provenance，审计固定返回 `deliverable_capture_provenance_unavailable`，不能回退使用聊天回复或模型自报 artifact。盲评冻结前会扫描 assignment、score、两侧 transcript 和实际 asset；禁止身份来自 protocol 的全部 arm、treatment 和 run ID，并包含稳定中英文语义别名。扫描最多处理 `4096` 个 JSONL 事件、`8192` 个字符串字段、`256 KiB` 字符与 `64` 种解码形式，支持最多四层 NFKC、percent/form、JSON Unicode 和 padded/unpadded URL-safe Base64 组合；达到层数后仍呈可解码包装时失败关闭。

Skill 证据只接受成功完成的 `sed`/`cat` 完整读取命令；执行配置必须冻结绝对 `plugin_root`、`package-manifest.json` 原始摘要、完整 package payload 摘要和逐 skill 内容摘要。local audit 直接复用 package verifier 校验声明根的 manifest 与全树，要求 verifier 返回的 `payload_digest` 等于 `plugin_payload_digest`；只保留 skills 而删除或篡改 runtime 同样失败。命令路径、实际插件文件摘要、完整输出与 frontmatter ID 必须同时匹配。任意命令字符串中出现 `SKILL.md`、假插件根或只输出 `name` 行都不算已读取；这仍是命令确认的读取证据，不是宿主专用的 skill-load 事件。委派 usage 必须同时绑定 export 与原生 child transcript 的完整祖先 session 链、摘要和 token；无关 session 拼接、export/native 跨角色复用会失败，原生 child 工具事件也计入整棵运行的 treatment conformance。协议另冻结随机种子摘要、实际启动顺序、运行时间和不可变配置摘要；所有实际启动的 primary 或 spare 运行都必须绑定 `attempt-outcome`，并从摘要封闭的 raw `attempt_fact` receipt 重放 run/protocol/workload/arm/treatment、退出与 gate、usage/墙钟、cost status、rework、安全、质量与文档计数；与 run-record 现有字段或 receipt 不一致时失败关闭，旧 `1.0` 记录只降级为 `legacy_unverifiable`。所有运行（包括排除的失败尝试）都必须列入记录，只有与实际失败相符的排除理由和完整替代覆盖才可接受。审计先限制 protocol、run-record 与 inclusion manifest 的单文件、文件数和累计 bytes，再限制唯一证据文件数、累计 bytes 和 JSONL 事件数；重复引用复用已锚定 payload，循环线程图失败关闭，transcript 逐行解析。这些上限只保护审计器资源，不截断被评产品任务。

该命令输出 `local_structural` 或 `legacy_unverifiable` 非晋级证据状态：前者表示当前结构合同通过，并提供覆盖全部输入记录的 `audited_run_bindings` 以及其中实际纳入统计的 `included_run_bindings`；后者表示保留的旧 1.0 记录缺少新增执行、prompt、read-scope、child-native provenance，或 protocol 未冻结插件根与逐 skill 摘要，审计器只读降级而不改写原记录。两种非晋级状态都返回退出码 `3`，结构或合同失败返回 `2`，调用方不得把 `3` 当作普通 CI 成功。每次当前结构运行都必须明确记录 Broker `unavailable`、账单 `not_collected`；任何伪装成 configured/attested/collected 的本地记录都会失败。read-path 若宿主未可靠暴露，必须标记 `not_exposed` 且不得填写推测路径。skill 仍是命令确认的读取证据而非宿主专用事件，委派关系仍不是宿主统一计量，因此这些限制继续披露。该命令不生成 attestation、不能满足成本门槛，也不能作为发布晋级或产品收益证据；结构不完整时返回失败状态，但不得据此截断正在执行的产品任务。

## 准备 manifest

manifest 必须符合 `evals/canary/preparation-manifest.schema.json`。artifact 路径相对于 manifest 所在目录；`artifact_measurements` 必须与 `artifact_paths` 一一对应，并声明每份 artifact 支撑的测量类型。所有已填写测量值都必须有对应证据类型。正式 observation 还要绑定 `experiment_kind`、`experiment_protocol_digest` 与实际 `arm_id`；其中 protocol/run-record 的逻辑 binding 使用解析后 canonical JSON digest，`artifact_refs.digest` 单独约束原始 bytes 完整性，二者不得混用。protocol 必须以每个 workload 的 `input_artifact`、顶层 `quality_rubric_artifact` 和 `environment_artifact` 绑定原始 bytes，artifact digest 必须分别等于既有的 workload、rubric 和 environment digest；每个 local-structural 线程还必须把这三类内容声明为 `fixed_workload_input`、`quality_rubric` 和 `fixed_environment_snapshot` evidence，审计器按 bytes 重算而不接受自报摘要。`delegation_ablation` 的 baseline 固定为 `full_local_control`，candidate 固定为 `minimum_matrix_risk_delegation`，并为每个 workload/repeat 提供包含 `run_id`、`workload_id`、`repeat_index`、`arm_id`、`run_record_digest` 的三臂封闭 binding。对应 protocol、完整 inclusion manifest 和真实 auditor 报告都必须唯一进入 refs；报告的 `audited_run_bindings` 对应的全部 source run-record 及其 prompt、平台 transcript、门禁 stdout/stderr、线程 export/native transcript、线程 evidence、假设、委派 prompt、共享 evidence，以及 package manifest 所列全部 payload 原始 bytes 必须完整进入闭包，而不只是当前 cell 三份记录。重放时 transcript 中的命令仍按 protocol 声明的原绝对 `plugin_root` 校验；bundle bytes 会在隔离临时根重建完整 package 并复用同一 package verifier，读取 skill 内容也只来自该冻结 package。因此原插件目录不可访问时 prepare/import 仍能自包含验证，缺失或错误 manifest、runtime 或 skill bytes 都会失败关闭。selected bindings 必须是 `included_run_bindings` 的精确子集，included 又必须属于 audited，inclusion entries 必须与 audited 全集一致。受控 artifact 角色不得交叉；同实验全量闭包按 source ref/raw digest 内容寻址复用，每份 observation claims 仍列出完整 refs。prepare、attestation import 与 assemble 都会执行完整 schema、canonical binding 与 raw bytes 校验；外部 Broker 必须用这些 bytes 重放全实验结构审计后才可签发。任一 `run_id`、run-record canonical digest 或三臂组合不得被不同 task 复用，不能靠人工文件名、自报状态或任意摘要字符串关联本地消融与正式收益结果。

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
      "noncached_input_tokens": 250,
      "output_tokens": 200,
      "wall_time_milliseconds": 420000,
      "cost_usd_micros": 45000,
      "quality_score": 91.5,
      "document_noise_units": 8,
      "safety_violations": 0,
      "blind_blocker_count": 0,
      "blind_major_count": 0,
      "applicable_matrix_cells": 12,
      "closed_matrix_cells": 12,
      "production_contract_failures": 0,
      "artifact_paths": ["evidence/task-001.json"],
      "artifact_measurements": {
        "evidence/task-001.json": [
          "usage",
          "timing",
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
| `usage` | `input_tokens`（包含缓存 input）、`noncached_input_tokens`、`output_tokens` |
| `timing` | `wall_time_milliseconds` |
| `billing` | `cost_usd_micros` |
| `quality_evaluation` | `quality_score` |
| `document_noise` | `document_noise_units` |
| `safety_audit` | `safety_violations`、`blind_blocker_count`、`blind_major_count`、`applicable_matrix_cells`、`closed_matrix_cells`、`production_contract_failures` |

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

当前通过阈值为：平均质量变化不低于 `-2` 分、任一 workload 质量变化不低于 `-5` 分；total input、noncached input、output 和墙钟时间在总体及任一 workload 上均不得增加；实际美元成本降幅至少 `25%`、文档噪声降幅至少 `30%`；candidate 的安全违规、盲评 Blocker、盲评 Major、未闭合矩阵单元格和生产合同失败均为 `0`。这些安全字段进入 broker 签名 claims、run/result schema 和确定性 threshold，`closed_matrix_cells` 不能大于 `applicable_matrix_cells`；安全审计 artifact 与结构化计数冲突时 Broker 必须拒绝签发。结果同时输出逐 workload 的四项效率变化与 `overhead_fields`，因此不能用其他 workload 的节省抵消局部膨胀。旧有 `token_reduction_ratio` 继续按 input 与 output 合计计算并单独报告；各 Token 指标不能代替实际账单成本门禁。未采集账单时只能继续做本地优化，不能满足正式成本收益门禁。任一阈值失败时 `canary-validate` 输出 `status=failed`、列出 `threshold_failures` 并返回非零退出码。

这些阈值只用于一组真实运行已经完整结束后的 RC 晋级判定，不是执行预算。Hook、路由和 Runtime 不得因 Token、输出大小、重复调用或墙钟阈值拒绝、暂停或截断正在执行的任务；优化应先消除确定性失败、重复读取和无效治理调用，并继续保留 TDD、测试和风险相称的安全评审。没有账单或外部 Broker 时保持证据不完整或验证失败，不能以人工例外软通过。

出现任一效率膨胀时，必须按相同 workload、git ref、模型、权限和执行参数补做 `routing_ablation`；每臂至少重复两次，并随机化或交错运行顺序。若要因果判断委派本身的成本或质量贡献，再执行 `delegation_ablation`：内联矩阵评审、矩阵加风险触发的正交委派、同期 full-treatment 控制组；记录委派次数、未闭合假设数、主/子 Agent 证据重叠和重复全量评审。必要性材料必须绑定 workload digest、candidate treatment digest、独立质量量表及原始 usage/timing evidence refs，逐项说明新增 Token 对质量或安全的不可替代贡献。人工评审只可作出“继续优化”“拒绝 treatment”或“记录为 RC 例外候选”的处置；处置记录不能改写原始结果，也不能让失败 canary 自动通过。接受 RC 例外、调整阈值或进入稳定版仍需单独明确授权。

## 失败处理

- workload、environment、execution config 或 quality rubric 摘要不匹配：重新固定同一实验条件并重跑对应配对。
- baseline 与 candidate 的 treatment 摘要相同：重新计算真实处理内容摘要，不能用分支名或 git ref 代替。
- broker 不可信、回执 inactive 或 claims 不一致：停止使用该回执，由宿主管理员修复 trust binding 或 broker；Runtime 不得降级为自签。
- usage、timing、成本或质量来源缺失：保持 `incomplete`，不能以 token 推算账单、用起止时间替代真实墙钟测量，也不能由执行 Agent 自评替代独立评分。
- 某项指标未过阈值：保留原始证据并记录反馈处置，优化后以新的 treatment 和 bundle 重跑；不得覆盖失败证据。
