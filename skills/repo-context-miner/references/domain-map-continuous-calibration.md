# Existing-system domain map: continuous full-business calibration

Use this reference when extracting a business-domain map from an existing codebase.

## Durable workflow lesson

Do not let a few representative business chains become the basis of the whole domain map.

Representative chains are useful only for calibration:

- validate naming against real business flow
- expose hidden cross-service collaboration
- test whether a boundary is plausible
- find ambiguous ownership questions

The domain map itself must be continuously summarized from the full scanned business scope:

1. Extract all business capabilities across the covered services.
2. Build a candidate full-business domain map from the entire capability set.
3. Use selected chains only to calibrate names and boundaries.
4. When the user confirms a boundary, write it back into:
   - the human domain map
   - the domain boundary calibration table
   - the machine evidence/index file
   - open questions, marking the question as resolved
5. Keep candidate/final states explicit. Do not promote candidate domains to final until the user confirms them.

## Boundary calibration table shape

For each candidate domain, track:

- included capabilities
- explicitly excluded capabilities
- primary owning/hosting services
- collaborating services or external platform capability owners
- data-object evidence candidates
- event/dependency evidence candidates
- confirmed boundary decisions
- remaining open questions

## Pitfalls

- Do not infer domain ownership from service name alone.
- Do not classify a platform capability as local business ownership just because local code calls it or stores a copy/reference.
- Do not treat peripheral capabilities as core just because they have substantial code volume.
- Do not bury user-confirmed boundary decisions in conversation summaries; persist them in both human-readable docs and machine-readable indexes.
