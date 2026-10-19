"""A fail-closed Linux Provider boundary, installed before untrusted code.

Landlock ABI 3 is mandatory: ABI 1/2 cannot deny truncation.  A seccomp
allowlist denies all networking, process creation, additional exec, privilege
changes, ptrace, io_uring and other interfaces which can bypass path mediation.
No external sandbox executable or user namespaces are required.

References: docs.kernel.org/userspace-api/landlock.html and
docs.kernel.org/userspace-api/seccomp_filter.html.
"""

from __future__ import annotations

import ctypes
import errno
import os
import platform
import stat
import sys
import sysconfig
from pathlib import Path


class SandboxUnavailable(OSError):
    """The OS cannot enforce the complete Provider contract."""


class _Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class _Filter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_uint16), ("jt", ctypes.c_uint8),
        ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32),
    ]


class _Program(ctypes.Structure):
    _fields_ = [("len", ctypes.c_uint16), ("filter", ctypes.POINTER(_Filter))]


# Native syscall numbers from Linux asm/unistd.h.  Other architectures are
# explicitly unsupported; never infer numbers from a similar architecture.
_ARCHITECTURES = {
    "x86_64": {
        "audit_arch": 0xC000003E, "seccomp": 317,
        "allowed": {
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
            17, 18, 19, 20, 21, 24, 25, 28, 32, 33, 35, 39,
            60, 63, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81,
            82, 83, 84, 87, 89, 95, 96, 97, 98, 99, 100, 102,
            104, 107, 108, 110, 131, 137, 138, 186, 201, 202, 204,
            217, 218, 219, 228, 229, 230, 231, 257, 258, 262, 263,
            264, 267, 269, 273, 292, 295, 296, 318, 326, 327, 332,
            334, 436, 437, 439,
        },
    },
    "aarch64": {
        "audit_arch": 0xC00000B7, "seccomp": 277,
        "allowed": {
            17, 23, 24, 25, 32, 34, 35, 38, 43, 44, 45, 46, 48,
            49, 50, 56, 57, 61, 62, 63, 64, 65, 66, 67, 68, 69,
            70, 72, 73, 78, 79, 80, 82, 83, 93, 94, 96, 98, 99,
            101, 113, 114, 115, 123, 124, 128, 132, 134, 135, 136,
            139, 153, 160, 163, 165, 166, 168, 169, 172, 173,
            174, 175, 176, 177, 178, 179, 214, 215, 216, 222,
            226, 233, 278, 285, 286, 291, 293, 436, 437, 439,
        },
    },
}

_LANDLOCK_CREATE = 444
_LANDLOCK_ADD = 445
_LANDLOCK_RESTRICT = 446
_FS_READ = (1 << 2) | (1 << 3)
_FS_WORK = _FS_READ | (1 << 1) | (1 << 4) | (1 << 5) | (1 << 7) | (1 << 8) | (1 << 13) | (1 << 14)


def _libc():
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    library.prctl.restype = ctypes.c_int
    return library


def _checked(result: int, operation: str) -> int:
    if result < 0:
        error = ctypes.get_errno()
        raise SandboxUnavailable(error, f"Linux sandbox {operation}: {os.strerror(error)}")
    return result


def capability() -> dict:
    """Read capability without restricting the calling host process."""
    if sys.platform != "linux":
        return {"supported": False, "backend": "landlock-seccomp", "reason": "not Linux"}
    architecture = platform.machine().lower()
    if architecture not in _ARCHITECTURES:
        return {"supported": False, "backend": "landlock-seccomp", "reason": f"unsupported architecture {architecture}"}
    try:
        abi = _checked(_libc().syscall(_LANDLOCK_CREATE, 0, 0, 1), "ABI query")
    except OSError as exc:
        return {"supported": False, "backend": "landlock-seccomp", "reason": str(exc)}
    return {
        "supported": abi >= 3,
        "backend": "landlock-seccomp",
        "landlock_abi": abi,
        "reason": None if abi >= 3 else "Landlock ABI 3 or later is required",
        "qualification": "execution_required",
    }


