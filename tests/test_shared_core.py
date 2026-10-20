from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class SharedCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def package(self, name, agent):
        from engineering_assistant.tools.compiler import build_package
        path = self.root / name
        build_package(ROOT, agent, path)
        return path

    def test_hosts_reuse_one_verified_core_and_keep_distinct_entries(self):
        from engineering_assistant.installer.shared_core import prepare_core
        from engineering_assistant.installer.installation import _storage
        from engineering_assistant.runtime.shared_core import resolve_core
        codex, claude = self.package("codex", "codex"), self.package("claude", "claude-code")
        data = self.root / "共享 核心"
        storage = _storage(data)
        self.addCleanup(storage.close)
        first = prepare_core(codex, storage)
        second = prepare_core(claude, storage)
        self.assertEqual(first, second)
        self.assertTrue(first.is_relative_to(data / "cores"))
        self.assertEqual(first, resolve_core(codex / "engineering-assistant", data))
        self.assertEqual(first, resolve_core(claude / "engineering-assistant", data))
        self.assertTrue((first / "skills/code-review/SKILL.md").is_file())
        self.assertFalse((first / "runtime-lock.json").exists())
        self.assertFalse((first / ".codex-plugin").exists())

    def test_core_tampering_and_unknown_files_fail_without_overwriting(self):
        from engineering_assistant.installer.shared_core import prepare_core
        from engineering_assistant.installer.installation import _storage
        from engineering_assistant.runtime.shared_core import resolve_core
        package = self.package("codex", "codex")
        data = self.root / "data"
        storage = _storage(data)
        self.addCleanup(storage.close)
        core = prepare_core(package, storage)
        target = core / "runtime/engineering_assistant/__init__.py"
        original = target.read_bytes()
        target.write_bytes(b"raise RuntimeError('changed core')")
        for check in (lambda: prepare_core(package, storage), lambda: resolve_core(package / "engineering-assistant", data)):
            with self.assertRaises(ValueError):
                check()
        self.assertNotEqual(original, target.read_bytes())
        target.write_bytes(original)
        (core / "unexpected.py").write_bytes(b"unexpected")
        with self.assertRaises(ValueError):
            resolve_core(package / "engineering-assistant", data)

    def test_explicit_repair_retains_changed_core_and_restores_verified_content(self):
        from engineering_assistant.installer.shared_core import prepare_core
        from engineering_assistant.installer.installation import _storage
        package = self.package("codex", "codex")
        storage = _storage(self.root / "data")
        self.addCleanup(storage.close)
        core = prepare_core(package, storage)
        marker = core / "runtime/engineering_assistant/__init__.py"
        expected = marker.read_bytes()
        marker.write_bytes(b"changed")
        self.assertEqual(core, prepare_core(package, storage, repair=True))
        self.assertEqual(expected, marker.read_bytes())
        retained = list(storage.path("retained-cores").glob("*/runtime/engineering_assistant/__init__.py"))
        self.assertEqual(1, len(retained))
        self.assertEqual(b"changed", retained[0].read_bytes())

    def test_native_entry_executes_shared_core_instead_of_transport_copy(self):
        from test_compiler_adapters import CompilerAdapterTests
        import subprocess
        package = self.package("codex", "codex")
        fixture = CompilerAdapterTests()
        fixture.root = self.root
        launcher, environment = fixture.native_runtime_fixture(package)
        # Native entry files remain intact; a transport module must not become
        # the code executed by a prepared native entry.
        (package / "engineering-assistant/runtime/engineering_assistant/runtime/router.py").write_text(
            "raise RuntimeError('transport module executed')\n", encoding="utf-8")
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        result = subprocess.run([str(launcher), "mcp-serve"], input=json.dumps(request) + "\n",
            cwd=self.root, env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["result"]["tools"])

    @unittest.skipIf(os.name == "nt", "POSIX link fixture")
    def test_core_link_escape_is_rejected_without_touching_target(self):
        from engineering_assistant.installer.shared_core import prepare_core
        from engineering_assistant.installer.installation import _storage
        from engineering_assistant.runtime.shared_core import core_descriptor
        package = self.package("codex", "codex")
        storage = _storage(self.root / "data")
        self.addCleanup(storage.close)
        outside = self.root / "outside"
        outside.mkdir()
        marker = outside / "keep"
        marker.write_bytes(b"keep")
        parent = storage.ensure_directory("cores")
        (parent / core_descriptor(package)["payload_digest"][7:]).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            prepare_core(package, storage)
        self.assertEqual([marker], list(outside.iterdir()))

    def test_legacy_package_without_core_descriptor_still_uses_bundled_runtime(self):
        from engineering_assistant.runtime.shared_core import resolve_core
        entry = self.root / "legacy/engineering-assistant"
        entry.mkdir(parents=True)
        self.assertEqual(entry, resolve_core(entry, self.root / "unused"))

    def test_new_package_never_falls_back_when_shared_core_is_missing(self):
        from engineering_assistant.runtime.shared_core import resolve_core
        package = self.package("codex", "codex")
        with self.assertRaises(FileNotFoundError):
            resolve_core(package / "engineering-assistant", self.root / "absent")

    def test_default_locator_follows_fixed_environment_without_a_latest_core_alias(self):
        from unittest import mock
        from engineering_assistant.runtime.shared_core import bootstrap_data_home
        default, actual = self.root / "default", self.root / "custom 数据"
        key = "a" * 64
        path = default / "bindings/codex" / (key + ".json")
        path.parent.mkdir(parents=True)
        lock = {"schema_version": "2", "agent": "codex", "target": "macos-arm64", "environment_key": key}
        path.write_text(json.dumps({**lock, "environment": str(actual / "environments" / key)}), encoding="utf-8")
        with mock.patch("engineering_assistant.runtime.shared_core.default_data_home", return_value=default):
            self.assertEqual(actual, bootstrap_data_home(lock))


if __name__ == "__main__":
    unittest.main()
