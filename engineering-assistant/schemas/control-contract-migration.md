# Control Contract Version And Migration Policy

## Current Version
- `schema_version`: `2.0.0`
- Core control contracts are strict by default. Extension data must be placed under `metadata` or `extensions`; business fields cannot keep open-ended `additionalProperties: true`.

## Migration Rule
- Old v2 control-plane artifacts with unknown nested business fields are not auto-blessed.
- A migration can copy known fields into the strict target schema and move unknown non-business data to `extensions`.
- If an unknown field changes implementation scope, quality commands, browser acceptance, production risk or approval state, migration must stop with `blocked` and create an open question.

## Frontend Acceptance Rule
- Missing browser/build-web-apps/Playwright screenshot evidence can still pass code-level checks.
- It cannot pass frontend product acceptance; the result must be `code_level_only` or `blocked`.
