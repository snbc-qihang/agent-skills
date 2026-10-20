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
    reason = "runtime_contract_invalid"
    try:
        from engineering_assistant.runtime.environment import _read_control, _validate_runtime_lock, verify_running_python
        lock = _read_control(root / "runtime-lock.json")
        reason = "shared_core_verification_failed"
        from engineering_assistant.runtime.shared_core import bootstrap_data_home, resolve_core
        core = resolve_core(root, bootstrap_data_home(lock))
        if core != root:
            # The native cache supplies only bootstrap and host identity. All
            # application imports and repository paths use the verified core.
            for name in tuple(sys.modules):
                if name == "engineering_assistant" or name.startswith("engineering_assistant."):
                    del sys.modules[name]
            sys.path[0] = str(core / "runtime")
            root = core
            from engineering_assistant.runtime.environment import _validate_runtime_lock, verify_running_python
        if lock.get("schema_version") == "2":
            reason = "python_artifact_verification_failed"
            _validate_runtime_lock(lock)
            verify_running_python(lock)
        elif lock.get("schema_version") != "1":
            raise ValueError("unsupported Runtime contract")
    except Exception:
        if mode == "cursor-hook":
            return 1
        if mode == "hook":
            print("{}")
            return 0
        print(json.dumps({"status": "needs_preparation", "reason": reason}), file=sys.stderr)
        return 2
    if mode == "cursor-hook":
        try:
            from engineering_assistant.platforms.cursor_hook import run_cursor_hook
            return run_cursor_hook(schema_root=root / "schemas")
        except Exception:
            return 1
    if mode == "hook":
        try:
            agent = lock["agent"]
            if agent == "claude-code":
                from engineering_assistant.platforms.claude_hook import run_claude_hook
                return run_claude_hook(schema_root=root / "schemas")
            from engineering_assistant.runtime.feedback import run_codex_hook
            return run_codex_hook(schema_root=root / "schemas")
        except Exception:
            print("{}")
            return 0
    if mode == "hermes-rpc":
        from engineering_assistant.platforms.hermes_bridge import main as bridge
        return bridge(root)
    if mode == "sandbox-probe":
        from engineering_assistant.runtime.sandbox_probe import qualify
        print(json.dumps(qualify(root), ensure_ascii=False))
        return 0
    from engineering_assistant.runtime.cli import main as cli
    return cli(["--repository-root", str(root), *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
