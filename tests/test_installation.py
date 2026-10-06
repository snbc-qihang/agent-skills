from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from contextlib import contextmanager, redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class InstallationTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX ownership/mode contract")
    def test_preparation_rejects_an_existing_nonprivate_data_directory(self):
        from engineering_assistant.installation import _storage
        from engineering_assistant.validation import ValidationFailure
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary).resolve() / "public-data"
            data.mkdir(mode=0o777)
            data.chmod(0o777)
            with self.assertRaisesRegex(ValidationFailure, "private"):
                _storage(data)
            self.assertEqual(0o777, data.stat().st_mode & 0o777)

    def test_setup_cli_reports_unsupported_host_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            result = subprocess.run(
                [sys.executable, "-m", "engineering_assistant.setup_cli", "doctor",
                 "--agent", "codex", "--data-home", str(home), "--target", "unknown", "--json"],
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                capture_output=True, text=True,
            )
            self.assertEqual("unsupported", json.loads(result.stdout)["status"])
            self.assertNotEqual(0, result.returncode)
            self.assertEqual([], list(home.iterdir()))

    def test_agent_home_uses_explicit_then_platform_environment(self):
        from engineering_assistant.installation import agent_home
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            environment = {"CODEX_HOME": str(root / "环境 目录")}
            self.assertEqual(root / "明确 目录", agent_home("codex", root / "明确 目录", environment))
            self.assertEqual(root / "环境 目录", agent_home("codex", environment=environment))

    def test_binding_key_changes_when_runtime_or_product_version_changes(self):
        from engineering_assistant.installation import environment_key
        key = environment_key("2.3.0.0-rc.1", "3.13.13", "a" * 64, "macos-arm64")
        self.assertRegex(key, r"^[0-9a-f]{64}$")
        self.assertNotEqual(key, environment_key("2.3.0.0-rc.2", "3.13.13", "a" * 64, "macos-arm64"))
        self.assertNotEqual(key, environment_key("2.3.0.0-rc.1", "3.13.14", "a" * 64, "macos-arm64"))

    def test_environment_failure_preserves_existing_version_binding(self):
        from engineering_assistant.installation import prepare_runtime
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            data = root / "data"
            from engineering_assistant.installation import _storage
            _storage(data).close()
            (data / "bindings").mkdir(parents=True)
            binding = data / "bindings/codex.json"
            previous = b'{"previous":"active"}\n'
            binding.write_bytes(previous)
            with mock.patch("engineering_assistant.installation.verify_package", return_value={
                "platform": "codex", "canonical_version": "2.3.0.0-rc.1", "target": "macos-arm64",
            }), mock.patch("engineering_assistant.installation.host_target", return_value="macos-arm64"), mock.patch(
                "engineering_assistant.installation._create_environment", side_effect=RuntimeError("fixture sync failed")
            ), mock.patch("engineering_assistant.installation._uv", return_value=Path(sys.executable)):
                from engineering_assistant.installation import runtime_lock, python_download_metadata
                lock, requirements = runtime_lock(ROOT, "codex", "macos-arm64", "2.3.0.0-rc.1")
                runtime = root / "package/engineering-assistant"
                runtime.mkdir(parents=True)
                (runtime / "runtime-lock.json").write_text(json.dumps(lock), encoding="utf-8")
                (runtime / "runtime-requirements.txt").write_bytes(requirements)
                (runtime / "runtime-python-downloads.json").write_bytes(python_download_metadata(lock))
                with self.assertRaisesRegex(RuntimeError, "sync failed"):
                    prepare_runtime(root / "package", data_home=data, uv_executable=sys.executable)
            self.assertEqual(previous, binding.read_bytes())

    def test_doctor_does_not_count_an_unprepared_package_as_ready(self):
        from engineering_assistant.installation import doctor
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch("engineering_assistant.installation.host_target", return_value="macos-arm64"), mock.patch(
                "engineering_assistant.installation.verify_package", return_value={
                    "platform": "codex", "canonical_version": "2.3.0.0-rc.1", "target": "macos-arm64",
                }
            ):
                result = doctor("codex", package=root / "package", data_home=root / "data")
            self.assertEqual("needs_preparation", result["status"])
            self.assertFalse(result["ready"])

    def test_home_config_precedence_and_source_data_rejection(self):
        from engineering_assistant.installation import agent_home, _storage
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {"agent_homes": {"hermes": str(root / "config")}}
            self.assertEqual(root / "config", agent_home("hermes", environment={}, config=config))
            self.assertEqual(root / "env", agent_home("hermes", environment={"HERMES_HOME": str(root / "env")}, config=config))
        from engineering_assistant.validation import ValidationFailure
        forbidden = ROOT / "never-create-runtime-data"
        with self.assertRaises(ValidationFailure):
            _storage(forbidden)
        self.assertFalse(forbidden.exists())

    def test_protocol_output_limit_and_timeout_are_enforced(self):
        from engineering_assistant.installation import _protocol_run
        from engineering_assistant.validation import ValidationFailure
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            with self.assertRaisesRegex((ValidationFailure, OSError), "bounded|limit"):
                _protocol_run([sys.executable, "-c", "print('x'*1100000)"], cwd=cwd)
            with self.assertRaises((ValidationFailure, subprocess.TimeoutExpired)):
                _protocol_run([sys.executable, "-c", "import time;time.sleep(5)"], cwd=cwd, timeout=1)

    def test_protocol_requires_the_expected_cli_exit_code(self):
        from engineering_assistant.installation import _protocol_run
        from engineering_assistant.validation import ValidationFailure
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            command = [sys.executable, "-c", "print('{}'); raise SystemExit(2)"]
            with self.assertRaises(ValidationFailure):
                _protocol_run(command, cwd=cwd)
            self.assertEqual({}, json.loads(_protocol_run(command, cwd=cwd, expected_exit_code=2)))
            with self.assertRaises(ValidationFailure):
                _protocol_run([sys.executable, "-c", "print('{}')"], cwd=cwd, expected_exit_code=2)

    def test_failed_final_repair_check_restores_the_original_environment(self):
        from engineering_assistant.installation import prepare_runtime, runtime_lock, python_download_metadata
        from engineering_assistant.validation import ValidationFailure
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = root / "package"
            runtime = package / "engineering-assistant"
            runtime.mkdir(parents=True)
            lock, requirements = runtime_lock(ROOT, "codex", "macos-arm64", "2.3.0.0-rc.1")
            (runtime / "runtime-lock.json").write_text(json.dumps(lock), encoding="utf-8")
            (runtime / "runtime-requirements.txt").write_bytes(requirements)
            (runtime / "runtime-python-downloads.json").write_bytes(python_download_metadata(lock))
            data = root / "data"
            from engineering_assistant.installation import _storage
            _storage(data).close()
            environment = data / "environments" / lock["environment_key"]
            environment.mkdir(parents=True)
            marker = environment / "original.txt"
            marker.write_text("retain original", encoding="utf-8")
            checks = {"provider": {"qualified": True}}
            with mock.patch("engineering_assistant.installation.verify_package", return_value={
                "platform": "codex", "canonical_version": lock["canonical_version"], "target": "macos-arm64",
            }), mock.patch("engineering_assistant.installation.host_target", return_value="macos-arm64"), mock.patch(
                "engineering_assistant.installation._uv", return_value=Path(sys.executable)
            ), mock.patch("engineering_assistant.installation._create_environment"), mock.patch(
                "engineering_assistant.installation._verify_interpreter", side_effect=[ValidationFailure("broken fixture"), None]
            ), mock.patch("engineering_assistant.installation._protocol_checks", side_effect=[checks, ValidationFailure("final path rejected")]):
                with self.assertRaisesRegex(ValidationFailure, "final path"):
                    prepare_runtime(package, data_home=data, repair=True, publish_default=False)
            self.assertEqual("retain original", marker.read_text(encoding="utf-8"))
            self.assertFalse((data / "bindings/codex.json").exists())


    def test_failed_repair_cannot_rollback_a_successful_newer_writer(self):
        from engineering_assistant import installation as inst
        from engineering_assistant.artifact_io import ArtifactIO
        from engineering_assistant.validation import ValidationFailure
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = root / "package"
            runtime = package / "engineering-assistant"
            runtime.mkdir(parents=True)
            lock, requirements = inst.runtime_lock(ROOT, "codex", "macos-arm64", "2.3.0.0-rc.1")
            (runtime / "runtime-lock.json").write_text(json.dumps(lock), encoding="utf-8")
            (runtime / "runtime-requirements.txt").write_bytes(requirements)
            (runtime / "runtime-python-downloads.json").write_bytes(inst.python_download_metadata(lock))
            data = root / "data"
            inst._storage(data).close()
            environment = data / "environments" / lock["environment_key"]
            environment.mkdir(parents=True)
            (environment / "generation.txt").write_text("original broken", encoding="utf-8")
            generations, intervened = [], [False]
            original_transaction = ArtifactIO.transaction

            def create(staging, *_args):
                generation = "A" if not generations else "B"
                generations.append(generation)
                (staging / "generation.txt").write_text(generation, encoding="utf-8")

            def verify(python, *_args, **_kwargs):
                if (python.parent.parent / "generation.txt").read_text(encoding="utf-8") == "original broken":
                    raise ValidationFailure("original broken")

            def checks(_package, *, python=None, data=None):
                if python is not None:
                    candidate = python.parent.parent
                    if candidate.parent.name == "environments" and (candidate / "generation.txt").read_text(encoding="utf-8") == "A":
                        raise ValidationFailure("A final path fails")
                return {"provider": {"qualified": True}}

            @contextmanager
            def interleaving(storage, *parts, **kwargs):
                try:
                    with original_transaction(storage, *parts, **kwargs):
                        yield
                except ValidationFailure as error:
                    # B acquires the same key immediately after A releases it.
                    # A must restore its own failed generation before that release.
                    if str(error) == "A final path fails" and not intervened[0]:
                        intervened[0] = True
                        result = inst.prepare_runtime(package, data_home=data, repair=True, publish_default=False)
                        self.assertEqual("prepared", result["status"])
                        self.assertEqual("B", (environment / "generation.txt").read_text(encoding="utf-8"))
                    raise

            with mock.patch.object(inst, "verify_package", return_value={
                "platform": "codex", "canonical_version": lock["canonical_version"], "target": "macos-arm64",
            }), mock.patch.object(inst, "host_target", return_value="macos-arm64"), mock.patch.object(
                inst, "_uv", return_value=Path(sys.executable)
            ), mock.patch.object(inst, "_create_environment", side_effect=create), mock.patch.object(
                inst, "_verify_interpreter", side_effect=verify
            ), mock.patch.object(inst, "_protocol_checks", side_effect=checks), mock.patch.object(
                ArtifactIO, "transaction", new=interleaving
            ):
                with self.assertRaisesRegex(ValidationFailure, "A final path"):
                    inst.prepare_runtime(package, data_home=data, repair=True, publish_default=False)
            self.assertTrue(intervened[0])
            self.assertEqual("B", (environment / "generation.txt").read_text(encoding="utf-8"))


class NativeInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "agent"
        self.home.mkdir()
        self.manifests = {}
        self.verifier = mock.patch("engineering_assistant.installation.verify_package",
            side_effect=lambda path: self.manifests[Path(path).resolve()])
        self.verifier.start()
        self.addCleanup(self.verifier.stop)
        transport = mock.patch("engineering_assistant.installation._command", return_value="{}")
        transport.start()
        self.addCleanup(transport.stop)

    def package(self, path, agent="codex", version="2.3.0-rc.1+build.0", digest="a"):
        path.mkdir(parents=True)
        self.manifests[path.resolve()] = {"platform": agent, "canonical_version": "2.3.0.0-rc.1",
            "target": "macos-arm64", "payload_digest": "sha256:" + digest * 64}
        manifest_dir = ".codex-plugin" if agent == "codex" else ".claude-plugin"
        (path / manifest_dir).mkdir()
        (path / manifest_dir / "plugin.json").write_text(json.dumps({"name": "engineering-assistant", "version": version}))
        (path / "package-manifest.json").write_text("{}")
        return path

    def codex_entry(self, marketplace="selected", version="2.3.0-rc.1+build.0"):
        return {"name": "engineering-assistant", "pluginId": "engineering-assistant@" + marketplace,
            "marketplaceName": marketplace, "version": version, "installed": True, "enabled": True}

    def test_discovery_uses_native_installed_identity_instead_of_newer_cache(self):
        from engineering_assistant.installation import find_package
        selected = self.package(self.home / "plugins/cache/selected/engineering-assistant/2.3.0-rc.1+build.0")
        stale = self.package(self.home / "plugins/cache/unselected/engineering-assistant/9.0.0", version="9.0.0")
        os.utime(stale, ns=(2_000_000_000_000_000_000,) * 2)
        with mock.patch("engineering_assistant.installation._native_query", create=True,
                        return_value={"installed": [self.codex_entry()], "available": []}):
            self.assertEqual(selected, find_package("codex", self.home))

    def test_discovery_requires_explicit_marketplace_when_sources_conflict(self):
        from engineering_assistant.installation import find_package
        from engineering_assistant.validation import ValidationFailure
        with mock.patch("engineering_assistant.installation._native_query", create=True,
                return_value={"installed": [self.codex_entry("first"), self.codex_entry("second")]}):
            with self.assertRaisesRegex(ValidationFailure, "ambiguous"):
                find_package("codex", self.home)

    def test_claude_discovery_uses_user_install_path_and_exact_version(self):
        from engineering_assistant.installation import find_package
        selected = self.package(self.root / "native selection", agent="claude-code")
        entry = {"id": "engineering-assistant@selected", "scope": "user", "version": "2.3.0-rc.1+build.0",
                 "installPath": str(selected), "enabled": True}
        with mock.patch("engineering_assistant.installation._native_query", create=True, return_value=[entry]):
            self.assertEqual(selected, find_package("claude-code", self.home))
        entry["version"] = "9.0.0"
        with mock.patch("engineering_assistant.installation._native_query", create=True, return_value=[entry]):
            from engineering_assistant.validation import ValidationFailure
            with self.assertRaisesRegex(ValidationFailure, "version"):
                find_package("claude-code", self.home)

    def test_codex_update_prepares_available_candidate_before_native_selection(self):
        from engineering_assistant.installation import update_plugin
        current = self.package(self.home / "plugins/cache/selected/engineering-assistant/2.3.0-rc.1+build.0")
        candidate = self.package(self.root / "candidate")
        entry = self.codex_entry()
        available = {**entry, "source": {"source": "local", "path": str(candidate)}}
        events = []
        def query(_agent, arguments, _home):
            return {"available": [available]} if "--available" in arguments else {"installed": [entry]}
        with mock.patch("engineering_assistant.installation._native_query", create=True, side_effect=query), mock.patch(
            "engineering_assistant.installation._native_call", create=True, side_effect=lambda _a, args, _h: events.append(args)
        ), mock.patch("engineering_assistant.installation.prepare_runtime", side_effect=lambda path, **kw: events.append(["prepare", path])), mock.patch(
            "engineering_assistant.installation.doctor", return_value={"status": "ready"}
        ):
            result = update_plugin("codex", self.home, "selected")
        self.assertEqual("ready", result["status"])
        self.assertEqual(["plugin", "marketplace", "upgrade", "selected"], events[0])
        self.assertEqual(["prepare", candidate], events[1])
        self.assertEqual(["plugin", "add", "engineering-assistant@selected", "--json"], events[2])

    def test_failed_candidate_preparation_never_selects_native_release(self):
        from engineering_assistant.installation import update_plugin
        self.package(self.home / "plugins/cache/selected/engineering-assistant/2.3.0-rc.1+build.0")
        candidate = self.package(self.root / "candidate")
        entry = self.codex_entry()
        with mock.patch("engineering_assistant.installation._native_query", create=True, side_effect=lambda a, args, h:
            {"available": [{**entry, "source": {"source": "local", "path": str(candidate)}}]} if "--available" in args else {"installed": [entry]}
        ), mock.patch("engineering_assistant.installation._native_call", create=True) as native, mock.patch(
            "engineering_assistant.installation.prepare_runtime", side_effect=RuntimeError("sync failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "sync failed"):
                update_plugin("codex", self.home, "selected")
        self.assertEqual(1, native.call_count)
        self.assertIn("upgrade", native.call_args.args[1])

    def test_hermes_update_requires_candidate_before_native_mutation(self):
        from engineering_assistant.installation import update_plugin
        from engineering_assistant.validation import ValidationFailure
        with mock.patch("engineering_assistant.installation._native_call", create=True) as native:
            with self.assertRaisesRegex(ValidationFailure, "candidate"):
                update_plugin("hermes", self.home)
            native.assert_not_called()

    def test_setup_install_parser_accepts_explicit_distribution(self):
        from engineering_assistant.setup_cli import build_parser
        arguments = build_parser().parse_args(["install", "--agent", "codex", "--source", "example/distribution@v1", "--marketplace", "selected"])
        self.assertEqual("example/distribution@v1", arguments.source)

    def test_setup_update_returns_verified_native_result_without_second_prepare(self):
        from engineering_assistant.setup_cli import main
        with mock.patch("engineering_assistant.installation.update_plugin", return_value={"status": "ready"}) as update, mock.patch(
            "engineering_assistant.setup_cli.prepare_runtime"
        ) as prepare, mock.patch("engineering_assistant.setup_cli.find_package") as discover, redirect_stdout(io.StringIO()):
            self.assertEqual(0, main(["update", "--agent", "codex", "--agent-home", str(self.home), "--marketplace", "selected"]))
        prepare.assert_not_called()
        discover.assert_not_called()
        self.assertEqual("selected", update.call_args.kwargs["marketplace"])

    def test_codex_candidate_can_be_in_installed_catalogue_with_an_older_cache_version(self):
        from engineering_assistant.installation import _candidate_package
        candidate = self.package(self.root / "candidate", version="2.4.0+build.0")
        entry = {**self.codex_entry(version="2.3.0+build.0"), "source": {"source": "local", "path": str(candidate)}}
        with mock.patch("engineering_assistant.installation._native_query", return_value={"installed": [entry], "available": []}):
            self.assertEqual(candidate, _candidate_package("codex", self.home, "selected"))

    def test_claude_update_reads_refreshed_snapshot_and_prepares_before_selection(self):
        from engineering_assistant.installation import update_plugin
        current = self.package(self.root / "current", agent="claude-code")
        snapshot = self.root / "snapshot"
        candidate = self.package(snapshot / "plugins/engineering-assistant", agent="claude-code")
        (snapshot / ".claude-plugin").mkdir()
        manifest = snapshot / ".claude-plugin/marketplace.json"
        manifest.write_text(json.dumps({"name": "selected", "plugins": [{"name": "engineering-assistant", "source": "./plugins/engineering-assistant"}]}))
        events = []
        def query(_agent, arguments, _home):
            if "marketplace" in arguments:
                return [{"name": "selected", "installLocation": str(snapshot)}]
            return [{"id": "engineering-assistant@selected", "scope": "user", "version": "2.3.0-rc.1+build.0", "installPath": str(current), "enabled": True}]
        with mock.patch("engineering_assistant.installation._native_query", side_effect=query), mock.patch(
            "engineering_assistant.installation._native_call", side_effect=lambda a, args, h: events.append(args)
        ), mock.patch("engineering_assistant.installation.prepare_runtime", side_effect=lambda path, **kw: events.append(["prepare", path])), mock.patch(
            "engineering_assistant.installation.doctor", return_value={"status": "ready"}
        ):
            self.assertEqual("ready", update_plugin("claude-code", self.home)["status"])
        self.assertEqual(["plugin", "marketplace", "update", "selected"], events[0])
        self.assertEqual(["prepare", candidate], events[1])
        self.assertEqual(["plugin", "update", "engineering-assistant@selected", "--scope", "user"], events[2])
        manifest.write_text(json.dumps({"name": "selected", "plugins": [{"name": "engineering-assistant", "source": "../../outside"}]}))
        with mock.patch("engineering_assistant.installation._native_query", side_effect=query), mock.patch(
            "engineering_assistant.installation._native_call"
        ) as native, mock.patch("engineering_assistant.installation.prepare_runtime") as prepare:
            from engineering_assistant.validation import ValidationFailure
            with self.assertRaisesRegex(ValidationFailure, "inside"):
                update_plugin("claude-code", self.home)
        prepare.assert_not_called()
        self.assertEqual(1, native.call_count)

    def test_failed_hermes_update_preserves_a_verified_previous_selection(self):
        from engineering_assistant.installation import update_plugin
        from engineering_assistant.validation import ValidationFailure
        self.package(self.home / "plugins/engineering-assistant", agent="hermes", digest="b")
        candidate = self.package(self.root / "candidate", agent="hermes", digest="a")
        entry = {"name": "engineering-assistant", "version": "2.3.0-rc.1+build.0", "status": "enabled", "source": "user"}
        events = []
        with mock.patch("engineering_assistant.installation._native_query", return_value=[entry]), mock.patch(
            "engineering_assistant.installation._native_call", side_effect=lambda a, args, h: events.append(args)
        ), mock.patch("engineering_assistant.installation.prepare_runtime", side_effect=lambda path, **kw: events.append(["prepare", path])), mock.patch(
            "engineering_assistant.installation.doctor"
        ) as doctor:
            result = update_plugin("hermes", self.home, package=candidate)
        self.assertEqual("failed", result["status"])
        self.assertTrue(result["recovery_required"])
        self.assertEqual("previous_selection_retained", result["native_state"])
        self.assertEqual([["prepare", candidate], ["plugins", "update", "engineering-assistant"]], events)
        doctor.assert_not_called()

    def test_native_update_error_rechecks_side_effects_without_claiming_rollback(self):
        from engineering_assistant.installation import update_plugin
        from engineering_assistant.validation import ValidationFailure
        current = self.package(self.home / "plugins/cache/selected/engineering-assistant/2.3.0-rc.1+build.0", digest="b")
        candidate = self.package(self.root / "candidate", digest="a")
        entry, mutated = self.codex_entry(), [False]
        def query(_agent, arguments, _home):
            if "--available" in arguments:
                return {"available": [{**entry, "source": {"source": "local", "path": str(candidate)}}]}
            return {"installed": [entry]}
        def native(_agent, arguments, _home):
            if arguments[:2] == ["plugin", "add"]:
                self.manifests[current.resolve()] = self.manifests[candidate.resolve()]
                mutated[0] = True
                raise ValidationFailure("transport failed after side effect")
        with mock.patch("engineering_assistant.installation._native_query", side_effect=query), mock.patch(
            "engineering_assistant.installation._native_call", side_effect=native
        ), mock.patch("engineering_assistant.installation.prepare_runtime"), mock.patch(
            "engineering_assistant.installation.doctor"
        ) as doctor:
            result = update_plugin("codex", self.home, "selected")
        self.assertTrue(mutated[0])
        self.assertEqual("failed", result["status"])
        self.assertTrue(result["recovery_required"])
        self.assertTrue(result["retained_runtime_environments"])
        self.assertEqual("verified_candidate", result["native_state"])
        doctor.assert_not_called()

    def test_unverified_claude_selection_is_disabled_after_native_side_effect(self):
        from engineering_assistant.installation import _verify_selection
        current = self.package(self.root / "current", agent="claude-code", digest="b")
        candidate = self.package(self.root / "candidate", agent="claude-code", digest="a")
        entry = {"id": "engineering-assistant@selected", "scope": "user", "version": "2.3.0-rc.1+build.0",
                 "installPath": str(current), "enabled": True}
        with mock.patch("engineering_assistant.installation._native_query", return_value=[entry]), mock.patch(
            "engineering_assistant.installation._native_call", side_effect=lambda *_args: entry.update(enabled=False)
        ) as native, mock.patch("engineering_assistant.installation.doctor") as doctor:
            result = _verify_selection("claude-code", self.home, "selected", self.manifests[candidate.resolve()],
                                       data=None, hooks_trusted=True)
        self.assertEqual("failed", result["status"])
        self.assertEqual("disabled", result["native_state"])
        self.assertTrue(result["recovery_required"])
        self.assertEqual(["plugin", "disable", "engineering-assistant@selected", "--scope", "user"], native.call_args.args[1])
        doctor.assert_not_called()

    def test_unverified_hermes_update_is_disabled_and_observed_after_mutation(self):
        from engineering_assistant.installation import update_plugin
        current = self.package(self.home / "plugins/engineering-assistant", agent="hermes", digest="b")
        candidate = self.package(self.root / "candidate", agent="hermes", digest="a")
        entry = {"name": "engineering-assistant", "version": "2.3.0-rc.1+build.0", "status": "enabled", "source": "user"}
        events = []
        def native(_agent, arguments, _home):
            events.append(arguments)
            if arguments[1] == "update":
                self.manifests[current.resolve()] = {**self.manifests[current.resolve()], "payload_digest": "sha256:" + "c" * 64}
            elif arguments[1] == "disable":
                entry["status"] = "not enabled"
        with mock.patch("engineering_assistant.installation._native_query", return_value=[entry]), mock.patch(
            "engineering_assistant.installation._native_call", side_effect=native
        ), mock.patch("engineering_assistant.installation.prepare_runtime"):
            result = update_plugin("hermes", self.home, package=candidate)
        self.assertEqual("failed", result["status"])
        self.assertEqual("disabled", result["native_state"])
        self.assertEqual([["plugins", "update", "engineering-assistant"], ["plugins", "disable", "engineering-assistant"]], events)

    def test_windows_hook_probe_executes_verified_manifest_without_shell_interpolation(self):
        from engineering_assistant.installation import _windows_hook_probe
        from engineering_assistant.adapters.codex import windows_hook_command
        package = self.root / "中文 plugin & %"
        (package / "hooks").mkdir(parents=True)
        (package / "hooks/hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "commandWindows": windows_hook_command()}]}]}}))
        powershell = self.root / "SystemRoot/WindowsPowerShell/powershell.exe"
        powershell.parent.mkdir(parents=True)
        powershell.write_bytes(b"fixture")
        request = json.dumps({"prompt": "中文输入"}, ensure_ascii=False).encode()
        with mock.patch("engineering_assistant.installation.shutil.which", return_value=str(powershell)), mock.patch(
            "engineering_assistant.installation._protocol_run", return_value=b"{}"
        ) as run:
            self.assertEqual("passed", _windows_hook_probe(package, self.root, request, {}))
        self.assertEqual(str(powershell), run.call_args.args[0][0])
        self.assertIn("-EncodedCommand", run.call_args.args[0])
        self.assertEqual(str(package), run.call_args.kwargs["environment"]["PLUGIN_ROOT"])
        self.assertEqual(request, run.call_args.kwargs["input_data"])

    def test_windows_hook_probe_missing_shell_or_unknown_manifest_cannot_pass(self):
        from engineering_assistant.installation import _windows_hook_probe
        from engineering_assistant.adapters.codex import windows_hook_command
        from engineering_assistant.validation import ValidationFailure
        package = self.root / "package"
        (package / "hooks").mkdir(parents=True)
        manifest = package / "hooks/hooks.json"
        manifest.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "commandWindows": windows_hook_command()}]}]}}))
        with mock.patch("engineering_assistant.installation.shutil.which", return_value=None), mock.patch(
            "engineering_assistant.installation._protocol_run"
        ) as run:
            with self.assertRaisesRegex(ValidationFailure, "PowerShell"):
                _windows_hook_probe(package, self.root, b"{}", {})
            manifest.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "commandWindows": "unsafe.exe"}]}]}}))
            with self.assertRaisesRegex(ValidationFailure, "Windows Hook"):
                _windows_hook_probe(package, self.root, b"{}", {})
        run.assert_not_called()

    def test_new_windows_staging_owner_normalization_uses_retained_descriptors(self):
        from engineering_assistant.installation import _normalize_new_windows_environment
        staging = self.root / "staging"
        (staging / "Scripts").mkdir(parents=True)
        (staging / "Scripts/python.exe").write_bytes(b"fixture")
        owners = []
        from engineering_assistant.installation import artifact_fs
        filesystem = mock.Mock(wraps=artifact_fs)
        filesystem.O_NOFOLLOW = getattr(artifact_fs, "O_NOFOLLOW", 0)
        filesystem.set_private_owner = mock.Mock(side_effect=lambda fd: owners.append(artifact_fs.fstat(fd).st_mode))
        filesystem.assert_private_directory = mock.Mock()
        with mock.patch("engineering_assistant.installation.artifact_fs", filesystem):
            _normalize_new_windows_environment(staging)
        self.assertEqual(3, len(owners))
        import stat
        self.assertEqual([True, True, False], [stat.S_ISDIR(mode) for mode in owners])

    def test_codex_single_install_prepares_before_native_plugin_add(self):
        from engineering_assistant.installation import install_plugin
        distribution = self.root / "distribution"
        candidate = self.package(distribution / "plugins/engineering-assistant")
        current = self.package(self.home / "plugins/cache/selected/engineering-assistant/2.3.0-rc.1+build.0")
        (distribution / ".agents/plugins").mkdir(parents=True)
        (distribution / ".agents/plugins/marketplace.json").write_text(json.dumps({"name": "selected"}))
        entry, events = self.codex_entry(), []
        def query(_agent, arguments, _home):
            if "marketplace" in arguments:
                return {"marketplaces": [{"name": "selected", "root": str(distribution),
                    "marketplaceSource": {"sourceType": "local", "source": str(distribution)}}]
                    if events else []}
            if "--available" in arguments:
                return {"available": [{**entry, "source": {"source": "local", "path": str(candidate)}}]}
            return {"installed": [entry] if any(event[:2] == ["plugin", "add"] for event in events) else []}
        with mock.patch("engineering_assistant.installation._native_query", side_effect=query), mock.patch(
            "engineering_assistant.installation._native_call", side_effect=lambda a, args, h: events.append(args)
        ), mock.patch("engineering_assistant.installation.prepare_runtime", side_effect=lambda path, **kw: events.append(["prepare", path])), mock.patch(
            "engineering_assistant.installation.doctor", return_value={"status": "needs_trust", "runtime_ready": True}
        ):
            result = install_plugin("codex", str(distribution), home=self.home, marketplace="selected")
        self.assertEqual("needs_trust", result["status"])
        self.assertEqual(["plugin", "marketplace", "add", str(distribution), "--json"], events[0])
        self.assertEqual(["prepare", candidate], events[1])
        self.assertEqual(["plugin", "add", "engineering-assistant@selected", "--json"], events[2])

    def test_claude_install_rejects_same_name_marketplace_from_another_repo_or_ref(self):
        from engineering_assistant.installation import install_plugin
        from engineering_assistant.validation import ValidationFailure
        for repo, ref in (("other/distribution", "v1"), ("example/distribution", "v2")):
            with self.subTest(repo=repo, ref=ref), mock.patch(
                "engineering_assistant.installation._native_query", side_effect=lambda a, args, h:
                    [{"name": "selected", "source": "github", "repo": repo, "ref": ref,
                      "installLocation": str(self.root / "snapshot")}] if "marketplace" in args else []
            ), mock.patch("engineering_assistant.installation._native_call") as native, mock.patch(
                "engineering_assistant.installation.prepare_runtime"
            ) as prepare:
                with self.assertRaisesRegex(ValidationFailure, "source.*differs"):
                    install_plugin("claude-code", "example/distribution@v1", home=self.home, marketplace="selected")
            native.assert_not_called()
            prepare.assert_not_called()

    def test_claude_successful_marketplace_add_cannot_keep_an_unrelated_source(self):
        from engineering_assistant.installation import install_plugin
        from engineering_assistant.validation import ValidationFailure
        snapshot = self.root / "snapshot"
        self.package(snapshot / "plugins/engineering-assistant", agent="claude-code")
        (snapshot / ".claude-plugin").mkdir()
        (snapshot / ".claude-plugin/marketplace.json").write_text(json.dumps({"name": "selected", "plugins": [
            {"name": "engineering-assistant", "source": "./plugins/engineering-assistant"}]}))
        calls = []
        def query(_agent, arguments, _home):
            if "marketplace" in arguments:
                return [{"name": "selected", "source": "github", "repo": "other/distribution", "ref": "v1",
                         "installLocation": str(snapshot)}] if calls else []
            return []
        with mock.patch("engineering_assistant.installation._native_query", side_effect=query), mock.patch(
            "engineering_assistant.installation._native_call", side_effect=lambda a, args, h: calls.append(args)
        ), mock.patch("engineering_assistant.installation.prepare_runtime") as prepare:
            with self.assertRaisesRegex(ValidationFailure, "source.*differs"):
                install_plugin("claude-code", "example/distribution@v1", home=self.home, marketplace="selected")
        self.assertEqual([["plugin", "marketplace", "add", "example/distribution@v1", "--scope", "user"]], calls)
        prepare.assert_not_called()

    def test_codex_install_rejects_different_local_marketplace_root(self):
        from engineering_assistant.installation import install_plugin
        from engineering_assistant.validation import ValidationFailure
        distribution = self.root / "distribution"
        (distribution / ".agents/plugins").mkdir(parents=True)
        (distribution / ".agents/plugins/marketplace.json").write_text(json.dumps({"name": "selected"}))
        with mock.patch("engineering_assistant.installation._native_query", side_effect=lambda a, args, h:
            {"marketplaces": [{"name": "selected", "root": str(self.root / "other")}]} if "marketplace" in args else {"installed": []}
        ), mock.patch("engineering_assistant.installation._native_call") as native, mock.patch(
            "engineering_assistant.installation.prepare_runtime"
        ) as prepare:
            with self.assertRaisesRegex(ValidationFailure, "source.*differs"):
                install_plugin("codex", str(distribution), home=self.home, marketplace="selected")
        native.assert_not_called()
        prepare.assert_not_called()

    def test_codex_remote_install_cross_checks_native_config_and_git_checkout(self):
        from engineering_assistant.installation import install_plugin
        snapshot = self.root / "snapshot"
        candidate = self.package(snapshot / "plugins/engineering-assistant")
        self.package(self.home / "plugins/cache/selected/engineering-assistant/2.3.0-rc.1+build.0")
        (snapshot / ".git").mkdir()
        (snapshot / ".git/HEAD").write_text("a" * 40)
        (snapshot / ".git/config").write_text('[remote "origin"]\nurl = https://github.com/example/distribution.git\n')
        (self.home / "config.toml").write_text('[marketplaces.selected]\nsource_type = "git"\nsource = "https://github.com/example/distribution.git"\nref = "v1"\n')
        events, entry = [], self.codex_entry()
        def query(_agent, arguments, _home):
            if "marketplace" in arguments:
                return {"marketplaces": [{"name": "selected", "root": str(snapshot),
                    "marketplaceSource": {"sourceType": "git", "source": "https://github.com/example/distribution.git"}}]}
            if "--available" in arguments:
                return {"available": [{**entry, "source": {"source": "local", "path": str(candidate)}}]}
            return {"installed": [entry] if any(event[:2] == ["plugin", "add"] for event in events) else []}
        def git(command, **kwargs):
            self.assertNotIn("GIT_DIR", kwargs["environment"])
            self.assertEqual("1", kwargs["environment"]["GIT_CONFIG_NOSYSTEM"])
            return "https://github.com/example/distribution.git" if "config" in command else "a" * 40
        with mock.patch("engineering_assistant.installation._native_query", side_effect=query), mock.patch(
            "engineering_assistant.installation._native_call", side_effect=lambda a, args, h: events.append(args)
        ), mock.patch("engineering_assistant.installation._command", side_effect=git), mock.patch(
            "engineering_assistant.installation.shutil.which", return_value="git"
        ), mock.patch.dict(os.environ, {"GIT_DIR": str(self.root / "unrelated")}), mock.patch(
            "engineering_assistant.installation.prepare_runtime", side_effect=lambda path, **kw: events.append(["prepare", path])
        ), mock.patch("engineering_assistant.installation.doctor", return_value={"status": "needs_trust", "runtime_ready": True}):
            result = install_plugin("codex", "example/distribution@v1", home=self.home, marketplace="selected")
        self.assertTrue(result["runtime_ready"])
        self.assertEqual(["prepare", candidate], events[1])

    def test_codex_git_ref_mismatch_and_unverifiable_config_stop_native_mutations(self):
        from engineering_assistant.installation import install_plugin
        from engineering_assistant.validation import ValidationFailure
        snapshot = self.root / "snapshot"
        snapshot.mkdir()
        entry = {"name": "selected", "root": str(snapshot), "marketplaceSource": {
            "sourceType": "git", "source": "https://github.com/example/distribution.git"}}
        config = self.home / "config.toml"
        config.write_text('[marketplaces.selected]\nsource_type = "git"\nsource = "https://github.com/example/distribution.git"\nref = "wrong"\n')
        with mock.patch("engineering_assistant.installation._native_query", return_value={"marketplaces": [entry]}), mock.patch(
            "engineering_assistant.installation._native_call"
        ) as native, mock.patch("engineering_assistant.installation.prepare_runtime") as prepare:
            with self.assertRaisesRegex(ValidationFailure, "source or ref differs"):
                install_plugin("codex", "example/distribution@v1", home=self.home, marketplace="selected")
            config.unlink()
            result = install_plugin("codex", "example/distribution@v1", home=self.home, marketplace="selected")
        self.assertEqual("unsupported", result["status"])
        self.assertFalse(result["ready"])
        native.assert_not_called()
        prepare.assert_not_called()

    def test_unknown_native_marketplace_source_contract_is_explicitly_unsupported(self):
        from engineering_assistant.installation import install_plugin
        with mock.patch("engineering_assistant.installation._native_query", return_value=[{
            "name": "selected", "source": "future-source", "installLocation": str(self.root / "snapshot")
        }]), mock.patch("engineering_assistant.installation._native_call") as native:
            result = install_plugin("claude-code", "example/distribution@v1", home=self.home, marketplace="selected")
        self.assertEqual("unsupported", result["status"])
        native.assert_not_called()

    def test_codex_git_snapshot_identity_matches_a_real_checkout_and_rejects_head_drift(self):
        from engineering_assistant.installation import _codex_git_snapshot
        from engineering_assistant.validation import ValidationFailure
        import shutil
        git = shutil.which("git")
        self.assertIsNotNone(git, "native distribution qualification requires Git")
        snapshot = self.root / "snapshot"
        repository = "example/distribution"
        expected_url = "https://github.com/" + repository + ".git"
        environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        def run(arguments, cwd=None):
            return subprocess.run([git, *arguments], cwd=cwd, env=environment, check=True, capture_output=True, timeout=15)
        run(["init", "--quiet", str(snapshot)])
        run(["config", "remote.origin.url", expected_url], snapshot)
        commit = ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "--allow-empty", "-m", "fixture"]
        run(commit, snapshot)
        run(["tag", "v1"], snapshot)
        (self.home / "config.toml").write_text('[marketplaces.selected]\nsource_type = "git"\nsource = "' + expected_url + '"\nref = "v1"\n')
        def command(arguments, *, cwd, environment):
            return subprocess.run(arguments, cwd=cwd, env=environment, check=True, capture_output=True, timeout=15).stdout.decode()
        with mock.patch("engineering_assistant.installation._command", side_effect=command):
            _codex_git_snapshot(self.home, "selected", snapshot, repository, "v1")
            run(commit, snapshot)
            with self.assertRaisesRegex(ValidationFailure, "source checkout differs"):
                _codex_git_snapshot(self.home, "selected", snapshot, repository, "v1")

    def test_codex_git_config_is_bounded_and_cannot_be_replaced_by_a_symlink(self):
        from engineering_assistant.installation import _codex_git_snapshot, MAX_CONTROL_BYTES
        from engineering_assistant.validation import ValidationFailure
        config = self.home / "config.toml"
        config.write_bytes(b" " * (MAX_CONTROL_BYTES + 1))
        with self.assertRaises(ValidationFailure):
            _codex_git_snapshot(self.home, "selected", self.root, "example/distribution", "v1")
        config.unlink()
        target = self.root / "outside-control"
        target.write_text("fixture")
        config.symlink_to(target)
        with self.assertRaises(ValidationFailure):
            _codex_git_snapshot(self.home, "selected", self.root, "example/distribution", "v1")

    def test_hermes_install_remains_disabled_when_preparation_fails(self):
        from engineering_assistant.installation import install_plugin
        self.package(self.home / "plugins/engineering-assistant", agent="hermes")
        entry = {"name": "engineering-assistant", "version": "2.3.0-rc.1+build.0", "status": "not enabled", "source": "user"}
        events = []
        with mock.patch("engineering_assistant.installation._native_query", side_effect=[[], [entry]]), mock.patch(
            "engineering_assistant.installation._native_call", side_effect=lambda a, args, h: events.append(args)
        ), mock.patch("engineering_assistant.installation.prepare_runtime", side_effect=RuntimeError("sync failed")):
            with self.assertRaisesRegex(RuntimeError, "sync failed"):
                install_plugin("hermes", "example/distribution", home=self.home)
        self.assertEqual([["plugins", "install", "example/distribution", "--no-enable"]], events)

    def test_install_rejects_author_or_credential_source_without_native_mutation(self):
        from engineering_assistant.installation import install_plugin
        from engineering_assistant.validation import ValidationFailure
        with mock.patch("engineering_assistant.installation._native_call") as native:
            for source in (str(ROOT), "https://user:secret@example.com/distribution.git"):
                with self.assertRaises(ValidationFailure):
                    install_plugin("codex", source, home=self.home, marketplace="selected")
            result = install_plugin("hermes", "example/distribution@v1", home=self.home)
        self.assertEqual("unsupported", result["status"])
        native.assert_not_called()

    def test_native_transport_failure_does_not_disclose_credentials(self):
        from engineering_assistant.installation import _native_call
        from engineering_assistant.validation import ValidationFailure
        with mock.patch("engineering_assistant.local_publish._resolve_platform_cli", return_value="fixture"), mock.patch(
            "engineering_assistant.installation._command", side_effect=RuntimeError("https://user:secret@example.com")
        ):
            with self.assertRaises(ValidationFailure) as error:
                _native_call("codex", ["plugin", "list", "--json"], self.home)
        self.assertNotIn("secret", str(error.exception))

    def test_native_commands_cannot_write_an_agent_home_under_author_source(self):
        from engineering_assistant.installation import _native_call
        from engineering_assistant.validation import ValidationFailure
        with mock.patch("engineering_assistant.installation._command") as command:
            with self.assertRaises(ValidationFailure):
                _native_call("codex", ["plugin", "list", "--json"], ROOT / "never-create-agent-home")
        command.assert_not_called()
        self.assertFalse((ROOT / "never-create-agent-home").exists())

    def test_wrong_explicit_target_stops_before_install_or_update(self):
        from engineering_assistant.setup_cli import main
        with mock.patch("engineering_assistant.installation.install_plugin") as install, mock.patch(
            "engineering_assistant.installation.update_plugin"
        ) as update, redirect_stdout(io.StringIO()):
            for command in ("install", "update"):
                self.assertEqual(2, main([command, "--agent", "codex", "--target", "unknown"]))
        install.assert_not_called()
        update.assert_not_called()

    def test_prepare_rechecks_the_same_native_selection_and_enabled_state(self):
        from engineering_assistant.setup_cli import main
        data = self.root / "data"
        from engineering_assistant.installation import _storage
        _storage(data).close()
        (data / "bindings").mkdir(parents=True)
        (data / "bindings/codex.json").write_text("{}")
        self.package(self.home / "plugins/cache/selected/engineering-assistant/2.3.0-rc.1+build.0")
        entries = {"installed": [self.codex_entry(), self.codex_entry("other")]}
        from engineering_assistant.installation import runtime_lock, _read_control
        lock = runtime_lock(ROOT, "codex", "macos-arm64", "2.3.0.0-rc.1")[0]
        binding = {**lock, "python_build": "20260414", "python_base": str(data / "base"), "python": str(data / "python")}
        with mock.patch("engineering_assistant.installation._native_query", return_value=entries), mock.patch(
            "engineering_assistant.installation.host_target", return_value="macos-arm64"
        ), mock.patch("engineering_assistant.setup_cli.prepare_runtime"), mock.patch(
            "engineering_assistant.installation._protocol_checks", return_value={"provider": {"qualified": True}}
        ), mock.patch("engineering_assistant.installation._package_lock", return_value=lock), mock.patch(
            "engineering_assistant.installation._read_control",
            side_effect=lambda path: binding if "bindings" in path.parts else _read_control(path)
        ), mock.patch("engineering_assistant.installation._verify_interpreter"
        ), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, main(["prepare", "--agent", "codex", "--agent-home", str(self.home),
                "--data-home", str(data), "--marketplace", "selected", "--hooks-trusted"]))
        self.assertEqual("ready", json.loads(output.getvalue())["status"])

    def test_native_uninstall_verifies_removal_and_keeps_runtime_environments(self):
        from engineering_assistant.installation import uninstall
        from engineering_assistant.validation import ValidationFailure
        entries = {"installed": [self.codex_entry()]}
        with mock.patch("engineering_assistant.installation._native_query", side_effect=[entries, {"installed": []}]), mock.patch(
            "engineering_assistant.installation._native_call"
        ) as native:
            result = uninstall("codex", self.home, "selected")
        self.assertEqual("uninstalled", result["status"])
        self.assertTrue(result["retained_runtime_environments"])
        self.assertEqual(["plugin", "remove", "engineering-assistant@selected", "--json"], native.call_args.args[1])
        with mock.patch("engineering_assistant.installation._native_query", return_value=entries), mock.patch(
            "engineering_assistant.installation._native_call"
        ):
            with self.assertRaisesRegex(ValidationFailure, "did not remove"):
                uninstall("codex", self.home, "selected")

    def test_doctor_distinguishes_runtime_checks_trust_and_native_activation(self):
        from engineering_assistant.installation import doctor, runtime_lock
        data = self.root / "data"
        from engineering_assistant.installation import _storage
        _storage(data).close()
        (data / "bindings").mkdir(parents=True)
        (data / "bindings/codex.json").write_text("{}")
        (data / "bindings/hermes.json").write_text("{}")
        codex = self.package(self.root / "codex")
        hermes = self.package(self.root / "hermes", agent="hermes")
        checks = {"provider": {"qualified": True}, "mcp": "passed", "tools_call": "passed", "hook": "passed"}
        def unit_lock(package):
            return runtime_lock(ROOT, "hermes" if package == hermes else "codex", "macos-arm64", "2.3.0.0-rc.1")[0]
        def unit_binding(path):
            lock = runtime_lock(ROOT, path.parent.name, "macos-arm64", "2.3.0.0-rc.1")[0]
            return {**lock, "python_build": "20260414", "python_base": str(data / "base"), "python": str(data / "python")}
        with mock.patch("engineering_assistant.installation.host_target", return_value="macos-arm64"), mock.patch(
            "engineering_assistant.installation._protocol_checks", return_value=checks
        ), mock.patch("engineering_assistant.installation._package_lock", side_effect=unit_lock), mock.patch(
            "engineering_assistant.installation._read_control", side_effect=unit_binding
        ), mock.patch("engineering_assistant.installation._verify_interpreter"), mock.patch("engineering_assistant.installation._native_query") as native:
            untrusted = doctor("codex", package=codex, data_home=data)
            trusted = doctor("codex", package=codex, data_home=data, hooks_trusted=True)
            active = doctor("codex", package=codex, data_home=data, hooks_trusted=True, native_activation_verified=True)
            active_untrusted = doctor("codex", package=codex, data_home=data, native_activation_verified=True)
            inactive = doctor("hermes", package=hermes, data_home=data)
        native.assert_not_called()
        self.assertEqual("needs_preparation", untrusted["status"])
        self.assertEqual("not_verified", untrusted["native_activation"])
        self.assertFalse(untrusted["ready"])
        self.assertTrue(untrusted["runtime_ready"])
        self.assertEqual("user_confirmed", trusted["hook_trust"])
        self.assertEqual("needs_preparation", trusted["status"])
        self.assertTrue(active["ready"])
        self.assertEqual("needs_trust", active_untrusted["status"])
        self.assertEqual("enabled", active_untrusted["native_activation"])
        self.assertEqual("not_executed", active["native_marketplace_session"])
        self.assertEqual("requires_native_activation", inactive["reason"])
        self.assertTrue(inactive["runtime_ready"])


if __name__ == "__main__":
    unittest.main()
