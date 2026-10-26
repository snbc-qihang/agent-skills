"""Prepare a native Cowork import; account installation stays in Claude's UI."""
from __future__ import annotations

import hashlib
import io
import json
import re
import secrets
import zipfile
from pathlib import Path

from ..runtime.artifact_io import ArtifactIO, artifact_fs
from ..runtime.package import MAX_BUILD_PAYLOAD_FILE_BYTES
from ..runtime.validation import ValidationFailure
from . import installation as runtime
from .internal_distribution import _assert_location, _extract_git_archive, _fetch_ref, _portable_parts, _tree_digest
from .legacy_installation import installation_path_is_safe
from .release_contract import INTERNAL_REPOSITORY, MAX_FILE_BYTES, MAX_TREE_BYTES, MAX_TREE_ENTRIES, _safe_root

AGENT = "claude-cowork"
_ARCHIVE = "engineering-assistant.plugin"
_MAX_BYTES = 200 * 1024 * 1024


def _open(parent: ArtifactIO, *parts: str) -> ArtifactIO:
    with parent.open_directory(*parts) as descriptor:
        return ArtifactIO.from_open_directory_fd(parent.path(*parts), descriptor)


def _snapshot(storage: ArtifactIO) -> dict[str, str]:
    return storage.sha256_file_digests(max_file_bytes=MAX_FILE_BYTES,
        max_entries=MAX_TREE_ENTRIES, max_total_bytes=MAX_TREE_BYTES)


def _source(source: str, data: Path) -> tuple[Path, str | None, dict[str, str]]:
    local = Path(source).expanduser()
    if local.exists() or local.is_symlink():
        if not installation_path_is_safe(local):
            raise ValidationFailure("Cowork 来源路径不可包含符号链接或 reparse point")
        local = local.absolute()
        if local == runtime.DEFAULT_REPOSITORY_ROOT or runtime.DEFAULT_REPOSITORY_ROOT in local.parents:
            raise ValidationFailure("Cowork 来源必须是已构建发行，不能是作者源码")
        storage = _safe_root(local)
        try:
            return local, None, _snapshot(storage)
        finally:
            storage.close()
    prefix = INTERNAL_REPOSITORY + "@"
    if not source.startswith(prefix) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/._-]*", source[len(prefix):]) is None:
        raise ValidationFailure("Cowork 需要已构建目录或 snbc-qihang/agent-skills@tag 固定来源")
    tag = source[len(prefix):]
    key = hashlib.sha256(source.encode()).hexdigest()
    root = runtime._storage(data)
    try:
        root.ensure_directory("sources", AGENT)
        parent = _open(root, "sources", AGENT)
        try:
            if not parent.entry_exists(key):
                name = ".staging-" + secrets.token_hex(12)
                parent.ensure_directory(name)
                staging = _open(parent, name)
                try:
                    revision = _fetch_ref("https://github.com/" + INTERNAL_REPOSITORY + ".git", tag, staging.path(), staging)
                    raw = staging.read_bytes_limited(MAX_TREE_BYTES, "release.tar")
                    staging.ensure_directory("tree")
                    tree = _open(staging, "tree")
                    try:
                        _extract_git_archive(raw, tree)
                        digest = _tree_digest(tree)
                    finally:
                        tree.close()
                    staging.create_immutable_json({"source": source, "revision": revision, "tree_sha256": digest}, "receipt.json")
                    _assert_location(staging)
                    parent.rename_child_directory(name, key)
                finally:
                    staging.close()
            cached = _open(parent, key)
            try:
                receipt = cached.read_json_limited(65536, "receipt.json")[0]
                if (receipt.get("source") != source
                        or re.fullmatch(r"[0-9a-f]{40}", str(receipt.get("revision"))) is None):
                    raise ValidationFailure("Cowork 固定来源记录无效")
                tree = _open(cached, "tree")
                try:
                    files = _snapshot(tree)
                    digest = "sha256:" + hashlib.sha256("\n".join(
                        name + ":" + value for name, value in sorted(files.items())).encode()).hexdigest()
                    if digest != receipt.get("tree_sha256"):
                        raise ValidationFailure("Cowork 缓存来源内容已改变，请核对后重新取得候选")
                finally:
                    tree.close()
                return cached.path("tree"), receipt["revision"], files
            finally:
                cached.close()
        finally:
            parent.close()
    finally:
        root.close()


