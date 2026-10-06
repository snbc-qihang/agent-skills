"""One-time Runtime preparation and read-only installation diagnostics."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .installation import AGENTS, _read_control, agent_home, doctor, find_package, prepare_runtime


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
    parser.add_argument("--source", help="已构建的独立 distribution owner/repo@ref 或受控本地 marketplace。")
    parser.add_argument("--hooks-trusted", action="store_true", help="声明已由用户在原生宿主审查并信任本插件 Hook；仅记为 user_confirmed。")
    parser.add_argument("--target")
    parser.add_argument("--json", action="store_true")
    return parser


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
        from .installation import host_target
        if args.target is not None and args.target != host_target():
            result = {"status": "unsupported", "ready": False, "target": args.target}
        elif args.command == "doctor":
            result = doctor(args.agent, package=args.package, home=home,
                            data_home=data, target=args.target, marketplace=args.marketplace,
                            hooks_trusted=args.hooks_trusted)
        elif args.command == "install":
            from .installation import install_plugin
            if not args.source:
                raise ValueError("install requires an explicit --source distribution")
            result = install_plugin(args.agent, args.source, home=home, marketplace=args.marketplace,
                                    data_home=data, uv_executable=uv, hooks_trusted=args.hooks_trusted)
        elif args.command == "update":
            from .installation import update_plugin
            result = update_plugin(args.agent, home=home, marketplace=args.marketplace,
                                   package=args.package, data_home=data, uv_executable=uv,
                                   hooks_trusted=args.hooks_trusted)
        elif args.command == "uninstall":
            # Native marketplaces own plugin lifecycle. Retained environments
            # may still be used by open sessions and are never silently removed.
            from .installation import uninstall
            result = uninstall(args.agent, home=home, marketplace=args.marketplace)
        else:
            package = args.package or find_package(args.agent, home, args.marketplace)
            if package is None:
                result = {"status": "needs_preparation", "ready": False,
                          "reason": "请先从 Agent 原生市场安装工程助手插件。"}
            else:
                from .installation import _verified_package
                _verified_package(package, args.agent)
                prepare_runtime(package, data_home=data, uv_executable=uv, repair=args.command == "repair")
                result = doctor(args.agent, package=args.package, home=home,
                                data_home=data, target=args.target, marketplace=args.marketplace,
                                hooks_trusted=args.hooks_trusted)
    except Exception as exc:
        result = {"status": "failed", "ready": False, "reason": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"ready", "uninstalled"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
