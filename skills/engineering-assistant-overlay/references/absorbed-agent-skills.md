# Absorbed Agent Skills Capability Pack

Local pack: `ea-agent-skills-delta` version `1.5.0`. This is an Engineering Assistant-native, multi-source adaptation. It is not an upstream router and does not expose upstream slash commands.

## 1. Bounded intent clarification

Trigger: the request has materially different interpretations or is missing an objective, target user, success criterion, constraint, or non-goal that changes the solution.

Do: `requirement-intake` reads source evidence first, infers what it can, and asks one question per turn only for the highest-impact unresolved fact. It stops without a final confirmation when the requirement is clear, or pauses after six questions if ambiguity remains.

Checks: no interview for clear/mechanical work, one question per turn, no more than six, explicit stop condition, and no planning or coding across unresolved material ambiguity.

Gate: G0 when ambiguity can change scope, architecture, data, security, or acceptance; otherwise G1.

## 2. Feasibility argumentation

Trigger: `L2_SHARED`, `L3_CRITICAL`, materially uncertain feasibility, repeated bug, or a decision with multiple credible paths.

Do: `requirement-intake` compares up to three meaningful candidates against current architecture/code, exact dependencies and local reuse, data/external systems, risks/rollback, tests, and delivery cost. It records a selected path and rejected reasons, or stops with blocking evidence and the nearest viable alternative.

Checks: verdict is `executable`, `executable_after_conditions`, or `not_executable`; conditions and stop/resume behavior match the verdict; complex evidence dimensions are complete; fresh review receives artifact and contract without author claims when triggered.

Gate: G0 for L3, repeated bug, fix-A-break-B, and `not_executable`; G1 for other L2 decisions.

## 3. Fresh-context doubt review

Trigger: a repeated bug, fix-A-break-B chain, L3 or cross-module decision, or two plausible causal/design hypotheses.

Do: extract the smallest artifact and its contract without the author's conclusion; send it to a fresh read-only reviewer with an adversarial issue-finding instruction. Reconcile each finding as contract misread, actionable, accepted trade-off, or noise. Council may supply parallel reviewers when its efficiency trigger is met.

Checks: isolated artifact/contract packet, reviewer independence, finding reconciliation, and at most two Engineering Assistant Council rounds or three lightweight doubt cycles.

Gate: G0 when required for repeated/fix-chain/high-risk evidence; otherwise G1. Use existing Council and deterministic gates; reviewer opinion never overrides tests.

## 4. Authoritative source verification

Trigger: implementation correctness depends on a JDK, framework, library, build tool, runtime, or API version.

Do: read the project's exact dependency/runtime version, inventory existing local utilities and conventions, then verify the selected API against primary official documentation. Record why the selected project/JDK/library capability is preferable to the rejected alternatives.

Checks: version evidence, official source, local reuse inventory, changed-scope decision, and citation or source path.

Gate: G1 for non-trivial framework-dependent L1/L2/L3 changes; G2 for optional modernization. Do not force Stream, Optional, a library, or a design pattern when explicit code is clearer.

## 5. Bounded hypothesis recovery

Trigger: a defect survived a fix, root cause is uncertain, or validation fails after a patch.

Do: reproduce first; record one ranked hypothesis and one falsification experiment per iteration; distinguish source defect from stale runtime/cache/data/deployment state. After two failed patch attempts, stop patching and route to Council or human review with the accumulated evidence.

Checks: symptom history, reproduction, hypothesis ledger, falsification result, protected behavior, runtime-state classification, and target plus preservation test.

Gate: G0 for repeated bugs, fix chains, and deterministic failing checks.

## 6. Context-budgeted handoff

Trigger: multi-module, multi-window, Council, or long-running work requires context transfer.

Do: the sole controller builds a selected capability/task dependency DAG, freezes shared contracts under one owner, and sends each worker only a source-labelled scoped fact packet, contract, ownership boundary, expected artifact, and stop condition. Dispatch every independent ready worker before waiting, then consume all outputs behind a completion barrier. Workers cannot recursively spawn workers or replan the global DAG.

Checks: no stale conversation treated as fact, no overlapping writer ownership, packet checksum/provenance when high risk, parallel ready-set evidence, and output consumption.

Gate: G1. Existing multi-window conflict and parallel-dispatch gates remain authoritative.

