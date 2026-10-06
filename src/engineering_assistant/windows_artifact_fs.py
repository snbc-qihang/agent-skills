"""Windows handle-relative filesystem seam used by ArtifactIO.

Each child is opened relative to a retained directory HANDLE. Reparse points are
opened without following them and rejected from handle attributes; mutations use
the opened file's identity and an anchored destination HANDLE. No process-wide
monkey patch, shell command or reconstructed child path is used for filesystem IO.
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import struct
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from .validation import ValidationFailure


_DWORD = ctypes.c_uint32
_HANDLE = ctypes.c_void_p
_NTSTATUS = ctypes.c_int32
_ACCESS_MODE = os.O_RDONLY | os.O_WRONLY | os.O_RDWR


class _UnicodeString(ctypes.Structure):
    _fields_ = [("Length", ctypes.c_uint16), ("MaximumLength", ctypes.c_uint16),
                ("Buffer", ctypes.c_void_p)]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [("Length", _DWORD), ("RootDirectory", _HANDLE),
                ("ObjectName", ctypes.POINTER(_UnicodeString)), ("Attributes", _DWORD),
                ("SecurityDescriptor", ctypes.c_void_p), ("SecurityQualityOfService", ctypes.c_void_p)]


class _IOStatusBlock(ctypes.Structure):
    _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]


class _NameInformation(ctypes.Structure):
    _fields_ = [("ReplaceIfExists", ctypes.c_ubyte), ("RootDirectory", _HANDLE),
                ("FileNameLength", _DWORD), ("FileName", ctypes.c_uint16 * 1)]


class _ACLSizeInformation(ctypes.Structure):
    _fields_ = [("AceCount", _DWORD), ("AclBytesInUse", _DWORD), ("AclBytesFree", _DWORD)]


class _FileIdentifier(ctypes.Union):
    _fields_ = [("FileId", ctypes.c_uint64), ("Reserved", ctypes.c_ubyte * 16)]


class _FileIdDescriptor(ctypes.Structure):
    _fields_ = [("dwSize", _DWORD), ("Type", ctypes.c_int32), ("Id", _FileIdentifier)]


def _validate_child_name(name: str) -> None:
    """Reject Windows device aliases, ADS, and ambiguous Win32 spelling."""

    device = name.split(".", 1)[0].upper()
    if (
        not name or name in (".", "..") or any(char in name for char in '/\\:\x00<>"|?*')
        or any(ord(char) < 32 for char in name) or name.endswith((".", " "))
        or device in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        or device in {f"{prefix}{number}" for prefix in ("COM", "LPT")
                      for number in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "¹", "²", "³")}
    ):
        raise ValidationFailure("artifact path contains an unsafe Windows name")


def _name_information(name: str, parent_handle: int, *, replace: bool):
    _validate_child_name(name)
    encoded = name.encode("utf-16-le")
    offset = _NameInformation.FileName.offset
    buffer = ctypes.create_string_buffer(max(ctypes.sizeof(_NameInformation), offset + len(encoded)))
    head = _NameInformation.from_buffer(buffer)
    head.ReplaceIfExists = int(replace)
    head.RootDirectory = parent_handle
    head.FileNameLength = len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
    return buffer


def _decode_directory_names(raw: bytes):
    offset = 0
    while True:
        if len(raw) - offset < 12:
            raise ValidationFailure("Windows directory record is truncated")
        next_offset, _index, length = struct.unpack_from("<III", raw, offset)
        end = offset + 12 + length
        if length % 2 or end > len(raw):
            raise ValidationFailure("Windows directory record is truncated")
        try:
            name = raw[offset + 12:end].decode("utf-16-le")
        except UnicodeDecodeError as exc:
            raise ValidationFailure("Windows directory record contains invalid text") from exc
        if name not in (".", ".."):
            _validate_child_name(name)
            yield name
        if not next_offset:
            return
        if next_offset < 12 + length or next_offset % 4 or offset + next_offset >= len(raw):
            raise ValidationFailure("Windows directory record has an invalid offset")
        offset += next_offset


class WindowsFilesystem:
    """A small os-compatible subset; exposed descriptors remain real CRT fds."""

    O_DIRECTORY = 0x10000000
    O_NOFOLLOW = 0x20000000
    O_NONBLOCK = 0x40000000

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows filesystem backend requires Windows")
        import msvcrt

        self._crt = msvcrt
        self._nt = ctypes.WinDLL("ntdll", use_last_error=True)
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._bind(self._nt, "NtCreateFile", _NTSTATUS,
                   [ctypes.POINTER(_HANDLE), _DWORD, ctypes.POINTER(_ObjectAttributes),
                    ctypes.POINTER(_IOStatusBlock), ctypes.c_void_p, _DWORD, _DWORD,
                    _DWORD, _DWORD, ctypes.c_void_p, _DWORD])
        self._bind(self._nt, "NtSetInformationFile", _NTSTATUS,
                   [_HANDLE, ctypes.POINTER(_IOStatusBlock), ctypes.c_void_p, _DWORD, _DWORD])
        self._bind(self._nt, "NtQueryInformationFile", _NTSTATUS,
                   [_HANDLE, ctypes.POINTER(_IOStatusBlock), ctypes.c_void_p, _DWORD, _DWORD])
        self._bind(self._nt, "NtQueryDirectoryFile", _NTSTATUS,
                   [_HANDLE, _HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.POINTER(_IOStatusBlock), ctypes.c_void_p, _DWORD, _DWORD,
                    ctypes.c_ubyte, ctypes.c_void_p, ctypes.c_ubyte])
        self._bind(self._nt, "RtlNtStatusToDosError", _DWORD, [_NTSTATUS])
        self._bind(self._kernel, "GetFileInformationByHandleEx", ctypes.c_int,
                   [_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD])
        self._bind(self._kernel, "GetFileType", _DWORD, [_HANDLE])
        self._bind(self._kernel, "CloseHandle", ctypes.c_int, [_HANDLE])
        self._bind(self._kernel, "OpenFileById", _HANDLE,
                   [_HANDLE, ctypes.POINTER(_FileIdDescriptor), _DWORD, _DWORD, ctypes.c_void_p, _DWORD])
        self._bind(self._kernel, "GetFinalPathNameByHandleW", _DWORD,
                   [_HANDLE, ctypes.c_wchar_p, _DWORD, _DWORD])
        self._bind(self._kernel, "GetCurrentProcess", _HANDLE, [])
        self._bind(self._kernel, "LocalFree", _HANDLE, [_HANDLE])
        self._bind(self._kernel, "GetVolumeInformationByHandleW", ctypes.c_int,
                   [_HANDLE, ctypes.c_wchar_p, _DWORD, ctypes.POINTER(_DWORD),
                    ctypes.POINTER(_DWORD), ctypes.POINTER(_DWORD), ctypes.c_wchar_p, _DWORD])
        self._bind(self._advapi, "OpenProcessToken", ctypes.c_int,
                   [_HANDLE, _DWORD, ctypes.POINTER(_HANDLE)])
        self._bind(self._advapi, "GetTokenInformation", ctypes.c_int,
                   [_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD, ctypes.POINTER(_DWORD)])
        self._bind(self._advapi, "ConvertSidToStringSidW", ctypes.c_int,
                   [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)])
        self._bind(self._advapi, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                   ctypes.c_int, [ctypes.c_wchar_p, _DWORD, ctypes.POINTER(ctypes.c_void_p),
                                  ctypes.POINTER(_DWORD)])
        self._bind(self._advapi, "GetSecurityDescriptorDacl", ctypes.c_int,
                   [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int)])
        self._bind(self._advapi, "GetSecurityDescriptorOwner", ctypes.c_int,
                   [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int)])
        self._bind(self._advapi, "SetSecurityInfo", _DWORD,
                   [_HANDLE, ctypes.c_int, _DWORD, ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.c_void_p, ctypes.c_void_p])
        self._bind(self._advapi, "GetSecurityInfo", _DWORD,
                   [_HANDLE, ctypes.c_int, _DWORD, ctypes.POINTER(ctypes.c_void_p),
                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_void_p)])
        self._bind(self._advapi, "IsValidAcl", ctypes.c_int, [ctypes.c_void_p])
        self._bind(self._advapi, "GetAclInformation", ctypes.c_int,
                   [ctypes.c_void_p, ctypes.c_void_p, _DWORD, ctypes.c_int])
        self._bind(self._advapi, "GetAce", ctypes.c_int,
                   [ctypes.c_void_p, _DWORD, ctypes.POINTER(ctypes.c_void_p)])
        self._bind(self._advapi, "IsValidSid", ctypes.c_int, [ctypes.c_void_p])
        self._bind(self._advapi, "GetLengthSid", _DWORD, [ctypes.c_void_p])
        self._private_security = self._owner_security_descriptor()

    @staticmethod
    def _bind(library, name, result, arguments) -> None:
        function = getattr(library, name)
        function.restype = result
        function.argtypes = arguments

    def __getattr__(self, name):
        return getattr(os, name)

    def _owner_security_descriptor(self):
        token = _HANDLE()
        if not self._advapi.OpenProcessToken(self._kernel.GetCurrentProcess(), 0x8, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            length = _DWORD()
            self._advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))
            if not length.value or length.value > 65536:
                raise ValidationFailure("cannot obtain Windows user identity")
            buffer = ctypes.create_string_buffer(length.value)
            if not self._advapi.GetTokenInformation(token, 1, buffer, length, ctypes.byref(length)):
                raise ctypes.WinError(ctypes.get_last_error())
            sid = ctypes.c_void_p.from_buffer(buffer).value
            text = ctypes.c_void_p()
            if not self._advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                self._user_sid = ctypes.wstring_at(text)
            finally:
                self._kernel.LocalFree(text)
        finally:
            self._kernel.CloseHandle(token)
        # Protected DACL: the current user and SYSTEM can access created objects.
        # It is supplied at creation, so an inherited broad DACL is never exposed.
        return self._security_descriptor(
            f"O:{self._user_sid}D:P(A;OICI;FA;;;{self._user_sid})(A;OICI;FA;;;SY)"
        )

    def _security_descriptor(self, sddl: str):
        descriptor = ctypes.c_void_p()
        if not self._advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return descriptor

    def _handle(self, descriptor: int) -> int:
        return self._crt.get_osfhandle(descriptor)

    def _sid_text(self, sid) -> str:
        if not sid or not self._advapi.IsValidSid(sid):
            raise ValidationFailure("Runtime directory has an invalid Windows identity")
        text = ctypes.c_void_p()
        if not self._advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ValidationFailure("Runtime directory identity cannot be read")
        try:
            return ctypes.wstring_at(text)
        finally:
            self._kernel.LocalFree(text)

    def set_private_owner(self, descriptor: int) -> None:
        """Set user ownership on a caller-owned, newly created staging handle.

        The caller must restrict this to its new unpublished files/directories.
        Existing data directories and published environments are never repaired
        through this API. DACLs are preserved; this does not widen any access.
        """
        metadata = os.fstat(descriptor)
        if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
            raise ValidationFailure("private owner requires a regular staging object")
        if self._attributes(self._handle(descriptor)) & 0x400:
            raise ValidationFailure("private owner cannot target a reparse point")
        security = self._security_descriptor(f"O:{self._user_sid}")
        try:
            handle = self._reopen_handle(descriptor, 0xA0080, flags=0x82200000)
        except BaseException:
            self._kernel.LocalFree(security)
            raise
        try:
            owner, defaulted = ctypes.c_void_p(), ctypes.c_int()
            if not self._advapi.GetSecurityDescriptorOwner(security, ctypes.byref(owner), ctypes.byref(defaulted)):
                raise ValidationFailure("new staging owner cannot be constructed")
            error = self._advapi.SetSecurityInfo(handle, 1, 0x1, owner, None, None, None)
            if error:
                raise ValidationFailure("new staging owner cannot be assigned")
        finally:
            self._kernel.CloseHandle(handle)
            self._kernel.LocalFree(security)

    def assert_private_directory(self, path_or_descriptor) -> None:
        """Require current-user ownership and only user/SYSTEM allow ACEs.

        Administrators are not an implicit application data trustee. OS-level
        privileged takeover is outside this single-user data access contract.
        This validates the retained directory identity and never changes its ACL.
        """
        if isinstance(path_or_descriptor, int):
            handle = self._reopen_handle(path_or_descriptor, 0x120080)
            descriptor = None
        else:
            descriptor = self._native_open(str(Path(path_or_descriptor).absolute()),
                                            os.O_RDONLY | self.O_DIRECTORY, extra_access=0x20000)
            handle = self._handle(descriptor)
        security, owner, dacl = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        try:
            attributes = self._attributes(handle)
            if attributes & 0x400 or not attributes & 0x10:
                raise ValidationFailure("Runtime directory is unsafe")
            # OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION; the
            # returned owner/DACL pointers belong to the LocalFree buffer.
            status = self._advapi.GetSecurityInfo(handle, 1, 0x5, ctypes.byref(owner),
                None, ctypes.byref(dacl), None, ctypes.byref(security))
            if status or self._sid_text(owner) != self._user_sid or not dacl:
                raise ValidationFailure("Runtime directory is not private to the current user")
            information = _ACLSizeInformation()
            if not self._advapi.IsValidAcl(dacl) or not self._advapi.GetAclInformation(
                dacl, ctypes.byref(information), ctypes.sizeof(information), 2
            ) or not 0 < information.AceCount <= 1024 or not 8 <= information.AclBytesInUse <= 65535:
                raise ValidationFailure("Runtime directory DACL is missing or invalid")
            user_allowed = False
            for index in range(information.AceCount):
                ace = ctypes.c_void_p()
                if not self._advapi.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
                    raise ValidationFailure("Runtime directory DACL cannot be inspected")
                if not dacl.value + 8 <= ace.value <= dacl.value + information.AclBytesInUse - 8:
                    raise ValidationFailure("Runtime directory DACL has an invalid ACE")
                kind, flags, size, mask = struct.unpack("<BBHI", ctypes.string_at(ace, 8))
                if kind not in (0, 1) or size < 16 or ace.value + size > dacl.value + information.AclBytesInUse:
                    raise ValidationFailure("Runtime directory DACL has an unsupported ACE")
                sid = ctypes.c_void_p(ace.value + 8)
                sid_header = ctypes.string_at(sid, 8)
                if 8 + 4 * sid_header[1] > size - 8:
                    raise ValidationFailure("Runtime directory DACL has a truncated identity")
                trustee = self._sid_text(sid)
                if self._advapi.GetLengthSid(sid) > size - 8:
                    raise ValidationFailure("Runtime directory DACL has an invalid identity")
                if kind == 0 and mask:
                    if trustee not in (self._user_sid, "S-1-5-18"):
                        raise ValidationFailure("Runtime directory grants access outside the current user and SYSTEM")
                    user_allowed |= trustee == self._user_sid and not flags & 0x8  # INHERIT_ONLY_ACE
            if not user_allowed:
                raise ValidationFailure("Runtime directory does not grant its current user access")
        finally:
            if security.value:
                self._kernel.LocalFree(security)
            if descriptor is None:
                self._kernel.CloseHandle(handle)
            else:
                os.close(descriptor)

    def _raise_status(self, status: int, name: str | None = None) -> None:
        code = status & 0xFFFFFFFF
        if code in (0xC0000034, 0xC000003A):
            raise FileNotFoundError(errno.ENOENT, "Windows artifact entry does not exist", name)
        if code == 0xC0000035:
            raise FileExistsError(errno.EEXIST, "Windows artifact entry already exists", name)
        if code in (0xC000050B, 0xC0000275, 0xC0000280):
            raise OSError(errno.ELOOP, "artifact path contains an unsafe reparse point", name)
        raise ctypes.WinError(self._nt.RtlNtStatusToDosError(status))

    def _attributes(self, handle: int) -> int:
        info = (_DWORD * 2)()
        if not self._kernel.GetFileInformationByHandleEx(handle, 9, info, ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return info[0]

    def _native_open(self, name: str, flags: int, *, directory_fd=None,
                     allow_reparse=False, delete_access=False, directory=None,
                     metadata_only=False, extra_access=0) -> int:
        if directory_fd is None:
            path = Path(name)
            # Restrict mutable artifacts to local DOS drive paths. Device paths,
            # UNC, and alternate streams have different access/locking contracts.
            if not path.is_absolute() or len(path.drive) != 2 or path.drive[1] != ":":
                raise ValidationFailure("Windows artifacts require an absolute local drive path")
            for part in path.parts[1:]:
                _validate_child_name(part)
            if len(path.parts) > 1:
                # Resolve the drive alias once, then walk every filesystem
                # component relative to retained handles. This also prevents
                # junction traversal in an absolute root's intermediate path.
                parent = self._native_open(path.anchor, os.O_RDONLY | self.O_DIRECTORY)
                try:
                    for part in path.parts[1:-1]:
                        child = self._native_open(part, os.O_RDONLY | self.O_DIRECTORY,
                                                  directory_fd=parent)
                        os.close(parent)
                        parent = child
                    return self._native_open(path.name, flags, directory_fd=parent,
                                              allow_reparse=allow_reparse,
                                              delete_access=delete_access, directory=directory,
                                              metadata_only=metadata_only, extra_access=extra_access)
                finally:
                    os.close(parent)
            native_name = "\\??\\" + str(path)
        else:
            _validate_child_name(name)
            native_name = name
        encoded = native_name.encode("utf-16-le")
        if len(encoded) > 65532:
            raise ValidationFailure("Windows artifact path is too long")
        name_buffer = ctypes.create_string_buffer(encoded + b"\0\0")
        unicode = _UnicodeString(len(encoded), len(encoded) + 2, ctypes.addressof(name_buffer))
        creating = bool(flags & os.O_CREAT)
        attributes = _ObjectAttributes(
            ctypes.sizeof(_ObjectAttributes),
            None if directory_fd is None else self._handle(directory_fd),
            ctypes.pointer(unicode),
            0x40 | (0x1000 if directory_fd is not None and not allow_reparse else 0),
            self._private_security if creating else None, None,
        )
        is_directory = bool(flags & self.O_DIRECTORY) if directory is None else directory
        access = 0x100000 | 0x80 | extra_access  # SYNCHRONIZE | FILE_READ_ATTRIBUTES
        if is_directory:
            access |= 0x1 | 0x20  # FILE_LIST_DIRECTORY | FILE_TRAVERSE
        elif not metadata_only:
            # FlushFileBuffers requires GENERIC_WRITE on writable data handles.
            access |= {os.O_RDONLY: 0x1, os.O_WRONLY: 0x40000000,
                       os.O_RDWR: 0xC0000000}[flags & _ACCESS_MODE]
        if delete_access:
            access |= 0x10000
        disposition = (2 if flags & os.O_EXCL else 3) if creating else 1
        # WRITE_THROUGH also requests NTFS metadata flushing for mutations made
        # through the handle; Windows does not offer POSIX directory fsync.
        options = 0x20 | 0x200000 | 0x2
        if directory is not None or flags & self.O_DIRECTORY:
            options |= 0x1 if is_directory else 0x40
        elif not allow_reparse:
            options |= 0x40
        handle = _HANDLE()
        status_block = _IOStatusBlock()
        status = self._nt.NtCreateFile(ctypes.byref(handle), access, ctypes.byref(attributes),
                                       ctypes.byref(status_block), None, 0x80, 0x7,
                                       disposition, options, None, 0)
        if status < 0:
            self._raise_status(status, name)
        try:
            file_attributes = self._attributes(handle)
            if self._kernel.GetFileType(handle) != 1:
                raise ValidationFailure("artifact is not a disk file or directory")
            if file_attributes & 0x400 and not allow_reparse:
                raise OSError(errno.ELOOP, "artifact path contains an unsafe reparse point", name)
            if directory_fd is None:
                filesystem = ctypes.create_unicode_buffer(64)
                if not self._kernel.GetVolumeInformationByHandleW(
                    handle, None, 0, None, None, None, filesystem, len(filesystem)
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                if filesystem.value != "NTFS":
                    raise ValidationFailure("Windows artifacts require a local NTFS filesystem")
            return self._crt.open_osfhandle(handle.value,
                                            (flags & _ACCESS_MODE) | os.O_BINARY | os.O_NOINHERIT)
        except BaseException:
            self._kernel.CloseHandle(handle)
            raise

    def _final_path(self, descriptor: int) -> Path:
        buffer = ctypes.create_unicode_buffer(32768)
        length = self._kernel.GetFinalPathNameByHandleW(self._handle(descriptor), buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise ValidationFailure("cannot identify anchored Windows directory")
        text = buffer.value
        if not text.startswith("\\\\?\\") or text.startswith("\\\\?\\UNC\\"):
            raise ValidationFailure("Windows artifacts require a local filesystem")
        return Path(text[4:])

    def _file_id(self, handle: int) -> int:
        identity, status_block = ctypes.c_uint64(), _IOStatusBlock()
        status = self._nt.NtQueryInformationFile(handle, ctypes.byref(status_block),
            ctypes.byref(identity), ctypes.sizeof(identity), 6)  # FileInternalInformation on NTFS.
        if status < 0:
            self._raise_status(status)
        return identity.value

    def _reopen_handle(self, descriptor: int, access: int, *, flags=0x02200000) -> int:
        # ReOpenFile requires a CreateFile handle, whereas this backend opens
        # through NtCreateFile. Reopen by NTFS identity on the retained volume;
        # parent renames cannot redirect this operation to a replacement path.
        original = self._handle(descriptor)
        if self._attributes(original) & 0x400:
            raise ValidationFailure("artifact handle contains a reparse point")
        identity = self._file_id(original)
        information = _FileIdDescriptor(ctypes.sizeof(_FileIdDescriptor), 0, _FileIdentifier(FileId=identity))
        handle = self._kernel.OpenFileById(original, ctypes.byref(information), access, 7, None, flags)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if self._kernel.GetFileType(handle) != 1 or self._attributes(handle) & 0x400:
                raise ValidationFailure("reopened artifact handle is unsafe")
            if self._file_id(handle) != identity:
                raise ValidationFailure("reopened artifact changed its NTFS identity")
            return handle
        except BaseException:
            self._kernel.CloseHandle(handle)
            raise

    def _reopen_directory(self, descriptor: int) -> int:
        handle = self._reopen_handle(descriptor, 0x1000A1)
        try:
            if not self._attributes(handle) & 0x10:
                raise ValidationFailure("artifact descriptor is not a directory")
            return self._crt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
        except BaseException:
            self._kernel.CloseHandle(handle)
            raise

    def open(self, path, flags, mode=0o777, *, dir_fd=None) -> int:
        name = os.fspath(path)
        if dir_fd is not None and name == ".":
            return self._reopen_directory(dir_fd)
        if dir_fd is not None and name == "..":
            current = self._final_path(dir_fd)
            if current.parent == current:
                return os.dup(dir_fd)
            parent_fd = self._native_open(str(current.parent), self.O_DIRECTORY | os.O_RDONLY)
            try:
                child_fd = self._native_open(current.name, self.O_DIRECTORY | os.O_RDONLY,
                                             directory_fd=parent_fd)
                try:
                    first, second = os.fstat(child_fd), os.fstat(dir_fd)
                    if (first.st_dev, first.st_ino) != (second.st_dev, second.st_ino):
                        raise ValidationFailure("anchored Windows parent directory changed identity")
                finally:
                    os.close(child_fd)
                return parent_fd
            except BaseException:
                os.close(parent_fd)
                raise
        return self._native_open(name, flags, directory_fd=dir_fd)

    def stat(self, path, *, dir_fd=None, follow_symlinks=True):
        descriptor = self._native_open(os.fspath(path), os.O_RDONLY, directory_fd=dir_fd,
                                       allow_reparse=True, directory=None, metadata_only=True)
        try:
            metadata = os.fstat(descriptor)
            if self._attributes(self._handle(descriptor)) & 0x400:
                return self._reparse_stat(metadata)
            return metadata
        finally:
            os.close(descriptor)

    @staticmethod
    def _reparse_stat(metadata):
        fields = {name: getattr(metadata, name) for name in dir(metadata) if name.startswith("st_")}
        fields["st_mode"] = stat.S_IFLNK | stat.S_IMODE(metadata.st_mode)
        return SimpleNamespace(**fields)

    def mkdir(self, path, mode=0o777, *, dir_fd=None) -> None:
        descriptor = self._native_open(os.fspath(path), os.O_RDONLY | os.O_CREAT | os.O_EXCL |
                                       self.O_DIRECTORY, directory_fd=dir_fd)
        os.close(descriptor)

    def _set_information(self, descriptor: int, buffer, information_class: int) -> None:
        status_block = _IOStatusBlock()
        status = self._nt.NtSetInformationFile(self._handle(descriptor), ctypes.byref(status_block),
                                              ctypes.byref(buffer), ctypes.sizeof(buffer), information_class)
        if status < 0:
            self._raise_status(status)

    def _move(self, source, target, *, src_dir_fd, dst_dir_fd, replace=False, link=False) -> None:
        if src_dir_fd is None or dst_dir_fd is None:
            raise ValidationFailure("Windows artifact mutation requires anchored directories")
        _validate_child_name(os.fspath(source))
        descriptor = self._native_open(os.fspath(source), os.O_RDONLY, directory_fd=src_dir_fd,
                                       delete_access=not link, directory=None, allow_reparse=True,
                                       metadata_only=True, extra_access=0x100 if link else 0)
        try:
            if self._attributes(self._handle(descriptor)) & 0x400:
                raise ValidationFailure("artifact mutation cannot target a reparse point")
            buffer = _name_information(os.fspath(target), self._handle(dst_dir_fd), replace=replace)
            if not link and replace:
                _DWORD.from_buffer(buffer).value |= 0x2  # FILE_RENAME_POSIX_SEMANTICS
            self._set_information(descriptor, buffer, 11 if link else 65)
        finally:
            os.close(descriptor)

    def rename(self, source, target, *, src_dir_fd=None, dst_dir_fd=None) -> None:
        self._move(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    def replace(self, source, target, *, src_dir_fd=None, dst_dir_fd=None) -> None:
        self._move(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, replace=True)

    def link(self, source, target, *, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True) -> None:
        self._move(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, link=True)

    def _delete(self, path, *, dir_fd, directory: bool) -> None:
        if dir_fd is None:
            raise ValidationFailure("Windows artifact deletion requires an anchored directory")
        descriptor = self._native_open(os.fspath(path), os.O_RDONLY, directory_fd=dir_fd,
                                       delete_access=True, directory=directory, metadata_only=True)
        try:
            # Windows 11/NTFS supports immediate name removal while cooperating
            # readers retain handles. Do not weaken to path-based DeleteFile.
            flags = _DWORD(0x1 | 0x2)  # DELETE | POSIX_SEMANTICS
            self._set_information(descriptor, flags, 64)
        finally:
            os.close(descriptor)

    def unlink(self, path, *, dir_fd=None) -> None:
        self._delete(path, dir_fd=dir_fd, directory=False)

    def rmdir(self, path, *, dir_fd=None) -> None:
        self._delete(path, dir_fd=dir_fd, directory=True)

    def fsync(self, descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            # Metadata mutations use synchronous WRITE_THROUGH handles. There is
            # no additional directory-fsync operation exposed by Windows.
            return
        access, status_block = _DWORD(), _IOStatusBlock()
        result = self._nt.NtQueryInformationFile(
            self._handle(descriptor), ctypes.byref(status_block), ctypes.byref(access),
            ctypes.sizeof(access), 8,  # FileAccessInformation
        )
        if result < 0:
            self._raise_status(result)
        if not access.value & 0x6:  # FILE_WRITE_DATA | FILE_APPEND_DATA
            # Metadata-only/read handles cannot modify data and FlushFileBuffers
            # rejects them. Metadata mutations use WRITE_THROUGH handles.
            return
        os.fsync(descriptor)

    def fchmod(self, descriptor: int, mode: int) -> None:
        # Map owner permissions to a private DACL. Group/world bits never widen
        # access to runtime artifacts; Windows has no POSIX uid/gid contract.
        if self._attributes(self._handle(descriptor)) & 0x400:
            raise ValidationFailure("artifact mode cannot target a reparse point")
        permissions = "RCWDWO"
        for bit, rights in ((0o400, "FR"), (0o200, "FW"), (0o100, "FX")):
            if mode & bit:
                permissions += rights
        security = self._security_descriptor(
            f"D:P(A;;{permissions};;;{self._user_sid})(A;;FA;;;SY)"
        )
        try:
            handle = self._reopen_handle(descriptor, 0x60080, flags=0x82200000)
        except BaseException:
            self._kernel.LocalFree(security)
            raise
        try:
            present, defaulted, dacl = ctypes.c_int(), ctypes.c_int(), ctypes.c_void_p()
            if not self._advapi.GetSecurityDescriptorDacl(
                security, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
            ) or not present.value or not dacl.value:
                raise ValidationFailure("cannot construct a private Windows artifact DACL")
            error = self._advapi.SetSecurityInfo(handle, 1, 0x80000004, None, None, dacl, None)
            if error:
                raise ctypes.WinError(error)
        finally:
            self._kernel.CloseHandle(handle)
            self._kernel.LocalFree(security)

    @contextmanager
    def scandir(self, descriptor: int):
        directory = self._reopen_directory(descriptor)
        try:
            yield self._entries(directory)
        finally:
            os.close(directory)

    def _entries(self, descriptor: int):
        buffer = ctypes.create_string_buffer(65536)
        restart = True
        while True:
            status_block = _IOStatusBlock()
            status = self._nt.NtQueryDirectoryFile(self._handle(descriptor), None, None, None,
                                                  ctypes.byref(status_block), buffer, len(buffer),
                                                  12, 0, None, int(restart))
            restart = False
            if status & 0xFFFFFFFF == 0x80000006:  # STATUS_NO_MORE_FILES
                return
            if status < 0:
                self._raise_status(status)
            length = status_block.Information
            if not length or length > len(buffer):
                raise ValidationFailure("Windows directory enumeration returned invalid data")
            for name in _decode_directory_names(buffer.raw[:length]):
                yield _DirectoryEntry(self, descriptor, name)

    def listdir(self, descriptor: int) -> list[str]:
        with self.scandir(descriptor) as entries:
            return [entry.name for entry in entries]


class _DirectoryEntry:
    def __init__(self, filesystem: WindowsFilesystem, directory_fd: int, name: str) -> None:
        self._filesystem = filesystem
        self._directory_fd = directory_fd
        self.name = name
        self.path = name  # Same as os.scandir(fd): it is relative to that fd.

    def stat(self, *, follow_symlinks=True):
        return self._filesystem.stat(self.name, dir_fd=self._directory_fd,
                                     follow_symlinks=follow_symlinks)

    def is_dir(self, *, follow_symlinks=True) -> bool:
        return stat.S_ISDIR(self.stat(follow_symlinks=follow_symlinks).st_mode)

    def is_file(self, *, follow_symlinks=True) -> bool:
        return stat.S_ISREG(self.stat(follow_symlinks=follow_symlinks).st_mode)

    def is_symlink(self) -> bool:
        return stat.S_ISLNK(self.stat(follow_symlinks=False).st_mode)

    def inode(self) -> int:
        return self.stat(follow_symlinks=False).st_ino
