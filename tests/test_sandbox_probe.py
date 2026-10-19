from __future__ import annotations

import os
import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.runtime.provider_runtime import ProviderExecutor  # noqa: E402
from engineering_assistant.runtime.sandbox_probe import _exec_probe, qualify  # noqa: E402


class SandboxProbeTests(unittest.TestCase):
    def test_windows_exec_probe_preserves_crt_arguments(self) -> None:
        # API argument contract only, not actual Windows confinement evidence.
        executable = r"C:\private runtime\python.exe"
        arguments = [executable, "-I", "-S", "-c", 'print("argument with spaces")']
        with patch("engineering_assistant.runtime.sandbox_probe.os.name", "nt"):
            source = _exec_probe(executable, arguments, "same_python_exec")
        with patch("os.execv", side_effect=PermissionError) as execute, redirect_stdout(io.StringIO()):
            exec(source, {})
        execute.assert_called_once_with(executable, [subprocess.list2cmdline([value]) for value in arguments])

    def test_command_interpreter_exec_does_not_apply_crt_escaping(self) -> None:
        executable = r"C:\Windows\System32\cmd.exe"
        arguments = [executable, "/d", "/c", 'echo {"extra_exec":false}']
        with patch("engineering_assistant.runtime.sandbox_probe.os.name", "nt"):
            source = _exec_probe(executable, arguments, "extra_exec", crt_arguments=False)
        with patch("os.execv", side_effect=PermissionError) as execute, redirect_stdout(io.StringIO()):
            exec(source, {})
        execute.assert_called_once_with(executable, arguments)

    def test_real_sandbox_qualification_requires_every_execution_boundary(self) -> None:
        capability = ProviderExecutor.sandbox_capability()
        if not capability["supported"]:
            if os.environ.get("ENGINEERING_ASSISTANT_REQUIRE_PROVIDER_SANDBOX") == "1":
                self.fail(capability["reason"])
            self.skipTest(capability["reason"])
        result = qualify(ROOT)
        self.assertTrue(result["qualified"], result)
        for name in (
            "positive_execution", "snapshot_read", "private_work_write",
            "network_ipv4", "network_ipv6", "child_process", "same_python_exec",
            "extra_exec", "outside_read", "outside_write", "snapshot_write",
        ):
            self.assertIs(result["checks"][name], True, name)
        self.assertEqual({"network_ipv4": True, "network_ipv6": True}, result["baselines"])

    def test_unavailable_capability_is_never_reported_as_qualified(self) -> None:
        # Diagnostic contract only; this substitute is not OS execution evidence.
        with patch.object(ProviderExecutor, "sandbox_capability", return_value={
            "supported": False, "backend": "unavailable", "reason": "disabled on host",
        }), patch.object(ProviderExecutor, "invoke") as invoke:
            result = qualify(ROOT)
        self.assertFalse(result["qualified"])
        self.assertEqual("disabled on host", result["reason"])
        invoke.assert_not_called()

    def test_diagnostic_rejects_a_real_unconfined_control(self) -> None:
        # Detector sensitivity control, not OS sandbox qualification. Execute
        # the same bounded fixture without the production confinement seam.
        def unconfined(_executor, _provider, _invocation, bundle, work, _denied):
            result = subprocess.run(
                [sys.executable, "-I", "-S", str(bundle / "scripts/search.py")],
                cwd=work, stdin=subprocess.DEVNULL, capture_output=True, timeout=5, check=True,
            )
            return result.stdout.decode("utf-8").strip()

        with patch.object(ProviderExecutor, "sandbox_capability", return_value={
            "supported": True, "backend": "unconfined-control", "reason": None,
        }), patch.object(ProviderExecutor, "_run_ui_ux_pro_max", new=unconfined):
            result = qualify(ROOT)
        self.assertFalse(result["qualified"], result)
        self.assertEqual({
            "positive_execution", "snapshot_read", "private_work_write",
            "network_ipv4", "network_ipv6", "outside_read", "outside_write",
            "snapshot_write", "child_process", "same_python_exec", "extra_exec",
        }, set(result["checks"]), result)
        for name in (
            "network_ipv4", "network_ipv6", "outside_read", "outside_write",
            "snapshot_write", "child_process", "same_python_exec", "extra_exec",
        ):
            self.assertIs(result["checks"][name], False, name)

    def test_completed_output_without_required_checks_cannot_qualify(self) -> None:
        # Result validation only; fabricated output provides no OS evidence.
        with patch.object(ProviderExecutor, "sandbox_capability", return_value={
            "supported": True, "backend": "output-contract", "reason": None,
        }), patch.object(ProviderExecutor, "_run_ui_ux_pro_max", return_value="## Design System: SandboxProbe\n{}"):
            result = qualify(ROOT)
        self.assertFalse(result["qualified"])
        self.assertIn("incomplete or invalid checks", result["reason"])


if __name__ == "__main__":
    unittest.main()
