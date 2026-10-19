from __future__ import annotations

import io
import json
import hashlib
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CLEAN_LEGACY = {"legacy_installation_detected": False, "legacy_check_complete": True,
                "legacy_scope": [], "legacy_confirmed": [], "legacy_unknown": [], "legacy_manual_steps": []}


class InternalEntryTests(unittest.TestCase):
    def test_codex_install_without_source_uses_the_internal_distribution(self):
        from engineering_assistant.installer.setup_cli import main
        with mock.patch("engineering_assistant.installer.setup_cli.install_internal_codex", create=True,
                        return_value={"status": "ready", "ready": True}) as install, \
                redirect_stdout(io.StringIO()) as output:
            code = main(["install", "--agent", "codex", "--json"])
        self.assertEqual(0, code, output.getvalue())
        install.assert_called_once()
        self.assertEqual("ready", json.loads(output.getvalue())["status"])

    def test_default_output_explains_pending_hook_trust_in_chinese(self):
        from engineering_assistant.installer.setup_cli import main
        result = {"status": "needs_trust", "ready": False, "runtime_ready": True}
        with mock.patch("engineering_assistant.installer.setup_cli.doctor", return_value=result), \
                mock.patch("engineering_assistant.installer.setup_cli.inspect_legacy_codex", return_value=CLEAN_LEGACY), \
                redirect_stdout(io.StringIO()) as output:
            code = main(["doctor", "--agent", "codex"])
        self.assertEqual(2, code)
        self.assertIn("信任", output.getvalue())
        self.assertNotIn('"status"', output.getvalue())

    def test_doctor_without_control_cli_reports_preparation_without_writes(self):
        from engineering_assistant.installer.setup_cli import main
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            data = root / "not-created"
            with mock.patch("engineering_assistant.installer.installation.host_target", return_value="macos-arm64"), \
                    mock.patch("engineering_assistant.platforms.codex_control._candidates", return_value=[]), \
                    mock.patch.dict("os.environ", {"CODEX_CLI": ""}), redirect_stdout(io.StringIO()) as output:
                code = main(["doctor", "--agent", "codex", "--agent-home", str(root),
                             "--data-home", str(data), "--json"])
            result = json.loads(output.getvalue())
            self.assertEqual(2, code)
            self.assertEqual("needs_preparation", result["status"])
            self.assertIn("install", result["reason"])
            self.assertFalse(data.exists())


