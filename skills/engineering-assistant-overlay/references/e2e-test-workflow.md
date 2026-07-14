# Universal E2E Test Workflow

Use this reference only after an Engineering Assistant request triggers 全流程测试, E2E, distributed business flow testing, or a project + branch + scenario test request.

## Entry Contract

Minimum user input:

```yaml
project: string
branch: string
scenario: string
```

Before execution, confirm the real project path, current git branch, dirty worktree, involved repositories, scenario clarity, and user restrictions such as read-only mode, no real writes, no code edits, or no external calls.

## Skill Routing

Use existing skills instead of inventing a new runner:

- `engineering-assistant`: entrypoint, scope control, artifacts, confirmations, and gates.
- project skill such as `bc-lilishop-retail-dev`: project rules, branch, memory, and repo constraints.
- `designing-distributed-system-tests`: scenario modeling, claims, matrix, Oracle, and coverage argument.
- `executing-distributed-system-tests`: execution, evidence, environment capability, verdicts, and green-but-broken checks.
- `engineering-assistant:self-test`: narrow API or interface self-tests inside `LIGHT_FLOW` or as a precheck.
- `skill-evolution-planner`: only for later assistant capability proposals, not for business test execution.

## P0-P1: Project Profile

Read project rules and evidence before making claims:

- `AGENTS.md`
- `agent_memory/context.md`
- `agent_memory/progress.md`
- `agent_memory/bugs.md`
- `README`
- `docs`
- test directories
- entry controllers/pages/scripts for the scenario
- current branch and relevant history

Output:

- project type: product/workspace category, verified from code or clearly labeled as inferred
- core entities
- system boundaries
- key code entry points
- data sources: DB, Redis, ES, external systems, config center
- verified facts with source
- inferred facts clearly labeled

## P2: E2E Test Classifier

Every scenario gets exactly one classification:

```text
NO_E2E
LIGHT_FLOW
FULL_E2E
```

`NO_E2E`: copy, single UI style, single API field, single-table query, no state transition, no external side effect. Stop after light verification advice.

`LIGHT_FLOW`: single service state transition, login state, cache, one frontend/backend loop, or small business flow. Produce a light flow script or test plan.

`FULL_E2E`: crosses 2+ systems or 2+ roles, or touches high-risk state transition, money/value movement, inventory/resource allocation, external synchronization, async callback, idempotency, or external side effect. Continue to scenario contract and matrix.

If uncertain, output classifier evidence and required user confirmations. Skipping this is `E2E_TEST_CLASSIFIER_SKIPPED`.

## P3: Scenario Contract

For `FULL_E2E`, produce `scenario-contract.yaml` and wait for confirmation before execution:

```yaml
scenario_id:
scenario_name:
project:
branch:
business_goal:
actors:
systems:
core_entities:
entry_points:
state_machine:
business_invariants:
external_side_effects:
happy_path:
branches:
failure_cases:
required_accounts:
required_tokens:
required_test_data:
required_environment:
unknowns:
user_confirmation_required:
```

Make accounts, tokens, test data, unavailable environments, external systems, non-closed business rules, inferred facts, and permission for real write/payment/refund/verification explicit. Missing confirmation is `E2E_SCENARIO_CONTRACT_UNCONFIRMED`.

## P4: Matrix And Oracle

Generate matrix layers:

- Smoke happy path
- business branches
- exception and idempotency cases
- data consistency checks
- permission and boundary checks
- regression cases

Each case must include: case id, business guarantee, preconditions, steps, systems, input data, expected state-machine transition, Oracle, evidence, failure attribution, automation suitability, and human-confirmation needs.

## P5: Agent Reuse Policy

Default to one controller. Do not create new agents for every run.

Use one isolated test session per scenario. Reuse roles within a scenario. Enable multi-agent roles only when the scenario crosses 2+ repos, 2+ roles, external systems, high-risk business state, value/resource movement, parallel evidence collection, or independent Oracle review.

Roles:

- Coordinator: scenario contract, sequence, status, conclusion
- Project Reader: project/branch/code/doc evidence
- Test Agent: execution and raw evidence
- Oracle Agent: business guarantee verdict
- Fix Agent: only after `REAL_BUG`
- Retest Agent: failing-point retest, continuation, final E2E

Real writes are serial. Read-only analysis can be parallel.

## P6: Execution Evidence

Before execution, confirm environment, account, token, test data, write permission, external call permission, payment/refund/verification permission, and data risk.

Every step records request, response, DB state, page state, middle-platform state, log correlation id, external ledger, business object state, Oracle verdict, and screenshot/log evidence when applicable. API success alone is never enough.

## P7: Failure, Fix, Continuation, Final Retest

Classify every failure before edits:

- `ENV_FAILURE`
- `AUTH_FAILURE`
- `TEST_DATA_FAILURE`
- `SCRIPT_FAILURE`
- `BUSINESS_AMBIGUITY`
- `RUNTIME_STATE_FAILURE`
- `REAL_BUG`

Only `REAL_BUG` enters code repair.

Before repair, record failing case id, step, request, response, DB state, page/middle-platform state, log correlation id, expected vs actual result, violated invariant, classification, and `REAL_BUG` decision.

After repair:

1. Run compile/unit/interface checks needed for the touched scope.
2. Restart or refresh the affected runtime.
3. Prove the new runtime is active: process, port, interface, startup time, config, and commit/build evidence when available.
4. Retest the original failing point.
5. Continue from the blocking point through the remaining scenario steps.
6. Repeat failure classification and repair if another blocker appears.
7. Only after the current scenario first completes, run one final full E2E from the entry point using clean or explicitly reusable test data.

Do not immediately restart the whole E2E after every bug fix. Continue the current flow first.

Statuses:

```text
blocked
pending-user-confirmation
pending-runtime-verification
pending-flow-continuation
pending-final-full-e2e-retest
fixed-pending-runtime-verification
```

If runtime activation, blocking-point continuation, or final full E2E ordering is skipped, mark `E2E_RUNTIME_CONTINUATION_GATE_MISSING`.

## P8: New Feature Gate

For new features:

- `NO_E2E`: unit/API/page self-test is enough.
- `LIGHT_FLOW`: add a light flow script or plan.
- `FULL_E2E`: add scenario contract, matrix, executable flow script, or execution plan.

New flow work should extend existing assets instead of rebuilding the whole flow.

## P9: Project Flow Memory

Record reusable evidence-backed flow assets as candidates under run artifacts first.

Suggested structure:

```text
project-flow-memory/
  project-profile.yaml
  scenario-registry.yaml
  flow-assets/
    <scenario-a>.yaml
    <scenario-b>.yaml
    <scenario-c>.yaml
  regression-suite.yaml
  known-risks.yaml
  evidence-index.json
```

Each scenario asset records scenario id, business domain, systems, roles, entities, state machine, stable steps, evidence, regression cases, known risks, last verified time, evidence source, and stale policy.

Only evidence-backed assets can be promoted. Mark old assets `stale`. Business-rule changes require revalidation. Missing reusable-flow handling is `PROJECT_FLOW_MEMORY_NOT_RECORDED`.
