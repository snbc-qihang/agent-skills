"""CI-only fixed native DLL diagnostic; never Provider qualification."""
from __future__ import annotations

import hashlib
import ctypes
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import sysconfig
import xml.etree.ElementTree as ET
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.platforms import provider_sandbox_windows as windows
from engineering_assistant.runtime.artifact_io import ArtifactIO  # noqa: E402
from engineering_assistant.runtime.catalog import load_catalog  # noqa: E402
from engineering_assistant.installer.installation import (  # noqa: E402
    MAX_CONTROL_BYTES, _check_python_base, python_download_metadata, runtime_lock,
)
from engineering_assistant.platforms.windows_process import run_bounded_windows  # noqa: E402


CRT_MODULES = tuple("api-ms-win-crt-" + name + "-l1-1-0.dll" for name in (
    "stdio", "environment", "string", "heap", "runtime", "locale", "convert", "math", "time",
    "process", "conio", "filesystem"))
FILE_CHECKS = ("file_read", "file_read_execute", "sec_image", "view_sec_image",
               "sec_image_no_execute", "view_sec_image_no_execute", "actctx_core_manifest")
MODULES = ("ucrtbase.dll", "advapi32.dll", "shell32.dll", "ole32.dll", "oleaut32.dll",
           "version.dll", "ws2_32.dll", "bcrypt.dll", "api-ms-win-core-path-l1-1-0.dll",
           "vcruntime140.dll", *CRT_MODULES, "python313.dll")
IMPORTS = {"GetStdHandle", "WriteFile", "LoadLibraryExW", "GetLastError", "FreeLibrary",
           "ExitProcess", "GetModuleFileNameW", "CreateFileW", "CreateFileMappingW", "CloseHandle",
           "MapViewOfFile", "UnmapViewOfFile", "CreateActCtxW", "ReleaseActCtx"}
SOURCE_SHA256 = "5e0e6c2826c2a8917b9939241e8f708df99ebd8af4751c5df9495f4ebeb2cd9f"
MAX_IMAGE = 1_048_576
MANIFEST_FREE_IMAGES = {
    "python.exe": ("1cef81e2d42a8548becdfb134fd82746e0305a317f4337c95dc868551ed6d039", 10280,
                   "7c9b1e6b2c57695476d7ed73938766eb4b64872ddd498e2f857291cfb870caac"),
    "python313.dll": ("68dc4b6989e4a5954417157f5d714d2a1d21b1da855549e98ef1c2ab43468b62", 6098968,
                      "5d5218b5ec9f47af179f152b1fb53e372da293a01bffbc41fe8803e9eda50067"),
}


class ProbeFailure(ValueError):
    """Fixed maintainer diagnostic codes; never retain tool text or paths."""

    def __init__(self, stage: str, error: str, code: int | None = None):
        self.stage, self.error, self.code = stage, error, code
        super().__init__(stage + "/" + error)


def _error_record(exc, stage="diagnostic") -> dict:
    if isinstance(exc, ProbeFailure):
        result = {"stage": exc.stage, "error": exc.error}
        code = exc.code
    else:
        result = {"stage": stage, "error": "operation_timeout" if isinstance(
            exc, subprocess.TimeoutExpired) else "operation_failed"}
        code = getattr(exc, "errno", None)
    if isinstance(code, int):
        result["code"] = code
    return result


def parse_output(data: bytes) -> dict:
    result = {"entry": False, "complete": False, "checks": [], "loads": []}
    if not data:
        return result
    error = ValueError("unrecognized native probe output")
    if len(data) > 4096 or not data.endswith(b"\n"):
        raise error
    try:
        lines = data.decode("ascii", errors="strict").split("\n")[:-1]
    except UnicodeError:
        raise error from None
    if not lines or lines[0] != "EA_NATIVE_DLL_PROBE_V4":
        raise error
    result["entry"] = True
    index = 1
    opened = {}
    for operation in FILE_CHECKS:
        if index == len(lines):
            return result
        if lines[index] != "CHECK " + operation + " python313.dll":
            raise error
        index += 1
        if index == len(lines):
            result["pending_check"] = operation
            return result
        status = re.fullmatch(r"CHECK_RESULT " + operation + r" python313\.dll (0x[0-9A-F]{8}|SKIPPED)", lines[index])
        required = {"sec_image": "file_read_execute", "sec_image_no_execute": "file_read",
                    "view_sec_image": "sec_image", "view_sec_image_no_execute": "sec_image_no_execute"}.get(operation)
        if not status or ((status[1] == "SKIPPED") != (required is not None and not opened[required])):
            raise error
        item = {"operation": operation, "module": "python313.dll"}
        if status[1] == "SKIPPED":
            item["not_attempted"] = True
        else:
            item["win32_error"] = status[1]
        result["checks"].append(item)
        opened[operation] = status[1] == "0x00000000"
        index += 1
    for module in MODULES:
        if index == len(lines):
            return result
        if lines[index] != "LOAD " + module:
            raise error
        index += 1
        if index == len(lines):
            result["pending_module"] = module
            return result
        status = re.fullmatch(r"RESULT " + re.escape(module) + r" (0x[0-9A-F]{8})", lines[index])
        if not status:
            raise error
        result["loads"].append({"module": module, "win32_error": status[1]})
        index += 1
    if index != len(lines):
        if lines[index:] != ["DONE"]:
            raise error
        result["complete"] = True
    return result


