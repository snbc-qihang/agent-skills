# Plugin Capability Routing Standard

This standard describes how the local Engineering Assistant plugin advertises and routes capabilities.

## Source layers

- `active_plugin`: runtime skills, workflows, registries, schemas, scripts, and compiled skill IR under `/Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1`.
- `durable_overlay`: user-local guardrails and overlay-only capabilities under `/Users/fengtianyangyang/.codex/skills/engineering-assistant-overlay`.
- `window_context`: current conversation context; never sufficient by itself to claim an installed capability.

## Routing rules

1. Route ordinary staged engineering work through the active plugin workflow and skill registries.
2. Route local policy, multi-window coordination, feedback/closed-loop, artifact retention, and stricter gates through the durable overlay when the active plugin does not provide them.
3. High-risk capabilities must not be implicitly invoked unless their registry entry allows it and the user intent is explicit enough.
4. When a capability is provided only by the overlay, report `provided_by=overlay` and do not claim it is compiled into active plugin runtime skill IR.
5. If a capability is missing from both active plugin and overlay, mark `ACTIVE_ENGINEERING_ASSISTANT_CAPABILITY_MISSING`.

## Validation

- `engineering-assistant/registry/plugin-capabilities.json` lists capability source, status, and routing metadata.
- Overlay startup self-checks verify required capabilities are present in either active plugin or overlay.
- Overlay-only capabilities remain subject to overlay validation and user-local gates.
