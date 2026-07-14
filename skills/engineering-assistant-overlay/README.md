# Engineering Assistant Overlay

This directory is the durable user-local patch layer for Engineering Assistant.

The cached marketplace plugin can be refreshed or restored by Codex. This overlay
keeps local L4-entry rules stable across windows and plugin cache changes.

## Load order

1. Load `/Users/fengtianyangyang/.codex/skills/engineering-assistant/SKILL.md`.
2. Load the cached marketplace Engineering Assistant plugin.
3. Load this overlay `SKILL.md`.
4. Apply overlay gates when they are stricter than cached plugin behavior.

## Required startup check

Run:

```bash
python3 /Users/fengtianyangyang/.codex/skills/engineering-assistant-overlay/scripts/validate_active_engineering_assistant_capabilities.py
```

Passing output means required L4-entry support is available either from the
active plugin or from this overlay.

## Artifact policy

Default run artifact root:

`~/.codex/run-artifacts/engineering-assistant/<repo-slug>/<run_id>/`

Do not write process artifacts into target repositories by default.

Process artifacts include `run_state.json`, `workflow-trace.json`,
`capability-invocation-ledger.json`, `assistant-run-feedback.json`, temporary
plans, development notes, audit drafts, post-run reviews, and capability
matrices.

## Completion contract

Before final response, Codex must inspect `assistant-run-feedback.json` and
report its conclusion. The user is not expected to audit raw artifacts.

## Current status

Current maturity is not L4.0. Project-specific real-run samples now live under
`project-overlays/projects/<project_slug>/references/`; failed or partial
samples do not prove L4 readiness when they wrote process artifacts into the
target repository or lacked assistant feedback, capability health, and
capability output consumption evidence.

## Capability assimilation

Engineering Assistant is the sole entrypoint and gate owner for external
capabilities. External packs are audited capability by capability; only verified
deltas are adapted into native owners. The current independently versioned pack
is `ea-agent-skills-delta` `1.5.0`. Its source routers, commands, and personas are not active.

Validate an assimilation release with:

```bash
python3 scripts/evaluate_absorbed_capabilities.py tests/capability-assimilation/historical-regressions.json --registry registry/absorbed-capabilities.json --out /tmp/acceptance-results.json
python3 /Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1/engineering-assistant/scripts/validate_absorbed_agent_skills_behavior.py --out /tmp/behavior-evidence.json
python3 scripts/validate_capability_assimilation.py registry/absorbed-capabilities.json tests/capability-assimilation/capability-overlap-matrix.json /tmp/acceptance-results.json --routing-registry /Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1/engineering-assistant/registry/skill-routing-signals.json --behavior-evidence /tmp/behavior-evidence.json
```

Real-entrypoint evaluation lives at
`/Users/fengtianyangyang/.codex/eval/engineering-assistant`. The accepted MLflow
run for `1.1.0` is `5ef0b48f072848a393cf25f678c66189`; `1.2.0` behavior evidence remains protected,
and `1.3.0` through `1.5.0` acceptance is stored under the standard local run-artifact root.

## Local update log

- 2026-07-14: Upgraded `ea-agent-skills-delta` to `1.5.0`. Council now audits
  one complete main-Agent proposal instead of generating competing candidates.
  Parallel auditors cross-review findings, answer challenges, review the final
  revision, and stop for user audit before development. The three-artifact and
  two-round limits remain unchanged.
- 2026-07-12: Upgraded `ea-agent-skills-delta` to `1.4.0`. Complex plans now
  require bounded multi-Agent deliberation: parallel independent candidates,
  anonymous peer-review and response waves, and zero unresolved blocker/major
  reviews before implementation. The workflow keeps at most two rounds, does
  not require forced unanimity, and adds no fourth Council artifact.
- 2026-07-11: Upgraded `ea-agent-skills-delta` to `1.3.0`. Added an
  Engineering Assistant-owned quality floor, independent specification and
  quality verdicts, an evidence-based abstraction/YAGNI boundary, and a
  changed-scope smell baseline. The finite acceptance passed 20/20 cases with
  zero existing-gate regressions; no external router or business repository was
  installed or modified.
- 2026-07-11: Upgraded the local Engineering Assistant runtime to `1.1.0.0`
  while retaining the compatibility cache directory. Upgraded
  `ea-agent-skills-delta` to `1.2.0`: `requirement-intake` absorbed bounded
  clarification and feasibility argumentation; the controller and
  implementation owner absorbed selected-DAG, contract-first, true parallel
  ready-set scheduling, fresh review packets, and completion barriers.
- 2026-07-11: Slimmed the default overlay entrypoint from 621 lines / 44,739
  bytes to 401 lines / 28,071 bytes. Runtime/regression, Java validation,
  self-improvement, and run-evidence details now load through direct references;
  the soft/hard entrypoint budgets are 500/650 lines. No stage skill, absorbed
  capability, Council rule, multi-window rule, or hard gate was removed.
- 2026-07-11: Upgraded `ea-agent-skills-delta` to `1.1.0` after a real
  MLflow-traced Codex evaluation passed 10/10 cases with exact routing, gate,
  decision, and controller-ownership scores of 1.0. Added feedback-pair and
  historical-corpus audit tooling plus structured source resolution.
- 2026-07-11: Added a generic external capability assimilation gate and the
  independently versioned `ea-agent-skills-delta` pack. Six native delta
  capabilities are protected by G0/G1/G2 routing and ten finite historical
  regression cases.
- 2026-06-27: Added universal E2E test workflow overlay support. Engineering
  Assistant now routes project + branch + scenario requests through
  classification, scenario contract, matrix, runtime restart/continuation, final
  full-flow retest, and Project Flow Memory candidate handling.
- 2026-06-24: Added `JAVA_COMPILE_FIX_SCOPE_UNCLASSIFIED` and Java compile-fix
  discipline. Java/Maven/IDE compiler-error repairs must now cluster errors by
  root cause and report touched/full scope gates before broad cross-module
  edits.
