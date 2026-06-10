# YQ DDD-first architecture inspection blueprint

Use this reference for high-level design or architecture inspection of the YQ/Yingqi system.

## Non-negotiable sequence

1. Establish phase-1 architecture planning first:
   - Yingqi–Renrenqu platform architecture relation.
   - Domain architecture diagram.
   - Business capability map.
   - Data boundary map.
   - Open questions and ADRs.
2. Only after phase 1 is reviewed, proceed to phase-2 norms/fixes:
   - MQ reliability rules.
   - Feign/fallback governance.
   - Table/database cutting execution.
   - Concrete refactor/backlog items.

If the user points out that you have moved into local governance too early, stop and reset to phase 1.

## Confirmed YQ architecture constraints

- YQ code is for 萤启业务.
- 人人取 provides platform base capabilities.
- 会员业务和会员数据 belong to 萤启.
- Platform base facts, such as real order modification, happen in 人人取.
- 萤启 listens to platform base data through MQ, keeps local copies, and implements customized business on top.

## Required diagrams in phase 1

- 萤启-人人取总体架构图.
- 萤启领域架构图.
- 数据边界图.

Diagrams may be Mermaid in Markdown for draft discussion. Do not present them as final if any component boundary is still an assumption.

## Evidence and discussion rule

Every architecture statement must be one of:

- code evidence
- doc evidence
- inference from evidence
- explicit decision
- open assumption/discussion item

Unsupported assumptions must be separated from final conclusions.

## Human-review shape

Human-facing outputs should be short:

- one-line conclusion
- confirmed decisions
- candidate boundaries
- open questions
- diagrams
- next decision needed

Put raw code analysis and scans in machine-readable artifacts.