## 7. Post-green simplification

Trigger: target behavior and preservation tests pass, and the changed diff contains duplication, unnecessary indirection, unrelated rule concentration, or avoidable custom infrastructure.

Do: simplify only the changed ownership slice. Prefer project/JDK/framework capabilities already evidenced; preserve public behavior and test seams. Use Chesterton-style preservation: explain the purpose of an existing structure before removing it.

Checks: green baseline, simplification candidate, before/after diff, protected behavior, and rerun result.

Gate: G2 by default; elevate to existing G1 business-code-pileup handling only when the diff provides concrete pileup evidence.

## 8. Observability and release evidence

Trigger: customer-visible flows, async work, retries, partial failure, production-impacting changes, or formal release claims.

Do: identify the failure signals needed to diagnose the changed flow, reuse the project's logging/metrics/tracing stack, test useful failure-path telemetry, and bind release claims to build/test/static-analysis/runtime evidence plus rollback or disable instructions.

Checks: observable failure path, correlation identity where relevant, no sensitive-data leakage, required release evidence status, and rollback/disable path.

Gate: G1 for formal release or production-impacting work; G2 for optional local instrumentation.

## 9. Independent quality constitution

Trigger: L1/L2/L3 implementation or review, especially when project conventions are incomplete, contradictory, or low quality.

Do: read `engineering-code-quality-constitution.md`; apply its rule hierarchy and issue separate `spec_verdict` and `quality_verdict`. Repository precedent cannot lower correctness, ownership, testability, behavior-preservation, or minimal-complexity requirements.

Checks: rule hierarchy, two verdicts, changed-scope smell evidence, and a bounded remedy. Static metrics and pattern counts remain signals, not standalone gates.

Gate: G1 through `ENGINEERING_QUALITY_FLOOR_BYPASSED`; deterministic correctness and security failures retain their existing G0 gates.

## 10. Evidence-based complexity control

Trigger: a change or review suggestion adds an abstraction, pattern, dependency, option, extension point, framework integration, or custom infrastructure.

Do: prove the current problem, compare the simpler path, record concrete complexity evidence, define ownership and test seams, and reject hypothetical future work. Use existing `OVER_DESIGN_BOUNDARY_UNCHECKED` and verification gates rather than adding a parallel architecture workflow.

Checks: evidence can be a current stable variation, real external boundary, protected invariant, measured coupling/failure history, or verified framework requirement. Counts alone neither require nor forbid an abstraction.

Gate: G1 when new complexity is introduced; G2 when the result is only an optional simplification observation.

## 11. Bounded single-proposal multi-Agent audit

Trigger: a complete complex L2/L3 proposal, repeated bug, fix-A-break-B chain, uncertain root cause, or material reviewer disagreement requires adversarial audit before user review.

Do: the main Agent authors one complete baseline proposal. The Council controller dispatches 2-4 independent read-only auditors in parallel against that same proposal. Auditors produce findings rather than competing plans, cross-review one another's findings, and answer challenges. The main Agent responds to every finding, produces one final revision, and every auditor reviews that exact revision. A second round is allowed only to test changed evidence or resolve a blocker.

Checks: the baseline is complete before dispatch; all auditors reviewed it; every audit was cross-reviewed; every challenge and finding has exactly one owner response; every auditor reviewed the final revision; at most two rounds ran; unresolved cross-review and blocker/major finding ids are empty. Internal pass stops at `ready_for_user_review`; only user approval of the exact final proposal unlocks development. `no_issue` is valid; manufactured objections, competing-plan voting, and forced unanimity are not.

Gate: G0 when the trigger applies before development. Use `COUNCIL_DELIBERATION_MISSING` or `COUNCIL_UNRESOLVED_BLOCKERS`; simple or single-path tasks skip Council with an evidenced reason.

## Source Boundary

These capabilities adapt selected ideas from `addyosmani/agent-skills`, including its doubt-driven and Agent Teams orchestration guidance, plus `mattpocock/skills`, `anthropics/claude-plugins-official`, and `obra/superpowers` under their respective licenses. Engineering Assistant owns local naming, wording, routing, gate levels, schemas, tests, versioning, and future upgrades. Audited routers and playbooks that compete with this controller remain rejected or deferred.
