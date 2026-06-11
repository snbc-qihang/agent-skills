# Design governance loop: prevent wasteful draft churn

Use this reference when orchestrating product/engineering design workflows where the agent collects information, generates design docs, self-reviews, incorporates human review, and mines reusable rules.

## Durable workflow
1. Collect and classify information before formal generation:
   - team rules / long-lived standards
   - project facts
   - current requirement facts
   - run state / workflow evidence
   - eval or regression examples
2. Decide whether information collection is complete. Minimum checks: goal, scope, non-goals, involved systems, data objects, key flows, impacted specialties, missing-info classification.
3. If blocking facts or direction choices are missing, pause in `waiting_for_input` and produce only control artifacts such as information inventory, missing-information list, required-information request, direction-decision draft, workflow trace, and resume point.
4. Do not generate formal design documents until `preflight_input_state == ready` and direction/specialty scope are confirmed.
5. After formal generation, run deterministic validators plus reviewer-agent self-review.
6. Auto-fix only bounded issues: formatting, template gaps, known fact omissions, terminology inconsistency, document routing, and clarity of already-confirmed decisions.
7. Do not auto-fix business direction, core interface addition/removal, risk strategy, system boundaries, or human approvals.
8. Send a human-review package only after self-review. Human review state is not final/approved.
9. Classify human feedback before revising: fact completion, direction change, document defect, standard violation, team-rule candidate.
10. Prefer incremental patching of affected artifacts. Full regeneration requires a core architecture/data/interface/message-model change, impact analysis, and marking previous versions superseded.
11. Mine user corrections, agent corrections, self-review findings, and human-review feedback into rule/prompt candidates for TL review. Never auto-write candidates into team plugins, SKILL.md, templates, or validators.

## Anti-patterns
- Generating a full set of formal design docs and then asking the user to fill missing information.
- Treating human-review HTML as a machine fact source.
- Turning one requirement’s concrete facts into team plugin rules.
- Letting agent self-review replace human approval.
- Regenerating every design document after small review comments.

## Candidate package shape for TL
Each rule/prompt candidate should include: candidate_id, source_run_id, original user change, agent original design, human review feedback, generalized rule, scope, non-scope, counterexamples, whether it contains concrete business facts, generalization level, suggested landing zone, and TL review status.
