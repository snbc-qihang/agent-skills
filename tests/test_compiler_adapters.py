from __future__ import annotations

import json
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.tools.compiler import build_package, verify_package  # noqa: E402
import engineering_assistant.tools.compiler as compiler_module  # noqa: E402
from engineering_assistant.runtime.artifact_io import ArtifactIO, artifact_fs  # noqa: E402
from engineering_assistant.runtime.validation import ValidationFailure  # noqa: E402
from engineering_assistant.runtime.catalog import load_catalog  # noqa: E402
from engineering_assistant.runtime.version import platform_version  # noqa: E402


def reseal_package_fixture(package: Path) -> dict:
    """Rebind deliberate fixture mutations so semantic guards are exercised."""
    path = package / "package-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    files = compiler_module._file_digests(package, exclude={"package-manifest.json"})
    manifest["payload_files"] = files
    manifest["payload_digest"] = "sha256:" + hashlib.sha256(
        "\n".join(f"{name}:{digest}" for name, digest in files.items()).encode()).hexdigest()
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def native_v1_fixture(package: Path, *, cachebuster: str | None = None) -> dict:
    """Full native 2.0/v1 contract with a real host binary, never qualification."""
    from engineering_assistant.installer.installation import environment_key
    build_package(ROOT, "codex", package, codex_cachebuster=cachebuster)
    path = package / "package-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    requirements = (package / "engineering-assistant/runtime-requirements.txt").read_bytes()
    digest = hashlib.sha256(requirements).hexdigest()
    lock = {"schema_version": "1", "agent": "codex", "target": manifest["target"],
            "canonical_version": manifest["canonical_version"], "python_version": "3.13.13",
            "requirements_digest": digest,
            "environment_key": environment_key(manifest["canonical_version"], "3.13.13", digest, manifest["target"])}
    (package / "engineering-assistant/runtime-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (package / "engineering-assistant/runtime-python-downloads.json").unlink()
    (package / "engineering-assistant/runtime-core.json").unlink()
    manifest["runtime_environment_key"] = lock["environment_key"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return reseal_package_fixture(package)


class CompilerAdapterTests(unittest.TestCase):
    def test_native_v1_package_keeps_strict_verification_but_is_not_preparable_as_v2(self):
        from engineering_assistant.installer.installation import _package_lock
        package = self.root / "legacy-native-v1"
        expected = native_v1_fixture(package)
        self.assertEqual("2.0", expected["build_format_version"])
        self.assertEqual(expected, verify_package(package))
        with self.assertRaisesRegex(ValidationFailure, "artifact"):
            _package_lock(package)

    def test_native_v1_resealed_wrong_key_or_mixed_fields_are_rejected(self):
        package = self.root / "legacy-native-v1"
        native_v1_fixture(package)
        path = package / "engineering-assistant/runtime-lock.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        for replacement in ({"environment_key": "b" * 64}, {"python_artifact_digest": "a" * 64}, {"schema_version": "3"}):
            with self.subTest(replacement=tuple(replacement)):
                path.write_text(json.dumps({**original, **replacement}), encoding="utf-8")
                reseal_package_fixture(package)
                with self.assertRaises(ValidationFailure):
                    verify_package(package)

    def test_native_v1_resealed_changed_requirements_are_rejected(self):
        package = self.root / "legacy-native-v1"
        native_v1_fixture(package)
        path = package / "engineering-assistant/runtime-requirements.txt"
        path.write_bytes(path.read_bytes() + b"\n# changed dependency contract\n")
        reseal_package_fixture(package)
        with self.assertRaisesRegex(ValidationFailure, "dependency"):
            verify_package(package)

    def test_native_v1_resealed_invalid_native_binary_is_rejected(self):
        package = self.root / "legacy-native-v1"
        manifest = native_v1_fixture(package)
        executable = "ea.exe" if manifest["target"] == "windows-x64" else "ea"
        (package / "engineering-assistant/bin" / executable).write_bytes(b"not a native executable")
        reseal_package_fixture(package)
        with self.assertRaisesRegex(ValidationFailure, "machine header"):
            verify_package(package)

    def test_native_v2_resealed_package_still_requires_python_metadata(self):
        package = self.root / "native-v2"
        build_package(ROOT, "codex", package)
        (package / "engineering-assistant/runtime-python-downloads.json").unlink()
        reseal_package_fixture(package)
        with self.assertRaises(ValidationFailure):
            verify_package(package)

    def test_native_runtime_fixture_keeps_venv_under_private_data(self) -> None:
        package = self.root / "private-runtime-fixture"
        build_package(ROOT, "codex", package)
        _launcher, environment = self.native_runtime_fixture(package)
        data = Path(environment["ENGINEERING_ASSISTANT_DATA_HOME"])
        lock = json.loads((package / "engineering-assistant/runtime-lock.json").read_text())
        binding = json.loads((data / "bindings/codex" / (lock["environment_key"] + ".json")).read_text())
        self.assertTrue(Path(binding["environment"]).is_relative_to(data))
        self.assertTrue(Path(binding["python"]).is_relative_to(Path(binding["environment"])))

    def test_hermes_native_git_metadata_never_exempts_plugin_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary).resolve() / "hermes"
            build_package(ROOT, "hermes", package)
            metadata = package / ".git"
            metadata.mkdir()
            (metadata / "config").write_text("native clone metadata", encoding="utf-8")
            verify_package(package)
            (package / "plugin.yaml").write_text("tampered plugin", encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "payload"):
                verify_package(package)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def native_runtime_fixture(self, package: Path) -> tuple[Path, dict[str, str]]:
        """Current test Python checks launcher protocols, not the pinned install contract."""
        core = package / "engineering-assistant"
        lock = json.loads((core / "runtime-lock.json").read_text(encoding="utf-8"))
        # This deliberately exercises the legacy protocol contract with the
        # current test Python. The v2 pinned artifact is qualified by prepare.
        lock["schema_version"] = "1"
        (core / "runtime-lock.json").write_text(json.dumps(lock), encoding="utf-8")
        data = self.root / "launcher-unit-data"
        from engineering_assistant.installer.installation import _normalize_new_windows_environment, _storage
        storage = _storage(data)
        try:
            from engineering_assistant.installer.shared_core import prepare_core
            prepare_core(package, storage)
            environment = data / "environments/launcher-unit-python"
            if not environment.exists():
                storage.ensure_directory("environments", "launcher-unit-python")
                venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(environment)
                if os.name == "nt":
                    _normalize_new_windows_environment(environment)
            python = environment / ("Scripts/python.exe" if lock["target"] == "windows-x64" else "bin/python")
            binding = {
                "schema_version": "1", "agent": lock["agent"], "target": lock["target"],
                "environment_key": lock["environment_key"], "canonical_version": lock["canonical_version"],
                "environment": str(environment), "python": str(python), "uv": str(Path(sys.executable).absolute()),
                "test_fixture": "current_test_python_not_installation_qualification",
            }
            storage.create_immutable_json(binding, "bindings", lock["agent"], lock["environment_key"] + ".json")
        finally:
            storage.close()
        launcher = core / "bin" / ("ea.exe" if lock["target"] == "windows-x64" else "ea")
        self.assertTrue(launcher.is_file())
        return launcher, {**os.environ, "ENGINEERING_ASSISTANT_DATA_HOME": str(data)}

    def test_replace_rejects_repository_ancestors_before_deletion(self) -> None:
        repository = self.root / "repository"
        repository.mkdir()

        with mock.patch(
            "engineering_assistant.tools.compiler.load_catalog",
            return_value=object(),
        ), self.assertRaisesRegex(ValidationFailure, "outside"):
            build_package(repository, "codex", self.root, replace=True)

    def test_replace_only_accepts_an_intact_builder_owned_package(self) -> None:
        arbitrary = self.root / "arbitrary"
        arbitrary.mkdir()
        marker = arbitrary / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValidationFailure, "non-destructive"):
            build_package(ROOT, "codex", arbitrary, replace=True)
        self.assertEqual("keep", marker.read_text(encoding="utf-8"))

        managed = self.root / "managed"
        build_package(ROOT, "codex", managed)
        manifest_before = (managed / "package-manifest.json").read_bytes()
        with self.assertRaisesRegex(ValidationFailure, "non-destructive"):
            build_package(ROOT, "codex", managed, replace=True)
        self.assertEqual(
            manifest_before,
            (managed / "package-manifest.json").read_bytes(),
        )

    def test_build_never_writes_into_a_replaced_output_directory(self) -> None:
        output = self.root / "swapped-output"
        marker = output / "unrelated.txt"
        original_copy = ArtifactIO.copy_contents_to

        def replace_output_during_copy(
            source,
            destination,
            *,
            max_file_bytes,
            **kwargs,
        ):
            if destination.artifact_root.name == output.name:
                output.rename(self.root / "held-build-output")
                output.mkdir()
                marker.write_text("unrelated", encoding="utf-8")
            return original_copy(
                source,
                destination,
                max_file_bytes=max_file_bytes,
                **kwargs,
            )

        with mock.patch.object(
            ArtifactIO,
            "copy_contents_to",
            new=replace_output_during_copy,
        ), self.assertRaisesRegex(ValidationFailure, "output directory identity"):
            build_package(ROOT, "codex", output)

        self.assertEqual("unrelated", marker.read_text(encoding="utf-8"))

    def test_build_never_cleans_a_replaced_temporary_directory(self) -> None:
        output = self.root / "safe-output"
        marker = self.root / "replacement-marker.txt"
        original_remove = ArtifactIO.remove_all_contents
        replaced = False

        def replace_temporary_directory_before_cleanup(artifact_io):
            nonlocal replaced
            temporary_root = artifact_io.artifact_root
            if (
                not replaced
                and temporary_root.name.startswith(
                    ".engineering-assistant-build-"
                )
            ):
                replaced = True
                temporary_root.rename(self.root / "held-temporary-build")
                temporary_root.mkdir()
                marker.write_text("unrelated", encoding="utf-8")
            return original_remove(artifact_io)

        with mock.patch.object(
            ArtifactIO,
            "remove_all_contents",
            new=replace_temporary_directory_before_cleanup,
        ):
            build_package(ROOT, "codex", output)

        self.assertTrue(replaced)
        self.assertEqual("unrelated", marker.read_text(encoding="utf-8"))
        self.assertTrue(output.is_dir())

    def test_build_uses_bound_working_directory_after_temp_name_replacement(self) -> None:
        output = self.root / "bound-output"
        marker = self.root / "replacement-build-marker.txt"
        original_compile = compiler_module._compile_package
        attack_attempted = False

        def replace_temporary_root_before_compile(*args, **kwargs):
            nonlocal attack_attempted
            temporary_roots = list(
                self.root.glob(".engineering-assistant-build-*")
            )
            self.assertEqual(1, len(temporary_roots))
            temporary_root = temporary_roots[0]
            held = self.root / "held-build-before-compile"
            if os.name == "nt":
                # NTFS keeps the parent in place while the package child is open.
                identity = (temporary_root / "package").stat()
                with self.assertRaises(PermissionError) as denied:
                    temporary_root.rename(held)
                self.assertEqual(5, denied.exception.winerror)
                retained = artifact_fs.fstat(args[2]._root_fd)
                current = (temporary_root / "package").stat()
                self.assertEqual((identity.st_dev, identity.st_ino), (current.st_dev, current.st_ino))
                self.assertEqual((retained.st_dev, retained.st_ino), (current.st_dev, current.st_ino))
                self.assertFalse(held.exists())
            else:
                temporary_root.rename(held)
                temporary_root.mkdir()
            marker.write_text("unrelated", encoding="utf-8")
            attack_attempted = True
            return original_compile(*args, **kwargs)

        with mock.patch.object(
            compiler_module,
            "_compile_package",
            new=replace_temporary_root_before_compile,
        ):
            build_package(ROOT, "codex", output)

        self.assertTrue(attack_attempted)
        self.assertEqual("unrelated", marker.read_text(encoding="utf-8"))
        verify_package(output)

    def test_platform_packages_have_the_same_core(self) -> None:
        claude = self.root / "claude-code"
        codex = self.root / "codex"
        hermes = self.root / "hermes"
        build_package(ROOT, "claude-code", claude)
        codex_report = build_package(ROOT, "codex", codex)
        build_package(ROOT, "hermes", hermes)
        for package in (claude, codex, hermes):
            for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
                self.assertEqual((ROOT / name).read_bytes(), (package / name).read_bytes())
        self.assertEqual(11, codex_report["skill_count"])
        self.assertTrue((claude / ".claude-plugin/plugin.json").is_file())
        self.assertTrue((codex / ".codex-plugin/plugin.json").is_file())
        self.assertTrue((codex / ".mcp.json").is_file())
        self.assertTrue((codex / "hooks/hooks.json").is_file())
        self.assertTrue((codex / "hooks/feedback_capture.py").is_file())
        self.assertTrue((hermes / "plugin.yaml").is_file())
        self.assertTrue((hermes / "__init__.py").is_file())
        self.assertEqual(11, len(list((claude / "skills").glob("*/SKILL.md"))))
        self.assertEqual(11, len(list((codex / "skills").glob("*/SKILL.md"))))
        self.assertEqual(11, len(list((hermes / "skills").glob("*/SKILL.md"))))
        self.assertFalse((codex / "engineering-assistant/generator").exists())
        self.assertFalse(any(path.name == ".DS_Store" for path in claude.rglob("*")))
        self.assertFalse(any(path.name == ".DS_Store" for path in codex.rglob("*")))
        self.assertFalse(any(path.name == ".DS_Store" for path in hermes.rglob("*")))
        verify_package(claude)
        verify_package(codex)
        verify_package(hermes)

        codex_manifest = json.loads((codex / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual("./.mcp.json", codex_manifest["mcpServers"])
        mcp_config = json.loads((codex / ".mcp.json").read_text(encoding="utf-8"))
        target = codex_report["target"]
        executable = "ea.exe" if target == "windows-x64" else "ea"
        self.assertEqual(
            ["mcp-serve"],
            mcp_config["mcpServers"]["engineering-assistant"]["args"][-1:],
        )
        self.assertEqual(
            f"./engineering-assistant/bin/{executable}",
            mcp_config["mcpServers"]["engineering-assistant"]["command"],
        )
        self.assertEqual(".", mcp_config["mcpServers"]["engineering-assistant"]["cwd"])

        claude_manifest = json.loads(
            (claude / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual("engineering-assistant", claude_manifest["name"])
        claude_mcp = json.loads((claude / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(
            "${CLAUDE_PLUGIN_ROOT}/engineering-assistant/bin/" + executable,
            claude_mcp["mcpServers"]["engineering-assistant"]["command"],
        )

        hermes_manifest = (hermes / "plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("provides_tools:", hermes_manifest)
        self.assertIn("engineering_assistant_route", hermes_manifest)
        self.assertIn("provides_hooks:", hermes_manifest)
        hooks = json.loads((codex / "hooks/hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"},
            set(hooks["hooks"]),
        )
        for event_name in ("PreToolUse", "PostToolUse"):
            groups = hooks["hooks"][event_name]
            self.assertEqual(
                "^mcp__engineering_assistant__engineering_assistant_.*$",
                groups[0]["matcher"],
            )
            command = groups[0]["hooks"][0]["command"]
            self.assertEqual('"${PLUGIN_ROOT}/engineering-assistant/bin/ea" hook', command)
            from engineering_assistant.platforms.adapters.codex import windows_hook_command
            self.assertEqual(windows_hook_command(), groups[0]["hooks"][0]["commandWindows"])
        for event_name in ("UserPromptSubmit", "Stop"):
            self.assertNotIn("matcher", hooks["hooks"][event_name][0])

        claude_hooks = json.loads((claude / "hooks/hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(set(hooks["hooks"]), set(claude_hooks["hooks"]))
        for event_name in ("PreToolUse", "PostToolUse"):
            self.assertEqual(
                "^mcp__plugin_engineering-assistant_engineering-assistant__engineering_assistant_.*$",
                claude_hooks["hooks"][event_name][0]["matcher"],
            )
            handler = claude_hooks["hooks"][event_name][0]["hooks"][0]
            self.assertEqual("${CLAUDE_PLUGIN_ROOT}/engineering-assistant/bin/" + executable, handler["command"])
            self.assertEqual(["hook"], handler["args"])

        hook_source = (codex / "hooks/feedback_capture.py").read_text(encoding="utf-8")
        self.assertLess(
            hook_source.index("read_gate_input"),
            hook_source.index("engineering_assistant.runtime.feedback"),
        )

        hook_project = self.root / "codex-hook-project"
        hook_project.mkdir()
        hook_payload = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "transcript_path": None,
            "cwd": str(hook_project),
            "hook_event_name": "Stop",
            "model": "test",
            "permission_mode": "default",
            "stop_hook_active": False,
            "last_assistant_message": "当前被测试失败阻断。",
        }
        ordinary_payload = {
            **hook_payload,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "解释这个普通 Python 函数。",
        }
        ordinary_payload.pop("last_assistant_message")
        ordinary_payload.pop("stop_hook_active")
        ordinary_run = subprocess.run(
            [sys.executable, str(codex / "hooks/feedback_capture.py")],
            input=json.dumps(ordinary_payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, ordinary_run.returncode, ordinary_run.stderr)
        self.assertEqual({}, json.loads(ordinary_run.stdout))
        ordinary_pre_payload = {
            **hook_payload,
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git status --short"},
            "tool_use_id": "ordinary-tool",
        }
        ordinary_pre_payload.pop("last_assistant_message")
        ordinary_pre_payload.pop("stop_hook_active")
        ordinary_pre = subprocess.run(
            [sys.executable, str(codex / "hooks/feedback_capture.py")],
            input=json.dumps(ordinary_pre_payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, ordinary_pre.returncode, ordinary_pre.stderr)
        self.assertEqual({}, json.loads(ordinary_pre.stdout))
        ordinary_stop = subprocess.run(
            [sys.executable, str(codex / "hooks/feedback_capture.py")],
            input=json.dumps(hook_payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, ordinary_stop.returncode, ordinary_stop.stderr)
        self.assertEqual({}, json.loads(ordinary_stop.stdout))
        self.assertFalse(
            (hook_project / ".run-artifacts/engineering-assistant").exists()
        )

        claude_hook = claude / "hooks/feedback_capture.py"
        claude_payload = {
            "session_id": "claude-hook-session",
            "prompt_id": "claude-hook-prompt",
            "cwd": str(hook_project),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "解释这个普通 Python 函数。",
        }
        claude_run = subprocess.run(
            [sys.executable, str(claude_hook)],
            input=json.dumps(claude_payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, claude_run.returncode, claude_run.stderr)
        self.assertEqual({}, json.loads(claude_run.stdout))
        self.assertFalse(
            (hook_project / ".run-artifacts/engineering-assistant").exists()
        )
        invalid_claude = subprocess.run(
            [sys.executable, str(claude_hook)],
            input=json.dumps({"hook_event_name": "Stop"}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, invalid_claude.returncode, invalid_claude.stderr)
        self.assertEqual({}, json.loads(invalid_claude.stdout))
        activation_payload = {
            **hook_payload,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "使用已安装的 engineering-assistant 插件，对当前仓库执行只读评审。",
        }
        activation_payload.pop("last_assistant_message")
        activation_payload.pop("stop_hook_active")
        activation_run = subprocess.run(
            [sys.executable, str(codex / "hooks/feedback_capture.py")],
            input=json.dumps(activation_payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            0,
            activation_run.returncode,
            activation_run.stdout + activation_run.stderr,
        )
        self.assertIn("hookSpecificOutput", json.loads(activation_run.stdout))
        ledgers = list(
            (
                hook_project
                / ".run-artifacts/engineering-assistant/usage-observations"
            ).rglob("turn-*.json")
        )
        self.assertEqual(1, len(ledgers))

        packaged_events = [
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "mcp__codegraph__codegraph_explore",
                "tool_input": {"query": "auth"},
                "tool_use_id": "index-1",
            },
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "mcp__codegraph__codegraph_explore",
                "tool_input": {"query": "acl"},
                "tool_use_id": "index-2",
            },
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git status --short"},
                "tool_use_id": "shell-1",
            },
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git status --short"},
                "tool_use_id": "shell-2",
            },
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git status --short"},
                "tool_use_id": "shell-1",
                "tool_response": {"output": "x" * 70_000},
            },
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git diff --stat"},
                "tool_use_id": "shell-3",
            },
        ]
        for event in packaged_events:
            payload = {
                key: value
                for key, value in {**hook_payload, **event}.items()
                if key not in {"last_assistant_message", "stop_hook_active"}
            }
            run = subprocess.run(
                [sys.executable, str(codex / "hooks/feedback_capture.py")],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertEqual({}, json.loads(run.stdout))
            self.assertNotIn("permissionDecision", run.stdout)
            self.assertNotIn("deny", run.stdout.casefold())

        observation = json.loads(ledgers[0].read_text(encoding="utf-8"))
        self.assertEqual(2, observation["index_queries"])
        self.assertGreater(observation["output_bytes"], 64_000)
        self.assertIn("duplicate_call", observation["signals"])
        self.assertIn("index_query_reference_exceeded", observation["signals"])
        self.assertIn("output_reference_exceeded", observation["signals"])

        ledgers[0].write_text("{", encoding="utf-8")
        corrupt_run = subprocess.run(
            [sys.executable, str(codex / "hooks/feedback_capture.py")],
            input=json.dumps(
                {
                    key: value
                    for key, value in {
                        **hook_payload,
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Bash",
                        "tool_input": {"command": "git log -1"},
                        "tool_use_id": "shell-after-corruption",
                    }.items()
                    if key not in {"last_assistant_message", "stop_hook_active"}
                }
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            0,
            corrupt_run.returncode,
            corrupt_run.stdout + corrupt_run.stderr,
        )
        corrupt_response = json.loads(corrupt_run.stdout)
        self.assertEqual({}, corrupt_response)
        hook_run = subprocess.run(
            [sys.executable, str(codex / "hooks/feedback_capture.py")],
            input=json.dumps(hook_payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, hook_run.returncode, hook_run.stdout + hook_run.stderr)
        self.assertEqual({}, json.loads(hook_run.stdout))
        self.assertEqual(
            1,
            len(
                list(
                    (
                        hook_project
                        / ".run-artifacts/engineering-assistant/feedback/events"
                    ).glob("*.json")
                )
            ),
        )

        continuation_project = self.root / "codex-continuation-project"
        continuation_project.mkdir()

        def run_continuation_prompt(prompt: str, turn_id: str) -> dict:
            completed = subprocess.run(
                [sys.executable, str(codex / "hooks/feedback_capture.py")],
                input=json.dumps(
                    {
                        "session_id": "continuation-session",
                        "turn_id": turn_id,
                        "cwd": str(continuation_project),
                        "hook_event_name": "UserPromptSubmit",
                        "prompt": prompt,
                        "model": "test",
                        "permission_mode": "default",
                    }
                ),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            return json.loads(completed.stdout)

        self.assertIn(
            "hookSpecificOutput",
            run_continuation_prompt(
                "使用 engineering-assistant 插件评审当前 diff。",
                "continuation-turn-1",
            ),
        )
        self.assertEqual(
            {},
            run_continuation_prompt(
                "刚才的评审不对，请改为同时检查性能。",
                "continuation-turn-2",
            ),
        )
        self.assertEqual(
            {},
            run_continuation_prompt(
                "请改为解释这个普通 Python 函数。",
                "continuation-turn-3",
            ),
        )
        self.assertEqual(
            {},
            run_continuation_prompt(
                "刚才的解释不对，请改为逐行说明。",
                "continuation-turn-4",
            ),
        )
        self.assertEqual(
            1,
            len(
                list(
                    (
                        continuation_project
                        / ".run-artifacts/engineering-assistant/usage-observations"
                    ).rglob("turn-*.json")
                )
            ),
        )

        for source in sorted((ROOT / "skills").glob("*/SKILL.md")):
            relative = source.relative_to(ROOT / "skills")
            self.assertEqual(source.read_bytes(), (codex / "skills" / relative).read_bytes())
            self.assertEqual(source.read_bytes(), (hermes / "skills" / relative).read_bytes())

    def test_repeated_build_is_byte_deterministic(self) -> None:
        first = build_package(ROOT, "codex", self.root / "first")
        second = build_package(ROOT, "codex", self.root / "second")
        self.assertEqual(first["payload_digest"], second["payload_digest"])
        self.assertEqual(first["payload_files"], second["payload_files"])

    def test_packaged_codex_hook_fails_open_when_gate_or_runtime_cannot_load(
        self,
    ) -> None:
        codex = self.root / "codex"
        build_package(ROOT, "codex", codex)
        hook = codex / "hooks/feedback_capture.py"
        gate = (
            codex
            / "engineering-assistant/runtime/engineering_assistant/runtime/hook_gate.py"
        )
        feedback = (
            codex
            / "engineering-assistant/runtime/engineering_assistant/runtime/feedback.py"
        )
        payload = {
            "session_id": "fail-open-session",
            "turn_id": "fail-open-turn",
            "cwd": str(self.root / "project"),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "使用已安装的 engineering-assistant 插件执行评审。",
        }

        def run_hook() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(hook)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )

        gate_source = gate.read_text(encoding="utf-8")
        gate.write_text("raise RuntimeError('broken gate')\n", encoding="utf-8")
        broken_gate = run_hook()
        self.assertEqual(0, broken_gate.returncode, broken_gate.stderr)
        self.assertEqual({}, json.loads(broken_gate.stdout))

        gate.write_text(gate_source, encoding="utf-8")
        feedback.write_text("raise RuntimeError('broken runtime')\n", encoding="utf-8")
        broken_runtime = run_hook()
        self.assertEqual(0, broken_runtime.returncode, broken_runtime.stderr)
        self.assertEqual({}, json.loads(broken_runtime.stdout))

    def test_packaged_codex_hook_is_scoped_to_plugin_tools_and_finalizes_each_call(
        self,
    ) -> None:
        codex = self.root / "codex-scoped-hook"
        build_package(ROOT, "codex", codex)
        hooks = json.loads((codex / "hooks/hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"},
            set(hooks["hooks"]),
        )
        self.assertEqual(
            {
                "^mcp__engineering_assistant__engineering_assistant_.*$",
            },
            {
                group["matcher"]
                for event_name in ("PreToolUse", "PostToolUse")
                for groups in (hooks["hooks"][event_name],)
                for group in groups
            },
        )
        matcher = next(
            group["matcher"]
            for event_name in ("PreToolUse", "PostToolUse")
            for groups in (hooks["hooks"][event_name],)
            for group in groups
        )
        self.assertIsNotNone(
            re.search(
                matcher,
                "mcp__engineering_assistant__engineering_assistant_route",
            )
        )
        for unrelated_tool in (
            "Bash",
            "apply_patch",
            "mcp__filesystem__read_file",
            "mcp__other__mcp__engineering_assistant__engineering_assistant_route",
            "mcp__engineering-assistant__engineering_assistant_route",
        ):
            self.assertIsNone(re.search(matcher, unrelated_tool), unrelated_tool)

        project = self.root / "codex-scoped-hook-project"
        project.mkdir()
        hook = codex / "hooks/feedback_capture.py"
        base = {
            "session_id": "scoped-session",
            "turn_id": "scoped-turn",
            "cwd": str(project),
            "model": "test",
            "permission_mode": "default",
            "tool_name": "mcp__engineering_assistant__engineering_assistant_route",
            "tool_input": {"intent": {"task_kind": "review"}},
            "tool_use_id": "scoped-tool",
        }
        for payload in (
            {**base, "hook_event_name": "PreToolUse"},
            {
                **base,
                "hook_event_name": "PostToolUse",
                "tool_response": {"status": "failed", "error": "provider failed"},
            },
        ):
            completed = subprocess.run(
                [sys.executable, str(hook)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
                env={
                    **os.environ,
                    "ENGINEERING_ASSISTANT_OBSERVE_OUTPUT_BYTES": "1",
                },
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual({}, json.loads(completed.stdout))

        self.assertEqual(
            [],
            list(
                (
                    project
                    / ".run-artifacts/engineering-assistant/usage-observations"
                ).rglob("turn-*.json")
            ),
        )
        self.assertEqual(
            1,
            len(
                list(
                    (
                        project
                        / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
                    ).glob("*.json")
                )
            ),
        )
        efficiency_candidate = json.loads(
            next(
                (
                    project
                    / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
                ).glob("*.json")
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("tool_hook", efficiency_candidate["source"])
        self.assertEqual(
            1,
            len(
                list(
                    (
                        project
                        / ".run-artifacts/engineering-assistant/feedback/captures"
                    ).glob("*.json")
                )
            ),
        )
        events = list(
            (
                project
                / ".run-artifacts/engineering-assistant/feedback/events"
            ).glob("*.json")
        )
        self.assertEqual(1, len(events))
        event = json.loads(events[0].read_text(encoding="utf-8"))
        disposition_path = self.root / "feedback-disposition.json"
        disposition_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "disposition_id": "feedback-disposition-" + "f" * 24,
                    "event_id": event["event_id"],
                    "decision": "accepted_for_evolution",
                    "reason": "packaged vertical regression",
                    "actor_ref": "packaged-test-reviewer",
                    "evidence_refs": [],
                    "reusable_candidate": True,
                    "decided_at": "2026-07-14T08:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        launcher, native_environment = self.native_runtime_fixture(codex)
        disposition = subprocess.run(
            [
                str(launcher),
                "feedback-disposition",
                "--project-root",
                str(project),
                "--input",
                str(disposition_path),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=native_environment,
        )
        self.assertEqual(0, disposition.returncode, disposition.stdout + disposition.stderr)
        evolution = subprocess.run(
            [
                str(launcher),
                "feedback-evolution-export",
                "--project-root",
                str(project),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=native_environment,
        )
        self.assertEqual(0, evolution.returncode, evolution.stdout + evolution.stderr)
        evolution_payload = json.loads(evolution.stdout)
        self.assertEqual(1, evolution_payload["proposal_count"])
        self.assertFalse(evolution_payload["proposals"][0]["formal_assets_modified"])

    def test_packaged_hermes_hook_failure_does_not_break_tools_or_skills(self) -> None:
        hermes = self.root / "hermes-fail-open"
        build_package(ROOT, "hermes", hermes)
        feedback = (
            hermes
            / "engineering-assistant/runtime/engineering_assistant/runtime/feedback.py"
        )
        feedback.write_text("raise RuntimeError('broken hook runtime')\n", encoding="utf-8")
        script = """
import importlib.util, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('hermes_fail_open_fixture', root / '__init__.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class Context:
    def __init__(self):
        self.tools = []
        self.hooks = []
        self.skills = []
    def register_tool(self, **kwargs): self.tools.append(kwargs['name'])
    def register_hook(self, name, handler): self.hooks.append(name)
    def register_skill(self, name, path): self.skills.append(name)
context = Context()
module.register(context)
print(json.dumps({'tools': len(context.tools), 'hooks': context.hooks, 'skills': len(context.skills)}))
"""

        completed = subprocess.run(
            [sys.executable, "-c", script, str(hermes)],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        registered = json.loads(completed.stdout)
        self.assertGreater(registered["tools"], 0)
        self.assertEqual(["post_llm_call"], registered["hooks"])
        self.assertEqual(11, registered["skills"])

    def test_manifest_uses_supported_platform_fields_and_build_manifest_preserves_canonical_version(self) -> None:
        output = self.root / "codex-version"
        build_package(ROOT, "codex", output)
        manifest = json.loads((output / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        catalog = load_catalog(ROOT)
        self.assertEqual(platform_version(catalog.version, supports_four_part=False), manifest["version"])
        self.assertEqual(
            {"name": "sunliming625@gmail.com", "email": "sunliming625@gmail.com"},
            manifest["author"],
        )
        self.assertNotIn("canonical_version", manifest)
        self.assertNotIn("skill_versions", manifest)
        self.assertTrue(manifest["interface"]["longDescription"])
        self.assertEqual("sunliming625@gmail.com", manifest["interface"]["developerName"])
        self.assertEqual(3, len(manifest["interface"]["defaultPrompt"]))

        build_manifest = json.loads((output / "package-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog.version, build_manifest["canonical_version"])
        self.assertEqual(11, len(build_manifest["skill_versions"]))
        self.assertEqual({skill.id: skill.version for skill in catalog.skills.values()}, build_manifest["skill_versions"])
        for name in (
            "strategic-modeling.md",
            "tactical-modeling.md",
            "model-artifact.md",
            "scenario-traceability.md",
        ):
            relative = f"skills/domain-modeling/references/{name}"
            self.assertTrue((output / relative).is_file())
            self.assertIn(relative, build_manifest["payload_files"])

    def test_compiled_runtime_routes_and_serves_mcp_without_author_tools(self) -> None:
        output = self.root / "runtime-smoke"
        build_package(ROOT, "codex", output)
        launcher, native_environment = self.native_runtime_fixture(output)
        runtime = output / "engineering-assistant"
        self.assertFalse((runtime / "evals").exists())
        self.assertFalse((runtime / "runtime/engineering_assistant/tools").exists())
        self.assertFalse((runtime / "runtime/engineering_assistant/installer").exists())
        intent = dict(task_kind="review", requested_outcome="只读评审", scope=["fixture"],
                      risk_signals=["security"], requested_external_actions=[], confirmed_actions=[],
                      confidence=.99, evidence=["明确只读"], read_only=True)
        for read_only, decision in ((True, "proceed"), (False, "confirm")):
            routed = subprocess.run([str(launcher), "route", "--intent", "-"],
                input=json.dumps({**intent, "read_only": read_only}), text=True,
                capture_output=True, check=False, env=native_environment)
            self.assertEqual(0, routed.returncode, routed.stdout + routed.stderr)
            self.assertEqual(decision, json.loads(routed.stdout)["decision"]["decision"])

        messages = "\n".join(
            json.dumps(message)
            for message in [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ]
        ) + "\n"
        mcp = subprocess.run(
            [str(launcher), "mcp-serve"],
            input=messages,
            text=True,
            capture_output=True,
            check=False,
            env=native_environment,
        )
        self.assertEqual(0, mcp.returncode, mcp.stdout + mcp.stderr)
        responses = [json.loads(line) for line in mcp.stdout.splitlines()]
        self.assertEqual([1, 2], [response["id"] for response in responses])
        tool_names = {item["name"] for item in responses[1]["result"]["tools"]}
        self.assertEqual(17, len(tool_names))
        self.assertIn("engineering_assistant_artifact_validate", tool_names)
        self.assertIn("engineering_assistant_investigation_decide", tool_names)

    def test_packaged_hermes_runtime_has_no_host_trust_binding(self) -> None:
        output = self.root / "hermes-host-trust"
        build_package(ROOT, "hermes", output)
        script = r"""
import importlib.util
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location('hermes_host_trust_fixture', root / '__init__.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps({
    'has_trust': hasattr(module, '_TRUST'),
    'has_host_kernel': any(name == 'engineering_assistant' or name.startswith('_ea_runtime_') for name in sys.modules),
}))
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(output)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        loaded = json.loads(result.stdout)
        self.assertFalse(loaded["has_trust"])
        self.assertFalse(loaded["has_host_kernel"])

    def test_packaged_hermes_tools_emit_nonblocking_efficiency_feedback(self) -> None:
        output = self.root / "hermes-efficiency"
        build_package(ROOT, "hermes", output)

        class Context:
            def __init__(self) -> None:
                self.tools = {}
                self.hooks = {}

            def register_tool(self, **kwargs) -> None:
                self.tools[kwargs["name"]] = kwargs

            def register_skill(self, _name, _path) -> None:
                return None

            def register_hook(self, name, handler) -> None:
                self.hooks[name] = handler

        spec = importlib.util.spec_from_file_location(
            "compiled_hermes_efficiency", output / "__init__.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _launcher, native_environment = self.native_runtime_fixture(output)
        binding = mock.patch.dict(os.environ, {
            "ENGINEERING_ASSISTANT_DATA_HOME": native_environment["ENGINEERING_ASSISTANT_DATA_HOME"],
        })
        binding.start()
        self.addCleanup(binding.stop)
        context = Context()
        module.register(context)
        project = self.root / "hermes-efficiency-project"
        project.mkdir()
        arguments = {
            "intent": {
                "task_kind": "review",
                "requested_outcome": "评审当前变更。",
                "scope": ["diff"],
                "risk_signals": [],
                "requested_external_actions": [],
                "confirmed_actions": [],
                "confidence": 0.99,
                "evidence": ["用户请求"],
            }
        }
        handler = context.tools["engineering_assistant_route"]["handler"]

        first = handler(
            arguments,
            session_id="hermes-efficiency-session",
            task_id="hermes-efficiency-task",
            cwd=str(project),
        )
        second = handler(
            arguments,
            session_id="hermes-efficiency-session",
            task_id="hermes-efficiency-task",
            cwd=str(project),
        )
        for payload in (first, second):
            response = json.loads(payload)
            self.assertIn("decision", response, payload)
            self.assertEqual("review", response["decision"]["flow_id"])
        context.hooks["post_llm_call"](
            "hermes-efficiency-session",
            "使用 engineering-assistant 插件评审当前变更。",
            "评审完成。",
            [],
            "test",
            "hermes",
            cwd=str(project),
            task_id="hermes-efficiency-task",
            turn_id="hermes-efficiency-turn",
        )

        candidates = list(
            (
                project
                / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
            ).glob("*.json")
        )
        self.assertEqual(1, len(candidates))
        candidate = json.loads(candidates[0].read_text(encoding="utf-8"))
        self.assertEqual(2, candidate["tool_calls"])
        self.assertEqual(0, candidate["shell_calls"])
        self.assertEqual(0, candidate["index_queries"])
        self.assertIn("duplicate_call", candidate["signals"])
        self.assertEqual(["hermes_plugin_tool"], candidate["coverage"])
        self.assertEqual("post_llm_call", candidate["source"])

        # The real native bridge uses test Python; fixed Python qualification has its own gate.
        for mode, expected_captures in (("disabled", 0), ("metadata", 2)):
            mode_project = self.root / f"hermes-{mode}-project"
            mode_project.mkdir()
            mode_task = f"hermes-{mode}-task"
            handler(
                arguments, session_id="hermes-mode-session", task_id=mode_task,
                cwd=str(mode_project), feedback_mode=mode,
            )
            self.assertIsNone(context.hooks["post_llm_call"](
                "hermes-mode-session", "使用 engineering-assistant 插件评审当前变更。",
                "评审完成。", [], "test", "hermes", cwd=str(mode_project),
                task_id=mode_task, turn_id=mode_task, feedback_mode=mode,
            ))
            artifact_root = mode_project / ".run-artifacts/engineering-assistant"
            self.assertEqual([], list((artifact_root / "usage-observations").rglob("*.json")))
            self.assertEqual(expected_captures, len(list((artifact_root / "feedback/captures").glob("*.json"))))

    def test_hermes_adapter_registers_runtime_tools_from_the_same_kernel(self) -> None:
        output = self.root / "hermes-runtime"
        build_package(ROOT, "hermes", output)

        class Context:
            def __init__(self) -> None:
                self.tools = {}
                self.skills = {}
                self.hooks = {}

            def register_tool(self, **kwargs) -> None:
                self.tools[kwargs["name"]] = kwargs

            def register_skill(self, name, path) -> None:
                self.skills[name] = path

            def register_hook(self, name, handler) -> None:
                self.hooks[name] = handler

        spec = importlib.util.spec_from_file_location(
            "compiled_engineering_assistant", output / "__init__.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _launcher, native_environment = self.native_runtime_fixture(output)
        binding = mock.patch.dict(os.environ, {
            "ENGINEERING_ASSISTANT_DATA_HOME": native_environment["ENGINEERING_ASSISTANT_DATA_HOME"],
        })
        binding.start()
        self.addCleanup(binding.stop)
        context = Context()
        module.register(context)
        self.assertEqual(17, len(context.tools))
        self.assertIn("engineering_assistant_artifact_validate", context.tools)
        self.assertIn("engineering_assistant_investigation_decide", context.tools)
        plugin_lines = (output / "plugin.yaml").read_text(encoding="utf-8").splitlines()
        start = plugin_lines.index("provides_tools:") + 1
        end = plugin_lines.index("provides_hooks:")
        declared_tools = {line.removeprefix("  - ") for line in plugin_lines[start:end]}
        self.assertEqual(set(context.tools), declared_tools)
        self.assertEqual(11, len(context.skills))
        self.assertEqual({"post_llm_call"}, set(context.hooks))
        payload = context.tools["engineering_assistant_route"]["handler"](
            {
                "intent": {
                    "task_kind": "review",
                    "requested_outcome": "评审变更。",
                    "scope": ["diff"],
                    "risk_signals": [],
                    "requested_external_actions": [],
                    "confirmed_actions": [],
                    "confidence": 0.95,
                    "evidence": ["用户请求"],
                }
            }
        )
        response = json.loads(payload)
        self.assertIn("decision", response, payload)
        self.assertEqual("review", response["decision"]["flow_id"])

        project = self.root / "hermes-project"
        project.mkdir()
        context.hooks["post_llm_call"](
            "session-1",
            "补充要求：不要增加新依赖。",
            "当前被测试失败阻断。",
            [],
            "test",
            "cli",
            cwd=str(project),
        )
        self.assertFalse(
            (project / ".run-artifacts/engineering-assistant").exists()
        )

        context.hooks["post_llm_call"](
            "session-1",
            "使用 $engineering-assistant:code-review，补充要求：不要增加新依赖。",
            "当前被测试失败阻断。",
            [],
            "test",
            "cli",
            cwd=str(project),
            turn_id="turn-1",
        )
        self.assertEqual(
            2,
            len(
                list(
                    (
                        project
                        / ".run-artifacts/engineering-assistant/feedback/events"
                    ).glob("*.json")
                )
            ),
        )
        class ExplodingString:
            def __str__(self) -> str:
                raise RuntimeError("host metadata cannot be stringified")

        hostile_session = ExplodingString()
        fail_open_payload = context.tools["engineering_assistant_route"]["handler"](
            {
                "intent": {
                    "task_kind": "review",
                    "requested_outcome": "评审变更。",
                    "scope": ["diff"],
                    "risk_signals": [],
                    "requested_external_actions": [],
                    "confirmed_actions": [],
                    "confidence": 0.95,
                    "evidence": ["用户请求"],
                }
            },
            session_id=hostile_session,
            turn_id="turn-hostile",
        )
        response = json.loads(fail_open_payload)
        self.assertIn("decision", response, fail_open_payload)
        self.assertEqual("review", response["decision"]["flow_id"])
        self.assertIsNone(
            context.hooks["post_llm_call"](
                hostile_session,
                "使用 $engineering-assistant:code-review 完成评审。",
                "评审完成。",
                [],
                "test",
                "cli",
                cwd=str(project),
                turn_id="turn-hostile",
            )
        )

        tool_project = self.root / "hermes-tool-project"
        tool_project.mkdir()
        context.tools["engineering_assistant_route"]["handler"](
            {
                "intent": {
                    "task_kind": "review",
                    "requested_outcome": "评审变更。",
                    "scope": ["diff"],
                    "risk_signals": [],
                    "requested_external_actions": [],
                    "confirmed_actions": [],
                    "confidence": 0.95,
                    "evidence": ["用户请求"],
                }
            },
            session_id="session-2",
            turn_id="turn-2",
        )
        context.hooks["post_llm_call"](
            "session-2",
            "补充要求：不要增加新依赖。",
            "当前被测试失败阻断。",
            [],
            "test",
            "cli",
            cwd=str(tool_project),
            turn_id="turn-2",
        )
        self.assertEqual(
            2,
            len(
                list(
                    (
                        tool_project
                        / ".run-artifacts/engineering-assistant/feedback/events"
                    ).glob("*.json")
                )
            ),
        )
        production_kwargs_project = self.root / "hermes-production-kwargs"
        production_kwargs_project.mkdir()
        context.tools["engineering_assistant_route"]["handler"](
            {
                "intent": {
                    "task_kind": "review",
                    "requested_outcome": "评审变更。",
                    "scope": ["diff"],
                    "risk_signals": [],
                    "requested_external_actions": [],
                    "confirmed_actions": [],
                    "confidence": 0.95,
                    "evidence": ["用户请求"],
                }
            },
            session_id="session-production",
            task_id="task-production",
            user_task="评审变更",
        )
        context.hooks["post_llm_call"](
            "session-production",
            "补充要求：不要增加新依赖。",
            "当前被测试失败阻断。",
            [],
            "test",
            "cli",
            cwd=str(production_kwargs_project),
            task_id="task-production",
            turn_id="turn-production",
        )
        self.assertEqual(
            2,
            len(
                list(
                    (
                        production_kwargs_project
                        / ".run-artifacts/engineering-assistant/feedback/events"
                    ).glob("*.json")
                )
            ),
        )
        context.hooks["post_llm_call"](
            "session-production",
            "刚才的评审不对，请改为同时检查性能。",
            "已经补充性能检查。",
            [],
            "test",
            "cli",
            cwd=str(production_kwargs_project),
            task_id="task-production-followup",
            turn_id="turn-production-followup",
        )
        self.assertEqual(
            2,
            len(
                list(
                    (
                        production_kwargs_project
                        / ".run-artifacts/engineering-assistant/feedback/events"
                    ).glob("*.json")
                )
            ),
        )

        context.hooks["post_llm_call"](
            "session-production",
            "解释这个普通 Python 函数。",
            "这是逐行解释。",
            [],
            "test",
            "cli",
            cwd=str(production_kwargs_project),
            task_id="task-production-ordinary",
            turn_id="turn-production-ordinary",
        )
        context.hooks["post_llm_call"](
            "session-production",
            "刚才的解释不对，请改为逐行说明。",
            "已经修改解释。",
            [],
            "test",
            "cli",
            cwd=str(production_kwargs_project),
            task_id="task-production-later",
            turn_id="turn-production-later",
        )
        self.assertEqual(
            2,
            len(
                list(
                    (
                        production_kwargs_project
                        / ".run-artifacts/engineering-assistant/feedback/events"
                    ).glob("*.json")
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()
