from __future__ import annotations

import io
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.installer import legacy_installation as legacy
from engineering_assistant.runtime.validation import ValidationFailure


class LegacyInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home, self.data = self.root / "Codex 中文", self.root / "Runtime 数据"
        self.home.mkdir()
        self.installed, self.markets = [], []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(legacy, "_default_data_home", return_value=self.root / "default-data"))
        self.query = self.stack.enter_context(mock.patch.object(legacy.runtime, "_native_query", side_effect=self.native))

    def native(self, agent, arguments, home):
        return {"marketplaces": self.markets} if "marketplace" in arguments else {"installed": self.installed}

    def package(self, path, version="2.2.0.0-rc.1"):
        path.mkdir(parents=True)
        (path / ".codex-plugin").mkdir()
        (path / ".codex-plugin/plugin.json").write_text(json.dumps({"name": "engineering-assistant", "version": version}))
        (path / "package-manifest.json").write_text(json.dumps({"canonical_version": version, "platform": "codex"}))
        return path

    def inspect(self):
        return legacy.inspect_legacy_codex(self.home, self.data)

    def test_clean_inspection_is_readonly_and_never_prepares_control_tools(self):
        with mock.patch.object(legacy.runtime, "_storage", side_effect=AssertionError("write")), \
                mock.patch("engineering_assistant.platforms.codex_control.urlopen", side_effect=AssertionError("download")):
            result = self.inspect()
        self.assertFalse(result["legacy_installation_detected"])
        self.assertTrue(result["legacy_check_complete"])
        self.assertFalse(self.data.exists())

    def test_all_registered_old_sources_are_reported_with_exact_remove_arguments(self):
        for market in ("personal", "team"):
            self.installed.append({"name": "engineering-assistant", "installed": True,
                                   "marketplaceName": market, "version": "2.2.0-rc.1", "enabled": True})
            self.package(self.home / "plugins/cache" / market / "engineering-assistant/2.2.0-rc.1")
        result = self.inspect()
        self.assertTrue(result["legacy_installation_detected"])
        commands = [item.get("command") for item in result["legacy_manual_steps"]]
        for market in ("personal", "team"):
            self.assertIn(["codex", "plugin", "remove", "engineering-assistant@" + market, "--json"], commands)
        self.assertNotIn(["codex", "plugin", "marketplace", "remove", "personal"], commands)

    def test_orphan_cache_publish_backups_and_codex_runtime_are_bounded_and_attributed(self):
        cache = self.package(self.home / "plugins/cache/personal/engineering-assistant/2.2.0-rc.1")
        backup = self.package(self.home.parent / "plugins/.engineering-assistant.backup-old")
        self.data.mkdir()
        bindings = self.data / "bindings/codex"
        bindings.mkdir(parents=True)
        (bindings / "old.json").write_text(json.dumps({"agent": "codex", "canonical_version": "2.2.0.0-rc.1", "environment_key": "old"}))
        environment = self.data / "environments/old"
        environment.mkdir(parents=True)
        (environment / "runtime-environment.json").write_text(json.dumps({"agent": "codex", "canonical_version": "2.2.0.0-rc.1"}))
        unrelated = self.root / "project/.run-artifacts/engineering-assistant"
        unrelated.mkdir(parents=True)
        (unrelated / "secret.json").write_text("private fixture")
        result = self.inspect()
        paths = {item["path"] for item in result["legacy_confirmed"]}
        self.assertTrue({str(cache), str(backup), str(environment), str(bindings / "old.json")} <= paths)
        self.assertNotIn(str(unrelated), json.dumps(result))
        self.assertEqual("private fixture", (unrelated / "secret.json").read_text())

    def test_current_one_x_backups_and_shared_python_are_not_legacy(self):
        self.package(self.home.parent / "plugins/.engineering-assistant.backup-new", "1.0.0.1")
        self.package(self.home / "plugins/cache/engineering-assistant/engineering-assistant/1.0.0+build.1", "1.0.0.1")
        shared = self.data / "python/shared"
        shared.mkdir(parents=True)
        (shared / "runtime-python.json").write_text("not scanned")
        result = self.inspect()
        self.assertFalse(result["legacy_installation_detected"])
        self.assertTrue(result["legacy_check_complete"])
        self.assertNotIn(str(shared), json.dumps(result))

    def test_runtime_created_binding_lock_is_not_an_unknown_installation(self):
        storage = legacy.runtime._storage(self.data)
        try:
            legacy.runtime._publish_versioned_binding(storage, {
                "agent": "codex", "canonical_version": "1.0.0.1", "environment_key": "current",
            })
        finally:
            storage.close()
        lock = self.data / "bindings/codex/.artifact.lock"
        self.assertTrue(lock.is_file())
        before = {p.relative_to(self.data): p.read_bytes() for p in self.data.rglob("*") if p.is_file()}
        result = self.inspect()
        self.assertFalse(result["legacy_installation_detected"])
        self.assertTrue(result["legacy_check_complete"], result["legacy_unknown"])
        self.assertEqual(before, {p.relative_to(self.data): p.read_bytes() for p in self.data.rglob("*") if p.is_file()})

    def test_binding_lock_with_content_directory_or_symlink_remains_unknown(self):
        lock = self.data / "bindings/codex/.artifact.lock"
        lock.parent.mkdir(parents=True)
        secret = self.root / "private-fixture"
        secret.write_text("must not be read")
        for kind in ("content", "single_byte", "directory", "symlink"):
            with self.subTest(kind=kind):
                if kind == "content":
                    lock.write_text("unexpected lock content")
                elif kind == "single_byte":
                    lock.write_bytes(b"x")
                elif kind == "directory":
                    lock.mkdir()
                else:
                    lock.symlink_to(secret)
                result = self.inspect()
                self.assertFalse(result["legacy_check_complete"])
                self.assertNotIn("must not be read", json.dumps(result))
                self.assertEqual("must not be read", secret.read_text())
                if kind == "directory":
                    lock.rmdir()
                else:
                    lock.unlink()

    def test_windows_byte_range_binding_lock_is_recognized_without_writes(self):
        lock = self.data / "bindings/codex/.artifact.lock"
        lock.parent.mkdir(parents=True)
        with lock.open("wb") as stream:
            legacy.ArtifactIO._prepare_windows_lock(stream.fileno())
        self.assertEqual(b"0", lock.read_bytes())
        result = self.inspect()
        self.assertTrue(result["legacy_check_complete"], result["legacy_unknown"])
        self.assertEqual(b"0", lock.read_bytes())

    def test_missing_cli_still_reports_disk_findings_and_incomplete_check(self):
        backup = self.package(self.home.parent / "plugins/.engineering-assistant.backup-old")
        self.query.side_effect = ValidationFailure("sensitive native failure fixture")
        result = self.inspect()
        self.assertTrue(result["legacy_installation_detected"])
        self.assertFalse(result["legacy_check_complete"])
        self.assertIn(str(backup), json.dumps(result))
        self.assertNotIn("sensitive", json.dumps(result))

    def test_unknown_or_symlinked_owned_entry_is_reported_without_following_it(self):
        external = self.package(self.root / "other-project/old")
        owned = self.home / "plugins/cache/personal/engineering-assistant"
        owned.mkdir(parents=True)
        (owned / "2.2.0").symlink_to(external, target_is_directory=True)
        result = self.inspect()
        self.assertFalse(result["legacy_check_complete"])
        self.assertFalse(result["legacy_installation_detected"])
        self.assertNotIn(str(external), json.dumps(result))

    def test_first_install_blocks_before_storage_fetch_and_preparation(self):
        from engineering_assistant.installer import internal_installation as managed
        self.package(self.home.parent / "plugins/.engineering-assistant.backup-old")
        with mock.patch.object(managed.runtime, "_storage", side_effect=AssertionError("write")), \
                mock.patch.object(managed, "acquire_internal_release", side_effect=AssertionError("network")), \
                mock.patch.object(managed.runtime, "prepare_runtime", side_effect=AssertionError("prepare")):
            result = managed.install_internal_codex(home=self.home, data_home=self.data)
        self.assertEqual("needs_preparation", result["status"])
        self.assertFalse(result["ready"])
        self.assertTrue(result["legacy_installation_detected"])
        self.assertFalse(self.data.exists())

    def test_doctor_json_reports_legacy_without_executing_old_runtime(self):
        from engineering_assistant.installer.setup_cli import main
        self.package(self.home.parent / "plugins/.engineering-assistant.backup-old")
        with mock.patch("engineering_assistant.installer.setup_cli.doctor", side_effect=AssertionError("old runtime")), \
                redirect_stdout(io.StringIO()) as output:
            code = main(["doctor", "--agent", "codex", "--agent-home", str(self.home), "--data-home", str(self.data), "--json"])
        result = json.loads(output.getvalue())
        self.assertEqual(2, code)
        self.assertEqual("needs_preparation", result["status"])
        self.assertTrue(result["legacy_installation_detected"])

    def test_only_missing_cli_can_prepare_tools_then_recheck_without_installation_writes(self):
        prepared = []
        def query(agent, arguments, home):
            if not prepared:
                context = legacy.runtime._NATIVE_CONTROL.get()
                if not context["allow_download"]:
                    raise legacy.ControlNeedsPreparation("missing")
                prepared.append(True)
            return self.native(agent, arguments, home)
        self.query.side_effect = query
        with mock.patch.object(legacy.runtime, "_storage", side_effect=AssertionError("installation write")):
            result = legacy.preflight_legacy_codex(self.home, self.data)
        self.assertEqual([True], prepared)
        self.assertTrue(result["legacy_check_complete"])
        self.assertFalse(self.data.exists())

    def test_existing_old_file_or_unknown_metadata_never_prepares_tools(self):
        backup = self.package(self.home.parent / "plugins/.engineering-assistant.backup-old")
        downloads = []
        def query(*args):
            if legacy.runtime._NATIVE_CONTROL.get()["allow_download"]:
                downloads.append(True)
            raise legacy.ControlNeedsPreparation("missing")
        self.query.side_effect = query
        result = legacy.preflight_legacy_codex(self.home, self.data)
        self.assertTrue(result["legacy_installation_detected"])
        self.assertEqual([], downloads)
        self.assertIn("Codex App", json.dumps(result, ensure_ascii=False))
        (backup / "package-manifest.json").write_text("invalid private fixture")
        (backup / ".codex-plugin/plugin.json").unlink()
        result = legacy.preflight_legacy_codex(self.home, self.data)
        self.assertFalse(result["legacy_check_complete"])
        self.assertEqual([], downloads)
        self.assertNotIn("private fixture", json.dumps(result))

    def test_unrelated_files_and_other_agents_do_not_make_the_check_incomplete(self):
        cache = self.home / "plugins/cache"
        cache.mkdir(parents=True)
        (cache / ".DS_Store").write_bytes(b"unrelated")
        marker = self.data / "environments/hermes/runtime-environment.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"agent": "hermes", "canonical_version": "2.2.0.0-rc.1"}))
        result = self.inspect()
        self.assertTrue(result["legacy_check_complete"])
        self.assertFalse(result["legacy_installation_detected"])

    def test_metadata_and_directory_budgets_are_reported_as_incomplete(self):
        backup = self.package(self.home.parent / "plugins/.engineering-assistant.backup-old")
        (backup / "package-manifest.json").write_bytes(b"x" * (legacy.MAX_CONTROL_BYTES + 1))
        result = self.inspect()
        self.assertFalse(result["legacy_check_complete"])
        with mock.patch.object(legacy, "MAX_ENTRIES", 1):
            self.package(self.home.parent / "plugins/.engineering-assistant.backup-second")
            result = self.inspect()
            self.assertIn("scan_limit", {item["kind"] for item in result["legacy_unknown"]})

    def test_registered_local_source_and_dangling_entry_require_manual_review(self):
        source = self.root / "explicit-old-market"
        package = self.package(source / "plugins/engineering-assistant")
        manifest = source / ".agents/plugins/marketplace.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"plugins": [{"name": "engineering-assistant", "source": {
            "source": "local", "path": "./plugins/engineering-assistant"}}]}))
        self.markets.append({"name": "old-team", "root": str(source), "marketplaceSource": {"sourceType": "local"}})
        result = self.inspect()
        self.assertIn(str(package), {item["path"] for item in result["legacy_confirmed"]})
        import shutil
        shutil.rmtree(package)
        result = self.inspect()
        self.assertFalse(result["legacy_check_complete"])
        self.assertIn("orphan_marketplace_entry", {item["kind"] for item in result["legacy_unknown"]})
        self.assertTrue(any(item["action"] == "edit_marketplace_entry" for item in result["legacy_manual_steps"]))

    def test_default_data_bindings_are_checked_even_with_an_explicit_data_home(self):
        marker = self.root / "default-data/bindings/codex.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"agent": "codex", "canonical_version": "2.3.0.0-rc.1"}))
        result = self.inspect()
        self.assertIn(str(marker), {item["path"] for item in result["legacy_confirmed"]})

    def test_unattributed_runtime_environment_and_invalid_native_version_are_incomplete(self):
        (self.data / "environments/orphan").mkdir(parents=True)
        self.installed.append({"name": "engineering-assistant", "installed": True,
                               "marketplaceName": "personal", "version": None})
        result = self.inspect()
        self.assertFalse(result["legacy_check_complete"])
        kinds = {item["kind"] for item in result["legacy_unknown"]}
        self.assertTrue({"native_inventory", "unattributed_environment"} <= kinds)

    def test_non_object_control_json_is_unknown_without_exposing_its_content(self):
        manifest = self.home.parent / ".agents/plugins/marketplace.json"
        manifest.parent.mkdir(parents=True)
        for payload in ([], "private fixture", None):
            with self.subTest(payload=type(payload).__name__):
                manifest.write_text(json.dumps(payload))
                result = self.inspect()
                self.assertFalse(result["legacy_check_complete"])
                self.assertFalse(result["legacy_installation_detected"])
                self.assertIn("invalid_metadata", {item["kind"] for item in result["legacy_unknown"]})
                self.assertNotIn("private fixture", json.dumps(result))

    def test_contradictory_package_versions_are_unknown_instead_of_legacy(self):
        package = self.package(self.home.parent / "plugins/.engineering-assistant.backup-conflict")
        plugin = package / ".codex-plugin/plugin.json"
        for version in ("1.0.0+build.1", "2.2.0-rc.1+build.1"):
            with self.subTest(version=version):
                plugin.write_text(json.dumps({"name": "engineering-assistant", "version": version}))
                result = self.inspect()
                self.assertFalse(result["legacy_installation_detected"])
                self.assertFalse(result["legacy_check_complete"])
                self.assertIn("package_identity_conflict", {item["kind"] for item in result["legacy_unknown"]})

    def test_unregistered_unrelated_market_symlink_is_outside_plugin_scope(self):
        external = self.root / "unrelated-market"
        external.mkdir()
        cache = self.home / "plugins/cache"
        cache.mkdir(parents=True)
        (cache / "other-plugin-only").symlink_to(external, target_is_directory=True)
        result = self.inspect()
        self.assertTrue(result["legacy_check_complete"])
        self.assertFalse(result["legacy_installation_detected"])

    def test_unsafe_home_or_data_stops_before_any_native_call_or_tool_preparation(self):
        external = self.root / "unrelated-home"
        external.mkdir()
        for attribute in ("home", "data"):
            with self.subTest(attribute=attribute):
                original = getattr(self, attribute)
                link = self.root / (attribute + "-link")
                link.symlink_to(external, target_is_directory=True)
                setattr(self, attribute, link)
                self.query.side_effect = AssertionError("native must not follow an unsafe root")
                with mock.patch("engineering_assistant.platforms.codex_control.resolve_codex_control", side_effect=AssertionError("prepare")):
                    result = legacy.preflight_legacy_codex(self.home, self.data)
                self.assertFalse(result["legacy_check_complete"])
                self.assertEqual([], list(external.iterdir()))
                setattr(self, attribute, original)

    def test_known_codex_binding_requires_valid_identity_but_ignores_other_agents(self):
        marker = self.data / "bindings/codex.json"
        marker.parent.mkdir(parents=True)
        for record in ({}, {"agent": "codex", "canonical_version": None},
                       {"agent": "codex", "canonical_version": "unparseable"}):
            with self.subTest(record=record):
                marker.write_text(json.dumps(record))
                result = self.inspect()
                self.assertFalse(result["legacy_check_complete"])
                self.assertFalse(result["legacy_installation_detected"])
                self.assertIn("binding_metadata", {item["kind"] for item in result["legacy_unknown"]})
        for record in ({"agent": "hermes", "canonical_version": None},
                       {"agent": "codex", "canonical_version": "1.0.0.1"}):
            marker.write_text(json.dumps(record))
            self.assertTrue(self.inspect()["legacy_check_complete"])

    def test_selected_home_installation_state_requires_valid_current_identity(self):
        key = hashlib.sha256(str(self.home).encode()).hexdigest()
        marker = self.data / "installations/codex" / key / "state.json"
        marker.parent.mkdir(parents=True)
        for current in ({"canonical_version": None}, {"canonical_version": "unparseable"}, None):
            with self.subTest(current=current):
                marker.write_text(json.dumps({"home": str(self.home), "current": current}))
                result = self.inspect()
                self.assertFalse(result["legacy_check_complete"])
                self.assertFalse(result["legacy_installation_detected"])
                self.assertIn("installation_metadata", {item["kind"] for item in result["legacy_unknown"]})
        marker.write_text(json.dumps({"home": str(self.home), "current": {"canonical_version": "1.0.0.1"}}))
        self.assertTrue(self.inspect()["legacy_check_complete"])
        marker.write_text(json.dumps({"home": str(self.home), "phase": "switching", "candidate": {"canonical_version": "1.0.0.1"}, "previous": None}))
        self.assertTrue(self.inspect()["legacy_check_complete"])

    def test_known_codex_environment_rejects_an_unparseable_canonical_version(self):
        marker = self.data / "environments/orphan/runtime-environment.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"agent": "codex", "canonical_version": "unparseable"}))
        result = self.inspect()
        self.assertFalse(result["legacy_check_complete"])
        self.assertIn("unattributed_environment", {item["kind"] for item in result["legacy_unknown"]})

    def test_every_setup_operation_rejects_unsafe_home_or_data_before_native_dispatch(self):
        from engineering_assistant.installer.setup_cli import main
        external = self.root / "other-user-data"
        external.mkdir()
        link = self.root / "unsafe-root"
        link.symlink_to(external, target_is_directory=True)
        for command in ("prepare", "doctor", "repair", "install", "update", "uninstall"):
            for flag in ("--agent-home", "--data-home"):
                with self.subTest(command=command, flag=flag), \
                        mock.patch("engineering_assistant.installer.setup_cli.repair_internal_codex", side_effect=AssertionError("repair")), \
                        mock.patch("engineering_assistant.installer.setup_cli.uninstall_internal_codex", side_effect=AssertionError("uninstall")), \
                        mock.patch("engineering_assistant.installer.setup_cli.install_internal_codex", side_effect=AssertionError("install")), \
                        mock.patch("engineering_assistant.installer.setup_cli.find_package", side_effect=AssertionError("discover")), \
                        redirect_stdout(io.StringIO()) as output:
                    home, data = (link, self.data) if flag == "--agent-home" else (self.home, link)
                    code = main([command, "--agent", "codex", "--agent-home", str(home), "--data-home", str(data), "--json"])
                result = json.loads(output.getvalue())
                self.assertEqual(2, code)
                self.assertEqual("needs_preparation", result["status"])
                self.assertIn("unsafe_path", {item["kind"] for item in result["legacy_unknown"]})
        self.assertEqual([], list(external.iterdir()))


if __name__ == "__main__":
    unittest.main()
