"""Stdlib-only fast gate for Codex hooks scoped to this plugin's MCP tools."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping, TextIO


MAX_HOOK_INPUT_CHARS = 1_048_576
OBSERVATION_ROOT = ".run-artifacts/engineering-assistant/usage-observations"
PLUGIN_SKILL_IDS = (
    "engineering-assistant",
    "research",
    "decision-interview",
    "domain-modeling",
    "repo-context",
    "wayfinder",
    "prototype",
    "codebase-design",
    "tdd",
    "diagnosing-bugs",
    "code-review",
)
PLUGIN_TOOL_NAMES = frozenset(
    {
        "engineering_assistant_route",
        "engineering_assistant_artifact_validate",
        "engineering_assistant_start",
        "engineering_assistant_next",
        "engineering_assistant_runs_list",
        "engineering_assistant_run_status",
        "engineering_assistant_evidence_register",
        "engineering_assistant_approval_record",
        "engineering_assistant_complete",
        "engineering_assistant_quality_submit",
        "engineering_assistant_provider_invoke",
        "engineering_assistant_investigation_propose",
        "engineering_assistant_investigation_list",
        "engineering_assistant_investigation_decide",
        "engineering_assistant_investigation_start",
        "engineering_assistant_investigation_finish",
    }
)
OBSERVATION_EXEMPT_TOOL_NAMES = frozenset(
    {"engineering_assistant_feedback_summary"}
)
_SKILL_TOKEN = (
    r"\$engineering-assistant(?::(?:"
    + "|".join(re.escape(skill) for skill in PLUGIN_SKILL_IDS)
    + r"))?(?!:)\b"
)
_ZH_COMMAND_PREFIX = (
    r"(?:(?:请\s*(?:务必\s*)?(?:在(?:本|当前)(?:任务|轮次|请求)中\s*)?)|"
    r"(?:(?:能否|可否|是否可以)\s*)|"
    r"(?:我(?:明确)?要求\s*))?"
    r"(?:明确\s*)?"
    r"(?:使用|调用|启用|用)\s*"
)
_EN_COMMAND_PREFIX = (
    r"(?:(?:please(?:\s*,)?\s+)|"
    r"(?:(?:could|can|would)\s+you\s+)|"
    r"(?:i\s+(?:explicitly\s+)?(?:want\s+you\s+to|request\s+you\s+to|"
    r"require\s+you\s+to)\s+))?"
    r"(?:use|invoke|enable)\s+"
)
_NAMESPACED_PLUGIN_CALLS = (
    re.compile(r"^\s*" + _ZH_COMMAND_PREFIX + _SKILL_TOKEN, re.IGNORECASE),
    re.compile(r"^\s*" + _EN_COMMAND_PREFIX + _SKILL_TOKEN, re.IGNORECASE),
    re.compile(r"^\s*" + _SKILL_TOKEN, re.IGNORECASE),
)
_NATURAL_PLUGIN_CALL = re.compile(
    r"^\s*" + _ZH_COMMAND_PREFIX + r"(?:已安装的\s*)?"
    r"engineering-assistant\s*插件"
    r"(?=\s|[，,。:：]|完成|执行|进行|评审|审查|分析|处理|帮|$)",
    re.IGNORECASE,
)
_ENGLISH_PLUGIN_CALL = re.compile(
    r"^\s*" + _EN_COMMAND_PREFIX +
    r"(?:the\s+)?(?:installed\s+)?engineering-assistant\s+plugin\b",
    re.IGNORECASE,
)
_SEQUENCED_PLUGIN_CALLS = (
    re.compile(
        r"(?:\bthen\s+|然后\s*)" + _EN_COMMAND_PREFIX
        + r"(?:the\s+)?(?:installed\s+)?engineering-assistant\s+plugin\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:\bthen\s+|然后\s*)" + _ZH_COMMAND_PREFIX
        + r"(?:已安装的\s*)?engineering-assistant\s*插件",
        re.IGNORECASE,
    ),
)
_SEQUENCED_NAMESPACED_PLUGIN_CALLS = (
    re.compile(
        r"(?:\bthen\s+|然后\s*)" + _EN_COMMAND_PREFIX + _SKILL_TOKEN,
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:\bthen\s+|然后\s*)" + _ZH_COMMAND_PREFIX + _SKILL_TOKEN,
        re.IGNORECASE,
    ),
)
_POLICY_OR_CONDITIONAL_CONTEXT = re.compile(
    r"\bonly\s+if\b|\bif\s+the\s+user\b|"
    r"只有[^。！？!?]{0,80}(?:才|时)",
    re.IGNORECASE,
)
_NEGATING_CONTEXT = re.compile(
    r"不是(?:本|当前)?任务[^。！？!?]{0,24}(?:要求|请求)|"
    r"(?:不要|不应|无需)[^。！？!?]{0,24}(?:使用|调用|启用|用)[^。！？!?]{0,24}engineering-assistant|"
    r"(?:\bdo\s+not\b|\bdon't\b)[^.;!?]{0,24}(?:use|invoke|enable)"
    r"[^.;!?]{0,24}(?:engineering-assistant|\bit\b)|"
    r"engineering-assistant[^.;!?]{0,80}\bnot\s+(?:required|requested)\b",
    re.IGNORECASE,
)
_EXPLANATORY_TAIL = re.compile(
    r"^\s*[，,。:：]?\s*(?:"
    r"这句话|这段话|这个表达|是什么意思|是什么|含义|表示什么|怎么理解|"
    r"会怎样|是否|会做什么|能做什么|"
    r"what\s+does\b|what\s+is\b|what\s+happens\b|"
    r"作为(?:本|当前)?(?:测试|示例|正例)[^。！？!?]{0,40}(?:输入|字符串|文本)|"
    r"作为[^。！？!?]{0,24}(?:输入字符串|示例|正例)|"
    r"(?:这|以上|前述)(?:只)?是(?:一个)?(?:示例|输入|引用|测试文本)|"
    r"this\s+is\s+(?:(?:only|just)\s+)?(?:an?\s+)?"
    r"(?:example|input|quotation|test\s+text)|"
    r"explain\b|means?\b"
    r")",
    re.IGNORECASE,
)
_META_EXAMPLE_PREFIX = re.compile(
    r"(?:示例输入|输入示例|请记录(?:这个|以下)?示例|"
    r"(?:示例|样例|例子|例如|比如)\s*[:：]?|"
    r"这是(?:一个)?示例|"
    r"以下(?:是|为)?[^\u3002！？!?\n]{0,24}示例|"
    r"引用(?:文本|内容)|"
    r"(?:just\s+an?\s+)?(?:example|sample)(?:\s+input)?|"
    r"for\s+example|e\.g\.|"
    r"(?:reference|quoted)\s+(?:text|content)|"
    r"this\s+is\s+(?:an?\s+)?example)"
    r"[^\u3002！？!?\n]{0,160}$",
    re.IGNORECASE,
)
_META_EXAMPLE_SUFFIX = re.compile(
    r"[，,。:：;；—-]\s*(?:(?:这|以上|前述)(?:只)?是(?:一个)?"
    r"(?:示例|输入|引用|测试文本)|"
    r"this\s+is\s+(?:(?:only|just)\s+)?(?:an?\s+)?"
    r"(?:example|input|quotation|test\s+text))\s*[.。！!？?]?\s*$",
    re.IGNORECASE,
)
_CONDITIONAL_PREFIX = re.compile(
    r"(?:(?:当[^。！？!?;\n]{0,80}时)|如果|假如|若|仅当|除非)"
    r"[^\u3002！？!?;\n]{0,200}$|"
    r"(?:\bif\b|\bwhen\b|\bonly\s+when\b|\bunless\b)"
    r"[^.!?;\n]{0,200}$",
    re.IGNORECASE,
)
_NEGATING_PREFIX = re.compile(
    r"(?:\bnever\b|\b(?:must|should|do)\s+not\b|"
    r"\b(?:mustn't|shouldn't|don't)\b|"
    r"不得|切勿|不应|不可以)"
    r"[^.。！？!?;\n]{0,200}$",
    re.IGNORECASE,
)
_CLAUSE_BOUNDARY = re.compile(r"[，,。；;！!？?\n]")


def _candidate_clause(prompt: str, start: int, end: int) -> str:
    before = list(_CLAUSE_BOUNDARY.finditer(prompt, 0, start))
    clause_start = before[-1].end() if before else 0
    after = _CLAUSE_BOUNDARY.search(prompt, end)
    clause_end = after.start() if after is not None else len(prompt)
    return prompt[clause_start:clause_end]


def _inside_quoted_context(prefix: str) -> bool:
    for opening, closing in (
        ("“", "”"),
        ("‘", "’"),
        ("「", "」"),
        ("『", "』"),
    ):
        if prefix.rfind(opening) > prefix.rfind(closing):
            return True
    for quote in ('"', "'", "`"):
        opened = False
        for match in re.finditer(rf"(?<!\\){re.escape(quote)}", prefix):
            position = match.start()
            if quote == "'":
                before = prefix[position - 1] if position else ""
                after = prefix[position + 1] if position + 1 < len(prefix) else ""
                if before.isalnum() and after.isalnum():
                    continue
            opened = not opened
        if opened:
            return True
    return False


def _candidate_is_request(prompt: str, match: re.Match[str]) -> bool:
    tail = prompt[match.end() :]
    if (
        _EXPLANATORY_TAIL.search(tail) is not None
        or _META_EXAMPLE_SUFFIX.search(tail) is not None
        or _NEGATING_CONTEXT.search(tail) is not None
    ):
        return False
    prefix = prompt[max(0, match.start() - 200) : match.start()]
    if (
        _META_EXAMPLE_PREFIX.search(prefix) is not None
        or _CONDITIONAL_PREFIX.search(prefix) is not None
        or _NEGATING_PREFIX.search(prefix) is not None
        or re.search(r"(?m)^\s*>[^\n]*$", prefix) is not None
        or _inside_quoted_context(prefix)
    ):
        return False
    clause = _candidate_clause(prompt, match.start(), match.end())
    return (
        _POLICY_OR_CONDITIONAL_CONTEXT.search(clause) is None
        and _NEGATING_CONTEXT.search(clause) is None
    )


def hashed_ref(prefix: str, value: str, length: int) -> str:
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def is_namespaced_plugin_request(prompt: str) -> bool:
    for pattern in (*_NAMESPACED_PLUGIN_CALLS, *_SEQUENCED_NAMESPACED_PLUGIN_CALLS):
        match = pattern.search(prompt)
        if match is not None and _candidate_is_request(prompt, match):
            return True
    return False


def is_explicit_plugin_request(prompt: str) -> bool:
    if is_namespaced_plugin_request(prompt):
        return True
    for pattern in (
        _NATURAL_PLUGIN_CALL,
        _ENGLISH_PLUGIN_CALL,
        *_SEQUENCED_PLUGIN_CALLS,
    ):
        match = pattern.search(prompt)
        if match is not None and _candidate_is_request(prompt, match):
            return True
    return False


def is_plugin_tool(tool_name: str) -> bool:
    parts = tool_name.casefold().split("__")
    if len(parts) != 3 or parts[0] != "mcp":
        return False
    server = parts[1].replace("-", "_")
    return (
        server in {
            "engineering_assistant",
            "plugin_engineering_assistant_engineering_assistant",
        }
        and parts[2] in PLUGIN_TOOL_NAMES
    )


def is_observation_exempt_tool(tool_name: str) -> bool:
    parts = tool_name.casefold().split("__")
    if len(parts) != 3 or parts[0] != "mcp":
        return False
    server = parts[1].replace("-", "_")
    return (
        server == "engineering_assistant"
        and parts[2] in OBSERVATION_EXEMPT_TOOL_NAMES
    )


def should_load_runtime(payload: Mapping[str, object]) -> bool:
    event_name = payload.get("hook_event_name")
    if event_name in {"PreToolUse", "PostToolUse"}:
        tool_name = payload.get("tool_name")
        if isinstance(tool_name, str) and is_observation_exempt_tool(tool_name):
            return False
    if event_name == "UserPromptSubmit":
        prompt = payload.get("prompt")
        if isinstance(prompt, str):
            if is_explicit_plugin_request(prompt):
                return True
    if event_name == "PreToolUse":
        tool_name = payload.get("tool_name")
        if isinstance(tool_name, str) and is_plugin_tool(tool_name):
            return True
    session_id = payload.get("session_id")
    turn_id = payload.get("turn_id")
    cwd = payload.get("cwd")
    if not all(isinstance(value, str) and value for value in (session_id, turn_id, cwd)):
        return False
    session_ref = hashed_ref("session-", session_id, 16)
    turn_ref = hashed_ref("turn-", turn_id, 16)
    marker = Path(cwd).resolve() / OBSERVATION_ROOT / session_ref / f"{turn_ref}.json"
    if marker.is_file():
        return True
    run_root = Path(cwd).resolve() / ".run-artifacts/engineering-assistant"
    if not run_root.is_dir():
        return False
    try:
        candidates = sorted(run_root.glob("*/run-state.json"))[:256]
        for candidate in candidates:
            if candidate.stat().st_size > 262_144:
                continue
            state = json.loads(candidate.read_text(encoding="utf-8"))
            if state.get("schema_version") == "2" and state.get("status") not in {
                "blocked", "cancelled", "completed"
            }:
                return True
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return False


def read_gate_input(input_stream: TextIO) -> tuple[bool, str]:
    raw = input_stream.read(MAX_HOOK_INPUT_CHARS + 1)
    if len(raw) > MAX_HOOK_INPUT_CHARS:
        return False, ""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, RecursionError):
        return False, ""
    if not isinstance(payload, dict):
        return False, ""
    return should_load_runtime(payload), raw
