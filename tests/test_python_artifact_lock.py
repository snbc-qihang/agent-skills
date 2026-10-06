from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant import installation as inst
from engineering_assistant.artifact_io import ArtifactIO
from engineering_assistant.validation import ValidationFailure


class PythonArtifactLockTests(unittest.TestCase):
    def lock(self):
        return inst.runtime_lock(ROOT, "codex", "macos-arm64", "2.3.0.0-rc.1")[0]

    def test_same_python_version_with_another_artifact_has_a_different_environment_key(self):
        arguments = ("2.3.0.0-rc.1", "3.13.13", "a" * 64, "macos-arm64")
        self.assertNotEqual(inst.environment_key(*arguments, "b" * 64),
                            inst.environment_key(*arguments, "c" * 64))

    def test_all_native_locks_bind_the_fixed_upstream_artifact(self):
        for target in inst.TARGETS:
            with self.subTest(target=target):
                lock, _ = inst.runtime_lock(ROOT, "codex", target, "2.3.0.0-rc.1")
                self.assertEqual("2", lock["schema_version"])
                artifact = lock["python_artifact"]
                self.assertEqual("20260414", artifact["build"])
                self.assertEqual("cpython", artifact["name"])
                self.assertIsNone(artifact["variant"])
                self.assertRegex(artifact["sha256"], r"^[0-9a-f]{64}$")
                data = inst.python_download_metadata(lock)
                self.assertEqual(lock["python_artifact_digest"], hashlib.sha256(data).hexdigest())
                self.assertEqual({artifact["key"]}, set(json.loads(data)))

    def test_creation_ignores_ambient_selection_and_keeps_old_base_untouched(self):
        lock = self.lock()
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary).resolve()
            old = data / "python/old-build"
            old.mkdir(parents=True)
            marker = old / "keep.txt"
            marker.write_text("retain old base")
            staging = data / "venv"
            staging.mkdir()
            commands = []
            def command(argv, **kwargs):
                commands.append((argv, kwargs))
                if "install" in argv:
                    (Path(kwargs["environment"]["UV_PYTHON_INSTALL_DIR"]) / lock["python_artifact"]["key"].replace("-darwin-", "-macos-")).mkdir()
                return "uv 0.11.7" if argv[-1] == "--version" else ""
            with mock.patch.dict(os.environ, {
                "UV_PYTHON_CPYTHON_BUILD": "20260602", "UV_PYTHON_DOWNLOADS_JSON_URL": "untrusted.json",
                "UV_PYTHON_INSTALL_MIRROR": "https://untrusted.invalid", "UV_CONFIG_FILE": "untrusted.toml",
                "UV_NO_VERIFY_HASHES": "1", "UV_PYTHON": "other-python", "UV_NO_MANAGED_PYTHON": "1",
                "UV_PYTHON_INSTALL_REGISTRY": "1", "UV_PYTHON_INSTALL_BIN": "1",
            }), mock.patch.object(inst, "_command", side_effect=command), \
                 mock.patch.object(inst, "_verify_interpreter"), \
                 mock.patch.object(inst, "_normalize_new_windows_environment"), \
                 mock.patch.object(inst, "_record_python_artifact"):
                inst._create_environment(staging, lock, data / "requirements.txt", Path("/trusted/uv"), data)
            venv_command, options = next(item for item in commands if "venv" in item[0])
            self.assertIn("--no-config", venv_command)
            environment = options["environment"]
            self.assertEqual("20260414", environment["UV_PYTHON_CPYTHON_BUILD"])
            self.assertEqual(data / "python" / lock["python_artifact_digest"],
                             Path(environment["UV_PYTHON_INSTALL_DIR"]))
            self.assertNotIn("UV_PYTHON_INSTALL_MIRROR", environment)
            self.assertNotIn("UV_CONFIG_FILE", environment)
            self.assertNotIn("UV_NO_VERIFY_HASHES", environment)
            self.assertNotIn("UV_NO_MANAGED_PYTHON", environment)
            self.assertEqual("0", environment["UV_PYTHON_INSTALL_BIN"])
            self.assertEqual("0", environment["UV_PYTHON_INSTALL_REGISTRY"])
            self.assertEqual(inst.python_download_metadata(lock),
                Path(environment["UV_PYTHON_DOWNLOADS_JSON_URL"]).read_bytes())
            self.assertEqual("retain old base", marker.read_text())

    def test_old_uv_cannot_silently_ignore_the_build_pin(self):
        lock = self.lock()
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch.object(inst, "_command", return_value="uv 0.8.13") as command:
            data = Path(temporary).resolve()
            with self.assertRaisesRegex(ValidationFailure, "0.8.14"):
                inst._create_environment(data / "venv", lock, data / "requirements", Path("/trusted/uv"), data)
            self.assertEqual(1, command.call_count)

    def test_venv_failure_leaves_a_verified_base_reusable_without_another_download(self):
        lock = self.lock()
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary).resolve()
            base = data / "python" / lock["python_artifact_digest"] / lock["python_artifact"]["key"].replace("-darwin-", "-macos-")
            calls = []
            def failed_venv(argv, **kwargs):
                calls.append(argv)
                if argv[-1] == "--version":
                    return "uv 0.11.7"
                if "install" in argv:
                    downloaded = Path(kwargs["environment"]["UV_PYTHON_INSTALL_DIR"]) / base.name
                    downloaded.mkdir()
                    (downloaded / "BUILD").write_text("20260414")
                    return ""
                if "venv" in argv and not base.exists():
                    base.mkdir()
                    (base / "BUILD").write_text("20260414")
                raise ValidationFailure("venv fixture failed")
            with mock.patch.object(inst, "_command", side_effect=failed_venv):
                with self.assertRaisesRegex(ValidationFailure, "venv fixture"):
                    inst._create_environment(data / "venv", lock, data / "requirements", Path("/trusted/uv"), data)
            inst._check_python_base(base, lock)
            calls.clear()
            def retry(argv, **kwargs):
                calls.append(argv)
                return "uv 0.11.7" if argv[-1] == "--version" else ""
            with mock.patch.object(inst, "_command", side_effect=retry), mock.patch.object(inst, "_verify_interpreter"), \
                 mock.patch.object(inst, "_normalize_new_windows_environment"):
                inst._create_environment(data / "venv", lock, data / "requirements", Path("/trusted/uv"), data)
            self.assertFalse(any("install" in argv for argv in calls))
            self.assertIn("--no-python-downloads", next(argv for argv in calls if "venv" in argv))

    def test_interruption_before_receipt_never_publishes_an_unbound_base(self):
        lock = self.lock()
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary).resolve()
            downloaded = []
            def install(argv, **kwargs):
                if "install" in argv:
                    base = Path(kwargs["environment"]["UV_PYTHON_INSTALL_DIR"]) / lock["python_artifact"]["key"].replace("-darwin-", "-macos-")
                    base.mkdir()
                    (base / "BUILD").write_text("20260414")
                    downloaded.append(base)
                return "uv 0.11.7" if argv[-1] == "--version" else ""
            with mock.patch.object(inst, "_command", side_effect=install), \
                 mock.patch.object(inst, "_record_python_artifact", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    inst._create_environment(data / "venv", lock, data / "requirements", Path("/trusted/uv"), data)
            final = data / "python" / lock["python_artifact_digest"] / downloaded[0].name
            self.assertFalse(final.exists())
            with mock.patch.object(inst, "_command", side_effect=install), mock.patch.object(inst, "_verify_interpreter"), \
                 mock.patch.object(inst, "_normalize_new_windows_environment"):
                inst._create_environment(data / "venv", lock, data / "requirements", Path("/trusted/uv"), data)
            self.assertEqual(2, len(downloaded))
            self.assertNotEqual(downloaded[0], downloaded[1])
            self.assertTrue(downloaded[0].is_dir(), "retain the unbound attempt instead of deleting its contents")
            inst._check_python_base(final, lock)

    def test_package_rejects_changed_or_missing_python_metadata(self):
        lock = self.lock()
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary).resolve() / "engineering-assistant"
            runtime.mkdir()
            (runtime / "runtime-lock.json").write_text(json.dumps(lock))
            metadata = runtime / "runtime-python-downloads.json"
            with self.assertRaises((ValidationFailure, FileNotFoundError)):
                inst._package_lock(runtime.parent)
            metadata.write_bytes(inst.python_download_metadata(lock))
            self.assertEqual(lock, inst._package_lock(runtime.parent))
            metadata.write_bytes(metadata.read_bytes().replace(b"20260414", b"20260602"))
            with self.assertRaisesRegex(ValidationFailure, "Python|artifact"):
                inst._package_lock(runtime.parent)

    def test_same_version_wrong_build_or_unbound_base_is_rejected(self):
        lock = self.lock()
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary).resolve()
            artifact = lock["python_artifact"]
            base = data / "python" / lock["python_artifact_digest"] / artifact["key"].replace("-darwin-", "-macos-")
            base.mkdir(parents=True)
            (base / "BUILD").write_text("20260602")
            facts = {"python": "3.13.13", "jsonschema": "4.26.0", "implementation": "cpython",
                     "base_prefix": str(base), "gil": True}
            with mock.patch.object(inst, "_command", return_value=json.dumps(facts)):
                with self.assertRaisesRegex(ValidationFailure, "build"):
                    inst._verify_interpreter(data / "venv/bin/python", lock)
            (base / "BUILD").write_text("20260414")
            with mock.patch.object(inst, "_command", return_value=json.dumps(facts)):
                with self.assertRaisesRegex(ValidationFailure, "receipt"):
                    inst._verify_interpreter(data / "venv/bin/python", lock)
            inst._record_python_artifact(base, lock)
            with mock.patch.object(inst, "_command", return_value=json.dumps(facts)):
                inst._verify_interpreter(data / "venv/bin/python", lock)
            facts["base_prefix"] = str(data / "another-base")
            with mock.patch.object(inst, "_command", return_value=json.dumps(facts)):
                with self.assertRaisesRegex(ValidationFailure, "base"):
                    inst._verify_interpreter(data / "venv/bin/python", lock)

    def test_doctor_cannot_promote_a_wrong_build_after_protocol_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary).resolve()
            lock = self.lock()
            binding = {name: lock[name] for name in ("schema_version", "agent", "target", "environment_key", "python_artifact_digest")}
            binding.update(python=str(data / "venv/bin/python"), python_base=str(data / "base"), python_build="20260414")
            storage = ArtifactIO(data, ".")
            try:
                storage.create_immutable_json(binding, "bindings", "codex.json")
                storage.create_immutable_json(binding, "bindings", "codex", lock["environment_key"] + ".json")
            finally:
                storage.close()
            with mock.patch.object(inst, "host_target", return_value="macos-arm64"), \
                 mock.patch.object(inst, "_verified_package", return_value={"target": "macos-arm64", "canonical_version": "2.3.0.0-rc.1"}), \
                 mock.patch.object(inst, "_package_lock", return_value=self.lock()), \
                 mock.patch.object(inst, "_verify_interpreter", side_effect=ValidationFailure("Python build mismatch")), \
                 mock.patch.object(inst, "_protocol_checks", return_value={"provider": {"qualified": True}}):
                result = inst.doctor("codex", package=data / "package", data_home=data)
            self.assertFalse(result["ready"])
            self.assertEqual("failed", result["status"])

    def test_v2_boot_rejects_an_unprepared_real_python_without_mcp_stdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            shutil.copytree(ROOT / "src/engineering_assistant", root / "runtime/engineering_assistant",
                            ignore=shutil.ignore_patterns("__pycache__"))
            boot = root / "runtime_boot.py"
            shutil.copyfile(ROOT / "src/engineering_assistant/runtime_boot.py", boot)
            (root / "runtime-lock.json").write_text(json.dumps(self.lock()), encoding="utf-8")
            command = [sys.executable, "-I", "-B", str(boot)]
            result = subprocess.run([*command, "mcp-serve"], stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
            self.assertEqual(2, result.returncode)
            self.assertEqual(b"", result.stdout)
            self.assertEqual("python_artifact_verification_failed", json.loads(result.stderr)["reason"])
            hook = subprocess.run([*command, "hook"], stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
            self.assertEqual(0, hook.returncode)
            self.assertEqual({}, json.loads(hook.stdout))
            self.assertEqual(b"", hook.stderr)


if __name__ == "__main__":
    unittest.main()
