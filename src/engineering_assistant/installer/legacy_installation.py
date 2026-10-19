"""Bounded, read-only inventory for the user's manual removal of Codex 2.x."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from . import installation as runtime
from ..runtime.artifact_io import ArtifactIO, artifact_fs
from ..platforms.codex_control import ControlNeedsPreparation
from ..runtime.validation import ValidationFailure
from ..runtime.version import CanonicalVersion, platform_version

MAX_ENTRIES = 256
MAX_TOTAL_ENTRIES = 2048
MAX_CONTROL_BYTES = 65536


def _default_data_home() -> Path:
    return runtime.data_home(environment={key: value for key, value in os.environ.items()
                                         if key != "ENGINEERING_ASSISTANT_DATA_HOME"})


def installation_path_is_safe(path: Path | str) -> bool:
    """Reject unreadable/link/reparse ancestors before any native dispatch."""
    path = Path(path).expanduser().absolute()
    try:
        for parent in (path, *path.parents):
            try:
                metadata = parent.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                return False
        return True
    except OSError:
        return False


def inspect_legacy_codex(home: Path | str, data: Path | str) -> dict:
    """Inspect selected state without installation/configuration writes.

    Native inventory commands may initialize their own temporary CLI work area;
    this function never prepares tools or executes an old plugin Runtime.
    """
    home, data = Path(home).expanduser().absolute(), Path(data).expanduser().absolute()
    confirmed, unknown, scope, steps = [], [], [], []
    visited, findings, total = set(), set(), 0

    def problem(kind: str, path: Path | None, reason: str) -> None:
        item = {"kind": kind, "reason": reason}
        if path is not None:
            item["path"] = str(path)
        if item not in unknown:
            unknown.append(item)

    def safe(path: Path) -> bool:
        if not installation_path_is_safe(path):
            problem("unsafe_path", path, "路径不可读或含符号链接/reparse point；未跟随，需人工核对")
            return False
        return True

    def read(path: Path) -> dict | None:
        if not safe(path):
            return None
        try:
            path.lstat()
        except FileNotFoundError:
            return None
        except OSError:
            problem("unreadable", path, "无法检查该已知位置")
            return None
        storage = None
        try:
            storage = ArtifactIO(path.parent, ".")
            payload = storage.read_json_limited(MAX_CONTROL_BYTES, path.name)[0]
            if not isinstance(payload, dict):
                raise ValidationFailure("control metadata must be an object")
            return payload
        except (OSError, ValueError, RecursionError, ValidationFailure):
            problem("invalid_metadata", path, "元数据损坏、不可读或超限；不回显内容")
            return None
        finally:
            if storage is not None:
                storage.close()

    def children(path: Path) -> list[Path]:
        nonlocal total
        if not safe(path):
            return []
        storage = None
        try:
            if not path.exists():
                return []
            storage = ArtifactIO(path, ".")
            result = []
            with storage.open_directory() as descriptor, artifact_fs.scandir(descriptor) as entries:
                for entry in entries:
                    total += 1
                    if len(result) >= MAX_ENTRIES or total > MAX_TOTAL_ENTRIES:
                        problem("scan_limit", path, "检查超过有界数量；未完成部分需人工核对")
                        break
                    result.append(path / entry.name)
            return result
        except (OSError, ValidationFailure):
            problem("unreadable", path, "无法完整检查该已知目录")
            return []
        finally:
            if storage is not None:
                storage.close()

    def directory(path: Path) -> bool:
        try:
            metadata = path.lstat()
            return stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)
        except OSError:
            problem("unreadable", path, "无法核对目录项身份")
            return False

    def found(kind: str, path: Path, version: str, marketplace: str | None = None) -> None:
        key = (kind, str(path))
        if key in findings:
            return
        findings.add(key)
        item = {"kind": kind, "path": str(path), "version": version}
        if marketplace:
            item["marketplace"] = marketplace
        confirmed.append(item)
        if kind == "native_plugin":
            steps.append({"action": "native_uninstall", "command": ["codex", "plugin", "remove",
                          "engineering-assistant@" + marketplace, "--json"],
                          "instruction": "沿用检查所选 CODEX_HOME，由用户执行原生卸载，再核对 plugin list --json"})
        else:
            steps.append({"action": "manual_cleanup", "path": str(path),
                          "instruction": "停止旧会话后，由用户核对并清理该已归属 Codex 2.x 项；安装器不删除或接管"})

    def old(version: object) -> bool:
        return isinstance(version, str) and re.fullmatch(r"2\.[0-9A-Za-z.+-]+", version) is not None

    def valid_canonical(version: object) -> bool:
        if not isinstance(version, str):
            return False
        try:
            CanonicalVersion.parse(version)
            return True
        except ValueError:
            return False

    def versions_match(canonical: object, installed: object) -> bool:
        if not isinstance(canonical, str) or not isinstance(installed, str):
            return False
        try:
            mapped = platform_version(canonical, supports_four_part=False)
        except ValueError:
            return False
        # Historical local publishing deliberately replaced build metadata with
        # a timestamp cachebuster; its release core must still agree.
        return installed in (canonical, mapped) or re.fullmatch(
            re.escape(mapped.partition("+")[0]) + r"\+codex\.local-[0-9]{8}-[0-9]{6}", installed) is not None

    def package(path: Path, kind: str) -> None:
        if str(path) in visited or not safe(path) or not path.exists():
            return
        visited.add(str(path))
        if kind == "local_source" and (path / "catalog").is_dir() and (path / "src").is_dir():
            problem("author_source", path, "该来源是作者源码，不能作为删除目标；仅核对旧市场登记")
            return
        manifest = read(path / "package-manifest.json")
        plugin = read(path / ".codex-plugin/plugin.json")
        version = manifest.get("canonical_version") if manifest else plugin.get("version") if plugin else None
        if (manifest and manifest.get("platform") != "codex") or (plugin and plugin.get("name") != "engineering-assistant"):
            problem("unattributed_package", path, "该目录不能归属为 Codex 工程助手；不提供删除命令")
        elif manifest is not None and plugin is not None and not versions_match(version, plugin.get("version")):
            problem("package_identity_conflict", path, "包清单与插件版本身份不一致；仅人工核对，不假定可删除")
        elif not manifest and not plugin or not isinstance(version, str):
            problem("unattributed_package", path, "孤儿目录缺少有效包身份；需人工核对，不假定可删除")
        elif old(version):
            found(kind, path, version)

    def local_market(root: Path) -> None:
        manifest_path = root / ".agents/plugins/marketplace.json"
        manifest = read(manifest_path)
        if manifest is None:
            return
        entries = manifest.get("plugins")
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            problem("marketplace_metadata", manifest_path, "市场清单合同无效或超限")
            return
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("name") != "engineering-assistant":
                continue
            source = entry.get("source")
            location = source.get("path") if isinstance(source, dict) and source.get("source") == "local" else None
            if not isinstance(location, str) or ".." in Path(location).parts:
                problem("local_source", manifest_path, "本插件本地来源身份不可安全解析；仅人工核对该条目")
                continue
            path = Path(location)
            path = path if path.is_absolute() else root / path
            if safe(path) and not path.exists():
                problem("orphan_marketplace_entry", manifest_path, "本插件本地来源已缺失；仅人工核对该市场条目")
                step = {"action": "edit_marketplace_entry", "path": str(manifest_path),
                        "instruction": "由用户核对并移除 engineering-assistant 的失效来源条目，保留共享市场与其他插件"}
                if step not in steps:
                    steps.append(step)
            else:
                package(path, "local_source")

    scope.append({"kind": "codex_home", "path": str(home)})
    safe_home, safe_data = safe(home), safe(data)
    owned_markets = {"personal", "engineering-assistant"}
    commands = ((["plugin", "list", "--json"], "installed"),
                (["plugin", "marketplace", "list", "--json"], "marketplaces")) if safe_home and safe_data else ()
    with runtime.native_control(data, allow_download=False):
        for command, key in commands:
            try:
                payload = runtime._native_query("codex", command, home)
                entries = payload.get(key) if isinstance(payload, dict) else None
                if not isinstance(entries, list) or len(entries) > MAX_ENTRIES or any(not isinstance(item, dict) for item in entries):
                    raise ValidationFailure("unsupported inventory")
                for entry in entries:
                    if key == "installed":
                        if entry.get("name") != "engineering-assistant" or entry.get("installed") is not True:
                            continue
                        market, version = entry.get("marketplaceName"), entry.get("version")
                        market = runtime._component(market, "marketplace")
                        owned_markets.add(market)
                        version = runtime._component(version, "version")
                        if entry.get("pluginId", "engineering-assistant@" + market) != "engineering-assistant@" + market:
                            raise ValidationFailure("contradictory plugin identity")
                        path = home / "plugins/cache" / market / "engineering-assistant" / version
                        if old(version):
                            found("native_plugin", path, version, market)
                    else:
                        source = entry.get("marketplaceSource")
                        if isinstance(source, dict) and source.get("sourceType") == "local":
                            location = entry.get("root")
                            if not isinstance(location, str) or not Path(location).is_absolute() or ".." in Path(location).parts:
                                raise ValidationFailure("unsafe marketplace root")
                            local_market(Path(location))
            except ControlNeedsPreparation:
                problem("native_cli_missing", home, "缺少兼容控制 CLI；原生清单尚未核对，install 可自动准备工具后复查")
                break
            except (OSError, ValueError, ValidationFailure):
                problem("native_inventory", home, "原生清单不可验证；未回显宿主输出，需检查 CLI 与所选 CODEX_HOME")
                break

    for market in children(home / "plugins/cache"):
        if not directory(market):
            continue
        metadata = market.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            if market.name in owned_markets:
                safe(market)
            continue
        for version in children(market / "engineering-assistant"):
            package(version, "plugin_cache")
    local_market(home.parent)
    publish_root = home.parent / "plugins"
    scope.append({"kind": "local_publish", "path": str(publish_root / "engineering-assistant")})
    for path in children(publish_root):
        if path.name == "engineering-assistant" or path.name.startswith((".engineering-assistant.backup-", ".engineering-assistant.failed-")):
            package(path, "publish_backup" if path.name.startswith(".") else "published_package")

    for root in dict.fromkeys((data, _default_data_home())):
        scope.append({"kind": "runtime_data", "path": str(root)})
        bindings = [root / "bindings/codex.json", *children(root / "bindings/codex")]
        for path in bindings:
            if path.name == ".artifact.lock" and safe(path):
                try:
                    storage = ArtifactIO(path.parent, ".")
                    try:
                        # Windows byte-range locking initializes one zero digit.
                        if storage.read_bytes_limited(1, path.name) in (b"", b"0"):
                            continue
                    finally:
                        storage.close()
                except (OSError, ValidationFailure):
                    problem("invalid_metadata", path, "无法核对内部锁文件")
            if path.suffix != ".json":
                problem("binding_metadata", path, "绑定目录含未知项；需人工核对")
                continue
            binding = read(path)
            if binding is None:
                continue
            agent = binding.get("agent")
            if isinstance(agent, str) and agent and agent != "codex":
                continue
            if agent != "codex" or not valid_canonical(binding.get("canonical_version")):
                problem("binding_metadata", path, "Codex 绑定缺少有效身份；需人工核对，不假定可删除")
            elif old(binding.get("canonical_version")):
                found("runtime_binding", path, binding["canonical_version"])
        for path in children(root / "environments"):
            if not directory(path):
                continue
            record = read(path / "runtime-environment.json")
            if (not record or not isinstance(record.get("agent"), str) or not record["agent"]
                    or record["agent"] == "codex" and not valid_canonical(record.get("canonical_version"))):
                problem("unattributed_environment", path, "Runtime 目录缺少有效身份；需人工核对，不假定可删除")
            elif record["agent"] == "codex" and old(record.get("canonical_version")):
                found("runtime_environment", path, record["canonical_version"])
        key = hashlib.sha256(str(home).encode()).hexdigest()
        state_path = root / "installations/codex" / key / "state.json"
        state = read(state_path)
        if state is not None:
            roles = ("candidate", "previous") if state.get("phase") == "switching" and "current" not in state else ("current", "previous", "candidate")
            records = [state.get(roles[0]), *(state[role] for role in roles[1:] if state.get(role) is not None)]
            if (state.get("home") != str(home) or any(not isinstance(item, dict)
                    or not valid_canonical(item.get("canonical_version")) for item in records)):
                problem("installation_metadata", state_path, "所选 Codex 安装记录缺少有效身份；需人工核对，不假定可删除")
            else:
                versions = [item["canonical_version"] for item in records]
                if any(old(version) for version in versions):
                    found("installation_record", state_path, next(version for version in versions if old(version)))
        for market in children(root / "marketplaces/codex" / key):
            if market.name == "current" or market.name.startswith(("previous-", "failed-", "uninstalled-")):
                package(market / "plugins/engineering-assistant", "managed_market_backup")

    if confirmed:
        steps.append({"action": "verify_removal", "command": ["codex", "plugin", "list", "--json"],
                      "instruction": "只移除本插件登记；共享 personal 市场、其他插件、Python 基底、作者源码及项目 .run-artifacts 不在清理范围"})
    if unknown:
        steps.append({"action": "manual_review", "instruction": "先核对未知项；检查不完整时不能宣称历史清理已完成，不执行通配符删除"})
    if any(item["kind"] == "native_cli_missing" for item in unknown):
        steps.append({"action": "app_uninstall", "instruction": "可先在 Codex App 插件管理中按旧来源卸载工程助手；CLI 可用时再执行列出的原生命令，不要求另装 CLI"})
    return {"legacy_installation_detected": bool(confirmed), "legacy_check_complete": not unknown,
            "legacy_scope": scope, "legacy_confirmed": confirmed, "legacy_unknown": unknown,
            "legacy_manual_steps": steps}


def legacy_blocker(report: dict) -> dict | None:
    if report["legacy_installation_detected"] or not report["legacy_check_complete"]:
        return {**report, "status": "needs_preparation", "ready": False,
                "reason": "发现历史 Codex 2.x，请按指导自行卸载与清理后复查" if report["legacy_installation_detected"]
                          else "历史安装检查不完整，请先核对未知项；缺少控制 CLI 时 install 可自动准备后复查"}
    return None


def preflight_legacy_codex(home: Path, data: Path) -> dict:
    """A clean filesystem may prepare only missing control tools, then recheck."""
    report = inspect_legacy_codex(home, data)
    if (not report["legacy_installation_detected"] and report["legacy_unknown"]
            and all(item["kind"] == "native_cli_missing" for item in report["legacy_unknown"])):
        # The outer installer context permits the existing fixed control-tool
        # preparation; no distribution, Runtime or marketplace is created here.
        with runtime.native_control(data, allow_download=True):
            runtime._native_query("codex", ["plugin", "list", "--json"], home)
        report = inspect_legacy_codex(home, data)
    return report
