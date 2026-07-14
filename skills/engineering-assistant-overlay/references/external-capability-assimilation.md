# External Capability Assimilation

Use this protocol when Engineering Assistant audits, imports, absorbs, replaces, or upgrades an external skill or capability pack. Engineering Assistant remains the only task entrypoint, router, gate owner, and acceptance authority.

## Trigger

- The user asks to install, merge, absorb, ingest, or upgrade an external skill.
- A capability audit identifies an external implementation that may close a verified Engineering Assistant gap.
- A previously absorbed capability has a proposed local version upgrade.

## Do

1. Freeze the source inventory and list every candidate capability. Do not install its router, commands, personas, or workflow controller into the active path.
2. Build `capability-overlap-matrix.json`. Classify every candidate as `absorbed`, `covered`, `deferred`, or `rejected_router_conflict` with current evidence and a target owner.
3. Absorb only a demonstrated delta. Rewrite it as an Engineering Assistant-native action, check, stop condition, and gate; do not retain a competing meta-skill.
4. Assign one gate level:
   - `G0`: hard block for repeated-fix evidence gaps, fix-A-break-B survival gaps, deterministic test/build failures, critical design gaps, router ownership conflicts, or existing capability regression.
   - `G1`: conditional block for non-trivial source/version decisions, high-risk context handoffs, evidenced business-code pileup, formal release evidence, or other triggered risk that can be satisfied with a bounded check.
   - `G2`: observation for simplification, optional instrumentation, or optimization candidates that do not invalidate current correctness.
5. Register the adapted capability in `registry/absorbed-capabilities.json`. Give it an independent local semantic version. Upstream commits are not runtime version identifiers.
6. Replay a finite acceptance set. Every G0 case must pass, the configured overall threshold must pass, and all existing gates listed as protected must survive.
7. Produce an upgrade report and rollback path. Future upstream changes enter as a new audit and local version upgrade; they never overwrite the active capability automatically.

## Checks

- `sole_entrypoint=engineering-assistant` and `sole_gate_owner=engineering-assistant`.
- Every source candidate has one overlap decision and evidence-backed rationale.
- Every absorbed capability names its source skill, native owner, trigger, gate level, completion evidence, stop condition, and protected existing gates.
- `using-agent-skills` or an equivalent upstream router is rejected, and upstream commands are not imported.
- The local version is independent, upgrade history is append-only, and source attribution/license are retained.
- Acceptance evidence includes the agreed case count, G0 pass rate, overall pass rate, and existing-regression count.

## Gate

- `EXTERNAL_CAPABILITY_GAP_NOT_PROVEN`: absorption has no verified incremental gap.
- `EXTERNAL_CAPABILITY_ROUTER_CONFLICT`: an upstream router, controller, or command surface would compete with Engineering Assistant.
- `EXTERNAL_CAPABILITY_OVERLAP_UNCLASSIFIED`: a source candidate lacks an overlap decision.
- `EXTERNAL_CAPABILITY_GATE_LEVEL_MISSING`: an absorbed capability has no G0/G1/G2 classification.
- `EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED`: G0, overall threshold, or protected-gate regression requirements fail.
- `EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED`: a local version is changed without a new overlap audit and acceptance result.

## Stop Conditions

- Stop before adoption if the source inventory, license, delta evidence, or protected existing behavior cannot be established.
- Stop after the finite acceptance set; do not expand the current upgrade with unapproved capabilities.
- Leave evidence-poor candidates as `deferred`; absence of evidence is not a reason to install everything.
