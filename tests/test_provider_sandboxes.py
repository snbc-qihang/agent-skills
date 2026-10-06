from __future__ import annotations

import ctypes
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant import provider_sandbox_linux as linux  # noqa: E402
from engineering_assistant import provider_sandbox_macos as macos  # noqa: E402
from engineering_assistant import provider_sandbox_windows as windows  # noqa: E402


class ProviderSandboxContractTests(unittest.TestCase):
    """Portable unit contracts complement, never replace, OS qualification."""

    @staticmethod
    def filter_result(architecture: str, syscall: int, audit_arch: int | None = None) -> int:
        instructions = linux._filter_instructions(architecture)
        accumulator, index = 0, 0
        while index < len(instructions):
            code, yes, no, value = instructions[index]
            if code == 0x20:
                accumulator = syscall if value == 0 else audit_arch or linux._ARCHITECTURES[architecture]["audit_arch"]
            elif code == 0x15:
                index += yes if accumulator == value else no
            elif code == 0x06:
                return value
            else:
                raise AssertionError("unexpected BPF instruction")
            index += 1
        raise AssertionError("filter did not terminate")

    def test_linux_filter_denies_network_processes_signals_privilege_and_unknown_syscalls(self) -> None:
        denied = {
            "x86_64": {41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55,
                       56, 57, 58, 59, 62, 90, 91, 101, 200, 234, 272, 288, 298,
                       299, 307, 308, 310, 311, 317, 321, 322, 425, 426, 427, 435},
            "aarch64": {29, 40, 51, 52, 53, 54, 55, 97, 117, 129, 130, 131, 167,
                        180, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207,
                        208, 209, 210, 211, 212, 220, 221, 242, 268, 270, 271,
                        277, 280, 281, 425, 426, 427, 435},
        }
        for architecture, numbers in denied.items():
            for number in numbers | {99999, 0x40000000}:
                with self.subTest(architecture=architecture, syscall=number):
                    self.assertEqual(0x00050001, self.filter_result(architecture, number))

    def test_linux_filter_allows_required_read_write_and_rejects_another_abi(self) -> None:
        for architecture, numbers in {"x86_64": {0, 1, 3, 9, 60, 257}, "aarch64": {56, 57, 63, 64, 93, 222}}.items():
            for number in numbers:
                self.assertEqual(0x7FFF0000, self.filter_result(architecture, number))
            self.assertEqual(0x80000000, self.filter_result(architecture, 0, 0x40000003))
        self.assertEqual(12, ctypes.sizeof(linux._PathRule))

    def test_macos_profile_has_no_exec_exception_and_quotes_paths(self) -> None:
        profile = macos.profile('/runtime/"quoted"', "/private/bundle", "/private/work")
        self.assertIn("(deny default)", profile)
        self.assertIn("(deny process-exec)", profile)
        self.assertIn("(deny process-fork)", profile)
        self.assertIn("(deny network*)", profile)
        self.assertNotIn("(allow process-exec", profile)
        self.assertIn('/runtime/\\"quoted\\"', profile)

    def test_windows_terminates_suspended_process_if_job_assignment_failed(self) -> None:
        kernel = Mock()
        kernel.WaitForSingleObject.return_value = 0
        api = SimpleNamespace(kernel=kernel)
        windows._terminate_process(api, 123, 456, False)
        kernel.TerminateJobObject.assert_not_called()
        kernel.TerminateProcess.assert_called_once_with(123, 1)
        kernel.WaitForSingleObject.assert_called_once_with(123, 5000)

    def test_windows_job_termination_has_direct_process_fallback(self) -> None:
        kernel = Mock()
        kernel.WaitForSingleObject.return_value = 0
        kernel.TerminateJobObject.return_value = False
        api = SimpleNamespace(kernel=kernel)
        windows._terminate_process(api, 123, 456, True)
        kernel.TerminateJobObject.assert_called_once_with(456, 1)
        kernel.TerminateProcess.assert_called_once_with(123, 1)

    def test_windows_unconfirmed_exit_is_a_failure(self) -> None:
        kernel = Mock()
        kernel.WaitForSingleObject.return_value = 258
        with self.assertRaisesRegex(OSError, "could not confirm exit"):
            windows._terminate_process(SimpleNamespace(kernel=kernel), 123, 456, False)


if __name__ == "__main__":
    unittest.main()
