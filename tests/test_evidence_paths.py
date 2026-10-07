from __future__ import annotations

import hashlib
import ntpath
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.evidence import EvidenceStore  # noqa: E402
from engineering_assistant.state_store import StateStore  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class _WindowsLexicalPath(PureWindowsPath):
    """Exercise Windows parsing on any host; this is not native FS evidence."""

    def resolve(self):
        return type(self)(ntpath.normpath(str(self)))


class EvidencePathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name).resolve()
        self.store = EvidenceStore(StateStore(self.project, ROOT / "schemas"))

    def register(self, uri: str, evidence_id: str = "path-evidence"):
        return self.store.register(
            "path-run", evidence_id=evidence_id, kind="source", uri=uri,
            producer="path-test", scope="repository",
        )

    def test_native_absolute_relative_and_file_uri_are_observed_and_hashed(self) -> None:
        source = self.project / "facts with space.txt"
        source.write_bytes(b"observed project fact")
        expected = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
        for index, uri in enumerate((str(source), source.name, source.as_uri())):
            with self.subTest(uri=uri):
                evidence = self.register(uri, f"local-{index}")
                self.assertEqual("runtime_observed", evidence.provenance)
                self.assertEqual(expected, evidence.digest)
                self.assertEqual(evidence, self.store.get("path-run", evidence.id))
        source.write_bytes(b"changed project fact")
        with self.assertRaisesRegex(ValidationFailure, "digest does not match"):
            self.store.get("path-run", "local-0")

    def test_external_urls_remain_agent_reported(self) -> None:
        evidence = self.register("https://example.com/C:/project/facts.txt")
        self.assertEqual("agent_reported", evidence.provenance)
        self.assertIsNone(evidence.digest)
        with self.assertRaisesRegex(ValidationFailure, "provenance must be assigned by the runtime"):
            self.store.save("path-run", replace(evidence, id="forged", provenance="runtime_observed"))

    def test_missing_and_escaping_local_paths_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationFailure, "local file does not exist"):
            self.register("missing.txt")
        with tempfile.TemporaryDirectory() as outside:
            source = Path(outside).resolve() / "outside.txt"
            source.write_bytes(b"outside project")
            for uri in (str(source), source.as_uri(), "../outside.txt"):
                with self.subTest(uri=uri), self.assertRaisesRegex(ValidationFailure, "inside project_root"):
                    self.register(uri)

    def test_windows_drive_is_local_before_url_scheme_parsing(self) -> None:
        project = _WindowsLexicalPath(r"C:\project")
        store = EvidenceStore(SimpleNamespace(project_root=project))
        with patch("engineering_assistant.evidence.Path", _WindowsLexicalPath):
            for uri in (r"C:\project\facts.txt", "C:/project/facts.txt"):
                with self.subTest(uri=uri):
                    self.assertEqual(project / "facts.txt", store._local_path(uri))
            for uri in (r"C:\project\..\outside.txt", r"C:\project-other\facts.txt", r"D:\project\facts.txt"):
                with self.subTest(uri=uri), self.assertRaisesRegex(ValidationFailure, "inside project_root"):
                    store._local_path(uri)

    def test_windows_file_uri_removes_only_the_drive_prefix_slash(self) -> None:
        project = _WindowsLexicalPath(r"C:\project")
        store = EvidenceStore(SimpleNamespace(project_root=project))
        with patch("engineering_assistant.evidence.Path", _WindowsLexicalPath):
            for uri in ("file:///C:/project/facts%20with%20space.txt", "file://localhost/C:/project/facts%20with%20space.txt"):
                with self.subTest(uri=uri):
                    self.assertEqual(project / "facts with space.txt", store._local_path(uri))
            with self.assertRaisesRegex(ValidationFailure, "inside project_root"):
                store._local_path("file:///C:/project/%2e%2e/outside.txt")

    def test_unc_device_drive_relative_and_nonlocal_file_uris_are_rejected(self) -> None:
        for uri in (
            r"\\server\share\facts.txt", "//server/share/facts.txt",
            r"\\?\C:\project\facts.txt", r"\\.\C:\project\facts.txt",
            "C:facts.txt", "C:", "C:../facts.txt", "file:///C:facts.txt",
            "file://server/share/facts.txt",
        ):
            with self.subTest(uri=uri), self.assertRaises(ValidationFailure):
                self.store._local_path(uri)


if __name__ == "__main__":
    unittest.main()
