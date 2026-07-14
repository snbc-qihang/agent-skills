# Overlay Retention Boundary

Use this reference before adding durable Engineering Assistant overlay rules or accumulating repeated record files.

## Core rule

The overlay is not a transcript, changelog, or issue database. It is a small durable policy layer. Put only always-needed routing rules, checks, and gate names in `SKILL.md`.

## Where content belongs

- `SKILL.md`: triggers, short do/check/gate rules, capability names, and routing boundaries.
- `references/`: detailed protocols, examples, decision tables, and domain-specific guidance loaded only when needed.
- `scripts/`: deterministic checks, generators, compaction validators, and repeatable transformations.
- `schemas/`: JSON contracts for machine-checkable artifacts.
- `templates/`: reusable minimal output templates.
- `run-artifacts/`: one-run evidence, raw samples, temporary audit reports, failed attempts, and candidate rules.
- formal project docs: only approved and project-owned documents.

## Size budgets

- `SKILL.md` target: concise; soft budget 500 lines, hard budget 650 lines.
- single reference target: soft budget 200 lines, hard budget 400 lines unless it is a schema or generated artifact.
- cumulative upgrade summary target: soft budget 220 lines, hard budget 400 lines.
- raw sample reports stay in dated run-artifact folders and should not be copied into overlay.

Soft budget means "summarize or move detail soon." Hard budget means "stop appending and compact or archive first."

## Compaction review before adding durable rules

Record:

- `new_rule_or_record`
- `why_durable`
- `source_samples`
- `existing_rule_to_update`
- `duplicate_or_overlap`
- `project_specific_or_global`
- `can_live_in_reference`
- `can_live_in_run_artifact_only`
- `expiry_or_review_date`
- `expected_validation`
- `decision`: `append`, `merge`, `move_to_reference`, `run_artifact_only`, `reject`, or `archive_then_append`.

## Record-file rotation

Long cumulative files such as upgrade summaries must not grow forever. When soft budget is reached, append only a short index entry and move details to a dated artifact. When hard budget is reached, create an archive summary and start a new current summary.

## Run-artifact retention

Default process artifacts are ephemeral. Keep only:

- `assistant-run-feedback.json`
- `assistant-run-feedback.summary.md`
- `closed-loop-outcome.json`
- `closed-loop-outcome.summary.md`
- `minimal-evidence-index.json`

Keep raw samples, full traces, screenshots, and long reports only when the run is failed, under active review, or explicitly approved for formal retention.
