# Engineering Code Quality Constitution

This reference defines the Engineering Assistant quality floor. Load it for non-trivial implementation, refactoring, simplification, or code review, especially when repository conventions are incomplete or visibly weak.

## Trigger

- L1/L2/L3 code implementation or review.
- The repository contains duplicated rules, unclear ownership, weak tests, utility dumping, or inconsistent conventions.
- A change adds an abstraction, design pattern, dependency, framework integration, extension point, or hand-written infrastructure.
- A review suggestion would add code for a hypothetical future use case.

L0 local-only edits do not require a formal quality record, but they still preserve behavior and avoid unrelated change.

## Rule Hierarchy

Apply rules in this order:

1. Correctness, security, data integrity, explicit requirements, and protected behavior.
2. This Engineering Assistant quality floor.
3. Repository architecture, framework, language, and team conventions that do not weaken levels 1 or 2.
4. Stylistic preferences.

Repository precedent is compatibility evidence, not proof of quality. A weak local pattern may be preserved only when replacing it would exceed the approved scope; new code must not copy it without recording the debt and the smallest contained alternative.

Stack-specific rules are conditional profiles, not universal architecture mandates. DDD applies only when the project or accepted design uses it. JDK features apply only after the actual runtime version is verified. A design pattern is selected only after its present problem and cheaper alternative have been evaluated.

## Two Independent Verdicts

For non-trivial code review or completion, record two independent verdicts:

- `spec_verdict`: the implementation satisfies requested behavior, constraints, edge cases, and protected existing behavior.
- `quality_verdict`: the implementation satisfies ownership, cohesion, readability, boundaries, testability, failure behavior, and triggered security/performance requirements.

Overall success requires both verdicts to pass. A passing test suite cannot excuse misplaced business rules, speculative abstractions, or unreviewed regression risk. A clean structure cannot excuse incorrect behavior.

## Quality Floor

Check the changed ownership slice for:

- Correct behavior and explicit failure semantics.
- One clear owner for each business rule, invariant, state transition, and external boundary.
- Cohesive placement: orchestration, domain rules, persistence, transport, and presentation are not mixed without a current reason.
- Readability through explicit names and control flow; clever syntax is not a goal.
- Reuse of verified JDK, framework, project, or library capabilities before custom infrastructure.
- Tests at the smallest public seam that prove the changed behavior and preserve adjacent known-good behavior.
- Security, concurrency, performance, observability, migration, and rollback checks only when their risk triggers apply.
- Minimal necessary complexity: every new layer, type, option, dependency, or extension point pays for a present requirement or risk.

Do not use method length, class count, abstraction count, design-pattern count, or cognitive-complexity score as a standalone pass/fail rule. Metrics locate review targets; evidence decides the finding.

## Evidence-Based Complexity Control

Before adding an abstraction, design pattern, dependency, configurable option, or extension point, record:

1. The current problem or risk it solves.
2. The existing capability or simpler implementation considered first.
3. Concrete evidence for the added complexity.
4. Its ownership boundary and current consumers.
5. The test seam and the condition under which the abstraction should be removed or not expanded.

Valid evidence includes at least one of:

- Multiple current variants or consumers share a stable responsibility.
- A volatile external system or framework boundary must be isolated.
- An invariant, construction rule, state transition, or transaction boundary needs enforced ownership.
- Measured duplication, coupling, failure history, or change impact shows the simpler form is already costly.
- The verified framework contract requires an extension point.

Invalid evidence includes "might be useful later", style preference, a fixed line threshold, design-pattern enthusiasm, or copying a neighboring abstraction without proving the same responsibility.

One consumer can justify a boundary when it isolates a real external dependency or protects an invariant. Two consumers do not automatically justify an abstraction when their behavior only looks similar. This avoids both premature abstraction and rigid counting rules.

## Smell Baseline

Use this catalog to investigate, not to hunt patterns mechanically:

- Duplicated business knowledge or state transitions.
- Divergent change, shotgun surgery, and unrelated rule concentration.
- Feature envy, data clumps, primitive obsession, and repeated type/status switches.
- Speculative generality, middle-man layers, message chains, and shallow wrappers.
- God service/class, utility dumping, framework leakage, hidden side effects, and untestable static/global state.
- Tests that assert implementation trivia, omit business outcomes, or cannot protect adjacent behavior.

Each smell finding must name the concrete maintenance or correctness cost, cite changed-scope evidence, and propose the smallest remedy. A smell without demonstrated cost is an observation, not a blocker.

## Review Suggestion Filter

Before implementing review advice:

1. Verify the suggestion against source, tests, requirements, and actual runtime/library versions.
2. Classify it as correctness/security, quality-floor compliance, current simplification, optional optimization, or hypothetical future work.
3. Implement only the smallest current change that preserves accepted behavior.
4. Reject or defer hypothetical features, unused configurability, pattern-only rewrites, and metric gaming.
5. Rerun the target check and the nearest preservation check after each independent fix.

## Checks

- `quality_rule_hierarchy`: the selected rule source and any local conflict are recorded.
- `spec_verdict` and `quality_verdict`: independently evidenced for L1/L2/L3 completion or review.
- `smell_evidence`: only changed-scope smells with demonstrated cost affect the gate.
- `complexity_evidence`: required only when new complexity is introduced.
- `review_suggestion_verification`: required only when review advice changes code or design.
- `post_green_scope`: simplification stays within the changed ownership slice and preservation checks remain green.

## Gate

- `ENGINEERING_QUALITY_FLOOR_BYPASSED`: repository precedent or a passing functional check was used to waive the independent quality floor.
- `OVER_DESIGN_BOUNDARY_UNCHECKED`: new complexity lacks current evidence, a simpler-path comparison, ownership, or a test seam.
- `CHANGE_VERIFICATION_EVIDENCE_MISSING`: review advice or simplification changed behavior/design without target and preservation evidence.

## Stop Conditions

- Stop after the changed ownership slice passes both verdicts and triggered checks; do not expand into repository-wide cleanup.
- Leave unrelated legacy debt as evidenced residual risk.
- Stop and return to diagnosis/design when ownership, protected behavior, or the current reason for an abstraction cannot be established.

## Adapted Sources

- `addyosmani/agent-skills`: code review dimensions and behavior-preserving simplification.
- `mattpocock/skills`: independent standards/spec review and code-smell baseline.
- `anthropics/claude-plugins-official`: changed-scope simplification and explicit readability.
- `obra/superpowers`: test evidence, minimal implementation, and verification of review suggestions before implementation.

Engineering Assistant owns the local hierarchy, routing, gate levels, acceptance cases, and wording. No upstream router, command surface, persona, or fixed metric threshold is imported.
