# Requirement Clarification And Argumentation Standard

This standard is owned by the existing `requirement-intake` Skill and composed only by `workflow-orchestrator`. It absorbs the useful behavior of `interview-me`, `idea-refine`, `spec-driven-development`, and `doubt-driven-development` without importing an upstream router, command, persona, or gate owner.

## Trigger

- Clarify when a request has more than one materially different interpretation, or lacks objective, target user, success criteria, constraints, or non-goals.
- Run argumentation for `L2_SHARED` and `L3_CRITICAL`, and for lower-risk work whose feasibility, architecture direction, or root cause is materially uncertain.
- Do not interview for mechanical, informational, or already unambiguous work.

## Stage 1: Bounded Intent Clarification

1. Read available source, repository, history, and user context before asking.
2. Track six fields: `objective`, `target_user`, `success_criteria`, `constraints`, `non_goals`, and `why_now`.
3. Infer fields supported by evidence. Ask only about a missing field that changes the solution.
4. Ask exactly one question per turn. Include a concise best-supported interpretation when useful.
5. Stop without final confirmation as soon as objective, target user, success, constraints, and non-goals are clear and no mutually exclusive interpretation remains. `why_now` is optional unless it changes priority or scope.
6. Stop after six questions. If a material ambiguity remains, return `waiting_for_input`; do not plan or code.

## Stage 2: Feasibility Argumentation

1. Freeze the clarified requirement and a focused evidence packet. Label every source as user-confirmed, source-verified, historical, or inferred.
2. Check current architecture and code ownership, exact stack and dependencies, existing reusable utilities, data and external systems, security and operational risks, rollback or disable path, testability, and material delivery cost.
3. Generate at most three meaningfully different executable candidates. Prefer the smallest path that preserves existing behavior.
4. Record one selected path and reasons for rejecting alternatives. A single candidate is valid when evidence rules out meaningful alternatives.
5. For repeated bugs, fix-A-break-B, uncertain root cause, or L3 disagreement, send only `ARTIFACT + CONTRACT` to a fresh read-only reviewer. Do not send the author's claim or chain of reasoning. Reconcile findings; reviewers never spawn reviewers.
6. Return exactly one verdict:
   - `executable`: prerequisites and evidence are sufficient.
   - `executable_after_conditions`: list concrete unmet conditions and the resume check.
   - `not_executable`: stop implementation, cite blocking evidence, and provide the nearest viable alternative.

## Output

Write `requirement-argumentation.json` to the run artifact root, not the target repository, unless the user explicitly requests formal retention. Validate it with `validate_requirement_argumentation.py`. Downstream design and implementation Skills consume only the selected path, protected invariants, rejected-alternative reasons, conditions, and evidence references.

## Checks

- No question was asked when source evidence made the request unambiguous.
- Clarification used one question per turn and no more than six.
- Complex work includes architecture/code, dependencies/reuse, data/external systems, risks/rollback, tests, and cost evidence.
- The verdict, selected path, rejected alternatives, and stop/resume behavior are internally consistent.
- Fresh review, when triggered, received artifact and contract without the author's claim.

## Gate

- `REQUIREMENT_INTENT_AMBIGUOUS`: a material ambiguity remains.
- `REQUIREMENT_CLARIFICATION_UNBOUNDED`: the one-question or six-question bound was exceeded.
- `FEASIBILITY_ARGUMENTATION_MISSING`: complex or materially uncertain work skipped argumentation.
- `FEASIBILITY_EVIDENCE_INCOMPLETE`: a required evidence dimension is absent.
- `NON_EXECUTABLE_PATH_CONTINUED`: planning or implementation continued after a `not_executable` verdict.
