# YQ 架构巡检治理规则

Use this reference when inspecting `/Users/sunliming/work/project/snbc/yq` or any YQ/Yingqi architecture work.

## Project-level facts confirmed by the user

- YQ services focus on 萤启业务.
- Feign/API calls mostly represent 人人取平台能力, but this is not enough by itself to prove target domain ownership.
- 会员数据和会员业务属于萤启, not 人人取.
- 萤启依托人人取平台基础能力, but must be able to evolve independently.
- 人人取平台 owns actual base-business-data mutations such as real order modification.
- 萤启 listens to 人人取 platform base-business-data changes via MQ, keeps local copies, and builds customized business functions on top of platform capabilities and local copies.

## Required phase order

Do not jump from static findings into local refactoring or concrete governance.

Phase 1 must settle architecture planning first:

1. 萤启-人人取总体架构关系.
2. 领域划分: core/supporting/generic/external platform capabilities.
3. 业务能力划分.
4. 数据边界: 萤启自有业务事实, 人人取平台基础事实, 本地副本, 集成治理数据.
5. 架构图: 萤启-人人取 architecture diagram and 萤启 domain architecture diagram.
6. Open questions and ADRs for anything not backed by code/docs or user decision.

Only after Phase 1 is reviewed should Phase 2 discuss specific norms or fixes such as MQ reliability, listener rewrites, Feign fallback, table split execution, or local code refactors.

## Evidence discipline

Classify every meaningful statement:

- `code_evidence`: backed by path/class/method/config/table evidence.
- `doc_evidence`: backed by existing design/requirement/interface docs.
- `inferred`: derived from evidence; include the reasoning chain and uncertainty.
- `assumption`: useful but unsupported; must go to discussion/open questions, not final conclusions.
- `decision`: confirmed by user/stakeholder; record as ADR with impact.

No unsupported architecture claim should appear as a final conclusion.

## Human vs machine artifacts

Separate outputs:

- Human-facing: conclusions, risks, decisions, open questions, diagrams, recommended next decision.
- Machine-facing: raw scans, code paths, line numbers, Feign/MQ/DB inventories, inference chains, JSON/YAML/CSV evidence.

Human reviewers should not need to read analysis process or raw evidence dumps.

## YQ data boundary vocabulary

- Platform base fact: true source of platform data, e.g. real platform order state in 人人取.
- Yingqi local copy: data copied from platform events/API for local query/decision/customization.
- Yingqi business fact: customized business state owned by 萤启, e.g. membership, SVIP, benefits usage, coupon relation, fulfillment extension, idempotency/compensation records.
- Integration governance data: MQ raw message, consumer idempotency, sync watermark, dead-letter/compensation state.

## Common pitfall

Do not treat an existing service name such as `mp-mall`, `franchisemanagement`, or `coupon-activity` as the domain boundary. These are historical code containers. Domain boundaries must be expressed in business terms and then mapped back to current services with evidence.
