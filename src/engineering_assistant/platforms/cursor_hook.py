"""Normalize Cursor events without changing native permissions or reading transcripts."""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from typing import Mapping, TextIO

from ..runtime.catalog import DEFAULT_REPOSITORY_ROOT
from ..runtime.feedback import FeedbackCollector, MAX_HOOK_INPUT_BYTES, run_lifecycle_hook
from ..runtime.hook_gate import PLUGIN_TOOL_NAMES, OBSERVATION_EXEMPT_TOOL_NAMES, is_plugin_tool
from ..runtime.validation import ValidationFailure

_EVENTS = {"beforeSubmitPrompt": "UserPromptSubmit", "beforeMCPExecution": "PreToolUse",
           "afterMCPExecution": "PostToolUse", "postToolUseFailure": "PostToolUse", "stop": "Stop"}


def normalize_cursor_payload(payload: Mapping) -> dict | None:
    event = payload.get("hook_event_name")
    if event not in _EVENTS:
        raise ValidationFailure("unsupported Cursor hook event")
    session, turn = payload.get("conversation_id"), payload.get("generation_id")
    roots = payload.get("workspace_roots")
    cwd = payload.get("cwd")
    if not cwd and isinstance(roots, list) and len(roots) == 1:
        cwd = roots[0]
    if (not isinstance(session, str) or not session.strip() or not isinstance(turn, str) or not turn.strip()
        or not isinstance(cwd, str) or not Path(cwd).is_absolute()):
        raise ValidationFailure("Cursor hook has no unambiguous session, generation or project")
    normalized = {"hook_event_name": _EVENTS[event], "session_id": "cursor:" + session, "turn_id": turn,
                  "cwd": cwd, "model": str(payload.get("model_id") or payload.get("model") or "unknown"),
                  "stop_hook_active": bool(payload.get("loop_count", 0))}
    if event == "beforeSubmitPrompt":
        if not isinstance(payload.get("prompt"), str):
            raise ValidationFailure("Cursor prompt must be a string")
        normalized["prompt"] = payload["prompt"]
    elif event == "stop":
        normalized["last_assistant_message"] = ""
    else:
        name = payload.get("tool_name")
        if event == "postToolUseFailure":
            if not isinstance(name, str) or not is_plugin_tool(name):
                return None
            short = name.split("__")[-1]
        else:
            if payload.get("mcp_server_name") != "engineering-assistant":
                return None
            short = name.split("__")[-1] if isinstance(name, str) else None
            if short not in PLUGIN_TOOL_NAMES | OBSERVATION_EXEMPT_TOOL_NAMES:
                return None
        normalized["tool_name"] = "mcp__engineering-assistant__" + short
        tool_input = payload.get("tool_input", {})
        normalized["tool_input"] = json.loads(tool_input) if isinstance(tool_input, str) else tool_input
        normalized["tool_use_id"] = payload.get("tool_use_id") or ""
        if event == "postToolUseFailure":
            # The shared collector records a controlled classification and hash,
            # never the raw error, authenticated user email or transcript path.
            normalized["tool_response"] = {"isError": True, "error": "cursor_tool_failure"}
        elif event == "afterMCPExecution":
            result = payload.get("result_json", {})
            normalized["tool_response"] = json.loads(result) if isinstance(result, str) else result
    return normalized


def run_cursor_hook(*, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout,
                    schema_root: Path | str = DEFAULT_REPOSITORY_ROOT / "schemas",
                    environment: Mapping[str, str] = os.environ) -> int:
    try:
        raw = input_stream.read(MAX_HOOK_INPUT_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_HOOK_INPUT_BYTES:
            raise ValidationFailure("Cursor hook input is too large")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValidationFailure("Cursor hook input must be an object")
        normalized = normalize_cursor_payload(payload)
    except Exception:
        # Cursor blocks invalid permission JSON and exit 2. Its documented
        # fail-open path is exit 1; never emit Codex's {} for a permission hook.
        return 1
    if normalized is not None:
        try:
            if normalized["hook_event_name"] in {"PreToolUse", "PostToolUse"} and not normalized.get("tool_use_id"):
                # Cursor's MCP-specific event schema does not guarantee a call
                # ID. Do not invent one or miscount concurrent identical calls.
                if normalized["hook_event_name"] == "PostToolUse":
                    FeedbackCollector(schema_root).collect_lifecycle(normalized, platform="cursor",
                        mode=environment.get("ENGINEERING_ASSISTANT_FEEDBACK_MODE", "candidates"))
            else:
                run_lifecycle_hook(platform="cursor", input_stream=io.StringIO(json.dumps(normalized, ensure_ascii=False)),
                    output_stream=io.StringIO(), schema_root=schema_root, environment=environment)
        except Exception:
            pass
    response = {"continue": True} if payload["hook_event_name"] == "beforeSubmitPrompt" else (
        {"permission": "allow"} if payload["hook_event_name"] == "beforeMCPExecution" else {})
    json.dump(response, output_stream, ensure_ascii=False)
    output_stream.write("\n")
    output_stream.flush()
    return 0
