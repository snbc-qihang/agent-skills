"""Fetch one verified team Git release, without building consumer packages."""
from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import os
import re
import secrets
import shutil
import stat
import tarfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

from ..runtime.artifact_io import ArtifactIO, artifact_fs
from ..runtime.catalog import DEFAULT_REPOSITORY_ROOT
from .release_contract import (INTERNAL_TARGETS, MAX_CONTROL_BYTES as MAX_INDEX_BYTES,
    MAX_FILE_BYTES, MAX_TREE_BYTES, MAX_TREE_ENTRIES as MAX_ENTRIES)
from ..runtime.validation import ValidationFailure


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _tree_digest(storage: ArtifactIO) -> str:
    files = storage.sha256_file_digests(max_file_bytes=MAX_FILE_BYTES,
        max_entries=MAX_ENTRIES, max_total_bytes=MAX_TREE_BYTES)
    return _digest("\n".join(f"{name}:{digest}" for name, digest in sorted(files.items())).encode())


def internal_spec() -> dict:
    from .installation import _read_control
    spec = _read_control(DEFAULT_REPOSITORY_ROOT / "config/internal-distribution.json")
    if (spec.get("schema_version") != "1"
            or spec.get("repository_url") != "https://github.com/snbc-qihang/agent-skills.git"
            or spec.get("installer_ref") != "internal/installer"
            or spec.get("installer_tag_prefix") != "internal/installer/"
            or spec.get("release_tag_prefix") != "internal/codex/"
            or spec.get("marketplace") != "engineering-assistant"
            or spec.get("agents") != ["codex"] or tuple(spec.get("targets", [])) != INTERNAL_TARGETS):
        raise ValidationFailure("内部发行配置与已确认支持范围不符")
    return spec


def installer_source_commit(repository_url: str, installer_ref: str = "internal/installer", *,
                            version: str | None = None, installer_tag_prefix: str = "internal/installer/") -> str:
    """Use uv's actual PEP 610 origin, rather than trusting a version string."""
    try:
        if version is None:
            from .installation import _read_control
            version = _read_control(DEFAULT_REPOSITORY_ROOT / "catalog/skills/public.json")["version"]
        raw = importlib.metadata.distribution("engineering-assistant-kernel").read_text("direct_url.json")
        if raw is None or len(raw.encode()) > 65536:
            raise ValueError
        origin = json.loads(raw)
        vcs = origin.get("vcs_info", {})
        commit = vcs.get("commit_id")
        if (origin.get("url") != repository_url or vcs.get("vcs") != "git"
                or vcs.get("requested_revision") not in {installer_ref, installer_tag_prefix + version}
                or not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None):
            raise ValueError
        return commit
    except (OSError, ValueError, TypeError, AttributeError, importlib.metadata.PackageNotFoundError):
        raise ValidationFailure("无法核对安装器 Git 来源；请使用团队提供的固定 uvx 安装命令") from None


def _portable_parts(name: object) -> tuple[str, ...]:
    if not isinstance(name, str):
        raise ValidationFailure("发行文件路径无效")
    path = PurePosixPath(name)
    reserved = re.compile(r"^(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)", re.I)
    if (not name or not path.parts or path.is_absolute() or "\\" in name or len(path.parts) > 32
            or any(part.casefold() in {".", "..", ".git"} or part.endswith((".", " "))
                   or reserved.match(part) or any(ord(c) < 32 or c in ':<>"|?*' for c in part)
                   for part in path.parts)):
        raise ValidationFailure("发行文件路径不能跨平台安全使用")
    return path.parts


