"""Offline verification for pinned open-source review evidence."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Callable, Mapping

from ..runtime.artifact_io import ArtifactIO
from ..runtime.catalog import Catalog, SourceDecision
from ..runtime.validation import ValidationFailure


MAX_SOURCE_EVIDENCE_BYTES = 8 * 1024 * 1024
RevisionReader = Callable[[Path], str]


def _git_revision(checkout: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    revision = completed.stdout.strip()
    if completed.returncode != 0 or len(revision) != 40:
        raise ValidationFailure(
            f"source checkout has no readable git revision: {checkout}"
        )
    return revision


def verify_source_checkout(
    source: SourceDecision,
    checkout: Path | str,
    *,
    revision_reader: RevisionReader = _git_revision,
) -> dict:
    raw_checkout = Path(checkout).expanduser()
    if raw_checkout.is_symlink() or not raw_checkout.is_dir():
        raise ValidationFailure(f"source {source.id}: checkout is missing or unsafe")
    checkout_root = raw_checkout.resolve()
    observed_revision = revision_reader(checkout_root)
    if observed_revision != source.revision:
        raise ValidationFailure(
            f"source {source.id}: checkout revision does not match pinned revision"
        )

    expected_paths = set(source.license_evidence) | set(source.evidence_paths)
    if set(source.evidence_digests) != expected_paths:
        raise ValidationFailure(
            f"source {source.id}: evidence digest coverage is incomplete"
        )
    artifacts = ArtifactIO(checkout_root, ".")
    try:
        observed_digests: dict[str, str] = {}
        for relative in sorted(expected_paths):
            content = artifacts.read_bytes_limited(
                MAX_SOURCE_EVIDENCE_BYTES,
                *Path(relative).parts,
            )
            observed = "sha256:" + hashlib.sha256(content).hexdigest()
            expected = source.evidence_digests[relative]
            if observed != expected:
                raise ValidationFailure(
                    f"source {source.id}: evidence digest mismatch for {relative}"
                )
            observed_digests[relative] = observed
    finally:
        artifacts.close()
    return {
        "source_id": source.id,
        "status": "passed",
        "repository_url": source.repository_url,
        "revision": observed_revision,
        "evidence_file_count": len(observed_digests),
        "evidence_digests": observed_digests,
    }


def verify_source_checkouts(
    catalog: Catalog,
    roots: Mapping[str, Path | str],
    *,
    revision_reader: RevisionReader = _git_revision,
) -> dict:
    expected = set(catalog.sources)
    provided = set(roots)
    if provided != expected:
        missing = sorted(expected - provided)
        unknown = sorted(provided - expected)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise ValidationFailure(
            "source verification requires every catalog source: " + "; ".join(details)
        )
    reports = [
        verify_source_checkout(
            catalog.sources[source_id],
            roots[source_id],
            revision_reader=revision_reader,
        )
        for source_id in sorted(expected)
    ]
    return {
        "status": "passed",
        "source_count": len(reports),
        "sources": reports,
    }
