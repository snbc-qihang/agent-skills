"""Trusted entrypoint copied beside a platform's native launcher."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "runtime"))
    arguments = sys.argv[1:]
    mode = arguments[0] if arguments else "--help"
    if mode == "hook":
        try:
            from engineering_assistant.installation import _read_control
            agent = _read_control(root / "runtime-lock.json")["agent"]
            if agent == "claude-code":
                from engineering_assistant.claude_hook import run_claude_hook
                return run_claude_hook(schema_root=root / "schemas")
            from engineering_assistant.feedback import run_codex_hook
            return run_codex_hook(schema_root=root / "schemas")
        except Exception:
            print("{}")
            return 0
    if mode == "hermes-rpc":
        from engineering_assistant.hermes_bridge import main as bridge
        return bridge(root)
    if mode == "sandbox-probe":
        from engineering_assistant.sandbox_probe import qualify
        print(json.dumps(qualify(root), ensure_ascii=False))
        return 0
    from engineering_assistant.cli import main as cli
    return cli(["--repository-root", str(root), *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
