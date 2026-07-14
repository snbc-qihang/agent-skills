# Closed-loop Evolution Protocol

Use this reference when an Engineering Assistant run must feed future assistant behavior. The goal is not to add more rules. The goal is to turn real outcomes into evidence-backed improvement candidates.

## Pipeline

1. Collect: record the real run outcome in `assistant-run-feedback.json` and `closed-loop-outcome.json`.
2. Attribute: classify failures as requirement, design, implementation, runtime, verification, review, conflict, performance, or external-evidence gaps.
3. Distill: identify repeated success/failure patterns across runs.
4. Compress: merge duplicate gates, detect conflicts, isolate project-specific rules, and remove stale candidates before durable adoption.
5. Evaluate: score the run with explicit metrics or mark `pending_metrics`.
6. Adopt: promote only validated and human-approved candidates into durable overlay, formal skills, or project memory.
7. Replay: use historical failure samples as eval cases before claiming a new rule prevents the old issue.

## Intake before self-healing or upgrade

Before an Engineering Assistant audit, upgrade, self-healing run, or continuation of a related task, consume the latest relevant run artifacts when available:

- `assistant-run-feedback.json`: prior status, blockers, rule violations, capability consumption, artifact policy, and response contract.
- `closed-loop-outcome.json`: execution feedback, trajectory samples, compression candidates, reward-signal status, external-evidence boundaries, independent-review state, and `next_run_context`.
- `workflow-trace.json`: entry mode, executed/skipped nodes, pauses, recovery points, and next action.
- `artifact-index.json`: where evidence and outputs live; use it to avoid target-repo document pollution.
- `approval-requests.json`: unresolved human approvals and high-risk gates.

Default lookup root is `~/.codex/run-artifacts/engineering-assistant/<repo-slug>/<run_id>/`; user-provided artifact paths override or supplement the default. If records are unavailable, state that no artifact evidence was found and continue with source files/tests instead of inventing history.

## Agent-consumed feedback contract

Every ending, pause, block, or handoff must produce `assistant-run-feedback.json` and `assistant-run-feedback.summary.md` with `feedback_owner=codex_agent`, `agent_review_required=true`, `assistant_response_contract.must_read_feedback_before_final_response=true`, and `assistant_response_contract.must_not_ask_user_to_audit_artifacts=true`. The agent reads these before answering; the user is not asked to audit raw artifacts.

Missing lookup is `ASSISTANT_RUN_ARTIFACT_INTAKE_SKIPPED`; unread related feedback is `NEXT_RUN_FEEDBACK_NOT_CONSUMED`; missing or unconsumed final feedback is `ASSISTANT_FEEDBACK_NOT_GENERATED` or `ASSISTANT_FEEDBACK_NOT_CONSUMED_BY_AGENT`.

## Required outcome sections

`closed-loop-outcome.json` must include:

- `execution_feedback`: first-pass success, fix attempts, user corrections, regressions, tests, runtime refresh, and verification evidence.
- `trajectory_distillation`: success/failure/repeated-fix/performance/conflict/design samples and candidate reusable patterns.
- `compression_augmentation`: duplicate, stale, conflicting, overlapping, project-specific, and candidate-gate decisions.
- `reinforcement_signal`: task score when metrics exist, otherwise `pending_metrics`, with required metric sources listed.
- `external_evidence`: Sentry, MLflow/trace, CI/test platform, performance monitoring, and Git/PR review status.
- `independent_review`: developer verification and independent review state.
- `project_memory`: project profile, scenario flow, failed-flow, stale-flow, and reusable evidence candidates.
- `next_run_context`: what the next related run must consume before planning or editing.

## Local development boundary

If Sentry, MLflow, CI, performance monitoring, or PR-review connectors are not configured, record `pending_external_connector`. Do not block local development only because those connectors are unavailable. Do block formal release, production-readiness, or "online fixed" claims when required external evidence is missing.

## Promotion rules

- Candidate rules stay in run artifacts until approved.
- Project-specific evidence must not become global overlay rules unless it generalizes beyond one project.
- Durable overlay changes require validation and an upgrade summary.
- Formal project memory requires user approval unless the target project already defines that retention policy.
- A rule that cannot name trigger, scope, non-goals, counterexamples, and validation must remain a candidate.

## Reward signal guidance

Use real metrics when available:

- fix attempt count
- first-pass success
- regression introduced
- user correction count
- test and E2E pass rate
- runtime refresh verified
- independent review result
- production error rate
- API latency, CPU, memory, slow SQL

If metrics are missing, use `score_status=pending_metrics` and list the missing sources. Do not invent a score.
