"""Owned Cursor local-plugin entries; never edits user MCP/Hook configuration."""
from __future__ import annotations

import os
import re
import secrets
import shutil
from pathlib import Path

from ..runtime.artifact_io import ArtifactIO, artifact_fs
from ..runtime.package import MAX_BUILD_PAYLOAD_FILE_BYTES
from ..runtime.validation import ValidationFailure
from . import installation as runtime
from .legacy_installation import installation_path_is_safe

_NAME = "engineering-assistant"
_CONTROL = ".engineering-assistant-installer"


def _state(control: ArtifactIO) -> dict | None:
    try:
        state = control.read_json_limited(65536, "state.json")[0]
    except FileNotFoundError:
        return None
    if (not isinstance(state, dict) or state.get("schema_version") != "1" or state.get("agent") != "cursor"
        or state.get("phase") not in {"active", "switching", "removing", "uninstalled"}):
        raise ValidationFailure("Cursor local plugin ownership record is invalid")
    return state


def _save(control: ArtifactIO, value: dict) -> None:
    previous = _state(control)
    record = {**value, "schema_version": "1", "agent": "cursor", "revision": (previous or {}).get("revision", 0) + 1}
    if previous is None:
        control.create_immutable_json(record, "state.json")
    else:
        control.replace_json_cas(record, "state.json", expected_revision=previous["revision"])


def cursor_selection(home: Path) -> dict | None:
    package = home / "plugins/local" / _NAME
    if not installation_path_is_safe(package):
        raise ValidationFailure("Cursor local plugin path is unsafe")
    record = home / "plugins" / _CONTROL / "state.json"
    if not record.exists():
        if package.exists() or package.is_symlink():
            raise ValidationFailure("Cursor 同名本地插件不由本安装器管理，请先在宿主核对来源")
        return None
    control = ArtifactIO(record.parent, ".")
    try:
        state = _state(control)
    finally:
        control.close()
    if state["phase"] in {"switching", "removing"}:
        raise ValidationFailure("Cursor 安装被中断，请执行 repair；需要核对本地入口后才能继续")
    if state["phase"] == "uninstalled":
        if package.exists() or package.is_symlink():
            raise ValidationFailure("Cursor 本地目录与卸载记录冲突")
        return None
    actual = runtime._verified_package(package, "cursor")
    if actual["payload_digest"] != state["current"]["payload_digest"]:
        raise ValidationFailure("Cursor 本地插件与受控安装记录不一致")
    version = runtime._read_control(package / ".cursor-plugin/plugin.json")["version"]
    # File presence proves registration, not that policy allows local imports,
    # or that another marketplace installation has not taken precedence.
    return {"package": package, "version": version, "marketplace": "local", "enabled": False}


def _restore_previous(native: ArtifactIO, control: ArtifactIO, state: dict) -> None:
    backup, previous = state.get("backup"), state.get("previous")
    if not isinstance(backup, str) or re.fullmatch(r"retained-[0-9a-f]{24}", backup) is None:
        raise ValidationFailure("invalid Cursor recovery path")
    active = native.path("local", _NAME)
    present = native.entry_exists("local", _NAME)
    if present:
        digest = runtime._verified_package(active, "cursor")["payload_digest"]
        if previous and digest == previous["payload_digest"]:
            _save(control, {"phase": "active", "current": previous})
            return
        if digest != state["current"]["payload_digest"]:
            raise ValidationFailure("Cursor active entry is not owned by this transaction")
    if previous:
        retained = native.path(".engineering-assistant-staging", backup)
        if runtime._verified_package(retained, "cursor")["payload_digest"] != previous["payload_digest"]:
            raise ValidationFailure("Cursor backup differs from its recorded entry")
    if present:
        with native.open_directory("local") as src, native.open_directory(".engineering-assistant-staging") as dst:
            artifact_fs.rename(_NAME, "failed-" + secrets.token_hex(12), src_dir_fd=src, dst_dir_fd=dst)
    if previous:
        with native.open_directory(".engineering-assistant-staging") as src, native.open_directory("local") as dst:
            artifact_fs.rename(backup, _NAME, src_dir_fd=src, dst_dir_fd=dst)
        _save(control, {"phase": "active", "current": previous})
    else:
        _save(control, {"phase": "uninstalled"})


