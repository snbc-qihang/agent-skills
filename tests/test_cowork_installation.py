"""Local preparation and native handoff, never authenticated Cowork acceptance."""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import tarfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class CoworkCommandTests(unittest.TestCase):
    def test_cli_accepts_cowork_without_resolving_a_claude_code_home(self):
        from engineering_assistant.installer.setup_cli import build_parser
        arguments = build_parser().parse_args(["install", "--agent", "claude-cowork"])
        self.assertEqual("claude-cowork", arguments.agent)

    def test_cli_keeps_account_activation_separate_from_local_success(self):
        from engineering_assistant.installer.setup_cli import main
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()) as output, mock.patch(
            "engineering_assistant.installer.setup_cli.agent_home", side_effect=AssertionError("not Claude Code")
        ), mock.patch("engineering_assistant.installer.installation.host_target", return_value="macos-arm64"), mock.patch(
            "engineering_assistant.installer.cowork_installation.prepare_cowork",
            return_value={"status": "needs_activation", "ready": False, "installation_prepared": True}
        ) as prepare:
            code = main(["install", "--agent", "claude-cowork", "--package", temporary, "--json"])
        self.assertEqual(0, code)
        self.assertIs(json.loads(output.getvalue())["ready"], False)
        self.assertEqual(temporary, prepare.call_args.kwargs["source"])

    def test_cowork_cannot_use_code_home_or_a_trust_declaration(self):
        from engineering_assistant.installer.setup_cli import main
        for option in (["--agent-home", "unused"], ["--marketplace", "unused"], ["--hooks-trusted"]):
            with self.subTest(option=option), redirect_stdout(io.StringIO()) as output, mock.patch(
                "engineering_assistant.installer.installation.host_target", return_value="macos-arm64"
            ), mock.patch("engineering_assistant.installer.cowork_installation.prepare_cowork") as prepare:
                self.assertEqual(2, main(["install", "--agent", "claude-cowork", *option, "--json"]))
            self.assertEqual("failed", json.loads(output.getvalue())["status"])
            prepare.assert_not_called()

    def test_cowork_rejects_other_host_targets_without_preparation(self):
        from engineering_assistant.installer.setup_cli import main
        with redirect_stdout(io.StringIO()) as output, mock.patch(
            "engineering_assistant.installer.installation.host_target", return_value="linux-x64"
        ), mock.patch("engineering_assistant.installer.cowork_installation.prepare_cowork") as prepare:
            self.assertEqual(2, main(["install", "--agent", "claude-cowork", "--json"]))
        self.assertEqual("unsupported", json.loads(output.getvalue())["status"])
        prepare.assert_not_called()

    def test_readonly_and_account_actions_reject_ignored_source_arguments(self):
        from engineering_assistant.installer.setup_cli import main
        for command in ("doctor", "uninstall"):
            for flag in ("--package", "--source"):
                with self.subTest(command=command, flag=flag), redirect_stdout(io.StringIO()), mock.patch(
                    "engineering_assistant.installer.installation.host_target", return_value="macos-arm64"
                ), mock.patch("engineering_assistant.installer.cowork_installation.inspect_cowork",
                    return_value={"status": "needs_activation", "ready": False}) as inspect:
                    self.assertEqual(2, main([command, "--agent", "claude-cowork", flag, "wrong-source", "--json"]))
                inspect.assert_not_called()


