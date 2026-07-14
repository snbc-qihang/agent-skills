# Multi-window Coordination

Use this reference only when the user explicitly asks to open, create, fork, name, command, or coordinate multiple visible Codex windows.

## Terminology

- `controller_window`: the current visible Codex window that owns decomposition, dispatch, status reading, conflict handling, and summary.
- `worker_window`: a user-visible Codex work window with a title, role, module scope, and task brief.
- `threadId`: the underlying implementation identifier. Show it to the user as a window id, not as a subthread.

Do not describe this capability as hidden subthreads, internal subagents, or background workers. Use "window" in user-facing text.

## Entry Rule

Creating or forking a visible Codex window requires explicit user authorization. If authorization is absent, produce a window plan and wait.

Allowed trigger examples:

- `开启多窗口协调模式`
- `当前窗口做主控`
- `创建工作窗口`
- `给窗口命名`
- `派生多个窗口`
- `指挥多个窗口干活`

## Preflight Required Inputs

The controller performs source-first clarification before creation. It first produces:

- `required-information-requests.json`
- `window-plan.json`

Required facts, preferably inferred from source and existing run context:

- project path and target branch;
- business goal, target users, in-scope items, and out-of-scope items;
- affected clients, modules, pages, APIs, data/config boundaries, and forbidden areas;
- permission to create visible windows, write code, and use fork/worktree isolation;
- test environment, accounts, tokens, test data, and external-system call permission;
- acceptance criteria, reviewers, release/verification owners, and risk areas.
The controller may infer all facts supported by repository, profile, run history, and user context. Do not ask the user to reconfirm source-verifiable facts. If a missing fact creates materially different execution paths, ask exactly one question per turn under the bounded requirement clarification standard. Visible window creation and high-risk actions still require explicit authorization. If a critical fact remains missing, set the coordination status to `waiting_for_input`; otherwise continue without a final routing confirmation.

## Controller Boundary

`workflow-orchestrator` is the sole owner of the global dependency DAG, scheduling, conflict decisions, and completion barrier. Worker windows and internal workers execute one frozen task contract; they cannot create or command other workers, expand global scope, or replan sibling tasks. A reviewer receives only the artifact under review plus its contract and source references, not the author's claim or reasoning.

Each dispatch packet must be focused and source-labelled:

- current objective and acceptance conditions;
- artifact and contract inputs required by that task;
- verified source facts and exact stack versions;
- allowed and forbidden write scopes;
- dependencies, protected invariants, and expected outputs;
- context budget or explicit omitted-context list.

Old window history, summaries, and author conclusions are hints only until reverified against the packet.

## Workflow

1. Parse the user goal, project, branch, write permissions, and whether window creation/fork is authorized.
2. Produce `required-information-requests.json` and `window-plan.json`: selected tasks only, roles, modules, file boundaries, required contracts, review gates, test windows, and conflict policy.
3. Wait for confirmation when required inputs, write permission, or window creation authorization are missing.
4. Read `window-registry.json` and reconcile existing logical windows before creating any new window.
5. Create `window-registry.json` before dispatching work if it does not exist. It records every window `window_key`, `threadId`, name, role, responsibilities, module scope, edit permission, outputs, health, replacement history, and status.
6. Create or fork only the windows approved by the user and only after reuse/reconciliation proves the logical window is missing, inaccessible, invalid, or explicitly requested for replacement. Immediately name each new window.
7. Build the dependency/conflict graph from routed Skills and implementation slices, select the current ready set, and dispatch all conflict-free ready windows as one concurrent batch. Do not create extra windows merely to demonstrate parallelism.
8. After the whole batch is accepted, wait/read statuses behind a completion barrier. Unread worker output cannot be treated as complete.
9. Block if multiple write windows may edit the same file, config, API contract, business rule, or migration without worktree or single-owner isolation.
10. Summarize with `coordination-summary.md`, including consumed outputs, unresolved questions, conflicts, and next action.

## Parallel Dispatch Contract
Trigger: apply whenever at least two planned tasks are ready at the same dependency level.
Do:
1. Record every task's `task_id`, `depends_on`, write scope, shared-contract ownership, and target `window_key` in `window-plan.json`.
2. Compute the ready set from tasks whose dependencies are complete. Remove only tasks with a proven write/contract conflict or an explicit runtime concurrency limit.
3. When the ready set has two or more tasks, issue all `send_message_to_thread` calls in one runtime-supported concurrent tool batch. Use `dispatch_method=concurrent_tool_batch` and `dispatch_barrier=dispatch_all_ready_before_wait`.
4. Do not perform `read_thread`, polling, waiting, integration, or completion handling for worker B before every worker in that ready set has been dispatched. The forbidden sequence is `send B -> wait/read B -> send C` when B and C were both ready.
5. After dispatch acceptance, wait for all workers in the batch, consume each output, resolve conflicts, then unlock the next dependency wave. Cap the default batch at four windows; split larger ready sets into bounded concurrent batches.
6. Freeze shared API, schema, message, and migration contracts under one owner before implementation workers that consume them are considered ready. Run the highest-risk or highest-uncertainty investigation wave first when it can invalidate the remaining plan.
Checks:
- `window-plan.json` uses `scheduling_policy.mode=dependency_aware_parallel`, declares a dependency DAG, planned batches, and any `serial_reason`.
- `dispatch-ledger.json` records each ready set, concurrent dispatch method, accepted sends, first wait/read time, and completion barrier; `validate_parallel_dispatch.py` must pass.
Gate: if two or more conflict-free tasks were ready but the controller waited for one before dispatching the others, mark `MULTI_WINDOW_PARALLEL_DISPATCH_SKIPPED`.

