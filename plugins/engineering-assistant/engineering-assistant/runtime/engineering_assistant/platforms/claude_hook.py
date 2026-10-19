"""Claude Code lifecycle-hook normalization."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from typing import Mapping, TextIO

from ..runtime.catalog import DEFAULT_REPOSITORY_ROOT
from ..runtime.feedback import MAX_HOOK_INPUT_BYTES, run_lifecycle_hook
from ..runtime.validation import ValidationFailure


_EVENTS = frozenset({"PreToolUse", "PostToolUse", "Stop", "UserPromptSubmit"})


def normalize_claude_payload(payload: Mapping[str, object]) -> dict[str, object]:
    event_name = payload.get("hook_event_name")
    if event_name not in _EVENTS:
        raise ValidationFailure("unsupported Claude Code hook event")
    for key in ("session_id", "prompt_id", "cwd"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValidationFailure(f"Claude Code hook field {key} must be a non-empty string")
    normalized = dict(payload)
    normalized["turn_id"] = payload["prompt_id"]
    normalized["model"] = str(payload.get("model") or "unknown")
    normalized["permission_mode"] = str(payload.get("permission_mode") or "unknown")
    normalized["stop_hook_active"] = bool(payload.get("stop_hook_active", False))
    return normalized


def run_claude_hook(
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    schema_root: Path | str = DEFAULT_REPOSITORY_ROOT / "schemas",
    environment: Mapping[str, str] = os.environ,
) -> int:
    try:
        raw = input_stream.read(MAX_HOOK_INPUT_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_HOOK_INPUT_BYTES:
            raise ValidationFailure("Claude Code hook input is too large")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValidationFailure("Claude Code hook input must be a JSON object")
        payload = normalize_claude_payload(parsed)
    except Exception:
        json.dump({}, output_stream, ensure_ascii=False)
        output_stream.write("\n")
        output_stream.flush()
        return 0
    return run_lifecycle_hook(
        platform="claude-code",
        input_stream=io.StringIO(json.dumps(payload, ensure_ascii=False)),
        output_stream=output_stream,
        schema_root=schema_root,
        environment=environment,
    )
