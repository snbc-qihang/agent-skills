# Export interface no-filter adjustment — repository context lessons

Use this reference when mining context or drafting plans for export/query adjustments in an existing Java/Spring/MyBatis system.

## Lessons

1. Start from the controller entrypoint, then trace to async/task handlers and mapper XML.
   - Do not infer the data path from class names alone.
   - Use codegraph from the controller method to task creation, snapshot construction, handler prepare/queryPage, mapper interface, and XML SQL.

2. Treat user corrections as stronger evidence and re-ground the plan.
   - If the user says tables/DTOs/DDL already exist, locate them and rewrite the impact plan around reuse.
   - If the user says final DDL is in a database directory, read that DDL before proposing SQL shape.

3. For large-table export design, respect the existing data-shape strategy.
   - If order and order-item tables are large and designed as wide tables, do not propose joining them to fill export fields.
   - Align DTO/Excel columns with the wide table. If a field is not in the wide table and the user confirms it is not required, remove/ignore the DTO column instead of adding a join.

4. Normalize authorization to the smallest durable resource.
   - For point-resource and non-point-resource branches, reuse existing authorization services.
   - Let existing logic resolve tenant/city/user role inputs to the smallest permission resource, e.g. vending-machine IDs.
   - Export SQL should filter by the resolved resource set, not reimplement tenant/city/role logic.
   - Also identify how the existing system represents "all permissions". Do not treat an empty resource list as "all" unless the current code explicitly says so.
   - Plan for three separate states: no permission, partial permission, and all permission. Persist an explicit `allAuth`/equivalent flag in the export snapshot when needed so asynchronous handlers do not conflate these states.
   - "All permission" is still not a license to run an unbounded table scan. If the export table lacks a safe tenant/facilitator boundary, keep a vending-machine boundary via resolved IDs or a task permission-range table/temporary table.

5. Removing export filters means removing binding, not just ignoring fields.
   - If the export controller still binds a validated query DTO, validation such as `@NotBlank` still applies.
   - Delete the DTO parameter from export methods when the requirement says the interface no longer accepts filters.
   - Keep the query DTO for list/page APIs if those still accept filters.

## Plan checklist

- Controller export signatures no longer include the filter DTO.
- Snapshot construction contains only server-derived identity/permission data.
- Existing role/permission service is reused.
- Existing "all permission" semantics are traced from current code/data flags, not guessed.
- The plan distinguishes no permission, partial permission, and all permission in the export snapshot.
- SQL filters by server-derived permission resource set and required business state.
- `allAuth=true` does not remove the authorization boundary unless the table has a verified safe tenant/facilitator boundary.
- SQL does not use removed frontend filters.
- Large table joins are not introduced when the design calls for wide tables.
- DTO/Excel columns match the chosen table shape.