def _extract_git_archive(raw: bytes, destination: ArtifactIO) -> None:
    entries, total, seen = 0, 0, set()
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            for member in archive:
                entries += 1
                parts = _portable_parts(member.name.rstrip("/"))
                folded = unicodedata.normalize("NFC", "/".join(parts)).casefold()
                total += member.size
                if (entries > MAX_ENTRIES or total > MAX_TREE_BYTES or not 0 <= member.size <= MAX_FILE_BYTES
                        or folded in seen or not (member.isfile() or member.isdir())):
                    raise ValidationFailure("发行归档包含重复路径、链接、特殊文件或超限内容")
                seen.add(folded)
                if member.isdir():
                    destination.ensure_directory(*parts)
                else:
                    reader = archive.extractfile(member)
                    if reader is None:
                        raise ValidationFailure("发行归档文件无法读取")
                    payload = reader.read(member.size + 1)
                    if len(payload) != member.size:
                        raise ValidationFailure("发行归档文件长度不符")
                    destination.write_bytes_exclusive(payload, *parts,
                        mode=0o700 if member.mode & 0o111 else 0o600)
    except ValidationFailure:
        raise
    except (OSError, ValueError, tarfile.TarError, EOFError):
        raise ValidationFailure("内部发行归档无效或无法安全解包") from None


def _assert_location(storage: ArtifactIO) -> None:
    """Reject path replacement before invoking tools that require a pathname."""
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
        raise ValidationFailure("内部发行目录路径身份发生变化") from None


def _fetch_ref(repository_url: str, tag: str, staging: Path, storage: ArtifactIO) -> str:
    from .installation import _command
    git = shutil.which("git")
    if not git:
        raise ValidationFailure("请先安装 Git；公开发行下载无需 GitHub 登录")
    environment = {key: value for key, value in os.environ.items()
        if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_PARAMETERS",
                       "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR",
                       "GIT_NAMESPACE", "GIT_SHALLOW_FILE", "GIT_REPLACE_REF_BASE"}
        and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    environment.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_COUNT="0", GIT_NO_REPLACE_OBJECTS="1")
    # git archive applies working-tree conversions; user settings must not
    # rewrite the bytes bound by the immutable release's digests.
    prefix = [git, "-c", "core.autocrlf=false", "-c", "core.attributesFile=" + os.devnull,
              "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull, "-c", "init.templateDir="]
    storage.ensure_directory("git")
    cwd = staging / "git"
    try:
        with storage.open_directory("git") as descriptor:
            transport = ArtifactIO.from_open_directory_fd(cwd, descriptor)
        try:
            def command(arguments):
                _assert_location(storage)
                _assert_location(transport)
                result = _command([*prefix, *arguments], cwd=cwd, environment=environment)
                _assert_location(storage)
                _assert_location(transport)
                return result
            command(["init", "--bare", "."])
            command(["fetch", "--depth=1", "--no-tags", repository_url, "refs/tags/" + tag])
            revision = command(["rev-parse", "--verify", "FETCH_HEAD^{commit}"]).strip()
            if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
                raise ValidationFailure("内部发行 Git revision 无效")
            command(["archive", "--format=tar", "--output", str(staging / "release.tar"), revision])
        finally:
            transport.close()
        return revision
    except Exception:
        raise ValidationFailure("无法获取团队发行版本；请检查网络及该版本是否已发布，现有插件未切换") from None


def verify_release(storage: ArtifactIO, *, version: str, source_commit: str,
                   target: str, tag: str) -> tuple[dict, dict]:
    from .release_contract import _verify_candidate
    from .release_contract import validate_acceptance_summary
    if target not in INTERNAL_TARGETS:
        raise ValidationFailure("内部首轮发行目标无效")
    _assert_location(storage)
    try:
        expected, _ = storage.read_json_limited(MAX_INDEX_BYTES, "release-index.json")
        if (not isinstance(expected, dict) or expected.get("canonical_version") != version
                or expected.get("source_commit") != source_commit or expected.get("release_tag") != tag):
            raise ValidationFailure("安装器源码、发行版本或支持矩阵不一致")
        # Promotion and consumer/offline checks share the complete matrix,
        # archive, wheel and native package contract.
        index, raw = _verify_candidate(storage, allow_acceptance=True)
        if index != expected:
            raise ValidationFailure("内部发行索引在验证期间发生变化")
        summary = storage.read_json_limited(MAX_INDEX_BYTES, "acceptance-summary.json")[0]
        validate_acceptance_summary(index, raw, summary)
        entry = next(item for item in index["packages"] if item["target"] == target)
    except ValidationFailure:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, StopIteration, zipfile.BadZipFile):
        raise ValidationFailure("内部发行结构或文件无效，现有插件未切换") from None
    _assert_location(storage)
    return index, entry


