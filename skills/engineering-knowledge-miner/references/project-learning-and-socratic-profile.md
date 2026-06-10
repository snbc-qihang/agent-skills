# Project learning + Socratic personal profile workflow

Use this reference when a project optimization session has two goals:

1. Improve the user's personal capability through the process.
2. Produce a final project knowledge base as the deliverable.

## Key separation

Do not mix process learning into final project artifacts.

| Layer | Purpose | Typical location | Audience |
| --- | --- | --- | --- |
| Final project knowledge base | Stable conclusions, architecture baseline, decisions, diagrams | `final/` | Team / future project readers |
| Process learning | Personal capability growth, method lessons, retrospectives | `learning/` | User + agent |
| Socratic profile | Scenario-based personal positioning and planning inputs | `learning/socratic-personal-profile.md` | User + agent |
| Machine evidence | Evidence chain, scans, JSON/CSV maps | `machine/` | Agent / auditors |
| Drafts and ADRs | Traceability and decisions | phase folders / ADR folders | Occasional review |

## Why scenario-based questions

Direct personal evaluation is often difficult and inaccurate. Prefer concrete scenario questions that reveal patterns through choices and explanations.

Avoid:
- “What kind of person are you?”
- “What are your strengths?”
- “What are your weaknesses?”

Prefer:
- “You inherit a complex legacy system and the team wants to list MQ/Feign/table issues immediately. What do you stop first?”
- “An architecture diagram contains inferred, unconfirmed content. What worries you most?”
- “After the architecture baseline is accepted, which second-stage risk is most likely for you?”

## Questioning rules

- Ask at most 2–4 questions per round.
- Ask only at stage boundaries, user corrections, disagreements, or retrospectives.
- Use concrete work scenarios, not abstract self-labels.
- Record observations as `confirmed`, `candidate`, or `rejected`.
- Do not let profiling interrupt project progress; it should inform the next plan.

## Record format

```text
Observation:
Evidence:
Interpretation:
Status: candidate / confirmed / rejected
How to use in future planning:
```

## Planning implication

When enough profile signals exist, plans should include both:

1. Work plan: phases, deliverables, gates, verification.
2. Personal-fit plan: the role the user should play in each phase, likely risks, self-brake/self-push mechanisms, and how to externalize judgment to the team.

Example phase-role mapping:

| Phase | User role | Guardrail |
| --- | --- | --- |
| Architecture clarification | Boundary setter / architecture organizer | Do not enter local governance too early |
| Problem classification | Judge / problem cutter | Use issue-to-domain matrix |
| Governance execution | Execution driver | Use timeboxes to avoid endless classification |
| Knowledge closure | Knowledge curator | Keep `final/` clean; put process harvest in `learning/` |