def verify_pe(data: bytes) -> None:
    """Fail closed on this fixture's actual PE, not the no_std source label.

    Layout: https://learn.microsoft.com/windows/win32/debug/pe-format
    This is a narrow check of the freshly compiled, source-bound probe.
    """
    error = ValueError("invalid native probe PE")
    def unpack(format, offset):
        size = struct.calcsize(format)
        if offset < 0 or offset + size > len(data):
            raise error
        return struct.unpack_from(format, data, offset)
    if not 64 <= len(data) <= MAX_IMAGE or data[:2] != b"MZ":
        raise error
    pe = unpack("<I", 60)[0]
    if not 64 <= pe <= 65536 or data[pe:pe + 4] != b"PE\0\0":
        raise error
    machine, count = unpack("<HH", pe + 4)
    optional_size, flags = unpack("<HH", pe + 20)
    optional = pe + 24
    if machine != 0x8664 or not 1 <= count <= 16 or optional_size != 240 or not flags & 2 or flags & 0x2000:
        raise error
    if unpack("<H", optional)[0] != 0x20B or unpack("<I", optional + 108)[0] != 16:
        raise error
    for directory in (9, 11, 13):  # No TLS callbacks, bound or delay imports.
        if unpack("<II", optional + 112 + directory * 8) != (0, 0):
            raise error
    sections = []
    headers_end = optional + optional_size + count * 40
    for index in range(count):
        virtual_size, address, size, offset = unpack("<IIII", optional + optional_size + index * 40 + 8)
        end = address + max(virtual_size, size)
        if not address or end > 0x100000000 or (size and (offset < headers_end or offset + size > len(data))):
            raise error
        if any(address < prior_end and prior_address < end for prior_address, prior_end, _, _ in sections):
            raise error
        sections.append((address, end, offset, size))

    def mapped(rva, length):
        found = [(offset + rva - address, offset + size) for address, end, offset, size in sections
                 if address <= rva and rva + length <= end and rva - address + length <= size]
        if len(found) != 1:
            raise error
        return found[0]

    def string(rva, limit):
        offset, end = mapped(rva, 1)
        terminator = data.find(b"\0", offset, min(end, offset + limit))
        if terminator < offset:
            raise error
        try:
            return data[offset:terminator].decode("ascii", errors="strict")
        except UnicodeError:
            raise error from None

    mapped(unpack("<I", optional + 16)[0], 1)
    imports, size = unpack("<II", optional + 120)
    if size != 40:
        raise error
    offset, _ = mapped(imports, size)
    lookup, timestamp, forwarder, name, addresses = unpack("<IIIII", offset)
    if not lookup or not addresses or timestamp or forwarder or string(name, 32).lower() != "kernel32.dll":
        raise error
    if data[offset + 20:offset + 40] != b"\0" * 20:
        raise error
    observed = set()
    for index in range(len(IMPORTS) + 1):
        entry, _ = mapped(lookup + index * 8, 8)
        target, _ = mapped(addresses + index * 8, 8)
        symbol = unpack("<Q", entry)[0]
        if unpack("<Q", target)[0] != symbol:
            raise error
        if not symbol:
            if observed != IMPORTS:
                raise error
            return
        if symbol >= 0x80000000:
            raise error  # Reject ordinals and non-RVA high bits.
        imported = string(symbol + 2, 64)
        if imported not in IMPORTS or imported in observed:
            raise error
        observed.add(imported)
    raise error


def _read_file(path: Path, maximum: int) -> bytes:
    metadata = path.lstat()
    if windows._reparse(path) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
        raise ValueError("invalid native probe file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(maximum + 1)
    if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino) or len(data) > maximum or windows._reparse(path):
        raise ValueError("invalid native probe file")
    return data


def replace_runtime(destination: Path, image: bytes, original) -> Path:
    verify_pe(image)
    executable = original(destination)
    if executable != destination / "python.exe" or windows._reparse(destination) or windows._reparse(executable):
        raise ValueError("invalid native probe runtime")
    executable.write_bytes(image)
    copied = _read_file(executable, MAX_IMAGE)
    if hashlib.sha256(copied).digest() != hashlib.sha256(image).digest():
        raise ValueError("invalid native probe runtime")
    verify_pe(copied)
    return executable


