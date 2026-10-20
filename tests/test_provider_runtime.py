from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.runtime.catalog import load_catalog  # noqa: E402
from engineering_assistant.runtime.model import ProviderInvocation  # noqa: E402
from engineering_assistant.runtime.provider_runtime import ProviderExecutor  # noqa: E402


class ProviderRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(ROOT)
        self.temporary = tempfile.TemporaryDirectory()
        self.bundle = Path(self.temporary.name) / "ui-ux-pro-max"
        (self.bundle / "scripts").mkdir(parents=True)
        (self.bundle / "data").mkdir()
        (self.bundle / "scripts/search.py").write_text(
            "print('## Design System: Test')\n", encoding="utf-8"
        )
        (self.bundle / "data/styles.csv").write_text(
            "name,value\nminimal,1\n", encoding="utf-8"
        )
        integrity = ProviderExecutor._tree_integrity(self.bundle)
        provider = self.catalog.providers["ui-ux-pro-max"]
        self.catalog.providers["ui-ux-pro-max"] = replace(
            provider,
            source=replace(provider.source, integrity=integrity),
        )
        self.executor = ProviderExecutor(self.catalog)

    def refresh_integrity(self) -> None:
        provider = self.catalog.providers["ui-ux-pro-max"]
        self.catalog.providers["ui-ux-pro-max"] = replace(
            provider,
            source=replace(
                provider.source,
                integrity=ProviderExecutor._tree_integrity(self.bundle),
            ),
        )
        self.executor = ProviderExecutor(self.catalog)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def invocation() -> ProviderInvocation:
        return ProviderInvocation(
            invocation_id="ui-advice-1",
            run_id="run-1",
            capability_id="frontend-design",
            query="enterprise analytics dashboard",
            operation="design_system",
            project_name="Analytics",
            variance=6,
            motion=3,
            density=8,
        )

    def test_bounded_fallback_keeps_failure_category_and_final_exception(self) -> None:
        warning = "provider exited with status 1: " + "traceback frame\n" * 200 + "ImportError: fixed native extension failed"
        provider = self.catalog.providers["ui-ux-pro-max"]
        result = self.executor._fallback(self.invocation(), provider, warning)
        self.assertEqual("fallback", result.status)
        self.assertLessEqual(len(result.warning), 1000)
        self.assertTrue(result.warning.startswith("provider exited with status 1:"))
        self.assertTrue(result.warning.endswith("ImportError: fixed native extension failed"))

    def test_provider_uses_the_host_temporary_directory_and_cleans_its_snapshot(self) -> None:
        temporary_parent = Path(self.temporary.name) / "临时工作 目录"
        temporary_parent.mkdir()
        configured_parent = temporary_parent
        if os.name != "nt":
            configured_parent = Path(self.temporary.name) / "系统临时路径别名"
            configured_parent.symlink_to(temporary_parent, target_is_directory=True)
        snapshots = []

        def execute(_provider, _invocation, bundle, work, _denied):
            snapshots.append(bundle.parent)
            self.assertEqual(temporary_parent.resolve(), bundle.parent.parent.resolve())
            self.assertEqual(bundle.resolve(), bundle)
            self.assertEqual(work.resolve(), work)
            self.assertEqual(bundle.parent, work.parent)
            self.assertEqual(b"name,value\nminimal,1\n", (bundle / "data/styles.csv").read_bytes())
            if os.name != "nt":
                self.assertEqual(0o700, bundle.parent.stat().st_mode & 0o777)
            return "## Design System: temporary snapshot"

        with patch("engineering_assistant.runtime.provider_runtime.tempfile.tempdir", str(configured_parent)), patch.object(
            self.executor, "_run_ui_ux_pro_max", side_effect=execute,
        ):
            result = self.executor.invoke(self.invocation(), provider_root=self.bundle)
        self.assertEqual("completed", result.status, result.warning)
        self.assertEqual(1, len(snapshots))
        self.assertFalse(snapshots[0].exists())

    def test_pinned_bundle_executes_without_shell_network_env_or_persist(self) -> None:
        real_popen = subprocess.Popen
        calls = []

        def launch(*args, **kwargs):
            calls.append((args, kwargs))
            return real_popen(*args, **kwargs)

        def launch_windows(command, _bundle, work, environment, _timeout, _limit):
            calls.append(((command,), {"cwd": work, "env": environment, "stdin": subprocess.DEVNULL, "start_new_session": True}))
            # Transport shape only. Windows production tests below exercise the
            # LPAC launcher and real Python process without this substitute.
            return 0, b"## Design System: Test", b""

        with patch.object(
            ProviderExecutor,
            "_sandbox_command",
            side_effect=lambda command, _bundle, _work, _denied: command,
        ), patch(
            "engineering_assistant.runtime.provider_runtime.subprocess.Popen",
            side_effect=launch,
        ), patch(
            "engineering_assistant.platforms.provider_sandbox_windows.run",
            side_effect=launch_windows,
        ):
            result = self.executor.invoke(
                self.invocation(), provider_root=self.bundle
            )
        self.assertEqual("completed", result.status)
        self.assertEqual("ui-ux-pro-max", result.provider_id)
        command = calls[0][0][0]
        self.assertIn(str(ProviderExecutor._runtime_executable()), command)
        self.assertIn("-I", command)
        self.assertIn("-S", command)
        self.assertIn("-B", command)
        self.assertNotIn("--persist", command)
        self.assertNotIn("HOME", calls[0][1]["env"])
        self.assertNotIn("HTTP_PROXY", calls[0][1]["env"])
        if sys.platform == "win32":
            utf8 = command.index("-X")
            self.assertEqual("utf8", command[utf8 + 1])
        self.assertEqual(calls[0][1]["cwd"], Path(calls[0][1]["env"]["TMP"]))
        self.assertNotIn("preexec_fn", calls[0][1])
        self.assertEqual(subprocess.DEVNULL, calls[0][1]["stdin"])
        self.assertTrue(calls[0][1]["start_new_session"])

    def test_windows_trusted_bootstrap_restores_private_directory_options(self) -> None:
        # This portable seam executes the bootstrap, not Windows confinement.
        # Windows native qualification below must still pass real LPAC launch.
        (self.bundle / "scripts/search.py").write_text(
            "import os\n"
            "keys = ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'TEMP', 'TMP', 'TMPDIR')\n"
            "assert all(os.environ[key] == os.getcwd() for key in keys)\n"
            "print('## Design System: private directory options')\n",
            encoding="utf-8",
        )
        self.refresh_integrity()

        def launch(command, _bundle, work, environment, timeout, _limit):
            redirected = dict(environment)
            redirected.update({key: 'unapproved-profile' for key in (
                'LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'TEMP', 'TMP', 'TMPDIR',
            )})
            result = subprocess.run(command, cwd=work, env=redirected, capture_output=True, timeout=timeout)
            return result.returncode, result.stdout, result.stderr

        with patch('engineering_assistant.runtime.provider_runtime.platform.system', return_value='Windows'), patch.object(
            ProviderExecutor, '_sandbox_command', side_effect=lambda command, *_args: command,
        ), patch('engineering_assistant.platforms.provider_sandbox_windows.run', side_effect=launch):
            result = self.executor.invoke(self.invocation(), provider_root=self.bundle)
        self.assertEqual('completed', result.status, result.warning)
        self.assertEqual('## Design System: private directory options', result.output)

    @unittest.skipUnless(sys.platform == "win32", "native Windows LPAC environment redirection")
    def test_windows_lpac_keeps_temporary_and_profile_options_in_private_work(self) -> None:
        self._require_production_sandbox()
        (self.bundle / "scripts/search.py").write_text(
            "import os, tempfile\n"
            "from pathlib import Path\n"
            "keys = ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'TEMP', 'TMP', 'TMPDIR')\n"
            "assert all(os.environ[key] == os.getcwd() for key in keys)\n"
            "assert 'HOME' not in os.environ and 'HTTP_PROXY' not in os.environ\n"
            "with tempfile.TemporaryFile() as stream:\n"
            "    stream.write(b'private temporary data')\n"
            "assert Path(tempfile.gettempdir()).samefile(Path.cwd())\n"
            "print('## Design System: private temporary directory')\n",
            encoding="utf-8",
        )
        self.refresh_integrity()
        result = self.executor.invoke(self.invocation(), provider_root=self.bundle)
        self.assertEqual("completed", result.status, result.warning)

    @unittest.skipUnless(sys.platform == "win32", "native Windows LPAC long Unicode paths")
    def test_windows_lpac_reads_and_writes_deep_unicode_paths(self) -> None:
        self._require_production_sandbox()
        relative = Path(*(["中文 带空格目录" + "层" * 24] * 8))
        data = self.bundle / "data" / relative / "资料.txt"
        self.assertGreater(len(str(data)), 300)
        data.parent.mkdir(parents=True)
        data.write_text("中文资料", encoding="utf-8")
        (self.bundle / "scripts/search.py").write_text(
            "from pathlib import Path\n"
            f"relative = Path({str(relative)!r})\n"
            "data = Path(__file__).parent.parent / 'data' / relative / '资料.txt'\n"
            "try:\n"
            "    content = data.read_text(encoding='utf-8')\n"
            "except OSError as error:\n"
            "    raise RuntimeError(f'EA_DEEP_READ:{type(error).__name__}:{error.errno}:{getattr(error, \"winerror\", None)}') from None\n"
            "assert content == '中文资料'\n"
            "assert data in list(data.parent.iterdir())\n"
            "output = Path.cwd() / relative / '结果.txt'\n"
            "try:\n"
            "    output.parent.mkdir(parents=True)\n"
            "    output.write_text('中文结果', encoding='utf-8')\n"
            "except OSError as error:\n"
            "    raise RuntimeError(f'EA_DEEP_WRITE:{type(error).__name__}:{error.errno}:{getattr(error, \"winerror\", None)}') from None\n"
            "assert output.read_text(encoding='utf-8') == '中文结果'\n"
            "print('## Design System: 中文路径与结果')\n", encoding="utf-8",
        )
        self.refresh_integrity()
        parent = Path(self.temporary.name) / "中文 临时目录"
        parent.mkdir()
        with patch("engineering_assistant.runtime.provider_runtime.tempfile.tempdir", str(parent)):
            result = self.executor.invoke(self.invocation(), provider_root=self.bundle)
        self.assertEqual("completed", result.status, result.warning)
        self.assertEqual("## Design System: 中文路径与结果", result.output)

    def test_darwin_venv_uses_the_base_framework_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            venv_root = root / "venv"
            base_root = root / "framework"
            executable = base_root / "Resources/Python.app/Contents/MacOS/Python"
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch(
                "engineering_assistant.runtime.provider_runtime.platform.system",
                return_value="Darwin",
            ), patch(
                "engineering_assistant.runtime.provider_runtime.sys.prefix", str(venv_root)
            ), patch(
                "engineering_assistant.runtime.provider_runtime.sys.base_prefix", str(base_root)
            ):
                self.assertEqual(base_root.resolve(), ProviderExecutor._runtime_root())
                self.assertEqual(executable.resolve(), ProviderExecutor._runtime_executable())

    def test_darwin_venv_accepts_a_direct_base_runtime_without_framework(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            venv_root = root / "venv"
            base_root = root / "python"
            executable = base_root / "bin/python3"
            executable.parent.mkdir(parents=True)
            executable.touch()
            venv_executable = venv_root / "bin/python"
            venv_executable.parent.mkdir(parents=True)
            venv_executable.symlink_to(executable)
            with patch(
                "engineering_assistant.runtime.provider_runtime.platform.system",
                return_value="Darwin",
            ), patch(
                "engineering_assistant.runtime.provider_runtime.sys.prefix", str(venv_root)
            ), patch(
                "engineering_assistant.runtime.provider_runtime.sys.base_prefix", str(base_root)
            ), patch(
                "engineering_assistant.runtime.provider_runtime.sys.executable", str(venv_executable)
            ):
                self.assertEqual(executable.resolve(), ProviderExecutor._runtime_executable())

    def test_non_darwin_runtime_root_keeps_the_current_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch(
                "engineering_assistant.runtime.provider_runtime.platform.system",
                return_value="Linux",
            ), patch(
                "engineering_assistant.runtime.provider_runtime.sys.prefix", str(root / "venv")
            ), patch(
                "engineering_assistant.runtime.provider_runtime.sys.base_prefix", str(root / "base")
            ):
                self.assertEqual((root / "venv").resolve(), ProviderExecutor._runtime_root())

    def test_missing_or_tampered_bundle_falls_back_to_native(self) -> None:
        missing = self.executor.invoke(self.invocation(), provider_root=None)
        self.assertEqual("fallback", missing.status)
        self.assertEqual("native-engineering", missing.provider_id)

        (self.bundle / "data/styles.csv").write_text("tampered\n", encoding="utf-8")
        tampered = self.executor.invoke(
            replace(self.invocation(), invocation_id="ui-advice-2"),
            provider_root=self.bundle,
        )
        self.assertEqual("fallback", tampered.status)
        self.assertIn("integrity", tampered.warning)

    def test_symlink_or_oversized_output_is_contained_by_fallback(self) -> None:
        target = Path(self.temporary.name) / "outside"
        target.write_text("outside", encoding="utf-8")
        (self.bundle / "data/link").symlink_to(target)
        linked = self.executor.invoke(
            replace(self.invocation(), invocation_id="ui-advice-link"),
            provider_root=self.bundle,
        )
        self.assertEqual("fallback", linked.status)
        self.assertIn("symlink", linked.warning)

    def test_bytecode_and_special_files_are_rejected(self) -> None:
        cache = self.bundle / "scripts/__pycache__"
        cache.mkdir()
        (cache / "search.cpython-314.pyc").write_bytes(b"malicious")
        bytecode = self.executor.invoke(
            replace(self.invocation(), invocation_id="ui-advice-pyc"),
            provider_root=self.bundle,
        )
        self.assertEqual("fallback", bytecode.status)
        self.assertIn("bytecode", bytecode.warning)
        (cache / "search.cpython-314.pyc").unlink()
        cache.rmdir()

        if hasattr(os, "mkfifo"):
            fifo = self.bundle / "data/fifo"
            os.mkfifo(fifo)
            special = self.executor.invoke(
                replace(self.invocation(), invocation_id="ui-advice-fifo"),
                provider_root=self.bundle,
            )
            self.assertEqual("fallback", special.status)
            self.assertIn("special file", special.warning)

    def test_sandbox_cannot_exfiltrate_a_file_outside_snapshot(self) -> None:
        secret = Path(self.temporary.name) / "host-secret"
        secret.write_text("TOP-SECRET-CANARY", encoding="utf-8")
        (self.bundle / "scripts/search.py").write_text(
            "from pathlib import Path\n"
            f"print('## Design System: ' + Path({str(secret)!r}).read_text())\n",
            encoding="utf-8",
        )
        self.refresh_integrity()
        result = self.executor.invoke(
            replace(self.invocation(), invocation_id="ui-advice-secret"),
            provider_root=self.bundle,
            denied_roots=[secret.parent],
        )
        self.assertEqual("fallback", result.status)
        self.assertNotIn("TOP-SECRET-CANARY", result.output)

    @unittest.skipUnless(os.name == "posix", "POSIX output-file path replacement; Windows uses pipes")
    def test_output_path_replacement_does_not_make_parent_read_a_secret(self) -> None:
        secret = Path(self.temporary.name) / "parent-secret"
        secret.write_text("## Design System: PARENT-ONLY-SECRET", encoding="utf-8")
        output_path = Path(self.temporary.name) / "stdout.txt"
        error_path = Path(self.temporary.name) / "stderr.txt"
        # Simulate path substitution at the reader seam. Production policies
        # remain unchanged; Linux does not grant MAKE_SYM in private work.
        with output_path.open("w+b") as output, error_path.open("w+b") as error:
            output.write(b"## Design System: safe output")
            output.flush()
            output_path.unlink()
            output_path.symlink_to(secret)
            content, _ = ProviderExecutor._read_output_handles(output, error)
        self.assertEqual(b"## Design System: safe output", content)
        self.assertNotIn(b"PARENT-ONLY-SECRET", content)

    def test_missing_sandbox_capability_falls_back_before_provider_executes(self) -> None:
        marker = Path(self.temporary.name) / "executed"
        (self.bundle / "scripts/search.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('unconfined')\n"
            "print('## Design System: unconfined')\n",
            encoding="utf-8",
        )
        self.refresh_integrity()
        with patch("engineering_assistant.runtime.provider_runtime.platform.system", return_value="Linux"), patch.object(
            ProviderExecutor, "sandbox_capability", return_value={"supported": False, "reason": "Landlock disabled"}
        ):
            result = self.executor.invoke(self.invocation(), provider_root=self.bundle)
        self.assertEqual("fallback", result.status)
        self.assertIn("Landlock disabled", result.warning)
        self.assertFalse(marker.exists())

    def _require_production_sandbox(self) -> None:
        capability = ProviderExecutor.sandbox_capability()
        if capability["supported"]:
            return
        if os.environ.get("ENGINEERING_ASSISTANT_REQUIRE_PROVIDER_SANDBOX") == "1":
            self.fail(f"Provider qualification is mandatory: {capability['reason']}")
        self.skipTest(f"Provider cannot be qualified on this host: {capability['reason']}")

    @unittest.skipUnless(sys.platform in {"darwin", "linux", "win32"}, "production OS sandbox")
    def test_production_sandbox_runs_provider_and_allows_only_private_work_writes(self) -> None:
        self._require_production_sandbox()
        (self.bundle / "scripts/search.py").write_text(
            "import csv, hashlib, json, math\n"
            "from pathlib import Path\n"
            "data = Path(__file__).parent.parent / 'data/styles.csv'\n"
            "rows = list(csv.DictReader(data.open(encoding='utf-8')))\n"
            "Path('allowed.txt').write_text('private work', encoding='utf-8')\n"
            "print('## Design System: ' + rows[0]['name'] + str(math.sqrt(4)))\n",
            encoding="utf-8",
        )
        self.refresh_integrity()
        result = self.executor.invoke(self.invocation(), provider_root=self.bundle)
        self.assertEqual("completed", result.status, result.warning)
        self.assertEqual("## Design System: minimal2.0", result.output)

    @unittest.skipUnless(sys.platform in {"darwin", "linux", "win32"}, "production OS sandbox")
    def test_production_sandbox_denies_network_processes_exec_and_outside_writes(self) -> None:
        self._require_production_sandbox()
        outside = Path(self.temporary.name) / "outside-write"
        executable = str(ProviderExecutor._runtime_executable())
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(("127.0.0.1", 0))
        server.listen()
        ipv6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        self.addCleanup(ipv6.close)
        ipv6.bind(("::1", 0))
        probes = {
            "network-v4": f"import socket; sock=socket.socket(socket.AF_INET, socket.SOCK_STREAM); sock.connect(('127.0.0.1', {server.getsockname()[1]}))\n",
            "network-v6": f"import socket; sock=socket.socket(socket.AF_INET6, socket.SOCK_DGRAM); sock.sendto(b'escaped', ('::1', {ipv6.getsockname()[1]}))\n",
            "child-process": f"import subprocess; subprocess.run([{executable!r}, '-I', '-S', '-c', 'pass'], check=True)\n",
            "additional-exec": f"import os; os.execv({executable!r}, [{executable!r}, '-I', '-S', '-c', 'pass'])\n",
            "outside-write": f"from pathlib import Path; Path({str(outside)!r}).write_text('escaped')\n",
            "snapshot-write": "from pathlib import Path; Path(__file__).write_text('overwritten')\n",
        }
        if sys.platform == "linux":
            probes["symlink-create"] = "from pathlib import Path; Path('link').symlink_to('/etc/passwd')\n"
        for name, source in probes.items():
            with self.subTest(probe=name):
                (self.bundle / "scripts/search.py").write_text(source + "print('## Design System: escaped')\n", encoding="utf-8")
                self.refresh_integrity()
                result = self.executor.invoke(
                    replace(self.invocation(), invocation_id="qualification-" + name), provider_root=self.bundle
                )
                self.assertEqual("fallback", result.status)
                self.assertIn("provider exited with status", result.warning, "sandbox setup failure cannot count as a denied probe")
                self.assertNotIn("escaped", result.output)
                self.assertFalse(outside.exists())

    @unittest.skipUnless(sys.platform in {"darwin", "linux", "win32"}, "production OS sandbox")
    def test_production_sandbox_enforces_timeout_and_output_limit(self) -> None:
        self._require_production_sandbox()
        provider = self.catalog.providers["ui-ux-pro-max"]
        self.catalog.providers[provider.id] = replace(provider, timeout_seconds=1)
        probes = {
            "timeout": "import time; time.sleep(10)\nprint('## Design System: escaped')\n",
            "output-limit": "print('## Design System: ' + 'X' * 1000000)\n",
        }
        for name, source in probes.items():
            with self.subTest(probe=name):
                (self.bundle / "scripts/search.py").write_text(source, encoding="utf-8")
                self.refresh_integrity()
                result = self.executor.invoke(
                    replace(self.invocation(), invocation_id="qualification-" + name), provider_root=self.bundle
                )
                self.assertEqual("fallback", result.status)
                if name == "timeout":
                    self.assertIn("timed out", result.warning)
                self.assertLessEqual(len(result.output.encode("utf-8")), 128 * 1024)

    @unittest.skipUnless(sys.platform == "darwin", "Darwin sandbox contract")
    def test_production_sandbox_denies_shared_temp_and_child_processes(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            secret = Path(handle.name)
            handle.write(b"PRIVATE-TMP-SECRET")
        self.addCleanup(secret.unlink, missing_ok=True)
        (self.bundle / "scripts/search.py").write_text(
            "from pathlib import Path\n"
            f"print('## Design System: ' + Path({str(secret)!r}).read_text())\n",
            encoding="utf-8",
        )
        self.refresh_integrity()
        leaked = self.executor.invoke(
            replace(self.invocation(), invocation_id="ui-advice-shared-temp"),
            provider_root=self.bundle,
        )
        self.assertEqual("fallback", leaked.status)
        self.assertNotIn("PRIVATE-TMP-SECRET", leaked.output)

        (self.bundle / "scripts/search.py").write_text(
            "import subprocess\n"
            "subprocess.run(['/bin/sh', '-c', 'sleep 60'], check=True)\n"
            "print('## Design System: child escaped')\n",
            encoding="utf-8",
        )
        self.refresh_integrity()
        child = self.executor.invoke(
            replace(self.invocation(), invocation_id="ui-advice-child"),
            provider_root=self.bundle,
        )
        self.assertEqual("fallback", child.status)
        self.assertNotIn("child escaped", child.output)

    def test_empty_output_is_not_reported_as_completed(self) -> None:
        (self.bundle / "scripts/search.py").write_text("pass\n", encoding="utf-8")
        self.refresh_integrity()
        with patch.object(
            ProviderExecutor,
            "_sandbox_command",
            side_effect=lambda command, _bundle, _work, _denied: command,
        ):
            result = self.executor.invoke(
                replace(self.invocation(), invocation_id="ui-advice-empty"),
                provider_root=self.bundle,
            )
        self.assertEqual("fallback", result.status)
        self.assertIn("empty output", result.warning)

    def test_output_limit_is_enforced_before_loading_into_memory(self) -> None:
        (self.bundle / "scripts/search.py").write_text(
            "print('X' * 200000)\n", encoding="utf-8"
        )
        self.refresh_integrity()
        with patch.object(
            ProviderExecutor,
            "_sandbox_command",
            side_effect=lambda command, _bundle, _work, _denied: command,
        ):
            result = self.executor.invoke(
                replace(self.invocation(), invocation_id="ui-advice-large"),
                provider_root=self.bundle,
            )
        self.assertEqual("fallback", result.status)
        self.assertLessEqual(len(result.output.encode("utf-8")), 128 * 1024)


if __name__ == "__main__":
    unittest.main()
