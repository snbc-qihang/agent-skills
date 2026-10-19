"""Transactional Codex installation from a qualified internal Git release."""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

from . import installation as runtime
from ..runtime.artifact_io import ArtifactIO
from .internal_distribution import (
    MAX_ENTRIES, MAX_FILE_BYTES, MAX_TREE_BYTES, _tree_digest, acquire_internal_release,
)
from ..runtime.validation import ValidationFailure
from .legacy_installation import legacy_blocker, preflight_legacy_codex

MARKETPLACE = "engineering-assistant"


def _home_key(home: Path) -> str:
    return hashlib.sha256(str(home).encode()).hexdigest()


def _read_state(data: Path, home: Path) -> dict | None:
    path = data / "installations/codex" / _home_key(home) / "state.json"
    if not path.exists():
        return None
    state = runtime._read_control(path)
    if (state.get("schema_version") != "1" or state.get("home") != str(home)
            or state.get("marketplace") != MARKETPLACE or state.get("phase") not in {"active", "switching"}):
        raise ValidationFailure("内部安装记录无效；不能自动覆盖现有插件")
    return state


def pending_internal_installation(data: Path, home: Path) -> bool:
    state = _read_state(data, home)
    return state is not None and state["phase"] == "switching"


def _save_state(storage: ArtifactIO, state: dict, old: dict | None) -> dict:
    state = {**state, "revision": (old or {}).get("revision", 0) + 1}
    parts = ("installations", "codex", _home_key(Path(state["home"])), "state.json")
    if old is None:
        storage.create_immutable_json(state, *parts)
    else:
        storage.replace_json_cas(state, *parts, expected_revision=old["revision"])
    return state


def _market_parent(storage: ArtifactIO, home: Path) -> ArtifactIO:
    parts = ("marketplaces", "codex", _home_key(home))
    storage.ensure_directory(*parts)
    with storage.open_directory(*parts) as descriptor:
        return ArtifactIO.from_open_directory_fd(storage.path(*parts), descriptor)


def _copy_market(source: Path, parent: ArtifactIO) -> tuple[str, str]:
    name = "candidate-" + secrets.token_hex(12)
    parent.ensure_directory(name)
    with parent.open_directory(name) as descriptor:
        destination = ArtifactIO.from_open_directory_fd(parent.path(name), descriptor)
    origin = ArtifactIO(source, ".")
    try:
        digest = _tree_digest(origin)
        origin.copy_contents_to(destination, max_file_bytes=MAX_FILE_BYTES,
            max_entries=MAX_ENTRIES, max_total_bytes=MAX_TREE_BYTES)
        if _tree_digest(destination) != digest:
            raise ValidationFailure("复制后的内部市场摘要不一致")
        return name, digest
    finally:
        origin.close()
        destination.close()


def _select_market(home: Path, source: Path) -> None:
    entry = runtime._marketplace_entry("codex", home, MARKETPLACE)
    if entry is None:
        runtime._native_call("codex", ["plugin", "marketplace", "add", str(source), "--json"], home)
    else:
        runtime._verify_marketplace_source("codex", home, MARKETPLACE, str(source), source, required=True)
    runtime._verify_marketplace_source("codex", home, MARKETPLACE, str(source), source, required=True)
    runtime._native_call("codex", runtime._selection_arguments("codex", "install", MARKETPLACE), home)


