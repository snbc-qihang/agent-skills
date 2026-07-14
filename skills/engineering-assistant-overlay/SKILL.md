---
name: engineering-assistant-overlay
description: Use when Engineering Assistant is loaded and user-local workflow gates, overlay rules, capability health, run feedback, artifact persistence, self-healing, or project-specific guardrails may affect the task.
---

# Engineering Assistant Durable Overlay

This overlay patches the cached marketplace Engineering Assistant without modifying the cache as the only source of truth. Cached plugin files may be refreshed by Codex or marketplace updates; this overlay is the durable user-local policy layer.

## Required rule

Every Engineering Assistant run must distinguish three layers:

1. `window_context`: rules remembered in the current Codex conversation.
2. `active_plugin`: files loaded from `/Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1`.
3. `durable_overlay`: files loaded from `/Users/fengtianyangyang/.codex/skills/engineering-assistant-overlay`.

Do not claim a capability is installed just because it exists in `window_context`. The capability must exist in `active_plugin` or `durable_overlay`, and the final response must state the source when relevant.

## Overlay hierarchy and context scope

Before development, debugging, review, E2E testing, or self-healing, classify project/repo/module/surface/runtime scope and read `references/context-scope-routing.md` when multiple services, modules, APIs, pages, or prior samples are involved. For durable rule changes, read `references/overlay-scope-hierarchy.md`; keep global overlay project-neutral, and route project/module rules to the project overlay hierarchy.

Gates: `CONTEXT_SCOPE_UNCLASSIFIED`, `CONTEXT_LOAD_PLAN_MISSING`, `CROSS_MODULE_CONTEXT_POLLUTION`, `SCOPED_FACT_PACKET_MISSING`, `OVERLAY_LAYER_UNCLASSIFIED`, `PROJECT_MODULE_OVERLAY_ROUTE_MISSING`, `PROJECT_SPECIFIC_RULE_IN_GLOBAL_OVERLAY`.

## Multi-window coordination

When the user explicitly asks to open, create, fork, name, command, or coordinate multiple visible Codex windows, read `references/multi-window-coordination.md` before using thread tools. User-facing text must say "window", not subthread. Creating or forking a visible window requires explicit user authorization. The controller must first produce `required-information-requests.json` and `window-plan.json`, then read/reconcile `window-registry.json`, reuse registered logical windows, and keep old context historical-only. For two or more ready tasks with no dependency or write conflict, dispatch every ready worker in one concurrent tool batch before any wait/read; use serial waves only for declared dependencies, conflicts, or runtime concurrency limits. Worker outputs must be read and consumed behind a completion barrier before summary.

Gates: `EXPLICIT_WINDOW_CREATION_REQUIRED`, `REQUIRED_INFORMATION_REQUESTS_MISSING`, `WINDOW_REGISTRY_MISSING`, `WINDOW_SCOPE_UNCLASSIFIED`, `WINDOW_NAME_MISSING`, `BUSINESS_REVIEW_PENDING`, `DESIGN_REVIEW_REQUIRED`, `REQUIREMENT_FREEZE_REQUIRED`, `API_CONTRACT_REQUIRED`, `TRACEABILITY_MATRIX_REQUIRED`, `DEVELOPER_CONFIRMATION_REQUIRED`, `INDEPENDENT_TEST_REQUIRED`, `SELF_REVIEW_FORBIDDEN`, `MULTI_WINDOW_FILE_CONFLICT_UNCHECKED`, `MULTI_WINDOW_PARALLEL_DISPATCH_SKIPPED`, `WORKER_WINDOW_OUTPUT_NOT_CONSUMED`, `REPEATED_FIX_DIAGNOSTIC_RESET_REQUIRED`, `WINDOW_REGISTRY_REUSE_SKIPPED`, `WINDOW_REPLACEMENT_NOT_RECORDED`, `STALE_WINDOW_CONTEXT_USED_AS_FACT`.