class CoworkInstallationTests(unittest.TestCase):
    def setUp(self):
        from engineering_assistant.installer import cowork_installation as cowork
        from engineering_assistant.tools.compiler import build_package
        self.cowork = cowork
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.package, self.data = self.root / "候选 插件", self.root / "共享 数据"
        self.manifest = build_package(ROOT, "claude-code", self.package)
        self.prepare = mock.patch.object(cowork.runtime, "prepare_runtime", return_value={"status": "prepared"})
        self.prepare_call = self.prepare.start()
        self.addCleanup(self.prepare.stop)
        self.doctor = mock.patch.object(cowork.runtime, "doctor", return_value={
            "status": "needs_preparation", "ready": False, "runtime_ready": True, "provider_ready": True,
            "checks": {"hook": "passed"}, "native_marketplace_session": "not_executed",
        })
        self.doctor.start()
        self.addCleanup(self.doctor.stop)
        self.native = mock.patch.object(cowork.runtime, "_native_call", side_effect=AssertionError("no native account CLI"))
        self.native.start()
        self.addCleanup(self.native.stop)

    def install(self, **kwargs):
        return self.cowork.prepare_cowork(source=str(self.package), data_home=self.data, **kwargs)

    def changed_candidate(self):
        from test_compiler_adapters import reseal_package_fixture
        path = self.package / ".claude-plugin/plugin.json"
        value = json.loads(path.read_text())
        value["description"] += " fixture revision"
        path.write_text(json.dumps(value), encoding="utf-8")
        reseal_package_fixture(self.package)

    def test_import_is_in_default_product_layout_with_original_verified_bytes(self):
        result = self.install()
        self.assertEqual("needs_activation", result["status"])
        self.assertIs(result["ready"], False)
        self.assertEqual("manual_import_required", result["native_discovery"])
        self.assertEqual("not_verified", result["native_activation"])
        self.assertEqual("not_executed", result["host_acceptance"])
        archive = Path(result["import_package"])
        self.assertTrue(archive.is_relative_to(self.data / "entries/claude-cowork"))
        with zipfile.ZipFile(archive) as bundle:
            self.assertIn(".claude-plugin/plugin.json", bundle.namelist())
            self.assertIn(".mcp.json", bundle.namelist())
            self.assertIn("hooks/hooks.json", bundle.namelist())
            self.assertFalse(any(name.startswith("bin/") for name in bundle.namelist()))
            for name in bundle.namelist():
                self.assertEqual((self.package / name).read_bytes(), bundle.read(name))
            launcher = "engineering-assistant/bin/" + ("ea.exe" if os.name == "nt" else "ea")
            self.assertTrue(bundle.getinfo(launcher).external_attr >> 16 & 0o100)
        self.assertFalse((self.data / ".claude").exists())
        self.assertTrue(self.prepare_call.call_args.args[0].is_relative_to(self.data))

    def test_repeat_install_reuses_the_same_entry_and_archive(self):
        first = self.install()
        raw = Path(first["import_package"]).read_bytes()
        result = self.install()
        self.assertIs(result["reused"], True)
        self.assertEqual(first["import_package"], result["import_package"])
        self.assertEqual(raw, Path(result["import_package"]).read_bytes())
        self.assertEqual(1, len(list((self.data / "entries/claude-cowork").iterdir())))

    def test_update_requires_explicit_selection_and_failed_preparation_preserves_previous(self):
        first = self.install()
        state = self.data / "installations/claude-cowork/state.json"
        old, raw = state.read_bytes(), Path(first["import_package"]).read_bytes()
        self.changed_candidate()
        self.assertEqual("needs_update", self.install()["status"])
        self.prepare_call.side_effect = RuntimeError("fixture network failure")
        with self.assertRaisesRegex(RuntimeError, "network failure"):
            self.install(update=True)
        self.assertEqual(old, state.read_bytes())
        self.assertEqual(raw, Path(first["import_package"]).read_bytes())
        self.assertEqual(first["import_package"], self.cowork.inspect_cowork(self.data)["import_package"])

    def test_tampering_fails_and_explicit_repair_retains_the_changed_archive(self):
        first = self.install()
        archive = Path(first["import_package"])
        original = archive.read_bytes()
        archive.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.cowork.inspect_cowork(self.data)
        repaired = self.install(repair=True)
        self.assertEqual(original, Path(repaired["import_package"]).read_bytes())
        retained = list((self.data / "entries/claude-cowork").glob("retained-*/engineering-assistant.plugin"))
        self.assertEqual(1, len(retained))
        self.assertEqual(b"changed", retained[0].read_bytes())

    def test_corrupted_package_is_never_prepared(self):
        (self.package / ".mcp.json").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.install()
        self.prepare_call.assert_not_called()
        self.assertFalse((self.data / "installations/claude-cowork/state.json").exists())

    def test_marketplace_traversal_does_not_reach_an_outside_package(self):
        market = self.root / "market/.claude-plugin"
        market.mkdir(parents=True)
        (market / "marketplace.json").write_text(json.dumps({"plugins": [
            {"name": "engineering-assistant", "source": "../../候选 插件"}]}))
        with self.assertRaises(ValueError):
            self.cowork.prepare_cowork(source=str(market.parent), data_home=self.data)
        self.prepare_call.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_symlink_data_and_source_do_not_redirect_installation(self):
        alias = self.root / "alias"
        alias.symlink_to(self.package, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.cowork.prepare_cowork(source=str(alias), data_home=self.data)
        self.data.mkdir(exist_ok=True)
        link = self.root / "data-link"
        link.symlink_to(self.data, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.cowork.prepare_cowork(source=str(self.package), data_home=link)
        self.prepare_call.assert_not_called()

    def test_doctor_is_readonly_and_account_uninstall_does_not_remove_other_hosts(self):
        missing = self.root / "not-created"
        self.assertEqual("needs_preparation", self.cowork.inspect_cowork(missing)["status"])
        self.assertFalse(missing.exists())
        first = self.install()
        marker = self.data / "codex-marker"
        marker.write_bytes(b"other host")
        result = self.cowork.uninstall_cowork()
        self.assertEqual("needs_native_action", result["status"])
        self.assertIs(result["ready"], False)
        self.assertEqual(b"other host", marker.read_bytes())
        self.assertTrue(Path(first["import_package"]).exists())

    def test_remote_sources_require_our_repository_and_an_explicit_tag(self):
        for source in ("snbc-qihang/agent-skills", "other/repository@v1", "https://example.test/code.git@v1"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.cowork.prepare_cowork(source=source, data_home=self.data)
        self.prepare_call.assert_not_called()

    def test_missing_promoted_source_and_doctor_do_not_create_data(self):
        result = self.cowork.prepare_cowork(source=None, data_home=self.data)
        self.assertEqual("needs_preparation", result["status"])
        self.assertFalse(self.data.exists())
        self.prepare_call.assert_not_called()

    def test_archive_cannot_contain_bytes_changed_after_package_verification(self):
        archive = self.cowork._archive
        def change_read(package, manifest):
            read = package.read_bytes_limited
            def replace(limit, *parts):
                return b"changed during archive" if parts == (".mcp.json",) else read(limit, *parts)
            with mock.patch.object(package, "read_bytes_limited", side_effect=replace):
                return archive(package, manifest)
        with mock.patch.object(self.cowork, "_archive", side_effect=change_read), self.assertRaises(ValueError):
            self.install()
        self.prepare_call.assert_not_called()

    def test_fixed_git_snapshot_is_verified_reused_and_tampering_stops_preparation(self):
        source = "snbc-qihang/agent-skills@candidate/claude-cowork/test"
        def fetch(url, tag, path, storage):
            self.assertEqual("https://github.com/snbc-qihang/agent-skills.git", url)
            self.assertEqual("candidate/claude-cowork/test", tag)
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode="w") as archive:
                for file in sorted(self.package.rglob("*")):
                    if file.is_file():
                        data = file.read_bytes()
                        entry = tarfile.TarInfo(file.relative_to(self.package).as_posix())
                        entry.size, entry.mode = len(data), file.stat().st_mode & 0o777
                        archive.addfile(entry, io.BytesIO(data))
            storage.write_bytes_exclusive(output.getvalue(), "release.tar")
            return "a" * 40
        with mock.patch.object(self.cowork, "_fetch_ref", side_effect=fetch) as fetch_call:
            first = self.cowork.prepare_cowork(source=source, data_home=self.data)
            second = self.cowork.prepare_cowork(source=source, data_home=self.data)
        self.assertEqual("a" * 40, first["source_revision"])
        self.assertIs(second["reused"], True)
        fetch_call.assert_called_once()
        cached = next((self.data / "sources/claude-cowork").glob("*/tree/.mcp.json"))
        cached.write_bytes(b"changed cached transport")
        self.prepare_call.reset_mock()
        with self.assertRaises(ValueError):
            self.cowork.prepare_cowork(source=source, data_home=self.data)
        self.prepare_call.assert_not_called()

    def test_source_replacement_cannot_rebind_a_verified_snapshot(self):
        from test_compiler_adapters import reseal_package_fixture
        source = self.cowork._source
        def replace_after_snapshot(*args):
            result = source(*args)
            retained = self.root / "retained-original-source"
            self.package.rename(retained)
            shutil.copytree(retained, self.package)
            (self.package / ".mcp.json").write_text('{"mcpServers":{"changed":{"command":"never-executed"}}}')
            reseal_package_fixture(self.package)
            return result
        with mock.patch.object(self.cowork, "_source", side_effect=replace_after_snapshot), self.assertRaises(ValueError):
            self.install()
        self.prepare_call.assert_not_called()

    def test_failed_repair_restores_a_previously_valid_entry(self):
        first = self.install()
        archive = Path(first["import_package"])
        original = archive.read_bytes()
        verify, corrupted = self.cowork._verify_entry, False
        def corrupt_new_entry(storage, current):
            nonlocal corrupted
            if not corrupted and list((self.data / "entries/claude-cowork").glob("retained-*")):
                corrupted = True
                archive.write_bytes(b"failed candidate archive")
            return verify(storage, current)
        with mock.patch.object(self.cowork, "_verify_entry", side_effect=corrupt_new_entry), self.assertRaises(ValueError):
            self.install(repair=True)
        self.assertTrue(corrupted)
        self.assertEqual(original, archive.read_bytes())
        self.assertEqual("needs_activation", self.cowork.inspect_cowork(self.data)["status"])

    def test_package_directory_swap_after_archiving_never_reaches_runtime_preparation(self):
        from test_compiler_adapters import reseal_package_fixture
        archive = self.cowork._archive
        def replace_after_archive(destination, manifest):
            raw = archive(destination, manifest)
            path = destination.path()
            retained = path.parent / "retained-original-package"
            path.rename(retained)
            shutil.copytree(retained, path)
            (path / ".mcp.json").write_text('{"mcpServers":{"changed":{"command":"never-executed"}}}')
            reseal_package_fixture(path)
            return raw
        with mock.patch.object(self.cowork, "_archive", side_effect=replace_after_archive), self.assertRaises(ValueError):
            self.install()
        self.prepare_call.assert_not_called()
