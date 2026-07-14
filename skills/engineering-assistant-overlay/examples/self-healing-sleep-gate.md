# Self-Healing Sleep Gate Example

## Input

The user asks Engineering Assistant to read the current Codex window context and
use Darwin plus SkillOpt-Sleep to repair or upgrade Engineering Assistant.

## Required Handling

1. Load the Engineering Assistant wrapper, cached workflow entrypoint, and this overlay.
2. Summarize the latest window context before diagnosing.
3. Run the active capability self-check and overlay tests.
4. Run `skillopt-sleep status` and an initial `dry-run --backend mock` for the target skill or project path.
5. If that attempt returns `n_sessions=0` or `n_tasks=0` while the user asked for window or past-run context, rerun read-only evidence gathering with `--source codex --scope all`.
6. Record baseline score, candidate score, gate action, acceptance, task count, session count, edits, staging directory, and whether `report.md` was read.
7. Do not adopt Sleep proposals unless the held-out score improves and the user explicitly approves adoption.

## Gate Scope Example

For a bc-service change, a touched-file Java comment guard can pass while a
full-project business-comment guard fails on pre-existing files. The final
feedback must label:

- `touched_scope_gate`: pass
- `full_scope_gate`: fail or warn
- `legacy_debt`: the pre-existing files or guard output

If these buckets are collapsed into a clean pass, mark
`SCOPE_GUARD_LEGACY_DEBT_UNLABELED`.
