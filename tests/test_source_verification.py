from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.source_verification import (  # noqa: E402
    verify_source_checkout,
)
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class SourceVerificationTests(unittest.TestCase):
    def test_fixed_revision_and_evidence_content_are_verified(self) -> None:
        source = load_catalog(ROOT).sources["taste-skill"]
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            payloads = {
                path: f"verified content for {path}\n".encode("utf-8")
                for path in set(source.license_evidence) | set(source.evidence_paths)
            }
            for path, content in payloads.items():
                target = checkout / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            pinned = replace(
                source,
                evidence_digests={
                    path: "sha256:" + hashlib.sha256(content).hexdigest()
                    for path, content in payloads.items()
                },
            )

            report = verify_source_checkout(
                pinned,
                checkout,
                revision_reader=lambda _root: pinned.revision,
            )

            self.assertEqual("passed", report["status"])
            self.assertEqual(pinned.revision, report["revision"])
            self.assertEqual(len(payloads), report["evidence_file_count"])

    def test_tampered_source_evidence_is_rejected(self) -> None:
        source = load_catalog(ROOT).sources["taste-skill"]
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            for path in set(source.license_evidence) | set(source.evidence_paths):
                target = checkout / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"tampered\n")

            with self.assertRaisesRegex(ValidationFailure, "digest"):
                verify_source_checkout(
                    source,
                    checkout,
                    revision_reader=lambda _root: source.revision,
                )

    def test_wrong_checkout_revision_is_rejected_before_content_is_trusted(self) -> None:
        source = load_catalog(ROOT).sources["taste-skill"]
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValidationFailure, "revision"):
                verify_source_checkout(
                    source,
                    Path(temporary),
                    revision_reader=lambda _root: "0" * 40,
                )


if __name__ == "__main__":
    unittest.main()
