"""Hermes registration stays independent of the host Python environment."""

from __future__ import annotations

import json
from pathlib import Path

from ..catalog import Catalog
from ..mcp_server import RuntimeTools
from ..version import platform_version


class HermesAdapter:
    id = "hermes"

    def __init__(self, *, target: str | None = None) -> None:
        from ..installation import TARGETS, host_target
        self.target = target or host_target()
        if self.target not in TARGETS:
            raise ValueError(f"unsupported Hermes target: {self.target}")

    def write_platform_files(self, package_root: Path, catalog: Catalog) -> list[Path]:
        definitions = RuntimeTools(catalog.root).definitions()
        plugin_yaml = package_root / "plugin.yaml"
        version = platform_version(catalog.version, supports_four_part=False)
        provides_tools = "".join(f"  - {tool['name']}\n" for tool in definitions)
        plugin_yaml.write_text(
            "name: engineering-assistant\n"
            f'version: "{version}"\n'
            f'canonical_version: "{catalog.version}"\n'
            'skill_versions_source: "engineering-assistant/catalog/skills/public.json"\n'
            'description: "基于证据的工程原语、受治理流程、状态恢复和人工审批门禁。"\n'
            'author: "sunliming625@gmail.com"\n'
            "kind: standalone\n"
            "provides_tools:\n" + provides_tools + "provides_hooks:\n"
            "  - post_llm_call\n"
            "platforms:\n  - linux\n  - macos\n  - windows\n",
            encoding="utf-8",
        )
        entrypoint = package_root / "__init__.py"
        launcher = "ea.exe" if self.target == "windows-x64" else "ea"
        entrypoint.write_text(
            _HOST.replace("__DEFINITIONS__", repr(json.dumps(definitions, ensure_ascii=False)))
            .replace("__LAUNCHER__", repr(launcher)),
            encoding="utf-8",
        )
        return [plugin_yaml, entrypoint]


