# Target Repo Doc Governance

Use this when Engineering Assistant may write Markdown into a target repository, or when the user reports that generated docs polluted a project.

## Core rule

Project `docs/` is for project-owned documents, not run traces. Temporary plans, summaries, audits, review notes, capability matrices, and generated process reports belong in `~/.codex/run-artifacts/engineering-assistant/<repo-slug>/<run_id>/`.

## Before writing Markdown to a target repo

Allowed only when the user explicitly asks for formal retention or the file is a project-maintained document.

Record:

- document purpose;
- owner;
- document status: `draft`, `reviewing`, `approved`, `final`, `deprecated`, or `unknown`;
- retention policy: `ephemeral`, `candidate`, `persist`, or `remove_candidate`;
- source artifacts;
- approval status;
- expected reader;
- removal or review condition.

If these cannot be named, do not write the Markdown into the project.

## Existing polluted docs

Do not delete blindly. First create a run-artifact `target-repo-doc-retention-index.json` with each Markdown file classified as:

- `formal_keep`: approved project doc;
- `candidate_review`: may be useful but needs user review;
- `process_artifact_move`: generated process/report file that should move to run artifacts;
- `remove_candidate`: safe-looking generated noise, pending user approval;
- `unknown`: insufficient evidence.

Cleanup requires explicit user approval. The assistant may recommend, but not perform, deletion or migration without approval.

## Gates

- `TARGET_REPO_DOC_PURPOSE_UNCLASSIFIED`: project Markdown exists or is being written without purpose, owner, status, and retention action.
- `TARGET_REPO_DOC_CLEANUP_WITHOUT_APPROVAL`: project Markdown was deleted or moved without user approval.
- `PROCESS_MD_WRITTEN_TO_PROJECT_DOCS`: process Markdown was written to target repo docs instead of run artifacts.