## Debate mode

When the user explicitly asks for debate mode, the same issue failed after a prior fix, or a change is high-risk with uncertain root cause, read `references/debate-mode.md`. Use lightweight debate for one bounded plan with blocking objections. Route to the installed Council integration when two or more independent hypotheses, designs, or reviewer positions should be evaluated in parallel. Debate and Council must have a correction reviewer or equivalent scope guard, evidence-backed objections, and a hard stop condition; if facts or scope are missing, stop at `waiting_for_input`.

Gates: `DEBATE_MODE_UNBOUNDED`, `DEBATE_CORRECTION_REVIEWER_MISSING`, `DEBATE_BLOCKING_OBJECTION_UNCLASSIFIED`.

## Council mode

For a complete complex L2/L3 proposal, cross-module decision, repeated bug, fix-A-break-B regression, uncertain root cause, material reviewer disagreement, or an explicit Council request that passes the efficiency gate, load `/Users/fengtianyangyang/.codex/skills/engineering-assistant-council-integration/SKILL.md`. The main Agent must first author one complete baseline proposal. Freeze that proposal with current source evidence, then dispatch 2-4 read-only audit specialists as one parallel ready set. Auditors inspect the same proposal, cross-review one another's findings, answer challenges, and review the main Agent's final revision; they do not create competing complete proposals. Prefer internal subagents; visible windows still require explicit user authorization. Keep `external_model_api_enabled=false` by default. Council opinions never override build, test, lint, architecture, security, migration, or human-approval gates.

Required artifacts remain exactly `council-plan.json`, `council-member-outputs.json`, and `council-decision.json`; baseline, audits, cross-review, responses, final proposal, and final reviews are embedded rather than creating another report. Council stops after two rounds and does not write business code. Passing internal audit produces `status=ready_for_user_review` and `development_gate_status=awaiting_user_review`; the complete final proposal is then presented to the user. Implementation requires approval of that exact proposal, `status=recommend`, deterministic gates passing, `development_gate_status=pass`, and empty unresolved cross-review and blocker/major finding ids. Unanimity is not required; experiments and human decisions keep development blocked.

Gates: reuse `SCOPED_FACT_PACKET_MISSING`, `DEBATE_MODE_UNBOUNDED`, and `CAPABILITY_OUTPUT_NOT_CONSUMED`; use `COUNCIL_PARALLEL_DISPATCH_SKIPPED`, `COUNCIL_DELIBERATION_MISSING`, `COUNCIL_UNRESOLVED_BLOCKERS`, and `COUNCIL_DETERMINISTIC_GATE_OVERRIDE_ATTEMPT` only for Council-specific failures.

## Assistant rule and capability audit edit boundary

When the user is reporting, auditing, or changing Engineering Assistant behavior, skills, overlay rules, capability routing, self-evolution, SkillOpt-Sleep, Darwin, or "研发助手规则缺陷", classify the run as `task_kind=audit` or `task_kind=self_healing` unless the user explicitly asks to modify a target business repository.

Required checks before any target repository edit:

- `assistant_rule_or_capability_audit`: true when the latest user intent is about Engineering Assistant rules/capabilities rather than target product behavior.
- `explicit_project_code_change_requested`: true only when the user explicitly asks to change project/business code, not when they describe a failure caused by Engineering Assistant.
- `target_repo_edits`: list every planned or actual edit outside Engineering Assistant skill/plugin/profile roots.
- `allowed_edit_roots`: restrict edits to Engineering Assistant skill/plugin/profile paths for audit/self-healing runs unless explicit project code change is confirmed.

If `assistant_rule_or_capability_audit=true`, `explicit_project_code_change_requested=false`, and `target_repo_edits` is non-empty, stop, revert agent-caused target repo edits, and mark `ASSISTANT_AUDIT_TARGET_REPO_EDIT_FORBIDDEN`.