def _without_sxs_manifest_lookup(data: bytes, *, dll: bool = True) -> bytes:
    """Fixed x64 image control: change only the documented SxS lookup bit.

    /ALLOWISOLATION:NO controls assembly manifests, not AppContainer isolation:
    https://learn.microsoft.com/cpp/build/reference/allowisolation
    This diagnostic never changes the installed interpreter or token policy.
    """
    error = ValueError("invalid private CPython image control")
    if not 64 <= len(data) <= 32 * 1024 * 1024 or data[:2] != b"MZ":
        raise error
    pe = struct.unpack_from("<I", data, 60)[0]
    if not 64 <= pe <= 65536 or pe + 24 > len(data) or data[pe:pe + 4] != b"PE\0\0":
        raise error
    machine = struct.unpack_from("<H", data, pe + 4)[0]
    size, flags = struct.unpack_from("<HH", data, pe + 20)
    optional = pe + 24
    if (machine != 0x8664 or size != 240 or flags & 0x2002 != (0x2002 if dll else 0x2)
            or optional + size > len(data) or struct.unpack_from("<H", data, optional)[0] != 0x20B):
        raise error
    result = bytearray(data)
    location = optional + 70
    characteristics = struct.unpack_from("<H", data, location)[0]
    struct.pack_into("<H", result, location, characteristics | 0x200)
    return bytes(result)


def _sxs_private_runtime(destination: Path, original) -> Path:
    executable = original(destination)
    if executable != destination / "python.exe" or windows._reparse(destination) or windows._reparse(executable):
        raise ValueError("invalid private CPython control directory")
    for name, dll in (("python.exe", False), ("python313.dll", True)):
        image = destination / name
        data = _without_sxs_manifest_lookup(_read_file(image, 32 * 1024 * 1024), dll=dll)
        image.write_bytes(data)
        if _read_file(image, 32 * 1024 * 1024) != data:
            raise ValueError("private CPython control changed")
    return executable


def _manifest_resource(path: Path, name: int, *, allow_missing=False) -> bytes | None:
    """Read only the fixed embedded manifest; never load executable code."""
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    for symbol, result, arguments in (
        ("LoadLibraryExW", ctypes.c_void_p, (ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32)),
        ("FindResourceW", ctypes.c_void_p, (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)),
        ("LoadResource", ctypes.c_void_p, (ctypes.c_void_p, ctypes.c_void_p)),
        ("SizeofResource", ctypes.c_uint32, (ctypes.c_void_p, ctypes.c_void_p)),
        ("LockResource", ctypes.c_void_p, (ctypes.c_void_p,)),
        ("FreeLibrary", ctypes.c_int, (ctypes.c_void_p,)),
    ):
        function = getattr(api, symbol)
        function.restype, function.argtypes = result, arguments
    module = api.LoadLibraryExW(str(path), None, 0x2 | 0x20)  # DATAFILE | IMAGE_RESOURCE
    if not module:
        raise ValueError("private Python resource mapping failed")
    try:
        ctypes.set_last_error(0)
        resource = api.FindResourceW(module, name, 24)  # RT_MANIFEST, not RT_VERSION (16)
        if not resource and allow_missing and ctypes.get_last_error() == 1813:
            return None  # Observed ERROR_RESOURCE_TYPE_NOT_FOUND only.
        size = api.SizeofResource(module, resource) if resource else 0
        loaded = api.LoadResource(module, resource) if 64 <= size <= 8192 else None
        address = api.LockResource(loaded) if loaded else None
        if not address:
            raise ValueError("private Python manifest resource unavailable")
        return ctypes.string_at(address, size)
    finally:
        api.FreeLibrary(module)


def _without_common_controls(data: bytes, manifest: bytes) -> bytes:
    if not 64 <= len(manifest) <= 8192 or len(data) > 32 * 1024 * 1024 or data.count(manifest) != 1 or b"<!" in manifest:
        raise ValueError("invalid private Python manifest control")
    try:
        root = ET.fromstring(manifest.rstrip(b"\0"))
    except ET.ParseError:
        raise ValueError("invalid private Python manifest control") from None
    namespace = "{urn:schemas-microsoft-com:asm.v1}"
    identities = root.findall(namespace + "dependency/" + namespace + "dependentAssembly/" + namespace + "assemblyIdentity")
    expected = dict(type="win32", name="Microsoft.Windows.Common-Controls", version="6.0.0.0",
                    processorArchitecture="*", publicKeyToken="6595b64144ccf1df", language="*")
    matches = list(re.finditer(rb"<dependency>.*?</dependency>", manifest, re.DOTALL))
    if root.tag != namespace + "assembly" or len(identities) != 1 or identities[0].attrib != expected or len(matches) != 1:
        raise ValueError("unexpected private Python manifest dependency")
    match = matches[0]
    offset = data.index(manifest) + match.start()
    return data[:offset] + b" " * len(match.group()) + data[offset + len(match.group()):]


