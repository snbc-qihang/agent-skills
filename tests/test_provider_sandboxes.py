from __future__ import annotations

import ctypes
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


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

    def test_windows_lpac_creation_environment_has_private_local_app_data(self) -> None:
        work = Path("private-work")
        block = windows._environment_block({
            "SystemRoot": "C:\\Windows", "TMP": "old-profile",
            "LOCALAPPDATA": "host-app-data", "HOME": "host-home", "HTTP_PROXY": "host-proxy",
        }, work)
        entries = {name: value for name, value in (
            item.split("=", 1) for item in block[:].rstrip("\0").split("\0")
        )}
        self.assertEqual(str(work), entries.get("LOCALAPPDATA"))
        self.assertEqual(str(work), entries["TMP"])
        self.assertNotIn("host-", block[:])
        self.assertNotIn("HOME", entries)
        self.assertNotIn("HTTP_PROXY", entries)
        self.assertTrue(block[:].endswith("\0\0"))

    def test_windows_environment_is_case_insensitive_and_rejects_embedded_nuls(self) -> None:
        block = windows._environment_block({"SystemRoot": "C:\\Windows", "TMP": "work", "LANG": "C.UTF-8"}, Path("work"))
        names = [item.split("=", 1)[0] for item in block[:].rstrip("\0").split("\0")]
        self.assertEqual(sorted(names, key=str.upper), names)
        with self.assertRaisesRegex(OSError, "invalid.*environment"):
            windows._environment_block({"SystemRoot": "C:\\Windows\0HOME=host"}, Path("work"))

    def test_windows_startup_access_check_uses_impersonation_and_bounded_storage(self) -> None:
        # WinAPI call contract only; native Windows diagnosis must run separately.
        def access_check(descriptor, token, desired, mapping, privileges, length, granted, status):
            self.assertEqual(123, token)
            self.assertEqual(0x02000000, desired)
            self.assertEqual(4096, length._obj.value)
            granted._obj.value = 0x22
            status._obj.value = 1
            return 1

        api = SimpleNamespace(check=lambda result, operation: self.assertTrue(result),
                              advapi=SimpleNamespace(AccessCheck=Mock(side_effect=access_check)))
        self.assertEqual({"allowed": True, "mask": "0x00000022"},
                         windows._access_mask(api, b"descriptor", 123, (1, 2, 3, 4)))

    def test_windows_diagnostic_is_explicitly_not_qualification(self) -> None:
        with patch.object(windows, "capability", return_value={
            "supported": False, "backend": "windows-lpac", "reason": "not Windows",
        }):
            result = windows.diagnose()
        self.assertIs(result["qualified"], False)
        self.assertEqual("startup_diagnostic_only", result["assurance"])

    def test_unavailable_lpac_token_query_does_not_discard_access_observations(self) -> None:
        # Optional TokenIsLessPrivilegedAppContainer can fail with WinError 87;
        # failure is unavailable evidence, not a false flag or a reason to lose
        # the other read-only observations. This is a WinAPI seam, not native.
        def checked(value, operation):
            if not value:
                raise OSError(87, operation)
            return value

        def token_information(token, kind, value, size, length):
            if kind == 46:
                return 0
            value._obj.value = 1
            length._obj.value = 4
            return 1

        def descriptor(*arguments):
            arguments[-1]._obj.value = 32
            return 1

        api = SimpleNamespace(kernel=Mock(), advapi=Mock(), check=checked, close=Mock())
        api.advapi.OpenProcessToken.side_effect = lambda process, access, token: setattr(token._obj, "value", 123) or 1
        api.advapi.DuplicateToken.side_effect = lambda token, level, duplicate: setattr(duplicate._obj, "value", 456) or 1
        api.advapi.GetTokenInformation.side_effect = token_information
        api.advapi.GetFileSecurityW.side_effect = descriptor
        user = Mock()
        user.GetUserObjectSecurity.side_effect = descriptor
        user.GetProcessWindowStation.return_value = 100
        user.GetThreadDesktop.return_value = 200
        with patch("ctypes.WinDLL", create=True, return_value=user), patch.object(
            windows, "_access_mask", return_value={"allowed": True, "mask": "0x00000022"},
        ) as access:
            result = windows._startup_access(api, 12, Path("runtime"), Path("bundle"), Path("work"))
        self.assertIs(result["appcontainer"], True)
        self.assertEqual({"error": 87}, result["lpac"])
        self.assertEqual(7, access.call_count)
        self.assertEqual({"allowed": True, "mask": "0x00000022"}, result["default_desktop"])
        self.assertEqual([456, 123], [call.args[0].value for call in api.close.call_args_list])


if __name__ == "__main__":
    unittest.main()