Do not reinterpret "处理研发助手问题", "规则缺陷", "skill 能力问题", "overlay 问题", or "为什么研发助手做错了" as permission to edit business code.

## Positive skill instruction shape

When adding or revising Engineering Assistant skills, overlay rules, project profiles, gates, workflow instructions, or self-healing guidance, write the instruction as an executable path before writing the failure gate.

Required shape:

- `trigger`: when this skill, rule, or gate should be read or applied.
- `do`: the positive target behavior and first concrete actions.
- `checks`: how Codex confirms the behavior is complete.
- `gate`: the failure marker only after the positive path is unavailable, skipped, or contradicted by evidence.

Use `description` frontmatter for trigger conditions. Put operational steps in the body. Put completion evidence in checks. Prefer "When X, do Y, verify Z" over blocker-first instructions.

Before merging a new or changed rule, record `skill_instruction_review` with:

- `description_is_trigger_only`
- `positive_target_behavior_present`
- `completion_checks_present`
- `gate_only_or_prohibition_first`
- `instruction_shape.trigger`
- `instruction_shape.do`
- `instruction_shape.checks`
- `instruction_shape.gate`

If a rule only says what not to do, starts from a prohibition/gate, or lacks completion checks, rewrite it into the required shape. If it is kept without that shape, mark `POSITIVE_SKILL_INSTRUCTION_SHAPE_MISSING`.

## Before-edit operating protocol

Trigger:

Before any non-trivial Engineering Assistant edit. Use this as a small execution protocol, not as a user-facing form. The goal is to do enough source-fact work before changing anything while keeping simple tasks fast.

Do:

1. Pick the lightest safe path before editing:
   - `L0_FAST`: typo-only comments, log text, formatting, or unused local code with no runtime behavior change.
   - `L1_DIRECT`: one function/class or direct behavior with local callers/tests.
   - `L2_SHARED`: DTO/entity/enum/API/Feign/DB/cache/MQ/index/read-model/shared-service/shared-tool changes.
   - `L3_CRITICAL`: money, price, inventory, order, payment, refund, member rights, coupon, permission, state machine, external sync/import/export, production config, or migration/backfill.
2. Run the minimum source-fact scan for the chosen path:
   - L0: read the target lines and verify the edit is local-only.
   - L1: read the file plus direct caller/callee or direct test/usage.
   - L2: search the changed symbol/field/key across the repo and identify producers, nearest consumers, shared contracts, and tests.
   - L3: do the L2 scan plus identify protected existing behavior, a consumer/preservation check, and a rollback or disable path.
3. Patch only after the source facts identify the owner path. If ownership or cross-module consumers are unclear, stop for diagnosis/design instead of guessing.
4. Keep user-facing output compact: normally report only the risk path, changed fact, key consumers, protected behavior, and verification. Do not expose full internal maps unless the task is high-risk, blocked, under review, or the user asks.
5. Block only when a required fact cannot be read from source/logs/tests or when multiple valid business decisions remain. Otherwise act with the best-supported minimal change.

Checks:

- `context_level`: L0/L1/L2/L3 with one-line reason.
- `changed_fact`: the fact being changed, not just the file.
- `source_fact_scan`: files/searches/tests used for the chosen path.
- `nearest_consumers`: direct consumers for L1; cross-module producers/consumers for L2/L3.
- `protected_behavior`: existing behavior that must survive for L2/L3.
- `smallest_verification`: target check plus preservation/consumer check when required.
- `rollback_or_disable_path`: present for L3 or production-impacting changes.

Gate:

Use the narrowest marker only when the positive path above was skipped or impossible:

- `CONTEXT_UNDERSTANDING_BEFORE_CHANGE_MISSING`
- `CHANGE_CONTEXT_LEVEL_UNCLASSIFIED`
- `CHANGED_FACT_UNIDENTIFIED`
- `PRODUCER_CONSUMER_MAP_MISSING`
- `PROTECTED_INVARIANT_MISSING`
- `VERIFICATION_PLAN_TOO_LOCAL`
- `REGRESSION_SURVIVAL_GATE_MISSING`
- `ROLLBACK_OR_DISABLE_PATH_MISSING`

