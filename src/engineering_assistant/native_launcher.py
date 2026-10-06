"""Build and verify the small native launcher outside the author repository."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import struct
import tempfile
from pathlib import Path

from .validation import ValidationFailure


RUST_TARGETS = {
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x64": "x86_64-apple-darwin",
    "linux-x64": "x86_64-unknown-linux-gnu",
    "windows-x64": "x86_64-pc-windows-msvc",
}


def host_target() -> str:
    system, machine = platform.system(), platform.machine().lower()
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if machine in {"x86_64", "amd64"}:
        target = {"Darwin": "macos-x64", "Linux": "linux-x64", "Windows": "windows-x64"}.get(system)
        if target:
            return target
    raise ValidationFailure(f"unsupported native launcher host: {system}/{machine}")


def launcher_info(executable: Path | str) -> dict:
    path = Path(executable).expanduser().absolute()
    if not path.is_file() or path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValidationFailure("native launcher executable is missing or unsafe")
    native_target = _binary_target(path)
    if native_target != host_target():
        raise ValidationFailure("native launcher binary requires its matching OS and architecture runner")
    try:
        result = subprocess.run([str(path), "--launcher-info"], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=10, check=False)
        if result.returncode or len(result.stdout) > 4096 or result.stderr:
            raise ValidationFailure("native launcher identity probe failed")
        information = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValidationFailure("native launcher identity probe failed") from exc
    if not isinstance(information, dict) or information.get("schema_version") != "1" or information.get("target") != native_target:
        raise ValidationFailure("native launcher identity is invalid")
    return information


def _binary_target(path: Path) -> str:
    """Verify the executable machine header before executing an identity probe."""
    with path.open("rb") as stream:
        header = stream.read(65536)
    if header[:4] == b"\x7fELF" and len(header) >= 20:
        if header[4:6] == b"\x02\x01" and struct.unpack_from("<H", header, 18)[0] == 62:
            return "linux-x64"
    if header[:4] in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"} and len(header) >= 8:
        endian = "<" if header[:4] == b"\xcf\xfa\xed\xfe" else ">"
        target = {0x01000007: "macos-x64", 0x0100000C: "macos-arm64"}.get(struct.unpack_from(endian + "I", header, 4)[0])
        if target:
            return target
    if header[:2] == b"MZ" and len(header) >= 64:
        offset = struct.unpack_from("<I", header, 60)[0]
        if offset + 6 <= len(header) and header[offset:offset + 4] == b"PE\0\0" and struct.unpack_from("<H", header, offset + 4)[0] == 0x8664:
            return "windows-x64"
    raise ValidationFailure("native launcher binary has an unsupported machine header")


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400:
        raise ValidationFailure("native launcher build cache is unsafe")
    if os.name != "nt" and (metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077):
        raise ValidationFailure("native launcher build cache is not private")


def build_launcher(repository_root: Path | str, target: str, executable_override: Path | str | None = None) -> Path:
    """Build only the native host target; other OS assets need their own runner."""
    if target not in RUST_TARGETS or target != host_target():
        raise ValidationFailure("native launcher target requires its matching OS and architecture runner")
    override = executable_override or os.environ.get("ENGINEERING_ASSISTANT_LAUNCHER")
    if override:
        executable = Path(override).expanduser().absolute()
        if launcher_info(executable)["target"] != target:
            raise ValidationFailure("native launcher executable target does not match")
        return executable
    repository = Path(repository_root).resolve()
    crate = repository / "native/launcher"
    files = [crate / "Cargo.toml", crate / "Cargo.lock", *sorted((crate / "src").rglob("*.rs"))]
    digest = hashlib.sha256()
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise ValidationFailure("native launcher source or pinned Cargo.lock is missing")
        digest.update(path.relative_to(crate).as_posix().encode("utf-8") + b"\0" + path.read_bytes())
    source_digest = digest.hexdigest()
    user = hashlib.sha256(str(Path.home()).encode("utf-8")).hexdigest()[:16]
    cache = Path(tempfile.gettempdir()) / f"engineering-assistant-native-{user}"
    _private_directory(cache)
    output = cache / source_digest / target
    _private_directory(output)
    suffix = ".exe" if target == "windows-x64" else ""
    executable = output / RUST_TARGETS[target] / "release" / f"ea{suffix}"
    if executable.exists():
        information = launcher_info(executable)
        if information.get("target") == target and information.get("source_digest") == source_digest:
            return executable
        raise ValidationFailure("cached native launcher identity does not match its source")
    cargo = os.environ.get("ENGINEERING_ASSISTANT_CARGO") or shutil.which("cargo")
    if not cargo:
        raise ValidationFailure("building the native launcher requires Cargo on the developer or CI host")
    environment = dict(os.environ)
    environment.update(CARGO_TARGET_DIR=str(output), EA_LAUNCHER_TARGET=target,
                       EA_LAUNCHER_SOURCE_DIGEST=source_digest)
    try:
        subprocess.run([cargo, "build", "--locked", "--release", "--target", RUST_TARGETS[target],
                        "--manifest-path", str(crate / "Cargo.toml")], cwd=repository,
                       env=environment, stdin=subprocess.DEVNULL, capture_output=True,
                       timeout=300, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationFailure("native launcher compilation failed") from exc
    information = launcher_info(executable)
    if information.get("target") != target or information.get("source_digest") != source_digest:
        raise ValidationFailure("compiled native launcher identity does not match")
    return executable