_HOST = r'''"""Generated Hermes host: stdlib registration and fixed Runtime RPC only."""
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_LAUNCHER = _ROOT / "engineering-assistant" / "bin" / __LAUNCHER__
_DEFINITIONS = json.loads(__DEFINITIONS__)
_MAX_RPC_BYTES = 1_048_576
_RPC_TIMEOUT_SECONDS = 120
_ACTIVE_TURNS = {}
_ACTIVE_TURNS_LOCK = threading.RLock()
_MAX_ACTIVE_TURNS = 1024
_ACTIVE_TURN_TTL_SECONDS = 3600
_CONTEXT_KEYS = ("session_id", "task_id", "turn_id", "cwd", "feedback_mode")


def _context(kwargs):
    result = {}
    for key in _CONTEXT_KEYS:
        value = kwargs.get(key)
        if value is not None:
            try:
                result[key] = str(value)
            except Exception:
                pass
    return result


def _turn_key(session_id, kwargs):
    activity_id = kwargs.get("task_id") or kwargs.get("turn_id")
    if session_id is None or activity_id is None:
        return None
    return str(session_id), str(activity_id)


def _activate_turn(session_id, kwargs):
    key = _turn_key(session_id, kwargs)
    if key is None:
        return
    with _ACTIVE_TURNS_LOCK:
        now = time.monotonic()
        for item in [item for item, state in _ACTIVE_TURNS.items() if state[1] < now]:
            _ACTIVE_TURNS.pop(item, None)
        if key not in _ACTIVE_TURNS and len(_ACTIVE_TURNS) >= _MAX_ACTIVE_TURNS:
            _ACTIVE_TURNS.pop(next(iter(_ACTIVE_TURNS)), None)
        # Token prevents a concurrent tool call from being cleared by an older hook.
        _ACTIVE_TURNS[key] = (kwargs.get("cwd"), now + _ACTIVE_TURN_TTL_SECONDS, object())


def _terminate(process):
    try:
        if os.name == "nt":
            # Native launcher owns a kill-on-close Job for its Runtime subtree.
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def _rpc(payload):
    request = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(request) > _MAX_RPC_BYTES:
        raise ValueError("RPC input limit exceeded")
    process = subprocess.Popen(
        [str(_LAUNCHER), "hermes-rpc"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt", bufsize=0,
    )
    output = bytearray()
    failures = []
    finished = threading.Event()

    def send():
        try:
            remaining = memoryview(request)
            while remaining:
                written = process.stdin.write(remaining)
                if not written:
                    raise OSError("fixed Runtime input closed")
                remaining = remaining[written:]
        except (OSError, ValueError):
            failures.append("input")
        finally:
            process.stdin.close()

    def receive():
        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                if len(output) + len(chunk) > _MAX_RPC_BYTES:
                    failures.append("output")
                    _terminate(process)
                    break
                output.extend(chunk)
        except (OSError, ValueError):
            failures.append("output")
        finally:
            finished.set()

    writer = threading.Thread(target=send, daemon=True)
    reader = threading.Thread(target=receive, daemon=True)
    writer.start()
    reader.start()
    deadline = time.monotonic() + _RPC_TIMEOUT_SECONDS
    try:
        process.wait(timeout=_RPC_TIMEOUT_SECONDS)
        if not finished.wait(max(0, deadline - time.monotonic())):
            raise subprocess.TimeoutExpired(process.args, _RPC_TIMEOUT_SECONDS)
        writer.join(max(0, deadline - time.monotonic()))
        if writer.is_alive() or process.returncode or failures:
            raise OSError("fixed Runtime RPC failed")
        result = json.loads(output.decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("invalid fixed Runtime response")
        return result
    finally:
        if process.poll() is None or not finished.is_set():
            _terminate(process)
        process.wait()
        writer.join(1)
        reader.join(1)
        process.stdin.close()
        process.stdout.close()


def _handler(name):
    def invoke(args, **kwargs):
        context = _context(kwargs)
        try:
            _activate_turn(context.get("session_id"), context)
        except Exception:
            pass
        try:
            response = _rpc({"operation": "call", "name": name, "args": args, "kwargs": context})
        except Exception:
            response = {"error": "ToolExecutionError", "status": "failed"}
        return json.dumps(response, ensure_ascii=False)
    return invoke


def _capture_feedback(session_id, user_message, assistant_response, conversation_history, model, platform, **kwargs):
    try:
        context = _context({**kwargs, "session_id": session_id})
        key = _turn_key(context.get("session_id"), context)
        with _ACTIVE_TURNS_LOCK:
            state = _ACTIVE_TURNS.get(key)
        tool_active = state is not None and state[1] >= time.monotonic()
        if tool_active and state[0] is not None and state[0] != context.get("cwd"):
            tool_active = False
        # Cheap rejection keeps unrelated Hermes turns from even starting Runtime.
        # The worker applies the full product-qualified activation rules.
        if not tool_active and (not isinstance(user_message, str) or "engineering-assistant" not in user_message.casefold()):
            return None
        result = _rpc({
            "operation": "post_llm_call", "name": "post_llm_call",
            # Only the length is used for legacy fallback IDs; raw history stays in Hermes.
            "args": [context.get("session_id"), user_message, assistant_response,
                     len(conversation_history), model, platform],
            "kwargs": {**context, "tool_active": tool_active},
        })
        if result.get("complete"):
            with _ACTIVE_TURNS_LOCK:
                if _ACTIVE_TURNS.get(key) is state:
                    _ACTIVE_TURNS.pop(key, None)
    except Exception:
        pass
    return None


def register(ctx):
    for tool in _DEFINITIONS:
        ctx.register_tool(
            name=tool["name"], toolset="engineering-assistant",
            schema={"name": tool["name"], "description": tool["description"],
                    "parameters": tool["inputSchema"]}, handler=_handler(tool["name"]),
        )
    ctx.register_hook("post_llm_call", _capture_feedback)
    for skill_md in sorted((_ROOT / "skills").glob("*/SKILL.md")):
        ctx.register_skill(skill_md.parent.name, skill_md)
'''