def _source_package(source: str, data: Path) -> Path:
    local = Path(source).expanduser()
    if local.exists():
        if not installation_path_is_safe(local):
            raise ValidationFailure("Cursor 发行来源不可包含符号链接或 reparse point")
        local = local.absolute()
    else:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9/._-]*", source) is None:
            raise ValidationFailure("Cursor 需要已构建目录或 owner/repo@ref 固定发行来源")
        repository, ref = source.split("@", 1)
        git = shutil.which("git")
        if not git:
            raise ValidationFailure("Git prerequisite is unavailable")
        storage = runtime._storage(data)
        try:
            local = storage.ensure_directory("source-checkouts", "cursor-" + secrets.token_hex(12))
        finally:
            storage.close()
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
                           GIT_NO_REPLACE_OBJECTS="1", GIT_OPTIONAL_LOCKS="0")
        prefix = [git, "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false",
                  "-c", "protocol.file.allow=never", "-c", "protocol.ext.allow=never"]
        runtime._command([*prefix, "init", "--template="], cwd=local, environment=environment)
        runtime._command([*prefix, "fetch", "--depth=1", "--no-tags", "https://github.com/" + repository + ".git", ref],
                         cwd=local, environment=environment)
        runtime._command([*prefix, "checkout", "--detach", "FETCH_HEAD"], cwd=local, environment=environment)
    if (local / "package-manifest.json").exists():
        package = local
    else:
        market = runtime._read_control(local / ".cursor-plugin/marketplace.json")
        entries = [item for item in market.get("plugins", []) if isinstance(item, dict) and item.get("name") == _NAME]
        if len(entries) != 1 or not isinstance(entries[0].get("source"), str):
            raise ValidationFailure("Cursor marketplace requires one local engineering-assistant package")
        relative = Path(entries[0]["source"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValidationFailure("Cursor marketplace package must remain inside its source")
        package = local / relative
    if package == runtime.DEFAULT_REPOSITORY_ROOT or runtime.DEFAULT_REPOSITORY_ROOT in package.parents:
        raise ValidationFailure("Cursor install source must be a built distribution, not the author repository")
    runtime._verified_package(package, "cursor")
    return package


def _result(home: Path, data, hooks_trusted: bool) -> dict:
    result = runtime.doctor("cursor", home=home, data_home=data, hooks_trusted=hooks_trusted)
    return {**result, "restart_required": True, "native_registration": "local_plugin_directory",
            "host_acceptance": "not_executed", "usage_observation": "requires_real_host_tool_use_id_coverage", "next_steps": [
                "重开 Cursor 或执行 Developer: Reload Window",
                "在 Customize 核对 engineering-assistant 的 skills、MCP 与 Hook；确认允许本地插件导入，且无同名市场插件覆盖",
                "完成真实 MCP、Hook、恢复和 Provider 验收后再报告该宿主可用"],
            "retained_runtime_environments": True}


def install_cursor(*, source: str | None, home: Path, data=None, uv=None, hooks_trusted: bool = False,
                   update: bool = False, package: Path | str | None = None) -> dict:
    if not installation_path_is_safe(home):
        raise ValidationFailure("Cursor native home is unsafe")
    plugins = home / "plugins"
    ancestor = next(path for path in (plugins, *plugins.parents) if path.exists())
    root = ArtifactIO(ancestor, ".")
    try:
        root.assert_runtime_target(runtime.DEFAULT_REPOSITORY_ROOT / "schemas")
        root.ensure_directory(*plugins.relative_to(ancestor).parts)
    finally:
        root.close()
    native = ArtifactIO(plugins, ".")
    native.ensure_directory(_CONTROL)
    control = ArtifactIO(plugins / _CONTROL, ".")
    try:
        with control.transaction("cursor-install"):
            state = _state(control)
            if state and state["phase"] in {"switching", "removing"}:
                return {"status": "failed", "ready": False, "recovery_required": True, "reason": "Cursor 安装事务待 repair 恢复"}
            selected = cursor_selection(home)
            if update and selected is None:
                raise ValidationFailure("Cursor 插件尚未安装，请先执行 install")
            source = str(package) if package else source or (state or {}).get("current", {}).get("source")
            if not source:
                raise ValidationFailure("Cursor 需要显式 --source 发行来源")
            candidate = _source_package(source, runtime.data_home(data))
            expected = runtime._verified_package(candidate, "cursor")
            runtime.prepare_runtime(candidate, data_home=data, uv_executable=uv)
            previous = state["current"] if selected else None
            if previous and previous["payload_digest"] == expected["payload_digest"]:
                return {**_result(home, data, hooks_trusted), "reused": True}
            if selected and not update:
                return {"status": "needs_update", "ready": False, "reason": "已有不同版本，请使用 update --package 或已记录发行来源"}
            stage_name = secrets.token_hex(12)
            stage = native.ensure_directory(".engineering-assistant-staging", stage_name)
            original, staged = ArtifactIO(candidate, "."), ArtifactIO(stage, ".")
            try:
                original.copy_contents_to(staged, max_file_bytes=MAX_BUILD_PAYLOAD_FILE_BYTES,
                                         max_entries=4096, max_total_bytes=256 * 1024 * 1024)
            finally:
                staged.close()
                original.close()
            if runtime._verified_package(stage, "cursor")["payload_digest"] != expected["payload_digest"]:
                raise ValidationFailure("Cursor candidate changed while copying")
            native.ensure_directory("local")
            backup = "retained-" + secrets.token_hex(12)
            current = {"payload_digest": expected["payload_digest"], "source": source}
            journal = {"phase": "switching", "current": current, "previous": previous, "stage": stage_name, "backup": backup}
            _save(control, journal)
            try:
                with native.open_directory("local") as local_fd, native.open_directory(".engineering-assistant-staging") as staging_fd:
                    if previous:
                        artifact_fs.rename(_NAME, backup, src_dir_fd=local_fd, dst_dir_fd=staging_fd)
                    artifact_fs.rename(stage_name, _NAME, src_dir_fd=staging_fd, dst_dir_fd=local_fd)
                if runtime._verified_package(plugins / "local" / _NAME, "cursor")["payload_digest"] != expected["payload_digest"]:
                    raise ValidationFailure("Cursor selected package differs from its candidate")
                _save(control, {"phase": "active", "current": current})
            except Exception:
                try:
                    # A write may have committed before reporting an I/O error.
                    observed = _state(control)
                    if observed["phase"] == "active" and observed["current"] == current:
                        return _result(home, data, hooks_trusted)
                    _restore_previous(native, control, journal)
                    return {"status": "failed", "ready": False, "recovery_required": False,
                            "reason": "Cursor 入口切换失败，已恢复之前的受控入口", "retained_runtime_environments": True,
                            "native_state": "previous_entry_restored" if previous else "not_installed"}
                except Exception:
                    pass
                return {"status": "failed", "ready": False, "recovery_required": True,
                        "reason": "Cursor 本地入口切换未核验；旧入口和 Runtime 已保留，请执行 repair"}
            return _result(home, data, hooks_trusted)
    finally:
        control.close()
        native.close()


def repair_cursor(home: Path, *, data=None, uv=None, hooks_trusted: bool = False) -> dict:
    native = ArtifactIO(home / "plugins", ".")
    control = ArtifactIO(home / "plugins" / _CONTROL, ".")
    try:
        with control.transaction("cursor-install"):
            state = _state(control)
            if not state or state["phase"] == "uninstalled":
                raise ValidationFailure("Cursor 插件尚未安装")
            if state["phase"] == "switching":
                _restore_previous(native, control, state)
                if not state.get("previous"):
                    return {"status": "needs_preparation", "ready": False,
                            "reason": "中断的首次安装已恢复未安装状态，请重新执行 install"}
            elif state["phase"] == "removing":
                backup = state.get("backup")
                if not isinstance(backup, str) or re.fullmatch(r"uninstalled-[0-9a-f]{24}", backup) is None:
                    raise ValidationFailure("invalid Cursor uninstall recovery path")
                path = native.path("local", _NAME) if native.entry_exists("local", _NAME) else native.path(".engineering-assistant-staging", backup)
                if runtime._verified_package(path, "cursor")["payload_digest"] != state["current"]["payload_digest"]:
                    raise ValidationFailure("Cursor uninstall recovery entry differs from its record")
                if not native.entry_exists("local", _NAME):
                    _save(control, {"phase": "uninstalled"})
                    return {"status": "uninstalled", "agent": "cursor", "retained_runtime_environments": True}
                _save(control, {"phase": "active", "current": state["current"]})
            selected = cursor_selection(home)
            runtime.prepare_runtime(selected["package"], data_home=data, uv_executable=uv, repair=True)
            return _result(home, data, hooks_trusted)
    except Exception as exc:
        return {"status": "failed", "ready": False, "recovery_required": True, "reason": str(exc)}
    finally:
        control.close()
        native.close()


def uninstall_cursor(home: Path) -> dict:
    native = ArtifactIO(home / "plugins", ".")
    control = ArtifactIO(home / "plugins" / _CONTROL, ".")
    try:
        with control.transaction("cursor-install"):
            selected = cursor_selection(home)
            if selected is None:
                raise ValidationFailure("Cursor 插件尚未安装")
            native.ensure_directory(".engineering-assistant-staging")
            backup = "uninstalled-" + secrets.token_hex(12)
            _save(control, {"phase": "removing", "current": _state(control)["current"], "backup": backup})
            with native.open_directory("local") as src, native.open_directory(".engineering-assistant-staging") as dst:
                artifact_fs.rename(_NAME, backup, src_dir_fd=src, dst_dir_fd=dst)
            _save(control, {"phase": "uninstalled"})
        return {"status": "uninstalled", "agent": "cursor", "restart_required": True,
                "retained_runtime_environments": True, "retained_native_backup": True}
    finally:
        control.close()
        native.close()
