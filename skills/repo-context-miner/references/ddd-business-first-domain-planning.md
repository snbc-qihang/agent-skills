# DDD business-first domain planning for existing codebases

Use this reference when a repository inspection is being used to produce a business/domain map.

## Core lesson

A domain map for an existing system must not be treated as DDD-complete just because it is backed by service/controller/service/mapper/MQ/Feign evidence.

Code facts are evidence. They are not the domain boundary.

The correct sequence is:

1. Extract full-business code facts first so the agent does not invent domains.
2. Label the resulting map explicitly as a code-fact-constrained business-domain candidate.
3. Derive a DDD business-first model from business objects, business flows, business rules, and lifecycles.
4. Map the DDD model back to code evidence and record where current code supports, mixes, or distorts the business domains.
5. Only after user agreement may the candidate become a phase conclusion.

## Pitfall seen in practice

If the agent starts from existing services and then names domains, the output can look like a DDD domain model while still being shaped by historical service boundaries, package names, API names, and current implementation accidents.

The right wording is not:

- “This is the YQ domain model.”

Use:

- “This is a code-fact-constrained domain candidate.”
- “This is current-system evidence for later DDD derivation.”
- “Service is evidence, not domain boundary.”

## Business-first derivation checklist

Before calling a domain map a DDD model, identify:

1. Business objects: users, members, orders, coupons/activities, accounts, operators/franchisees, points/sites, device-collaboration relationships, product extensions, price extensions.
2. Business flows: user transaction, membership entitlement, marketing/coupon, account/prestore/refund, operator management, point operation, product-price extension config and publish, device collaboration.
3. Business-rule clusters: rules that change together, are maintained by the same business role, share the same language, and have real business cohesion rather than just technical coupling.
4. Lifecycle boundaries: who creates an object, who maintains it, who changes its state, who consumes it, and whether the state belongs to the local business system or the platform.
5. Platform/local ownership: which capabilities are platform-owned and which are local extensions.

## Output pattern

For each domain candidate, include:

- one-sentence business definition
- owning capabilities
- non-owning capabilities
- upstream/platform dependencies
- downstream collaborations
- current code evidence
- open questions
- whether the boundary is user-confirmed or candidate

## Guardrail

Do not proceed from code-fact domain candidates into architecture, performance, code-smell, coupling, MQ/Feign governance, or service split recommendations until the user has agreed on the business-first domain model.
