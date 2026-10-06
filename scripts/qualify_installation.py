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
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.compiler import build_package, verify_package
from engineering_assistant.installation import PYTHON_VERSION, _protocol_run, doctor, host_target, prepare_runtime


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
            "python_version": PYTHON_VERSION, "checks": result["checks"], "persistent_run": "passed", "feedback_hook": "passed",
            "native_marketplace_session": "not_executed", "hook_trust": "requires_native_host_review"})
    return {"schema_version": "1", "status": "runtime_qualified", "target": target,
            "system": platform.platform(), "results": results,
            "windows_11_qualification": "not_executed" if os.name == "nt" else "not_applicable"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ea-install-qualification-") as temporary:
        result = qualify(Path(temporary).resolve())
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "target": result["target"], "agents": len(result["results"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