def _common_controls_private_runtime(destination: Path, original) -> Path:
    executable = original(destination)
    if executable != destination / "python.exe" or windows._reparse(destination) or windows._reparse(executable):
        raise ValueError("invalid private Python control directory")
    for name, resource in (("python.exe", 1), ("python313.dll", 2)):
        image = destination / name
        data = _without_common_controls(_read_file(image, 32 * 1024 * 1024), _manifest_resource(image, resource))
        image.write_bytes(data)
        if _read_file(image, 32 * 1024 * 1024) != data:
            raise ValueError("private Python control changed")
    return executable


def _without_embedded_manifest(data: bytes, name: str) -> bytes:
    record = MANIFEST_FREE_IMAGES.get(name)
    if record is None or hashlib.sha256(data).hexdigest() != record[0]:
        raise ValueError("manifest type control requires the exact fixed PBS image")
    _before, offset, after = record
    if offset + 4 > len(data) or struct.unpack_from("<I", data, offset)[0] != 24:
        raise ValueError("manifest type control has an invalid fixed resource entry")
    result = data[:offset] + struct.pack("<I", 65535) + data[offset + 4:]
    if hashlib.sha256(result).hexdigest() != after:
        raise ValueError("manifest type control result mismatch")
    return result


def _manifest_free_private_runtime(destination: Path, original) -> Path:
    executable = original(destination)
    if executable != destination / "python.exe" or windows._reparse(destination) or windows._reparse(executable):
        raise ValueError("invalid private Python control directory")
    images = {name: _without_embedded_manifest(_read_file(destination / name, 32 * 1024 * 1024), name)
              for name in MANIFEST_FREE_IMAGES}
    for name, data in images.items():
        image = destination / name
        image.write_bytes(data)
        if _read_file(image, 32 * 1024 * 1024) != data:
            raise ValueError("manifest type control changed")
        resource = 1 if name == "python.exe" else 2
        if _manifest_resource(image, resource, allow_missing=True) is not None:
            raise ValueError("manifest type control remains visible")
    return executable


def _python_sxs_control(original, api, owner, environment, *, remove_common_controls=False, hide_manifest=False) -> dict:
    observation = {"diagnostic_only": True, "qualified": False, "capability_count": 0,
                   "manifest_lookup": "private_common_controls_removed" if remove_common_controls else "disabled_private_python_images"}
    if hide_manifest:
        observation["manifest_lookup"] = "fixed_private_manifest_type_hidden"
    try:
        with tempfile.TemporaryDirectory(prefix="ea-native-sxs-control-") as temporary:
            base = Path(temporary).resolve()
            api.acl(base, owner, None, False)
            bundle, work = base / "bundle", base / "work"
            bundle.mkdir()
            work.mkdir()
            copier = _manifest_free_private_runtime if hide_manifest else _common_controls_private_runtime if remove_common_controls else _sxs_private_runtime
            with patch.object(windows, "_private_runtime", lambda path: copier(path, original)):
                code, output, stderr = windows._run_lpac(list(windows._STARTUP_COMMAND), bundle, work,
                    environment, 10, 4096, diagnostics=observation)
            observation.update(exit_code=f"0x{code & 0xFFFFFFFF:08X}",
                marker=code == 0 and not stderr and output in (b"EA_LPAC_STARTUP_OK\n", b"EA_LPAC_STARTUP_OK\r\n"),
                stdout_marker=b"EA_LPAC_STARTUP_OK" in output,
                stdout_bytes=len(output), stderr_present=bool(stderr), stderr_bytes=len(stderr),
                stderr_flags=[label for label, text in (
                    ("python_path_configuration", b"Python path configuration:"),
                    ("python_fatal_error", b"Fatal Python error:"),
                    ("permission_error", b"PermissionError:"),
                    ("missing_independent_libraries", b"Could not find platform independent libraries"),
                    ("missing_dependent_libraries", b"Could not find platform dependent libraries"),
                ) if text in stderr])
            if hide_manifest:
                observation["manifest_resource_absence_verified"] = True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        observation["error"] = _error_record(exc)
    return observation


