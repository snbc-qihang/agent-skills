# Run Evidence Governance

Read this reference when a run writes process artifacts, calls tool-backed capabilities, claims strict route/L4 status, or must separate touched-scope results from legacy debt.

## Persistence boundary

Default root: `~/.codex/run-artifacts/engineering-assistant/<repo-slug>/<run_id>/`.

Process artifacts stay outside target repositories unless the user explicitly approves formal retention. This includes run state, workflow traces, stage results, capability ledgers/summaries, feedback/outcome files, route/persistence decisions, plans, temporary audits, post-run reviews, capability matrices, and Darwin analysis.

Before writing, moving, or deleting target-repository Markdown, read `references/target-repo-doc-governance.md` and classify purpose, owner, status, source evidence, and retention action. Target `docs/` is reserved for approved project-owned API, design, deployment, migration, operations, acceptance, or normative documents.

Use the narrow marker that matches the failure: `TARGET_REPO_ARTIFACT_POLLUTION`, `TARGET_REPO_DOC_PURPOSE_UNCLASSIFIED`, `TARGET_REPO_DOC_CLEANUP_WITHOUT_APPROVAL`, `PROCESS_MD_WRITTEN_TO_PROJECT_DOCS`, or `PROCESS_DOCUMENTATION_POLLUTION`.

## Route strictness

`assistant-run-feedback.json` cannot pass with a missing, unknown, or non-standard route.

- `task_kind`: `context`, `audit`, `change`, `release`, `self_healing`
- `evidence_level`: `inline`, `lite`, `standard`, `formal`
- `persistence_mode`: `inline`, `ephemeral`, `target_repo`, `blocked`

Historical ad-hoc values may remain partial evidence but cannot count as strict L4 until normalized. Use `RUNTIME_ROUTE_NOT_SELECTED` or `NON_STANDARD_RUNTIME_ROUTE` for current invalid routes.

## Capability health and consumption

Before a tool-backed capability affects a decision, record health using `schemas/capability_health.schema.json`. This applies to CodeGraph, Understand-Anything, browser/chrome, GitHub/CI/Sentry, and external security scanners. Missing required health is `CAPABILITY_HEALTH_NOT_CHECKED`.

When a capability is called, record output artifacts or an explicit no-artifact rationale in `capability-invocation-ledger.json`, then record downstream use with `schemas/capability_output_consumption.schema.json`. Unconsumed output is `CAPABILITY_OUTPUT_NOT_CONSUMED`; unrecorded output is `CAPABILITY_OUTPUT_NOT_RECORDED`.

For `task_kind=change`, strict evidence requires a real target-code diff and verification. Missing them is `NO_EFFECTIVE_CODE_CHANGE` or `CHANGE_VERIFICATION_EVIDENCE_MISSING`.

## Gate-scope evidence

Separate:

- `touched_scope_gate`: checks for changed files or behavior.
- `full_scope_gate`: repository-wide checks.
- `legacy_debt`: pre-existing failures outside the touched scope, with command/file evidence.

Do not turn touched-scope success into a full-project pass, or unrelated full-scope debt into failure of a bounded change unless project policy requires it. Use warn/pending evidence when ambiguous. Unlabeled legacy debt is `SCOPE_GUARD_LEGACY_DEBT_UNLABELED`.

## L4 entry

L4 entry requires all of:

1. Active capability self-check passes.
2. Real context E2E passes without target-repository pollution.
3. Real audit E2E passes or blocks with valid feedback.
4. A real change E2E proves target-code diff and verification.
5. Feedback is generated and consumed by Codex.
6. Called tool-backed capabilities have health evidence.
7. Called outputs are consumed downstream.
8. Process documents default to ephemeral artifacts.

Historical samples that polluted a target repository or lack feedback, health, or output-consumption evidence do not prove L4 readiness.