## Window Lifecycle And Reuse

`window-registry.json` is the source of truth for visible Codex windows. Each development flow must reuse registered logical windows first.
Lookup windows by stable logical key, not by title alone:

`project + module_id + role + responsibility`

Example keys:

- `bc-service:order-backend:backend_developer:implementation`
- `bc-service:order-backend:api_tester:api-contract-test`
- `bc-admin:order-page:page_acceptance_tester:page-acceptance`

Reuse policy:

- default: `reuse_registered_window_first`
- recreate only when `thread_not_found`, `thread_inaccessible`, `host_unavailable_and_handoff_failed`, `window_role_or_module_scope_unrecoverable`, or `user_explicitly_requests_recreate`
- never recreate when the window is idle, has old context but the same role/module, or the title changed while `threadId` remains readable

Before development, the controller must:

1. Read `window-registry.json`.
2. Reconcile each needed `window_key` by checking the current `threadId`.
3. Mark health as `available`, `missing`, `inaccessible`, or `invalid_scope`.
4. Reuse available windows by sending a fresh task brief.
5. Recreate only invalid logical windows when user authorization permits it.
6. Overwrite the same registry entry with the current `threadId`, name, status, health, and replacement metadata.
7. Record `window-reconciliation-ledger.json` with reused, missing, inaccessible, invalid, and recreated windows.

When a window is reused, old context is historical only. The controller must send an authoritative input package for the current run:

- `approved_requirements.md`
- `approved_business-rules.md`
- `approved_architecture-design.md`
- `module-task-brief.md`
- `allowed-files.json`
- `forbidden-scope.json`

Set `old_window_context_policy=historical_only` and `must_not_reuse_unverified_prior_conclusions=true`. A reused window may keep role continuity, but current facts come only from the controller's frozen inputs and fresh evidence.

## Tool Operation Mapping

- `spawn_agent`: create an internal read-only Council member or bounded worker; start every ready Council member before the first wait.
- `wait_agent`: apply the Council completion barrier only after all ready members have been spawned.
- `send_input`: refine a running internal member only when new authoritative evidence is frozen and shared consistently.
- `close_agent`: close completed internal members after outputs are consumed.
- `list_threads`: list existing visible Codex windows.
- `read_thread`: read worker status and outputs.
- `create_thread`: create a new visible work window; requires explicit user authorization.
- `fork_thread`: derive a visible work window from current context; requires explicit user authorization.
- `set_thread_title`: name a window after creation or discovery.
- `send_message_to_thread`: dispatch a task brief or follow-up instruction; submit all calls for one ready set in a concurrent tool batch before waiting.
- `handoff_thread`: move window ownership or execution context; treat as high risk.

## Council Boundary

Council analysis defaults to internal subagents and does not create visible windows. Visible Council windows require the same explicit authorization, registry, reuse, naming, and reconciliation rules as all other visible windows. The main Agent first authors one complete baseline proposal. Council members are read-only auditors and receive that same proposal, frozen source-fact packet, and distinct audit responsibilities. Fresh-context audit packets preserve the compact `ARTIFACT + CONTRACT + source references` boundary. Members return findings, cross-review other audits, answer challenges, and review the final proposal revision; they do not return competing complete plans or vote on alternatives. Members cannot recursively spawn members. After user approval of the final audited proposal, implementation is routed through the existing single-writer or isolated worktree rules. Never let Council opinion override deterministic engineering gates.

## Role Model

Use only roles needed for the task:

