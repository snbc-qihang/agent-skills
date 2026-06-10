# Scenario-based personal profile mining

Use when the user wants project work to improve personal capability and help an AI agent understand how to plan for them.

## Principle

Do not ask abstract self-evaluation questions such as “what kind of person are you?” or “what are your strengths?” Direct personal evaluation is often hard and produces low-quality labels.

Use concrete scenarios instead.

## Flow

1. Present a realistic work scenario tied to the current project.
2. Offer 4-6 choices plus an “other / describe yourself” option.
3. Record the user’s selection exactly.
4. Infer a candidate profile observation.
5. Link the observation to evidence and future planning behavior.
6. Keep status as `candidate` until validated across multiple scenarios or explicitly confirmed.

## Good scenario dimensions

- Time pressure: what the user sacrifices or protects under deadline pressure.
- Team disagreement: whether they decide, facilitate, time-slice, or escalate.
- Project completion: what counts as done.
- Evidence standards: how they handle assumptions and incomplete knowledge.
- Role switching: when they act as architect, expert, executor, or knowledge curator.
- Delegation: what must align before others explore independently.
- Communication: how they explain decisions upward, sideways, and to themselves.

## Output shape

Store detailed profile in a durable personal profile file, e.g.:

`~/.hermes/user-profile/personal-operating-profile.md`

Keep Hermes memory compact:

- stable preferences;
- storage path;
- high-signal collaboration rules.

Store project-specific evidence in project `learning/`, not in final project deliverables.

## Planning implication

Profiles must change how plans are written. Include:

- the user’s role for each phase;
- phase goals and exit criteria;
- time boxes;
- decision explanation templates;
- short-term / mid-term / long-term lanes;
- rules for separating final artifacts from learning artifacts.