## Conditional engineering gates

Trigger:

After the before-edit protocol selects L1/L2/L3, expand only the gates that match the actual risk. Do not run every gate for every task. This section replaces checklist pile-up with conditional routing.

Default for all non-trivial edits:

- Read source facts before editing.
- Record the changed fact, owner path, nearest consumers, and smallest verification.
- Prefer existing project patterns and local helpers before adding new code.
- Keep the user-facing plan/status to 3-5 bullets unless the run is blocked or high-risk.

Expand only when triggered:

- Business capability or shared service change: add compact design intake and owner/domain boundary.
- New abstraction, framework, SDK-like code, retry/cache/polling/state machine, or hand-written infrastructure: add over-design boundary plus project/framework reuse decision.
- Customer-facing page/API, production latency/CPU/memory issue, or multi-step flow: add performance budget or flow performance budget.
- Frontend/backend responsibility ambiguity: classify invariant ownership versus presentation ownership.
- Sync/import/backfill/external data: verify downstream usability, not just write success.
- Repeated failure, "still broken", or "fix A broke B": run diagnostic reset, known-good preservation, and sibling/consumer regression check.
- Git conflict, cherry-pick, branch sync, or cross-branch push: run feature-preservation and branch validation gates.
- Runtime/business configuration change: run config necessity review from `references/business-config-boundary.md`.
- Development run that claims completion beyond self-check: separate implementer verification from independent review.

Critical-path additions for L3:

- Identify the invariant that must not break.
- Run or create the smallest target check and one preservation/consumer check.
- Record rollback, disable, or safe fallback path.
- If the invariant or product decision cannot be inferred from source evidence, pause for human input.

Checks:

- `default_engineering_check`: changed fact, owner, consumers, smallest verification.
- `conditional_gate_selected`: only triggered gates are listed, with why each applies.
- `conditional_gate_skipped`: major gates intentionally skipped with one-line reason when relevant.
- `critical_path_guard`: invariant, preservation check, and rollback/disable path for L3.

Gate:

Use existing narrow markers for the triggered gate only; do not surface unrelated gates. Common markers include:

- `DESIGN_BEFORE_CODE_GATE_MISSING`
- `BUSINESS_CODE_PILEUP_UNCHECKED`
- `DESIGN_PATTERN_DECISION_MISSING`
- `OVER_DESIGN_BOUNDARY_UNCHECKED`
- `FRAMEWORK_REUSE_NOT_EVALUATED`
- `FRAMEWORK_INTEGRATION_NOT_EVALUATED`
- `API_PERFORMANCE_BUDGET_MISSING`
- `FLOW_PERFORMANCE_REGRESSION_UNCHECKED`
- `BUSINESS_REDUNDANCY_BOUNDARY_UNCHECKED`
- `DOMAIN_BOUNDARY_UNCLASSIFIED`
- `FRONTEND_BACKEND_RESPONSIBILITY_UNCLASSIFIED`
- `SYNC_DATA_USABILITY_NOT_VERIFIED`
- `DEVELOPER_REVIEWER_NOT_SEPARATED`
- `REPEATED_FIX_DIAGNOSTIC_RESET_REQUIRED`
- `GIT_CONFLICT_FEATURE_PRESERVATION_UNCHECKED`
- `CONFIG_NECESSITY_UNREVIEWED`

## Engineering code quality constitution

Trigger:

For L1/L2/L3 implementation, refactoring, simplification, or code review, and whenever repository quality is weak or new complexity is proposed.

Do:

Read `references/engineering-code-quality-constitution.md`. Apply the Engineering Assistant quality floor above non-conflicting repository conventions, produce independent `spec_verdict` and `quality_verdict`, and require current evidence before adding abstractions, patterns, dependencies, configuration, or extension points. Keep L0 fast and keep remediation inside the changed ownership slice.