- product_manager: requirements, business rules, acceptance criteria, open questions.
- business_reviewer: validates product/business docs against user/business evidence.
- architect: code-evidence-backed technical design, architecture design, API/data plans, final architecture acceptance.
- design_reviewer: independent review of product, technical, and architecture docs.
- frontend_developer, backend_developer, integration_developer: module implementation after confirmation.
- api_tester: independent API tests for parameters, responses, error codes, auth, idempotency, paging, sorting, and boundaries against `api-contract.md`; output `api-test-report.md`.
- module_flow_tester: independent module flow tests for happy paths, exception paths, state changes, DB writes, MQ/cache side effects, and business invariants; output `module-flow-test-report.md`.
- page_acceptance_tester: independent page acceptance for display, interactions, buttons, forms, errors, navigation, and responsive behavior against product docs and acceptance criteria; output `page-acceptance-report.md`.
- module_tester: legacy alias only; prefer the three test roles above.
- code_reviewer: independent diff review against requirements, design, and test evidence.

Developer windows must confirm scope, expected files, open questions, risks, and readiness before coding.

Test windows should not inherit developer-window conclusions. They read frozen requirements, business rules, architecture/design, API contracts, diffs, runtime URLs, and test credentials only.

## Document Correctness

Do not let one window self-certify product, business, architecture, code, or test correctness.

Required mechanisms:

- source evidence for each requirement, business rule, and design decision;
- traceability from requirement to business rule, design, module task, diff, test, and acceptance;
- independent review for product/business docs, architecture docs, code, and test evidence;
- freeze-and-change-control before development, with changes routed back to the controller window.

Document status must move through `draft -> reviewing -> approved` before high-risk development. Requirement changes after approval must be registered by the controller and reflected in the traceability matrix.

## Anti-Rework Controls

- Use small development slices; each slice needs its own minimum verification before broadening scope.
- Keep `api-contract.md`, `business-flow.md`, and `data-change-plan.md` contract-first. Private contract changes by a worker window are forbidden.
- Development self-test may only produce `developer_verified`; independent test windows produce `tester_verified`; independent review or architecture acceptance produces `independent_reviewed`.
- If the same issue fails twice, stop blind modification and require a diagnostic reset with symptom history, changed files, shared invariants, impact map, suspected root cause, and regression protection.

## Isolation

Prefer a separate worktree for parallel write windows. If using the same directory, there must be a single writer per file and explicit read-only windows for review/test.

Do not assign two windows to write the same file or shared contract unless the controller names a single owner and merge path.

## Required Artifacts

- `required-information-requests.json`
- `window-plan.json`
- `window-registry.json`
- `window-reconciliation-ledger.json`
- `dispatch-ledger.json`
- `window-status-ledger.json`
- `coordination-summary.md`
- `assistant-run-feedback.json`
- `closed-loop-outcome.json`

Artifacts default to run artifacts. Do not write them to a target repository unless the user explicitly requests formal retention.

## Gates

- `EXPLICIT_WINDOW_CREATION_REQUIRED`: creating or forking visible windows without explicit user authorization.
- `REQUIRED_INFORMATION_REQUESTS_MISSING`: controller skipped `required-information-requests.json` before planning/creation.
- `WINDOW_REGISTRY_MISSING`: missing window registry with threadId, name, role, responsibility, module scope, and status.
- `WINDOW_SCOPE_UNCLASSIFIED`: worker window task boundary is unclear.
- `WINDOW_NAME_MISSING`: worker window has no clear title.
- `BUSINESS_REVIEW_PENDING`: product or business docs are not independently confirmed.
- `DESIGN_REVIEW_REQUIRED`: architecture or technical design lacks independent review.
- `REQUIREMENT_FREEZE_REQUIRED`: requirement, business, or architecture docs are not approved before high-risk development.
- `API_CONTRACT_REQUIRED`: interface work lacks a shared API contract.
- `TRACEABILITY_MATRIX_REQUIRED`: requirements are not linked to business rules, design, diffs, tests, and acceptance.
- `DEVELOPER_CONFIRMATION_REQUIRED`: developer window starts coding before confirming scope, risks, and questions.
- `INDEPENDENT_TEST_REQUIRED`: interface, flow, or page changes lack independent tester evidence.
- `SELF_REVIEW_FORBIDDEN`: a developer window is the final reviewer of its own code.
- `MULTI_WINDOW_FILE_CONFLICT_UNCHECKED`: possible overlapping file/contract edits without isolation or owner.
- `MULTI_WINDOW_PARALLEL_DISPATCH_SKIPPED`: two or more independent ready windows were dispatched with an intervening wait/read instead of one concurrent batch.
- `WORKER_WINDOW_OUTPUT_NOT_CONSUMED`: controller did not read and consume worker output.
- `REPEATED_FIX_DIAGNOSTIC_RESET_REQUIRED`: same issue failed twice without diagnostic reset.
- `WINDOW_REGISTRY_REUSE_SKIPPED`: controller created windows without checking reusable registry entries first.
- `WINDOW_REPLACEMENT_NOT_RECORDED`: recreated window did not overwrite the logical registry entry with current threadId, status, and replacement metadata.
- `STALE_WINDOW_CONTEXT_USED_AS_FACT`: reused window treated old context as current-run fact without authoritative inputs.
