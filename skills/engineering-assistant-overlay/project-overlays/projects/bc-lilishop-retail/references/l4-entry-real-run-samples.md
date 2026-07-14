# L4-entry real-run samples

These samples come from real Engineering Assistant runs on 2026-06-21 against
`/Users/fengtianyangyang/workspace/Playground/micro/bc-service`.

They are useful for L4 validation, but they are not passing L4 evidence.

## Sample 1: full protocol audit

Artifact root:

`/Users/fengtianyangyang/workspace/Playground/micro/bc-service/artifacts/workflow-orchestrator`

Observed status:

`blocked`

Useful evidence:

- `run_state.json`
- `capability-invocation-ledger.json`
- `capability-usage-summary.md`
- `plugin-capability-plan.json`
- `workflow-trace.json`
- `stage-run-result.json`
- `darwin-skill-evidence.json`

Capabilities observed:

- `bc-lilishop-retail-dev`: call
- `codegraph`: call
- `understand-anything`: skip
- `ponytail`: call
- `codex-security`: blocked
- `ateam`: skip
- `darwin-skill`: call

Why it fails L4:

- process artifacts were written into the target repository
- no `assistant-run-feedback.json`
- no `capability-health.json`
- no `capability-output-consumption.json`
- gate list included `GATE_NOT_ENFORCED`

## Sample 2: project-read context run

Artifact root:

`/Users/fengtianyangyang/workspace/Playground/micro/bc-service/artifacts/workflow-orchestrator/project-read-20260621T012031+0800`

Observed status:

`succeeded`

Useful evidence:

- real repo context loading
- CodeGraph called
- Understand-Anything skipped
- module/risk/reusable capability outputs generated

Why it fails L4:

- process artifacts were written into the target repository
- no `artifact-persistence-policy.json`
- no `assistant-run-feedback.json`
- no `capability-health.json`
- no `capability-output-consumption.json`

## Sample 3: project audit run

Artifact root:

`/Users/fengtianyangyang/workspace/Playground/micro/bc-service/artifacts/workflow-orchestrator/audit-20260621T012651+0800`

Observed status:

`blocked`

Useful evidence:

- `engineering-assistant:code-review`: call
- `engineering-assistant:code-quality-governor`: call
- `mcp__codegraph.codegraph_context`: call
- `codex-security:security-scan`: skip

Why it fails L4:

- process artifacts were written into the target repository
- no agent-consumed feedback
- no capability health check
- no capability output consumption proof

## How to use these samples

Use these as failed/partial L4 regression cases. They should not be counted as
L4 passing evidence until a rerun produces:

- ephemeral artifact root under `~/.codex/run-artifacts/engineering-assistant`
- `assistant-run-feedback.json`
- `capability-health.json` for tool-backed capabilities
- `capability-output-consumption.json` for called outputs
- no process artifacts written into target repository by default
