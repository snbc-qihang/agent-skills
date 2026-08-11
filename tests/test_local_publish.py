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

from engineering_assistant.artifact_io import ArtifactIO  # noqa: E402
from engineering_assistant.compiler import build_package, verify_package  # noqa: E402
from engineering_assistant.local_publish import (  # noqa: E402
    _load_policy,
    _publish_one,
    _repair_codex_cache_version,
    _run_repository_preflight,
    _resolve_platform_cli,
    _restore_codex_cache_snapshots,
    _roll_back,
    _snapshot_codex_caches,
    _swap_in,
    _update_personal_marketplace,
    uninstall_claude_installation,
    verify_claude_installation,
)
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class LocalPublishTests(unittest.TestCase):
    @staticmethod
    def official_validation(_repository: Path, package: Path, **_kwargs) -> dict:
        manifest = json.loads(
            (Path(package) / "package-manifest.json").read_text(encoding="utf-8")
        )
        return {
            "status": "passed",
            "codex_payload_digest": manifest["payload_digest"],
        }

    def test_repository_preflight_requires_source_and_official_validation(self) -> None:
        evaluation = {
            "version": "2.2.0.0-rc.1",
            "simulation": False,
            "canary": {
                "status": "not_run",
                "reason": "real product evidence is external to repository evals",
                "simulation_results_accepted": False,
            },
            "routing": {
                "case_count": 120,
                "top1_accuracy": 1.0,
                "unconfirmed_high_risk_writes": 0,
            },
        }
        official = {
            "status": "passed",
            "skill_count": 11,
            "quick_validate": "passed",
            "codex_plugin_validate": "not_run",
            "codex_payload_digest": None,
            "validator_dependency": "pyyaml==6.0.2",
        }
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch(
            "engineering_assistant.local_publish.subprocess.run",
            return_value=completed,
        ), mock.patch(
            "engineering_assistant.local_publish.run_evals",
            return_value=evaluation,
        ), mock.patch(
            "engineering_assistant.local_publish.validate_with_official_tools",
            return_value=official,
        ) as validate_official:
            report = _run_repository_preflight(ROOT)

        self.assertEqual("passed", report["source_validation"])
        self.assertEqual(11, report["source_skill_count"])
        self.assertEqual(official, report["official_validation"])
        self.assertEqual(evaluation["canary"], report["canary"])
        self.assertEqual(
            {
                "scope": "local_prerelease",
                "required": False,
                "status": "not_required_for_local_prerelease",
            },
            report["canary_gate"],
        )
        validate_official.assert_called_once_with(ROOT, validate_plugin=False)

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
            self.assertEqual("2.2.0-rc.1+codex.local-test-1", manifest["version"])

    def test_codex_registration_uses_the_selected_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / "isolated-codex-home"
            environments: list[dict[str, str] | None] = []
            installed = False
            installed_version: str | None = None

            def register(command: list[str], environment=None) -> dict:
                nonlocal installed, installed_version
                environments.append(environment)
                action = command[2]
                if action == "list":
                    entries = []
                    if installed:
                        entries.append(
                            {"name": "engineering-assistant", "version": installed_version}
                        )
                    return {"installed": entries}
                if action == "remove":
                    installed = False
                    return {"status": "removed"}
                target = root / "plugins/engineering-assistant"
                version = json.loads(
                    (target / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
                )["version"]
                cache = (
                    codex_home
                    / "plugins/cache/personal/engineering-assistant"
                    / version
                )
                cache.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(target, cache)
                installed = True
                installed_version = version
                return {"status": "added", "version": version}

            report = _publish_one(
                ROOT,
                "codex",
                codex_home=codex_home,
                hermes_home=root / ".hermes",
                dry_run=False,
                register=register,
                official_validate=self.official_validation,
            )

            self.assertTrue(environments)
            self.assertEqual(
                str(
                    codex_home
                    / "plugins/cache/personal/engineering-assistant"
                    / report["plugin_version"]
                ),
                report["registered_cache"]["path"],
            )
            self.assertEqual(
                report["payload_digest"],
                report["registered_cache"]["payload_digest"],
            )
            self.assertTrue(
                all(
                    environment is not None
                    and environment.get("CODEX_HOME") == str(codex_home)
                    for environment in environments
                )
            )

    def test_hermes_registration_is_noninteractive_and_uses_the_selected_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hermes_home = root / "isolated-hermes-home"
            calls: list[tuple[list[str], dict[str, str] | None]] = []

            def register(command: list[str], environment=None) -> dict:
                calls.append((command, environment))
                return {"status": "passed"}

            _publish_one(
                ROOT,
                "hermes",
                codex_home=root / ".codex",
                hermes_home=hermes_home,
                dry_run=False,
                register=register,
                official_validate=self.official_validation,
            )

            self.assertEqual(
                [
                    "hermes",
                    "plugins",
                    "enable",
                    "engineering-assistant",
                    "--no-allow-tool-override",
                ],
                calls[0][0],
            )
            self.assertEqual(str(hermes_home), calls[0][1]["HERMES_HOME"])

    def test_codex_publish_rolls_back_when_registration_does_not_install_the_built_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            target = root / "plugins/engineering-assistant"
            target.parent.mkdir(parents=True)
            build_package(ROOT, "codex", target, codex_cachebuster="local-before-missing-cache")
            previous_version = json.loads(
                (target / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
            )["version"]

            with self.assertRaisesRegex(ValidationFailure, "cache|缓存"):
                _publish_one(
                    ROOT,
                    "codex",
                    codex_home=codex_home,
                    hermes_home=root / ".hermes",
                    dry_run=False,
                    register=lambda _command, _environment=None: {"status": "passed"},
                    official_validate=self.official_validation,
                )

            self.assertEqual(
                previous_version,
                json.loads(
                    (target / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
                )["version"],
            )

    def test_codex_publish_rejects_a_registered_cache_with_a_payload_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"

            installed_version: str | None = None

            def register(command: list[str], _environment=None) -> dict:
                nonlocal installed_version
                if command[2] == "list":
                    return {
                        "installed": (
                            [{"name": "engineering-assistant", "version": installed_version}]
                            if installed_version
                            else []
                        )
                    }
                if command[2] == "remove":
                    installed_version = None
                    return {"status": "removed"}
                target = root / "plugins/engineering-assistant"
                version = json.loads(
                    (target / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
                )["version"]
                cache = (
                    codex_home
                    / "plugins/cache/personal/engineering-assistant"
                    / version
                )
                cache.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(target, cache)
                registered_hook = cache / "hooks/hooks.json"
                registered_hook.unlink()
                registered_hook.symlink_to(target / "hooks/hooks.json")
                installed_version = version
                return {"status": "added"}

            with self.assertRaises(ValidationFailure):
                _publish_one(
                    ROOT,
                    "codex",
                    codex_home=codex_home,
                    hermes_home=root / ".hermes",
                    dry_run=False,
                    register=register,
                    official_validate=self.official_validation,
                )

    def test_codex_publish_rejects_a_registered_cache_directory_replaced_after_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            registered_cache: Path | None = None

            installed_version: str | None = None

            def register(command: list[str], _environment=None) -> dict:
                nonlocal registered_cache, installed_version
                if command[2] == "list":
                    return {
                        "installed": (
                            [{"name": "engineering-assistant", "version": installed_version}]
                            if installed_version
                            else []
                        )
                    }
                if command[2] == "remove":
                    installed_version = None
                    return {"status": "removed"}
                target = root / "plugins/engineering-assistant"
                version = json.loads(
                    (target / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
                )["version"]
                registered_cache = (
                    codex_home
                    / "plugins/cache/personal/engineering-assistant"
                    / version
                )
                registered_cache.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(target, registered_cache)
                installed_version = version
                return {"status": "added"}

            original_hash = ArtifactIO.sha256_file_digests
            replaced = False

            def replace_after_hash(artifacts, **kwargs):
                nonlocal replaced
                result = original_hash(artifacts, **kwargs)
                if registered_cache is not None and not replaced:
                    moved = registered_cache.with_name(registered_cache.name + ".moved")
                    registered_cache.rename(moved)
                    registered_cache.mkdir()
                    replaced = True
                return result

            with mock.patch.object(
                ArtifactIO,
                "sha256_file_digests",
                autospec=True,
                side_effect=replace_after_hash,
            ):
                with self.assertRaisesRegex(ValidationFailure, "变化|identity|替换"):
                    _publish_one(
                        ROOT,
                        "codex",
                        codex_home=codex_home,
                        hermes_home=root / ".hermes",
                        dry_run=False,
                        register=register,
                        official_validate=self.official_validation,
                    )

            self.assertTrue(replaced)

    def test_codex_publish_restores_a_corrupted_old_active_cache_during_compensation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            target = root / "plugins/engineering-assistant"
            target.parent.mkdir(parents=True)
            old_version = "2.2.0-rc.1+codex.local-corrupted-active"
            build_package(ROOT, "codex", target, codex_cachebuster="local-corrupted-active")
            old_cache = (
                codex_home
                / "plugins/cache/personal/engineering-assistant"
                / old_version
            )
            shutil.copytree(target, old_cache)
            _update_personal_marketplace(root / ".agents/plugins/marketplace.json")
            registration_calls = 0
            installed_version: str | None = old_version

            def register(command: list[str], _environment=None) -> dict:
                nonlocal registration_calls, installed_version
                registration_calls += 1
                if command[2] == "list":
                    (old_cache / "hooks/hooks.json").write_text("{}\n", encoding="utf-8")
                    return {
                        "installed": [
                            {"name": "engineering-assistant", "version": installed_version}
                        ]
                    }
                if command[2] == "remove":
                    installed_version = None
                    return {"status": "removed"}
                installed_version = json.loads(
                    (target / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
                )["version"]
                return {"status": "added", "version": installed_version}

            with self.assertRaisesRegex(ValidationFailure, "cache|缓存"):
                _publish_one(
                    ROOT,
                    "codex",
                    codex_home=codex_home,
                    hermes_home=root / ".hermes",
                    dry_run=False,
                    register=register,
                    official_validate=self.official_validation,
                )

            self.assertEqual(5, registration_calls)
            verify_package(old_cache)
            self.assertEqual(
                old_version,
                json.loads(
                    (old_cache / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
                )["version"],
            )

    def test_codex_registration_can_restore_caches_used_by_active_threads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            version = "2.2.0-rc.1+codex.local-active-thread"
            cache = codex_home / "plugins/cache/personal/engineering-assistant" / version
            cache.parent.mkdir(parents=True)
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

    def test_codex_cache_snapshot_preserves_the_known_previous_manifest_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            version = "2.2.0-rc.1+codex.local-previous-contract"
            cache = codex_home / "plugins/cache/personal/engineering-assistant" / version
            cache.parent.mkdir(parents=True)
            build_package(
                ROOT,
                "codex",
                cache,
                codex_cachebuster="local-previous-contract",
            )
            manifest_path = cache / "package-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("build_format_version")
            manifest.pop("source_count")
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            snapshot = root / "snapshot"
            snapshot.mkdir()

            self.assertEqual([version], _snapshot_codex_caches(codex_home, snapshot))
            shutil.rmtree(cache)
            self.assertEqual([version], _restore_codex_cache_snapshots(codex_home, snapshot))
            self.assertEqual(manifest, verify_package(cache))

    def test_codex_cache_snapshot_never_follows_a_payload_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            version = "2.2.0-rc.1+codex.local-unsafe-snapshot"
            cache = codex_home / "plugins/cache/personal/engineering-assistant" / version
            cache.parent.mkdir(parents=True)
            build_package(ROOT, "codex", cache, codex_cachebuster="local-unsafe-snapshot")
            outside_hook = root / "outside-hooks.json"
            outside_hook.write_bytes((cache / "hooks/hooks.json").read_bytes())
            (cache / "hooks/hooks.json").unlink()
            (cache / "hooks/hooks.json").symlink_to(outside_hook)
            snapshot = root / "snapshot"
            snapshot.mkdir()

            with self.assertRaisesRegex(ValidationFailure, "unsafe"):
                _snapshot_codex_caches(codex_home, snapshot)

    def test_codex_cache_candidate_discovery_never_follows_a_manifest_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            version = "2.2.0-rc.1+codex.local-unsafe-manifest"
            cache = codex_home / "plugins/cache/personal/engineering-assistant" / version
            cache.parent.mkdir(parents=True)
            build_package(ROOT, "codex", cache, codex_cachebuster="local-unsafe-manifest")
            outside_manifest = root / "outside-plugin.json"
            manifest = cache / ".codex-plugin/plugin.json"
            outside_manifest.write_bytes(manifest.read_bytes())
            manifest.unlink()
            manifest.symlink_to(outside_manifest)
            snapshot = root / "snapshot"
            snapshot.mkdir()

            self.assertEqual([], _snapshot_codex_caches(codex_home, snapshot))
            self.assertEqual([], list(snapshot.iterdir()))

    def test_missing_active_cache_can_be_repaired_from_publish_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            target = root / "plugins/engineering-assistant"
            target.parent.mkdir(parents=True)
            backup = target.parent / ".engineering-assistant.backup-test"
            version = "2.2.0-rc.1+codex.local-repair"
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

    def test_successful_publish_keeps_only_the_selected_cache_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            hermes_home = root / ".hermes"
            target = root / "plugins/engineering-assistant"
            target.parent.mkdir(parents=True)
            old_version = "2.2.0-rc.1+codex.local-old-thread"
            build_package(ROOT, "codex", target, codex_cachebuster="local-old-thread")
            old_cache = codex_home / "plugins/cache/personal/engineering-assistant" / old_version
            shutil.copytree(target, old_cache)
            _update_personal_marketplace(root / ".agents/plugins/marketplace.json")

            installed_version: str | None = old_version

            def register(command: list[str], _environment=None) -> dict:
                nonlocal installed_version
                cache_root = old_cache.parent
                if command[2] == "list":
                    return {
                        "installed": [
                            {"name": "engineering-assistant", "version": installed_version}
                        ] if installed_version else []
                    }
                if command[2] == "remove":
                    installed_version = None
                    return {"status": "removed"}
                version = json.loads((target / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
                cache_root.mkdir(parents=True, exist_ok=True)
                shutil.copytree(target, cache_root / version)
                installed_version = version
                return {"version": version}

            report = _publish_one(
                ROOT,
                "codex",
                codex_home=codex_home,
                hermes_home=hermes_home,
                dry_run=False,
                register=register,
                official_validate=self.official_validation,
            )

            self.assertEqual([report["plugin_version"]], report["active_cache_versions"])
            self.assertTrue(report["selected_version_verified"])
            self.assertIn(old_version, report["removed_cache_versions"])
            self.assertFalse(old_cache.exists())
            self.assertNotIn("restored_cache_versions", report)

    def test_failure_snapshot_preserves_all_valid_active_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            cache_root = codex_home / "plugins/cache/personal/engineering-assistant"
            cache_root.mkdir(parents=True)
            versions = []
            for index in range(9):
                cachebuster = f"local-retention-{index}"
                version = f"2.2.0-rc.1+codex.{cachebuster}"
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

            self.assertEqual(9, len(preserved))
            self.assertIn(versions[0], preserved)
            self.assertIn(versions[-1], preserved)

    def test_registration_side_effect_then_error_is_compensated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            hermes_home = root / ".hermes"
            target = root / "plugins/engineering-assistant"
            target.parent.mkdir(parents=True)
            old_version = "2.2.0-rc.1+codex.local-partial-registration"
            build_package(ROOT, "codex", target, codex_cachebuster="local-partial-registration")
            old_cache = codex_home / "plugins/cache/personal/engineering-assistant" / old_version
            shutil.copytree(target, old_cache)
            _update_personal_marketplace(root / ".agents/plugins/marketplace.json")
            registered_versions: list[str] = []
            installed_version: str | None = old_version

            def register(command: list[str], _environment=None) -> dict:
                nonlocal installed_version
                cache_root = old_cache.parent
                if command[2] == "list":
                    return {
                        "installed": [
                            {"name": "engineering-assistant", "version": installed_version}
                        ] if installed_version else []
                    }
                if command[2] == "remove":
                    installed_version = None
                    if cache_root.exists():
                        shutil.rmtree(cache_root)
                    cache_root.mkdir(parents=True)
                    return {"status": "removed"}
                cache_root.mkdir(parents=True, exist_ok=True)
                version = json.loads((target / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
                shutil.copytree(target, cache_root / version)
                registered_versions.append(version)
                installed_version = version
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
                    official_validate=self.official_validation,
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
            target.parent.mkdir(parents=True)
            old_version = "2.2.0-rc.1+codex.local-old-registration"
            build_package(ROOT, "codex", target, codex_cachebuster="local-old-registration")
            old_cache = codex_home / "plugins/cache/personal/engineering-assistant" / old_version
            shutil.copytree(target, old_cache)
            _update_personal_marketplace(root / ".agents/plugins/marketplace.json")
            registered_versions: list[str] = []
            installed_version: str | None = old_version

            def register(command: list[str], _environment=None) -> dict:
                nonlocal installed_version
                cache_root = old_cache.parent
                if command[2] == "list":
                    return {
                        "installed": [
                            {"name": "engineering-assistant", "version": installed_version}
                        ] if installed_version else []
                    }
                if command[2] == "remove":
                    installed_version = None
                    if cache_root.exists():
                        shutil.rmtree(cache_root)
                    cache_root.mkdir(parents=True)
                    return {"status": "removed"}
                cache_root.mkdir(parents=True, exist_ok=True)
                version = json.loads((target / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
                shutil.copytree(target, cache_root / version)
                registered_versions.append(version)
                installed_version = version
                if len(registered_versions) == 1:
                    raise RuntimeError("force compensation")
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
                with self.assertRaisesRegex(ValidationFailure, "cache_restore=restore failed"):
                    _publish_one(
                        ROOT,
                        "codex",
                        codex_home=codex_home,
                        hermes_home=hermes_home,
                        dry_run=False,
                        register=register,
                        official_validate=self.official_validation,
                    )

            self.assertEqual(old_version, registered_versions[-1])
            self.assertEqual(old_version, json.loads((target / ".codex-plugin/plugin.json").read_text())["version"])
            self.assertTrue((old_cache / "hooks/feedback_capture.py").is_file())

    def test_local_publish_policy_allows_supported_platforms_without_history(self) -> None:
        policy = ROOT / "config/local-publish-policy.json"
        loaded = _load_policy(policy, ["codex", "hermes", "claude-code"])
        self.assertTrue(loaded["enabled"])
        self.assertEqual("2.2.0.0-rc.1", loaded["canonical_version"])
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
                    official_validate=self.official_validation,
                )
                self.assertEqual("dry_run_passed", report["status"])
                self.assertEqual(11, report["skill_count"])
                if platform == "codex":
                    self.assertEqual(
                        report["payload_digest"],
                        report["official_validation"]["codex_payload_digest"],
                    )
                else:
                    self.assertIsNone(report["official_validation"])
            self.assertFalse((home / "plugins").exists())
            self.assertFalse((home / ".hermes").exists())

    def test_claude_code_marketplace_install_verify_and_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            homes = {
                "codex_home": root / ".codex",
                "hermes_home": root / ".hermes",
                "claude_home": root / ".claude",
            }
            installed = False
            commands: list[list[str]] = []

            def register(command: list[str], _environment=None) -> dict:
                nonlocal installed
                commands.append(command)
                if command[1:3] == ["plugin", "list"]:
                    return ([{"id": "engineering-assistant@engineering-assistant-local"}] if installed else [])
                if command[1:3] == ["plugin", "install"] or command[1:3] == ["plugin", "update"]:
                    installed = True
                if command[1:3] == ["plugin", "uninstall"]:
                    installed = False
                return {"status": "passed"}

            report = _publish_one(
                ROOT,
                "claude-code",
                dry_run=False,
                register=register,
                official_validate=self.official_validation,
                **homes,
            )
            target = homes["claude_home"] / "plugins/marketplaces/engineering-assistant-local"
            marketplace = json.loads((target / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
            self.assertEqual("published", report["status"])
            self.assertEqual("./plugins/engineering-assistant", marketplace["plugins"][0]["source"])
            self.assertTrue((target / "plugins/engineering-assistant/.mcp.json").is_file())
            self.assertIn(
                ["claude", "plugin", "marketplace", "add", str(target), "--scope", "user"],
                commands,
            )
            self.assertIn(
                ["claude", "plugin", "install", "engineering-assistant@engineering-assistant-local", "--scope", "user"],
                commands,
            )

            commands.clear()
            updated = _publish_one(
                ROOT,
                "claude-code",
                dry_run=False,
                register=register,
                official_validate=self.official_validation,
                **homes,
            )
            self.assertEqual("published", updated["status"])
            self.assertIn(
                ["claude", "plugin", "update", "engineering-assistant@engineering-assistant-local"],
                commands,
            )

            verified = verify_claude_installation(ROOT, register=register, **homes)
            self.assertEqual("verified", verified["status"])
            removed = uninstall_claude_installation(ROOT, register=register, **homes)
            self.assertEqual("uninstalled", removed["status"])
            self.assertTrue(target.is_dir())

    def test_claude_code_dry_run_uses_strict_marketplace_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            commands: list[list[str]] = []

            def register(command: list[str], _environment=None) -> dict:
                commands.append(command)
                return {"status": "passed"}

            report = _publish_one(
                ROOT,
                "claude-code",
                codex_home=home / ".codex",
                hermes_home=home / ".hermes",
                claude_home=home / ".claude",
                dry_run=True,
                register=register,
            )
            self.assertEqual("dry_run_passed", report["status"])
            self.assertEqual(["claude", "plugin", "validate"], commands[0][:3])
            self.assertEqual("--strict", commands[0][-1])
            self.assertFalse((home / ".claude").exists())

    def test_official_validator_cannot_mutate_final_staging_after_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)

            def mutating_validator(_repository: Path, package: Path, **_kwargs) -> dict:
                manifest = json.loads(
                    (Path(package) / "package-manifest.json").read_text(encoding="utf-8")
                )
                plugin = Path(package) / ".codex-plugin/plugin.json"
                plugin.write_text("{}\n", encoding="utf-8")
                return {
                    "status": "passed",
                    "codex_payload_digest": manifest["payload_digest"],
                }

            with self.assertRaisesRegex(Exception, "payload|digest|hash|摘要"):
                _publish_one(
                    ROOT,
                    "codex",
                    codex_home=home / ".codex",
                    hermes_home=home / ".hermes",
                    dry_run=True,
                    official_validate=mutating_validator,
                )

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
