# Overlay Scope Hierarchy

Use this reference before adding, moving, or promoting Engineering Assistant overlay rules.

## Layers

Load overlays in this order:

1. `global`: durable Engineering Assistant rules that apply to all projects.
2. `project`: rules for one project, stored under `project-overlays/projects/<project_slug>/project-overlay.json`.
3. `module`: rules for one module/service/surface, stored under `project-overlays/projects/<project_slug>/modules/<module_slug>.json`.
4. `run_candidate`: temporary candidates in run artifacts; not durable until approved.

The narrower layer overrides only within its declared scope. It must not weaken global safety gates.

## Routing Rule

Before reading project or module overlays, produce:

- `overlay_layer`: selected layer list.
- `project_slug`: active project.
- `module_slug`: active module or `none`.
- `project_overlay_route`: exact overlay files to load.
- `excluded_overlays`: similar project/module overlays intentionally not loaded.

Do not wildcard-load every project overlay. Cross-project or cross-module overlays are hypotheses unless current-scope evidence confirms them.

## Write Rule

Store rules by their narrowest durable scope:

- Global overlay: project-neutral workflow, safety, artifact, feedback, review, and validation rules.
- Project overlay: one product or workspace.
- Module overlay: one bounded domain, integration module, UI surface, worker, external-system adapter, or shared platform service.
- Run artifact: unapproved samples, repeated-fix evidence, draft rules, and migration candidates.

If a rule names a project, product line, domain table, module, external system, endpoint family, page, or business-specific data source, it is not global by default.

## Promotion Rule

Promote a candidate only when it has:

- evidence source;
- owner;
- scope;
- trigger;
- non-goals;
- validation check;
- expiry or review condition;
- user approval when it changes durable behavior.

## Required Fields

Project and module overlay JSON must include:

- `overlay_layer`
- `project_slug`
- `module_slug` for module overlays
- `applies_to`
- `rules`
- `gates`
- `evidence_sources`
- `owner`
- `review_after`

## Gates

- `OVERLAY_LAYER_UNCLASSIFIED`: a rule is added without deciding global/project/module/run_candidate.
- `PROJECT_MODULE_OVERLAY_ROUTE_MISSING`: a task has project/module scope but no explicit overlay route.
- `PROJECT_SPECIFIC_RULE_IN_GLOBAL_OVERLAY`: project or module-specific content is added to global overlay without promotion evidence.
