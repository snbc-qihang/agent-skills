"""Windows LPAC execution with private ACLs, bounded pipes and a Job Object.

The Provider receives no network capabilities.  Opting out of All Application
Packages is mandatory: an ordinary AppContainer is not an equivalent boundary.
Python is copied to a private runtime; shared installations are never re-ACL'd.
The process remains suspended until the Job Object is assigned.  No helper
tools, administrator privileges, Docker or WSL are used.

API contract: learn.microsoft.com/windows/win32/secauthz/implementing-an-appcontainer
and learn.microsoft.com/windows/win32/api/jobapi2/nf-jobapi2-setinformationjobobject.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path


DWORD = ctypes.c_uint32
BOOL = ctypes.c_int32
HANDLE = ctypes.c_void_p
LPWSTR = ctypes.c_wchar_p
SIZE_T = ctypes.c_size_t


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("length", DWORD), ("descriptor", HANDLE), ("inherit", BOOL)]


class _SecurityCapabilities(ctypes.Structure):
    _fields_ = [("sid", HANDLE), ("capabilities", HANDLE), ("count", DWORD), ("reserved", DWORD)]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", DWORD), ("reserved", LPWSTR), ("desktop", LPWSTR), ("title", LPWSTR),
        ("x", DWORD), ("y", DWORD), ("width", DWORD), ("height", DWORD),
        ("x_chars", DWORD), ("y_chars", DWORD), ("fill", DWORD), ("flags", DWORD),
        ("show", ctypes.c_uint16), ("reserved_size", ctypes.c_uint16),
        ("reserved_bytes", HANDLE), ("stdin", HANDLE), ("stdout", HANDLE), ("stderr", HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("startup", _StartupInfo), ("attributes", HANDLE)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("process", HANDLE), ("thread", HANDLE), ("pid", DWORD), ("tid", DWORD)]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", DWORD),
        ("min_working_set", SIZE_T), ("max_working_set", SIZE_T), ("active_processes", DWORD),
        ("affinity", SIZE_T), ("priority", DWORD), ("scheduling", DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "read_operations", "write_operations", "other_operations",
        "read_bytes", "write_bytes", "other_bytes",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits), ("io", _IoCounters), ("process_memory", SIZE_T),
        ("job_memory", SIZE_T), ("peak_process_memory", SIZE_T), ("peak_job_memory", SIZE_T),
    ]


def capability() -> dict:
    if sys.platform != "win32":
        return {"supported": False, "backend": "windows-lpac", "reason": "not Windows"}
    version = sys.getwindowsversion()
    architecture = platform.machine().lower()
    supported = version.major >= 10 and version.build >= 22000 and architecture in {"amd64", "x86_64"}
    return {
        "supported": supported, "backend": "windows-lpac", "qualification": "execution_required",
        "reason": None if supported else "Windows 11 x64 is required for this LPAC adapter",
    }


class _Api:
    def __init__(self) -> None:
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.userenv = ctypes.WinDLL("userenv", use_last_error=True)
        signatures = {
            "CloseHandle": (BOOL, [HANDLE]),
            "LocalFree": (HANDLE, [HANDLE]),
            "GetCurrentProcess": (HANDLE, []),
            "CreatePipe": (BOOL, [ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE), ctypes.POINTER(_SecurityAttributes), DWORD]),
            "SetHandleInformation": (BOOL, [HANDLE, DWORD, DWORD]),
            "PeekNamedPipe": (BOOL, [HANDLE, HANDLE, DWORD, HANDLE, ctypes.POINTER(DWORD), HANDLE]),
            "ReadFile": (BOOL, [HANDLE, HANDLE, DWORD, ctypes.POINTER(DWORD), HANDLE]),
            "InitializeProcThreadAttributeList": (BOOL, [HANDLE, DWORD, DWORD, ctypes.POINTER(SIZE_T)]),
            "UpdateProcThreadAttribute": (BOOL, [HANDLE, DWORD, SIZE_T, HANDLE, SIZE_T, HANDLE, HANDLE]),
            "DeleteProcThreadAttributeList": (None, [HANDLE]),
            "CreateProcessW": (BOOL, [LPWSTR, LPWSTR, HANDLE, HANDLE, BOOL, DWORD, HANDLE, LPWSTR, ctypes.POINTER(_StartupInfoEx), ctypes.POINTER(_ProcessInfo)]),
            "CreateJobObjectW": (HANDLE, [HANDLE, LPWSTR]),
            "SetInformationJobObject": (BOOL, [HANDLE, ctypes.c_int, HANDLE, DWORD]),
            "AssignProcessToJobObject": (BOOL, [HANDLE, HANDLE]),
            "ResumeThread": (DWORD, [HANDLE]),
            "WaitForSingleObject": (DWORD, [HANDLE, DWORD]),
            "GetExitCodeProcess": (BOOL, [HANDLE, ctypes.POINTER(DWORD)]),
            "TerminateJobObject": (BOOL, [HANDLE, DWORD]),
            "TerminateProcess": (BOOL, [HANDLE, DWORD]),
            "CreateFileW": (HANDLE, [LPWSTR, DWORD, DWORD, ctypes.POINTER(_SecurityAttributes), DWORD, DWORD, HANDLE]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.kernel, name)
            function.restype = result
            function.argtypes = arguments
        for name, result, arguments in (
            ("OpenProcessToken", BOOL, [HANDLE, DWORD, ctypes.POINTER(HANDLE)]),
            ("GetTokenInformation", BOOL, [HANDLE, ctypes.c_int, HANDLE, DWORD, ctypes.POINTER(DWORD)]),
            ("ConvertSidToStringSidW", BOOL, [HANDLE, ctypes.POINTER(LPWSTR)]),
            ("ConvertStringSecurityDescriptorToSecurityDescriptorW", BOOL, [LPWSTR, DWORD, ctypes.POINTER(HANDLE), HANDLE]),
            ("GetSecurityDescriptorDacl", BOOL, [HANDLE, ctypes.POINTER(BOOL), ctypes.POINTER(HANDLE), ctypes.POINTER(BOOL)]),
            ("GetSecurityDescriptorSacl", BOOL, [HANDLE, ctypes.POINTER(BOOL), ctypes.POINTER(HANDLE), ctypes.POINTER(BOOL)]),
            ("SetNamedSecurityInfoW", DWORD, [LPWSTR, ctypes.c_int, DWORD, HANDLE, HANDLE, HANDLE, HANDLE]),
            ("FreeSid", HANDLE, [HANDLE]),
        ):
            function = getattr(self.advapi, name)
            function.restype = result
            function.argtypes = arguments
        for name, arguments in (
            ("CreateAppContainerProfile", [LPWSTR, LPWSTR, LPWSTR, HANDLE, DWORD, ctypes.POINTER(HANDLE)]),
            ("DeleteAppContainerProfile", [LPWSTR]),
            ("GetAppContainerFolderPath", [LPWSTR, ctypes.POINTER(LPWSTR)]),
        ):
            function = getattr(self.userenv, name)
            function.restype = ctypes.c_int32
            function.argtypes = arguments

    @staticmethod
    def check(result, operation: str):
        if not result:
            error = ctypes.get_last_error()
            raise OSError(error, f"Windows sandbox {operation} failed: {ctypes.FormatError(error)}")
        return result

    def close(self, handle) -> None:
        if handle and handle != ctypes.c_void_p(-1).value:
            self.kernel.CloseHandle(handle)

    def sid_text(self, sid) -> str:
        value = LPWSTR()
        self.check(self.advapi.ConvertSidToStringSidW(sid, ctypes.byref(value)), "SID conversion")
        try:
            return value.value
        finally:
            self.kernel.LocalFree(ctypes.cast(value, HANDLE))

    def owner_sid(self) -> str:
        token = HANDLE()
        self.check(self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, ctypes.byref(token)), "account token")
        try:
            size = DWORD()
            self.advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not size.value or size.value > 65536:
                raise OSError("Windows sandbox account token is invalid")
            buffer = ctypes.create_string_buffer(size.value)
            self.check(self.advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)), "account SID")
            return self.sid_text(ctypes.cast(buffer, ctypes.POINTER(HANDLE))[0])
        finally:
            self.close(token)

    def acl(self, path: Path, owner: str, sandbox: str | None, writable: bool = False) -> None:
        if _reparse(path):
            raise OSError("Windows sandbox ACL target is a reparse point")
        rights = "FA" if writable else "FRFX"
        grant = f"(A;OICI;{rights};;;{sandbox})" if sandbox else ""
        descriptor = HANDLE()
        # A protected DACL excludes ambient Users/All Application Packages ACEs.
        sddl = f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{owner}){grant}"
        if writable:
            # LPAC runs at Low integrity: an allow ACE alone cannot make a
            # Medium-integrity work directory writable under mandatory policy.
            sddl += "S:(ML;OICI;NW;;;LW)"
        self.check(self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None), "ACL construction")
        try:
            present, defaulted, dacl = BOOL(), BOOL(), HANDLE()
            self.check(self.advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)), "ACL extraction")
            sacl, flags = HANDLE(), 0x80000004
            if writable:
                self.check(self.advapi.GetSecurityDescriptorSacl(descriptor, ctypes.byref(present), ctypes.byref(sacl), ctypes.byref(defaulted)), "work integrity label")
                flags |= 0x10
            error = self.advapi.SetNamedSecurityInfoW(str(path), 1, flags, None, None, dacl, sacl)
            if error:
                raise OSError(error, f"Windows sandbox ACL assignment failed: {ctypes.FormatError(error)}")
        finally:
            self.kernel.LocalFree(descriptor)


def _reparse(path: Path) -> bool:
    metadata = path.lstat()
    return path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _private_runtime(destination: Path) -> Path:
    """Copy runtime leaves only, excluding third-party packages and user code."""
    source = Path(sys.base_prefix).resolve()
    executable = source / "python.exe"
    if not executable.is_file() or _reparse(executable):
        raise OSError("Windows sandbox needs a direct base Python runtime")
    destination.mkdir()
    candidates = [executable]
    candidates.extend(sorted(source.glob("python*.dll")))
    candidates.extend(sorted(source.glob("vcruntime*.dll")))
    candidates.extend(sorted(source.glob("python*.zip")))
    candidates.extend(path for path in (source / "Lib", source / "DLLs") if path.exists())
    total = count = 0

    def copy(path: Path) -> None:
        nonlocal total, count
        if path.name in {"site-packages", "__pycache__"}:
            return
        metadata = path.lstat()
        if _reparse(path):
            raise OSError("Windows sandbox runtime contains a reparse point")
        count += 1
        if count > 20000:
            raise OSError("Windows sandbox runtime exceeds the entry limit")
        target = destination / path.relative_to(source)
        if stat.S_ISDIR(metadata.st_mode):
            target.mkdir()
            for child in path.iterdir():
                copy(child)
        elif stat.S_ISREG(metadata.st_mode):
            total += metadata.st_size
            if total > 256 * 1024 * 1024:
                raise OSError("Windows sandbox runtime exceeds the size limit")
            shutil.copyfile(path, target, follow_symlinks=False)
        else:
            raise OSError("Windows sandbox runtime contains a special file")

    for candidate in candidates:
        copy(candidate)
    return destination / "python.exe"


def _secure_tree(api: _Api, root: Path, owner: str, sandbox: str | None, writable: bool) -> None:
    api.acl(root, owner, sandbox, writable)
    for directory, names, files in os.walk(root, followlinks=False):
        for name in names + files:
            api.acl(Path(directory) / name, owner, sandbox, writable)


def run(
    command: list[str], bundle: Path, work: Path, environment: dict[str, str],
    timeout: int, output_limit: int,
) -> tuple[int, bytes, bytes]:
    """Execute with complete LPAC attributes or fail without running Provider."""
    available = capability()
    if not available["supported"]:
        raise OSError(available["reason"])
    api = _Api()
    name = "engineering-assistant-provider-" + uuid.uuid4().hex
    sid = HANDLE()
    profile_created = False
    handles = []
    process = _ProcessInfo()
    attributes = None
    attributes_initialized = False
    job = None
    job_assigned = False
    try:
        result = api.userenv.CreateAppContainerProfile(name, name, "Isolated Provider", None, 0, ctypes.byref(sid))
        if result < 0:
            raise OSError(f"Windows LPAC profile creation failed: HRESULT {result & 0xFFFFFFFF:08x}")
        profile_created = True
        sandbox, owner = api.sid_text(sid), api.owner_sid()
        # LPAC's otherwise-writable profile folder is outside the approved work
        # directory. Remove its package grant before starting any untrusted code.
        profile_folder = LPWSTR()
        result = api.userenv.GetAppContainerFolderPath(sandbox, ctypes.byref(profile_folder))
        if result < 0 or not profile_folder.value:
            raise OSError("Windows LPAC profile folder could not be isolated")
        try:
            _secure_tree(api, Path(profile_folder.value), owner, None, False)
        finally:
            # GetAppContainerFolderPath allocates with CoTaskMemAlloc.
            ole = ctypes.WinDLL("ole32", use_last_error=True)
            ole.CoTaskMemFree.argtypes = [HANDLE]
            ole.CoTaskMemFree(ctypes.cast(profile_folder, HANDLE))
        runtime = work.parent / "runtime"
        executable = _private_runtime(runtime)
        _secure_tree(api, runtime, owner, sandbox, False)
        _secure_tree(api, bundle, owner, sandbox, False)
        _secure_tree(api, work, owner, sandbox, True)
        actual_command = [str(executable), *command[1:]]
        security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
        readers, writers = [], []
        for _ in range(2):
            reader, writer = HANDLE(), HANDLE()
            api.check(api.kernel.CreatePipe(ctypes.byref(reader), ctypes.byref(writer), ctypes.byref(security), 4096), "output pipe")
            handles.extend([reader.value, writer.value])
            api.check(api.kernel.SetHandleInformation(reader, 1, 0), "pipe inheritance")
            readers.append(reader.value)
            writers.append(writer.value)
        stdin = api.kernel.CreateFileW("NUL", 0x80000000, 3, ctypes.byref(security), 3, 0, None)
        if stdin == ctypes.c_void_p(-1).value:
            raise OSError("Windows sandbox null stdin creation failed")
        handles.append(stdin)

        length = SIZE_T()
        api.kernel.InitializeProcThreadAttributeList(None, 4, 0, ctypes.byref(length))
        if not length.value:
            raise OSError("Windows LPAC process attributes are unavailable")
        buffer = ctypes.create_string_buffer(length.value)
        attributes = ctypes.cast(buffer, HANDLE)
        api.check(api.kernel.InitializeProcThreadAttributeList(attributes, 4, 0, ctypes.byref(length)), "process attributes")
        attributes_initialized = True
        capabilities = _SecurityCapabilities(sid, None, 0, 0)
        opt_out, children = DWORD(1), DWORD(1)
        inherited = (HANDLE * 3)(stdin, *writers)
        for attribute, value in (
            (0x20009, capabilities),  # SECURITY_CAPABILITIES, no network capabilities
            (0x2000F, opt_out),       # ALL_APPLICATION_PACKAGES_POLICY -> LPAC
            (0x2000E, children),      # CHILD_PROCESS_POLICY -> restricted
            (0x20002, inherited),     # HANDLE_LIST -> exactly stdin/stdout/stderr
        ):
            api.check(api.kernel.UpdateProcThreadAttribute(attributes, 0, attribute, ctypes.byref(value), ctypes.sizeof(value), None, None), "required process attribute")
        startup = _StartupInfoEx()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.startup.flags = 0x100
        startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = stdin, *writers
        startup.attributes = attributes
        environment_block = ctypes.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in sorted(environment.items())) + "\0\0")
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(actual_command))
        flags = 0x80000 | 0x400 | 0x4 | 0x08000000
        api.check(api.kernel.CreateProcessW(str(executable), command_line, None, None, True, flags, environment_block, str(work), ctypes.byref(startup), ctypes.byref(process)), "LPAC process creation")
        handles.extend([process.process, process.thread])

        job = api.kernel.CreateJobObjectW(None, None)
        api.check(job, "Job Object creation")
        handles.append(job)
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000 | 0x8 | 0x100 | 0x2
        limits.basic.active_processes = 1
        limits.basic.process_time = int(timeout + 1) * 10000000
        limits.process_memory = 512 * 1024 * 1024
        api.check(api.kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)), "Job limits")
        api.check(api.kernel.AssignProcessToJobObject(job, process.process), "Job assignment")
        job_assigned = True
        if api.kernel.ResumeThread(process.thread) == 0xFFFFFFFF:
            raise OSError("Windows LPAC process could not be resumed")
        # Parent writers must close so a terminated child yields pipe EOF.
        for writer in writers:
            api.close(writer)
            handles.remove(writer)
        streams = [bytearray(), bytearray()]
        deadline = time.monotonic() + timeout
        while True:
            for reader, stream in zip(readers, streams):
                while True:
                    available_bytes = DWORD()
                    if not api.kernel.PeekNamedPipe(reader, None, 0, None, ctypes.byref(available_bytes), None):
                        if ctypes.get_last_error() == 109:
                            break
                        api.check(False, "pipe query")
                    if not available_bytes.value:
                        break
                    remaining = output_limit + 1 - sum(len(item) for item in streams)
                    chunk = ctypes.create_string_buffer(min(available_bytes.value, remaining, 65536))
                    consumed = DWORD()
                    api.check(api.kernel.ReadFile(reader, chunk, len(chunk), ctypes.byref(consumed), None), "bounded output read")
                    stream.extend(chunk.raw[:consumed.value])
                    if sum(len(item) for item in streams) > output_limit:
                        raise OSError("provider output exceeds the configured limit")
            state = api.kernel.WaitForSingleObject(process.process, 0)
            if state == 0:
                # A final pass drains bytes buffered immediately before exit.
                if all(not _pipe_available(api, reader) for reader in readers):
                    break
            elif state != 258:
                api.check(False, "process wait")
            if time.monotonic() >= deadline:
                raise OSError("provider execution timed out")
            time.sleep(0.01)
        exit_code = DWORD()
        api.check(api.kernel.GetExitCodeProcess(process.process, ctypes.byref(exit_code)), "exit status")
        return exit_code.value, bytes(streams[0]), bytes(streams[1])
    finally:
        cleanup_error = None
        if process.process:
            try:
                _terminate_process(api, process.process, job, job_assigned)
            except OSError as exc:
                cleanup_error = exc
        if attributes_initialized:
            api.kernel.DeleteProcThreadAttributeList(attributes)
        for handle in reversed(handles):
            api.close(handle)
        if sid:
            api.advapi.FreeSid(sid)
        if profile_created:
            result = api.userenv.DeleteAppContainerProfile(name)
            if result < 0:
                cleanup_error = OSError(f"Windows LPAC profile cleanup failed: HRESULT {result & 0xFFFFFFFF:08x}")
        if cleanup_error:
            raise cleanup_error


def _terminate_process(api: _Api, process, job, job_assigned: bool) -> None:
    if job_assigned:
        api.kernel.TerminateJobObject(job, 1)
    # Job creation does not mean assignment succeeded. Always terminate the
    # process as a fallback, including a suspended, unassigned child. Resource
    # cleanup in run() still proceeds if OS termination cannot be confirmed.
    api.kernel.TerminateProcess(process, 1)
    if api.kernel.WaitForSingleObject(process, 5000) != 0:
        raise OSError("Windows LPAC process cleanup could not confirm exit")


def _pipe_available(api: _Api, reader) -> bool:
    size = DWORD()
    if api.kernel.PeekNamedPipe(reader, None, 0, None, ctypes.byref(size), None):
        return bool(size.value)
    if ctypes.get_last_error() == 109:
        return False
    api.check(False, "pipe drain")
    return False
