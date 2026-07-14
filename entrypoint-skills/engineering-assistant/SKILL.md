---
name: engineering-assistant
description: Use when a request involves development, debugging, review, architecture, testing, release, repository analysis, Engineering Assistant behavior, or any capability owned by the local Engineering Assistant plugin.
---

# Engineering Assistant Entrypoint

This is the only Skill exposed by the cached plugin. It is a controller entry, not a stage implementation.

## Do

1. Load `/Users/fengtianyangyang/.codex/skills/engineering-assistant/SKILL.md` and follow its required loading order.
2. Route natural-language intent through `engineering-assistant/scripts/route_skill.py`.
3. Let `workflow-orchestrator` compose only the selected internal stage Skills and their hard prerequisites.
4. Require a controller route record before any internal stage Skill executes.
5. Keep Engineering Assistant as the sole gate owner. Do not activate an upstream router, command set, or persona controller.

## Checks

- Plugin manifest exposes only this entrypoint directory.
- Internal stage contracts require a controller route record, except the controller itself.
- Routing, workflow, contract, and behavior validators pass.

## Gate

Redirect direct stage invocation to this entrypoint. A missing controller route record is not a valid stage run.