def acquire_internal_release(data: Path, target: str) -> dict:
    from .installation import _read_control, _storage
    if target not in INTERNAL_TARGETS:
        raise ValidationFailure("内部首轮发行仅支持 macOS 14+ 与 Windows 11 x64")
    spec = internal_spec()
    version = _read_control(DEFAULT_REPOSITORY_ROOT / "catalog/skills/public.json")["version"]
    source_commit = installer_source_commit(spec["repository_url"], spec.get("installer_ref", "internal/installer"),
        version=version, installer_tag_prefix=spec.get("installer_tag_prefix", "internal/installer/"))
    tag = spec["release_tag_prefix"] + version
    key = hashlib.sha256((source_commit + ":" + tag).encode()).hexdigest()
    root = _storage(data)
    try:
        root.ensure_directory("distributions")
        with root.open_directory("distributions") as descriptor:
            parent = ArtifactIO.from_open_directory_fd(data / "distributions", descriptor)
        try:
            with root.transaction("locks", "distribution-" + key):
                if parent.entry_exists(key):
                    with parent.open_directory(key) as descriptor:
                        release = ArtifactIO.from_open_directory_fd(parent.path(key), descriptor)
                    try:
                        index, entry = verify_release(release, version=version, source_commit=source_commit,
                                                      target=target, tag=tag)
                    finally:
                        release.close()
                else:
                    name = ".staging-" + secrets.token_hex(12)
                    path, fd, identity = parent.create_directory_exclusive_open(name)
                    staging = ArtifactIO.from_open_directory_fd(path, fd)
                    artifact_fs.close(fd)
                    try:
                        _fetch_ref(spec["repository_url"], tag, path, staging)
                        raw = staging.read_bytes_limited(MAX_TREE_BYTES, "release.tar")
                        staging.ensure_directory("tree")
                        with staging.open_directory("tree") as tree_fd:
                            release = ArtifactIO.from_open_directory_fd(path / "tree", tree_fd)
                        try:
                            _extract_git_archive(raw, release)
                            index, entry = verify_release(release, version=version, source_commit=source_commit,
                                                          target=target, tag=tag)
                            # Publish only the verified tree; Git transport remains private staging.
                            final_name = ".verified-" + secrets.token_hex(12)
                            final_path, final_fd, final_identity = parent.create_directory_exclusive_open(final_name)
                            final = ArtifactIO.from_open_directory_fd(final_path, final_fd)
                            artifact_fs.close(final_fd)
                            published = False
                            try:
                                release.copy_contents_to(final, max_file_bytes=MAX_FILE_BYTES,
                                    max_entries=MAX_ENTRIES, max_total_bytes=MAX_TREE_BYTES)
                                verify_release(final, version=version, source_commit=source_commit, target=target, tag=tag)
                                parent.rename_child_directory_if_matches(final_name, key, final_identity)
                                published = True
                            finally:
                                try:
                                    if not published:
                                        final.remove_all_contents()
                                        parent.remove_child_directory_if_matches(final_name, final_identity)
                                finally:
                                    final.close()
                        finally:
                            release.close()
                    finally:
                        staging.remove_all_contents()
                        staging.close()
                        # Do not clean a staging name that another process replaced.
                        parent.remove_child_directory_if_matches(name, identity)
            return {"index": index, "entry": entry, "marketplace": spec["marketplace"],
                    "source": parent.path(key, *PurePosixPath(entry["marketplace"]["path"]).parts),
                    "source_commit": source_commit, "release_tag": tag}
        finally:
            parent.close()
    finally:
        root.close()
