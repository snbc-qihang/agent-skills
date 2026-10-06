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
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
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


class _GenericMapping(ctypes.Structure):
    _fields_ = [(name, DWORD) for name in ("read", "write", "execute", "all")]


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


def _environment_block(environment: dict[str, str], work: Path):
    """Supply LPAC's required option without granting a host AppData path."""
    allowed = {"SYSTEMROOT", "WINDIR", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE", "LANG"}
    values = {}
    for key, value in environment.items():
        if not key or "=" in key or "\0" in key or "\0" in value:
            raise OSError("invalid Windows sandbox environment entry")
        if key.upper() in allowed:
            values[key.upper()] = value
    # CreateProcessW constructs AppContainer's environment using LOCALAPPDATA.
    # Omitting it fails before Python starts with ERROR_ENVVAR_NOT_FOUND (203).
    # Windows can redirect these options to its profile during creation; the
    # trusted bootstrap restores the approved work paths before Provider code.
    values.update({key: str(work) for key in (
        "LOCALAPPDATA", "APPDATA", "USERPROFILE", "TEMP", "TMP", "TMPDIR",
    )})
    if "\0" in str(work):
        raise OSError("invalid Windows sandbox environment work path")
    entries = (f"{key}={value}" for key, value in sorted(values.items()))
    return ctypes.create_unicode_buffer("\0".join(entries) + "\0\0")


def run(
    command: list[str], bundle: Path, work: Path, environment: dict[str, str],
    timeout: int, output_limit: int, *, diagnostics: dict | None = None,
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
        if diagnostics is not None:
            diagnostics["stage"] = "private_runtime_and_acl"
            preparation_started = time.monotonic()
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
        if diagnostics is not None:
            diagnostics["preparation_seconds"] = round(time.monotonic() - preparation_started, 3)
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
        environment_block = _environment_block(environment, work)
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(actual_command))
        flags = 0x80000 | 0x400 | 0x4 | 0x08000000
        if diagnostics is not None:
            diagnostics["stage"] = "create_lpac_process"
        api.check(api.kernel.CreateProcessW(str(executable), command_line, None, None, True, flags, environment_block, str(work), ctypes.byref(startup), ctypes.byref(process)), "LPAC process creation")
        handles.extend([process.process, process.thread])
        if diagnostics is not None:
            diagnostics["stage"] = "suspended_lpac_access"
            try:
                diagnostics["access"] = _startup_access(api, process.process, runtime, bundle, work)
            except OSError as exc:
                # Diagnostic collection never changes attributes, ACLs or Job
                # enforcement. An unavailable observation is reported as such.
                diagnostics["access_error"] = {"type": type(exc).__name__, "code": exc.errno}

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
        if diagnostics is not None:
            diagnostics["stage"] = "resume_lpac_process"
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
        if diagnostics is not None:
            diagnostics["stage"] = "process_exited"
            diagnostics["exit_code"] = f"0x{exit_code.value:08X}"
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


def _access_mask(api: _Api, descriptor, token, mapping: tuple[int, int, int, int]) -> dict:
    privileges = ctypes.create_string_buffer(4096)
    length, granted, allowed = DWORD(len(privileges)), DWORD(), BOOL()
    generic = _GenericMapping(*mapping)
    api.check(api.advapi.AccessCheck(descriptor, token, 0x02000000, ctypes.byref(generic),
                                    privileges, ctypes.byref(length), ctypes.byref(granted),
                                    ctypes.byref(allowed)), "diagnostic access check")
    return {"allowed": bool(allowed.value), "mask": f"0x{granted.value:08x}"}


def _startup_access(api: _Api, process, runtime: Path, bundle: Path, work: Path) -> dict:
    """Read-only observations of the suspended process; never grants access."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    signatures = (
        (api.advapi, "DuplicateToken", BOOL, [HANDLE, ctypes.c_int, ctypes.POINTER(HANDLE)]),
        (api.advapi, "AccessCheck", BOOL, [HANDLE, HANDLE, DWORD, ctypes.POINTER(_GenericMapping), HANDLE,
                                         ctypes.POINTER(DWORD), ctypes.POINTER(DWORD), ctypes.POINTER(BOOL)]),
        (api.advapi, "GetFileSecurityW", BOOL, [LPWSTR, DWORD, HANDLE, DWORD, ctypes.POINTER(DWORD)]),
        (api.kernel, "GetCurrentThreadId", DWORD, []),
        (user, "GetProcessWindowStation", HANDLE, []),
        (user, "GetThreadDesktop", HANDLE, [DWORD]),
        (user, "GetUserObjectSecurity", BOOL, [HANDLE, ctypes.POINTER(DWORD), HANDLE, DWORD, ctypes.POINTER(DWORD)]),
    )
    for library, name, result, arguments in signatures:
        function = getattr(library, name)
        function.restype, function.argtypes = result, arguments
    token, impersonation = HANDLE(), HANDLE()
    api.check(api.advapi.OpenProcessToken(process, 0x0A, ctypes.byref(token)), "diagnostic process token")
    try:
        api.check(api.advapi.DuplicateToken(token, 2, ctypes.byref(impersonation)), "diagnostic impersonation token")
        observations = {}
        for name, information_class in (("appcontainer", 29), ("lpac", 46)):
            value, length = DWORD(), DWORD()
            try:
                api.check(api.advapi.GetTokenInformation(token, information_class, ctypes.byref(value),
                                                         ctypes.sizeof(value), ctypes.byref(length)), "diagnostic token flag")
                observations[name] = bool(value.value)
            except OSError as exc:
                # Some Windows builds reject information class 46. Preserve
                # that observation as unavailable and still inspect objects;
                # absence of a query result cannot assert LPAC false or true.
                observations[name] = {"error": exc.errno}

        def read_access(reader, mapping):
            try:
                length = DWORD()
                reader(None, 0, ctypes.byref(length))
                if not length.value or length.value > 65536:
                    raise OSError("Windows startup diagnostic security descriptor size is invalid")
                descriptor = ctypes.create_string_buffer(length.value)
                api.check(reader(descriptor, len(descriptor), ctypes.byref(length)), "diagnostic security descriptor")
                return _access_mask(api, descriptor, impersonation, mapping)
            except OSError as exc:
                return {"error": exc.errno}

        # STARTUPINFO.lpDesktop is null: Windows uses the parent's station and
        # desktop. Borrowed parent handles must not be closed here. Read owner,
        # group and DACL (7); AccessCheck requires owner and group as well.
        for name, handle, mapping in (
            ("default_window_station", user.GetProcessWindowStation(), (0x20303, 0x2001C, 0x20060, 0xF037F)),
            ("default_desktop", user.GetThreadDesktop(api.kernel.GetCurrentThreadId()), (0x20041, 0x200BE, 0x20100, 0xF01FF)),
        ):
            information = DWORD(7)
            observations[name] = read_access(
                lambda buffer, size, length: user.GetUserObjectSecurity(handle, ctypes.byref(information), buffer, size, length), mapping)
        for name, path in (("runtime", runtime), ("runtime_executable", runtime / "python.exe"),
                           ("bundle", bundle), ("work", work), ("private_parent", work.parent)):
            observations[name] = read_access(
                lambda buffer, size, length: api.advapi.GetFileSecurityW(str(path), 7, buffer, size, length),
                (0x120089, 0x120116, 0x1200A0, 0x1F01FF))
        return observations
    finally:
        api.close(impersonation)
        api.close(token)


def diagnose() -> dict:
    """Bounded fixed-code startup experiment, explicitly not qualification."""
    available = capability()
    report = {**available, "qualified": False, "assurance": "startup_diagnostic_only"}
    if not available["supported"]:
        return report
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="ea-windows-startup-") as temporary:
            base = Path(temporary).resolve()
            api = _Api()
            api.acl(base, api.owner_sid(), None, False)
            work, bundle = base / "work", base / "bundle"
            work.mkdir()
            bundle.mkdir()
            environment = {name: value for name, value in os.environ.items()
                           if name.upper() in {"SYSTEMROOT", "WINDIR"}}
            block = _environment_block(environment, work)
            private_environment = dict(entry.split("=", 1) for entry in block[:].rstrip("\0").split("\0"))
            command = ["python.exe", "-I", "-B", "-S", "-c", "print('EA_LPAC_STARTUP_OK',flush=True)"]
            copy_started = time.monotonic()
            executable = _private_runtime(base / "baseline-runtime")
            report["baseline_copy_seconds"] = round(time.monotonic() - copy_started, 3)
            baseline = subprocess.run([str(executable), *command[1:]], cwd=work, env=private_environment,
                                      stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False)
            report["copied_runtime_baseline"] = {"exit_code": f"0x{baseline.returncode & 0xFFFFFFFF:08X}",
                                                "marker": baseline.stdout.strip() == b"EA_LPAC_STARTUP_OK"}
            strict = {}
            report["strict_lpac"] = strict
            code, output, _ = run(command, bundle, work, environment, 10, 4096, diagnostics=strict)
            strict["marker"] = code == 0 and output.strip() == b"EA_LPAC_STARTUP_OK"
    except (OSError, subprocess.SubprocessError) as exc:
        report["diagnostic_error"] = {"type": type(exc).__name__, "code": getattr(exc, "errno", None)}
    report["total_seconds"] = round(time.monotonic() - started, 3)
    return report


if __name__ == "__main__":
    if sys.argv[1:] != ["--diagnose"]:
        raise SystemExit("use --diagnose for the fixed Windows startup experiment")
    result = diagnose()
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result.get("strict_lpac", {}).get("marker") else 1)