def build_probe(destination: Path) -> bytes:
    try:
        source = _read_file(ROOT / "tests/fixtures/windows_startup_probe.rs", 16384)
    except (OSError, ValueError) as exc:
        raise ProbeFailure("source", "source_read_failed", getattr(exc, "errno", None)) from None
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ProbeFailure("source", "source_identity_mismatch")
    compiler = shutil.which("rustc")
    if not compiler:
        raise ProbeFailure("toolchain", "compiler_unavailable")
    # Preserve rustc's shim basename: resolving a rustup symlink changes its
    # argv[0] dispatch into rustup and loses the selected compiler operation.
    compiler = str(Path(compiler).absolute())
    # Fixed maintainer compiler, not an end-user dependency. Remove option
    # injection while retaining Rust/SDK locations from the controlled CI host.
    environment = {name: value for name, value in os.environ.items() if name.upper() not in {
        "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
        "RUSTC_BOOTSTRAP", "CL", "_CL_", "LINK", "_LINK_",
    }}
    try:
        code, version = run_bounded_windows([compiler, "+1.90.0", "--version"], cwd=destination,
                                           environment=environment, timeout_seconds=10, output_limit_bytes=4096)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        error = "compiler_check_timeout" if isinstance(exc, subprocess.TimeoutExpired) else "compiler_check_failed"
        raise ProbeFailure("toolchain", error, getattr(exc, "errno", None)) from None
    if code or not re.fullmatch(rb"rustc 1\.90\.0 \([0-9a-f]{9} 2025-09-14\)\s*", version):
        raise ProbeFailure("toolchain", "version_mismatch", code if code else None)
    snapshot, output = destination / "probe.rs", destination / "probe.exe"
    try:
        snapshot.write_bytes(source)
    except OSError as exc:
        raise ProbeFailure("build", "snapshot_write_failed", exc.errno) from None
    command = [compiler, "+1.90.0", str(snapshot), "--target", "x86_64-pc-windows-msvc", "--edition=2021",
               "-C", "panic=abort", "-C", "opt-level=2", "-C", "debuginfo=0", "-C", "codegen-units=1",
               "-C", "link-arg=/NODEFAULTLIB", "-C", "link-arg=/ENTRY:probe_entry",
               "-C", "link-arg=/SUBSYSTEM:CONSOLE", "-C", "link-arg=/INCREMENTAL:NO", "-C", "link-arg=/BREPRO",
               "-o", str(output)]
    try:
        code, _ = run_bounded_windows(command, cwd=destination, environment=environment,
                                    timeout_seconds=60, output_limit_bytes=65536)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        error = "compiler_timeout" if isinstance(exc, subprocess.TimeoutExpired) else "compiler_execution_failed"
        raise ProbeFailure("build", error, getattr(exc, "errno", None)) from None
    if code:
        raise ProbeFailure("build", "compiler_rejected", code)
    try:
        image = _read_file(output, MAX_IMAGE)
    except (OSError, ValueError) as exc:
        raise ProbeFailure("pe", "image_read_failed", getattr(exc, "errno", None)) from None
    try:
        verify_pe(image)
    except ValueError:
        raise ProbeFailure("pe", "image_contract_rejected") from None
    return image


def _observe(code: int, output: bytes, stderr: bytes | None = None) -> dict:
    observation = {"exit_code": f"0x{code & 0xFFFFFFFF:08X}"}
    # The baseline runner merges both streams; only LPAC returns separate
    # bytes that can establish stderr presence or absence.
    if stderr is not None:
        observation["stderr_present"] = bool(stderr)
    try:
        observation.update(parse_output(output))
    except ValueError:
        observation["output_error"] = "unrecognized native probe output"
    return observation


def _fixed_results(observation: dict, check_errors: tuple[str, ...], load_errors: tuple[str, ...]) -> bool:
    return (isinstance(observation, dict) and observation.get("entry") is True
            and observation.get("complete") is True and observation.get("exit_code") == "0x00000000"
            and observation.get("checks") == [{"operation": name, "module": "python313.dll", "win32_error": error}
                                               for name, error in zip(FILE_CHECKS, check_errors)]
            and observation.get("loads") == [{"module": name, "win32_error": error}
                                              for name, error in zip(MODULES, load_errors)])


def _registry_read_control_ready(report: dict) -> bool:
    zero, denied = "0x00000000", "0x00000005"
    return (_fixed_results(report.get("baseline", {}), (zero,) * len(FILE_CHECKS), (zero,) * len(MODULES))
            and _fixed_results(report.get("detached_console", {}), (zero,) * 6 + (denied,),
                               (zero,) * 22 + (denied,)))


