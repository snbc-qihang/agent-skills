from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.installer import cursor_installation as cursor
from engineering_assistant.tools.compiler import build_package
from engineering_assistant.runtime.validation import ValidationFailure


class CursorInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home, self.data = self.root / "Cursor 中文 配置", self.root / "共享 数据"
        self.home.mkdir()
        self.package = self.root / "candidate"
        build_package(ROOT, "cursor", self.package)
        self.prepare = mock.patch.object(cursor.runtime, "prepare_runtime", return_value={"status": "prepared"}).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(cursor, "_result", return_value={"status": "needs_preparation", "ready": False,
            "reason": "requires_native_activation"}).start()

    def install(self, **extra):
        return cursor.install_cursor(source=str(self.package), home=self.home, data=self.data, **extra)

    def test_native_entry_registration_reuse_and_uninstall_preserve_shared_data_and_config(self):
        config = self.home / "mcp.json"
        config.write_bytes(b'{"unrelated":true}')
        self.data.mkdir()
        marker = self.data / "other-agent-runtime"
        marker.write_bytes(b"retained")
        self.assertEqual("needs_preparation", self.install()["status"])
        self.assertTrue(self.install()["reused"])
        self.assertFalse(cursor.cursor_selection(self.home)["enabled"])
        self.assertEqual("uninstalled", cursor.uninstall_cursor(self.home)["status"])
        self.assertIsNone(cursor.cursor_selection(self.home))
        self.assertEqual(b'{"unrelated":true}', config.read_bytes())
        self.assertEqual(b"retained", marker.read_bytes())
        self.assertTrue(list((self.home / "plugins/.engineering-assistant-staging").glob("uninstalled-*")))

    def test_existing_unmanaged_entry_is_never_taken_over(self):
        entry = self.home / "plugins/local/engineering-assistant"
        entry.mkdir(parents=True)
        marker = entry / "keep"
        marker.write_bytes(b"keep")
        with self.assertRaises(ValidationFailure):
            self.install()
        self.assertEqual(b"keep", marker.read_bytes())
        self.prepare.assert_not_called()

    def test_preparation_failure_keeps_previous_native_entry(self):
        self.install()
        entry = self.home / "plugins/local/engineering-assistant/package-manifest.json"
        previous = entry.read_bytes()
        self.prepare.side_effect = ValidationFailure("network failure")
        with self.assertRaisesRegex(ValidationFailure, "network failure"):
            self.install(update=True)
        self.assertEqual(previous, entry.read_bytes())

    def test_selected_entry_tampering_is_not_reported_as_ready_or_removed(self):
        self.install()
        entry = self.home / "plugins/local/engineering-assistant"
        marker = entry / "mcp.json"
        marker.write_bytes(b"changed")
        for check in (lambda: cursor.cursor_selection(self.home), lambda: cursor.uninstall_cursor(self.home)):
            with self.assertRaises(ValidationFailure):
                check()
        self.assertEqual(b"changed", marker.read_bytes())

    def changed_candidate(self):
        from test_compiler_adapters import reseal_package_fixture
        path = self.package / ".cursor-plugin/plugin.json"
        manifest = json.loads(path.read_text())
        manifest["description"] += " 新候选"
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        reseal_package_fixture(self.package)

    def test_failed_update_switch_restores_the_previous_entry(self):
        self.install()
        previous = cursor.cursor_selection(self.home)["package"] / "package-manifest.json"
        expected = previous.read_bytes()
        self.changed_candidate()
        original = cursor.artifact_fs.rename
        failed = False
        def fail_once(source, destination, **kwargs):
            nonlocal failed
            if destination == "engineering-assistant" and not failed:
                failed = True
                raise OSError("interrupted switch")
            return original(source, destination, **kwargs)
        with mock.patch.object(cursor.artifact_fs, "rename", side_effect=fail_once):
            result = self.install(update=True)
        self.assertEqual("previous_entry_restored", result["native_state"])
        self.assertFalse(result["recovery_required"])
        self.assertEqual(expected, previous.read_bytes())
        self.assertIsNotNone(cursor.cursor_selection(self.home))

    def test_committed_state_write_error_does_not_diverge_the_selected_entry(self):
        self.install()
        self.changed_candidate()
        original = cursor._save
        failed = False
        def fail_after_commit(control, value):
            nonlocal failed
            original(control, value)
            if value["phase"] == "active" and not failed:
                failed = True
                raise OSError("commit acknowledgement lost")
        with mock.patch.object(cursor, "_save", side_effect=fail_after_commit):
            result = self.install(update=True)
        self.assertEqual("needs_preparation", result["status"])
        selected = cursor.cursor_selection(self.home)["package"]
        self.assertEqual((self.package / "package-manifest.json").read_bytes(), (selected / "package-manifest.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
