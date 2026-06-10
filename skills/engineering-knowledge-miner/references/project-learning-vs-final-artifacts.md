# YQ session learning: final artifact vs process harvest

This reference captures a durable pattern from the YQ architecture inspection session.

## Problem observed

The agent produced many intermediate artifacts while exploring architecture boundaries. The user clarified that the real need was not more process documentation, but a final domain/architecture document.

The user then reframed the larger optimization goal:

1. Process harvest: improve the user's personal capabilities through repeated project work.
2. Final deliverable: build the project knowledge base after the project is complete.

These are separate products and should not be mixed.

## Durable workflow

For multi-round project optimization:

1. Maintain a `final/` entry point for the project's final knowledge base.
2. Maintain a `learning/` entry point for process harvest and personal capability growth.
3. Keep `machine/`, draft, matrix, and evidence directories as trace material only.
4. At each phase boundary, update both:
   - final deliverable if project knowledge changed;
   - learning notes if the user's judgment pattern or reusable method changed.
5. Do not force the user to read the process trail.

## Socratic profile collection

When the user asks to learn about themselves during the project, add a lightweight Socratic loop:

- Ask only 2-4 questions at key moments.
- Questions must be tied to the current project decision.
- Capture observations as `candidate`, `confirmed`, or `rejected`.
- Focus on judgment patterns, stage-boundary criteria, document preferences, reaction to disagreement, and learning goals.
- Do not turn this into a generic personality test.

## Trigger phrases

- “过程文档太多”
- “我真正需要的是最终文档”
- “过程收获”
- “最终产物”
- “个人能力提升”
- “苏格拉底提问法”
- “个人画像”

## Recommended artifact shape

```text
artifacts/project-inspection/
  final/
    README.md
    <project-final-architecture-or-knowledge-base>.md
  learning/
    README.md
    socratic-personal-profile.md
  machine/
    evidence-map.json
```