@contextmanager
def _registry_read_factory(api, image_ready, observation):
    """Only the fresh, source-bound fixed control gets this named SID."""
    original = windows._SecurityCapabilities
    if ctypes.sizeof(original) != 24 or ctypes.sizeof(windows._SidAndAttributes) != 16:
        raise ProbeFailure("capability", "abi_mismatch")
    try:
        function = ctypes.WinDLL("kernelbase", use_last_error=True).DeriveCapabilitySidsFromName
    except (OSError, AttributeError):
        raise ProbeFailure("capability", "derive_unavailable") from None
    sid_pointer = ctypes.POINTER(windows.HANDLE)
    function.restype = windows.BOOL
    function.argtypes = [windows.LPWSTR, ctypes.POINTER(sid_pointer), ctypes.POINTER(windows.DWORD),
                         ctypes.POINTER(sid_pointer), ctypes.POINTER(windows.DWORD)]
    groups, sids = sid_pointer(), sid_pointer()
    group_count, sid_count = windows.DWORD(), windows.DWORD()
    try:
        if not function("registryRead", ctypes.byref(groups), ctypes.byref(group_count),
                        ctypes.byref(sids), ctypes.byref(sid_count)):
            raise ProbeFailure("capability", "derive_failed", ctypes.get_last_error())
        if group_count.value != 1 or sid_count.value != 1 or not groups or not sids or not groups[0] or not sids[0]:
            raise ProbeFailure("capability", "invalid_sid_result")
        # Group SIDs are not capabilities and never enter the child token.
        # Both returned arrays/SIDs stay alive until backend finally and patch
        # restoration have completed. This one ctypes array owns no OS heap SID.
        capability = (windows._SidAndAttributes * 1)(windows._SidAndAttributes(sids[0], 4))
        observation.update(capability_requested="registryRead", requested_capability_count=1,
                           requested_sid_attributes=4, constructed_capability_count=0)
        constructed = False
        def factory(sid, prior, count, reserved):
            nonlocal constructed
            if (constructed or image_ready() is not True or type(sid) is not windows.HANDLE or not sid.value
                    or prior is not None or type(count) is not int or count != 0
                    or type(reserved) is not int or reserved != 0):
                raise ProbeFailure("capability", "factory_contract_rejected")
            result = original(sid, ctypes.cast(capability, windows.HANDLE), 1, 0)
            constructed = True
            observation["constructed_capability_count"] = 1
            return result
        yield factory
    finally:
        cleanup_failed = False
        for array, count in ((groups, group_count.value), (sids, sid_count.value)):
            if array:
                # The documented fixed name returns one SID. Refuse oversized
                # API results without walking unbounded or unknown memory.
                if count <= 16:
                    for index in range(count):
                        if array[index] and api.kernel.LocalFree(array[index]):
                            cleanup_failed = True
                else:
                    cleanup_failed = True
                if api.kernel.LocalFree(ctypes.cast(array, windows.HANDLE).value):
                    cleanup_failed = True
        if cleanup_failed:
            raise ProbeFailure("capability", "allocation_cleanup_failed")


def _registry_read_control(image: bytes, original, api, owner: str, environment: dict) -> dict:
    observation = {"diagnostic_only": True, "qualified": False}
    started = time.monotonic()
    # This flag belongs only to the fourth fresh copy, never earlier cases.
    copied = False
    expected_runtime = None
    def private_runtime(destination):
        nonlocal copied
        if copied or destination != expected_runtime:
            raise ProbeFailure("capability", "runtime_copy_contract_rejected")
        executable = replace_runtime(destination, image, original)
        copied = True
        return executable
    try:
        with tempfile.TemporaryDirectory(prefix="ea-native-registry-control-") as temporary:
            base = Path(temporary).resolve()
            expected_runtime = base / "runtime"
            api.acl(base, owner, None, False)
            bundle, work = base / "bundle", base / "work"
            bundle.mkdir()
            work.mkdir()
            with _registry_read_factory(api, lambda: copied, observation) as factory:
                with patch.object(windows, "_private_runtime", private_runtime), \
                     patch.object(windows, "_SecurityCapabilities", factory):
                    code, output, stderr = windows._run_lpac(list(windows._STARTUP_COMMAND), bundle, work,
                        environment, 10, 4096, diagnostics=observation, _console_diagnostic=True)
            if observation["constructed_capability_count"] != 1:
                raise ProbeFailure("capability", "factory_not_used")
            observation.update(_observe(code, output, stderr))
            if (observation.get("entry") is not True or observation.get("complete") is not True
                    or observation.get("exit_code") != "0x00000000"):
                raise ProbeFailure("execution", "native_control_incomplete", code & 0xFFFFFFFF)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        observation["error"] = _error_record(exc, "execution")
    observation["total_seconds"] = round(time.monotonic() - started, 3)
    return observation


def _python_startup_control_ready(report: dict) -> bool:
    observation = report.get("detached_registry_read", {})
    zero = "0x00000000"
    return (_registry_read_control_ready(report)
            and all("error" not in report.get(name, {"error": None})
                    for name in ("baseline", "detached_console", "detached_registry_read"))
            and _fixed_results(observation, (zero,) * len(FILE_CHECKS), (zero,) * len(MODULES))
            and observation.get("diagnostic_only") is True and observation.get("qualified") is False
            and observation.get("capability_requested") == "registryRead"
            and type(observation.get("requested_capability_count")) is int
            and observation.get("requested_capability_count") == 1
            and type(observation.get("constructed_capability_count")) is int
            and observation.get("constructed_capability_count") == 1
            and observation.get("requested_sid_attributes") == 4)


