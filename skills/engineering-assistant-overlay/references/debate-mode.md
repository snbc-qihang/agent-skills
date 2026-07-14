# Debate Mode

Use debate mode only for high-risk engineering decisions, repeated failures, uncertain root cause, or explicit user request. Classify the run as `lightweight_debate` or `council` before dispatch.

## Trigger

- user explicitly asks for debate mode;
- same issue failed or returned after a prior fix;
- change affects money, orders, inventory, auth, data migration, external systems, performance, or cross-module contracts;
- root cause or implementation point is uncertain.

## Roles

- `requirement_reviewer`: checks goal, scope, and acceptance.
- `architecture_reviewer`: checks root-cause location, boundaries, and reuse.
- `risk_security_reviewer`: checks permission, data loss, safety, and rollback.
- `test_reviewer`: checks smallest evidence and regression coverage.
- `skeptic_reviewer`: checks hidden assumptions and counterexamples.
- `correction_reviewer`: keeps the debate on the confirmed user goal and stops scope drift.

## Process

1. Read evidence first: request, code path, prior attempts, runtime/data facts, and constraints.
2. Choose `lightweight_debate` when one plan needs bounded objections. Choose `council` when 2-4 independent hypotheses, designs, or reviewer positions should be produced in parallel.
3. In lightweight debate, the main agent proposes the smallest viable plan and reviewers raise only blocking objections.
4. In Council mode, load `/Users/fengtianyangyang/.codex/skills/engineering-assistant-council-integration/SKILL.md`, have the main Agent complete one baseline proposal, freeze it with one scoped fact packet, and dispatch every ready read-only auditor before the first wait. Auditors review the same proposal and cannot submit competing complete plans.
5. Auditors cross-review findings and answer challenges. The main Agent responds to every finding, revises the proposal, and returns that exact revision for all-auditor review before presenting it to the user.
6. Correction reviewer rejects off-goal objections and asks whether new scope needs user confirmation.

## Termination

Stop debate when any condition is true:

- no blocking objection remains;
- remaining objections are accepted tradeoffs with owner and verification;
- two debate rounds have completed;
- a required fact is missing and cannot be inferred safely;
- the debate introduces new scope that needs user confirmation;
- the task is low risk after evidence review.

If stopped because of missing facts or new scope, status is `waiting_for_input`, not `approved`.

## Gates

- `DEBATE_MODE_UNBOUNDED`: debate has no max rounds or stop condition.
- `DEBATE_CORRECTION_REVIEWER_MISSING`: no correction reviewer guards user goal and scope drift.
- `DEBATE_BLOCKING_OBJECTION_UNCLASSIFIED`: objections are not classified as blocking, accepted tradeoff, or out-of-scope.
- `COUNCIL_PARALLEL_DISPATCH_SKIPPED`: Council members were ready but dispatched serially or a wait began before all starts.
- `COUNCIL_DETERMINISTIC_GATE_OVERRIDE_ATTEMPT`: ranking or synthesis attempted to override a failed deterministic gate.
