# YQ / existing-system architecture inspection artifact governance

Use this reference when a project architecture inspection starts producing too many process documents.

## Storage split

- `final/`: the final human-facing project knowledge base. One or very few stable documents. Contains confirmed conclusions only.
- `learning/`: process learning, personal capability harvests, Socratic personal-profile evidence, method retrospectives.
- `machine/`: evidence maps, scan outputs, JSON/CSV indices, call graphs, raw data for repeatable analysis.
- `human/`, phase directories, ADR drafts: intermediate review material. Useful for traceability, not daily reading.

## Final document rule

Final architecture documents should contain:

1. Overall system relationship.
2. Confirmed architecture decisions.
3. Architecture diagrams.
4. Domain architecture.
5. Business capability map.
6. Data boundary.
7. Anti-corruption layer / integration boundary.
8. Next-phase entry rules.

Do not include long process narratives, raw code evidence, decision matrices, or exploratory scan details in final documents. Put them in `learning/` or `machine/`.

## Evidence rule

Final docs only contain facts that are:

- confirmed by the user or business owner;
- supported by code evidence;
- supported by existing project documentation;
- or explicitly marked as open question / candidate when not confirmed.

Never turn inferred architecture into final conclusion just to make a diagram look complete.

## Planning implication

When moving from architecture baseline to concrete governance, require each issue to map to:

- domain / bounded context;
- data type: platform fact, local copy, Yingqi business fact, integration governance data;
- platform-vs-Yingqi boundary;
- risk level;
- short-term vs mid-term vs long-term lane.
