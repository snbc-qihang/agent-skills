"""CI-only fixed native DLL diagnostic; never Provider qualification."""
from __future__ import annotations

import hashlib
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
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant import provider_sandbox_windows as windows  # noqa: E402
from engineering_assistant.windows_process import run_bounded_windows  # noqa: E402


MODULES = ("ucrtbase.dll", "advapi32.dll", "shell32.dll", "ole32.dll", "oleaut32.dll",
           "vcruntime140.dll", "python313.dll")
IMPORTS = {"GetStdHandle", "WriteFile", "LoadLibraryExW", "GetLastError", "FreeLibrary",
           "ExitProcess", "GetModuleFileNameW"}
SOURCE_SHA256 = "e6a506468cba2431035a6e52810eafa33bf0dca6f78164f93a8cde328793db94"
MAX_IMAGE = 1_048_576


def parse_output(data: bytes) -> dict:
    result = {"entry": False, "complete": False, "loads": []}
    if not data:
        return result
    error = ValueError("unrecognized native probe output")
    if len(data) > 4096 or not data.endswith(b"\n"):
        raise error
    try:
        lines = data.decode("ascii", errors="strict").split("\n")[:-1]
    except UnicodeError:
        raise error from None
    if not lines or lines[0] != "EA_NATIVE_DLL_PROBE_V1":
        raise error
    result["entry"] = True
    index = 1
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


def build_probe(destination: Path) -> bytes:
    source = _read_file(ROOT / "tests/fixtures/windows_startup_probe.rs", 16384)
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("invalid native probe source")
    compiler = shutil.which("rustc")
    if not compiler:
        raise ValueError("native probe needs the CI Rust toolchain")
    # Preserve rustc's shim basename: resolving a rustup symlink changes its
    # argv[0] dispatch into rustup and loses the selected compiler operation.
    compiler = str(Path(compiler).absolute())
    # Fixed maintainer compiler, not an end-user dependency. Remove option
    # injection while retaining Rust/SDK locations from the controlled CI host.
    environment = {name: value for name, value in os.environ.items() if name.upper() not in {
        "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
        "RUSTC_BOOTSTRAP", "CL", "_CL_", "LINK", "_LINK_",
    }}
    code, version = run_bounded_windows([compiler, "+1.90.0", "--version"], cwd=destination,
                                       environment=environment, timeout_seconds=10, output_limit_bytes=4096)
    if code or not re.fullmatch(rb"rustc 1\.90\.0 \([0-9a-f]{9} 2025-09-14\)\s*", version):
        raise ValueError("native probe requires the fixed Rust 1.90.0 compiler")
    snapshot, output = destination / "probe.rs", destination / "probe.exe"
    snapshot.write_bytes(source)
    command = [compiler, "+1.90.0", str(snapshot), "--target", "x86_64-pc-windows-msvc", "--edition=2021",
               "-C", "panic=abort", "-C", "opt-level=2", "-C", "debuginfo=0", "-C", "codegen-units=1",
               "-C", "link-arg=/NODEFAULTLIB", "-C", "link-arg=/ENTRY:probe_entry",
               "-C", "link-arg=/SUBSYSTEM:CONSOLE", "-C", "link-arg=/INCREMENTAL:NO", "-C", "link-arg=/BREPRO",
               "-o", str(output)]
    code, _ = run_bounded_windows(command, cwd=destination, environment=environment,
                                timeout_seconds=60, output_limit_bytes=65536)
    if code:
        raise ValueError("native probe build failed")
    image = _read_file(output, MAX_IMAGE)
    verify_pe(image)
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


def diagnose() -> dict:
    available = windows.capability()
    report = {**available, "diagnostic_only": True, "qualified": False,
              "assurance": "native_loader_diagnostic_only", **windows._host_information(),
              "load_order": list(MODULES), "same_process_sequence": True,
              "execution_timeout_seconds_per_case": 10, "compile_timeout_seconds": 60}
    if not available["supported"]:
        return report
    if sys.version_info[:3] != (3, 13, 13):
        raise ValueError("native probe requires the CI Python 3.13.13 runtime")
    started = time.monotonic()
    api = windows._Api()
    owner = api.owner_sid()
    original = windows._private_runtime
    with tempfile.TemporaryDirectory(prefix="ea-native-probe-build-") as temporary:
        build = Path(temporary).resolve()
        api.acl(build, owner, None, False)
        image = build_probe(build)
        report["source_bound"] = report["image_bound"] = True
        # Patch is scoped to this fixed source-bound fixture. No product API,
        # executable argument or capability/ACL override is introduced.
        def private_runtime(destination):
            return replace_runtime(destination, image, original)
        environment = {name: value for name, value in os.environ.items()
                       if name.upper() in {"SYSTEMROOT", "WINDIR"}}
        for name, detached in (("baseline", None), ("strict_lpac", False), ("detached_console", True)):
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
                        with patch.object(windows, "_private_runtime", private_runtime):
                            code, output, stderr = windows._run_lpac(list(windows._STARTUP_COMMAND), bundle, work,
                                environment, 10, 4096, diagnostics=observation, _console_diagnostic=detached)
                        observation.update(_observe(code, output, stderr))
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                observation["error"] = {"type": type(exc).__name__, "code": getattr(exc, "errno", None)}
            observation["total_seconds"] = round(time.monotonic() - case_started, 3)
    report["total_seconds"] = round(time.monotonic() - started, 3)
    return report


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise ValueError("native probe accepts no command or executable argument")
        report = diagnose()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report = {"diagnostic_only": True, "qualified": False,
                  "error": {"type": type(exc).__name__, "code": getattr(exc, "errno", None)}}
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    baseline = report.get("baseline", {})
    valid = (baseline.get("exit_code") == "0x00000000" and baseline.get("complete") is True
             and all(item["win32_error"] == "0x00000000" for item in baseline.get("loads", [])))
    # This exit means a usable diagnostic control, never Provider qualification.
    return 0 if valid and all("error" not in report.get(name, {"error": None})
                             for name in ("strict_lpac", "detached_console")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