def _pinned_python_base() -> Path:
    """Recheck local download/BUILD/receipt binding, not the downloaded archive."""
    try:
        lock, _ = runtime_lock(ROOT, "codex", "windows-x64", load_catalog(ROOT).version)
        base = Path(sys.base_prefix)
        executable = base / "python.exe"
        if (sys.version_info[:3] != (3, 13, 13) or sys.implementation.name != "cpython"
                or bool(sysconfig.get_config_var("Py_GIL_DISABLED")) or Path(sys.executable) != executable):
            raise ValueError("interpreter contract")
        for directory in (base, *list(base.parents)[:4]):
            if not stat.S_ISDIR(directory.lstat().st_mode) or windows._reparse(directory):
                raise ValueError("base directory contract")
        if not stat.S_ISREG(executable.lstat().st_mode) or windows._reparse(executable):
            raise ValueError("executable contract")
        _check_python_base(base, lock)
        storage = ArtifactIO(base.parent, ".")
        try:
            metadata = storage.read_bytes_limited(MAX_CONTROL_BYTES, "runtime-python-downloads.json")
        finally:
            storage.close()
        if metadata != python_download_metadata(lock):
            raise ValueError("download metadata contract")
        return base
    except (OSError, ValueError):
        raise ProbeFailure("runtime", "pinned_runtime_not_verified") from None


def _python_startup_control(original, api, owner: str, environment: dict) -> dict:
    observation = {"diagnostic_only": True, "qualified": False, "archive_rehashed": False}
    started = time.monotonic()
    try:
        source = _pinned_python_base()
    except ProbeFailure:
        return {**observation, "status": "not_run", "reason": "pinned_runtime_not_verified"}
    observation["source_contract"] = "pinned_download_metadata_build_receipt"
    copied, expected_runtime = False, None
    def private_runtime(destination):
        nonlocal copied
        if copied or destination != expected_runtime or _pinned_python_base() != source:
            raise ProbeFailure("runtime", "startup_copy_contract_rejected")
        executable = original(destination)
        if (_pinned_python_base() != source or executable != destination / "python.exe"
                or not stat.S_ISREG(executable.lstat().st_mode) or windows._reparse(executable)):
            raise ProbeFailure("runtime", "startup_copy_contract_rejected")
        copied = True
        return executable
    try:
        for name, capped in (("copied_runtime_baseline", False), ("detached_registry_read", True)):
            current = {}
            observation[name] = current
            copied = False
            with tempfile.TemporaryDirectory(prefix="ea-pinned-python-startup-") as temporary:
                base = Path(temporary).resolve()
                expected_runtime = base / "runtime"
                api.acl(base, owner, None, False)
                bundle, work = base / "bundle", base / "work"
                bundle.mkdir()
                work.mkdir()
                if capped:
                    with _registry_read_factory(api, lambda: copied, current) as factory:
                        with patch.object(windows, "_private_runtime", private_runtime), \
                             patch.object(windows, "_SecurityCapabilities", factory):
                            code, output, stderr = windows._run_lpac(list(windows._STARTUP_COMMAND), bundle, work,
                                environment, 10, 4096, diagnostics=current, _console_diagnostic=True)
                    if current["constructed_capability_count"] != 1:
                        raise ProbeFailure("capability", "factory_not_used")
                    current["stderr_present"] = bool(stderr)
                else:
                    executable = private_runtime(expected_runtime)
                    windows._secure_tree(api, expected_runtime, owner, None, False)
                    block = windows._environment_block(environment, work)
                    private_environment = dict(item.split("=", 1) for item in block[:].rstrip("\0").split("\0"))
                    code, output = run_bounded_windows([str(executable), *windows._STARTUP_COMMAND[1:]],
                        cwd=work, environment=private_environment, timeout_seconds=10, output_limit_bytes=4096)
                    stderr = b""
                current.update(exit_code=f"0x{code & 0xFFFFFFFF:08X}",
                    marker=code == 0 and not stderr and output in (b"EA_LPAC_STARTUP_OK\n", b"EA_LPAC_STARTUP_OK\r\n"))
                if current["marker"] is not True:
                    raise ProbeFailure("execution", "python_startup_incomplete", code & 0xFFFFFFFF)
        observation["status"] = "observed"
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        observation["status"] = "error"
        observation["error"] = _error_record(exc, "execution")
    observation["total_seconds"] = round(time.monotonic() - started, 3)
    return observation