Checks:

- `quality_rule_hierarchy`, independent verdicts, changed-scope smell evidence, conditional complexity evidence, and target plus preservation verification.
- Stack-specific standards such as DDD, JDK features, framework conventions, and static-analysis metrics are conditional profiles or signals, not universal architecture or standalone pass/fail rules.

Gate:

- `ENGINEERING_QUALITY_FLOOR_BYPASSED`
- Reuse `OVER_DESIGN_BOUNDARY_UNCHECKED` and `CHANGE_VERIFICATION_EVIDENCE_MISSING`; do not add duplicate quality markers.

## User-facing output discipline

Trigger:

Every Engineering Assistant response, especially after loading overlay rules or running gates.

Do:

1. Keep internal gates internal by default. Use them to guide actions; do not make the user read the checklist unless they ask or the task is blocked/high-risk.
2. For normal L0/L1/L2 tasks, explain in 3-5 bullets: risk path, source facts checked, decision, change, verification.
3. Ask the user only for facts that cannot be read from source/logs/tests or for real product trade-offs. Do not ask the user to fill matrices the assistant can derive.
4. Prefer "I checked X, found Y, will do Z" over gate names, artifact names, or workflow jargon.
5. For high-risk or blocked work, summarize the impact map and blocker; keep full matrices in run artifacts unless the user requests them.

Checks:

- `user_facing_summary`: concise and action/evidence oriented.
- `internal_gate_leak_check`: no unnecessary gate/artifact jargon in normal responses.
- `user_question_minimized`: questions are limited to unavailable facts or product decisions.

Gate:

- `INTERNAL_GATE_LEAKED_TO_USER`
- `USER_BURDENED_WITH_AGENT_CHECKLIST`
- `UNNECESSARY_USER_QUESTION`

## Self-improvement compression rule

Trigger:

When improving Engineering Assistant rules after a failure, user complaint, self-healing run, or capability audit.

Do:

1. Prefer rewriting an existing rule into a clearer executable path over adding a new rule.
2. Prefer merging duplicate gates and downgrading rarely needed checks to conditional routes.
3. Prefer default tool actions, stop conditions, and user-output discipline over new concepts or artifact names.
4. Add a new marker only when it catches a distinct failure mode that existing markers cannot express.
5. If a new rule increases ceremony, add the fast path and stop condition in the same edit.

Checks:

- `rule_compression_review`: what was merged, rewritten, downgraded, or left unchanged.
- `execution_path_added`: new guidance says what to do first, how to verify, and when to stop.
- `concept_count_justified`: new concepts/markers are minimized or explicitly justified.

Gate:

- `SELF_IMPROVEMENT_ADDED_CONCEPT_WITHOUT_EXECUTION_PATH`
- `RULE_COMPRESSION_SKIPPED`
- `FAST_PATH_OR_STOP_CONDITION_MISSING`

## External capability assimilation

Trigger:

When the user asks Engineering Assistant to install, absorb, merge, ingest, audit, or upgrade an external skill or capability pack.

Do:

1. Read `references/external-capability-assimilation.md` and inventory every source capability before changing the active overlay.
2. Keep Engineering Assistant as `sole_entrypoint` and `sole_gate_owner`. Reject the source router, slash commands, personas, and any controller that would compete with the Engineering Assistant workflow.
3. Build an overlap matrix and absorb only evidence-backed deltas. Adapt accepted ideas into existing Engineering Assistant owners; do not register the external pack as a parallel workflow.
4. Assign G0/G1/G2 using the protocol. G0 is hard blocking, G1 blocks only when its risk trigger is active, and G2 records an observation without invalidating correctness.
5. Register an independent local semantic version, run the finite historical regression set, validate with `scripts/validate_capability_assimilation.py`, and record rollback plus upgrade history.
6. For the active `ea-agent-skills-delta` pack, read `references/absorbed-agent-skills.md` only when one of its registered triggers matches the current task.

