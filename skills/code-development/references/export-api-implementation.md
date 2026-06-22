# Export/API implementation lessons

Use this when implementing export or API changes from an approved plan.

- If the user states a feature is new, do not keep legacy request fields, DTO fields, JSON snapshot fields, or SQL branches only for compatibility. Delete obsolete shapes directly and verify no handler/SQL still references them.
- When an export API is changed to accept no filters, remove the controller method parameter itself; do not merely ignore it. Framework binding and validation can still make old required fields mandatory.
- Treat server-side authorization as the source of truth. For permissioned exports, resolve permissions before creating the task and snapshot the resolved authorization boundary.
- If an export removes filters but still needs a permission-mode flag already used by the list API (for example `pointResourceVendorRole`), keep that flag as the only business parameter rather than inferring it with a different backend rule. Do not reintroduce order/phone/tenant/city/time filters under the same DTO.
- Prefer the smallest durable permission resource as the SQL boundary. In vending-machine/order domains, a resolved `vemIds` set is safer than re-expanding tenant/city logic in export SQL.
- Distinguish no-permission, partial-permission, and all-permission cases explicitly. Never implement "all" by dropping every permission predicate unless the table has a proven safe tenant/facilitator boundary.
- For wide-table exports, keep each export on its target read model table. Do not join the order and item wide tables just to fill display columns; remove/export-only DTO columns instead unless the wide table contract adds those fields.
- Keep generic export infrastructure and business export extensions separated. `asyncExport.service` should contain reusable task/executor/registry/file/MQ infrastructure; business-specific facades, permission snapshot builders, handlers, and query snapshots belong under `asyncExport.handler.<business>` as the extension entry point.
- When changing only export behavior, do not refactor or move validation for neighboring non-export APIs in the same controller/service. Restore untouched endpoints if a review points out scope creep.
- Verification checklist: compile/tests when possible; if build is blocked by dependency setup, still run targeted static checks such as XML parsing, stale-symbol search, and `git diff --check`, then report the build blocker separately.