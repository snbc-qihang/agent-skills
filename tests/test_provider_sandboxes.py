from __future__ import annotations

import ctypes
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.platforms import provider_sandbox_linux as linux
from engineering_assistant.platforms import provider_sandbox_macos as macos
from engineering_assistant.platforms import provider_sandbox_windows as windows


class WindowsPrivatePythonTests(unittest.TestCase):
    def fixture(self, root):
        source = root / "source"
        source.mkdir()
        images, records = {}, {}
        for name, offset in (("python.exe", 96), ("python313.dll", 128)):
            data = bytearray(b"unchanged image bytes" * 32)
            struct.pack_into("<I", data, offset, 24)
            original = bytes(data)
            struct.pack_into("<I", data, offset, 65535)
            derived = bytes(data)
            (source / name).write_bytes(original)
            images[name] = original, derived
            records[name] = hashlib.sha256(original).hexdigest(), offset, hashlib.sha256(derived).hexdigest()
        (source / "Lib").mkdir()
        (source / "Lib/os.py").write_bytes(b"unchanged standard library")
        return source, images, records

    def test_fixed_private_worker_changes_only_known_manifest_type_and_never_shared_python(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, images, records = self.fixture(root)
            with patch.object(windows.sys, "base_prefix", str(source)), \
                 patch.object(windows, "_LPAC_PYTHON_IMAGES", records):
                executable = windows._private_runtime(root / "private")
            self.assertEqual(root / "private/python.exe", executable)
            for name, (original, derived) in images.items():
                self.assertEqual(original, (source / name).read_bytes())
                self.assertEqual(derived, (root / "private" / name).read_bytes())
            self.assertEqual(b"unchanged standard library", (root / "private/Lib/os.py").read_bytes())

    def test_unknown_changed_and_truncated_runtime_never_returns_an_executable(self):
        for mode in ("unknown", "changed", "truncated", "missing"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, images, records = self.fixture(root)
                image = source / "python313.dll"
                if mode == "missing":
                    image.unlink()
                else:
                    original = images[image.name][0]
                    image.write_bytes(original + b"certificate" if mode == "unknown" else
                                      original[:-1] + b"X" if mode == "changed" else original[:-1])
                with patch.object(windows.sys, "base_prefix", str(source)), \
                     patch.object(windows, "_LPAC_PYTHON_IMAGES", records), self.assertRaises(OSError):
                    windows._private_runtime(root / "private")

    def test_derived_image_is_read_back_before_worker_can_be_returned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, _images, records = self.fixture(root)
            write = Path.write_bytes
            def corrupt(path, data):
                return write(path, data[:-1])
            with patch.object(windows.sys, "base_prefix", str(source)), \
                 patch.object(windows, "_LPAC_PYTHON_IMAGES", records), \
                 patch.object(Path, "write_bytes", corrupt), self.assertRaises(OSError):
                windows._private_runtime(root / "private")

    @unittest.skipUnless(sys.platform == "win32", "native fixed Windows worker token")
    def test_windows_private_worker_retains_token_restrictions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            bundle, work = root / "bundle", root / "work"
            bundle.mkdir()
            work.mkdir()
            api = windows._Api()
            api.acl(root, api.owner_sid(), None, False)
            diagnostics = {}
            code, output, error = windows.run(list(windows._STARTUP_COMMAND), bundle, work,
                {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR"}},
                10, 4096, diagnostics=diagnostics)
        self.assertEqual(0, code)
        self.assertIn(b"EA_LPAC_STARTUP_OK", output)
        access = diagnostics["access"]
        self.assertIs(access["appcontainer"], True)
        self.assertEqual("low", access["child_integrity"]["level"])
        self.assertIs(access["ui_access"], False)
        self.assertIs(access["virtualization_enabled"], False)
        self.assertEqual(0, access["capability_count"])
        # Never print trusted-startup text or host paths. These finite labels
        # distinguish residual Python/CRT diagnostics without storing content.
        words = ("warning", "runtimewarning", "registry", "path", "encoding", "codec", "console",
                 "handle", "ignored", "permission", "access", "denied", "utf", "thread", "locale")
        print(json.dumps({"fixed_worker_stderr_bytes": len(error),
                          "fixed_worker_stderr_tags": [word for word in words if word.encode() in error.lower()]}))


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
            result = windows.diagnose_console()
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
            if kind == 30:
                length._obj.value = 8
                if value is not None:
                    struct.pack_into("<I", value, 0, 0)
                return int(value is not None)
            if value is None:
                length._obj.value = 4
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

    def test_production_run_exposes_only_read_only_diagnostics(self) -> None:
        arguments = (["provider.exe"], Path("bundle"), Path("work"), {}, 1, 4096)
        observer = {}
        with patch.object(windows, "_run_lpac", create=True, return_value=(0, b"", b"")) as launch:
            self.assertEqual((0, b"", b""), windows.run(*arguments, diagnostics=observer))
        launch.assert_called_once_with(*arguments, diagnostics=observer)
        for option in ("_console_diagnostic", "_loader_diagnostic"):
            with self.assertRaises(TypeError):
                windows.run(*arguments, **{option: True})

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

    def test_windows_production_seals_new_profile_and_cleans_up_preparation_failure(self) -> None:
        # Stop before process creation: this checks ACL and resource ownership,
        # not a Windows startup or security qualification result.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "fresh-profile"
            profile.mkdir()
            (profile / "Temp").mkdir()
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
                    windows.run(["provider.exe"], root / "bundle", root / "work", {}, 1, 4096)
            self.assertEqual([(profile, "owner", None, False),
                              (profile / "Temp", "owner", None, False)],
                             [call.args for call in api.acl.call_args_list])
            api.kernel.CreateProcessW.assert_not_called()
            api.advapi.FreeSid.assert_called_once()
            api.userenv.DeleteAppContainerProfile.assert_called_once()

    def test_windows_production_refuses_existing_profile_and_reparse_acl_targets(self) -> None:
        api = Mock()
        api.userenv.CreateAppContainerProfile.return_value = ctypes.c_int32(0x800700B7).value
        with patch.object(windows, "capability", return_value={"supported": True}), \
             patch.object(windows, "_Api", return_value=api):
            with self.assertRaisesRegex(OSError, "profile creation failed"):
                windows.run(["provider.exe"], Path("bundle"), Path("work"), {}, 1, 4096)
        api.userenv.GetAppContainerFolderPath.assert_not_called()
        api.acl.assert_not_called()
        api.userenv.DeleteAppContainerProfile.assert_not_called()
        native = object.__new__(windows._Api)
        native.advapi = Mock()
        with patch.object(windows, "_reparse", return_value=True):
            with self.assertRaisesRegex(OSError, "ACL target is a reparse point"):
                windows._secure_tree(native, Path("fresh-profile"), "owner", "package", False)
        native.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.assert_not_called()

    def test_windows_host_report_distinguishes_server_from_workstation_without_filtering(self) -> None:
        for product_type, host_class in ((1, "workstation"), (2, "domain_controller"), (3, "server"), (7, "other")):
            with self.subTest(product_type=product_type), patch.object(
                windows.sys, "getwindowsversion", create=True,
                return_value=SimpleNamespace(product_type=product_type),
            ):
                self.assertEqual({"product_type": product_type, "host_class": host_class}, windows._host_information())

    def test_windows_session_observation_queries_without_changing_child_token(self) -> None:
        api = SimpleNamespace(kernel=Mock(), advapi=Mock(), check=lambda value, operation: value)
        api.kernel.GetCurrentProcessId.return_value = 101

        def parent(pid, session):
            self.assertEqual(101, pid)
            session._obj.value = 0
            return 1

        def child(token, kind, value, size, length):
            self.assertEqual((123, 12, 4), (token, kind, size))
            value._obj.value = 0
            length._obj.value = 4
            return 1

        api.kernel.ProcessIdToSessionId.side_effect = parent
        api.advapi.GetTokenInformation.side_effect = child
        self.assertEqual({"parent": 0, "child": 0, "same": True}, windows._session_information(api, 123))
        api.advapi.SetTokenInformation.assert_not_called()

    def test_windows_station_classification_never_reports_the_object_name(self) -> None:
        for name, flags, expected in (("WinSta0", 1, "winsta0"), ("Service-user-secret$", 0, "service_or_other")):
            with self.subTest(name=name):
                user = Mock()
                api = SimpleNamespace(check=lambda value, operation: value)

                def information(handle, kind, buffer, size, length):
                    self.assertEqual(123, handle)
                    if kind == 2:
                        length._obj.value = (len(name) + 1) * ctypes.sizeof(ctypes.c_wchar)
                        if buffer is None:
                            return 0
                        self.assertGreaterEqual(size, length._obj.value)
                        buffer.value = name
                    else:
                        self.assertEqual(1, kind)
                        self.assertEqual(12, size)
                        buffer._obj.flags = flags
                        length._obj.value = 12
                    return 1

                user.GetUserObjectInformationW.side_effect = information
                result = windows._station_information(api, user, 123)
                self.assertEqual({"class": expected, "visible": bool(flags & 1)}, result)
                self.assertNotIn(name, json.dumps(result))

    def test_windows_integrity_token_sid_is_bounded_before_it_is_read(self) -> None:
        for outside in (False, True):
            with self.subTest(outside=outside):
                api = SimpleNamespace(advapi=Mock(), check=lambda value, operation: value)
                size = ctypes.sizeof(windows._SidAndAttributes) + 12

                def information(token, kind, buffer, capacity, length):
                    self.assertEqual((123, 25), (token, kind))
                    length._obj.value = size
                    if buffer is None:
                        return 0
                    sid = ctypes.addressof(buffer) + (capacity + 1 if outside else ctypes.sizeof(windows._SidAndAttributes))
                    entry = windows._SidAndAttributes(sid, 0x20)
                    ctypes.memmove(buffer, bytes(entry), ctypes.sizeof(entry))
                    if not outside:
                        ctypes.memmove(sid, b"\x01\x01\0\0\0\0\0\x10" + bytes(windows.DWORD(0x1000)), 12)
                    return 1

                api.advapi.GetTokenInformation.side_effect = information
                if outside:
                    with self.assertRaisesRegex(OSError, "integrity SID.*outside"):
                        windows._token_integrity(api, 123)
                else:
                    self.assertEqual({"rid": 0x1000, "level": "low"}, windows._token_integrity(api, 123))
                api.advapi.SetTokenInformation.assert_not_called()

    def test_windows_mic_query_requests_only_label_and_preserves_borrowed_handles(self) -> None:
        api = SimpleNamespace(advapi=Mock(), kernel=Mock(), close=Mock(), check=lambda value, operation: value)
        user = Mock()
        # Self-relative descriptor header + ACL header + one mandatory-label ACE.
        data = b"\x01\0\x10\x80" + b"\0" * 8 + bytes(windows.DWORD(20)) + b"\0" * 4
        data += b"\x02\0\x1c\0\x01\0\0\0"
        data += b"\x11\0\x14\0" + bytes(windows.DWORD(1))
        data += b"\x01\x01\0\0\0\0\0\x10" + bytes(windows.DWORD(0x2000))

        def descriptor(handle, information, buffer, capacity, length):
            self.assertEqual(123, handle)
            self.assertEqual(0x10, information._obj.value)
            length._obj.value = len(data)
            if buffer is None:
                return 0
            ctypes.memmove(buffer, data, len(data))
            return 1

        def sacl(buffer, present, output, defaulted):
            present._obj.value = 1
            output._obj.value = ctypes.addressof(buffer) + 20
            return 1

        def acl_information(pointer, output, size, kind):
            self.assertEqual((12, 2), (size, kind))
            output._obj.count, output._obj.used = 1, 28
            return 1

        api.advapi.GetSecurityDescriptorSacl.side_effect = sacl
        api.advapi.GetAclInformation.side_effect = acl_information
        api.advapi.GetAce.side_effect = lambda pointer, index, output: setattr(output._obj, "value", pointer.value + 8) or 1
        user.GetUserObjectSecurity.side_effect = descriptor
        self.assertEqual({"label_present": True, "rid": 0x2000, "level": "medium", "policy_mask": "0x00000001"},
                         windows._object_integrity(api, user, 123))
        api.close.assert_not_called()
        api.kernel.LocalFree.assert_not_called()
        api.advapi.SetSecurityInfo.assert_not_called()

    def test_windows_mic_inherit_only_and_absent_labels_do_not_invent_a_policy(self) -> None:
        self.assertEqual({"label_present": False, "level": "implicit_medium"},
                         windows._descriptor_integrity(SimpleNamespace(advapi=Mock()), ctypes.create_string_buffer(
                             b"\x01\0\0\x80" + b"\0" * 16), 20))
        for sid in (b"\x01\x02\0\0\0\0\0\x10" + b"\0" * 4,
                    b"\x01\x01\0\0\0\0\0\x05" + b"\0" * 4):
            with self.assertRaisesRegex(OSError, "invalid mandatory integrity SID"):
                windows._integrity_sid(sid)

    def test_windows_observation_failures_preserve_other_available_facts(self) -> None:
        def checked(value, operation):
            if not value:
                raise OSError(5, operation)
            return value

        api = SimpleNamespace(kernel=Mock(), advapi=Mock(), check=checked)
        api.kernel.ProcessIdToSessionId.side_effect = lambda pid, output: setattr(output._obj, "value", 0) or 1
        api.advapi.GetTokenInformation.return_value = 0
        self.assertEqual({"parent": 0, "child": {"unavailable": True, "error": 5},
                          "same": {"unavailable": True}}, windows._session_information(api, 123))
        user = Mock()

        def information(handle, kind, output, size, length):
            if kind == 2:
                length._obj.value = 4097
                return 0
            output._obj.flags = 1
            length._obj.value = 12
            return 1

        user.GetUserObjectInformationW.side_effect = information
        result = windows._station_information(api, user, 123)
        self.assertIs(result["class"]["unavailable"], True)
        self.assertIs(result["visible"], True)

    def test_windows_mic_rejects_out_of_bounds_sdk_pointers_and_ignores_inherit_only(self) -> None:
        api = SimpleNamespace(advapi=Mock(), check=lambda value, operation: value)
        data = b"\x01\0\x10\x80" + b"\0" * 8 + bytes(windows.DWORD(20)) + b"\0" * 4
        data += b"\x02\0\x1c\0\x01\0\0\0"
        data += b"\x11\x08\x14\0" + bytes(windows.DWORD(1))
        data += b"\x01\x01\0\0\0\0\0\x10" + bytes(windows.DWORD(0x2000))
        buffer = ctypes.create_string_buffer(data)

        def sacl(descriptor, present, pointer, defaulted):
            present._obj.value = 1
            pointer._obj.value = ctypes.addressof(descriptor) + 20
            return 1

        def information(pointer, output, size, kind):
            output._obj.count, output._obj.used = 1, 28
            return 1

        api.advapi.GetSecurityDescriptorSacl.side_effect = sacl
        api.advapi.GetAclInformation.side_effect = information
        api.advapi.GetAce.side_effect = lambda pointer, index, output: setattr(output._obj, "value", pointer.value + 8) or 1
        self.assertEqual({"label_present": False, "level": "implicit_medium"},
                         windows._descriptor_integrity(api, buffer, len(data)))
        api.advapi.GetAce.side_effect = lambda pointer, index, output: setattr(output._obj, "value", ctypes.addressof(buffer) + len(data)) or 1
        with self.assertRaisesRegex(OSError, "label ACE is outside"):
            windows._descriptor_integrity(api, buffer, len(data))
        api.advapi.GetSecurityDescriptorSacl.side_effect = lambda descriptor, present, pointer, defaulted: setattr(present._obj, "value", 1) or setattr(pointer._obj, "value", ctypes.addressof(descriptor) + len(data)) or 1
        with self.assertRaisesRegex(OSError, "label ACL is outside"):
            windows._descriptor_integrity(api, buffer, len(data))

    def test_windows_console_diagnostic_changes_only_no_window_to_detached_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "fresh-profile"
            profile.mkdir()
            for experiment, loader, console_flag in ((None, False, 0x8), (None, True, 0x8),
                                                     (False, False, 0x08000000), (True, False, 0x8),
                                                     (False, True, 0x08000000), (True, True, 0x8)):
                with self.subTest(experiment=experiment, loader=loader):
                    api = Mock()
                    api.check = lambda value, operation: value
                    api.owner_sid.return_value = "owner"
                    api.sid_text.return_value = "package"
                    api.userenv.CreateAppContainerProfile.side_effect = lambda *args: setattr(args[-1]._obj, "value", 77) or 0
                    api.userenv.GetAppContainerFolderPath.side_effect = lambda sid, output: setattr(output._obj, "value", str(profile)) or 0
                    api.userenv.DeleteAppContainerProfile.return_value = 0
                    api.kernel.CreateFileW.return_value = 99
                    inherited, attributes, count = [], set(), [100]

                    def pipe(reader, writer, security, size):
                        count[0] += 2
                        reader._obj.value, writer._obj.value = count[0] - 1, count[0]
                        return 1

                    def initialize(pointer, amount, flags, length):
                        self.assertEqual(4, amount)
                        length._obj.value = 128
                        return 1

                    def attribute(pointer, flags, kind, value, size, old, length):
                        attributes.add(kind)
                        if kind == 0x20009:
                            self.assertEqual((77, None, 0, 0),
                                             (value._obj.sid, value._obj.capabilities, value._obj.count, value._obj.reserved))
                        elif kind == 0x20002:
                            inherited.extend(value._obj)
                        else:
                            self.assertEqual(1, value._obj.value)
                        return 1

                    def create(executable, command, process_security, thread_security, inherit, flags, environment, cwd, startup, process):
                        self.assertEqual({0x20009, 0x2000F, 0x2000E, 0x20002}, attributes)
                        self.assertEqual(0x80000 | 0x400 | 0x4 | console_flag | (0x2 if loader else 0), flags)
                        self.assertFalse(flags & 0x10)  # CREATE_NEW_CONSOLE
                        self.assertEqual([99, 102, 104], inherited)
                        self.assertEqual((99, 102, 104), (startup._obj.startup.stdin, startup._obj.startup.stdout, startup._obj.startup.stderr))
                        self.assertEqual(0x100, startup._obj.startup.flags)
                        self.assertTrue(inherit)
                        raise RuntimeError("stop before native console startup")

                    api.kernel.CreatePipe.side_effect = pipe
                    api.kernel.InitializeProcThreadAttributeList.side_effect = initialize
                    api.kernel.UpdateProcThreadAttribute.side_effect = attribute
                    api.kernel.CreateProcessW.side_effect = create
                    with patch.object(windows, "capability", return_value={"supported": True}), \
                         patch.object(windows, "_Api", return_value=api), \
                         patch("ctypes.WinDLL", create=True), \
                         patch.object(windows, "_secure_tree") as secure, \
                         patch.object(windows, "_private_runtime", return_value=root / "runtime" / "python.exe"):
                        with self.assertRaisesRegex(RuntimeError, "stop before native console startup"):
                            command = list(windows._STARTUP_COMMAND) if loader or experiment is not None else ["python.exe", "provider.py"]
                            windows._run_lpac(command, root / "bundle", root / "work", {}, 1, 4096,
                                              diagnostics={}, _console_diagnostic=experiment, _loader_diagnostic=loader)
                    self.assertEqual((api, profile, "owner", None, False), secure.call_args_list[0].args)
                    api.kernel.DeleteProcThreadAttributeList.assert_called_once()
                    api.userenv.DeleteAppContainerProfile.assert_called_once()

    def test_windows_console_diagnostic_refuses_untrusted_commands_and_has_two_fresh_cases(self) -> None:
        for command, observer, alternative in ((["provider.exe"], {}, True),
                                                (["provider.exe"], {}, False),
                                                (windows._STARTUP_COMMAND, None, True),
                                                (windows._STARTUP_COMMAND, None, False),
                                                (windows._STARTUP_COMMAND + ["external-input"], {}, True),
                                                (windows._STARTUP_COMMAND, {}, "registry_only")):
            with patch.object(windows, "_Api") as api:
                with self.assertRaisesRegex(OSError, "fixed startup diagnostic"):
                    windows._run_lpac(command, Path("bundle"), Path("work"), {}, 1, 4096,
                                      diagnostics=observer, _console_diagnostic=alternative)
            api.assert_not_called()
        modes, roots = [], []

        def launch(command, bundle, work, environment, timeout, output_limit, **options):
            self.assertEqual(windows._STARTUP_COMMAND, command)
            self.assertEqual((10, 4096), (timeout, output_limit))
            modes.append(options["_console_diagnostic"])
            roots.append(str(work.parent))
            return (0, b"EA_LPAC_STARTUP_OK", b"") if options["_console_diagnostic"] else (0xC0000142, b"", b"")

        with patch.object(windows, "capability", return_value={"supported": True, "backend": "windows-lpac"}), \
             patch.object(windows, "_Api"), \
             patch.object(windows, "_private_runtime", return_value=Path("python.exe")), \
             patch.object(windows.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"EA_LPAC_STARTUP_OK")), \
             patch.object(windows, "_run_lpac", side_effect=launch):
            result = windows.diagnose_console()
        self.assertEqual([False, True], modes)
        self.assertEqual(2, len(set(roots)))
        self.assertIs(result["qualified"], False)
        self.assertIs(result["strict_lpac"]["marker"], False)
        self.assertIs(result["detached_console"]["marker"], True)

    def test_windows_loader_diagnostic_rejects_provider_commands_before_winapi(self) -> None:
        for command, observer, loader in ((["provider.exe"], {}, True),
                                         (windows._STARTUP_COMMAND, None, True),
                                         (windows._STARTUP_COMMAND + ["external-input"], {}, True),
                                         (windows._STARTUP_COMMAND, {}, "DEBUG_PROCESS")):
            with patch.object(windows, "_Api") as api:
                with self.assertRaisesRegex(OSError, "fixed startup diagnostic"):
                    windows._run_lpac(command, Path("bundle"), Path("work"), {}, 1, 4096,
                                      diagnostics=observer, _loader_diagnostic=loader)
            api.assert_not_called()

    def test_windows_debug_event_matches_x64_sdk_layout(self) -> None:
        self.assertEqual(8, ctypes.sizeof(windows.HANDLE))
        self.assertEqual(152, ctypes.sizeof(windows._ExceptionRecord))
        self.assertEqual(32, windows._ExceptionRecord.parameters.offset)
        self.assertEqual(160, ctypes.sizeof(windows._ExceptionDebugInfo))
        self.assertEqual(152, windows._ExceptionDebugInfo.first_chance.offset)
        self.assertEqual(72, ctypes.sizeof(windows._CreateProcessDebugInfo))
        self.assertEqual(40, ctypes.sizeof(windows._LoadDllDebugInfo))
        self.assertEqual(16, windows._DebugEvent.data.offset)
        self.assertEqual(176, ctypes.sizeof(windows._DebugEvent))

    def test_windows_loader_continues_exceptions_and_releases_only_owned_image_handles(self) -> None:
        events = []
        created = windows._DebugEvent(3, 51, 61)
        created.data.create_process.file = 101
        created.data.create_process.process = 201
        created.data.create_process.thread = 202
        events.append(created)
        dll = windows._DebugEvent(6, 51, 61)
        dll.data.dll.file = 102
        dll.data.dll.base = 0x123456789
        dll.data.dll.image_name = 0xABCDEF
        events.append(dll)
        for code, first in ((0x80000003, 1), (0xC0000022, 1), (0xC0000022, 0)):
            event = windows._DebugEvent(1, 51, 61)
            event.data.exception.record.code = code
            event.data.exception.record.address = 0xDEADBEEF
            event.data.exception.first_chance = first
            events.append(event)
        events.append(windows._DebugEvent(8, 51, 61))  # Invalid SDK metadata must not cause a read.
        exit_event = windows._DebugEvent(5, 51, 61)
        exit_event.data.exit_process = 0xC0000022
        events.append(exit_event)
        api = Mock()
        api.check = lambda result, operation: self.assertTrue(result)

        def wait(output, milliseconds):
            self.assertLessEqual(milliseconds, 50)
            event = events.pop(0)
            ctypes.memmove(output, ctypes.byref(event), ctypes.sizeof(event))
            return 1

        def image_name(handle, output, capacity, flags):
            self.assertEqual((102, 1024, 0xC), (handle, capacity, flags))
            output.value = r"\Users\secret-account\private-runtime\python313.dll"
            return len(output.value)

        api.kernel.WaitForDebugEventEx.side_effect = wait
        api.kernel.GetFinalPathNameByHandleW.side_effect = image_name
        api.kernel.DuplicateHandle.side_effect = lambda current, source, target, output, access, inherit, options: setattr(
            output._obj, "value", 901) or 1
        process = windows._ProcessInfo(201, 202, 51, 61)
        handles = [201, 202, 301]
        report = []
        trace = windows._LoaderTrace(api, 51, report, process, handles)
        trace.retain_process()
        while events:
            trace.poll(0)
        self.assertTrue(trace.exited)
        self.assertEqual(901, process.process)
        self.assertEqual([301, 901], handles)
        self.assertEqual([101, 102], [call.args[0] for call in api.close.call_args_list])
        self.assertEqual([0x10002, 0x10002, 0x10002, 0x80010001,
                          0x80010001, 0x10002, 0x10002],
                         [call.args[2] for call in api.kernel.ContinueDebugEvent.call_args_list])
        self.assertEqual({"event": "dll_loaded", "module": "python313.dll"}, report[1])
        self.assertEqual({"event": "exception", "status": "0xC0000022", "first_chance": True}, report[3])
        self.assertEqual({"event": "process_exited", "status": "0xC0000022"}, report[-1])
        for value in ("secret-account", "Users", "123456789", "DEADBEEF", "ABCDEF"):
            self.assertNotIn(value, json.dumps(report))
        api.kernel.ReadProcessMemory.assert_not_called()

    def test_windows_loader_bound_continues_the_overflow_event_without_retaining_it(self) -> None:
        api = Mock()
        api.check = lambda result, operation: self.assertTrue(result)
        event = windows._DebugEvent(7, 51, 61)
        api.kernel.WaitForDebugEventEx.side_effect = lambda output, timeout: ctypes.memmove(
            output, ctypes.byref(event), ctypes.sizeof(event)) or 1
        report = []
        trace = windows._LoaderTrace(api, 51, report)
        for _ in range(128):
            trace.poll(0)
        with self.assertRaisesRegex(OSError, "event limit"):
            trace.poll(0)
        self.assertEqual(128, len(report))
        self.assertEqual(129, api.kernel.ContinueDebugEvent.call_count)
        self.assertIsNone(trace.pending)

    def test_windows_loader_cleanup_continues_pending_event_then_terminates_and_drains_exit(self) -> None:
        api = Mock()
        operations = []
        failed = [False]

        def checked(result, operation):
            if not result:
                raise OSError(5, operation)
            return result

        def continued(pid, tid, status):
            operations.append("continue")
            if not failed[0]:
                failed[0] = True
                return 0
            return 1

        api.check = checked
        api.kernel.ContinueDebugEvent.side_effect = continued
        api.kernel.TerminateJobObject.side_effect = lambda *args: operations.append("terminate-job") or 1
        api.kernel.TerminateProcess.side_effect = lambda *args: operations.append("terminate-process") or 1
        api.kernel.WaitForSingleObject.side_effect = lambda *args: operations.append("wait-exit") or 0
        event = windows._DebugEvent(1, 51, 61)
        event.data.exception.record.code = 0xC0000022
        event.data.exception.first_chance = 1
        exit_event = windows._DebugEvent(5, 51, 61)
        exit_event.data.exit_process = 1
        events = [event, exit_event]

        def waited(output, timeout):
            operations.append("debug-wait")
            event = events.pop(0)
            ctypes.memmove(output, ctypes.byref(event), ctypes.sizeof(event))
            return 1

        api.kernel.WaitForDebugEventEx.side_effect = waited
        trace = windows._LoaderTrace(api, 51, [])
        with self.assertRaises(OSError):
            trace.poll(0)
        self.assertIsNotNone(trace.pending)
        trace.terminate(401, 501, True)
        self.assertEqual(["debug-wait", "continue", "continue", "terminate-job", "terminate-process",
                          "debug-wait", "continue", "wait-exit"], operations)
        self.assertTrue(trace.exited)
        self.assertIsNone(trace.pending)

    def test_windows_loader_reports_missing_or_oversized_module_as_unavailable(self) -> None:
        api = Mock()
        for size in (0, 1024, 4096):
            with self.subTest(size=size):
                api.kernel.GetFinalPathNameByHandleW.return_value = size
                self.assertEqual("unavailable", windows._debug_module(api, 102))
        self.assertEqual("unavailable", windows._debug_module(api, None))

    def test_windows_loader_timeout_is_distinct_from_a_debug_api_failure(self) -> None:
        api = Mock()

        def checked(value, operation):
            if not value:
                raise OSError(5, operation)
            return value

        api.check = checked
        api.kernel.WaitForDebugEventEx.return_value = 0
        trace = windows._LoaderTrace(api, 51, [])
        with patch("ctypes.get_last_error", create=True, return_value=121):
            trace.poll(50)
        with patch("ctypes.get_last_error", create=True, return_value=5):
            with self.assertRaises(OSError):
                trace.poll(50)
        self.assertIsNone(trace.pending)
        api.kernel.ContinueDebugEvent.assert_not_called()

    def test_windows_loader_retention_failure_drains_exit_without_waiting_or_closing_borrowed_handles(self) -> None:
        api = Mock()

        def checked(value, operation):
            if not value:
                raise OSError(5, operation)
            return value

        api.check = checked
        api.kernel.DuplicateHandle.return_value = 0
        created = windows._DebugEvent(3, 51, 61)
        created.data.create_process.file = 101
        created.data.create_process.process, created.data.create_process.thread = 201, 202
        exited = windows._DebugEvent(5, 51, 61)
        exited.data.exit_process = 1
        events = [created, exited]
        api.kernel.WaitForDebugEventEx.side_effect = lambda output, timeout: ctypes.memmove(
            output, ctypes.byref(events.pop(0)), ctypes.sizeof(windows._DebugEvent)) or 1
        handles = [201, 202]
        trace = windows._LoaderTrace(api, 51, [], windows._ProcessInfo(201, 202, 51, 61), handles)
        with self.assertRaises(OSError):
            trace.retain_process()
        with self.assertRaisesRegex(OSError, "no retained handle to confirm exit"):
            trace.terminate(201, 501, False)
        self.assertTrue(trace.exited)
        self.assertEqual([], handles)
        self.assertEqual([101], [call.args[0] for call in api.close.call_args_list])
        api.kernel.TerminateProcess.assert_called_once_with(201, 1)
        api.kernel.TerminateJobObject.assert_not_called()
        api.kernel.WaitForSingleObject.assert_not_called()

    def test_windows_loader_cleanup_checks_detach_and_still_requires_confirmed_exit(self) -> None:
        for detach, wait in ((1, 0), (0, 0), (1, 258)):
            with self.subTest(detach=detach, wait=wait):
                api = Mock()

                def checked(value, operation):
                    if not value:
                        raise OSError(5, operation)
                    return value

                api.check = checked
                api.kernel.DebugActiveProcessStop.return_value = detach
                api.kernel.WaitForSingleObject.return_value = wait
                trace = windows._LoaderTrace(api, 51, [])
                with patch.object(windows.time, "monotonic", side_effect=[0, 4]):
                    if detach and wait == 0:
                        trace.terminate(401, None, False)
                    else:
                        with self.assertRaises(OSError):
                            trace.terminate(401, None, False)
                api.kernel.DebugActiveProcessStop.assert_called_once_with(51)
                self.assertEqual(2 if detach else 1, api.kernel.TerminateProcess.call_count)
                if detach:
                    api.kernel.WaitForSingleObject.assert_called_once_with(401, 2000)
                else:
                    api.kernel.WaitForSingleObject.assert_not_called()

    def test_windows_loader_diagnostic_keeps_two_fixed_console_cases_and_never_qualifies(self) -> None:
        options, roots = [], []

        def launch(command, bundle, work, environment, timeout, output_limit, **keywords):
            self.assertEqual(windows._STARTUP_COMMAND, command)
            self.assertEqual((10, 4096), (timeout, output_limit))
            options.append((keywords["_console_diagnostic"], keywords["_loader_diagnostic"]))
            roots.append(str(work.parent))
            return (0, b"EA_LPAC_STARTUP_OK", b"")

        with patch.object(windows, "capability", return_value={"supported": True}), \
             patch.object(windows, "_Api"), \
             patch.object(windows, "_private_runtime", return_value=Path("python.exe")), \
             patch.object(windows.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"EA_LPAC_STARTUP_OK")), \
             patch.object(windows, "_run_lpac", side_effect=launch):
            report = windows.diagnose_console(_loader_diagnostic=True)
        self.assertEqual([(False, True), (True, True)], options)
        self.assertEqual(2, len(set(roots)))
        self.assertIs(report["qualified"], False)
        self.assertIs(report["debug_observer"], True)
        self.assertIs(report["strict_lpac"]["marker"], True)

    def test_windows_loader_debug_message_reads_sdk_byte_length_and_reports_only_fixed_fields(self) -> None:
        for unicode, encoding in ((0, "ascii"), (1, "utf-16-le")):
            with self.subTest(unicode=unicode):
                api = Mock()
                payload = "Module: python313.dll, Status: 0xC0000022\0".encode(encoding)

                def read(process, address, buffer, size, consumed):
                    self.assertEqual((901, 0x1000, len(payload)), (process, address, size))
                    ctypes.memmove(buffer, payload, len(payload))
                    consumed._obj.value = len(payload)
                    return 1

                api.kernel.ReadProcessMemory.side_effect = read
                trace = windows._LoaderTrace(api, 51, [])
                trace.owned_process = 901
                result = trace.debug_message(windows._DebugStringInfo(0x1000, unicode, len(payload)))
                self.assertEqual({"event": "debug_string", "result": "recognized",
                                  "module": "python313.dll", "status": "0xC0000022"}, result)
                self.assertEqual(len(payload), trace.debug_bytes)

    def test_windows_loader_debug_message_rejects_sensitive_unknown_and_unrelated_text(self) -> None:
        samples = (
            "Token=secret-value user@example.org C:\\Users\\secret-account\\unknown.dll Status: 0xC0000022",
            "Module: python313.dll loaded. Status: 0xC0000022 from unrelated-operation",
            "Module: unknown-secret.dll Status: 0xC0000022",
            "Activation context succeeded. Status: 0xC0000022",
            "Process exited with 0xC0000022",
        )
        for sample in samples:
            with self.subTest(sample_index=samples.index(sample)):
                api = Mock()
                payload = (sample + "\0").encode("ascii")
                def read(process, address, buffer, size, consumed):
                    ctypes.memmove(buffer, payload, len(payload))
                    consumed._obj.value = len(payload)
                    return 1
                api.kernel.ReadProcessMemory.side_effect = read
                trace = windows._LoaderTrace(api, 51, [])
                trace.owned_process = 901
                self.assertEqual({"event": "debug_string", "result": "unrecognized"},
                                 trace.debug_message(windows._DebugStringInfo(0x1000, 0, len(payload))))

    def test_windows_loader_debug_message_classifies_only_explicit_same_grammar_phase_and_status(self) -> None:
        for phrase, kind in (("Activation context creation failed, Status: 0xC0000022", "activation_context"),
                             ("DLL initialization failed with NTStatus = 0xC0000142", "dll_initialization"),
                             ("Console initialization failed, Status 0xC0000022", "console_initialization")):
            api = Mock()
            payload = (phrase + "\0").encode("ascii")
            def read(process, address, buffer, size, consumed):
                ctypes.memmove(buffer, payload, len(payload))
                consumed._obj.value = len(payload)
                return 1
            api.kernel.ReadProcessMemory.side_effect = read
            trace = windows._LoaderTrace(api, 51, [])
            trace.owned_process = 901
            result = trace.debug_message(windows._DebugStringInfo(0x1000, 0, len(payload)))
            self.assertEqual(kind, result["kind"])
            self.assertEqual(phrase[-10:].upper().replace("0X", "0x"), result["status"])
            self.assertEqual({"event", "result", "kind", "status"}, set(result))

    def test_windows_loader_debug_message_rejects_invalid_metadata_without_reading(self) -> None:
        metadata = ((0, 0, 1), (0x1000, 0, 0), (0x1000, 0, 4097),
                    (0x1000, 2, 100), (0x1000, 1, 3), ((1 << 64) - 2, 0, 4))
        for pointer, unicode, length in metadata:
            api = Mock()
            trace = windows._LoaderTrace(api, 51, [])
            trace.owned_process = 901
            result = trace.debug_message(windows._DebugStringInfo(pointer, unicode, length))
            self.assertEqual("unavailable", result["result"])
            api.kernel.ReadProcessMemory.assert_not_called()
            self.assertEqual(0, trace.debug_bytes)

    def test_windows_loader_debug_message_reserves_attempted_budget_and_rejects_partial_or_invalid_payload(self) -> None:
        api = Mock()
        api.kernel.ReadProcessMemory.return_value = 0
        trace = windows._LoaderTrace(api, 51, [])
        trace.owned_process = 901
        for _ in range(4):
            self.assertEqual("unavailable", trace.debug_message(windows._DebugStringInfo(0x1000, 0, 4096))["result"])
        self.assertEqual(16384, trace.debug_bytes)
        self.assertEqual("budget_exhausted", trace.debug_message(windows._DebugStringInfo(0x1000, 0, 1))["reason"])
        self.assertEqual(4, api.kernel.ReadProcessMemory.call_count)
        for payload, count, unicode in ((b"Status: 0xC0000022\0", 4, 0),
                                        (b"Module: python313.dll Status: 0xC0000022", None, 0),
                                        (b"\xff\0", None, 0), (b"\x00\xd8\x00\x00", None, 1)):
            api = Mock()
            def read(process, address, buffer, size, consumed):
                ctypes.memmove(buffer, payload, len(payload))
                consumed._obj.value = len(payload) if count is None else count
                return 1
            api.kernel.ReadProcessMemory.side_effect = read
            trace = windows._LoaderTrace(api, 51, [])
            trace.owned_process = 901
            self.assertEqual("unavailable", trace.debug_message(windows._DebugStringInfo(0x1000, unicode, len(payload)))["result"])

    def test_windows_loader_debug_message_read_continues_on_failure_and_never_repeats_during_cleanup(self) -> None:
        api = Mock()
        payload = b"Module: python313.dll, Status: 0xC0000022\0"
        buffers = []

        def read(process, address, buffer, size, consumed):
            buffers.append(buffer)
            ctypes.memmove(buffer, payload, len(payload))
            consumed._obj.value = len(payload)
            return 1

        def checked(value, operation):
            if not value:
                raise OSError(5, operation)
            return value

        api.check = checked
        api.kernel.ReadProcessMemory.side_effect = read
        api.kernel.ContinueDebugEvent.side_effect = [0, 1, 1, 1]
        api.kernel.WaitForSingleObject.return_value = 0
        debug = windows._DebugEvent(8, 51, 61)
        debug.data.debug_string = windows._DebugStringInfo(0x1000, 0, len(payload))
        exited = windows._DebugEvent(5, 51, 61)
        exited.data.exit_process = 1
        events = [debug, debug, exited]
        api.kernel.WaitForDebugEventEx.side_effect = lambda output, timeout: ctypes.memmove(
            output, ctypes.byref(events.pop(0)), ctypes.sizeof(windows._DebugEvent)) or 1
        report = []
        trace = windows._LoaderTrace(api, 51, report)
        trace.owned_process = 901
        with self.assertRaises(OSError):
            trace.poll(0)
        self.assertIsNotNone(trace.pending)
        trace.terminate(901, None, False)
        self.assertTrue(trace.exited)
        self.assertIsNone(trace.pending)
        self.assertEqual(1, api.kernel.ReadProcessMemory.call_count)
        self.assertEqual(1, len(report))
        self.assertEqual(b"\0" * len(payload), buffers[0].raw)

    def test_windows_loader_error_grammar_reveals_only_known_dll_basename_and_same_message_status(self) -> None:
        for module in ("advapi32.dll", "shell32.dll", "ole32.dll", "oleaut32.dll"):
            api = Mock()
            payload = (f'LDR: ERROR: Unable to load DLL: "C:\\Users\\secret-account\\{module}", '
                       'Parent Module: "C:\\private\\python313.dll", Status: 0xc0000022\0').encode("ascii")
            def read(process, address, buffer, size, consumed):
                ctypes.memmove(buffer, payload, len(payload))
                consumed._obj.value = len(payload)
                return 1
            api.kernel.ReadProcessMemory.side_effect = read
            trace = windows._LoaderTrace(api, 51, [])
            trace.owned_process = 901
            result = trace.debug_message(windows._DebugStringInfo(0x1000, 0, len(payload)))
            self.assertEqual({"event": "debug_string", "result": "recognized", "module": module,
                              "status": "0xC0000022"}, result)
            self.assertNotIn("secret-account", json.dumps(result))
            self.assertNotIn("python313.dll", json.dumps(result))
        for message in ('Failed to load DLL: "unknown-secret.dll", Parent Module: "python313.dll", Status: 0xc0000022',
                        'Failed to load DLL: "ole32.dll". Unrelated Status: 0xc0000022'):
            api = Mock()
            payload = (message + "\0").encode("ascii")
            api.kernel.ReadProcessMemory.side_effect = read
            trace = windows._LoaderTrace(api, 51, [])
            trace.owned_process = 901
            self.assertEqual({"event": "debug_string", "result": "unrecognized"},
                             trace.debug_message(windows._DebugStringInfo(0x1000, 0, len(payload))))

    def test_windows_loader_read_exception_erases_buffer_and_still_continues_the_pending_event(self) -> None:
        api = Mock()
        api.check = lambda value, operation: self.assertTrue(value)
        payload = b"user@example.org secret-token secret-path\0"
        buffers = []
        def read(process, address, buffer, size, consumed):
            buffers.append(buffer)
            ctypes.memmove(buffer, payload, len(payload))
            raise OSError(5, "simulated SDK failure")
        api.kernel.ReadProcessMemory.side_effect = read
        event = windows._DebugEvent(8, 51, 61)
        event.data.debug_string = windows._DebugStringInfo(0x1000, 0, len(payload))
        api.kernel.WaitForDebugEventEx.side_effect = lambda output, timeout: ctypes.memmove(
            output, ctypes.byref(event), ctypes.sizeof(event)) or 1
        report = []
        trace = windows._LoaderTrace(api, 51, report)
        trace.owned_process = 901
        with self.assertRaises(OSError):
            trace.poll(0)
        self.assertEqual(b"\0" * len(payload), buffers[0].raw)
        api.kernel.ContinueDebugEvent.assert_called_once_with(51, 61, 0x10002)
        self.assertIsNone(trace.pending)
        self.assertEqual([], report)


if __name__ == "__main__":
    unittest.main()
