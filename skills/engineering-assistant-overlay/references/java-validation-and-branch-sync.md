# Java Validation and Branch Sync

Read this reference for Java/Maven compiler repair, validation-output interpretation, or cherry-picking Java changes across destination branches.

## Validation output triage

After Maven, pnpm, build, test, smoke, or service-start commands, classify:

- `blocking_errors`: caused the final command to fail.
- `non_blocking_warnings`: warnings that did not fail it.
- `legacy_noise`: pre-existing or out-of-scope output.
- `final_status`: the last command exit result after reruns.

Do not report a successful warning-heavy command as broadly broken. Treat an earlier failure followed by a passing targeted rerun as an intermediate finding. Otherwise mark `VALIDATION_OUTPUT_NOT_CLASSIFIED`.

## Java compile repair

Before source edits:

1. Group errors by root cause and file: duplicate definitions, missing symbols/imports, signature or constructor drift, record-component drift, test-only API drift, merge residue, generated/IDE cache noise, or unrelated legacy failures.
2. Identify target module, upstream shared modules, tests, and runtime-only wiring.
3. Patch the first blocking cluster with the smallest source-level change.
4. Add SDK VO fields, aliases, or compatibility overloads only with a requiring call site or failing test.
5. Rerun the narrowest Maven command, then broaden only to expose downstream contract breakage.
6. Correlate IntelliJ problem counts with Maven or exact problem-list files before declaring source broken.

Report `compile_error_clusters`, `touched_scope_gate`, optional `full_scope_gate`, `legacy_debt`, and `final_status`. Missing cluster/scope separation is `JAVA_COMPILE_FIX_SCOPE_UNCLASSIFIED`.

## Java branch synchronization

Treat every destination branch as a fresh validation target.

1. Synchronize with `git cherry-pick`; do not merge or rebase branch work into a destination.
2. Record `branch_sync_map`, commit list, destination, and exclusions such as Nacos changes.
3. Before picking, record `destination_before_sha`, changed files, and destination-only routes, APIs, methods, UI entries, or config keys that must survive.
4. Resolve conflicts by hunk; whole-file ours/theirs is allowed only for proven generated or disposable files.
5. Inspect `git diff --name-status <destination_before_sha>..HEAD`, deletions, large rewrites, and known route/API/method survival with targeted `rg`.
6. Scan changed constructors, final dependencies, Feign clients, DTO fields, service signatures, `@InjectMocks`, manual mocks, and builders for signature drift.
7. Run touched-module `test-compile` or targeted tests when dependency injection, constructors, tests, or test-visible APIs changed; compile-only is insufficient.
8. Repeat the touched-scope gate on each checked-out destination before push.
9. When runtime config is excluded, inspect the destination diff with a targeted config scan such as `git diff -G'(nacos|server-addr|namespace|101\.200|127\.0\.0\.1|localhost)' origin/<branch>..HEAD`.
10. Stop before push if destination behavior disappears, validation fails, signature scanning was skipped, or exclusions cannot be proven.

Report `branch_sync_map`, `feature_preservation_gate`, `signature_drift_scan`, `branch_touched_scope_gate`, conditional `nacos_exclusion_gate`, and `final_status`. Missing destination validation is `JAVA_BRANCH_SYNC_VALIDATION_MISSING`; unprotected destination functionality is `JAVA_BRANCH_SYNC_FEATURE_LOSS_UNCHECKED`.