def _restore(home: Path, data: Path, storage: ArtifactIO, parent: ArtifactIO, state: dict,
             uv_executable: Path | str | None = None) -> dict:
    previous = state.get("previous")
    try:
        if previous is None:
            selected = runtime._installed_identity("codex", home, MARKETPLACE)
            if selected is not None:
                actual = runtime._verified_package(selected["package"], "codex", selected["version"])
                if actual["payload_digest"] != state["candidate"]["package_payload_digest"]:
                    raise ValidationFailure("中断后的插件来源发生变化")
                runtime._native_call("codex", runtime._selection_arguments("codex", "uninstall", MARKETPLACE), home)
            if runtime._installed_identity("codex", home, MARKETPLACE) is not None:
                raise ValidationFailure("中断后的首次安装无法恢复未安装状态")
            if runtime._marketplace_entry("codex", home, MARKETPLACE) is not None:
                runtime._verify_marketplace_source("codex", home, MARKETPLACE, str(parent.path("current")),
                                                  parent.path("current"), required=True)
                runtime._native_call("codex", ["plugin", "marketplace", "remove", MARKETPLACE], home)
            if parent.entry_exists("current"):
                parent.rename_child_directory("current", "failed-" + secrets.token_hex(12))
            storage.delete_regular_file("installations", "codex", _home_key(home), "state.json")
            return {"status": "failed", "ready": False, "recovery_required": False,
                    "native_state": "not_installed", "reason": "安装失败，已恢复未安装状态"}
        backup = state["backup"]
        old_name = backup if parent.entry_exists(backup) else "current"
        with parent.open_directory(old_name) as descriptor:
            old = ArtifactIO.from_open_directory_fd(parent.path(old_name), descriptor)
        try:
            if _tree_digest(old) != previous["tree_sha256"]:
                raise ValidationFailure("上一版市场备份摘要不符")
            expected = runtime._verified_package(old.path("plugins", "engineering-assistant"), "codex")
            if expected["payload_digest"] != previous["package_payload_digest"]:
                raise ValidationFailure("上一版插件身份不符")
        finally:
            old.close()
        if old_name != "current":
            if parent.entry_exists("current"):
                parent.rename_child_directory("current", "failed-" + secrets.token_hex(12))
            parent.rename_child_directory(backup, "current")
        _select_market(home, parent.path("current"))
        selected = runtime._installed_identity("codex", home, MARKETPLACE)
        if selected is None or not selected["enabled"]:
            raise ValidationFailure("上一版插件未重新启用")
        actual = runtime._verified_package(selected["package"], "codex", selected["version"])
        if actual["payload_digest"] != previous["package_payload_digest"]:
            raise ValidationFailure("原生宿主未选回上一版")
        runtime.prepare_runtime(selected["package"], data_home=data, uv_executable=uv_executable)
        _save_state(storage, {"schema_version": "1", "home": str(home), "marketplace": MARKETPLACE,
                    "phase": "active", "current": previous}, state)
        return {"status": "failed", "ready": False, "recovery_required": False,
                "native_state": "previous_selection_restored", "reason": "更新失败，已重新安装并核对上一版插件"}
    except Exception:
        return {"status": "failed", "ready": False, "recovery_required": True,
                "native_state": "unverified", "reason": "原生插件恢复尚未完成；请执行 repair 并检查宿主状态"}


