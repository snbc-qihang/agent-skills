"""Select a qualified Codex CLI without changing the user's Codex installation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import tarfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from .artifact_io import ArtifactIO, artifact_fs
from .catalog import DEFAULT_REPOSITORY_ROOT
from .native_launcher import _binary_target
from .validation import ValidationFailure


VERSION = "0.159.2"
TARGET_TRIPLES = {"macos-arm64": "aarch64-apple-darwin", "macos-x64": "x86_64-apple-darwin",
                  "windows-x64": "x86_64-pc-windows-msvc"}
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_DEPTH = 16
RECEIPT = ".ea-control.json"
ARCHIVE = ".download.tar.gz"


class ControlNeedsPreparation(ValidationFailure):
    """A read-only command found no qualified control executable."""


def host_target() -> str:
    from .installation import host_target as installation_target
    return installation_target()


def _pin(target: str) -> dict:
    if target not in TARGET_TRIPLES:
        raise ValidationFailure("Codex 控制 CLI 仅支持 macOS arm64/x64 与 Windows x64")
    source = ArtifactIO(DEFAULT_REPOSITORY_ROOT / "config", ".")
    try:
        pins, _ = source.read_json_limited(65536, "codex-control.json")
    finally:
        source.close()
    if (set(pins) != {"schema_version", "version", "targets"} or pins["schema_version"] != "1"
            or pins["version"] != VERSION or not isinstance(pins["targets"], dict)
            or set(pins["targets"]) != set(TARGET_TRIPLES)):
        raise ValidationFailure("Codex 控制 CLI 固定来源配置无效")
    for name, entry in pins["targets"].items():
        triple = TARGET_TRIPLES[name]
        url = f"https://releases.openai.com/codex/releases/{VERSION}/codex-package-{triple}.tar.gz"
        if (not isinstance(entry, dict) or set(entry) != {"target_triple", "url", "size_bytes", "sha256"}
                or entry["target_triple"] != triple or entry["url"] != url
                or type(entry["size_bytes"]) is not int or not 0 < entry["size_bytes"] <= MAX_ARCHIVE_BYTES
                or not isinstance(entry["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None):
            raise ValidationFailure("Codex 控制 CLI 固定来源配置无效")
    return pins["targets"][target]


def _candidates(target: str, home: Path) -> list[Path]:
    paths = []
    discovered = shutil.which("codex")
    if discovered:
        paths.append(Path(discovered))
    if target.startswith("macos-"):
        from .local_publish import _bundled_cli_candidates
        paths.extend(_bundled_cli_candidates("codex"))
    elif target == "windows-x64":
        if os.environ.get("LOCALAPPDATA"):
            paths.append(Path(os.environ["LOCALAPPDATA"]) / "Programs/OpenAI/Codex/bin/codex.exe")
        paths.extend((home / "packages/standalone/current/bin/codex.exe",
                      home / "packages/standalone/current/codex.exe"))
    return list(dict.fromkeys(path.expanduser().resolve() for path in paths if path.is_file()))


def _probe_cli(executable: Path, home: Path, target: str) -> None:
    from .installation import _protocol_run
    environment = {**os.environ, "CODEX_HOME": str(home)}
    cwd = home if home.is_dir() else Path.home()
    def run(arguments: list[str]) -> bytes:
        return _protocol_run([str(executable), *arguments], cwd=cwd, environment=environment, timeout=15)
    try:
        if not executable.is_absolute() or not executable.is_file() or _binary_target(executable) != target:
            raise ValueError
        if re.fullmatch(rb"codex(?:-cli)? 0\.159\.2\s*", run(["--version"])) is None:
            raise ValueError
        helps = [("plugin", ("add", "remove", "list", "marketplace")),
                 ("plugin marketplace", ("add", "list", "upgrade", "remove")),
                 ("plugin marketplace upgrade", ("Usage:",)), ("plugin marketplace remove", ("Usage:",)),
                 ("plugin add", ("--json",)), ("plugin remove", ("--json",)),
                 ("plugin list", ("--json", "--available", "--marketplace")),
                 ("plugin marketplace add", ("--json",)), ("plugin marketplace list", ("--json",))]
        for command, terms in helps:
            help_text = run([*command.split(), "--help"]).decode("utf-8")
            if any(term not in help_text for term in terms):
                raise ValueError
        for command, key in ((["plugin", "list", "--json"], "installed"),
                             (["plugin", "marketplace", "list", "--json"], "marketplaces")):
            result = json.loads(run(command))
            if (not isinstance(result, dict) or not isinstance(result.get(key), list)
                    or len(result[key]) > 4096 or any(not isinstance(entry, dict) for entry in result[key])):
                raise ValueError
    except (OSError, ValueError, RecursionError, ValidationFailure):
        # Native output can contain local configuration or authentication details.
        raise ValidationFailure("Codex 控制 CLI 的版本、架构或插件命令合同不兼容") from None


def _required(target: str) -> tuple[str, ...]:
    suffix = ".exe" if target == "windows-x64" else ""
    files = ("codex-package.json", "bin/codex" + suffix,
             "bin/codex-code-mode-host" + suffix, "codex-path/rg" + suffix)
    if suffix:
        files += ("codex-resources/codex-command-runner.exe", "codex-resources/codex-windows-sandbox-setup.exe")
    return files


def _file_hashes(storage: ArtifactIO) -> dict[str, str]:
    return storage.sha256_file_digests(exclude=frozenset({RECEIPT}), max_file_bytes=MAX_FILE_BYTES,
        max_entries=MAX_ENTRIES, max_total_bytes=MAX_TOTAL_BYTES)


def _assert_location(storage: ArtifactIO) -> None:
    path = storage.artifact_root
    try:
        if any(parent.is_symlink() or getattr(parent.lstat(), "st_file_attributes", 0) & 0x400
               for parent in (path, *path.parents)):
            raise ValueError
        with storage.open_directory() as descriptor:
            expected, actual = artifact_fs.fstat(descriptor), path.lstat()
        if not stat.S_ISDIR(actual.st_mode) or (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino):
            raise ValueError
    except (OSError, ValueError):
        raise ValidationFailure("Codex 控制 CLI 目录路径身份发生变化") from None


def _verify_cache(parent: ArtifactIO, target: str, pin: dict, home: Path) -> Path:
    try:
        with parent.open_directory(target) as descriptor:
            package = ArtifactIO.from_open_directory_fd(parent.path(target), descriptor)
        try:
            receipt, _ = package.read_json_limited(1048576, RECEIPT)
            if (set(receipt) != {"schema_version", "version", "target", "archive", "files"}
                    or receipt["schema_version"] != "1" or receipt["version"] != VERSION
                    or receipt["target"] != target or receipt["archive"] != pin
                    or not isinstance(receipt["files"], dict) or _file_hashes(package) != receipt["files"]
                    or any(not package.regular_file_exists(path) for path in _required(target))):
                raise ValueError
            executable = package.path(_required(target)[1])
            _assert_location(package)
            _probe_cli(executable, home, target)
            _assert_location(package)
            return executable
        finally:
            package.close()
    except (OSError, ValueError, RecursionError, ValidationFailure):
        raise ValidationFailure("Codex 控制 CLI 缓存 integrity 校验失败；保留原目录，需人工检查后再 repair") from None


def _download(stream, pin: dict) -> None:
    digest, size = hashlib.sha256(), 0
    deadline = time.monotonic() + 300
    try:
        with urlopen(Request(pin["url"], headers={"User-Agent": "engineering-assistant-setup"}), timeout=30) as response:
            length = response.headers.get("Content-Length")
            if response.geturl() != pin["url"] or (length is not None and int(length) != pin["size_bytes"]):
                raise ValueError
            while True:
                if time.monotonic() >= deadline:
                    raise ValueError
                chunk = response.read(min(1048576, pin["size_bytes"] - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > pin["size_bytes"] or size > MAX_ARCHIVE_BYTES:
                    raise ValueError
                digest.update(chunk)
                stream.write(chunk)
        if size != pin["size_bytes"] or digest.hexdigest() != pin["sha256"]:
            raise ValueError
        stream.flush()
        os.fsync(stream.fileno())
        stream.seek(0)
    except (OSError, ValueError, URLError):
        raise ValidationFailure("固定官方 Codex 控制 CLI 下载失败，或来源、大小、摘要不匹配") from None


def _member_parts(name: str) -> tuple[str, ...]:
    parts = tuple(name.rstrip("/").split("/"))
    if len(parts) > MAX_DEPTH or any(not part or part in {".", ".."} or part[-1:] in {".", " "}
            or re.search(r"[\\:<>\"?*|\x00-\x1f\x7f]", part)
            or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part) for part in parts):
        raise ValidationFailure("Codex 控制 CLI 归档包含不安全路径")
    return parts


def _extract(stream, storage: ArtifactIO) -> None:
    seen, total, count = set(), 0, 0
    deadline = time.monotonic() + 300
    try:
        with tarfile.open(fileobj=stream, mode="r|gz") as archive:
            for member in archive:
                count += 1
                parts = _member_parts(member.name)
                key = "/".join(parts).casefold()
                if (count > MAX_ENTRIES or key in seen or member.issparse()
                        or not (member.isdir() or member.isreg()) or time.monotonic() >= deadline):
                    raise ValueError
                seen.add(key)
                if member.isdir():
                    storage.ensure_directory(*parts)
                    continue
                total += member.size
                if member.size < 0 or member.size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or parts[0] in {ARCHIVE, RECEIPT}:
                    raise ValueError
                storage.ensure_directory(*parts[:-1])
                with storage.open_directory(*parts[:-1]) as parent:
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                    descriptor = artifact_fs.open(parts[-1], flags, 0o700 if member.mode & 0o111 else 0o600, dir_fd=parent)
                    with os.fdopen(descriptor, "wb") as output, archive.extractfile(member) as source:
                        remaining = member.size
                        while remaining:
                            chunk = source.read(min(1048576, remaining))
                            if not chunk or time.monotonic() >= deadline:
                                raise ValueError
                            output.write(chunk)
                            remaining -= len(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    artifact_fs.fsync(parent)
    except (OSError, ValueError, tarfile.TarError, EOFError):
        raise ValidationFailure("Codex 控制 CLI 归档不完整或超过安全解包边界") from None


def _prepare(parent: ArtifactIO, target: str, pin: dict, home: Path) -> Path:
    name = "." + target + "-staging-" + secrets.token_hex(8)
    path, descriptor, identity = parent.create_directory_exclusive_open(name)
    package = ArtifactIO.from_open_directory_fd(path, descriptor)
    artifact_fs.close(descriptor)
    published = False
    try:
        with package.open_directory() as directory:
            descriptor = artifact_fs.open(ARCHIVE, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                                          | getattr(os, "O_BINARY", 0), 0o600, dir_fd=directory)
        with os.fdopen(descriptor, "w+b") as stream:
            _download(stream, pin)
            _extract(stream, package)
        package.delete_regular_file(ARCHIVE)
        if any(not package.regular_file_exists(item) for item in _required(target)):
            raise ValidationFailure("官方 Codex 控制 CLI 归档缺少完整运行组件")
        if not parent.child_directory_matches(name, identity):
            raise ValidationFailure("Codex 控制 CLI staging 目录身份发生变化")
        _assert_location(package)
        _probe_cli(package.path(_required(target)[1]), home, target)
        _assert_location(package)
        package.create_immutable_json({"schema_version": "1", "version": VERSION, "target": target,
                                       "archive": pin, "files": _file_hashes(package)}, RECEIPT)
        parent.rename_child_directory_if_matches(name, target, identity)
        published = True
        return _verify_cache(parent, target, pin, home)
    finally:
        if not published:
            try:
                package.remove_all_contents()
                parent.remove_child_directory_if_matches(name, identity)
            except (OSError, ValidationFailure):
                pass
        package.close()


def resolve_codex_control(data: Path, home: Path, *, explicit: Path | None = None,
                          allow_download: bool = True) -> Path:
    """Return an absolute, qualified native CLI; readonly callers never prepare tools."""
    target = host_target()
    pin = _pin(target)
    data, home = data.expanduser().absolute(), home.expanduser().absolute()
    override = explicit or os.environ.get("CODEX_CLI")
    if override:
        executable = Path(override).expanduser().resolve()
        _probe_cli(executable, home, target)
        return executable
    for executable in _candidates(target, home):
        try:
            _probe_cli(executable, home, target)
            return executable
        except ValidationFailure:
            continue
    from .installation import _storage
    if not data.exists() and not allow_download:
        raise ControlNeedsPreparation("无兼容 Codex 控制 CLI；请先运行 install 或 repair 自动准备")
    storage = _storage(data)
    try:
        if storage.entry_exists("tools", "codex", VERSION, target):
            with storage.open_directory("tools", "codex", VERSION) as descriptor:
                parent = ArtifactIO.from_open_directory_fd(storage.path("tools", "codex", VERSION), descriptor)
            try:
                return _verify_cache(parent, target, pin, home)
            finally:
                parent.close()
        if not allow_download:
            raise ControlNeedsPreparation("无兼容 Codex 控制 CLI；请先运行 install 或 repair 自动准备")
        with storage.transaction("locks", "codex-control", VERSION, target):
            storage.ensure_directory("tools", "codex", VERSION)
            with storage.open_directory("tools", "codex", VERSION) as descriptor:
                parent = ArtifactIO.from_open_directory_fd(storage.path("tools", "codex", VERSION), descriptor)
            try:
                if parent.entry_exists(target):
                    return _verify_cache(parent, target, pin, home)
                return _prepare(parent, target, pin, home)
            finally:
                parent.close()
    finally:
        storage.close()
