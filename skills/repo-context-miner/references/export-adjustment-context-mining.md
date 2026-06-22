# Export/API Adjustment Context Mining Pitfalls

Use this reference when a user asks to re-plan an API/export adjustment after other contributors changed related code.

## Lessons

1. Start from the live entrypoint and trace outward.
   - For endpoint changes, begin at the controller method and follow create/build/query flows with codegraph.
   - Do not assume mapper, DTO, entity, or DDL are missing just because the first search did not find the expected class name.

2. Treat final DDL/design artifacts as implementation evidence when the user points to them.
   - Search/read the project database/design directory before proposing mapper SQL.
   - Use final DDL to verify table columns, indexes, partition strategy, and status-code semantics.

3. For large-table/wide-table designs, do not propose joins as a default fix.
   - If both tables are large and the design direction is wide tables, keep each export/query on its own table.
   - If a DTO field is not present in the wide table, surface the mismatch: either adjust the DTO/output columns or add the field to the wide table/write path. Do not hide the mismatch with a large-table join.

4. Separate endpoint input removal from query-snapshot removal.
   - Removing request DTO binding at the controller is required when validation annotations would still reject no-parameter calls.
   - Query snapshot fields may be kept for historical JSON compatibility while controller no longer populates them and SQL no longer references them.

5. Server-derived flags must be traced to their authoritative source.
   - If a request flag is removed, identify the server-side mapper/service that derives it, and plan a wrapper method or service rather than scattering magic values in the controller.

## Output expectation

The plan should name exact paths, facts from controller/codegraph, DDL-backed table fields/indexes, and any remaining real mismatches. Avoid presenting stale open questions after the user has resolved them.