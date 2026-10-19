"""One-time Runtime preparation and read-only installation diagnostics."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..platforms.codex_control import ControlNeedsPreparation
from .installation import AGENTS, _read_control, agent_home, doctor, find_package, prepare_runtime
from .installation import data_home as resolve_data_home, native_control
from .legacy_installation import (
    inspect_legacy_codex, installation_path_is_safe, legacy_blocker, preflight_legacy_codex,
)
from .internal_installation import (
    install_internal_codex, pending_internal_installation, repair_internal_codex,
    uninstall_internal_codex,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ea-setup", description="准备并验证原生市场中的工程助手插件。")
    parser.add_argument("command", choices=("prepare", "doctor", "repair", "install", "update", "uninstall"))
    parser.add_argument("--agent", choices=AGENTS, required=True)
    parser.add_argument("--package", type=Path, help="显式指定已安装的、由CI构建的插件目录。")
    parser.add_argument("--agent-home", type=Path)
    parser.add_argument("--data-home", type=Path)
    parser.add_argument("--uv", type=Path)
    parser.add_argument("--config", type=Path, help="可选 JSON 配置；命令参数与 Agent 环境变量优先。")
    parser.add_argument("--marketplace", help="原生市场名称；存在多个来源时显式选择。")
    parser.add_argument("--source", help="可选高级发行来源；Codex 默认使用团队已验收的内部发行。")
    parser.add_argument("--hooks-trusted", action="store_true", help="声明已由用户在原生宿主审查并信任本插件 Hook；仅记为 user_confirmed。")
    parser.add_argument("--target")
    parser.add_argument("--json", action="store_true")
    return parser


def _execute(args, home: Path, data: Path | str | None, uv: Path | str | None) -> dict:
    from .installation import host_target
    if args.target is not None and args.target != host_target():
        return {"status": "unsupported", "ready": False, "target": args.target}
    if args.agent == "codex" and host_target() == "unsupported":
        return {"status": "unsupported", "ready": False, "target": "unsupported"}
    if args.agent == "codex":
        paths = (home, resolve_data_home(data))
        unknown = [{"kind": "unsafe_path", "path": str(path),
                    "reason": "路径不可读或含符号链接/reparse point；尚未调用原生宿主"}
                   for path in paths if not installation_path_is_safe(path)]
        if unknown:
            return legacy_blocker({"legacy_installation_detected": False, "legacy_check_complete": False,
                "legacy_scope": [{"kind": "installation_path", "path": str(path)} for path in paths],
                "legacy_confirmed": [], "legacy_unknown": unknown,
                "legacy_manual_steps": [{"action": "manual_review", "instruction": "请核对选定 CODEX_HOME 和数据目录的真实路径；安装器不会跟随链接或自动清理"}]})
    with native_control(data, allow_download=args.command in {"install", "update", "repair"}):
        if args.command == "doctor":
            inspection = inspect_legacy_codex(home, resolve_data_home(data)) if args.agent == "codex" else {}
            blocked = legacy_blocker(inspection) if inspection else None
            if blocked is not None:
                return blocked
            if args.agent == "codex" and pending_internal_installation(resolve_data_home(data), home):
                return {**inspection, "status": "failed", "ready": False, "recovery_required": True,
                        "reason": "发现中断的安装事务，请执行 repair；现有状态尚未核验"}
            return {**inspection, **doctor(args.agent, package=args.package, home=home, data_home=data,
                          target=args.target, marketplace=args.marketplace, hooks_trusted=args.hooks_trusted)}
        if args.command == "install":
            from .installation import install_plugin
            if not args.source:
                if args.agent != "codex":
                    raise ValueError("该 Agent 安装仍需显式 --source 发行来源")
                return install_internal_codex(home=home, data_home=data, marketplace=args.marketplace,
                    uv_executable=uv, hooks_trusted=args.hooks_trusted)
            if args.agent == "codex":
                blocked = legacy_blocker(preflight_legacy_codex(home, resolve_data_home(data)))
                if blocked is not None:
                    return blocked
            return install_plugin(args.agent, args.source, home=home, marketplace=args.marketplace,
                data_home=data, uv_executable=uv, hooks_trusted=args.hooks_trusted)
        if args.command == "update":
            from .installation import update_plugin
            if args.source:
                raise ValueError("update 使用已注册来源或团队固定版本，不接受新的 --source")
            if args.agent == "codex" and args.package is None and args.marketplace in {None, "engineering-assistant"}:
                return install_internal_codex(home=home, data_home=data, marketplace=args.marketplace,
                    uv_executable=uv, hooks_trusted=args.hooks_trusted, update=True)
            return update_plugin(args.agent, home=home, marketplace=args.marketplace, package=args.package,
                data_home=data, uv_executable=uv, hooks_trusted=args.hooks_trusted)
        if args.command == "uninstall":
            from .installation import uninstall
            if args.agent == "codex":
                result = uninstall_internal_codex(resolve_data_home(data), home, args.marketplace)
                if result is not None:
                    return result
            return uninstall(args.agent, home=home, marketplace=args.marketplace)
        if args.agent == "codex" and args.command == "repair" and args.package is None:
            result = repair_internal_codex(home=home, data_home=data, uv_executable=uv,
                                          hooks_trusted=args.hooks_trusted)
            if result is not None:
                return result
        package = args.package or find_package(args.agent, home, args.marketplace)
        if package is None:
            return {"status": "needs_preparation", "ready": False, "reason": "请先安装工程助手插件。"}
        from .installation import _verified_package
        _verified_package(package, args.agent)
        prepare_runtime(package, data_home=data, uv_executable=uv, repair=args.command == "repair")
        return doctor(args.agent, package=args.package, home=home, data_home=data, target=args.target,
                      marketplace=args.marketplace, hooks_trusted=args.hooks_trusted)


def _show_result(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    messages = {
        "ready": "工程助手已就绪。", "needs_trust": "插件与 Runtime 已准备好；请在 Codex 中审查并信任 Hook，然后重开会话。",
        "needs_update": "已安装旧版，请执行 update。", "needs_preparation": "插件尚未准备好，请执行 install 或 repair。",
        "unsupported": "当前系统或目标不在支持范围内。", "uninstalled": "插件已卸载；已保留 Runtime，供仍在运行的会话使用。",
        "partial": "完整功能资格尚未通过，插件未就绪。", "failed": "操作未完成。",
    }
    message = messages.get(result.get("status"), "操作未完成。")
    if result.get("status") == "partial" and result.get("runtime_ready") is True:
        message = "Runtime 与 MCP 可运行；Provider 隔离检查未通过，完整功能资格尚未通过。"
    elif result.get("reason") == "requires_native_activation":
        message = "插件与 Runtime 已准备好；请在 Codex 中启用插件，然后重开会话。"
    print(message)
    if result.get("version"):
        print("版本：" + result["version"])
    if result.get("reason") and result["status"] not in {"ready", "needs_trust"}:
        print("原因：" + str(result["reason"]))
    if result.get("legacy_installation_detected") or result.get("legacy_check_complete") is False:
        for item in result.get("legacy_confirmed", []):
            print("历史项：" + item["path"])
        for item in result.get("legacy_unknown", []):
            print("待核对：" + item.get("path", "原生登记") + "；" + item["reason"])
        for item in result.get("legacy_manual_steps", []):
            print("操作：" + item["instruction"])
            if item.get("command"):
                print("命令：" + " ".join(item["command"]))
    if result.get("restart_required") and result["status"] == "ready":
        print("请重开 Codex 会话以加载本版插件。")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        config = _read_control(args.config) if args.config else {}
        if not set(config).issubset({"agent_homes", "data_home", "uv"}):
            raise ValueError("unsupported ea-setup configuration field")
        home = agent_home(args.agent, args.agent_home, config=config)
        data = args.data_home or config.get("data_home")
        uv = args.uv or config.get("uv")
        result = _execute(args, home, data, uv)
    except ControlNeedsPreparation as exc:
        result = {"status": "needs_preparation", "ready": False, "reason": str(exc)}
    except Exception as exc:
        result = {"status": "failed", "ready": False, "reason": str(exc)}
    _show_result(result, args.json)
    return 0 if result["status"] in {"ready", "uninstalled"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
