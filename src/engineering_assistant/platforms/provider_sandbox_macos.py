"""Apply Seatbelt after trusted Python startup, before loading Provider code.

Wrapping an interpreter in sandbox-exec needs an initial process-exec grant;
that same grant permits hostile code to exec the interpreter again.  Applying
the profile in the trusted bootstrap avoids any process-exec exception.  A
missing/deprecated API fails closed, never runs the Provider without Seatbelt.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path


def _library():
    library = ctypes.CDLL("/usr/lib/libsandbox.1.dylib", use_errno=True)
    library.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
    library.sandbox_init.restype = ctypes.c_int
    library.sandbox_free_error.argtypes = [ctypes.c_char_p]
    library.sandbox_free_error.restype = None
    return library


def capability() -> dict:
    if sys.platform != "darwin":
        return {"supported": False, "backend": "darwin-seatbelt", "reason": "not macOS"}
    try:
        _library()
    except (OSError, AttributeError) as exc:
        return {"supported": False, "backend": "darwin-seatbelt", "reason": str(exc)}
    return {
        "supported": True, "backend": "darwin-seatbelt",
        "qualification": "execution_required", "reason": None,
    }


def profile(runtime: str, bundle: str, work: str) -> str:
    def escaped(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    return (
        '(version 1)(deny default)(import "system.sb")'
        '(deny network*)(deny file-write*)(deny process-fork)(deny process-exec)'
        f'(allow file-read* (subpath "{escaped(runtime)}"))'
        f'(allow file-read* (subpath "{escaped(bundle)}"))'
        f'(allow file-read* (subpath "{escaped(work)}"))'
        f'(allow file-write* (subpath "{escaped(work)}"))'
    )


def restrict(runtime: str, bundle: str, work: str) -> None:
    library = _library()
    error = ctypes.c_char_p()
    result = library.sandbox_init(profile(runtime, bundle, work).encode("utf-8"), 0, ctypes.byref(error))
    if result != 0:
        try:
            description = error.value.decode("utf-8", "replace") if error.value else "unknown error"
        finally:
            if error:
                library.sandbox_free_error(error)
        raise OSError(f"macOS sandbox enforcement failed: {description}")