def _runtime_reads() -> list[tuple[Path, int]]:
    """Grant runtime leaves, never a generic prefix such as /usr or HOME."""
    grants = [(Path(sys.executable).resolve(), 1 << 2)]
    seen = set()
    for name in ("stdlib", "platstdlib"):
        value = sysconfig.get_path(name)
        if value:
            root = Path(value).resolve()
            if root in seen or not root.is_dir():
                continue
            seen.add(root)
            grants.append((root, 1 << 3))
            for child in root.iterdir():
                if child.name not in {"site-packages", "dist-packages"} and not child.is_symlink():
                    grants.append((child, _FS_READ if child.is_dir() else 1 << 2))
    # Loaded native libraries are pinned by file, not by their parent directory.
    with open("/proc/self/maps", encoding="utf-8") as maps:
        for line in maps:
            parts = line.rstrip().split(None, 5)
            if len(parts) == 6 and parts[5].startswith("/"):
                path = Path(parts[5])
                if path.is_file():
                    grants.append((path.resolve(), 1 << 2))
    return grants


def restrict(bundle: str, work: str) -> None:
    """Install both boundaries; failure exits before loading Provider code."""
    available = capability()
    if not available["supported"]:
        raise SandboxUnavailable(errno.ENOTSUP, available["reason"])
    libc = _libc()
    if len(os.listdir("/proc/self/task")) != 1:
        raise SandboxUnavailable(errno.ENOTSUP, "Linux sandbox requires a single-threaded trusted bootstrap")
    # All ABI-3 filesystem rights are handled, with newer IOCTL mediation when
    # available.  Network is denied independently by seccomp on every ABI.
    handled = (1 << 15) - 1
    if available["landlock_abi"] >= 5:
        handled |= 1 << 15
    ruleset = _Ruleset(handled)
    ruleset_fd = _checked(
        libc.syscall(_LANDLOCK_CREATE, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0),
        "ruleset creation",
    )
    try:
        grants = _runtime_reads()
        grants.extend([(Path(bundle).resolve(), _FS_READ), (Path(work).resolve(), _FS_WORK)])
        for path, access in grants:
            descriptor = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    access &= (1 << 2)
                rule = _PathRule(access, descriptor)
                _checked(libc.syscall(_LANDLOCK_ADD, ruleset_fd, 1, ctypes.byref(rule), 0), "path rule")
            finally:
                os.close(descriptor)
        _checked(libc.prctl(38, 1, 0, 0, 0), "no_new_privs")
        _checked(libc.syscall(_LANDLOCK_RESTRICT, ruleset_fd, 0), "filesystem restriction")
    finally:
        os.close(ruleset_fd)
    _restrict_syscalls(libc, platform.machine().lower())


def _filter_instructions(architecture: str) -> list[tuple[int, int, int, int]]:
    spec = _ARCHITECTURES[architecture]
    instructions = [
        (0x20, 0, 0, 4),  # load seccomp_data.arch
        (0x15, 1, 0, spec["audit_arch"]),
        (0x06, 0, 0, 0x80000000),  # kill mismatched ABI, including i386
        (0x20, 0, 0, 0),  # load seccomp_data.nr
    ]
    for number in sorted(spec["allowed"]):
        instructions.extend([(0x15, 0, 1, number), (0x06, 0, 0, 0x7FFF0000)])
    instructions.append((0x06, 0, 0, 0x00050000 | errno.EPERM))
    return instructions


def _restrict_syscalls(libc, architecture: str) -> None:
    filters = _filter_instructions(architecture)
    array = (_Filter * len(filters))(*[_Filter(*entry) for entry in filters])
    program = _Program(len(filters), array)
    # TSYNC makes an unexpected pre-existing thread a hard error, rather than
    # silently leaving a thread outside the syscall filter.
    result = libc.syscall(_ARCHITECTURES[architecture]["seccomp"], 1, 1, ctypes.byref(program))
    if result != 0:
        error = ctypes.get_errno() if result < 0 else errno.EBUSY
        raise SandboxUnavailable(error, "Linux sandbox seccomp enforcement failed")
