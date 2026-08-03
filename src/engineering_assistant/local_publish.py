"""安全地构建并安装本机 Codex/Hermes 插件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .catalog import load_catalog
from .artifact_io import ArtifactIO
from .compiler import (
    MAX_BUILD_MANIFEST_BYTES,
    MAX_BUILD_PAYLOAD_FILE_BYTES,
    build_package,
    verify_package,
)
from .eval_runner import run_evals
from .official_validation import validate_with_official_tools
from .validation import ValidationFailure


PLUGIN_NAME = "teamwork-engineering-assistant"
DEFAULT_POLICY = "config/local-publish-policy.json"
CODEX_CACHE_MARKETPLACE = "personal"
MAX_CODEX_CACHE_CANDIDATES = 512
MAX_CODEX_CACHE_ENTRIES = 4096
MAX_CODEX_CACHE_TOTAL_BYTES = 256 * 1024 * 1024
RUNTIME_CACHE_IGNORED_NAMES = frozenset({"__pycache__", ".DS_Store"})
RUNTIME_CACHE_IGNORED_SUFFIXES = (".pyc",)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _cachebuster() -> str:
    return datetime.now(timezone.utc).strftime("local-%Y%m%d-%H%M%S")


def _load_policy(path: Path, platforms: list[str]) -> dict:
    if not path.is_file():
        raise ValidationFailure(f"缺少本机发布策略：{path}")
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("enabled") is not True:
        raise ValidationFailure("本机发布策略未启用")
    allowed = set(policy.get("platforms", []))
    missing = sorted(set(platforms) - allowed)
    if missing:
        raise ValidationFailure(f"本机发布策略未允许平台：{', '.join(missing)}")
    if policy.get("requires_explicit_yes") is not True:
        raise ValidationFailure("本机发布策略必须要求显式 --yes")
    if policy.get("stable_release_allowed") is True:
        raise ValidationFailure("本机发布策略不能放行稳定版")
    if policy.get("product_repository_changes_allowed") is True:
        raise ValidationFailure("本机发布策略不能放行产品仓库修改")
    return policy


def _run_repository_preflight(repository_root: Path) -> dict:
    environment = dict(os.environ)
    source_root = str(repository_root / "src")
    environment["PYTHONPATH"] = source_root + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=repository_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValidationFailure("仓库测试失败：\n" + completed.stdout + completed.stderr)
    catalog = load_catalog(repository_root, require_sources=True)
    evaluation = run_evals(repository_root)
    official_validation = validate_with_official_tools(
        repository_root,
        validate_plugin=False,
    )
    return {
        "tests": "passed",
        "source_validation": "passed",
        "source_skill_count": len(catalog.skills),
        "official_validation": official_validation,
        "version": evaluation["version"],
        "routing_cases": evaluation["routing"]["case_count"],
        "routing_top1_accuracy": evaluation["routing"]["top1_accuracy"],
        "unconfirmed_high_risk_writes": evaluation["routing"]["unconfirmed_high_risk_writes"],
        "simulation": evaluation["simulation"],
        "canary": evaluation["canary"],
        "canary_gate": {
            "scope": "local_prerelease",
            "required": False,
            "status": "not_required_for_local_prerelease",
        },
    }


def _ensure_outside_repository(repository_root: Path, target: Path) -> None:
    try:
        target.resolve().relative_to(repository_root.resolve())
    except ValueError:
        return
    raise ValidationFailure(f"本地安装目录不能位于作者源仓库内：{target}")


def _marketplace_payload(existing: dict) -> dict:
    entry = {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }
    plugins = []
    replaced = False
    for plugin in existing.get("plugins", []):
        if plugin.get("name") == PLUGIN_NAME:
            plugins.append(entry)
            replaced = True
        else:
            plugins.append(plugin)
    if not replaced:
        plugins.append(entry)
    return {
        **existing,
        "name": existing.get("name", "personal"),
        "interface": existing.get("interface", {"displayName": "Personal"}),
        "plugins": plugins,
    }


def _update_personal_marketplace(path: Path) -> tuple[bytes | None, bool]:
    previous = path.read_bytes() if path.is_file() else None
    existing = json.loads(previous.decode("utf-8")) if previous is not None else {}
    if existing and existing.get("name") != "personal":
        raise ValidationFailure(f"默认 marketplace 名称不是 personal：{path}")
    payload = (json.dumps(_marketplace_payload(existing), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if payload == previous:
        return previous, False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
    return previous, True


def _marketplace_contains_plugin(payload: bytes | None) -> bool:
    if payload is None:
        return False
    try:
        marketplace = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return any(plugin.get("name") == PLUGIN_NAME for plugin in marketplace.get("plugins", []))


def _restore_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_name(path.name + ".rollback.tmp")
    temporary.write_bytes(previous)
    os.replace(temporary, path)


def _swap_in(staging: Path, target: Path, stamp: str) -> Path | None:
    backup = target.parent / f".{target.name}.backup-{stamp}"
    if backup.exists():
        raise FileExistsError(f"备份目录已存在：{backup}")
    if target.exists():
        os.replace(target, backup)
    else:
        backup = None
    try:
        os.replace(staging, target)
    except Exception:
        if backup is not None:
            os.replace(backup, target)
        raise
    return backup


def _roll_back(target: Path, backup: Path | None, stamp: str) -> Path | None:
    failed = None
    if target.exists():
        failed = target.parent / f".{target.name}.failed-{stamp}"
        os.replace(target, failed)
    if backup is not None:
        os.replace(backup, target)
    return failed


def _bundled_cli_candidates(command: str) -> list[Path]:
    if command != "codex" or sys.platform != "darwin":
        return []
    return [
        Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
        Path("/Applications/Codex.app/Contents/Resources/codex"),
        Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex",
        Path.home() / "Applications/Codex.app/Contents/Resources/codex",
    ]


def _resolve_platform_cli(command: str, environment: dict[str, str] | None = None) -> str:
    environment = dict(os.environ) if environment is None else environment
    override_name = f"{command.upper()}_CLI"
    override = environment.get(override_name)
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        raise ValidationFailure(f"{override_name} 指向的文件不存在或不可执行：{candidate}")

    executable = shutil.which(command, path=environment.get("PATH"))
    if executable is not None:
        return executable

    for candidate in _bundled_cli_candidates(command):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())

    raise ValidationFailure(
        f"找不到平台 CLI：{command}。请将其加入 PATH，或通过 {override_name} 指定可执行文件"
    )


def _run_registration(command: list[str], environment: dict[str, str] | None = None) -> dict:
    environment = dict(os.environ) if environment is None else environment
    executable = _resolve_platform_cli(command[0], environment)
    completed = subprocess.run(
        [executable, *command[1:]],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise ValidationFailure(f"平台注册失败：{' '.join(command)}\n{completed.stdout}{completed.stderr}")
    output = completed.stdout.strip()
    try:
        return json.loads(output) if output else {"status": "passed"}
    except json.JSONDecodeError:
        return {"status": "passed", "output": output}


def _target_for(platform: str, codex_home: Path, hermes_home: Path) -> Path:
    if platform == "codex":
        return codex_home.parent / "plugins" / PLUGIN_NAME
    return hermes_home / "plugins" / PLUGIN_NAME


def _codex_cache_root(codex_home: Path) -> Path:
    return codex_home / "plugins/cache" / CODEX_CACHE_MARKETPLACE / PLUGIN_NAME


def _package_version_from_io(package_io: ArtifactIO) -> str | None:
    try:
        manifest, _raw = package_io.read_json_limited(
            MAX_BUILD_MANIFEST_BYTES,
            ".codex-plugin",
            "plugin.json",
        )
        version = manifest["version"]
    except (FileNotFoundError, KeyError, TypeError, ValidationFailure):
        return None
    if not isinstance(version, str) or re.fullmatch(
        r"[0-9A-Za-z][0-9A-Za-z.+-]*",
        version,
    ) is None:
        return None
    return version


def _package_version(package_root: Path) -> str | None:
    if package_root.is_symlink() or not package_root.is_dir():
        return None
    package_io = None
    try:
        package_io = ArtifactIO(package_root, ".")
        return _package_version_from_io(package_io)
    except (OSError, ValidationFailure):
        return None
    finally:
        if package_io is not None:
            package_io.close()


def _copy_clean_package_from_io(source_io: ArtifactIO, destination: Path) -> None:
    destination_io = None
    try:
        destination.mkdir()
        destination_io = ArtifactIO(destination, ".")
        source_io.copy_contents_to(
            destination_io,
            max_file_bytes=MAX_BUILD_PAYLOAD_FILE_BYTES,
            max_entries=MAX_CODEX_CACHE_ENTRIES,
            max_total_bytes=MAX_CODEX_CACHE_TOTAL_BYTES,
            ignored_names=RUNTIME_CACHE_IGNORED_NAMES,
            ignored_suffixes=RUNTIME_CACHE_IGNORED_SUFFIXES,
        )
        verify_package(destination)
    except Exception:
        if destination_io is not None:
            destination_io.close()
            destination_io = None
        if destination.is_symlink() or destination.exists():
            shutil.rmtree(destination)
        raise
    finally:
        if destination_io is not None:
            destination_io.close()


def _copy_clean_package(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise ValidationFailure(f"拒绝从符号链接恢复插件 cache：{source}")
    source_io = None
    try:
        source_io = ArtifactIO(source, ".")
        _copy_clean_package_from_io(source_io, destination)
    except Exception:
        if source_io is not None:
            source_io.close()
            source_io = None
        raise
    finally:
        if source_io is not None:
            source_io.close()


def _snapshot_codex_caches(codex_home: Path, snapshot_root: Path) -> list[str]:
    versions: list[str] = []
    if codex_home.is_symlink() or not codex_home.is_dir():
        return versions
    codex_io = ArtifactIO(codex_home, ".")
    cache_io = None
    try:
        try:
            with codex_io.open_directory(
                "plugins",
                "cache",
                CODEX_CACHE_MARKETPLACE,
                PLUGIN_NAME,
            ) as cache_fd:
                cache_root = _codex_cache_root(codex_home)
                cache_io = ArtifactIO.from_open_directory_fd(cache_root, cache_fd)
        except FileNotFoundError:
            return versions
        candidates: list[tuple[int, str]] = []
        with cache_io.open_directory() as cache_fd:
            entry_count = 0
            with os.scandir(cache_fd) as entries:
                for entry in entries:
                    entry_count += 1
                    if entry_count > MAX_CODEX_CACHE_CANDIDATES:
                        raise ValidationFailure("Codex cache 候选数量超出安全上限")
                    metadata = os.stat(
                        entry.name,
                        dir_fd=cache_fd,
                        follow_symlinks=False,
                    )
                    if not stat.S_ISDIR(metadata.st_mode):
                        continue
                    try:
                        with cache_io.open_directory(entry.name) as candidate_fd:
                            candidate_io = ArtifactIO.from_open_directory_fd(
                                cache_root / entry.name,
                                candidate_fd,
                            )
                        try:
                            if _package_version_from_io(candidate_io) == entry.name:
                                candidates.append((metadata.st_mtime_ns, entry.name))
                        finally:
                            candidate_io.close()
                    except (OSError, ValidationFailure):
                        continue
        selected = sorted(candidates, reverse=True)
        for _mtime, name in sorted(selected, key=lambda item: item[1]):
            with cache_io.open_directory(name) as source_fd:
                source_io = ArtifactIO.from_open_directory_fd(
                    _codex_cache_root(codex_home) / name,
                    source_fd,
                )
            try:
                if _package_version_from_io(source_io) != name:
                    raise ValidationFailure(f"Codex cache 版本在快照前发生变化：{name}")
                _copy_clean_package_from_io(source_io, snapshot_root / name)
            finally:
                source_io.close()
            versions.append(name)
        return versions
    finally:
        if cache_io is not None:
            cache_io.close()
        codex_io.close()


def _restore_codex_cache_snapshots(codex_home: Path, snapshot_root: Path) -> list[str]:
    cache_root = _codex_cache_root(codex_home)
    restored: list[str] = []
    if not snapshot_root.is_dir():
        return restored
    cache_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(snapshot_root.iterdir()):
        if not source.is_dir() or _package_version(source) != source.name:
            continue
        destination = cache_root / source.name
        if destination.exists():
            expected = verify_package(source)
            try:
                _verify_codex_cache_version(codex_home, source.name, expected)
            except (OSError, ValidationFailure):
                quarantine = cache_root / f".{source.name}.corrupt-{_stamp()}"
                if quarantine.is_symlink() or quarantine.exists():
                    raise ValidationFailure(f"Codex cache 隔离目标已存在：{quarantine}")
                cache_io = ArtifactIO(cache_root, ".")
                try:
                    with cache_io.open_directory() as cache_fd:
                        os.rename(
                            source.name,
                            quarantine.name,
                            src_dir_fd=cache_fd,
                            dst_dir_fd=cache_fd,
                        )
                        os.fsync(cache_fd)
                finally:
                    cache_io.close()
            else:
                continue
        temporary = Path(tempfile.mkdtemp(prefix=f".{source.name}.restore-", dir=cache_root))
        temporary.rmdir()
        _copy_clean_package(source, temporary)
        os.replace(temporary, destination)
        restored.append(source.name)
    return restored


def _verify_codex_cache_version(
    codex_home: Path,
    version: str,
    expected: dict,
) -> dict:
    codex_io = ArtifactIO(codex_home, ".")
    cache_io = None
    try:
        with codex_io.open_directory(
            "plugins",
            "cache",
            CODEX_CACHE_MARKETPLACE,
            PLUGIN_NAME,
        ) as cache_root_fd:
            cache = _codex_cache_root(codex_home) / version
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            cache_fd = os.open(version, flags, dir_fd=cache_root_fd)
            try:
                opened_cache = os.fstat(cache_fd)
                if not stat.S_ISDIR(opened_cache.st_mode):
                    raise ValidationFailure("Codex 注册 cache 版本不是目录")
                cache_io = ArtifactIO.from_open_directory_fd(cache, cache_fd)
            finally:
                os.close(cache_fd)
            registered_manifest, _raw = cache_io.read_json_limited(
                MAX_BUILD_MANIFEST_BYTES,
                "package-manifest.json",
            )
            if registered_manifest != expected:
                raise ValidationFailure("Codex 注册 cache manifest 与发布目标不一致")
            actual = cache_io.sha256_file_digests(
                exclude=frozenset({"package-manifest.json"}),
                max_file_bytes=MAX_BUILD_PAYLOAD_FILE_BYTES,
                max_entries=MAX_CODEX_CACHE_ENTRIES,
                max_total_bytes=MAX_CODEX_CACHE_TOTAL_BYTES,
            )
            if actual != expected["payload_files"]:
                raise ValidationFailure("Codex 注册 cache 与发布目标 payload 不一致")
            digest = hashlib.sha256(
                "\n".join(f"{path}:{value}" for path, value in actual.items()).encode("utf-8")
            ).hexdigest()
            if f"sha256:{digest}" != expected["payload_digest"]:
                raise ValidationFailure("Codex 注册 cache 与发布目标摘要不一致")
            current_cache = os.stat(
                version,
                dir_fd=cache_root_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(current_cache.st_mode)
                or (current_cache.st_dev, current_cache.st_ino)
                != (opened_cache.st_dev, opened_cache.st_ino)
            ):
                raise ValidationFailure("Codex 注册 cache 版本目录在校验期间发生替换")
            return {
                "path": str(cache),
                "plugin_version": version,
                "payload_digest": expected["payload_digest"],
            }
    finally:
        if cache_io is not None:
            cache_io.close()
        codex_io.close()


def _repair_codex_cache_version(codex_home: Path, target: Path, version: str) -> Path:
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]*", version):
        raise ValidationFailure(f"非法 Codex 插件版本：{version}")
    destination = _codex_cache_root(codex_home) / version
    if destination.is_dir():
        with tempfile.TemporaryDirectory(prefix=f".{PLUGIN_NAME}-cache-verify-") as temporary:
            clean = Path(temporary) / version
            _copy_clean_package(destination, clean)
        return destination
    if destination.exists():
        raise ValidationFailure(f"Codex cache 目标不是目录：{destination}")

    candidates = [target, *sorted(target.parent.glob(f".{target.name}.backup-*"), reverse=True)]
    source = next((candidate for candidate in candidates if _package_version(candidate) == version), None)
    if source is None:
        raise ValidationFailure(f"没有找到版本 {version} 的已校验本机发布包或备份")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{version}.repair-", dir=destination.parent))
    temporary.rmdir()
    _copy_clean_package(source, temporary)
    os.replace(temporary, destination)
    return destination


def _verify_codex_registered_cache(codex_home: Path, target: Path) -> dict:
    version = _installed_platform_version(target, "codex")
    published = verify_package(target)
    try:
        return _verify_codex_cache_version(codex_home, version, published)
    except FileNotFoundError as exc:
        cache = _codex_cache_root(codex_home) / version
        raise ValidationFailure(f"Codex 注册后缺少已构建版本 cache：{cache}") from exc
    except OSError as exc:
        cache = _codex_cache_root(codex_home) / version
        raise ValidationFailure(f"Codex 注册 cache 不是安全目录：{cache}") from exc


def _codex_plugin_entry(payload: object) -> dict | None:
    pending = [payload]
    while pending:
        current = pending.pop()
        if isinstance(current, list):
            pending.extend(current)
        elif isinstance(current, dict):
            name = current.get("name") or current.get("plugin_name")
            if name == PLUGIN_NAME:
                return current
            pending.extend(current.values())
    return None


def _verify_selected_codex_version(payload: object, expected_version: str) -> dict:
    entry = _codex_plugin_entry(payload)
    if entry is None:
        raise ValidationFailure("codex plugin list 未返回本次插件")
    selected = entry.get("version") or entry.get("plugin_version")
    if selected != expected_version:
        raise ValidationFailure(
            f"Codex 选择版本不一致：expected={expected_version}, actual={selected}"
        )
    return entry


def _prune_codex_cache_versions(codex_home: Path, keep_version: str) -> list[str]:
    cache_root = _codex_cache_root(codex_home)
    if not cache_root.is_dir():
        raise ValidationFailure("Codex 注册后缺少插件 cache 根目录")
    cache_io = ArtifactIO(cache_root, ".")
    removed = []
    try:
        for path in sorted(cache_root.iterdir()):
            if path.name == keep_version:
                if path.is_symlink() or not path.is_dir():
                    raise ValidationFailure("Codex 选中 cache 版本不是安全目录")
                continue
            if path.is_symlink() or not path.is_dir():
                raise ValidationFailure(
                    f"Codex cache 根目录包含不安全历史项：{path.name}"
                )
            if cache_io.remove_tree(path.name):
                removed.append(path.name)
    finally:
        cache_io.close()
    return removed


def _active_codex_cache_versions(codex_home: Path) -> list[str]:
    cache_root = _codex_cache_root(codex_home)
    if not cache_root.is_dir():
        return []
    return sorted(
        path.name
        for path in cache_root.iterdir()
        if path.is_dir() and not path.is_symlink() and _package_version(path) == path.name
    )


def _hooks_changed(previous: Path, candidate: Path) -> bool:
    old = previous / "hooks/hooks.json"
    new = candidate / "hooks/hooks.json"
    if not new.is_file():
        return False
    return not old.is_file() or old.read_bytes() != new.read_bytes()


def _publish_one(
    repository_root: Path,
    platform: str,
    *,
    codex_home: Path,
    hermes_home: Path,
    dry_run: bool,
    register: Callable[..., dict] = _run_registration,
    official_validate: Callable[..., dict] = validate_with_official_tools,
) -> dict:
    target = _target_for(platform, codex_home, hermes_home)
    _ensure_outside_repository(repository_root, target)
    stamp = _stamp()
    cachebuster = _cachebuster() if platform == "codex" else None
    if dry_run:
        staging = Path(tempfile.mkdtemp(prefix=f"{PLUGIN_NAME}-{platform}-dry-run-"))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{PLUGIN_NAME}-{platform}-stage-", dir=target.parent))
    staging.rmdir()
    cache_snapshot: Path | None = None
    preserved_cache_versions: list[str] = []
    removed_cache_versions: list[str] = []
    active_cache_versions: list[str] = []
    selected_version_verified = False
    codex_environment = dict(os.environ)
    codex_environment["CODEX_HOME"] = str(codex_home)
    try:
        build = build_package(
            repository_root,
            platform,
            staging,
            codex_cachebuster=cachebuster,
        )
        verify_package(staging)
        official_validation = None
        if platform == "codex":
            official_validation = official_validate(
                repository_root,
                staging,
                validate_skills=False,
            )
            verified_after_official = verify_package(staging)
            if (
                official_validation.get("codex_payload_digest")
                != verified_after_official["payload_digest"]
                or verified_after_official["payload_digest"] != build["payload_digest"]
            ):
                raise ValidationFailure(
                    "官方校验的 Codex 包摘要与最终 staging 包不一致"
                )
        if dry_run:
            shutil.rmtree(staging)
            return {
                "status": "dry_run_passed",
                "platform": platform,
                "canonical_version": build["canonical_version"],
                "payload_digest": build["payload_digest"],
                "skill_count": build["skill_count"],
                "official_validation": official_validation,
                "restart_required": platform == "codex",
                "hooks_review_required": platform == "codex",
            }

        marketplace_path = codex_home.parent / ".agents/plugins/marketplace.json"
        marketplace_previous = None
        marketplace_changed = False
        was_registered = False
        removed_previous = False
        add_attempted = False
        registered_cache = None
        hooks_review_required = _hooks_changed(target, staging) if platform == "codex" else False
        if platform == "codex":
            cache_snapshot = Path(tempfile.mkdtemp(prefix=f".{PLUGIN_NAME}-cache-snapshot-"))
            preserved_cache_versions = _snapshot_codex_caches(codex_home, cache_snapshot)
        backup = _swap_in(staging, target, stamp)
        try:
            if platform == "codex":
                marketplace_previous, marketplace_changed = _update_personal_marketplace(marketplace_path)
                listed_before = register(
                    ["codex", "plugin", "list", "--json"],
                    codex_environment,
                )
                was_registered = _codex_plugin_entry(listed_before) is not None
                if was_registered:
                    register(
                        ["codex", "plugin", "remove", f"{PLUGIN_NAME}@personal", "--json"],
                        codex_environment,
                    )
                    removed_previous = True
                add_attempted = True
                registration = register(
                    ["codex", "plugin", "add", f"{PLUGIN_NAME}@personal", "--json"],
                    codex_environment,
                )
                registered_cache = _verify_codex_registered_cache(codex_home, target)
                plugin_version = _installed_platform_version(target, platform)
                listed_after = register(
                    ["codex", "plugin", "list", "--json"],
                    codex_environment,
                )
                _verify_selected_codex_version(listed_after, plugin_version)
                selected_version_verified = True
                removed_cache_versions = _prune_codex_cache_versions(
                    codex_home, plugin_version
                )
                active_cache_versions = _active_codex_cache_versions(codex_home)
                if active_cache_versions != [plugin_version]:
                    raise ValidationFailure(
                        "Codex 活动 cache 必须只保留本次已验证版本"
                    )
            else:
                environment = dict(os.environ)
                environment["HERMES_HOME"] = str(hermes_home)
                registration = register(
                    [
                        "hermes",
                        "plugins",
                        "enable",
                        PLUGIN_NAME,
                        "--no-allow-tool-override",
                    ],
                    environment,
                )
            installed = verify_package(target)
        except Exception as original_error:
            if platform == "codex" and marketplace_changed:
                _restore_file(marketplace_path, marketplace_previous)
            _roll_back(target, backup, stamp)
            if platform == "codex" and cache_snapshot is not None:
                compensation_errors = []
                if add_attempted:
                    try:
                        register(
                            ["codex", "plugin", "remove", f"{PLUGIN_NAME}@personal", "--json"],
                            codex_environment,
                        )
                    except Exception as exc:
                        compensation_errors.append(f"remove={exc}")
                    if removed_previous:
                        try:
                            register(
                                ["codex", "plugin", "add", f"{PLUGIN_NAME}@personal", "--json"],
                                codex_environment,
                            )
                        except Exception as exc:
                            compensation_errors.append(f"add_previous={exc}")
                try:
                    _restore_codex_cache_snapshots(codex_home, cache_snapshot)
                except Exception as exc:
                    compensation_errors.append(f"cache_restore={exc}")
                if compensation_errors:
                    raise ValidationFailure(
                        "Codex 发布失败且注册补偿未完成："
                        f"publish={original_error}; compensation={'; '.join(compensation_errors)}"
                    ) from original_error
            raise
        return {
            "status": "published",
            "platform": platform,
            "canonical_version": installed["canonical_version"],
            "plugin_version": _installed_platform_version(target, platform),
            "target": str(target),
            "backup": str(backup) if backup is not None else None,
            "payload_digest": installed["payload_digest"],
            "skill_count": installed["skill_count"],
            "official_validation": official_validation,
            "registration": registration,
            "registered_cache": registered_cache,
            "active_cache_versions": active_cache_versions,
            "removed_cache_versions": removed_cache_versions,
            "selected_version_verified": selected_version_verified,
            "restart_required": platform == "codex",
            "hooks_review_required": hooks_review_required,
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if cache_snapshot is not None and cache_snapshot.exists():
            shutil.rmtree(cache_snapshot)


def _installed_platform_version(target: Path, platform: str) -> str:
    if platform == "codex":
        manifest = json.loads((target / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        return str(manifest["version"])
    for line in (target / "plugin.yaml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version:"):
            return line.partition(":")[2].strip().strip('"')
    raise ValidationFailure("Hermes plugin.yaml 缺少 version")


def publish_local(
    repository_root: Path,
    platforms: list[str],
    *,
    policy_path: Path | None,
    codex_home: Path,
    hermes_home: Path,
    dry_run: bool,
) -> dict:
    if not dry_run:
        if policy_path is None:
            raise ValidationFailure("实际发布必须提供本机发布策略")
        policy = _load_policy(policy_path, platforms)
    else:
        policy = None
    preflight = _run_repository_preflight(repository_root)
    if policy is not None:
        configured_version = policy.get("canonical_version")
        if configured_version != preflight["version"]:
            raise ValidationFailure(
                f"发布策略版本与作者源不一致：policy={configured_version}, source={preflight['version']}"
            )
    results = [
        _publish_one(
            repository_root,
            platform,
            codex_home=codex_home,
            hermes_home=hermes_home,
            dry_run=dry_run,
        )
        for platform in platforms
    ]
    return {"status": "passed", "preflight": preflight, "results": results}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将 engineering-assistant 安全发布到本机 Codex 或 Hermes。")
    parser.add_argument("--platform", choices=["codex", "hermes", "all"], default="codex")
    parser.add_argument("--repository-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--codex-home", default=str(Path.home() / ".codex"))
    parser.add_argument("--hermes-home", default=str(Path.home() / ".hermes"))
    parser.add_argument(
        "--repair-cache-version",
        help="从当前发布包或发布备份恢复仍被活跃 Codex 任务引用的插件 cache 版本。",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只验证和构建，不写入本机插件目录。")
    mode.add_argument("--yes", action="store_true", help="确认执行本机发布、备份和平台注册。")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    platforms = ["codex", "hermes"] if args.platform == "all" else [args.platform]
    repository_root = Path(args.repository_root).expanduser().resolve()
    policy = Path(args.policy).expanduser()
    if not policy.is_absolute():
        policy = repository_root / policy
    try:
        if args.repair_cache_version:
            if not args.yes or platforms != ["codex"]:
                raise ValidationFailure("修复 Codex cache 必须使用 --platform codex --yes")
            codex_home = Path(args.codex_home).expanduser().resolve()
            _load_policy(policy, ["codex"])
            target = _target_for("codex", codex_home, Path(args.hermes_home).expanduser().resolve())
            repaired = _repair_codex_cache_version(codex_home, target, args.repair_cache_version)
            print(
                json.dumps(
                    {
                        "status": "repaired",
                        "platform": "codex",
                        "plugin_version": args.repair_cache_version,
                        "cache_path": str(repaired),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        result = publish_local(
            repository_root,
            platforms,
            policy_path=policy,
            codex_home=Path(args.codex_home).expanduser().resolve(),
            hermes_home=Path(args.hermes_home).expanduser().resolve(),
            dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
