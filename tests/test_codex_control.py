from __future__ import annotations

import hashlib
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant import codex_control as control
from engineering_assistant.validation import ValidationFailure


class Response(io.BytesIO):
    def __init__(self, payload, url):
        super().__init__(payload)
        self.url = url
        self.headers = {"Content-Length": str(len(payload))}

    def geturl(self):
        return self.url


class CodexControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.data = self.root / "私有 data"
        self.home = self.root / "Codex home"
        self.home.mkdir()

    def archive(self, entries=None):
        entries = entries or [("codex-package.json", b"{}"), ("bin/codex", b"native fixture"),
                              ("bin/codex-code-mode-host", b"host"), ("codex-path/rg", b"rg")]
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for name, payload in entries:
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                member.mode = 0o755
                archive.addfile(member, io.BytesIO(payload))
        return output.getvalue()

    def pin(self, payload):
        return {"target_triple": "aarch64-apple-darwin",
                "url": "https://releases.openai.com/codex/releases/0.159.2/codex-package-aarch64-apple-darwin.tar.gz",
                "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    @contextmanager
    def preparation(self, payload, pin=None):
        download = mock.Mock(side_effect=lambda request, **kwargs: Response(payload, request.full_url))
        probe = mock.Mock()
        with mock.patch.multiple(control, host_target=mock.Mock(return_value="macos-arm64"),
                _candidates=mock.Mock(return_value=[]), _pin=mock.Mock(return_value=pin or self.pin(payload)),
                _probe_cli=probe, urlopen=download):
            yield {"urlopen": download, "_probe_cli": probe}

    def test_pins_cover_only_the_three_supported_native_targets(self):
        pins = json.loads((ROOT / "config/codex-control.json").read_text(encoding="utf-8"))
        self.assertEqual("0.159.2", pins["version"])
        self.assertEqual({"macos-arm64", "macos-x64", "windows-x64"}, set(pins["targets"]))
        for target in pins["targets"]:
            self.assertEqual(pins["targets"][target], control._pin(target))

    def test_explicit_compatible_cli_does_not_prepare_or_mutate_path(self):
        executable = self.root / "codex"
        executable.write_bytes(b"fixture")
        before = dict(os.environ)
        with mock.patch.object(control, "_probe_cli") as probe, mock.patch.object(control, "urlopen") as download:
            self.assertEqual(executable, control.resolve_codex_control(self.data, self.home, explicit=executable))
        probe.assert_called_once_with(executable, self.home, control.host_target())
        download.assert_not_called()
        self.assertFalse(self.data.exists())
        self.assertEqual(before, dict(os.environ))

    def test_explicit_incompatible_cli_is_not_silently_replaced(self):
        executable = self.root / "codex"
        executable.write_bytes(b"fixture")
        with mock.patch.object(control, "_probe_cli", side_effect=ValidationFailure("incompatible")), \
             mock.patch.object(control, "urlopen") as download:
            with self.assertRaises(ValidationFailure):
                control.resolve_codex_control(self.data, self.home, explicit=executable)
        download.assert_not_called()
        self.assertFalse(self.data.exists())

    def test_windows_official_standalone_layout_is_discovered_without_path(self):
        executable = self.home / "packages/standalone/current/bin/codex.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"fixture")
        with mock.patch.object(control, "host_target", return_value="windows-x64"), \
             mock.patch.object(control.shutil, "which", return_value=None), \
             mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local")}, clear=True), \
             mock.patch.object(control, "_probe_cli") as probe, mock.patch.object(control, "urlopen") as download:
            self.assertEqual(executable, control.resolve_codex_control(self.data, self.home))
        probe.assert_called_once_with(executable, self.home, "windows-x64")
        download.assert_not_called()

    def test_probe_verifies_version_commands_json_and_the_same_home(self):
        from engineering_assistant import installation
        executable = self.root / "codex"
        executable.write_bytes(b"fixture")
        calls = []
        def protocol(command, **kwargs):
            calls.append((command, kwargs))
            if command[1:] == ["--version"]:
                return b"codex-cli 0.159.2\n"
            if command[-1] == "--help":
                return b"Usage: add remove list marketplace upgrade --json --available --marketplace"
            return b'{"installed":[],"available":[],"marketplaces":[]}'
        with mock.patch.object(control, "_binary_target", return_value="macos-arm64"), \
             mock.patch.object(installation, "_protocol_run", side_effect=protocol):
            control._probe_cli(executable, self.home, "macos-arm64")
        self.assertGreaterEqual(len(calls), 7)
        self.assertTrue(all(kwargs["environment"]["CODEX_HOME"] == str(self.home) for _, kwargs in calls))
        self.assertTrue(all(kwargs["timeout"] <= 15 for _, kwargs in calls))

    def test_probe_rejects_newer_unqualified_version_and_unsafe_json(self):
        from engineering_assistant import installation
        executable = self.root / "codex"
        executable.write_bytes(b"fixture")
        for result in (b"codex-cli 0.160.0", b"codex-cli 0.159.2"):
            def protocol(command, **kwargs):
                return result if command[1:] == ["--version"] else b"{}"
            with mock.patch.object(control, "_binary_target", return_value="macos-arm64"), \
                 mock.patch.object(installation, "_protocol_run", side_effect=protocol):
                with self.assertRaises(ValidationFailure):
                    control._probe_cli(executable, self.home, "macos-arm64")

    def test_probe_requires_marketplace_upgrade_and_remove(self):
        from engineering_assistant import installation
        executable = self.root / "codex"
        executable.write_bytes(b"fixture")
        for missing in ("upgrade", "remove"):
            def protocol(command, **kwargs):
                if command[1:] == ["--version"]:
                    return b"codex-cli 0.159.2"
                if command[1:] == ["plugin", "marketplace", "--help"]:
                    return ("add list " + ("remove" if missing == "upgrade" else "upgrade")).encode()
                if command[-1] == "--help":
                    return b"Usage: add remove list marketplace upgrade --json --available --marketplace"
                return b'{"installed":[],"marketplaces":[]}'
            with mock.patch.object(control, "_binary_target", return_value="macos-arm64"), \
                 mock.patch.object(installation, "_protocol_run", side_effect=protocol):
                with self.assertRaises(ValidationFailure):
                    control._probe_cli(executable, self.home, "macos-arm64")

    def test_download_and_atomic_cache_reuse_verify_every_file(self):
        payload = self.archive()
        with self.preparation(payload) as patched:
            executable = control.resolve_codex_control(self.data, self.home)
            self.assertEqual(self.data / "tools/codex/0.159.2/macos-arm64/bin/codex", executable)
            self.assertEqual(executable, control.resolve_codex_control(self.data, self.home))
            self.assertEqual(1, patched["urlopen"].call_count)
            executable.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValidationFailure, "integrity"):
                control.resolve_codex_control(self.data, self.home)
            self.assertEqual(1, patched["urlopen"].call_count)

    def test_wrong_download_hash_size_and_redirect_never_publish(self):
        payload = self.archive()
        for kind in ("digest", "size", "redirect"):
            data = self.root / kind
            pin = self.pin(payload)
            if kind == "digest":
                pin["sha256"] = "0" * 64
            elif kind == "size":
                pin["size_bytes"] -= 1
            with self.preparation(payload, pin) as patched:
                if kind == "redirect":
                    patched["urlopen"].side_effect = lambda *args, **kwargs: Response(payload, "https://other.invalid/archive")
                with self.assertRaises(ValidationFailure):
                    control.resolve_codex_control(data, self.home)
            self.assertFalse((data / "tools/codex/0.159.2/macos-arm64").exists())

    def test_archive_traversal_links_duplicates_and_devices_fail_closed(self):
        for name, kind in (("../outside", tarfile.REGTYPE), ("/outside", tarfile.REGTYPE),
                           ("bin/codex:ads", tarfile.REGTYPE), ("bin/CON", tarfile.REGTYPE),
                           ("bin/link", tarfile.SYMTYPE), ("bin/fifo", tarfile.FIFOTYPE)):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode="w:gz") as archive:
                member = tarfile.TarInfo(name)
                member.type = kind
                member.linkname = "../../outside"
                archive.addfile(member)
            payload = output.getvalue()
            with self.subTest(name=name), self.preparation(payload):
                with self.assertRaises(ValidationFailure):
                    control.resolve_codex_control(self.data, self.home)
            self.assertFalse((self.root / "outside").exists())
        payload = self.archive([("bin/codex", b"a"), ("bin/codex", b"b")])
        with self.preparation(payload), self.assertRaises(ValidationFailure):
            control.resolve_codex_control(self.data, self.home)

    def test_incomplete_or_unqualified_archive_is_never_selected(self):
        payload = self.archive([("bin/codex", b"native fixture")])
        with self.preparation(payload), self.assertRaises(ValidationFailure):
            control.resolve_codex_control(self.data, self.home)
        self.assertFalse((self.data / "tools/codex/0.159.2/macos-arm64").exists())

    def test_download_overflow_and_entry_budget_fail_before_publication(self):
        payload = self.archive()
        with self.preparation(payload), mock.patch.object(control, "MAX_ENTRIES", 1), self.assertRaises(ValidationFailure):
            control.resolve_codex_control(self.data, self.home)
        self.assertFalse((self.data / "tools/codex/0.159.2/macos-arm64").exists())

    def test_readonly_missing_cli_never_creates_data_or_downloads(self):
        with mock.patch.object(control, "_candidates", return_value=[]), mock.patch.object(control, "urlopen") as download:
            with self.assertRaisesRegex(ValidationFailure, "install.*repair"):
                control.resolve_codex_control(self.data, self.home, allow_download=False)
        download.assert_not_called()
        self.assertFalse(self.data.exists())

    def test_readonly_reuses_verified_cache_without_creating_a_lock(self):
        payload = self.archive()
        with self.preparation(payload) as patched:
            executable = control.resolve_codex_control(self.data, self.home)
            before = sorted(str(path.relative_to(self.data)) for path in self.data.rglob("*"))
            with mock.patch.object(control.ArtifactIO, "transaction", side_effect=AssertionError("readonly lock write")):
                self.assertEqual(executable, control.resolve_codex_control(self.data, self.home, allow_download=False))
            self.assertEqual(before, sorted(str(path.relative_to(self.data)) for path in self.data.rglob("*")))
            self.assertEqual(1, patched["urlopen"].call_count)

    def test_unqualified_complete_archive_is_not_published(self):
        payload = self.archive()
        with self.preparation(payload) as patched:
            patched["_probe_cli"].side_effect = ValidationFailure("wrong contract")
            with self.assertRaises(ValidationFailure):
                control.resolve_codex_control(self.data, self.home)
        self.assertFalse((self.data / "tools/codex/0.159.2/macos-arm64").exists())

    def test_json_query_contract_and_native_failure_do_not_expose_output(self):
        from engineering_assistant import installation
        executable = self.root / "codex"
        executable.write_bytes(b"fixture")
        def protocol(command, **kwargs):
            if command[1:] == ["--version"]:
                return b"codex-cli 0.159.2"
            if command[-1] == "--help":
                return b"Usage: add remove list marketplace upgrade --json --available --marketplace"
            return b'{"installed":"sensitive fixture", "marketplaces":[]}'
        for runner in (mock.Mock(side_effect=protocol), mock.Mock(side_effect=ValidationFailure("private failure fixture"))):
            with mock.patch.object(control, "_binary_target", return_value="macos-arm64"), \
                 mock.patch.object(installation, "_protocol_run", runner):
                with self.assertRaises(ValidationFailure) as failure:
                    control._probe_cli(executable, self.home, "macos-arm64")
            self.assertNotIn("fixture", str(failure.exception))

    def test_concurrent_preparation_downloads_and_commits_once(self):
        payload = self.archive()
        with self.preparation(payload) as patched, ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(control.resolve_codex_control, self.data, self.home) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
            self.assertEqual(results[0], results[1])
            self.assertEqual(1, patched["urlopen"].call_count)

    def test_download_body_overflow_without_content_length_is_rejected(self):
        payload = self.archive()
        with self.preparation(payload) as patched:
            def response(request, **kwargs):
                result = Response(payload + b"extra", request.full_url)
                result.headers = {}
                return result
            patched["urlopen"].side_effect = response
            with self.assertRaises(ValidationFailure):
                control.resolve_codex_control(self.data, self.home)
        self.assertFalse((self.data / "tools/codex/0.159.2/macos-arm64").exists())

    def test_replaced_parent_is_rejected_and_replacement_is_preserved(self):
        payload = self.archive()
        replacement = self.data / "tools/codex/0.159.2"
        marker = replacement / "unrelated-marker"
        def replace_parent(executable, home, target):
            replacement.rename(replacement.with_name("original-version"))
            replacement.mkdir()
            marker.write_text("preserve", encoding="utf-8")
        with self.preparation(payload) as patched:
            patched["_probe_cli"].side_effect = replace_parent
            with self.assertRaises(ValidationFailure):
                control.resolve_codex_control(self.data, self.home)
            self.assertEqual(1, patched["_probe_cli"].call_count)
        self.assertEqual("preserve", marker.read_text(encoding="utf-8"))
        self.assertFalse((replacement / "macos-arm64").exists())

    def test_file_and_total_decompressed_limits_reject_before_native_probe(self):
        payload = self.archive()
        for limit in ("MAX_FILE_BYTES", "MAX_TOTAL_BYTES"):
            with self.preparation(payload) as patched, mock.patch.object(control, limit, 1):
                with self.assertRaises(ValidationFailure):
                    control.resolve_codex_control(self.data, self.home)
                patched["_probe_cli"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
