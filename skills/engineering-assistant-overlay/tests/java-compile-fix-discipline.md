# Java Compile-Fix Discipline Prompt

Use this prompt to regression-test the overlay rule for broad Java compile-error repairs.

## Prompt

The user pastes Maven or IDE errors showing duplicate record components, missing helper classes, missing constants, constructor signature mismatch, and several downstream missing variables in one Java converter class. They ask Engineering Assistant to "处理这个问题".

## Expected Behavior

- Build `compile_error_clusters` before editing.
- Identify whether errors come from an incomplete merge, duplicate methods, missing helpers, signature drift, or unrelated test-only compatibility.
- Propose the smallest first patch scoped to the failing class or module.
- Avoid broad SDK VO or cross-service compatibility edits unless compiler output proves a shared contract break.
- Run a narrow Maven compile/test command for the touched module, then report `blocking_errors`, `non_blocking_warnings`, `legacy_noise`, `touched_scope_gate`, `full_scope_gate`, and `final_status`.
- If IntelliJ still shows an error count, require exact IDE problem-list or Maven correlation before declaring the code still broken.

## Regression Marker

If the response skips error clustering and immediately edits many unrelated modules, mark `JAVA_COMPILE_FIX_SCOPE_UNCLASSIFIED`.
