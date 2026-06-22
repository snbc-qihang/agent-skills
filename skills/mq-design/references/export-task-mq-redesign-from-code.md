# Export-task MQ redesign from existing code

Use this when redesigning async export / batch-task MQ contracts from an existing Java/Spring codebase rather than from a greenfield requirement.

## Durable lessons

1. Start from the live producer and dispatcher, not from stale design artifacts.
   - Trace the producer send call for exchange/routingKey/body shape.
   - Trace the listener/strategy factory to see whether dispatch is by routingKey or by `configType`.
   - Trace the consumer handler to see where it reads identifiers from the message body.
   - Trace task creation persistence to confirm whether MQ can carry only task identity.

2. For async export messages, keep the body small and task-oriented.
   - Put large query conditions, permission snapshots, file path, progress and failure reason in the task table.
   - MQ should normally carry only root envelope fields plus task identity/routing/audit fields.

3. When the required unified envelope is introduced, write both producer and consumer deltas explicitly.
   - Example root shape: `issueId`, `configType`, and a body node named after `configType`.
   - If existing code sends a flat body, call out that the producer must wrap fields under the body node.
   - If existing code reads `taskId` from the root, call out that the consumer must read `<bodyRoot>.taskId` and validate `configType`.
   - If dispatch still uses routingKey, state that adding `configType` does not change routing unless code evidence says it does.

4. Do not carry forward unrelated messages from prior MQ design artifacts.
   - If the user asks to redesign export MQ, remove stale order-change/read-model messages unless the current scope explicitly includes them.
   - Existing design artifacts are inputs, not facts; code evidence wins when they conflict.

5. Artifact-path pitfall.
   - Some teamwork runs keep a repo-local artifact copy and a registered artifact path outside the repo.
   - If `stage-run-result.json` registers the external path, update and validate that registered path; if the repo also has a copy the user will inspect, keep the repo copy in sync or state which one is authoritative.

## Validation checklist

- Run the generic `validate_stage_run_result.py` on the registered `stage-run-result.json`.
- Run the skill-specific `skills/mq-design/scripts/validate_output.py` on the same result file.
- If a repo-local copy also exists and will be reviewed, run both validators against that copy too.
- For `mq-design.xlsx`, regenerate from the template with XML-preserving writes if validation reports style, merge-cell, dimension or added-row errors; do not use workbook libraries that rewrite template styles unless the validator proves it remains clean.