def _package(source: Path, files: dict[str, str]) -> tuple[Path, dict[str, str]]:
    if source == runtime.DEFAULT_REPOSITORY_ROOT or runtime.DEFAULT_REPOSITORY_ROOT in source.parents:
        raise ValidationFailure("Cowork 来源必须是已构建发行，不能是作者源码")
    storage = _safe_root(source)
    try:
        if "package-manifest.json" in files:
            return source, files
        raw = storage.read_bytes_limited(65536, ".claude-plugin", "marketplace.json")
        if "sha256:" + hashlib.sha256(raw).hexdigest() != files.get(".claude-plugin/marketplace.json"):
            raise ValidationFailure("Cowork 市场在来源快照之后改变")
        market = json.loads(raw)
        entries = [item for item in market.get("plugins", [])
                   if isinstance(item, dict) and item.get("name") == "engineering-assistant"]
        if len(entries) != 1:
            raise ValidationFailure("Cowork 市场必须包含唯一的 engineering-assistant 本地包")
        parts = _portable_parts(entries[0].get("source"))
        prefix = "/".join(parts) + "/"
        selected = {name[len(prefix):]: digest for name, digest in files.items() if name.startswith(prefix)}
        if "package-manifest.json" not in selected:
            raise ValidationFailure("Cowork 来源快照缺少目标包")
        with storage.open_directory(*parts):
            return storage.path(*parts), selected
    finally:
        storage.close()


def _archive(package: ArtifactIO, manifest: dict) -> bytes:
    names = [*manifest["payload_files"], "package-manifest.json"]
    if len(names) > 5000 or any(name.startswith("bin/") for name in names):
        raise ValidationFailure("Cowork 插件超出原生导入范围")
    output, total = io.BytesIO(), 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(names):
            raw = package.read_bytes_limited(MAX_BUILD_PAYLOAD_FILE_BYTES, *_portable_parts(name))
            if name == "package-manifest.json":
                if json.loads(raw) != manifest:
                    raise ValidationFailure("Cowork 构建清单在打包期间改变")
            elif "sha256:" + hashlib.sha256(raw).hexdigest() != manifest["payload_files"][name]:
                raise ValidationFailure("Cowork 插件字节在打包期间改变")
            total += len(raw)
            if total > _MAX_BYTES:
                raise ValidationFailure("Cowork 插件超过 200 MB 原生导入限制")
            entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            entry.create_system = 3
            executable = name in {"engineering-assistant/bin/ea", "engineering-assistant/bin/ea.exe"}
            entry.external_attr = (0o100755 if executable else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, raw)
    raw = output.getvalue()
    if len(raw) > _MAX_BYTES:
        raise ValidationFailure("Cowork 导入归档超过 200 MB 限制")
    return raw


def _state(storage: ArtifactIO) -> dict | None:
    try:
        state = storage.read_json_limited(65536, "installations", AGENT, "state.json")[0]
    except FileNotFoundError:
        return None
    if not isinstance(state, dict):
        raise ValidationFailure("Cowork 本机准备记录无效")
    current = state.get("current", {})
    if (state.get("schema_version") != "1" or state.get("agent") != AGENT
            or type(state.get("revision")) is not int or state["revision"] < 1
            or not isinstance(current, dict)
            or any(re.fullmatch(r"sha256:[0-9a-f]{64}", str(current.get(key))) is None
                   for key in ("payload_digest", "archive_sha256"))
            or not isinstance(current.get("source"), str)):
        raise ValidationFailure("Cowork 本机准备记录无效")
    return state


def _entry(storage: ArtifactIO, current: dict) -> Path:
    return storage.path("entries", AGENT, current["payload_digest"][7:])