Checks:

- `capability_overlap_matrix`: every source skill has an absorption, coverage, deferral, or router-conflict decision.
- `capability_assimilation_registry`: sole owner, local version, source attribution, native owner, trigger, evidence, stop condition, gate level, and protected gates are present.
- `capability_acceptance`: all G0 cases pass, overall pass rate meets the declared threshold, and existing-gate regressions equal zero.
- `version_upgrade_boundary`: updates require a new local version and acceptance run; upstream commits never overwrite the active version automatically.

Gate:

- `EXTERNAL_CAPABILITY_GAP_NOT_PROVEN`
- `EXTERNAL_CAPABILITY_ROUTER_CONFLICT`
- `EXTERNAL_CAPABILITY_OVERLAP_UNCLASSIFIED`
- `EXTERNAL_CAPABILITY_GATE_LEVEL_MISSING`
- `EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED`
- `EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED`

## Window-context evidence

When the request points at the current window, browser/runtime state, ports, branches, commits, or "现在/刚才/之前", read `references/runtime-and-regression-guards.md`. Consume latest visible facts, verify source/runtime identity, and classify stale state before another edit.

Checks: `window_context_summary`, git evidence for branch claims, and PID/cwd/served-source evidence for local runtime claims.

Gates: `WINDOW_CONTEXT_NOT_CONSUMED`, `BRANCH_RUNTIME_EVIDENCE_MISSING`, `ACTIVE_RUNTIME_PROJECT_UNVERIFIED`.

## Repeated-fix and regression guard

When a bug recurs, a prior fix fails, or fix B may break accepted fix A, read `references/runtime-and-regression-guards.md` before editing. Build the symptom/invariant/surface map, protect known-good behavior, and patch the shared owner where evidence supports it.

Checks: `symptom_history`, `shared_invariant`, `surface_map`, `known_good_preservation`, `root_cause_location`, and a sibling-aware regression check. For fix chains, record `protected_fix_set` before editing and pass `regression_survival_gate` for A and B afterward.

Gates: `REPEATED_FIX_SURFACE_ONLY`, `REGRESSION_PRESERVATION_GATE_MISSING`, `REPEATED_FIX_RUNTIME_STATE_UNCLASSIFIED`, `FIX_CHAIN_REGRESSION_UNCHECKED`.

## Universal E2E test workflow

For 全流程、端到端、分布式流程测试, or project + branch + scenario requests, read `references/e2e-test-workflow.md` before test execution or code edits. Classify `NO_E2E`/`LIGHT_FLOW`/`FULL_E2E`; require a confirmed scenario contract for full E2E; after fixes, prove refreshed runtime, retest the blocker, continue the flow, then run the final full scenario.

Checks: `e2e_classification`, conditional `scenario_contract`, `missing_information`, `agent_strategy`, `failure_progression_gate`, and `project_flow_memory_candidate`.

Gates: `UNIVERSAL_E2E_TEST_WORKFLOW_MISSING`, `E2E_TEST_CLASSIFIER_SKIPPED`, `E2E_SCENARIO_CONTRACT_UNCONFIRMED`, `E2E_RUNTIME_CONTINUATION_GATE_MISSING`, `PROJECT_FLOW_MEMORY_NOT_RECORDED`.

## Validation output triage

After build, test, smoke, or service-start commands, read the triage section in `references/java-validation-and-branch-sync.md`. Report `blocking_errors`, `non_blocking_warnings`, `legacy_noise`, and final command status. Missing this split is `VALIDATION_OUTPUT_NOT_CLASSIFIED`.

## Java compile-fix discipline

For Maven, IDE, or pasted Java compiler errors, read `references/java-validation-and-branch-sync.md` before editing. Cluster errors by root cause, patch the first blocking cluster, and verify the narrow touched scope before broader checks.

