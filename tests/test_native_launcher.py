from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.native_launcher import build_launcher, host_target, launcher_info  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class NativeLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.binary = build_launcher(ROOT, host_target())

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "中文 plugin with spaces"
        self.runtime = self.root / "engineering-assistant"
        (self.runtime / "bin").mkdir(parents=True)
        self.executable = self.runtime / "bin" / self.binary.name
        shutil.copyfile(self.binary, self.executable)
        self.executable.chmod(0o700)
        self.data_home = Path(self.temporary.name) / "中文 data home"
        self.key = "a" * 64
        self.lock = {"schema_version": "1", "agent": "codex", "target": host_target(),
                     "canonical_version": "2.3.0.0-rc.1", "environment_key": self.key}
        (self.runtime / "runtime-lock.json").write_text(json.dumps(self.lock), encoding="utf-8")
        (self.runtime / "runtime_boot.py").write_text("import json,sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")

    def invoke(self, *arguments: str) -> subprocess.CompletedProcess:
        environment = {"ENGINEERING_ASSISTANT_DATA_HOME": str(self.data_home), "PATH": ""}
        for key in ("SYSTEMROOT", "WINDIR"):
            if key in os.environ:
                environment[key] = os.environ[key]
        return subprocess.run([str(self.executable), *arguments], env=environment,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=10)

    def prepare(self) -> Path:
        if os.name == "nt":
            from engineering_assistant.artifact_io import ArtifactIO

            storage = ArtifactIO(Path(self.temporary.name), self.data_home.name)
            try:
                storage.ensure_directory()
            finally:
                storage.close()
            environment = self.data_home / "中文 Python environment"
        else:
            environment = Path(self.temporary.name) / "中文 Python environment"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(environment)],
                       check=True, capture_output=True, timeout=60)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        binding = {"schema_version": "1", "agent": "codex", "target": host_target(),
                   "environment_key": self.key, "python": str(python),
                   "uv": str(Path(sys.executable).absolute()), "environment": str(environment)}
        path = self.data_home / "bindings/codex" / f"{self.key}.json"
        path.parent.mkdir(parents=True)
        if os.name != "nt":
            self.data_home.chmod(0o700)
        path.write_text(json.dumps(binding), encoding="utf-8")
        if os.name == "nt":
            from engineering_assistant.artifact_io import artifact_fs

            # Mirror setup's ownership normalization of only new staging/control
            # objects, preserving inherited user/SYSTEM ACLs without chmod.
            for private in (path.parent.parent, path.parent, path, environment, python.parent, python):
                flags = os.O_RDONLY | (artifact_fs.O_DIRECTORY if private.is_dir() else 0)
                descriptor = artifact_fs.open(str(private.absolute()), flags)
                try:
                    artifact_fs.set_private_owner(descriptor)
                finally:
                    artifact_fs.close(descriptor)
        return path

    @staticmethod
    def _private_windows_path(path: Path) -> None:
        from engineering_assistant.artifact_io import artifact_fs

        flags = os.O_RDONLY | (artifact_fs.O_DIRECTORY if path.is_dir() else 0)
        descriptor = artifact_fs.open(str(path.absolute()), flags)
        try:
            artifact_fs.fchmod(descriptor, 0o700 if path.is_dir() else 0o600)
        finally:
            artifact_fs.close(descriptor)

    @staticmethod
    def _windows_dacl(path: Path, broad: bool) -> None:
        import ctypes
        from engineering_assistant.artifact_io import artifact_fs

        flags = os.O_RDONLY | (artifact_fs.O_DIRECTORY if path.is_dir() else 0)
        descriptor = artifact_fs.open(str(path.absolute()), flags)
        handle = artifact_fs._kernel.ReOpenFile(artifact_fs._handle(descriptor),
                                               0x40080, 7, 0x02200000)
        if handle in (None, ctypes.c_void_p(-1).value):
            artifact_fs.close(descriptor)
            raise ctypes.WinError(ctypes.get_last_error())
        security = None
        try:
            dacl = ctypes.c_void_p()
            if broad:
                security = artifact_fs._security_descriptor(
                    f"D:P(A;;FA;;;{artifact_fs._user_sid})(A;;FA;;;SY)(A;;FA;;;WD)"
                )
                present, defaulted = ctypes.c_int(), ctypes.c_int()
                if not artifact_fs._advapi.GetSecurityDescriptorDacl(
                    security, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
                ) or not present.value:
                    raise AssertionError("test DACL could not be constructed")
            error = artifact_fs._advapi.SetSecurityInfo(handle, 1, 0x80000004, None, None, dacl, None)
            if error:
                raise ctypes.WinError(error)
        finally:
            if security is not None:
                artifact_fs._kernel.LocalFree(security)
            artifact_fs._kernel.CloseHandle(handle)
            artifact_fs.close(descriptor)

    @unittest.skipUnless(os.name == "nt", "requires real Windows security descriptors and native launcher")
    def test_windows_launcher_accepts_inherited_private_runtime_acl(self) -> None:
        self.prepare()
        result = self.invoke("mcp-serve")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["mcp-serve"], json.loads(result.stdout))

    @unittest.skipUnless(os.name == "nt", "requires real Windows security descriptors and native launcher")
    def test_windows_launcher_rejects_broad_runtime_path_acl(self) -> None:
        binding = self.prepare()
        environment = Path(json.loads(binding.read_text(encoding="utf-8"))["environment"])
        for path in (self.data_home, binding, binding.parent, environment,
                     environment / "Scripts", environment / "Scripts/python.exe"):
            with self.subTest(path=path):
                self._windows_dacl(path, broad=True)
                try:
                    result = self.invoke("mcp-serve")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(b"", result.stdout)
                    self.assertIn("private", json.loads(result.stderr)["reason"])
                finally:
                    self._private_windows_path(path)

    @unittest.skipUnless(os.name == "nt", "requires real Windows security descriptors and native launcher")
    def test_windows_launcher_rejects_null_control_dacl(self) -> None:
        binding = self.prepare()
        for path in (self.data_home, binding):
            with self.subTest(path=path):
                self._windows_dacl(path, broad=False)
                try:
                    result = self.invoke("mcp-serve")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(b"", result.stdout)
                    self.assertIn("private", json.loads(result.stderr)["reason"])
                finally:
                    self._private_windows_path(path)

    @unittest.skipUnless(os.name == "posix", "POSIX ownership and mode contract")
    def test_public_data_root_is_rejected_before_python(self) -> None:
        self.prepare()
        self.data_home.chmod(0o777)
        result = self.invoke("mcp-serve")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertIn("private", json.loads(result.stderr)["reason"])

    @unittest.skipUnless(os.name == "posix", "POSIX ownership and mode contract")
    def test_other_user_writable_binding_and_environment_are_rejected(self) -> None:
        binding = self.prepare()
        environment = Path(json.loads(binding.read_text())["environment"])
        for path in (binding, binding.parent, environment):
            with self.subTest(path=path):
                original = path.stat().st_mode & 0o777
                path.chmod(original | 0o022)
                try:
                    result = self.invoke("mcp-serve")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(b"", result.stdout)
                    self.assertIn("private", json.loads(result.stderr)["reason"])
                finally:
                    path.chmod(original)

    def test_compiled_binary_reports_its_target_without_preparation(self) -> None:
        self.assertEqual(host_target(), launcher_info(self.executable)["target"])

    def test_unprepared_mcp_keeps_stdout_empty_and_reports_status(self) -> None:
        result = self.invoke("mcp-serve")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertEqual("needs_preparation", json.loads(result.stderr)["status"])

    def test_prepared_binding_runs_without_path_and_preserves_unicode_arguments(self) -> None:
        self.prepare()
        result = self.invoke("mcp-serve", "中文 value with spaces")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["mcp-serve", "中文 value with spaces"], json.loads(result.stdout))

    def test_unprepared_hook_returns_nonblocking_empty_object(self) -> None:
        result = self.invoke("hook", "--event", "Stop")
        self.assertEqual(0, result.returncode)
        self.assertEqual({}, json.loads(result.stdout))
        self.assertEqual("needs_preparation", json.loads(result.stderr)["status"])

    def test_binding_cannot_run_an_interpreter_outside_its_environment(self) -> None:
        path = self.prepare()
        binding = json.loads(path.read_text(encoding="utf-8"))
        binding["python"] = str(Path(sys.executable).absolute())
        path.write_text(json.dumps(binding), encoding="utf-8")
        result = self.invoke("mcp-serve")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertIn("outside", json.loads(result.stderr)["reason"])

    def test_target_mismatch_is_rejected_before_loading_bootstrap(self) -> None:
        path = self.prepare()
        binding = json.loads(path.read_text(encoding="utf-8"))
        binding["target"] = "wrong-target"
        path.write_text(json.dumps(binding), encoding="utf-8")
        result = self.invoke("mcp-serve")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertIn("does not match", json.loads(result.stderr)["reason"])

    def test_latest_alias_does_not_invalidate_an_older_version_binding(self) -> None:
        path = self.prepare()
        binding = json.loads(path.read_text(encoding="utf-8"))
        binding["environment_key"] = "b" * 64
        (self.data_home / "bindings/codex.json").write_text(json.dumps(binding), encoding="utf-8")
        result = self.invoke("mcp-serve")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["mcp-serve"], json.loads(result.stdout))

    def test_interpreter_keeps_its_venv_prefix_and_child_exit_status(self) -> None:
        path = self.prepare()
        binding = json.loads(path.read_text(encoding="utf-8"))
        (self.runtime / "runtime_boot.py").write_text("import sys\nprint(sys.prefix)\nraise SystemExit(7)\n", encoding="utf-8")
        result = self.invoke("mcp-serve")
        self.assertEqual(7, result.returncode)
        self.assertTrue(Path(binding["environment"]).samefile(result.stdout.decode("utf-8").strip()))

    def test_latest_alias_can_supply_a_matching_legacy_binding(self) -> None:
        path = self.prepare()
        path.rename(self.data_home / "bindings/codex.json")
        result = self.invoke("mcp-serve")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_oversized_binding_fails_before_starting_python(self) -> None:
        path = self.prepare()
        path.write_bytes(b" " * 131073)
        result = self.invoke("mcp-serve")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertIn("oversized", json.loads(result.stderr)["reason"])

    @unittest.skipIf(os.name == "nt", "Windows reparse protection is exercised by the directory junction test")
    def test_bootstrap_link_cannot_run_outside_code(self) -> None:
        self.prepare()
        boot = self.runtime / "runtime_boot.py"
        outside = Path(self.temporary.name) / "outside.py"
        outside.write_text("print('untrusted outside code')\n", encoding="utf-8")
        boot.unlink()
        boot.symlink_to(outside)
        result = self.invoke("mcp-serve")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertIn("unsafe", json.loads(result.stderr)["reason"])

    def test_environment_key_cannot_escape_the_binding_directory(self) -> None:
        self.lock["environment_key"] = "../outside"
        (self.runtime / "runtime-lock.json").write_text(json.dumps(self.lock), encoding="utf-8")
        result = self.invoke("mcp-serve")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertIn("key is invalid", json.loads(result.stderr)["reason"])

    def test_binding_parent_link_is_rejected(self) -> None:
        path = self.prepare()
        original = path.parent
        held = original.with_name("held")
        original.rename(held)
        if os.name == "nt":
            created = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(original), str(held)],
                                     capture_output=True, check=False)
            self.assertEqual(0, created.returncode, created.stderr)
            self.addCleanup(original.rmdir)
        else:
            original.symlink_to(held, target_is_directory=True)
        result = self.invoke("mcp-serve")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertIn("unsafe", json.loads(result.stderr)["reason"])

    def test_launcher_probe_rejects_a_script_before_execution(self) -> None:
        script = Path(self.temporary.name) / "fake launcher"
        marker = Path(self.temporary.name) / "executed"
        script.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
        script.chmod(0o700)
        with self.assertRaisesRegex(ValidationFailure, "machine header"):
            launcher_info(script)
        self.assertFalse(marker.exists())

    def test_cross_target_build_is_rejected_even_with_an_override(self) -> None:
        different = "linux-x64" if host_target() != "linux-x64" else "windows-x64"
        with self.assertRaisesRegex(ValidationFailure, "matching OS"):
            build_launcher(ROOT, different, executable_override=self.binary)

    def test_unknown_host_architecture_is_explicitly_unsupported(self) -> None:
        with patch("engineering_assistant.native_launcher.platform.system", return_value="Linux"), patch(
            "engineering_assistant.native_launcher.platform.machine", return_value="riscv64"
        ), self.assertRaisesRegex(ValidationFailure, "unsupported"):
            host_target()


if __name__ == "__main__":
    unittest.main()