def _verify_entry(storage: ArtifactIO, current: dict) -> Path:
    path = _entry(storage, current)
    owned = _safe_root(path)
    try:
        manifest = runtime._verified_package(owned.path("package"), "claude-code")
        raw = owned.read_bytes_limited(_MAX_BYTES, _ARCHIVE)
        if (manifest["payload_digest"] != current["payload_digest"]
                or hashlib.sha256(raw).hexdigest() != current["archive_sha256"][7:]):
            raise ValidationFailure("Cowork 入口或导入包已改变；请执行 repair，原内容不会被删除")
        return owned.path("package")
    finally:
        owned.close()


def _result(data: Path, storage: ArtifactIO, current: dict) -> dict:
    package = _verify_entry(storage, current)
    report = runtime.doctor("claude-code", package=package, data_home=data)
    prepared = report.get("runtime_ready") is True and report.get("provider_ready") is True and report.get("checks", {}).get("hook") == "passed"
    return {**report, "agent": AGENT, "data_home": str(data),
            "status": "needs_activation" if prepared else report["status"], "ready": False,
            "reason": "requires_native_import" if prepared else report.get("reason"),
            "installation_prepared": prepared, "native_discovery": "manual_import_required",
            "native_activation": "not_verified", "host_acceptance": "not_executed",
            "import_package": str(_entry(storage, current) / _ARCHIVE),
            "source_revision": current.get("source_revision"),
            "next_steps": ["打开 Claude 桌面端 Customize → Plugins → Add → Upload plugin，选择上述导入包",
                           "在 Claude 中审查并启用插件及所需连接器，启动新的 Cowork 任务",
                           "实际验证 Skills、MCP、Hook 和任务恢复；本机准备不代表 Cowork 验收通过"]}