Checks: `compile_error_clusters`, `touched_scope_gate`, optional `full_scope_gate`, `legacy_debt`, `final_status`. Gate: `JAVA_COMPILE_FIX_SCOPE_UNCLASSIFIED`.

## Java branch-sync validation gate

For Java cross-branch commit, cherry-pick, or push work, read `references/java-validation-and-branch-sync.md`. Use cherry-pick, preserve destination-only behavior, scan signature drift, and rerun touched-scope validation on every destination before push.

Checks: `branch_sync_map`, `feature_preservation_gate`, `signature_drift_scan`, per-branch `branch_touched_scope_gate`, conditional `nacos_exclusion_gate`, `final_status`.

Gates: `JAVA_BRANCH_SYNC_VALIDATION_MISSING`, `JAVA_BRANCH_SYNC_FEATURE_LOSS_UNCHECKED`.

## External system and data-source guards

For external-system sync, import, projection, real database writes, or external side effects, route to the active project/module overlay before acting. The global layer requires source-layer separation, mutation-target confirmation, customer-visible source restrictions review, and downstream usability evidence; project-specific source names and table layers live in project/module overlays.

## Self-improvement evidence

For self-healing, sleep, evolution, compression, or live skill optimization, read `references/self-improvement-evidence.md` before editing. Record Darwin maturity/effect evidence and SkillOpt-Sleep status or dry-run evidence; Sleep adoption still requires a staged improvement and explicit approval.

Checks: target, maturity before/after, validation effect, Sleep action/source/backend/scores/gate/staging, and rollback. Gates: `SKILLOPT_SLEEP_CONTEXT_FALLBACK_NOT_RUN`, `SKILLOPT_SLEEP_GATE_NOT_RECORDED`, `SKILLOPT_SLEEP_ADOPT_WITHOUT_APPROVAL`.

## Startup self-check

At the beginning of Engineering Assistant tasks that involve workflow gates, audit, development, self-healing, or L4 readiness, run or apply:

`scripts/validate_active_engineering_assistant_capabilities.py`

Required capability set is maintained in `config.yaml` and enforced by `scripts/validate_active_engineering_assistant_capabilities.py`.

If any required capability is not present in either active plugin or overlay, mark `ACTIVE_ENGINEERING_ASSISTANT_CAPABILITY_MISSING` and do not claim L4 readiness.

## Run artifact feedback intake

For audit, upgrade, self-healing, continuation, or prior-behavior review, read `references/closed-loop-evolution.md` and consume the latest relevant feedback/outcome plus available trace/index/approval artifacts before planning. Gates: `NEXT_RUN_FEEDBACK_NOT_CONSUMED`, `ASSISTANT_RUN_ARTIFACT_INTAKE_SKIPPED`.

## Agent-consumed feedback

Every run end, pause, block, or handoff must produce and consume agent-owned feedback using `references/closed-loop-evolution.md`. Required contract: `feedback_owner=codex_agent`, agent review required, feedback read before final response, and no request for the user to audit raw artifacts. Gates: `ASSISTANT_FEEDBACK_NOT_GENERATED`, `ASSISTANT_FEEDBACK_NOT_CONSUMED_BY_AGENT`.

## Closed-loop evolution record

For non-trivial endings, repeated fixes, code changes, E2E, handoffs, or assistant-quality feedback, read `references/closed-loop-evolution.md`. Generate `closed-loop-outcome.json` beside feedback and validate both with `scripts/validate_feedback_pair.py`; record execution, trajectory distillation, compression/augmentation, reinforcement signal, external evidence, independent review, project-memory candidates, and next-run context.

