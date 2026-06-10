# DDD-first architecture inspection blueprint

Use this reference when a user asks for whole-system architecture inspection, service boundary review, or refactoring direction for an existing multi-service codebase.

## Lesson captured

A code inspection can correctly find MQ, Feign, transaction, long-class, and performance problems but still lead the team in the wrong direction if it jumps directly into local refactoring. For legacy multi-service systems, first establish a business/domain blueprint.

## Recommended sequence

1. Inventory current services, major call paths, Feign targets, MQ topics/queues, shared DTOs, and high-risk services.
2. Convert implementation evidence into candidate business domains / bounded contexts.
3. Classify each context:
   - Core domain
   - Supporting domain
   - Generic domain
   - External capability
4. Draw a context map:
   - Customer/Supplier
   - Partnership
   - Shared Kernel
   - Conformist
   - Anti-Corruption Layer
   - Event Subscriber
5. Define target boundaries and owned concepts for each context.
6. Reclassify local findings under the relevant domain and violated boundary.
7. Produce a domain governance backlog, not just a code cleanup list.

## Example context candidates for commerce / vending systems

- Transaction Fulfillment domain: order lifecycle, payment request orchestration, fulfillment, refund, state transitions.
- Device Sale / Open Door domain: vending machine, channel/stock view, open-door session, delivery result.
- Member Benefit domain: member identity, level, SVIP, benefit eligibility and usage.
- Marketing Activity / Coupon domain: activity configuration, promotion eligibility, coupon lock/redeem/release.
- Franchisee / Operator domain: service provider, point/location relationship, operational strategy.
- Product / Inventory View domain: product master data, product mapping, inventory view.
- Settlement / Payment domain: payment channel, prepay, payment result, refund result.
- Statistics / Analytics domain: read models, dashboards, exports.
- Identity / Organization domain: account, tenant, organization, permissions.

## Reframing local findings

Bad:
- "Fix MQ listener catch(Exception)."

Better:
- Problem: payment-success MQ can be swallowed.
- Domain: Transaction Fulfillment.
- Context relationship: Transaction Fulfillment consumes Payment Result from Settlement/Payment.
- Violated principle: event consumption lacks idempotent state transition and retry/dead-letter policy.
- Local code evidence: listener and handler locations.
- Governance action: define PaymentSucceeded event contract, consumption record, state transition guard, retry/DLQ policy.

## Pitfalls

- Do not treat current service names as domain boundaries.
- Do not recommend service splitting before bounded contexts, events, and tests are clear.
- Do not create a flat list of refactors; organize by domain ownership and target architecture.
- Do not let statistics/export/query needs pollute the transaction core model; prefer read models/events.
