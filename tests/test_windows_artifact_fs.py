from __future__ import annotations

import ast
import ctypes
import inspect
import os
import struct
import sys
import tempfile
import textwrap
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.runtime.artifact_io import ArtifactConflict, ArtifactIO, artifact_fs
from engineering_assistant.runtime.validation import ValidationFailure
from engineering_assistant.platforms.windows_artifact_fs import (
    _NameInformation,
    _decode_directory_names,
    _name_information,
    _validate_child_name,
    WindowsFilesystem,
)


def _file_security_identity(filesystem, handle):
    security, owner, dacl = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    try:
        error = filesystem._advapi.GetSecurityInfo(handle, 1, 5, ctypes.byref(owner),
            None, ctypes.byref(dacl), None, ctypes.byref(security))
        if error:
            raise ctypes.WinError(error)
        get_control = filesystem._advapi.GetSecurityDescriptorControl
        get_control.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint16),
                               ctypes.POINTER(ctypes.c_uint32)]
        get_control.restype = ctypes.c_int
        control, revision = ctypes.c_uint16(), ctypes.c_uint32()
        if not get_control(security, ctypes.byref(control), ctypes.byref(revision)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not dacl.value or not filesystem._advapi.IsValidAcl(dacl):
            raise AssertionError("created file has no valid DACL")
        _, _, _, count, _ = struct.unpack("<BBHHH", ctypes.string_at(dacl, 8))
        allowed = {}
        for index in range(count):
            ace = ctypes.c_void_p()
            if not filesystem._advapi.GetAce(dacl, index, ctypes.byref(ace)):
                raise ctypes.WinError(ctypes.get_last_error())
            kind, _, _, mask = struct.unpack("<BBHI", ctypes.string_at(ace, 8))
            if kind != 0:
                raise AssertionError("created file has an unexpected non-allow ACE")
            # Binary SID conversion always returns S-...; SDDL can use LA/SY.
            trustee = filesystem._sid_text(ctypes.c_void_p(ace.value + 8))
            allowed[trustee] = allowed.get(trustee, 0) | mask
        return filesystem._sid_text(owner), control.value, allowed
    finally:
        if security.value:
            filesystem._kernel.LocalFree(security)


class WindowsProtocolTests(unittest.TestCase):
    def test_launcher_dacl_fixture_restores_inheritance_through_retained_handle(self) -> None:
        from test_native_launcher import NativeLauncherTests

        for control in (0, 0x1000):
            with self.subTest(protected=bool(control)):
                def get_security(_handle, _kind, flags, _owner, _group, dacl, _sacl, security):
                    self.assertEqual(4, flags)
                    dacl._obj.value, security._obj.value = 101, 102
                    return 0

                def get_control(_security, output, revision):
                    output._obj.value, revision._obj.value = control, 1
                    return 1

                def constructed_dacl(_security, present, dacl, _defaulted):
                    present._obj.value, dacl._obj.value = 1, 201
                    return 1

                filesystem = SimpleNamespace(O_DIRECTORY=0, open=Mock(return_value=8),
                    close=Mock(), _reopen_handle=Mock(return_value=99), _user_sid="current-user",
                    _security_descriptor=Mock(return_value=202), fchmod=Mock(),
                    _advapi=SimpleNamespace(GetSecurityInfo=Mock(side_effect=get_security),
                        GetSecurityDescriptorControl=Mock(side_effect=get_control),
                        GetSecurityDescriptorDacl=Mock(side_effect=constructed_dacl),
                        SetSecurityInfo=Mock(return_value=0)),
                    _kernel=SimpleNamespace(LocalFree=Mock(), CloseHandle=Mock()))
                with patch("engineering_assistant.runtime.artifact_io.artifact_fs", filesystem):
                    with self.assertRaisesRegex(RuntimeError, "probe failed"):
                        with NativeLauncherTests._windows_dacl(Path("."), broad=True):
                            raise RuntimeError("probe failed")
                calls = filesystem._advapi.SetSecurityInfo.call_args_list
                self.assertEqual(2, len(calls))
                self.assertEqual((99, 1, 0x80000004), calls[0].args[:3])
                self.assertEqual((99, 1, 4 | (0x80000000 if control else 0x20000000)),
                                 calls[1].args[:3])
                self.assertEqual(101, calls[1].args[5].value)
                filesystem.open.assert_called_once()
                filesystem._reopen_handle.assert_called_once_with(8, 0x60080)
                filesystem.fchmod.assert_not_called()
                filesystem._kernel.CloseHandle.assert_called_once_with(99)
                filesystem.close.assert_called_once_with(8)

    def test_chmod_acl_fixture_compares_binary_canonical_sid(self) -> None:
        user_sid = "S-1-5-21-100-200-300-500"  # SDDL can render this administrator as LA.
        user = bytes((1, 5, 0, 0, 0, 0, 0, 5)) + struct.pack("<5I", 21, 100, 200, 300, 500)
        system = bytes((1, 1, 0, 0, 0, 0, 0, 5)) + struct.pack("<I", 18)
        entries = [struct.pack("<BBHI", 0, 0, 8 + len(sid), mask) + sid
                   for sid, mask in ((user, 0x1E0089), (system, 0x1F01FF))]
        acl = ctypes.create_string_buffer(struct.pack("<BBHHH", 2, 0, 8 + sum(map(len, entries)), 2, 0)
                                         + b"".join(entries))
        owner = ctypes.create_string_buffer(user)

        def get_security(_handle, _kind, flags, owner_out, _group, dacl, _sacl, security):
            self.assertEqual(5, flags)
            owner_out._obj.value, dacl._obj.value = ctypes.addressof(owner), ctypes.addressof(acl)
            security._obj.value = 102
            return 0

        def get_control(_security, output, revision):
            output._obj.value, revision._obj.value = 0x1000, 1
            return 1

        def get_ace(_acl, index, output):
            output._obj.value = ctypes.addressof(acl) + 8 + sum(map(len, entries[:index]))
            return 1

        def sid_text(sid):
            size = 8 + 4 * ctypes.string_at(sid, 8)[1]
            value = ctypes.string_at(sid, size)
            return {user: user_sid, system: "S-1-5-18"}[value]

        filesystem = SimpleNamespace(_sid_text=Mock(side_effect=sid_text),
            _advapi=SimpleNamespace(GetSecurityInfo=Mock(side_effect=get_security),
                GetSecurityDescriptorControl=Mock(side_effect=get_control),
                GetAce=Mock(side_effect=get_ace), IsValidAcl=Mock(return_value=1),
                ConvertSecurityDescriptorToStringSecurityDescriptorW=Mock(
                    side_effect=AssertionError("SDDL aliases are not identities"))),
            _kernel=SimpleNamespace(LocalFree=Mock()))
        identity, control, allowed = _file_security_identity(filesystem, 99)
        self.assertEqual(user_sid, identity)
        self.assertTrue(control & 0x1000)
        self.assertEqual({user_sid: 0x1E0089, "S-1-5-18": 0x1F01FF}, allowed)
        self.assertEqual(3, filesystem._sid_text.call_count)
        filesystem._advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.assert_not_called()

    def test_launcher_acl_fixture_uses_bound_reopen_with_security_access(self) -> None:
        tree = ast.parse((ROOT / "tests/test_native_launcher.py").read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == "_windows_dacl")
        calls = [node for node in ast.walk(method)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        self.assertFalse(any(node.func.attr == "ReOpenFile" for node in calls))
        reopened = [node for node in calls if node.func.attr == "_reopen_handle"]
        self.assertEqual(1, len(reopened))
        self.assertEqual("descriptor", reopened[0].args[0].id)
        self.assertEqual(0x60080, reopened[0].args[1].value)

    def test_native_acl_fixture_reopens_through_the_bound_identity_api(self) -> None:
        source = inspect.getsource(
            WindowsArtifactIntegrationTests.test_created_file_and_chmod_preserve_private_owner_dacl
        )
        calls = [node for node in ast.walk(ast.parse(textwrap.dedent(source)))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        self.assertFalse(any(node.func.attr == "ReOpenFile" for node in calls))
        reopened = [node for node in calls if node.func.attr == "_reopen_handle"]
        self.assertEqual(1, len(reopened), "DACL integration must use the bound NTFS identity reopening API")
        self.assertEqual("descriptor", reopened[0].args[0].id)
        self.assertEqual(0x20080, reopened[0].args[1].value)

    def test_scalar_file_information_passes_its_address_to_native_api(self) -> None:
        filesystem = object.__new__(WindowsFilesystem)
        filesystem._handle = Mock(return_value=123)
        observed = []
        signature = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32)

        def set_information(_handle, _status, buffer, size, information_class):
            observed.append((ctypes.string_at(buffer, size), information_class))
            return 0

        filesystem._nt = SimpleNamespace(NtSetInformationFile=signature(set_information))
        filesystem._set_information(8, ctypes.c_uint32(3), 64)
        self.assertEqual([(struct.pack("<I", 3), 64)], observed)

    def test_directory_reopen_uses_retained_ntfs_id_instead_of_path(self) -> None:
        filesystem = object.__new__(WindowsFilesystem)
        filesystem._attributes = Mock(return_value=0x10)
        observed = {}

        def query(handle, _status, output, _size, information_class):
            self.assertEqual(6, information_class)  # FileInternalInformation
            self.assertIn(handle, (42, 99))
            output._obj.value = 789
            return 0

        def reopen(volume, identity, access, sharing, security, flags):
            information = identity._obj
            observed.update(volume=volume, identity=information.Id.FileId, kind=information.Type,
                            size=information.dwSize, access=access, sharing=sharing,
                            security=security, flags=flags)
            return 99

        filesystem._nt = SimpleNamespace(NtQueryInformationFile=query)
        filesystem._kernel = SimpleNamespace(OpenFileById=reopen, GetFileType=Mock(return_value=1),
            ReOpenFile=Mock(side_effect=PermissionError("native directory ReOpenFile: WinError 5")),
            CloseHandle=Mock())
        filesystem._crt = SimpleNamespace(get_osfhandle=Mock(return_value=42),
                                          open_osfhandle=Mock(return_value=7))
        windows_os = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
        windows_os.O_BINARY = windows_os.O_NOINHERIT = 0
        with patch("engineering_assistant.platforms.windows_artifact_fs.os", windows_os):
            self.assertEqual(7, filesystem._reopen_directory(8))
        self.assertEqual(42, observed["volume"])
        self.assertEqual(789, observed["identity"])
        self.assertEqual(0, observed["kind"])
        self.assertEqual(24, observed["size"])
        self.assertEqual(7, observed["sharing"])
        self.assertIsNone(observed["security"])
        self.assertTrue(observed["flags"] & 0x200000)  # Never follow a reparse point.
        filesystem._kernel.ReOpenFile.assert_not_called()

    def test_ntfs_reopen_rejects_changed_or_reparse_identity_before_crt_fd(self) -> None:
        for attributes, reason in ((0x400, "unsafe"), (0x10, "changed its NTFS identity")):
            with self.subTest(attributes=attributes):
                filesystem = object.__new__(WindowsFilesystem)
                filesystem._handle = Mock(return_value=42)
                filesystem._attributes = Mock(side_effect=(0x10, attributes))
                filesystem._file_id = Mock(side_effect=(789, 790))
                filesystem._kernel = SimpleNamespace(OpenFileById=Mock(return_value=99),
                    GetFileType=Mock(return_value=1), CloseHandle=Mock())
                filesystem._crt = SimpleNamespace(open_osfhandle=Mock(return_value=7))
                with self.assertRaisesRegex(ValidationFailure, reason):
                    filesystem._reopen_directory(8)
                filesystem._kernel.CloseHandle.assert_called_once_with(99)
                filesystem._crt.open_osfhandle.assert_not_called()

    def test_truncated_ace_sid_is_rejected_before_native_sid_conversion(self) -> None:
        filesystem = object.__new__(WindowsFilesystem)
        filesystem._user_sid = "current-user"
        filesystem._handle = Mock(return_value=12)
        filesystem._reopen_handle = Mock(return_value=123)
        filesystem._attributes = Mock(return_value=0x10)
        filesystem._sid_text = Mock(return_value="current-user")
        # ACE reserves eight SID bytes but claims one further subauthority.
        acl = ctypes.create_string_buffer(struct.pack("<BBHHHBBHI", 2, 0, 24, 1, 0, 0, 0, 16, 1)
                                         + bytes((1, 1, 0, 0, 0, 0, 0, 5)))

        def security(_handle, _kind, _flags, owner, _group, dacl, _sacl, _security):
            owner._obj.value = 1
            dacl._obj.value = ctypes.addressof(acl)
            return 0

        def information(_acl, output, _size, _class):
            output._obj.AceCount = 1
            output._obj.AclBytesInUse = 24
            return 1

        def ace(_acl, _index, output):
            output._obj.value = ctypes.addressof(acl) + 8
            return 1

        filesystem._advapi = SimpleNamespace(GetSecurityInfo=security, IsValidAcl=Mock(return_value=1),
                                            GetAclInformation=information, GetAce=ace,
                                            GetLengthSid=Mock(return_value=12))
        filesystem._kernel = SimpleNamespace(ReOpenFile=Mock(return_value=123), CloseHandle=Mock(),
                                            LocalFree=Mock())
        with self.assertRaisesRegex(ValidationFailure, "truncated identity"):
            filesystem.assert_private_directory(8)
        filesystem._sid_text.assert_called_once()  # Only the owner, never the truncated ACE.
        filesystem._advapi.GetLengthSid.assert_not_called()

    def test_readonly_metadata_sync_does_not_request_an_invalid_data_flush(self) -> None:
        filesystem = object.__new__(WindowsFilesystem)
        filesystem._handle = Mock(return_value=123)

        def query(_handle, _status, output, _size, information_class):
            self.assertEqual(8, information_class)
            output._obj.value = 0x1  # FILE_READ_DATA, no write/append data access
            return 0

        filesystem._nt = SimpleNamespace(NtQueryInformationFile=query)
        with patch("engineering_assistant.platforms.windows_artifact_fs.os.fstat",
                   return_value=SimpleNamespace(st_mode=0o100600)), patch(
            "engineering_assistant.platforms.windows_artifact_fs.os.fsync",
            side_effect=PermissionError("Windows FlushFileBuffers requires data write access"),
        ) as sync:
            filesystem.fsync(8)
            sync.assert_not_called()

    def test_write_handle_flush_failure_still_aborts_publication(self) -> None:
        filesystem = object.__new__(WindowsFilesystem)
        filesystem._handle = Mock(return_value=123)

        def query(_handle, _status, output, _size, _information_class):
            output._obj.value = 0x2  # FILE_WRITE_DATA
            return 0

        filesystem._nt = SimpleNamespace(NtQueryInformationFile=query)
        with patch("engineering_assistant.platforms.windows_artifact_fs.os.fstat",
                   return_value=SimpleNamespace(st_mode=0o100600)), patch(
            "engineering_assistant.platforms.windows_artifact_fs.os.fsync", side_effect=OSError("disk failed")
        ):
            with self.assertRaisesRegex(OSError, "disk failed"):
                filesystem.fsync(8)

    def test_link_and_stat_do_not_require_file_data_read_access(self) -> None:
        filesystem = object.__new__(WindowsFilesystem)
        filesystem._native_open = Mock(return_value=8)
        filesystem._attributes = Mock(return_value=0)
        filesystem._handle = Mock(return_value=123)
        filesystem._set_information = Mock()
        with patch("engineering_assistant.platforms.windows_artifact_fs.os.close"):
            filesystem.link("staging.json", "value.json", src_dir_fd=3, dst_dir_fd=4)
        options = filesystem._native_open.call_args.kwargs
        self.assertTrue(options.get("metadata_only"))
        self.assertEqual(0x100, options.get("extra_access"))
        with patch("engineering_assistant.platforms.windows_artifact_fs.os.close"), patch(
            "engineering_assistant.platforms.windows_artifact_fs.os.fstat", return_value=SimpleNamespace(st_mode=0o100600)
        ):
            filesystem.stat("value.json", dir_fd=4, follow_symlinks=False)
        self.assertTrue(filesystem._native_open.call_args.kwargs.get("metadata_only"))

    def test_native_child_open_retains_parent_and_checks_handle_before_exposing_fd(self) -> None:
        filesystem = object.__new__(WindowsFilesystem)
        filesystem._private_security = None
        observed = {}

        def create(handle_out, access, attributes_pointer, _status, _size,
                   _attributes, _sharing, disposition, options, _ea, _ea_size):
            attributes = attributes_pointer._obj
            name = attributes.ObjectName.contents
            observed.update(root=attributes.RootDirectory,
                            name=ctypes.string_at(name.Buffer, name.Length).decode("utf-16-le"),
                            access=access, disposition=disposition, options=options,
                            attributes=attributes.Attributes)
            handle_out._obj.value = 99
            return 0

        filesystem._nt = SimpleNamespace(NtCreateFile=create)
        filesystem._kernel = SimpleNamespace(GetFileType=Mock(return_value=1), CloseHandle=Mock())
        filesystem._crt = SimpleNamespace(get_osfhandle=Mock(return_value=42),
                                          open_osfhandle=Mock(return_value=7))
        filesystem._attributes = Mock(return_value=0)
        # These CRT flags exist only on Windows. The NT ABI and containment
        # decisions can be tested here without pretending to exercise the OS.
        windows_os = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
        windows_os.O_BINARY = 0
        windows_os.O_NOINHERIT = 0
        with patch("engineering_assistant.platforms.windows_artifact_fs.os", windows_os):
            self.assertEqual(7, filesystem.open("payload.json", os.O_RDONLY, dir_fd=3))
            self.assertEqual(42, observed["root"])
            self.assertEqual("payload.json", observed["name"])
            self.assertTrue(observed["attributes"] & 0x1000)
            self.assertTrue(observed["options"] & 0x200000)
            filesystem.open("payload.json", os.O_WRONLY, dir_fd=3)
            self.assertTrue(observed["access"] & 0x40000000)
            filesystem._attributes.return_value = 0x400
            filesystem._crt.open_osfhandle.reset_mock()
            with self.assertRaises(OSError):
                filesystem.open("payload.json", os.O_RDONLY, dir_fd=3)
            filesystem._kernel.CloseHandle.assert_called_once()
            filesystem._crt.open_osfhandle.assert_not_called()

    def test_unsafe_windows_names_cannot_address_a_device_or_stream(self) -> None:
        for name in ("", "..", "a/b", "a\\b", "C:thing", "file:stream", "NUL",
                     "con.txt", "COM1", "lpt9.log", "file.", "file ", "a\x00b"):
            with self.subTest(name=name), self.assertRaises(ValidationFailure):
                _validate_child_name(name)
        for name in ("payload.json", "中文文件.json", ".artifact.lock", "COM10"):
            _validate_child_name(name)

    def test_rename_buffer_uses_byte_length_and_native_handle_alignment(self) -> None:
        buffer = _name_information("中文.json", 123, replace=True)
        head = _NameInformation.from_buffer(buffer)
        self.assertEqual(1, head.ReplaceIfExists)
        self.assertEqual(123, head.RootDirectory)
        encoded = "中文.json".encode("utf-16-le")
        self.assertEqual(len(encoded), head.FileNameLength)
        self.assertEqual(encoded, buffer.raw[_NameInformation.FileName.offset:
                                            _NameInformation.FileName.offset + len(encoded)])

    def test_directory_decoder_rejects_truncated_or_cyclic_records(self) -> None:
        name = "中文.json".encode("utf-16-le")
        self.assertEqual(["中文.json"], list(_decode_directory_names(
            struct.pack("<III", 0, 0, len(name)) + name
        )))
        for raw in (b"short", struct.pack("<III", 0, 0, 80) + b"x",
                    struct.pack("<III", 4, 0, 2) + b"x\x00"):
            with self.assertRaises(ValidationFailure):
                list(_decode_directory_names(raw))


@unittest.skipUnless(os.name == "nt", "requires real Windows NT filesystem handles")
class WindowsArtifactIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.artifacts = ArtifactIO(self.root, "artifacts")

    def tearDown(self) -> None:
        self.artifacts.close()
        self.temporary.cleanup()

    def _set_directory_dacl(self, handle, sddl: str | None) -> None:
        security = artifact_fs._security_descriptor(sddl) if sddl is not None else None
        try:
            dacl = ctypes.c_void_p()
            if security is not None:
                present, defaulted = ctypes.c_int(), ctypes.c_int()
                self.assertTrue(artifact_fs._advapi.GetSecurityDescriptorDacl(
                    security, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
                ))
                self.assertTrue(present.value)
            self.assertEqual(0, artifact_fs._advapi.SetSecurityInfo(
                handle, 1, 0x80000004, None, None, dacl, None
            ))
        finally:
            if security is not None:
                artifact_fs._kernel.LocalFree(security)

    def test_private_directory_validation_accepts_path_and_retained_handle(self) -> None:
        directory = self.artifacts.ensure_directory("private")
        artifact_fs.assert_private_directory(directory)
        with self.artifacts.open_directory("private") as descriptor:
            artifact_fs.assert_private_directory(descriptor)

    def test_plain_created_descendants_inherit_private_directory_dacl(self) -> None:
        directory = self.artifacts.ensure_directory("private")
        # uv/Python create their venv children with ordinary filesystem APIs.
        nested = directory / "plain" / "Scripts"
        nested.mkdir(parents=True)
        (nested / "ordinary.json").write_text("{}", encoding="utf-8")
        for path in (nested.parent, nested):
            descriptor = artifact_fs.open(str(path), os.O_RDONLY | artifact_fs.O_DIRECTORY)
            try:
                # A Windows token may default ownership to an eligible group.
                artifact_fs.set_private_owner(descriptor)
                artifact_fs.assert_private_directory(descriptor)
            finally:
                artifact_fs.close(descriptor)

    def test_new_staging_owner_assignment_preserves_rejected_broad_dacl(self) -> None:
        directory = self.artifacts.ensure_directory("new-staging")
        with self.artifacts.open_directory("new-staging") as descriptor:
            handle = artifact_fs._reopen_handle(descriptor, 0x60080)
            self.assertNotIn(handle, (None, ctypes.c_void_p(-1).value))
            private = f"D:P(A;;FA;;;{artifact_fs._user_sid})(A;;FA;;;SY)"
            try:
                self._set_directory_dacl(handle, private + "(A;;FA;;;WD)")
                artifact_fs.set_private_owner(descriptor)
                with self.assertRaises(ValidationFailure):
                    artifact_fs.assert_private_directory(directory)
            finally:
                self._set_directory_dacl(handle, private)
                artifact_fs._kernel.CloseHandle(handle)

    def test_private_directory_validation_rejects_broad_and_null_dacls(self) -> None:
        directory = self.artifacts.ensure_directory("private")
        private = f"D:P(A;;FA;;;{artifact_fs._user_sid})(A;;FA;;;SY)"
        with self.artifacts.open_directory("private") as descriptor:
            handle = artifact_fs._reopen_handle(descriptor, 0x60080)
            self.assertNotIn(handle, (None, ctypes.c_void_p(-1).value))
            try:
                for principal in ("WD", "AU", "BA"):
                    with self.subTest(principal=principal):
                        self._set_directory_dacl(handle, private + f"(A;OICI;FA;;;{principal})")
                        with self.assertRaises(ValidationFailure):
                            artifact_fs.assert_private_directory(directory)
                        with self.assertRaises(ValidationFailure):
                            artifact_fs.assert_private_directory(descriptor)
                        # Validation must leave the rejected ACL untouched.
                        with self.assertRaises(ValidationFailure):
                            artifact_fs.assert_private_directory(descriptor)
                self._set_directory_dacl(handle, None)
                with self.assertRaises(ValidationFailure):
                    artifact_fs.assert_private_directory(descriptor)
            finally:
                self._set_directory_dacl(handle, private)
                artifact_fs._kernel.CloseHandle(handle)
            artifact_fs.assert_private_directory(descriptor)

    def test_concurrent_immutable_and_cas_have_exactly_one_winner(self) -> None:
        barrier = Barrier(2)

        def create(value):
            barrier.wait()
            try:
                self.artifacts.create_immutable_json({"revision": 0, "value": value}, "state.json")
                return "created"
            except ArtifactConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(["conflict", "created"], sorted(pool.map(create, (1, 2))))
        barrier = Barrier(2)

        def update(value):
            barrier.wait()
            try:
                self.artifacts.replace_json_cas({"revision": 1, "value": value},
                                                "state.json", expected_revision=0)
                return "saved"
            except ArtifactConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(["conflict", "saved"], sorted(pool.map(update, (3, 4))))

    def test_lock_timeout_and_empty_directory_removal(self) -> None:
        other = ArtifactIO(self.root, "artifacts", lock_timeout_seconds=0.02)
        try:
            with self.artifacts.transaction("busy"):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(other.create_immutable_json, {"value": 1}, "busy", "value.json")
                    with self.assertRaisesRegex(ValidationFailure, "lock is busy"):
                        future.result()
            self.assertTrue(self.artifacts.remove_empty_directory("busy"))
            self.assertFalse((self.root / "artifacts/busy").exists())
        finally:
            other.close()

    def test_created_file_and_chmod_preserve_private_owner_dacl(self) -> None:
        self.artifacts.write_bytes_exclusive(b"secret", "private.json")
        self.artifacts.chmod_regular_file(0o444, "private.json")
        with self.artifacts.open_directory() as directory:
            with self.assertRaises(OSError):
                descriptor = artifact_fs.open("private.json", os.O_WRONLY, dir_fd=directory)
                artifact_fs.close(descriptor)
            descriptor = artifact_fs.open("private.json", os.O_RDONLY, dir_fd=directory)
            try:
                handle = artifact_fs._reopen_handle(descriptor, 0x20080)
                self.assertNotIn(handle, (None, ctypes.c_void_p(-1).value))
                try:
                    owner, control, allowed = _file_security_identity(artifact_fs, handle)
                    self.assertEqual(artifact_fs._user_sid, owner)
                    self.assertTrue(control & 0x1000)  # SE_DACL_PROTECTED
                    self.assertEqual({artifact_fs._user_sid, "S-1-5-18"}, set(allowed))
                    self.assertTrue(allowed[artifact_fs._user_sid] & 1)  # FILE_READ_DATA
                    self.assertFalse(allowed[artifact_fs._user_sid] & 2)  # FILE_WRITE_DATA
                finally:
                    artifact_fs._kernel.CloseHandle(handle)
            finally:
                artifact_fs.close(descriptor)
        self.artifacts.chmod_regular_file(0o600, "private.json")
        self.assertEqual(b"secret", self.artifacts.read_bytes_limited(64, "private.json"))

    def test_parent_rename_keeps_reads_and_writes_on_opened_identity(self) -> None:
        self.artifacts.close()
        parent = self.root / "parent"
        project = parent / "project"
        project.mkdir(parents=True)
        self.artifacts = ArtifactIO(project, ".")
        self.artifacts.create_immutable_json({"trusted": True}, "old.json")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "old.json").write_text('{"trusted": false}', encoding="utf-8")
        held = self.root / "held"
        with self.artifacts.open_directory() as opened:
            before = artifact_fs.fstat(opened)
            # NTFS refuses ancestor rename while its child directory is open,
            # even when handles share DELETE (MS-FSA section 2.1.4.2).
            with self.assertRaises(PermissionError) as rejected:
                parent.rename(held)
            self.assertEqual(5, rejected.exception.winerror)
            after, named = artifact_fs.fstat(opened), project.stat()
            identity = (before.st_dev, before.st_ino)
            self.assertEqual(identity, (after.st_dev, after.st_ino))
            self.assertEqual(identity, (named.st_dev, named.st_ino))
            self.assertFalse(held.exists())
            self.assertEqual({"trusted": True}, self.artifacts.read_json("old.json"))
            self.artifacts.create_immutable_json({"trusted": True}, "new.json")
            self.assertTrue((project / "new.json").exists())
            self.assertFalse((outside / "new.json").exists())
            self.assertEqual('{"trusted": false}', (outside / "old.json").read_text(encoding="utf-8"))

    def test_directory_fd_copy_hash_rename_and_delete_contract(self) -> None:
        path, descriptor, metadata = self.artifacts.create_directory_exclusive_open("staging")
        child = ArtifactIO.from_open_directory_fd(path, descriptor)
        artifact_fs.close(descriptor)
        try:
            child.write_bytes_exclusive(b"data", "nested", "payload.txt")
            hashes = child.sha256_file_digests(max_file_bytes=100, max_entries=10)
            self.assertEqual({"nested/payload.txt"}, set(hashes))
            with child.open_directory("nested") as directory:
                with artifact_fs.scandir(directory) as entries:
                    self.assertEqual(["payload.txt"], [entry.name for entry in entries])
            self.artifacts.rename_child_directory_if_matches("staging", "published", metadata)
            self.assertTrue(self.artifacts.remove_tree("published"))
        finally:
            child.close()

    def test_junction_is_rejected_without_reading_or_writing_its_target(self) -> None:
        import subprocess

        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.json").write_text('{"outside": true}', encoding="utf-8")
        artifacts = self.artifacts.ensure_directory()
        junction = artifacts / "junction"
        completed = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J",
                                    str(junction), str(outside)], capture_output=True)
        self.assertEqual(0, completed.returncode, completed.stderr.decode(errors="replace"))
        try:
            with self.assertRaises(ValidationFailure):
                self.artifacts.read_json("junction", "secret.json")
            with self.assertRaises(ValidationFailure):
                self.artifacts.create_immutable_json({"new": True}, "junction", "new.json")
            with self.assertRaises(ValidationFailure):
                self.artifacts.sha256_file_digests(max_file_bytes=100)
            self.assertFalse((outside / "new.json").exists())
            self.assertEqual('{"outside": true}', (outside / "secret.json").read_text(encoding="utf-8"))
        finally:
            junction.rmdir()


if __name__ == "__main__":
    unittest.main()