Gates: `CLOSED_LOOP_OUTCOME_NOT_RECORDED`, `NEXT_RUN_FEEDBACK_NOT_CONSUMED`, `TRAJECTORY_DISTILLATION_CANDIDATE_MISSING`, `SKILL_GATE_COMPRESSION_NOT_EVALUATED`, `REWARD_SIGNAL_NOT_RECORDED`, `EXTERNAL_EVIDENCE_STATUS_UNCLASSIFIED`, `INDEPENDENT_REVIEW_ENFORCEMENT_MISSING`, `PROJECT_LONG_MEMORY_NOT_UPDATED`.

## Overlay and record growth control

Before adding durable overlay rules, long examples, detailed protocols, or recurring run records, read `references/overlay-retention-boundary.md`. Keep `SKILL.md` as the routing and gate surface; move detailed protocols, examples, schemas, and long explanations into references, scripts, schemas, or run artifacts.

Checks:

- `overlay_compaction_review`: duplicate, stale, project-specific, overlapping, or too-detailed durable additions checked.
- `overlay_size_budget`: `SKILL.md`, references, and record files checked against soft/hard budgets.
- `run_artifact_retention_review`: expiry, keep list, and formal-retention approval recorded.
- `record_file_rotation`: long cumulative files summarized or archived before continued appends.

Gate:

- `OVERLAY_COMPACTION_REVIEW_MISSING`
- `OVERLAY_SIZE_BUDGET_EXCEEDED`
- `RUN_ARTIFACT_RETENTION_UNREVIEWED`
- `RECORD_FILE_ROTATION_MISSING`

## Artifact persistence

Default process-artifact root is `~/.codex/run-artifacts/engineering-assistant/<repo-slug>/<run_id>/`. Read `references/run-evidence-governance.md` for every non-inline run and `references/target-repo-doc-governance.md` before target-repository Markdown writes or cleanup. Process evidence remains ephemeral unless formal retention is explicitly approved.

Gates: `TARGET_REPO_ARTIFACT_POLLUTION`, `RUNTIME_ROUTE_NOT_SELECTED`, `NON_STANDARD_RUNTIME_ROUTE`, `TARGET_REPO_DOC_PURPOSE_UNCLASSIFIED`, `TARGET_REPO_DOC_CLEANUP_WITHOUT_APPROVAL`, `PROCESS_MD_WRITTEN_TO_PROJECT_DOCS`, `PROCESS_DOCUMENTATION_POLLUTION`.

## Route strictness

Use `references/run-evidence-governance.md`. A feedback record cannot pass with a missing, unknown, or non-standard `task_kind`, `evidence_level`, or `persistence_mode`; historical ad-hoc routes remain partial evidence only.

## Capability health

Before tool-backed output affects a decision, read `references/run-evidence-governance.md` and record health with `schemas/capability_health.schema.json`. Missing evidence is `CAPABILITY_HEALTH_NOT_CHECKED`.

## Capability output consumption

Called capability outputs must be recorded and consumed downstream per `references/run-evidence-governance.md` and `schemas/capability_output_consumption.schema.json`. Gates: `CAPABILITY_OUTPUT_NOT_CONSUMED`, `CAPABILITY_OUTPUT_NOT_RECORDED`, `NO_EFFECTIVE_CODE_CHANGE`, `CHANGE_VERIFICATION_EVIDENCE_MISSING`.

## Quality gate scope evidence

Use `references/run-evidence-governance.md` to separate `touched_scope_gate`, `full_scope_gate`, and evidenced `legacy_debt`. Unlabeled scope debt is `SCOPE_GUARD_LEGACY_DEBT_UNLABELED`.

## L4-entry status rule

Use the eight-condition L4 checklist in `references/run-evidence-governance.md`. No context/audit/change E2E evidence, feedback consumption, capability health/output consumption, or ephemeral process boundary means L4 is not proven.

## Gates added by overlay

Gate registry lives in `config.yaml`; deterministic marker checks live in `scripts/validate_active_engineering_assistant_capabilities.py`.

## Scripts and schemas

See `scripts/`, `schemas/`, and `templates/` for deterministic validators, generators, contracts, and feedback templates.
