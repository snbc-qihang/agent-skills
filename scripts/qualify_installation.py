"""Run native package/Runtime qualification on its matching OS runner.

This verifies real child processes and local persistence. Agent marketplace
registration and interactive Hook trust require a separate native host check.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.compiler import build_package, verify_package
from engineering_assistant.installation import (
    PYTHON_VERSION, _check_python_base, _package_lock, _protocol_run, doctor, host_target, prepare_runtime,
)
from engineering_assistant.validation import ValidationFailure
from engineering_assistant.windows_process import run_bounded_windows


def qualify(base: Path) -> dict:
    target = host_target()
    if target == "unsupported":
        raise RuntimeError("this host is outside the supported native targets")
    packages, data = base / "packages", base / "Runtime 数据"
    packages.mkdir()
    results = []
    for agent in ("codex", "hermes", "claude-code"):
        package = packages / agent
        build_package(ROOT, agent, package, target=target)
        manifest = verify_package(package)
        prepared = prepare_runtime(package, data_home=data, publish_default=False)
        result = doctor(agent, package=package, data_home=data)
        if not result.get("runtime_ready", result.get("ready")):
            raise RuntimeError(f"{agent} Runtime qualification failed: {result}")
        command = [str(package / "engineering-assistant/bin" / ("ea.exe" if os.name == "nt" else "ea"))]
        environment = {**os.environ, "ENGINEERING_ASSISTANT_DATA_HOME": str(data)}
        project = base / (agent + " 实际项目")
        project.mkdir()
        intent = {"task_kind": "implement", "requested_outcome": "隔离安装资格检查", "scope": ["temporary fixture"],
                  "risk_signals": [], "requested_external_actions": [], "confirmed_actions": [],
                  "confidence": 1, "evidence": ["CI installation qualification"]}
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "engineering_assistant_start", "arguments": {"intent": intent,
                "task_id": "installation-qualification", "project_root": str(project)}}}
        response = json.loads(_protocol_run([*command, "mcp-serve"], cwd=project, environment=environment,
            input_data=(json.dumps(request) + "\n").encode()))
        if response.get("result", {}).get("isError", True):
            raise RuntimeError("native Runtime failed to persist an isolated run")
        if not any((project / ".run-artifacts/engineering-assistant").rglob("run-state.json")):
            raise RuntimeError("native Runtime did not produce its persistent state")
        # Exercise the generated Hermes host adapter, including the real native RPC.
        if agent == "hermes":
            previous = os.environ.get("ENGINEERING_ASSISTANT_DATA_HOME")
            os.environ["ENGINEERING_ASSISTANT_DATA_HOME"] = str(data)
            try:
                specification = importlib.util.spec_from_file_location("qualified_hermes", package / "__init__.py")
                module = importlib.util.module_from_spec(specification)
                specification.loader.exec_module(module)
                class Context:
                    def __init__(self):
                        self.tools = {}
                        self.hooks = {}
                    def register_tool(self, name, **kwargs):
                        self.tools[name] = kwargs
                    def register_skill(self, *args, **kwargs):
                        pass
                    def register_hook(self, name, handler):
                        self.hooks[name] = handler
                context = Context()
                module.register(context)
                routed = json.loads(context.tools["engineering_assistant_route"]["handler"]({"intent": intent}))
                if "decision" not in routed:
                    raise RuntimeError("Hermes host adapter did not invoke the native Runtime")
                context.hooks["post_llm_call"]("installation-session",
                    "请使用 engineering-assistant 插件。刚才的实现不对，请改为复用现有接口。",
                    "按修正约束继续。", [], "installation-fixture", "cli", cwd=str(project), turn_id="installation-turn")
            finally:
                if previous is None:
                    os.environ.pop("ENGINEERING_ASSISTANT_DATA_HOME", None)
                else:
                    os.environ["ENGINEERING_ASSISTANT_DATA_HOME"] = previous
        else:
            payload = {"hook_event_name": "UserPromptSubmit", "cwd": str(project),
                "session_id": "installation-session", "turn_id": "installation-turn", "prompt_id": "installation-turn",
                "prompt": "请使用 engineering-assistant 插件。刚才的实现不对，请改为复用现有接口。"}
            output = _protocol_run([*command, "hook"], cwd=project, environment=environment,
                input_data=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            response = json.loads(output)
            specific = response.get("hookSpecificOutput") if isinstance(response, dict) else None
            if (not isinstance(specific, dict) or set(response) != {"hookSpecificOutput"}
                    or set(specific) != {"hookEventName", "additionalContext"}
                    or specific["hookEventName"] != "UserPromptSubmit"
                    or not isinstance(specific["additionalContext"], str)):
                raise RuntimeError("native Hook did not return its nonblocking activation context")
        events = project / ".run-artifacts/engineering-assistant/feedback/events"
        if not any(json.loads(path.read_text(encoding="utf-8")).get("event_type") == "human_correction"
                   for path in events.glob("*.json")):
            raise RuntimeError(f"{agent} native feedback Hook did not execute its real collector")
        results.append({"agent": agent, "canonical_version": manifest["canonical_version"],
            "payload_digest": manifest["payload_digest"], "target": target,
            "python_build": result["python_build"], "python_artifact_digest": result["python_artifact_digest"],
            "python_version": PYTHON_VERSION, "checks": result["checks"], "persistent_run": "passed", "feedback_hook": "passed",
            "native_marketplace_session": "not_executed", "hook_trust": "requires_native_host_review"})
    return {"schema_version": "1", "status": "runtime_qualified", "target": target,
            "system": platform.platform(), "results": results,
            "windows_11_qualification": "not_executed" if os.name == "nt" else "not_applicable"}


def _diagnostic_reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def _windows_native_failure_diagnostic(base: Path) -> dict:
    """Observe only the already-prepared, receipt-bound Codex Windows base."""
    lock = _package_lock(base / "packages/codex")
    if lock["schema_version"] != "2" or lock["agent"] != "codex" or lock["target"] != "windows-x64":
        raise ValidationFailure("Windows diagnostic requires its fixed Codex artifact lock")
    data = base / "Runtime 数据"
    artifact_root = data / "python" / lock["python_artifact_digest"]
    python_base = artifact_root / lock["python_artifact"]["key"]
    for directory in (base, data, data / "python", artifact_root, python_base):
        if not stat.S_ISDIR(directory.lstat().st_mode) or _diagnostic_reparse(directory):
            raise ValidationFailure("Windows diagnostic requires its direct prepared artifact directories")
    _check_python_base(python_base, lock)
    python = python_base / "python.exe"
    script = ROOT / "scripts/diagnose_windows_native.py"
    for path in (python, script):
        if not stat.S_ISREG(path.lstat().st_mode) or _diagnostic_reparse(path):
            raise ValidationFailure("Windows diagnostic requires direct regular executable and script files")
    # Interpreter isolation ignores every PYTHON_* override and user site.
    # This fixed interpreter switch never becomes a diagnostic script argument.
    code, output = run_bounded_windows([str(python), "-I", str(script)], cwd=ROOT, environment=dict(os.environ),
                                       timeout_seconds=180, output_limit_bytes=65536)
    try:
        diagnostic = json.loads(output)
    except (ValueError, UnicodeError) as error:
        raise ValidationFailure("Windows diagnostic did not return its fixed JSON report") from error
    if (not isinstance(diagnostic, dict) or diagnostic.get("diagnostic_only") is not True
            or diagnostic.get("qualified") is not False):
        raise ValidationFailure("Windows diagnostic cannot claim Runtime qualification")
    return {"runtime_distribution": "uv_managed", "qualified": False, "diagnostic_only": True,
            "diagnostic_exit_code": code, "diagnostic": diagnostic}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--diagnose-windows-native-on-failure", action="store_true",
                        help="CI only: observe the fixed uv Windows base after qualification fails")
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ea-install-qualification-") as temporary:
        base = Path(temporary).resolve()
        try:
            result = qualify(base)
        except Exception:
            if arguments.diagnose_windows_native_on_failure and sys.platform == "win32":
                try:
                    diagnostic = _windows_native_failure_diagnostic(base)
                except Exception as error:
                    diagnostic = {"runtime_distribution": "uv_managed", "qualified": False,
                                  "diagnostic_only": True, "error_type": type(error).__name__}
                try:
                    arguments.output.parent.mkdir(parents=True, exist_ok=True)
                    (arguments.output.parent / "uv-native-diagnostic.json").write_text(
                        json.dumps(diagnostic, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
                    print(json.dumps(diagnostic, ensure_ascii=True, sort_keys=True), flush=True)
                except Exception:
                    # Optional observation and transport never replace the
                    # original mandatory qualification failure.
                    pass
            raise
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "target": result["target"], "agents": len(result["results"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