class ManagedInstallationTests(unittest.TestCase):
    """Real artifact transactions with a controlled native CLI boundary."""

    def setUp(self):
        from engineering_assistant.installer import internal_installation as managed
        self.managed = managed
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home, self.data = self.root / "Codex 中文", self.root / "Runtime 数据"
        self.home.mkdir()
        self.selected = None
        self.registered = False
        self.prepare_calls = 0
        self.selection_calls = 0
        self.fail_candidate = False
        self.fail_restore = False
        self.prepare_failure = False
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        runtime = managed.runtime
        self.stack.enter_context(mock.patch.object(managed, "preflight_legacy_codex", return_value=CLEAN_LEGACY))
        self.stack.enter_context(mock.patch.object(runtime, "host_target", return_value="macos-arm64"))
        self.stack.enter_context(mock.patch.object(runtime, "_installed_identity", side_effect=lambda *_a: self.selected))
        self.stack.enter_context(mock.patch.object(runtime, "_marketplace_entry", side_effect=lambda *_a:
            {"name": managed.MARKETPLACE} if self.registered else None))
        self.stack.enter_context(mock.patch.object(runtime, "_verified_package", side_effect=self.package))
        self.stack.enter_context(mock.patch.object(runtime, "prepare_runtime", side_effect=self.prepare))
        self.stack.enter_context(mock.patch.object(runtime, "_publish_default_binding"))
        self.stack.enter_context(mock.patch.object(runtime, "doctor", return_value={"status": "needs_trust", "ready": False}))
        self.stack.enter_context(mock.patch.object(runtime, "_verify_selection", side_effect=self.verify_selection))
        self.stack.enter_context(mock.patch.object(managed, "_select_market", side_effect=self.select_market))
        self.release_mock = self.stack.enter_context(mock.patch.object(managed, "acquire_internal_release"))
        self.release("2.3.0.0-rc.2")

    def package(self, path, *_a):
        return json.loads((Path(path) / "test-package.json").read_text())

    def release(self, version):
        from engineering_assistant.runtime.artifact_io import ArtifactIO
        from engineering_assistant.installer.internal_distribution import _tree_digest
        source = self.root / version
        package = source / "plugins/engineering-assistant"
        package.mkdir(parents=True)
        digest = "sha256:" + hashlib.sha256(version.encode()).hexdigest()
        manifest = {"canonical_version": version, "platform": "codex", "target": "macos-arm64", "payload_digest": digest}
        (package / "test-package.json").write_text(json.dumps(manifest))
        with_io = ArtifactIO(source, ".")
        try:
            tree_hash = _tree_digest(with_io)
        finally:
            with_io.close()
        self.release_mock.return_value = {"source": source, "source_commit": "a" * 40,
            "release_tag": "internal/codex/" + version, "index": {"canonical_version": version},
            "entry": {"package_payload_digest": digest, "marketplace": {"tree_sha256": tree_hash}}}

    def prepare(self, *_a, **_kw):
        self.prepare_calls += 1
        if self.prepare_failure:
            raise RuntimeError("controlled preparation failure")
        return {"agent": "codex"}

    def select_market(self, home, source):
        self.selection_calls += 1
        manifest = self.package(source / "plugins/engineering-assistant")
        cache = self.home / "cache" / manifest["canonical_version"]
        if cache.exists():
            shutil.rmtree(cache)
        shutil.copytree(source / "plugins/engineering-assistant", cache)
        self.selected = {"package": cache, "version": manifest["canonical_version"],
                         "marketplace": self.managed.MARKETPLACE, "enabled": True}
        self.registered = True
        if (self.fail_candidate and manifest["canonical_version"].endswith("rc.3")) or self.fail_restore:
            raise RuntimeError("native side effect followed by failure")

    def verify_selection(self, _agent, _home, _market, expected, **_kw):
        actual = self.package(self.selected["package"])
        return {"status": "needs_trust" if actual["payload_digest"] == expected["payload_digest"] else "failed",
                "ready": False, "marketplace": self.managed.MARKETPLACE}

    def install(self, update=False):
        return self.managed.install_internal_codex(home=self.home, data_home=self.data, update=update)

    def state(self):
        return self.managed._read_state(self.data, self.home)

    def test_install_commits_one_preparation_and_repeat_reuses_selected_version(self):
        first = self.install()
        self.assertEqual("needs_trust", first["status"])
        self.assertEqual(1, self.prepare_calls)
        self.assertEqual("active", self.state()["phase"])
        repeated = self.install()
        self.assertTrue(repeated["reused"])
        for key in ("source_commit", "release_tag", "marketplace"):
            self.assertEqual(first[key], repeated[key])
        self.assertEqual(1, self.selection_calls)

    def test_old_version_requires_update_and_does_not_change_selection(self):
        self.install()
        before = self.state()
        self.release("2.3.0.0-rc.3")
        self.assertEqual("needs_update", self.install()["status"])
        self.assertEqual(before, self.state())
        self.assertTrue(self.selected["version"].endswith("rc.2"))

    def test_preparation_failure_preserves_active_tree_record_and_selection(self):
        self.install()
        before = self.state()
        self.release("2.3.0.0-rc.3")
        self.prepare_failure = True
        with self.assertRaisesRegex(RuntimeError, "preparation"):
            self.install(update=True)
        self.assertEqual(before, self.state())
        self.assertTrue(self.selected["version"].endswith("rc.2"))
        self.assertEqual(1, self.selection_calls)

    def test_update_failure_after_native_side_effect_restores_previous_package(self):
        self.install()
        self.release("2.3.0.0-rc.3")
        self.fail_candidate = True
        result = self.install(update=True)
        self.assertEqual("previous_selection_restored", result["native_state"])
        self.assertFalse(result["recovery_required"])
        self.assertTrue(self.selected["version"].endswith("rc.2"))
        self.assertTrue(self.state()["current"]["canonical_version"].endswith("rc.2"))
        self.assertEqual("active", self.state()["phase"])

    def test_failed_compensation_is_repairable_without_network_or_missing_backup(self):
        self.install()
        self.release("2.3.0.0-rc.3")
        self.fail_candidate = True
        self.fail_restore = True
        result = self.install(update=True)
        self.assertTrue(result["recovery_required"])
        self.assertEqual("switching", self.state()["phase"])
        self.fail_candidate = self.fail_restore = False
        self.release_mock.side_effect = AssertionError("repair must not fetch Git")
        repaired = self.managed.repair_internal_codex(home=self.home, data_home=self.data)
        self.assertEqual("needs_trust", repaired["status"])
        self.assertEqual("active", self.state()["phase"])
        self.assertTrue(self.selected["version"].endswith("rc.2"))

    def test_other_marketplace_is_rejected_before_fetch_or_preparation(self):
        self.selected = {"marketplace": "personal"}
        with self.assertRaisesRegex(Exception, "其他市场"):
            self.install()
        self.release_mock.assert_not_called()
        self.assertEqual(0, self.prepare_calls)

    def test_unmanaged_same_name_marketplace_is_never_overwritten(self):
        self.registered = True
        with self.assertRaisesRegex(Exception, "同名市场"):
            self.install()
        self.release_mock.assert_not_called()
        self.assertEqual(0, self.selection_calls)


if __name__ == "__main__":
    unittest.main()
