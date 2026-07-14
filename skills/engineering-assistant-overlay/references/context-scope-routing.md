# Context Scope Routing

Use this reference before a task loads prior failures, project memory, E2E flows, module rules, or repeated-fix samples.

## Scope layers

Classify every run into:

- `global`: Engineering Assistant rules that apply to all projects.
- `project`: one product or workspace.
- `repository`: one code repo, such as backend, frontend, mobile app, worker, or integration service.
- `module_or_service`: one bounded business domain, integration module, UI surface, worker, or shared platform service.
- `surface`: API, page, job, consumer, listener, scheduler, database table, external callback, or runtime entry.
- `runtime`: local dev server, test server, prod-like server, active port, PID, profile, datasource.
- `data_source`: local DB, external system, cache, search index, imported projection, materialized business table.

## Load rule

Load only:

- global Engineering Assistant rules needed for this task kind;
- the project skill for the active project;
- module/service memory directly related to the active scope;
- previous feedback and closed-loop outcomes for the same project/module/surface;
- cross-module samples only as labeled hypotheses.

Do not load every known issue from the same project just because the symptom looks similar.

## Cross-module evidence rule

A similar error in another module may suggest a search direction, but it cannot become the root cause until current-scope evidence confirms:

- same business invariant;
- same caller or shared implementation point;
- same runtime source;
- same data source or state machine;
- same failing test or reproducible user path.

## Fact packet

For handoff, retry, or repeated-fix reset, write a scoped fact packet:

- `context_scope`: project/repository/module_or_service/surface/runtime/data_source;
- active scope;
- exact symptom;
- current evidence;
- verified non-causes;
- current hypotheses;
- out-of-scope history;
- next narrow verification step.

## Completion rule

Do not claim a module fix, project-wide fix, or global rule change when evidence only covers one narrower scope.
