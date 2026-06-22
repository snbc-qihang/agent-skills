# Business analysis completion gate for existing-system domain planning

Use this when inspecting an existing business system before architecture, performance, code-smell, service-boundary, MQ/Feign, or database-governance conclusions.

## Core lesson

A domain candidate map is not enough. Before downstream inspection, explicitly decide whether business analysis is complete.

Current-code evidence can support business analysis, but it must not define the business by itself. Services, Controller/Service/Mapper names, MQ listeners, Feign clients, tables, and package paths are evidence only.

## Required sequence

1. Extract code-fact-constrained business capability candidates.
2. Re-derive a DDD business-first model from:
   - business objects
   - business flows
   - business rule clusters
   - lifecycle boundaries
   - platform/business/peripheral ownership
3. Map code evidence back to the business model.
4. Add a business-analysis completion gate before any technical inspection.
5. If the gate fails, continue business analysis only.
6. If the gate is ready for review but not final, produce a review package for user confirmation.
7. Only after user confirmation may later architecture/performance/code-smell/governance work start.

## Gate checklist

Business analysis is not complete until all items are at least review-ready:

| Gate item | Evidence expected |
| --- | --- |
| Business object inventory | Core, supporting, and peripheral objects; ownership noted |
| Business flow inventory | Main user/operation/account/member/marketing/device-collaboration flows |
| Business rule clusters | High-cohesion business rules, not service-name clusters |
| Lifecycle boundaries | Who creates, maintains, changes state, and consumes each object |
| Platform/business/peripheral boundaries | Platform-owned, Yingqi-owned, and peripheral capabilities separated |
| Domain derivation | Domains derived from objects/flows/rules, then verified by code |
| Code evidence back-map | Code evidence supports/refutes the model; it does not define the model |
| User confirmation | Explicit approval before moving to downstream inspection |

## Blocking rule

Before the gate passes, do not output final conclusions for:

- architecture problems
- performance problems
- code smells
- service split/merge recommendations
- MQ/Feign/database governance
- release or refactor roadmaps

Allowed outputs before the gate passes:

- business facts
- business objects
- business flows
- business rules
- lifecycle evidence
- candidate domains
- open questions
- code evidence

## Review-ready but not final

If the model has enough evidence for user review but still has unresolved P0/P1 questions, generate a concise review package instead of expanding more process documents. The package should contain:

- current phase status
- P0 decisions with recommended answers and impact if rejected
- P1 questions that can be deferred
- phase conclusion draft
- explicit statement that technical inspection is still blocked until approval
