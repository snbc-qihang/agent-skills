from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.compiler import build_package, verify_package  # noqa: E402
from engineering_assistant.local_publish import (  # noqa: E402
    _load_policy,
    _publish_one,
    _repair_codex_cache_version,
    _resolve_platform_cli,
    _restore_codex_cache_snapshots,
    _roll_back,
    _snapshot_codex_caches,
    _swap_in,
    _update_personal_marketplace,
)


class LocalPublishTests(unittest.TestCase):
    def test_platform_cli_prefers_explicit_executable_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "codex-custom"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            resolved = _resolve_platform_cli("codex", {"PATH": "", "CODEX_CLI": str(executable)})
            self.assertEqual(str(executable.resolve()), resolved)

    def test_codex_cli_falls_back_to_macos_app_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "codex"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            with mock.patch(
                "engineering_assistant.local_publish._bundled_cli_candidates",
                return_value=[executable],
            ):
                resolved = _resolve_platform_cli("codex", {"PATH": ""})
            self.assertEqual(str(executable.resolve()), resolved)

    def test_codex_cachebuster_is_built_before_package_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "codex"
            build_package(ROOT, "codex", output, codex_cachebuster="local-test-1")
            verify_package(output)
            manifest = json.loads((output / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
            self.assertEqual("1.0.0-rc.1+codex.local-test-1", manifest["version"])

    def test_codex_registration_can_restore_caches_used_by_active_threads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            version = "1.0.0-rc.1+codex.local-active-thread"
            cache = codex_home / "plugins/cache/personal/engineering-assistant" / version
            build_package(ROOT, "codex", cache, codex_cachebuster="local-active-thread")
            runtime_cache = cache / "engineering-assistant/runtime/engineering_assistant/__pycache__"
            runtime_cache.mkdir()
            (runtime_cache / "feedback.cpython-314.pyc").write_bytes(b"runtime-derived")
            snapshot = root / "snapshot"
            snapshot.mkdir()

            self.assertEqual([version], _snapshot_codex_caches(codex_home, snapshot))
            self.assertFalse((snapshot / version / runtime_cache.relative_to(cache)).exists())
            shutil.rmtree(cache)
            self.assertEqual([version], _restore_codex_cache_snapshots(codex_home, snapshot))
            self.assertTrue((cache / "hooks/feedback_capture.py").is_file())

    def test_missing_active_cache_can_be_repaired_from_publish_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            target = root / "plugins/engineering-assistant"
            target.parent.mkdir(parents=True)
            backup = target.parent / ".engineering-assistant.backup-test"
            version = "1.0.0-rc.1+codex.local-repair"
            build_package(ROOT, "codex", backup, codex_cachebuster="local-repair")
            runtime_cache = backup / "engineering-assistant/runtime/engineering_assistant/__pycache__"
            runtime_cache.mkdir()
            (runtime_cache / "feedback.cpython-314.pyc").write_bytes(b"runtime-derived")

            repaired = _repair_codex_cache_version(codex_home, target, version)

            self.assertEqual(
                codex_home / "plugins/cache/personal/engineering-assistant" / version,
                repaired,
            )
            self.assertTrue((repaired / "hooks/feedback_capture.py").is_file())

    def test_publish_restores_cache_deleted_by_codex_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            hermes_home = root / ".hermes"
            target = root / "plugins/engineering-assistant"
            old_version = "1.0.0-rc.1+codex.local-old-thread"
            build_package(ROOT, "codex", target, codex_cachebuster="local-old-thread")
            old_cache = codex_home / "plugins/cache/personal/engineering-assistant" / old_version
            shutil.copytree(target, old_cache)
            _update_personal_marketplace(root / ".agents/plugins/marketplace.json")

            def register(command: list[str], _environment=None) -> dict:
                cache_root = old_cache.parent
                if cache_root.exists():
                    shutil.rmtree(cache_root)
                cache_root.mkdir(parents=True)
                version = json.loads((target / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
                shutil.copytree(target, cache_root / version)
                return {"version": version}

            report = _publish_one(
                ROOT,
                "codex",
                codex_home=codex_home,
                hermes_home=hermes_home,
                dry_run=False,
                register=register,
            )

            self.assertIn(old_version, report["preserved_cache_versions"])
            self.assertIn(old_version, report["restored_cache_versions"])
            self.assertTrue((old_cache / "hooks/feedback_capture.py").is_file())

    def test_cache_preservation_is_bounded_to_eight_recent_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            cache_root = codex_home / "plugins/cache/personal/engineering-assistant"
            versions = []
            for index in range(9):
                cachebuster = f"local-retention-{index}"
                version = f"1.0.0-rc.1+codex.{cachebuster}"
                cache = cache_root / version
                build_package(ROOT, "codex", cache, codex_cachebuster=cachebuster)
                os.utime(cache, ns=(index + 1, index + 1))
                versions.append(version)
            for index in range(8):
                invalid = cache_root / f".interrupted-restore-{index}"
                invalid.mkdir()
                os.utime(invalid, ns=(100 + index, 100 + index))
            snapshot = root / "snapshot"
            snapshot.mkdir()

            preserved = _snapshot_codex_caches(codex_home, snapshot)

            self.assertEqual(8, len(preserved))
            self.assertNotIn(versions[0], preserved)
            self.assertIn(versions[-1], preserved)

    def test_registration_side_effect_then_error_is_compensated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            hermes_home = root / ".hermes"
            target = root / "plugins/engineering-assistant"
            old_version = "1.0.0-rc.1+codex.local-partial-registration"
            build_package(ROOT, "codex", target, codex_cachebuster="local-partial-registration")
            old_cache = codex_home / "plugins/cache/personal/engineering-assistant" / old_version
            shutil.copytree(target, old_cache)
            _update_personal_marketplace(root / ".agents/plugins/marketplace.json")
            registered_versions: list[str] = []

            def register(command: list[str], _environment=None) -> dict:
                cache_root = old_cache.parent
                if cache_root.exists():
                    shutil.rmtree(cache_root)
                cache_root.mkdir(parents=True)
                version = json.loads((target / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
                shutil.copytree(target, cache_root / version)
                registered_versions.append(version)
                if len(registered_versions) == 1:
                    raise RuntimeError("registration failed after side effect")
                return {"version": version}

            with self.assertRaisesRegex(RuntimeError, "registration failed after side effect"):
                _publish_one(
                    ROOT,
                    "codex",
                    codex_home=codex_home,
                    hermes_home=hermes_home,
                    dry_run=False,
                    register=register,
                )

            self.assertEqual(old_version, registered_versions[-1])
            self.assertEqual(old_version, json.loads((target / ".codex-plugin/plugin.json").read_text())["version"])
            self.assertTrue((old_cache / "hooks/feedback_capture.py").is_file())

    def test_restore_failure_reregisters_rolled_back_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            hermes_home = root / ".hermes"
            target = root / "plugins/engineering-assistant"
            old_version = "1.0.0-rc.1+codex.local-old-registration"
            build_package(ROOT, "codex", target, codex_cachebuster="local-old-registration")
            old_cache = codex_home / "plugins/cache/personal/engineering-assistant" / old_version
            shutil.copytree(target, old_cache)
            _update_personal_marketplace(root / ".agents/plugins/marketplace.json")
            registered_versions: list[str] = []

            def register(command: list[str], _environment=None) -> dict:
                cache_root = old_cache.parent
                if cache_root.exists():
                    shutil.rmtree(cache_root)
                cache_root.mkdir(parents=True)
                version = json.loads((target / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
                shutil.copytree(target, cache_root / version)
                registered_versions.append(version)
                return {"version": version}

            restore_calls = 0

            def restore_with_first_failure(*args, **kwargs):
                nonlocal restore_calls
                restore_calls += 1
                if restore_calls == 1:
                    raise RuntimeError("restore failed")
                return _restore_codex_cache_snapshots(*args, **kwargs)

            with mock.patch(
                "engineering_assistant.local_publish._restore_codex_cache_snapshots",
                side_effect=restore_with_first_failure,
            ):
                with self.assertRaisesRegex(RuntimeError, "restore failed"):
                    _publish_one(
                        ROOT,
                        "codex",
                        codex_home=codex_home,
                        hermes_home=hermes_home,
                        dry_run=False,
                        register=register,
                    )

            self.assertEqual(old_version, registered_versions[-1])
            self.assertEqual(old_version, json.loads((target / ".codex-plugin/plugin.json").read_text())["version"])
            self.assertTrue((old_cache / "hooks/feedback_capture.py").is_file())

    def test_local_publish_policy_allows_both_platforms_without_history(self) -> None:
        policy = ROOT / "config/local-publish-policy.json"
        loaded = _load_policy(policy, ["codex", "hermes"])
        self.assertTrue(loaded["enabled"])
        self.assertEqual("1.0.0.0-rc.1", loaded["canonical_version"])
        self.assertNotIn("reviewer", loaded)
        self.assertNotIn("execution_result", loaded)

    def test_personal_marketplace_is_created_and_updated_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".agents/plugins/marketplace.json"
            previous, changed = _update_personal_marketplace(path)
            self.assertIsNone(previous)
            self.assertTrue(changed)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("personal", payload["name"])
            self.assertEqual("engineering-assistant", payload["plugins"][0]["name"])
            self.assertEqual("./plugins/engineering-assistant", payload["plugins"][0]["source"]["path"])
            _, changed_again = _update_personal_marketplace(path)
            self.assertFalse(changed_again)

    def test_dry_run_builds_both_platforms_without_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            for platform in ["codex", "hermes"]:
                report = _publish_one(
                    ROOT,
                    platform,
                    codex_home=home / ".codex",
                    hermes_home=home / ".hermes",
                    dry_run=True,
                    register=lambda _command, _environment=None: self.fail("dry-run must not register"),
                )
                self.assertEqual("dry_run_passed", report["status"])
                self.assertEqual(11, report["skill_count"])
            self.assertFalse((home / "plugins").exists())
            self.assertFalse((home / ".hermes").exists())

    def test_atomic_swap_can_be_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "engineering-assistant"
            staging = root / ".stage"
            target.mkdir()
            staging.mkdir()
            (target / "version").write_text("old", encoding="utf-8")
            (staging / "version").write_text("new", encoding="utf-8")
            backup = _swap_in(staging, target, "test")
            self.assertEqual("new", (target / "version").read_text(encoding="utf-8"))
            _roll_back(target, backup, "test")
            self.assertEqual("old", (target / "version").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
