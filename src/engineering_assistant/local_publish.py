"""安全地构建并安装本机 Codex/Hermes 插件。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .compiler import build_package, verify_package
from .eval_runner import run_evals
from .validation import ValidationFailure


PLUGIN_NAME = "engineering-assistant"
DEFAULT_POLICY = "config/local-publish-policy.json"


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
    evaluation = run_evals(repository_root)
    return {
        "tests": "passed",
        "version": evaluation["version"],
        "routing_cases": evaluation["routing"]["case_count"],
        "routing_top1_accuracy": evaluation["routing"]["top1_accuracy"],
        "unconfirmed_high_risk_writes": evaluation["routing"]["unconfirmed_high_risk_writes"],
        "simulation": evaluation["simulation"],
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


def _publish_one(
    repository_root: Path,
    platform: str,
    *,
    codex_home: Path,
    hermes_home: Path,
    dry_run: bool,
    register: Callable[..., dict] = _run_registration,
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
    try:
        build = build_package(
            repository_root,
            platform,
            staging,
            codex_cachebuster=cachebuster,
        )
        verify_package(staging)
        if dry_run:
            shutil.rmtree(staging)
            return {
                "status": "dry_run_passed",
                "platform": platform,
                "canonical_version": build["canonical_version"],
                "payload_digest": build["payload_digest"],
                "skill_count": build["skill_count"],
            }

        marketplace_path = codex_home.parent / ".agents/plugins/marketplace.json"
        marketplace_previous = None
        marketplace_changed = False
        backup = _swap_in(staging, target, stamp)
        try:
            if platform == "codex":
                marketplace_previous, marketplace_changed = _update_personal_marketplace(marketplace_path)
                registration = register(["codex", "plugin", "add", f"{PLUGIN_NAME}@personal", "--json"])
            else:
                environment = dict(os.environ)
                environment["HERMES_HOME"] = str(hermes_home)
                registration = register(["hermes", "plugins", "enable", PLUGIN_NAME], environment)
            installed = verify_package(target)
        except Exception:
            if platform == "codex" and marketplace_changed:
                _restore_file(marketplace_path, marketplace_previous)
            _roll_back(target, backup, stamp)
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
            "registration": registration,
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)


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
