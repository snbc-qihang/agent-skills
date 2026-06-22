# Phase-gated project inspection pattern

Use this when a user asks for broad existing-system inspection that includes architecture, performance, and code-smell findings, but the project lacks an agreed business/domain blueprint.

## Problem this prevents

Broad inspections often jump from service names, Feign/MQ counts, or code smells directly into architecture conclusions. That produces plausible but weak findings because the actual business ownership boundaries are not established.

## Pattern

1. Treat business/domain analysis as Phase 1.
2. Extract full-business code facts first: entry APIs, service responsibilities, mappers/tables, MQ listeners, Feign clients, data objects, external dependencies, and open questions.
3. Convert code facts into a DDD business-first model:
   - business objects
   - business processes
   - business rule clusters
   - lifecycle ownership
   - platform vs local vs peripheral capability boundaries
4. Do not enter architecture/performance/code-smell inspection until Phase 1 has a user-confirmed conclusion.
5. When evidence is enough for review but not final, stop expanding process docs and generate a compact review package:
   - P0 decisions that block next phase
   - P1 decisions that can be tentative
   - proposed core/supporting/peripheral domains
   - confirmed platform/local boundaries
   - explicit “allowed next phase” and “not allowed yet” gates
6. If the user confirms P0 and accepts/tentatively accepts P1, generate a Phase 1 conclusion document with `document_status: approved_for_next_phase` and update the project `final/README.md` to point to it.
7. Only then start architecture/performance/code-smell inspection. All later findings must be constrained by the confirmed domain model.

## Recommended artifact set

- `business-capability-inventory.md`
- `business-capability-detail.md`
- `ddd-business-domain-model-v0.1.md`
- `p0-lifecycle-evidence.md`
- `business-analysis-completion-review.md`
- `phase1-business-analysis-review-package.md`
- `phase1-business-analysis-conclusion.md`
- `business-analysis-completion-gate.md`
- `final/README.md`
- `machine/evidence-map.json`

## Gate semantics

- `candidate`: evidence/model exists, not yet reviewed.
- `candidate_review`: ready for user review, not ready for technical inspection.
- `confirmed`: review package accepted by user.
- `approved_for_next_phase` or `ready_for_next_phase`: business analysis can constrain downstream inspection.

## Pitfalls

- Do not mark business analysis final just because a DDD model exists.
- Do not continue producing large process documents after review questions are known; generate a review package instead.
- Do not treat user “同意” ambiguously when it follows a specific confirmation request; record which P0/P1 decisions were accepted and update the gate artifacts.
- Do not bury the current state in many old documents. Keep `final/README.md` and a top-level `README.md` as the human entry points; keep long scans in machine JSON/CSV/YAML.