def install_internal_codex(*, home: Path | str | None = None, data_home: Path | str | None = None,
                           uv_executable: Path | str | None = None, hooks_trusted: bool = False,
                           update: bool = False, marketplace: str | None = None) -> dict:
    if marketplace not in {None, MARKETPLACE}:
        raise ValidationFailure("内部入口使用 engineering-assistant 市场；自定义来源请显式指定 --source")
    root, data = runtime.agent_home("codex", home), runtime.data_home(data_home)
    inspection = preflight_legacy_codex(root, data)
    blocked = legacy_blocker(inspection)
    if blocked is not None:
        return blocked
    storage = runtime._storage(data)
    parent = _market_parent(storage, root)
    try:
        with storage.transaction("locks", "installation-" + _home_key(root)):
            state = _read_state(data, root)
            if state and state["phase"] == "switching":
                recovery = _restore(root, data, storage, parent, state, uv_executable)
                if recovery["recovery_required"]:
                    return recovery
                state = _read_state(data, root)
            selected = runtime._installed_identity("codex", root)
            if selected and selected["marketplace"] != MARKETPLACE:
                raise ValidationFailure("已有其他市场的工程助手；请先明确管理该来源，内部入口不会创建重复插件")
            if update and selected is None:
                raise ValidationFailure("尚未安装内部插件，请先执行 install")
            if selected and state is None:
                raise ValidationFailure("现有插件不是内部入口管理的版本；请使用原来源的更新方式")
            if state is None and runtime._marketplace_entry("codex", root, MARKETPLACE) is not None:
                raise ValidationFailure("同名市场已有其他来源；内部入口不会覆盖该市场")
            release = acquire_internal_release(data, runtime.host_target())
            entry = release["entry"]
            previous = state["current"] if state else None
            if selected:
                actual = runtime._verified_package(selected["package"], "codex", selected["version"])
                if actual["payload_digest"] != previous["package_payload_digest"]:
                    raise ValidationFailure("宿主插件已在安装器之外改变；拒绝覆盖")
                if actual["payload_digest"] == entry["package_payload_digest"]:
                    runtime.prepare_runtime(selected["package"], data_home=data, uv_executable=uv_executable)
                    return {**runtime.doctor("codex", home=root, data_home=data, marketplace=MARKETPLACE,
                        hooks_trusted=hooks_trusted), "reused": True, "marketplace": MARKETPLACE,
                        "source_commit": release["source_commit"], "release_tag": release["release_tag"]}
                if actual["canonical_version"] == release["index"]["canonical_version"]:
                    raise ValidationFailure("同一产品版本不能替换不同内容")
                if not update:
                    return {"status": "needs_update", "ready": False, "reason": "已安装旧版，请执行 update"}
            candidate = release["source"] / "plugins/engineering-assistant"
            expected = runtime._verified_package(candidate, "codex")
            binding = runtime.prepare_runtime(candidate, data_home=data, uv_executable=uv_executable, publish_default=False)
            name, digest = _copy_market(release["source"], parent)
            if digest != entry["marketplace"]["tree_sha256"]:
                raise ValidationFailure("候选市场在准备过程中改变")
            candidate_record = {"canonical_version": release["index"]["canonical_version"],
                "source_commit": release["source_commit"], "release_tag": release["release_tag"],
                "package_payload_digest": expected["payload_digest"], "tree_sha256": digest}
            backup = "previous-" + secrets.token_hex(12) if previous else None
            journal = _save_state(storage, {"schema_version": "1", "home": str(root), "marketplace": MARKETPLACE,
                "phase": "switching", "previous": previous, "candidate": candidate_record,
                "backup": backup, "staging": name}, state)
            try:
                if previous:
                    with parent.open_directory("current") as descriptor:
                        current = ArtifactIO.from_open_directory_fd(parent.path("current"), descriptor)
                    try:
                        if _tree_digest(current) != previous["tree_sha256"]:
                            raise ValidationFailure("当前市场在更新之前改变")
                    finally:
                        current.close()
                    parent.rename_child_directory("current", backup)
                parent.rename_child_directory(name, "current")
                _select_market(root, parent.path("current"))
                result = runtime._verify_selection("codex", root, MARKETPLACE, expected,
                    data=data, hooks_trusted=hooks_trusted)
                if result["status"] not in {"ready", "needs_trust"}:
                    raise ValidationFailure("候选插件未通过安装后验证")
                runtime._publish_default_binding(data, binding)
                _save_state(storage, {"schema_version": "1", "home": str(root), "marketplace": MARKETPLACE,
                    "phase": "active", "current": candidate_record}, journal)
                return {**result, "source_commit": release["source_commit"], "release_tag": release["release_tag"],
                        "restart_required": True, "retained_runtime_environments": True}
            except Exception:
                # A CAS replacement can commit before its directory fsync fails.
                # Journal compensation against the observed revision, never a
                # stale revision that could leave active/native identities split.
                try:
                    observed = _read_state(data, root)
                    if observed != journal:
                        if (observed is None or observed["phase"] != "active"
                                or observed["current"] != candidate_record):
                            raise ValidationFailure("安装事务记录在恢复前改变")
                        recovery_state = {key: value for key, value in journal.items() if key != "revision"}
                        try:
                            journal = _save_state(storage, recovery_state, observed)
                        except Exception:
                            written = _read_state(data, root)
                            if (written is None
                                    or {key: value for key, value in written.items() if key != "revision"} != recovery_state):
                                raise ValidationFailure("无法记录安装恢复事务") from None
                            journal = written
                except Exception:
                    return {"status": "failed", "ready": False, "recovery_required": True,
                            "native_state": "unverified", "retained_runtime_environments": True,
                            "reason": "安装记录提交结果无法核验；请执行 repair 并检查宿主状态"}
                result = _restore(root, data, storage, parent, journal, uv_executable)
                return {**result, "retained_runtime_environments": True}
    finally:
        parent.close()
        storage.close()


