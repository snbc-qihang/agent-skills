"""Manifest bridge tests; native Shell execution requires a Windows runner.

The temporary Runtime uses the test interpreter. It qualifies Shell routing and
byte transport, not the pinned production Runtime or an authenticated Agent.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.platforms.adapters.codex import CodexAdapter
from engineering_assistant.runtime.catalog import load_catalog
from engineering_assistant.platforms.native_launcher import build_launcher, host_target


def manifest_command(root: Path) -> str:
    CodexAdapter(target="windows-x64").write_platform_files(root, load_catalog(ROOT))
    hooks = json.loads((root / "hooks/hooks.json").read_text(encoding="utf-8"))
    commands = {group["hooks"][0]["commandWindows"]
                for groups in hooks["hooks"].values() for group in groups}
    if len(commands) != 1:
        raise AssertionError("all events must use the same Windows bridge")
    return commands.pop()


class WindowsHookManifestTests(unittest.TestCase):
    def test_windows_bridge_disables_encoding_preamble_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            command = manifest_command(Path(temporary))
        script = base64.b64decode(command.split()[-1], validate=True).decode("utf-16le")
        # Framework Process.Start constructs an AutoFlush StreamWriter using
        # Console.InputEncoding, which emits its preamble before BaseStream copy.
        encoding = "[Console]::InputEncoding = New-Object Text.UTF8Encoding $false"
        self.assertIn(encoding, script)
        self.assertLess(script.index(encoding), script.index("$process.Start()"))
        self.assertNotIn("StandardInputEncoding", script, "Windows PowerShell uses .NET Framework")

    def test_windows_bridge_suppresses_powershell_progress_before_module_load(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            command = manifest_command(Path(temporary))
        script = base64.b64decode(command.split()[-1], validate=True).decode("utf-16le")
        progress = "$ProgressPreference = 'SilentlyContinue'"
        self.assertIn(progress, script)
        self.assertLess(script.index(progress), script.index("New-Object"))

    def test_new_fixture_directory_keeps_inherited_private_acl(self) -> None:
        filesystem = SimpleNamespace(open=Mock(return_value=7), O_DIRECTORY=0x4000,
            set_private_owner=Mock(), assert_private_directory=Mock(), fchmod=Mock(), close=Mock())
        with patch("engineering_assistant.runtime.artifact_io.artifact_fs", filesystem), patch.object(os, "close"):
            WindowsHookExecutionTests.private(Path("private runtime"), directory=True)
        filesystem.set_private_owner.assert_called_once_with(7)
        filesystem.fchmod.assert_not_called()
        filesystem.assert_private_directory.assert_called_once_with(7)

    def test_windows_manifest_uses_constant_encoded_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            command = manifest_command(Path(temporary))
        match = re.fullmatch(
            r"powershell\.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand ([A-Za-z0-9+/=]+)",
            command,
        )
        self.assertIsNotNone(match, "Windows Hook must not depend on outer Shell variable syntax")
        self.assertLess(len(command), 8191, "CMD must accept the complete encoded bridge")
        script = base64.b64decode(match.group(1), validate=True).decode("utf-16le")
        self.assertIn("$env:PLUGIN_ROOT", script)
        self.assertIn("UseShellExecute = $false", script)
        self.assertIn("BaseStream.CopyToAsync", script)
        self.assertNotIn("${PLUGIN_ROOT}", script)
        self.assertNotIn("%PLUGIN_ROOT%", script)


@unittest.skipUnless(sys.platform == "win32", "requires real Windows CMD, PowerShell and Git Bash")
class WindowsHookExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.binary = build_launcher(ROOT, host_target())
        cls.runtime_fixture = tempfile.TemporaryDirectory(prefix="ea hook interpreter ")
        cls.addClassCleanup(cls.runtime_fixture.cleanup)
        from engineering_assistant.installer.installation import _storage
        storage = _storage(Path(cls.runtime_fixture.name) / "private Runtime")
        try:
            cls.environment = storage.ensure_directory("中文 Python environment")
        finally:
            storage.close()
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(cls.environment)],
                       check=True, capture_output=True, timeout=60)
        cls.python = cls.environment / "Scripts/python.exe"
        cls.private(cls.environment, directory=True)
        cls.private(cls.python.parent, directory=True)
        cls.private(cls.python, directory=False, executable=True)

    @staticmethod
    def private(path: Path, *, directory: bool, executable: bool = False) -> None:
        from engineering_assistant.runtime.artifact_io import artifact_fs

        descriptor = artifact_fs.open(str(path), os.O_RDONLY | (artifact_fs.O_DIRECTORY if directory else 0))
        try:
            artifact_fs.set_private_owner(descriptor)  # Only this test's new temporary objects.
            if directory:
                artifact_fs.assert_private_directory(descriptor)
            else:
                artifact_fs.fchmod(descriptor, 0o700 if executable else 0o600)
        finally:
            artifact_fs.close(descriptor)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ea Windows hooks ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "中文 plugin 空格 $符号 & %PATH%"
        self.root.mkdir()
        self.command = manifest_command(self.root)
        runtime = self.root / "engineering-assistant"
        (runtime / "bin").mkdir(parents=True)
        shutil.copyfile(self.binary, runtime / "bin/ea.exe")
        self.boot = runtime / "runtime_boot.py"
        self.boot.write_text(
            "import os,sys\n"
            "assert sys.argv[1:] == ['hook']\n"
            "assert os.environ['PLUGIN_ROOT'] == os.environ['EXPECTED_PLUGIN_ROOT']\n"
            "sys.stdout.buffer.write(b' ' * 131072); sys.stdout.buffer.flush()\n"
            "sys.stderr.buffer.write(('中文 diagnostic\\n' + ' ' * 131072).encode('utf-8')); sys.stderr.buffer.flush()\n"
            "payload = sys.stdin.buffer.read()\n"
            "sys.stdout.buffer.write(payload); sys.stdout.buffer.flush()\n",
            encoding="utf-8",
        )
        self.data = self.base / "中文 data home"
        key = "a" * 64
        lock = {"schema_version": "1", "agent": "codex", "target": "windows-x64",
                "canonical_version": load_catalog(ROOT).version, "environment_key": key}
        (runtime / "runtime-lock.json").write_text(json.dumps(lock), encoding="utf-8")
        binding = self.data / "bindings/codex" / (key + ".json")
        from engineering_assistant.installer.installation import _storage
        storage = _storage(self.data)
        try:
            storage.create_immutable_json({"schema_version": "1", "agent": "codex", "target": "windows-x64",
                "environment_key": key, "python": str(self.python), "environment": str(self.environment),
                "uv": str(Path(sys.executable).absolute())}, "bindings", "codex", key + ".json")
        finally:
            storage.close()
        for directory in (self.data, binding.parent.parent, binding.parent):
            self.private(directory, directory=True)
        self.private(binding, directory=False)
        self.powershell = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        self.assertTrue(self.powershell.is_file(), "Windows PowerShell is a required Hook prerequisite")
        self.env = {**os.environ, "PLUGIN_ROOT": str(self.root), "EXPECTED_PLUGIN_ROOT": str(self.root),
                    "ENGINEERING_ASSISTANT_DATA_HOME": str(self.data), "PATH": str(self.powershell.parent)}
        self.payload = json.dumps({"prompt": "中文 payload 空格 $ & %", "padding": "x" * 262144},
                                  ensure_ascii=False).encode("utf-8")

    def invoke(self, shell: str) -> subprocess.CompletedProcess:
        if shell == "cmd":
            program = Path(os.environ["COMSPEC"])
            # Codex's CMD runner uses raw_arg for one outer quoted command.
            command = subprocess.list2cmdline([str(program), "/c"]) + ' "' + self.command + '"'
        elif shell == "powershell":
            # -Command otherwise maps a native nonzero exit to Boolean failure
            # (1). This runner fixture explicitly preserves native exit status;
            # it does not establish an authenticated Agent's runner contract.
            command = [str(self.powershell), "-NoProfile", "-Command",
                       self.command + "; exit $LASTEXITCODE"]
        elif shell == "git-bash":
            candidates = [Path(os.environ["ENGINEERING_ASSISTANT_TEST_GIT_BASH"])] if os.environ.get(
                "ENGINEERING_ASSISTANT_TEST_GIT_BASH") else [
                Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe",
                Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Git/bin/bash.exe",
            ]
            program = next((path for path in candidates if path.is_file()), None)
            self.assertIsNotNone(program, "Windows qualification requires Git Bash, not WSL bash")
            command = [str(program), "-c", self.command]
        else:
            raise AssertionError("unknown test Shell")
        process = subprocess.Popen(command, cwd=self.base, env=self.env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            output, error = process.communicate(self.payload, timeout=30)
        except subprocess.TimeoutExpired:
            # Clean only this test-owned process tree; never leave a blocked bridge.
            taskkill = Path(os.environ["SYSTEMROOT"]) / "System32/taskkill.exe"
            subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=10, check=False)
            process.kill()
            process.communicate(timeout=10)
            raise
        return subprocess.CompletedProcess(command, process.returncode, output, error)

    def assert_round_trip(self, shell: str) -> None:
        result = self.invoke(shell)
        self.assertEqual(0, result.returncode, result.stderr[-4096:])
        self.assertEqual(b" " * 131072 + self.payload, result.stdout)
        self.assertEqual(("中文 diagnostic\n" + " " * 131072).encode("utf-8"), result.stderr)
        self.assertEqual(json.loads(self.payload), json.loads(result.stdout))

    def test_cmd_manifest_bridge_preserves_protocol_bytes(self) -> None:
        self.assert_round_trip("cmd")

    def test_powershell_manifest_bridge_preserves_protocol_bytes(self) -> None:
        self.assert_round_trip("powershell")

    def test_git_bash_manifest_bridge_preserves_protocol_bytes(self) -> None:
        self.assert_round_trip("git-bash")

    def test_bridge_preserves_native_failure_exit_status(self) -> None:
        self.boot.write_text("import sys\nsys.stdin.buffer.read()\nraise SystemExit(17)\n", encoding="utf-8")
        for shell in ("cmd", "powershell", "git-bash"):
            with self.subTest(shell=shell):
                result = self.invoke(shell)
                self.assertEqual(17, result.returncode, result.stderr)
                self.assertEqual(b"", result.stdout)

    def test_unprepared_hook_remains_nonblocking(self) -> None:
        shutil.rmtree(self.data)
        for shell in ("cmd", "powershell", "git-bash"):
            with self.subTest(shell=shell):
                result = self.invoke(shell)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(result.stdout.strip().startswith(b"{"), result.stdout)
                self.assertTrue(result.stderr.strip().startswith(b"{"), result.stderr)
                self.assertEqual({}, json.loads(result.stdout))
                self.assertEqual("needs_preparation", json.loads(result.stderr)["status"])

    def test_bridge_timeout_terminates_runtime_descendants(self) -> None:
        from engineering_assistant.platforms.windows_process import run_bounded_windows

        sentinel = self.base / "子进程 survived"
        child_code = "import pathlib,sys,time; time.sleep(60); pathlib.Path(sys.argv[1]).write_text('survived')"
        self.boot.write_text(
            "import json,os,subprocess,sys,time\n"
            f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}, {str(sentinel)!r}])\n"
            "print(json.dumps({'runtime_pid': os.getpid(), 'child_pid': child.pid}), flush=True)\n"
            "sys.stdin.buffer.read()\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        # This is the installer's Job boundary around the actual manifest bridge.
        # The total ten-second budget includes PowerShell's cold initialization
        # and Runtime execution. Both target processes remain live beyond it.
        # It does not establish an authenticated Agent's Hook deadline behavior.
        command = [str(self.powershell), *self.command.split()[1:]]
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            run_bounded_windows(command, cwd=self.base, environment=self.env,
                timeout_seconds=10, output_limit_bytes=65536, input_data=self.payload)
        self.assertTrue(raised.exception.output.strip().startswith(b"{"), raised.exception.output)
        pids = json.loads(raised.exception.output)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        for pid in (pids["runtime_pid"], pids["child_pid"]):
            handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
            if not handle:
                self.assertEqual(87, ctypes.get_last_error())  # Process no longer exists.
                continue
            try:
                self.assertEqual(0, kernel.WaitForSingleObject(handle, 5000))
            finally:
                kernel.CloseHandle(handle)
        time.sleep(2.1)
        self.assertFalse(sentinel.exists(), "timed-out Runtime descendant survived the Job boundary")


if __name__ == "__main__":
    unittest.main()
