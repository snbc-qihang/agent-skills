# Business Configuration Boundary

Use this reference before adding or changing business/runtime configuration during development. Examples include feature switches, source-selection flags, restriction configs, fallback flags, compatibility flags, Nacos/YAML properties, and config-table entries. The rule applies to any project, not only one product or module.

## Allowed config purposes

A config is usually acceptable when it is one of:

- `environment`: endpoint, tenant, namespace, datasource, credential alias, sandbox/prod separation.
- `safety`: block real value movement, external mutation, or production write risk.
- `rollback`: quickly return to a known-good path during incident response.
- `grey_release`: staged rollout by environment, tenant, store, user group, or percentage.
- `performance`: batch size, concurrency, timeout, retry bound, rate limit, circuit breaker.
- `idempotency_or_recovery`: replay limit, compensation enablement, lock timeout, checkpoint.
- `business_mode`: confirmed business variation, such as tenant/store/customer-specific rule differences.
- `observability`: log sampling, trace toggle, diagnostic-only metadata exposure.

## High-risk config purposes

A config is high risk when it:

- hides a bug instead of fixing root cause;
- compensates for unclear domain ownership;
- selects between duplicated business implementations without a retirement plan;
- exposes technical data source provenance to customer-facing behavior;
- makes synchronized data unusable instead of validating usability;
- changes high-risk value, lifecycle, allocation, entitlement, or external mutation semantics;
- creates many behavior combinations that are not tested;
- has no owner, default, monitoring, expiry, or rollback plan.

## Required config necessity record

Record:

- `config_key`
- `config_type`: one of the allowed purposes above, or `temporary_bypass`.
- `business_problem`
- `protected_failure`
- `default_value`
- `scope`: project, module, environment, tenant, store, user group, or scenario.
- `owner`
- `runtime_effect`: startup-only, refreshable, hot-reload, DB-driven, or unknown.
- `restart_required`
- `failure_impact_if_wrong`
- `monitoring_or_alert`
- `test_evidence`
- `expiry_or_review_condition`
- `remove_when`
- `alternative_design_considered`
- `why_config_beats_code_design`
- `decision`: `keep`, `narrow`, `temporary`, `reject`, or `replace_by_design`.

## Decision rules

- Use `keep` only when the config expresses real environment, safety, rollout, performance, recovery, or business variation.
- Use `narrow` when the config is valid but too broad; reduce scope to environment, tenant, store, scenario, or time window.
- Use `temporary` when the config is an incident bypass; it must have owner, expiry, and follow-up fix.
- Use `reject` when the config exists only because the implementation or test evidence is incomplete.
- Use `replace_by_design` when a clear domain model, state machine, strategy, adapter, workflow, or data validation would remove the need for the config.

## Completion boundary

Do not mark a feature complete merely because a config can make the visible path pass. Completion requires the behavior behind each supported config state to be tested, or unsupported combinations to be explicitly blocked.