def diagnose() -> dict:
    available = windows.capability()
    report = {**available, "diagnostic_only": True, "qualified": False,
              "assurance": "native_loader_diagnostic_only", **windows._host_information(),
              "load_order": list(MODULES), "check_order": list(FILE_CHECKS), "same_process_sequence": True,
              "mapping_handle_access": {"sec_image": "GENERIC_READ|GENERIC_EXECUTE", "sec_image_no_execute": "GENERIC_READ"},
              "image_view_access_flag": "FILE_MAP_READ", "sec_image_view_protection": "PE_section_permissions",
              "sec_image_desired_access_ignored": True, "image_view_contents_accessed": False,
              "image_checks_invoke_dll_entry": False,
              "core_manifest_resource_id": 2, "activation_context_flags": 8,
              "activation_context_struct_size": 56, "activation_context_activated": False,
              "execution_timeout_seconds_per_case": 10, "compile_timeout_seconds": 60}
    if not available["supported"]:
        return report
    if sys.version_info[:3] != (3, 13, 13):
        raise ProbeFailure("runtime", "python_version_mismatch")
    started = time.monotonic()
    api = windows._Api()
    owner = api.owner_sid()
    original = windows._private_runtime
    with tempfile.TemporaryDirectory(prefix="ea-native-probe-build-") as temporary:
        build = Path(temporary).resolve()
        api.acl(build, owner, None, False)
        image = build_probe(build)
        report["source_bound"] = report["image_bound"] = True
        # Original cases retain zero capabilities. Patches stay inside this
        # fixed source-bound fixture, with no product API or executable option.
        def private_runtime(destination):
            return replace_runtime(destination, image, original)
        environment = {name: value for name, value in os.environ.items()
                       if name.upper() in {"SYSTEMROOT", "WINDIR"}}
        for name, detached in (("baseline", None), ("strict_lpac", False), ("detached_console", True),
                               ("private_common_controls", True), ("private_no_manifest", True)):
            observation = {}
            report[name] = observation
            case_started = time.monotonic()
            try:
                with tempfile.TemporaryDirectory(prefix="ea-native-probe-case-") as case:
                    base = Path(case).resolve()
                    api.acl(base, owner, None, False)
                    bundle, work = base / "bundle", base / "work"
                    bundle.mkdir()
                    work.mkdir()
                    if detached is None:
                        executable = private_runtime(base / "runtime")
                        windows._secure_tree(api, base / "runtime", owner, None, False)
                        block = windows._environment_block(environment, work)
                        private_environment = dict(item.split("=", 1) for item in block[:].rstrip("\0").split("\0"))
                        code, output = run_bounded_windows([str(executable), *windows._STARTUP_COMMAND[1:]],
                            cwd=work, environment=private_environment, timeout_seconds=10, output_limit_bytes=4096)
                        observation.update(_observe(code, output))
                    else:
                        transform = {"private_common_controls": _common_controls_private_runtime,
                                     "private_no_manifest": _manifest_free_private_runtime}.get(name)
                        copier = (lambda path: replace_runtime(path, image, lambda target: transform(target, original))) if transform else private_runtime
                        with patch.object(windows, "_private_runtime", copier):
                            code, output, stderr = windows._run_lpac(list(windows._STARTUP_COMMAND), bundle, work,
                                environment, 10, 4096, diagnostics=observation, _console_diagnostic=detached)
                        observation.update(_observe(code, output, stderr))
                        if name == "private_no_manifest":
                            observation["manifest_resource_absence_verified"] = True
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                observation["error"] = _error_record(exc, "execution")
            observation["total_seconds"] = round(time.monotonic() - case_started, 3)
        if _registry_read_control_ready(report):
            report["detached_registry_read"] = _registry_read_control(image, original, api, owner, environment)
            report["python_startup_private_sxs"] = _python_sxs_control(original, api, owner, environment)
            report["python_startup_private_common_controls"] = _python_sxs_control(original, api, owner, environment, remove_common_controls=True)
            report["python_startup_private_no_manifest"] = _python_sxs_control(original, api, owner, environment, hide_manifest=True)
        if _python_startup_control_ready(report):
            report["python_startup_registry_read"] = _python_startup_control(original, api, owner, environment)
        else:
            report["python_startup_registry_read"] = {"diagnostic_only": True, "qualified": False,
                "status": "not_run", "reason": "native_control_not_verified"}
    report["total_seconds"] = round(time.monotonic() - started, 3)
    return report


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise ProbeFailure("arguments", "unsupported_arguments")
        report = diagnose()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report = {"diagnostic_only": True, "qualified": False,
                  "error": _error_record(exc)}
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    baseline = report.get("baseline", {})
    valid = _fixed_results(baseline, ("0x00000000",) * len(FILE_CHECKS), ("0x00000000",) * len(MODULES))
    cases = ("strict_lpac", "detached_console") + (("detached_registry_read",) if "detached_registry_read" in report else ())
    if "python_startup_registry_read" in report:
        cases += ("python_startup_registry_read",)
    # This exit means a usable diagnostic control, never Provider qualification.
    return 0 if valid and all("error" not in report.get(name, {"error": None})
                             for name in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
