# Runtime and Regression Guards

Read this reference when the request depends on current-window runtime evidence, a bug recurs after a prior fix, or fixing one issue may regress an earlier accepted fix.

## Current runtime evidence

When the user points at the current window, screenshots, DevTools, local ports, branches, commits, or says "现在/刚才/之前":

1. Record `window_context_summary` from the latest visible facts.
2. For branch or missing-commit questions, verify `git status`, `rev-parse`, `show`/`blame`/`log -S` before concluding.
3. For a local server or browser view, verify the listening PID, process cwd, and served source or bundle when available.
4. When multiple repositories can serve the same UI, verify the git top-level path, server PID/cwd, and one served-source clue.
5. If source and runtime contain the expected code but the browser disagrees, classify stale page, cache, dev server, data, or deployment state before another edit.

Use `WINDOW_CONTEXT_NOT_CONSUMED`, `BRANCH_RUNTIME_EVIDENCE_MISSING`, or `ACTIVE_RUNTIME_PROJECT_UNVERIFIED` only when the corresponding positive check is skipped or contradicted.

## Repeated-fix recurrence audit

Before editing after "还是/又/多次/反复", a failed prior fix, or fix-A-break-B:

1. Build `symptom_history`: latest symptom, prior fixes in the current window, and what each changed.
2. Name the `shared_invariant` that must hold across affected surfaces.
3. Build `surface_map` from code search or call-graph evidence for every caller, API, component, page, or mutation path.
4. Record `known_good_preservation` and its smallest protection check.
5. Select `root_cause_location`; prefer the shared owner and explain any surface-only patch.
6. Run a `regression_gate` for the failing case and at least one sibling or known-good path.

If prior code looks correct but runtime evidence disagrees, classify runtime/cache/data/deployment state before editing. Use `REPEATED_FIX_SURFACE_ONLY`, `REGRESSION_PRESERVATION_GATE_MISSING`, or `REPEATED_FIX_RUNTIME_STATE_UNCLASSIFIED` for the matching omission.

## Fix-chain survival

When fixing B after A was accepted in the same run, branch, or visible history:

1. Record `protected_fix_set` before the B edit.
2. If the diff touches A's owner path, state why the shared change preserves A.
3. After the B fix, run the smallest `regression_survival_gate` proving both A and B.

If a later fix reverts or breaks A without this evidence, mark `FIX_CHAIN_REGRESSION_UNCHECKED`.
