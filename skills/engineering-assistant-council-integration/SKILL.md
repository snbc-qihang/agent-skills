---
name: engineering-assistant-council-integration
description: Use when Engineering Assistant has a complete complex proposal that needs adversarial audit before user review, or faces a repeated bug, fix-A-break-B regression, uncertain root cause, material reviewer disagreement, or an explicit Council request. Runs bounded parallel audits of one proposal, cross-review, author response, final sign-off, and a user-review gate; do not use for simple edits or competing-plan voting.
---

# Engineering Assistant Council Integration

Use Council as a proposal-audit capability under Engineering Assistant. Engineering Assistant remains the workflow, evidence, write-scope, quality-gate, and final-acceptance owner.

## Trigger

Run Council only when one trigger is evidenced:

- `complex_task`: L2/L3 or cross-module work has a complete baseline proposal with material design or execution risk.
- `repeated_bug`: the same defect survives or returns after a prior fix.
- `fix_a_break_b`: a later fix risks or has broken an accepted behavior.
- `uncertain_root_cause`: source facts support multiple causal hypotheses that the baseline proposal must address.
- `material_disagreement`: reviewers disagree on a blocker or high-risk proposal decision.
- `explicit_user_request`: the user asks for Council and the task is large enough to justify it.

Skip Council for a simple local edit, an obvious next action, missing source facts, or work that cannot produce one complete baseline proposal. Record `skipped_reason=council_not_efficient` when explicitly requested but not justified.

## Backends

Prefer `subagents` for internal read-only audit. Spawn every ready auditor before the first wait. Use visible Codex windows only when the user explicitly authorizes visible window creation, then follow `engineering-assistant-overlay/references/multi-window-coordination.md`. ATeam may be used when installed and already selected by Engineering Assistant.

Keep `external_model_api_enabled=false` by default. Do not send repository content to OpenRouter or another external model gateway without explicit data-boundary approval.

## Workflow

1. Freeze a scoped fact packet from current source, logs, tests, prior diffs, approved constraints, and user requirements. Compute its checksum with `validate_council_run.py --hash-context`; old conversation or window context is historical only.
2. The main Engineering Assistant authors one complete `baseline_proposal`. It must state the goal, constraints, assumptions, implementation steps, impacted components, tradeoffs, risk controls, verification, rollback, open questions, and source evidence before any auditor is dispatched.
3. Create `council-plan.json` with the main Agent as `proposal_owner`, 2-4 read-only audit members with distinct responsibilities, parallel-ready-set dispatch, cross-review, final sign-off, deterministic gates, required user review, and at most two rounds. Audit members use `audit_only_no_competing_proposal`; they may suggest bounded corrections but cannot submit another complete plan.
4. Dispatch all audit members before any wait/read. Give every member the same frozen facts and the same baseline proposal plus one distinct audit responsibility. The controller records dispatch timing and verifies that Council introduced no target-repository edits.
5. Store one audit per member in `council-member-outputs.json`. Every audit either records evidence-backed findings with severity, affected proposal section, falsification test, and bounded correction, or records why no blocker was found.
6. Create an identity-stripped audit projection. In one concurrent cross-review wave, every auditor reviews another audit and returns `support`, `challenge`, `refine`, or `no_issue`. Every `challenge` or `refine` receives exactly one response from the challenged auditor. Do not expose member, role, model, provider, thread, or session identity.
7. Relay every surviving finding to the proposal owner. The owner responds exactly once to every finding with evidence and either revises the proposal, rebuts it, requests an experiment or human decision, accepts a minor tradeoff, or records that the finding was withdrawn after cross-review. Run a second round only when changed evidence can resolve a blocker; never exceed two rounds.
8. The proposal owner produces one `final_proposal` revision. Every auditor reviews that exact revision. Any blocking final review keeps the internal audit blocked.
9. Produce `council-decision.json` with `synthesis_method=anonymous_proposal_audit_synthesis`, the final proposal digest, accepted/rejected findings, disagreements, unresolved cross-review and blocking-finding ids, deterministic evidence, internal audit status, user-review status, and development gate status.
10. Validate all three artifacts with `scripts/validate_council_run.py` and return the final proposal to Engineering Assistant.
11. When internal audit passes, stop at `status=ready_for_user_review` and `development_gate_status=awaiting_user_review`. Present the complete final proposal and audit conclusion to the user. Development starts only after the user approves that exact proposal, the decision records the approval evidence, status becomes `recommend`, and `development_gate_status=pass`.

## Decision Rules

- Council audits one proposal. Multiple independent reports are allowed; multiple competing complete proposals, ranking, and voting are not this mode and must be rejected.
- Audit opinions are advisory. Source evidence and deterministic build, test, lint, architecture, security, and migration gates remain authoritative.
- A chairman, majority, or unanimous vote cannot change a failed deterministic gate to pass.
- Initial audits are not deliberation. Every auditor must cross-review another audit; every challenge must be answered; the proposal owner must answer every surviving finding; every auditor must sign off on the final revision.
- Unanimity is not required. `no_issue` is valid, and manufactured objections are prohibited.
- Blocker and major findings close only through an evidenced revision, evidenced rebuttal, or auditor withdrawal after cross-review. `accepted_tradeoff` closes only minor findings.
- Material disagreement ends in a named verification experiment or human review, not forced consensus. Missing facts stop at `waiting_for_input`.
- Stop after two rounds. Council and proposal owner do not write business code.
- For repeated bugs, the baseline and final proposals must protect both the target behavior and previously accepted fixes.
- Keep the three core artifacts in run artifacts, not the target repository, unless formal retention is explicitly requested.

## Artifacts

- `council-plan.json`
- `council-member-outputs.json`
- `council-decision.json`

Read [references/council-contract.md](references/council-contract.md) when constructing or reviewing these artifacts. Defaults and limits are in `config.yaml`.

## Validation

```bash
python3 scripts/validate_council_run.py \
  council-plan.json \
  council-member-outputs.json \
  council-decision.json
```

Before synthesis, project identities out of the member artifact:

```bash
python3 scripts/project_anonymous_review.py council-member-outputs.json
```

Compute the frozen source checksum before writing the plan:

```bash
python3 scripts/validate_council_run.py --hash-context <source-file> [<source-file> ...]
```

Expected success output: `VALID_ENGINEERING_ASSISTANT_COUNCIL_RUN`.

## Gates

- Reuse `SCOPED_FACT_PACKET_MISSING` when current source evidence is not frozen.
- Reuse `DEBATE_MODE_UNBOUNDED` when rounds or stop conditions are unbounded.
- Use `COUNCIL_PARALLEL_DISPATCH_SKIPPED` when ready auditors are dispatched serially or a wait begins before all starts.
- Use `COUNCIL_DELIBERATION_MISSING` when there is no single complete baseline, competing plans are substituted for audits, cross-review or responses are missing, the owner does not revise, or the final proposal lacks all-auditor review.
- Use `COUNCIL_UNRESOLVED_BLOCKERS` when a proposal is presented to the user or implementation is recommended with unresolved cross-reviews, blocker/major findings, or blocking final reviews.
- Reuse `CAPABILITY_OUTPUT_NOT_CONSUMED` when audits, the final proposal, or the final decision do not affect the Engineering Assistant run.
- Use `COUNCIL_DETERMINISTIC_GATE_OVERRIDE_ATTEMPT` when voting, ranking, or synthesis attempts to override a failed deterministic gate.

Do not claim Council completed unless the validator passes and Engineering Assistant records how the final proposal and decision were consumed.
