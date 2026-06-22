# Existing System Domain Planning from Code Evidence

Use this reference when inspecting an existing codebase to support business-domain planning, especially when the user has not yet agreed on phase-1 conclusions.

## Core rule

Do not convert early scans into architecture conclusions.

A code scan may produce useful evidence, but service names, package names, Feign/MQ counts, large classes, or two representative service deep-dives are not enough to define domains or start governance.

## Safe sequence

1. Define the current stage.
   - If the user is still establishing business-domain planning, mark all outputs as `candidate`.
   - Do not call outputs `final`, `approved`, or `baseline` until the user confirms the phase conclusion.

2. Extract full business facts from code.
   - Business entries: controller/api/openapi.
   - Business flows: service/application/handler.
   - Data objects: entity/model/mapper/xml.
   - Event entries: mq/listener/producer.
   - External dependencies: feign/api/client.
   - Open questions: boundaries that code alone cannot prove.

3. Separate human documents from machine evidence.
   - Human docs: short, current, readable, decision-oriented.
   - Machine evidence: JSON/CSV/YAML indexes with full scan detail.
   - Avoid long Markdown dumps of scan results.

4. Calibrate with real business chains.
   - Pick one or two real chains.
   - For each chain list: business step, entry interface, core service, data object, event, external dependency, open question.
   - Use this to rename rough code tags into real business capability candidates.

5. Only after user agreement, move to architecture/governance.
   - Platform coupling matrices, technical debt plans, performance plans, and code smell reports belong after phase-1 business-domain agreement.

## Pitfalls

- Do not equate a service with a domain.
- Do not equate a directory with a business boundary.
- Do not treat Feign/MQ count as proof of coupling severity.
- Do not preserve obsolete process Markdown just because it was generated. If it is no longer useful, delete it or move full detail to machine evidence.
- Do not store concrete project facts in reusable skills. Keep project facts in project artifacts; keep this reference class-level.
