from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
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
        ) as access, patch.object(windows, "_traverse_privilege", return_value={"present": True, "enabled": True}):
            result = windows._startup_access(api, 12, Path("runtime"), Path("bundle"), Path("work"))
        self.assertIs(result["appcontainer"], True)
        self.assertEqual({"error": 87}, result["lpac"])
        self.assertEqual(7, access.call_count)
        self.assertEqual({"allowed": True, "mask": "0x00000022"}, result["default_desktop"])
        self.assertEqual([456, 123], [call.args[0].value for call in api.close.call_args_list])

    def test_private_parent_acl_grants_only_noninheriting_traverse(self) -> None:
        api = object.__new__(windows._Api)
        api.advapi, api.kernel = Mock(), Mock()
        api.check = lambda result, operation: result
        api.advapi.SetNamedSecurityInfoW.return_value = 0
        with patch.object(windows, "_reparse", return_value=False), patch.object(Path, "is_dir", return_value=True):
            api.acl(Path("private-root"), "owner", "package", traverse_only=True)
        sddl = api.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.call_args.args[0]
        self.assertIn("(A;;0x00000020;;;package)", sddl)
        self.assertNotIn("OICI;0x00000020", sddl)
        self.assertNotIn("FRFX;;;package", sddl)

    def test_production_run_never_passes_a_startup_experiment(self) -> None:
        arguments = (["provider.exe"], Path("bundle"), Path("work"), {}, 1, 4096)
        observer = {}
        with patch.object(windows, "_run_lpac", create=True, return_value=(0, b"", b"")) as launch:
            self.assertEqual((0, b"", b""), windows.run(*arguments, diagnostics=observer))
        launch.assert_called_once_with(*arguments, diagnostics=observer)
        with self.assertRaises(TypeError):
            windows.run(*arguments, experiment="registry_read")

    def test_startup_experiments_reject_provider_commands_before_using_winapi(self) -> None:
        for command, experiment, observer in (
            (["provider.exe", "scripts/search.py"], "registry_only", {}),
            (windows._STARTUP_COMMAND, "internetClient", {}),
            (windows._STARTUP_COMMAND, "registry_only", None),
        ):
            with self.subTest(experiment=experiment, command=command):
                with patch.object(windows, "_Api") as native:
                    with self.assertRaisesRegex(OSError, "fixed startup diagnostic"):
                        windows._run_lpac(command, Path("bundle"), Path("work"), {}, 1, 4096,
                                          diagnostics=observer, _experiment=experiment)
                native.assert_not_called()

    def test_registry_diagnostic_frees_individual_sids_and_arrays_after_use(self) -> None:
        groups = (windows.HANDLE * 2)(101, 102)
        capabilities = (windows.HANDLE * 1)(201)
        native = Mock()

        def derive(name, group_output, group_count, capability_output, capability_count):
            self.assertEqual("registryRead", name)
            ctypes.cast(group_output, ctypes.POINTER(ctypes.POINTER(windows.HANDLE)))[0] = groups
            ctypes.cast(capability_output, ctypes.POINTER(ctypes.POINTER(windows.HANDLE)))[0] = capabilities
            group_count._obj.value = 2
            capability_count._obj.value = 1
            return 1

        native.DeriveCapabilitySidsFromName.side_effect = derive
        api = SimpleNamespace(kernel=Mock(), check=lambda result, operation: self.assertTrue(result))
        with patch("ctypes.WinDLL", create=True, return_value=native):
            with windows._registry_capability(api) as entries:
                self.assertEqual(16, ctypes.sizeof(windows._SidAndAttributes))
                self.assertEqual(201, entries[0].sid)
                self.assertEqual(4, entries[0].attributes)
                api.kernel.LocalFree.assert_not_called()
        freed = [call.args[0].value if isinstance(call.args[0], ctypes.c_void_p) else call.args[0]
                 for call in api.kernel.LocalFree.call_args_list]
        self.assertEqual({101, 102, 201, ctypes.addressof(groups), ctypes.addressof(capabilities)}, set(freed))
        self.assertEqual(5, len(freed))

    def test_registry_sid_lifetime_cleanup_survives_failed_launch_and_invalid_count(self) -> None:
        for invalid_count in (False, True):
            with self.subTest(invalid_count=invalid_count):
                groups = (windows.HANDLE * 1)(101)
                capabilities = (windows.HANDLE * 2)(201, 202)
                native = Mock()

                def derive(name, group_output, group_count, capability_output, capability_count):
                    ctypes.cast(group_output, ctypes.POINTER(ctypes.POINTER(windows.HANDLE)))[0] = groups
                    ctypes.cast(capability_output, ctypes.POINTER(ctypes.POINTER(windows.HANDLE)))[0] = capabilities
                    group_count._obj.value = 1
                    capability_count._obj.value = 2 if invalid_count else 1
                    return 1

                native.DeriveCapabilitySidsFromName.side_effect = derive
                api = SimpleNamespace(kernel=Mock(), check=lambda result, operation: self.assertTrue(result))
                with patch("ctypes.WinDLL", create=True, return_value=native):
                    with self.assertRaisesRegex(OSError if invalid_count else RuntimeError,
                                                "invalid SID count" if invalid_count else "failed launch"):
                        with windows._registry_capability(api):
                            api.kernel.LocalFree.assert_not_called()
                            raise RuntimeError("failed launch")
                freed = [call.args[0].value if isinstance(call.args[0], ctypes.c_void_p) else call.args[0]
                         for call in api.kernel.LocalFree.call_args_list]
                expected = {101, 201, ctypes.addressof(groups), ctypes.addressof(capabilities)}
                if invalid_count:
                    expected.add(202)
                self.assertEqual(expected, set(freed))
                self.assertEqual(len(expected), len(freed))

    def test_traverse_privilege_query_is_read_only_and_rejects_invalid_count(self) -> None:
        for attributes, invalid_count in ((0, False), (2, False), (2, True)):
            with self.subTest(attributes=attributes, invalid_count=invalid_count):
                api = SimpleNamespace(advapi=Mock(), check=lambda result, operation: self.assertTrue(result))

                def lookup(system, name, luid):
                    self.assertIsNone(system)
                    self.assertEqual("SeChangeNotifyPrivilege", name)
                    luid._obj.low = 42
                    return 1

                entry = windows._LuidAndAttributes(windows._Luid(42, 0), attributes)
                data = bytes(windows.DWORD(2 if invalid_count else 1)) + bytes(entry)

                def information(token, kind, buffer, size, length):
                    self.assertEqual(3, kind)
                    length._obj.value = len(data)
                    if buffer is None:
                        return 0
                    ctypes.memmove(buffer, data, len(data))
                    return 1

                api.advapi.LookupPrivilegeValueW.side_effect = lookup
                api.advapi.GetTokenInformation.side_effect = information
                if invalid_count:
                    with self.assertRaisesRegex(OSError, "privilege count is invalid"):
                        windows._traverse_privilege(api, 123)
                else:
                    self.assertEqual({"present": True, "enabled": bool(attributes & 2)},
                                     windows._traverse_privilege(api, 123))
                api.advapi.AdjustTokenPrivileges.assert_not_called()

    def test_fixed_startup_matrix_has_fresh_roots_and_never_qualifies_experiments(self) -> None:
        # Orchestration contract only: substitute launch outcomes do not prove
        # any Windows native startup or sandbox boundary.
        for parent_succeeded in (False, True):
            with self.subTest(parent_succeeded=parent_succeeded):
                modes, roots = [], []

                def launch(command, bundle, work, environment, timeout, output_limit, **options):
                    self.assertEqual(windows._STARTUP_COMMAND, command)
                    self.assertEqual(10, timeout)
                    self.assertEqual(4096, output_limit)
                    self.assertTrue(work.is_dir())
                    self.assertEqual(work.parent, bundle.parent)
                    mode = options["_experiment"]
                    modes.append(mode)
                    roots.append(str(work.parent))
                    return (0, b"EA_LPAC_STARTUP_OK", b"") if parent_succeeded and mode == "parent_only" else (0xC0000142, b"", b"")

                api = Mock()
                baseline = SimpleNamespace(returncode=0, stdout=b"EA_LPAC_STARTUP_OK", stderr=b"")
                with patch.object(windows, "capability", return_value={"supported": True, "backend": "windows-lpac"}), \
                     patch.object(windows, "_Api", return_value=api), \
                     patch.object(windows, "_private_runtime", return_value=Path("python.exe")), \
                     patch.object(windows.subprocess, "run", return_value=baseline), \
                     patch.object(windows, "_run_lpac", side_effect=launch):
                    result = windows.diagnose()
                self.assertIs(result["qualified"], False)
                self.assertIs(result["strict_lpac"]["marker"], False)
                self.assertEqual(len(roots), len(set(roots)))
                if parent_succeeded:
                    self.assertEqual([None, "parent_only"], modes)
                    self.assertEqual("private_parent_startup_succeeded", result["registry_only"]["not_run"])
                else:
                    self.assertEqual([None, "parent_only", "registry_only", "parent_and_registry"], modes)

    def test_profile_diagnostic_payload_reports_only_six_path_categories(self) -> None:
        environment = dict(os.environ)
        environment.update({"LOCALAPPDATA": "C:\\fresh-profile\\AC", "TEMP": "C:\\fresh-profile\\AC\\Temp",
                            "TMP": "C:\\private-work\\tmp", "TMPDIR": "D:\\outside-secret",
                            "APPDATA": "C:\\private-work-lookalike", "USERPROFILE": ""})
        process = subprocess.run([sys.executable, *windows._PROFILE_COMMAND[1:],
                                  "C:\\private-work", "C:\\fresh-profile\\AC"],
                                 env=environment, capture_output=True, timeout=5, check=True)
        self.assertEqual({"marker": True, "environment": {
            "LOCALAPPDATA": "new_profile", "TEMP": "new_profile", "TMP": "work",
            "TMPDIR": "other", "APPDATA": "other", "USERPROFILE": "missing",
        }}, windows._profile_result(process.returncode, process.stdout))
        self.assertNotIn(b"fresh-profile", process.stdout)
        self.assertNotIn(b"outside-secret", process.stdout)
        malformed = json.dumps({"marker": "EA_LPAC_STARTUP_OK", "environment": {"TEMP": "host-secret"}}).encode()
        self.assertEqual({"marker": False, "payload_error": "invalid_fixed_payload"},
                         windows._profile_result(0, malformed))

    def test_profile_readonly_is_only_for_exact_trusted_command_and_observer(self) -> None:
        for command, observer in ((windows._STARTUP_COMMAND, {}), (["provider.exe"], {}),
                                  (windows._PROFILE_COMMAND + ["external-path"], {}),
                                  (windows._PROFILE_COMMAND, None)):
            with self.subTest(command=command):
                with patch.object(windows, "_Api") as api:
                    with self.assertRaisesRegex(OSError, "fixed startup diagnostic"):
                        windows._run_lpac(command, Path("bundle"), Path("work"), {}, 1, 4096,
                                          diagnostics=observer, _experiment="profile_readonly")
                api.assert_not_called()

    def test_profile_readonly_changes_only_new_profile_and_seals_production(self) -> None:
        # WinAPI preparation seam only. A deliberate stop occurs before any
        # process creation; this does not claim a Windows startup result.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "fresh-profile"
            profile.mkdir()
            (profile / "Temp").mkdir()
            for experiment in (None, "profile_readonly"):
                with self.subTest(experiment=experiment):
                    api = Mock()
                    api.owner_sid.return_value = "owner"
                    api.sid_text.return_value = "package"
                    api.userenv.CreateAppContainerProfile.side_effect = lambda *args: setattr(args[-1]._obj, "value", 77) or 0
                    api.userenv.GetAppContainerFolderPath.side_effect = lambda sid, output: setattr(output._obj, "value", str(profile)) or 0
                    api.userenv.DeleteAppContainerProfile.return_value = 0
                    with patch.object(windows, "capability", return_value={"supported": True}), \
                         patch.object(windows, "_Api", return_value=api), \
                         patch("ctypes.WinDLL", create=True), \
                         patch.object(windows, "_private_runtime", side_effect=RuntimeError("stop before launch")):
                        with self.assertRaisesRegex(RuntimeError, "stop before launch"):
                            windows._run_lpac(list(windows._PROFILE_COMMAND), root / "bundle", root / "work", {}, 1, 4096,
                                              diagnostics={}, _experiment=experiment)
                    expected_sid = "package" if experiment else None
                    self.assertEqual([(profile, "owner", expected_sid, False),
                                      (profile / "Temp", "owner", expected_sid, False)],
                                     [call.args for call in api.acl.call_args_list])
                    api.kernel.CreateProcessW.assert_not_called()
                    api.userenv.DeleteAppContainerProfile.assert_called_once()

    def test_profile_startup_matrix_has_fresh_roots_zero_capabilities_and_no_qualification(self) -> None:
        modes, roots = [], []
        payload = json.dumps({"marker": "EA_LPAC_STARTUP_OK", "environment": {
            name: "work" for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "TEMP", "TMP", "TMPDIR")
        }}).encode()

        def launch(command, bundle, work, environment, timeout, output_limit, **options):
            self.assertEqual(windows._PROFILE_COMMAND, command)
            self.assertEqual((10, 4096), (timeout, output_limit))
            self.assertEqual(work.parent, bundle.parent)
            modes.append(options["_experiment"])
            roots.append(str(work.parent))
            return (0, payload, b"") if options["_experiment"] == "profile_readonly" else (0xC0000142, b"", b"")

        with patch.object(windows, "capability", return_value={"supported": True, "backend": "windows-lpac"}), \
             patch.object(windows, "_Api"), \
             patch.object(windows, "_private_runtime", return_value=Path("python.exe")), \
             patch.object(windows.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=payload)), \
             patch.object(windows, "_registry_capability") as registry, \
             patch.object(windows, "_run_lpac", side_effect=launch):
            result = windows.diagnose_profile()
        self.assertEqual([None, "profile_readonly"], modes)
        self.assertEqual(2, len(set(roots)))
        self.assertIs(result["qualified"], False)
        self.assertIs(result["strict_lpac"]["marker"], False)
        self.assertIs(result["new_profile_readonly"]["marker"], True)
        registry.assert_not_called()

    def test_profile_readonly_keeps_all_four_process_attributes_and_zero_capabilities(self) -> None:
        # Inspect the SDK call boundary and deliberately stop CreateProcess.
        # This checks configuration; real LPAC execution still needs Windows.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "fresh-profile"
            profile.mkdir()
            api = Mock()
            api.check = lambda value, operation: value
            api.owner_sid.return_value = "owner"
            api.sid_text.return_value = "package"
            api.userenv.CreateAppContainerProfile.side_effect = lambda *args: setattr(args[-1]._obj, "value", 77) or 0
            api.userenv.GetAppContainerFolderPath.side_effect = lambda sid, output: setattr(output._obj, "value", str(profile)) or 0
            api.userenv.DeleteAppContainerProfile.return_value = 0
            api.kernel.CreateFileW.return_value = 99
            attributes = {}

            def pipe(reader, writer, security, size):
                reader._obj.value, writer._obj.value = 101, 102
                return 1

            def initialize(pointer, count, flags, length):
                self.assertEqual(4, count)
                length._obj.value = 128
                return int(bool(pointer))

            def update(pointer, flags, attribute, value, size, old, length):
                if attribute == 0x20009:
                    self.assertEqual(ctypes.sizeof(windows._SecurityCapabilities), size)
                    self.assertEqual((77, None, 0, 0),
                                     (value._obj.sid, value._obj.capabilities, value._obj.count, value._obj.reserved))
                    attributes[attribute] = "zero_capabilities"
                elif attribute == 0x20002:
                    self.assertEqual(3 * ctypes.sizeof(windows.HANDLE), size)
                    attributes[attribute] = list(value._obj)
                else:
                    attributes[attribute] = value._obj.value
                return 1

            def create(executable, command, process_security, thread_security, inherit, flags, environment, cwd, startup, process):
                self.assertEqual({0x20009: "zero_capabilities", 0x2000F: 1,
                                  0x2000E: 1, 0x20002: [99, 102, 102]}, attributes)
                self.assertEqual(0x80000 | 0x400 | 0x4 | 0x08000000, flags)
                self.assertTrue(inherit)
                self.assertEqual(0x100, startup._obj.startup.flags)
                self.assertTrue(command.value.endswith(subprocess.list2cmdline([str(root / "work"), str(profile)])))
                raise RuntimeError("stop before native process")

            api.kernel.CreatePipe.side_effect = pipe
            api.kernel.InitializeProcThreadAttributeList.side_effect = initialize
            api.kernel.UpdateProcThreadAttribute.side_effect = update
            api.kernel.CreateProcessW.side_effect = create
            with patch.object(windows, "capability", return_value={"supported": True}), \
                 patch.object(windows, "_Api", return_value=api), \
                 patch("ctypes.WinDLL", create=True), \
                 patch.object(windows, "_registry_capability") as registry, \
                 patch.object(windows, "_private_runtime", return_value=root / "runtime" / "python.exe"):
                with self.assertRaisesRegex(RuntimeError, "stop before native process"):
                    windows._run_lpac(list(windows._PROFILE_COMMAND), root / "bundle", root / "work", {}, 1, 4096,
                                      diagnostics={}, _experiment="profile_readonly")
            registry.assert_not_called()
            api.kernel.DeleteProcThreadAttributeList.assert_called_once()
            api.userenv.DeleteAppContainerProfile.assert_called_once()

    def test_profile_readonly_refuses_existing_profile_and_reparse_acl_targets(self) -> None:
        api = Mock()
        api.userenv.CreateAppContainerProfile.return_value = ctypes.c_int32(0x800700B7).value
        with patch.object(windows, "capability", return_value={"supported": True}), \
             patch.object(windows, "_Api", return_value=api):
            with self.assertRaisesRegex(OSError, "profile creation failed"):
                windows._run_lpac(list(windows._PROFILE_COMMAND), Path("bundle"), Path("work"), {}, 1, 4096,
                                  diagnostics={}, _experiment="profile_readonly")
        api.userenv.GetAppContainerFolderPath.assert_not_called()
        api.acl.assert_not_called()
        api.userenv.DeleteAppContainerProfile.assert_not_called()
        native = object.__new__(windows._Api)
        native.advapi = Mock()
        with patch.object(windows, "_reparse", return_value=True):
            with self.assertRaisesRegex(OSError, "ACL target is a reparse point"):
                windows._secure_tree(native, Path("fresh-profile"), "owner", "package", False)
        native.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.assert_not_called()


if __name__ == "__main__":
    unittest.main()
