"""One bounded Hermes RPC inside the package's fixed Python Runtime."""
from __future__ import annotations

import contextlib
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Mapping

from .mcp_server import RuntimeTools

MAX_RPC_BYTES = 1_048_576
TOOL_FAILURE = {"error": "ToolExecutionError", "status": "failed"}


class HermesBridge:
    def __init__(self, runtime_root: Path | str) -> None:
        self.runtime_root = Path(runtime_root)
        self.tools = RuntimeTools(self.runtime_root)
        try:
            from .feedback import FeedbackCollector
            self.feedback = FeedbackCollector(self.runtime_root / "schemas")
        except Exception:
            self.feedback = None
        try:
            from .usage_observation import UsageObservationController
            self.observer = UsageObservationController(
                self.runtime_root / "schemas", coverage=("hermes_plugin_tool",)
            )
        except Exception:
            self.observer = None

    @staticmethod
    def _context(kwargs: Mapping) -> dict | None:
        activity = kwargs.get("task_id") or kwargs.get("turn_id")
        if kwargs.get("session_id") is None or activity is None or kwargs.get("cwd") is None:
            return None
        return {"session_id": str(kwargs["session_id"]), "turn_id": str(activity), "cwd": str(kwargs["cwd"])}

    @staticmethod
    def _mode(kwargs: Mapping) -> str:
        return kwargs.get("feedback_mode") or os.environ.get("ENGINEERING_ASSISTANT_FEEDBACK_MODE", "candidates")

    def call(self, name: str, args: dict, kwargs: Mapping) -> dict:
        observation = None
        context = self._context(kwargs)
        mode = self._mode(kwargs)
        try:
            if self.observer is not None and context is not None and mode == "candidates":
                observation = {
                    **context, "hook_event_name": "PreToolUse",
                    "tool_name": f"mcp__engineering_assistant__{name}",
                    "tool_input": args, "tool_use_id": secrets.token_hex(12),
                }
                self.observer.handle(observation, os.environ)
        except Exception:
            pass
        try:
            response = self.tools.call(name, args)
        except Exception:
            response = dict(TOOL_FAILURE)
            try:
                if self.feedback is not None and context is not None:
                    self.feedback.collect_tool_result(
                        {**context, "tool_name": f"mcp__engineering_assistant__{name}", "tool_response": response},
                        mode=mode, platform="hermes",
                    )
            except Exception:
                pass
        try:
            if self.observer is not None and observation is not None:
                self.observer.handle(
                    {**observation, "hook_event_name": "PostToolUse", "tool_response": json.dumps(response, ensure_ascii=False)},
                    os.environ,
                )
        except Exception:
            pass
        return response

    def post_llm_call(self, args: list, kwargs: Mapping) -> dict:
        from .hook_gate import is_explicit_plugin_request
        session, prompt, response, history_length, model, platform = args
        explicit = isinstance(prompt, str) and is_explicit_plugin_request(prompt)
        if not (explicit or kwargs.get("tool_active") is True):
            return {"complete": True}
        if self.feedback is None:
            return {"complete": False}
        mode = self._mode(kwargs)
        context = self._context({**kwargs, "session_id": session})
        observation_complete = self.observer is None or context is None or mode != "candidates"
        snapshot = None
        try:
            if self.observer is not None and context is not None and mode == "candidates":
                payload = {**context, "hook_event_name": "UserPromptSubmit", "prompt": prompt}
                if explicit and not self.observer.is_active(payload):
                    self.observer.handle(payload, os.environ)
                if self.observer.is_active(payload):
                    snapshot = self.observer.current_ledger(payload)
                    self.feedback.collect_usage_efficiency(
                        project_root=context["cwd"], ledger=snapshot, source="post_llm_call"
                    )
                observation_complete = True
        except Exception:
            pass
        try:
            self.feedback.collect_hermes_turn(
                project_root=kwargs.get("cwd") or Path.cwd(), session_id=session,
                turn_id=str(kwargs.get("turn_id") or f"{session}:{history_length}"),
                user_message=prompt, assistant_response=response,
                model=model, platform=platform, mode=mode,
            )
        except Exception:
            return {"complete": False}
        if observation_complete and snapshot is not None:
            try:
                finalized = self.observer.finalize_ledger(payload, snapshot)
                observation_complete = finalized in {"deleted", "missing"}
            except Exception:
                observation_complete = False
        return {"complete": observation_complete}

    def dispatch(self, request: dict) -> dict:
        operation = request.get("operation")
        name, args, kwargs = request.get("name"), request.get("args"), request.get("kwargs", {})
        if not isinstance(kwargs, dict):
            raise ValueError("RPC kwargs must be an object")
        if operation == "call" and isinstance(name, str) and isinstance(args, dict):
            return self.call(name, args, kwargs)
        if operation == "post_llm_call" and isinstance(args, list) and len(args) == 6:
            return self.post_llm_call(args, kwargs)
        if operation == "skill" and isinstance(name, str):
            skill = self.tools.catalog.skills[name]
            return {"id": skill.id, "source_path": skill.source_path}
        raise ValueError("invalid Hermes RPC request")


def main(runtime_root: Path | str) -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_RPC_BYTES + 1)
        if len(raw) > MAX_RPC_BYTES:
            raise ValueError("RPC input limit exceeded")
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError("RPC request must be an object")
        # A library's incidental print must not corrupt the protocol or expose content.
        with open(os.devnull, "w", encoding="utf-8") as discarded, contextlib.redirect_stdout(discarded):
            result = HermesBridge(runtime_root).dispatch(request)
        encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_RPC_BYTES:
            raise ValueError("RPC output limit exceeded")
    except Exception:
        encoded = json.dumps(TOOL_FAILURE).encode("utf-8")
    sys.stdout.buffer.write(encoded + b"\n")
    return 0