def uninstall_internal_codex(data: Path, home: Path, marketplace: str | None = None) -> dict | None:
    """Retry native removal and market cleanup under the installation lock."""
    if marketplace not in {None, MARKETPLACE}:
        return None
    state = _read_state(data, home)
    if state is None:
        return None
    storage = runtime._storage(data)
    try:
        with storage.transaction("locks", "installation-" + _home_key(home)):
            state = _read_state(data, home)
            if state and state["phase"] == "switching":
                raise ValidationFailure("安装事务尚未恢复，请先执行 repair")
            if state:
                parent = _market_parent(storage, home)
                try:
                    entry = runtime._marketplace_entry("codex", home, MARKETPLACE)
                    if entry is not None:
                        runtime._verify_marketplace_source("codex", home, MARKETPLACE, str(parent.path("current")),
                                                          parent.path("current"), required=True)
                    selected = runtime._installed_identity("codex", home, MARKETPLACE)
                    if selected is not None:
                        actual = runtime._verified_package(selected["package"], "codex", selected["version"])
                        if actual["payload_digest"] != state["current"]["package_payload_digest"]:
                            raise ValidationFailure("现有插件与内部记录不符，拒绝自动卸载")
                        runtime.uninstall("codex", home=home, marketplace=MARKETPLACE)
                    if entry is not None:
                        runtime._native_call("codex", ["plugin", "marketplace", "remove", MARKETPLACE], home)
                        if runtime._marketplace_entry("codex", home, MARKETPLACE) is not None:
                            raise ValidationFailure("插件已卸载，但内部市场注销尚未核验")
                    if parent.entry_exists("current"):
                        parent.rename_child_directory("current", "uninstalled-" + secrets.token_hex(12))
                finally:
                    parent.close()
                storage.delete_regular_file("installations", "codex", _home_key(home), "state.json")
                return {"status": "uninstalled", "agent": "codex", "retained_runtime_environments": True}
            return None
    finally:
        storage.close()


def repair_internal_codex(*, home: Path | str | None = None, data_home: Path | str | None = None,
                          uv_executable: Path | str | None = None, hooks_trusted: bool = False) -> dict | None:
    root, data = runtime.agent_home("codex", home), runtime.data_home(data_home)
    state = _read_state(data, root)
    if state is None:
        return None
    storage = runtime._storage(data)
    parent = _market_parent(storage, root)
    try:
        with storage.transaction("locks", "installation-" + _home_key(root)):
            state = _read_state(data, root)
            if state["phase"] == "switching":
                recovered = _restore(root, data, storage, parent, state, uv_executable)
                if recovered["recovery_required"] or recovered["native_state"] == "not_installed":
                    return recovered
                state = _read_state(data, root)
            selected = runtime._installed_identity("codex", root, MARKETPLACE)
            if selected is None:
                raise ValidationFailure("原生插件已移除，请重新执行 install")
            actual = runtime._verified_package(selected["package"], "codex", selected["version"])
            if actual["payload_digest"] != state["current"]["package_payload_digest"]:
                raise ValidationFailure("现有插件与内部记录不符，拒绝自动修复")
            runtime.prepare_runtime(selected["package"], data_home=data, uv_executable=uv_executable, repair=True)
            return runtime.doctor("codex", home=root, data_home=data, marketplace=MARKETPLACE,
                                  hooks_trusted=hooks_trusted)
    finally:
        parent.close()
        storage.close()
