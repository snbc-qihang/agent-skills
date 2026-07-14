---
name: engineering-assistant
description: Use when the user invokes @engineering-assistant, asks to use 研发助手, reports Engineering Assistant behavior, or a task needs staged engineering workflow, repository context mining, design, implementation control, self-test, quality governance, code review, release verification, or plugin routing.
---

# Engineering Assistant Wrapper

This skill is a discovery wrapper for the cached Engineering Assistant plugin. It does not duplicate the plugin rules. When this skill triggers, load the cached plugin files below and treat them as the source of truth.

## Source Paths

- Plugin root: `/Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1`
- Workflow entrypoint: `/Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1/skills/workflow-orchestrator/SKILL.md`
- Stage skills directory: `/Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1/skills`
- Engineering Assistant assets, standards, schemas, registry, scripts: `/Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1/engineering-assistant`
- Local durable overlay: `/Users/fengtianyangyang/.codex/skills/engineering-assistant-overlay/SKILL.md`
- Local Council integration: `/Users/fengtianyangyang/.codex/skills/engineering-assistant-council-integration/SKILL.md`

## Local Sync Status

- 2026-06-25: The cached plugin directory above was synced from `git@github.com:snbc-qihang/agent-skills.git` commit `0b2687b602fcdb7f6439e6dafd1bea10183f8971` by publishing the upstream package into Codex plugin layout and copying it into the local cache.
- 2026-06-25 P7: The cached plugin directory above was refreshed from the local source workspace `/tmp/20260625-194849-engineering-assistant-104-merge-source` on branch `ea-governance-v1-overlay-split`, including governance v1 overlay split, project profile isolation, governance eval groups, and self-evolution proposal pipeline gates.
- The directory name remains `1.0.0.1` for compatibility with the current Codex skill registry. On 2026-07-11 the local manifests and all stage/runtime contracts were independently upgraded to `1.1.0.0`; this local version is not an upstream release or commit.
- The previous cache was backed up at `/Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1.backup.20260625-194941`.
- The pre-P7 cache was backed up at `/Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1.backup.20260625-p7-222304`.
- The local durable overlay still loads after the cached plugin and remains the source of stricter user-local gates that are not present in the current active plugin manifest.

## Required Loading Order

1. Read the workflow entrypoint `workflow-orchestrator/SKILL.md` completely.
2. Read the local durable overlay `engineering-assistant-overlay/SKILL.md` completely. Overlay rules are user-local patches and take precedence over the cached marketplace plugin when they add stricter gates, feedback contracts, artifact persistence rules, or self-healing requirements.
3. If workflow-orchestrator routes to another stage skill, read that stage skill's `SKILL.md` completely before acting.
4. If a complex task, repeated bug, fix-A-break-B regression, uncertain root cause, material reviewer disagreement, or explicit Council request triggers Council mode, read the local Council integration skill before dispatching members.
5. When workflow-orchestrator requires standards or registries, read only the referenced files needed for the task, typically:
   - `engineering-assistant/standards/plugin-capability-routing-standard.md`
   - `engineering-assistant/registry/plugin-capabilities.json`
   - `engineering-assistant/registry/workflows.yaml`
   - `engineering-assistant/registry/skills.yaml`
6. Keep project-level `AGENTS.md`, user-level rules, and any project-specific skill as higher-priority local context for repository details.

## Active Capability Self-Check

Before claiming that Engineering Assistant latest capabilities are available, run or faithfully apply the overlay self-check:

- `/Users/fengtianyangyang/.codex/skills/engineering-assistant-overlay/scripts/validate_active_engineering_assistant_capabilities.py`

If the cached plugin does not contain a capability but the overlay provides it, report `provided_by=overlay`. If neither cached plugin nor overlay provides it, mark `ACTIVE_ENGINEERING_ASSISTANT_CAPABILITY_MISSING` and do not claim L4 readiness.

## Fallback

If the cached plugin path is missing, unreadable, or not suitable for the task, state the skipped reason clearly and continue with the best available project-specific skills and repository rules. Do not claim Engineering Assistant workflow gates have passed unless the required plugin stage files and validation steps were actually used.

If the overlay path is missing or unreadable, state `engineering_assistant_overlay_unavailable`; do not claim assistant-run-feedback, capability-health, capability-output-consumption, process-documentation-pollution, or active-capability self-check support unless those capabilities are present in the cached plugin itself.