def prepare_cowork(*, source: str | None, data_home=None, uv_executable=None,
                   update: bool = False, repair: bool = False, publish_default: bool = True) -> dict:
    data = runtime.data_home(data_home)
    if not installation_path_is_safe(data):
        raise ValidationFailure("Cowork 共享数据目录路径不安全")
    if not source and not (data / "installations" / AGENT / "state.json").exists():
        return {"status": "needs_preparation", "ready": False, "agent": AGENT,
                "reason": "Cowork 正式发行尚未推广，请使用维护者提供的 --source 固定候选来源"}
    storage = runtime._storage(data)
    try:
        with storage.transaction("locks", "cowork-install"):
            state = _state(storage)
            previous = state["current"] if state else None
            if not source:
                if not previous:
                    return {"status": "needs_preparation", "ready": False, "agent": AGENT,
                            "reason": "Cowork 正式发行尚未推广，请使用维护者提供的 --source 固定候选来源"}
                source = previous["source"]
            origin, revision, source_files = _source(source, data)
            package, expected_files = _package(origin, source_files)
            expected = runtime._verified_package(package, "claude-code")
            origin_io = _safe_root(package)
            try:
                if _snapshot(origin_io) != expected_files:
                    raise ValidationFailure("Cowork 包与已核对来源快照不一致")
            finally:
                origin_io.close()
            if expected["target"] != runtime.host_target():
                raise ValidationFailure("Cowork 原生包与当前操作系统或架构不符")
            if previous and previous["payload_digest"] != expected["payload_digest"] and not (update or repair):
                return {"status": "needs_update", "ready": False, "reason": "已有其他 Cowork 候选，请使用 update --source"}
            if previous and previous["payload_digest"] == expected["payload_digest"] and not repair:
                selected = _verify_entry(storage, previous)
                runtime.prepare_runtime(selected, data_home=data, uv_executable=uv_executable, publish_default=publish_default)
                return {**_result(data, storage, previous), "reused": True}
            storage.ensure_directory("entries", AGENT)
            parent = _open(storage, "entries", AGENT)
            try:
                name = ".staging-" + secrets.token_hex(12)
                path, descriptor, identity = parent.create_directory_exclusive_open(name)
                staging = ArtifactIO.from_open_directory_fd(path, descriptor)
                artifact_fs.close(descriptor)
                staging.ensure_directory("package")
                destination, original = _open(staging, "package"), _safe_root(package)
                try:
                    original.copy_contents_to(destination, max_file_bytes=MAX_BUILD_PAYLOAD_FILE_BYTES,
                                              max_entries=5000, max_total_bytes=_MAX_BYTES)
                    if _snapshot(destination) != expected_files:
                        raise ValidationFailure("Cowork 复制结果与已核对来源快照不一致")
                    _assert_location(staging)
                    copied = runtime._verified_package(destination.path(), "claude-code")
                    if copied["payload_digest"] != expected["payload_digest"]:
                        raise ValidationFailure("Cowork 候选在复制期间改变")
                    raw = _archive(destination, copied)
                    staging.write_bytes_exclusive(raw, _ARCHIVE)
                    _assert_location(staging)
                    _assert_location(destination)
                    if _snapshot(destination) != expected_files or runtime._verified_package(destination.path(), "claude-code") != copied:
                        raise ValidationFailure("Cowork 待准备入口与来源合同不一致")
                    runtime.prepare_runtime(destination.path(), data_home=data, uv_executable=uv_executable,
                                            repair=repair, publish_default=publish_default)
                    _assert_location(staging)
                    _assert_location(destination)
                    if _snapshot(destination) != expected_files:
                        raise ValidationFailure("Cowork 入口在 Runtime 准备期间改变")
                    current = {"payload_digest": copied["payload_digest"], "canonical_version": copied["canonical_version"],
                               "target": copied["target"], "archive_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                               "source": source, "source_revision": revision}
                    final = current["payload_digest"][7:]
                    retained, old_identity = None, None
                    if parent.entry_exists(final):
                        if not repair:
                            _verify_entry(storage, current)
                        else:
                            retained = "retained-" + secrets.token_hex(12)
                            with parent.open_directory(final) as old:
                                old_identity = artifact_fs.fstat(old)
                            parent.rename_child_directory_if_matches(final, retained, old_identity)
                    record = {"schema_version": "1", "agent": AGENT, "revision": (state or {}).get("revision", 0) + 1,
                              "current": current}
                    try:
                        if not parent.entry_exists(final):
                            parent.rename_child_directory_if_matches(name, final, identity)
                        _verify_entry(storage, current)
                        parts = ("installations", AGENT, "state.json")
                        if state:
                            storage.replace_json_cas(record, *parts, expected_revision=state["revision"])
                        else:
                            storage.create_immutable_json(record, *parts)
                    except Exception:
                        # A committed CAS acknowledgement can be lost. Never
                        # rewind a valid committed selection against old state.
                        if retained and _state(storage) != record:
                            if parent.child_directory_matches(final, identity):
                                parent.rename_child_directory_if_matches(final,
                                    "failed-" + secrets.token_hex(12), identity)
                            if not parent.entry_exists(final):
                                parent.rename_child_directory_if_matches(retained, final, old_identity)
                        raise
                finally:
                    original.close()
                    destination.close()
                    staging.close()
            finally:
                parent.close()
            return _result(data, storage, current)
    finally:
        storage.close()


def inspect_cowork(data_home=None) -> dict:
    data = runtime.data_home(data_home)
    if not data.exists():
        return {"status": "needs_preparation", "ready": False, "agent": AGENT, "data_home": str(data)}
    storage = _safe_root(data)
    try:
        state = _state(storage)
        if not state:
            return {"status": "needs_preparation", "ready": False, "agent": AGENT, "data_home": str(data)}
        return _result(data, storage, state["current"])
    finally:
        storage.close()


def uninstall_cowork() -> dict:
    return {"status": "needs_native_action", "ready": False, "agent": AGENT,
            "native_activation": "not_verified", "retained_runtime_environments": True,
            "reason": "Cowork 插件属于 Claude 账号，需在原生界面移除；本命令未宣称卸载完成",
            "next_steps": ["在 Claude 桌面端 Customize → Plugins 中找到 engineering-assistant 并选择 Remove",
                           "共享核心、导入包和其他 Agent 入口保留"]}
