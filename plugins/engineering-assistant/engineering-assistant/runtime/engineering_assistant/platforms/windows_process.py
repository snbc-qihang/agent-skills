"""Bounded Windows child execution with a Job Object assigned before resume.

This is a lifecycle boundary, not a privilege sandbox. Descendants are permitted
for uv/Python, and are killed when the operation closes its Job Object.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Mapping


DWORD = ctypes.c_uint32
BOOL = ctypes.c_int32
HANDLE = ctypes.c_void_p
LPWSTR = ctypes.c_wchar_p
SIZE_T = ctypes.c_size_t


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("length", DWORD), ("descriptor", HANDLE), ("inherit", BOOL)]


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


class _Api:
    def __init__(self) -> None:
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CloseHandle": (BOOL, [HANDLE]),
            "GetCurrentProcess": (HANDLE, []),
            "DuplicateHandle": (BOOL, [HANDLE, HANDLE, HANDLE, ctypes.POINTER(HANDLE), DWORD, BOOL, DWORD]),
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

    @staticmethod
    def check(result, operation: str):
        if not result:
            error = ctypes.get_last_error()
            raise OSError(error, f"Windows process {operation} failed: {ctypes.FormatError(error)}")
        return result

    def close(self, handle) -> None:
        if handle and handle != ctypes.c_void_p(-1).value:
            self.check(self.kernel.CloseHandle(handle), "handle close")


def run_bounded_windows(
    command: list[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    output_limit_bytes: int,
    input_data: bytes | None = None,
    input_limit_bytes: int = 1_048_576,
) -> tuple[int, bytes]:
    """Execute an absolute command, bounding output and cleaning up its entire tree."""
    if sys.platform != "win32":
        raise OSError("Windows bounded process execution requires native Windows")
    if not command or not Path(command[0]).is_absolute():
        raise ValueError("Windows bounded process execution requires an absolute executable")
    if input_data is not None and (not isinstance(input_data, bytes) or len(input_data) > input_limit_bytes):
        raise ValueError("Windows process input exceeds its bounded bytes contract")
    if timeout_seconds <= 0 or output_limit_bytes <= 0 or input_limit_bytes <= 0:
        raise ValueError("process timeout and output limit must be positive")
    api = _Api()
    handles = []
    process = _ProcessInfo()
    attributes = None
    initialized = False
    job_assigned = False
    job = None
    input_file = None
    try:
        security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
        reader, writer = HANDLE(), HANDLE()
        api.check(api.kernel.CreatePipe(ctypes.byref(reader), ctypes.byref(writer), ctypes.byref(security), 0), "pipe creation")
        handles.extend([reader.value, writer.value])
        api.check(api.kernel.SetHandleInformation(reader, 1, 0), "pipe inheritance")
        if input_data is None:
            stdin = api.kernel.CreateFileW("NUL", 0x80000000, 3, ctypes.byref(security), 3, 0, None)
            if stdin == ctypes.c_void_p(-1).value:
                raise OSError("Windows process null stdin creation failed")
        else:
            import msvcrt

            # A bounded one-shot request need not use a blocking pipe writer.
            # Duplicate a read-only handle to a private delete-on-close file;
            # stdin reaches EOF after the supplied bytes without another thread.
            input_file = tempfile.TemporaryFile(mode="w+b")
            input_file.write(input_data)
            input_file.flush()
            input_file.seek(0)
            duplicated = HANDLE()
            current = api.kernel.GetCurrentProcess()
            api.check(api.kernel.DuplicateHandle(
                current, msvcrt.get_osfhandle(input_file.fileno()), current,
                ctypes.byref(duplicated), 0x120089, True, 0,
            ), "read-only stdin handle")
            stdin = duplicated.value
        handles.append(stdin)

        length = SIZE_T()
        api.kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(length))
        if not length.value:
            raise OSError("Windows process handle attributes are unavailable")
        buffer = ctypes.create_string_buffer(length.value)
        attributes = ctypes.cast(buffer, HANDLE)
        api.check(api.kernel.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(length)), "attribute initialization")
        initialized = True
        inherited = (HANDLE * 2)(stdin, writer.value)
        api.check(api.kernel.UpdateProcThreadAttribute(attributes, 0, 0x20002, ctypes.byref(inherited), ctypes.sizeof(inherited), None, None), "inherited handle list")
        startup = _StartupInfoEx()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.startup.flags = 0x100
        startup.startup.stdin = stdin
        startup.startup.stdout = startup.startup.stderr = writer.value
        startup.attributes = attributes
        environment_block = ctypes.create_unicode_buffer(
            "\0".join(f"{key}={value}" for key, value in sorted(environment.items())) + "\0\0"
        )
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        # Child code cannot run or spawn descendants before Job assignment.
        flags = 0x80000 | 0x400 | 0x4 | 0x08000000
        api.check(api.kernel.CreateProcessW(str(command[0]), command_line, None, None, True, flags, environment_block, str(cwd), ctypes.byref(startup), ctypes.byref(process)), "suspended creation")
        handles.extend([process.process, process.thread])
        job = api.kernel.CreateJobObjectW(None, None)
        api.check(job, "Job Object creation")
        handles.append(job)
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        api.check(api.kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)), "Job limits")
        api.check(api.kernel.AssignProcessToJobObject(job, process.process), "Job assignment")
        job_assigned = True
        if api.kernel.ResumeThread(process.thread) == 0xFFFFFFFF:
            raise OSError("Windows process could not be resumed")
        api.close(writer.value)
        handles.remove(writer.value)
        captured = bytearray()
        deadline = time.monotonic() + timeout_seconds
        exited = False
        while True:
            while True:
                available = DWORD()
                if not api.kernel.PeekNamedPipe(reader, None, 0, None, ctypes.byref(available), None):
                    if ctypes.get_last_error() == 109:  # ERROR_BROKEN_PIPE
                        break
                    api.check(False, "pipe query")
                if not available.value:
                    break
                remaining = output_limit_bytes + 1 - len(captured)
                chunk = ctypes.create_string_buffer(min(available.value, remaining, 8192))
                consumed = DWORD()
                api.check(api.kernel.ReadFile(reader, chunk, len(chunk), ctypes.byref(consumed), None), "output read")
                captured.extend(chunk.raw[:consumed.value])
                if len(captured) > output_limit_bytes:
                    raise OSError("Windows process exceeded the bounded output limit")
            state = api.kernel.WaitForSingleObject(process.process, 0)
            if state == 0 and not exited:
                exited = True
                continue  # Drain bytes buffered immediately before process exit.
            if state == 0:
                exit_code = DWORD()
                api.check(api.kernel.GetExitCodeProcess(process.process, ctypes.byref(exit_code)), "exit status")
                return int(exit_code.value), bytes(captured)
            if state != 258:  # WAIT_TIMEOUT
                api.check(False, "process wait")
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout_seconds, output=bytes(captured))
            time.sleep(min(0.01, max(deadline - time.monotonic(), 0)))
    finally:
        if process.process:
            if job_assigned:
                api.kernel.TerminateJobObject(job, 1)
            # On any failure before assignment, terminate the suspended process.
            api.kernel.TerminateProcess(process.process, 1)
            api.kernel.WaitForSingleObject(process.process, 5000)
        if initialized:
            api.kernel.DeleteProcThreadAttributeList(attributes)
        for handle in reversed(handles):
            api.close(handle)
        if input_file is not None:
            input_file.close()
