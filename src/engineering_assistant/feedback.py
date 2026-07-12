"""Privacy-aware feedback capture shared by platform lifecycle hooks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, TextIO

from .artifact_io import ArtifactConflict, ArtifactIO
from .catalog import DEFAULT_REPOSITORY_ROOT
from .model import FeedbackCapture, FeedbackEvent
from .validation import ValidationFailure, load_json, validate_instance


FEEDBACK_ROOT = ".run-artifacts/engineering-assistant/feedback"
FEEDBACK_MODES = {"candidates", "metadata", "disabled"}
MAX_EXCERPT = 512

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
]

_STOP_SIGNALS = [
    (
        "blocker",
        "blocker",
        "reported-blocker",
        "运行应明确记录阻断原因、所需输入和恢复条件。",
        re.compile(
            r"阻断|等待(?:人工|用户|审批|输入)|无法继续|\bblocked\b|"
            r"waiting for (?:human|user|approval|input)|cannot continue",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_failure",
        "high",
        "reported-tool-failure",
        "失败门禁应保留准确错误、影响范围和下一修复动作。",
        re.compile(
            r"测试失败|构建失败|命令失败|校验失败|tests? failed|build failed|"
            r"command failed|validation failed|traceback|\berror:",
            re.IGNORECASE,
        ),
    ),
    (
        "rework",
        "medium",
        "reported-rework",
        "返工项应说明未满足的条件和再次验证方式。",
        re.compile(r"需要返工|需要重新修改|仍需修复|requires rework|needs? rework", re.IGNORECASE),
    ),
]

_PROMPT_SIGNALS = [
    (
        "human_correction",
        "medium",
        "human-correction",
        "Agent 应按用户明确修正更新当前约束，并记录受影响范围。",
        re.compile(
            r"刚才.*(?:不对|错误)|不是这样|(?:^|[，。,.!！?？\s])不对(?:[，。,.!！?？\s]|$)|"
            r"请改为|需要重新|你漏了|"
            r"that's wrong|not what i asked|please change|you missed",
            re.IGNORECASE,
        ),
    ),
    (
        "scope_change",
        "low",
        "user-scope-change",
        "新增范围应与现有目标合并，并重新检查风险和验收条件。",
        re.compile(
            r"(?:额外|另外|补充|再增加)(?:一个|一项|要求|建议)?|"
            r"additionally|also add|one more requirement",
            re.IGNORECASE,
        ),
    ),
]


@dataclass(frozen=True)
class CaptureResult:
    capture: FeedbackCapture | None
    event: FeedbackEvent | None
    duplicate: bool = False


class FeedbackStore:
    def __init__(self, project_root: Path | str, schema_root: Path | str) -> None:
        self.project_root = Path(project_root).resolve()
        self.schema_root = Path(schema_root).resolve()
        self.root = self.project_root / FEEDBACK_ROOT
        self.artifacts = ArtifactIO(self.project_root, self.root)
        self.artifacts.path()

    def capture_path(self, capture_id: str) -> Path:
        return self.artifacts.path("captures", f"{capture_id}.json")

    def event_path(self, event_id: str) -> Path:
        return self.artifacts.path("events", f"{event_id}.json")

    def save_capture(self, capture: FeedbackCapture) -> bool:
        validate_instance(
            capture.to_dict(),
            load_json(self.schema_root / "feedback-capture.schema.json"),
            "feedback-capture",
        )
        try:
            _, created = self.artifacts.create_immutable_json_with_status(
                capture.to_dict(), "captures", f"{capture.capture_id}.json"
            )
        except ArtifactConflict:
            return False
        return created

    def save_event(self, event: FeedbackEvent) -> bool:
        validate_instance(
            event.to_dict(),
            load_json(self.schema_root / "feedback-event.schema.json"),
            "feedback-event",
        )
        try:
            _, created = self.artifacts.create_immutable_json_with_status(
                event.to_dict(), "events", f"{event.event_id}.json"
            )
        except ArtifactConflict:
            return False
        return created


class FeedbackCollector:
    def __init__(self, schema_root: Path | str) -> None:
        self.schema_root = Path(schema_root).resolve()

    def collect_codex(self, payload: Mapping[str, object], *, mode: str = "candidates") -> CaptureResult:
        self._validate_mode(mode)
        if mode == "disabled":
            return CaptureResult(None, None)
        event_name = payload.get("hook_event_name")
        if event_name not in {"Stop", "UserPromptSubmit"}:
            raise ValidationFailure(f"unsupported feedback hook event {event_name!r}")
        session_id = self._required_string(payload, "session_id")
        turn_id = self._required_string(payload, "turn_id")
        project_root = self._required_string(payload, "cwd")
        content_key = "last_assistant_message" if event_name == "Stop" else "prompt"
        content = payload.get(content_key)
        if content is None and event_name == "Stop":
            content = ""
        if not isinstance(content, str):
            raise ValidationFailure(f"feedback hook field {content_key} must be a string or null")
        return self._collect(
            project_root=project_root,
            session_id=session_id,
            turn_id=turn_id,
            event_name=event_name,
            content=content,
            platform="codex",
            model=str(payload.get("model") or "unknown"),
            permission_mode=str(payload.get("permission_mode") or "unknown"),
            stop_hook_active=bool(payload.get("stop_hook_active", False)),
            mode=mode,
        )

    def collect_hermes_turn(
        self,
        *,
        project_root: Path | str,
        session_id: str,
        turn_id: str,
        user_message: str,
        assistant_response: str,
        model: str,
        platform: str,
        mode: str = "candidates",
    ) -> list[CaptureResult]:
        self._validate_mode(mode)
        return [
            self._collect(
                project_root=project_root,
                session_id=session_id,
                turn_id=turn_id,
                event_name="UserPromptSubmit",
                content=user_message,
                platform="hermes",
                model=model or "unknown",
                permission_mode=platform or "unknown",
                stop_hook_active=False,
                mode=mode,
            ),
            self._collect(
                project_root=project_root,
                session_id=session_id,
                turn_id=turn_id,
                event_name="Stop",
                content=assistant_response,
                platform="hermes",
                model=model or "unknown",
                permission_mode=platform or "unknown",
                stop_hook_active=False,
                mode=mode,
            ),
        ]

    def _collect(
        self,
        *,
        project_root: Path | str,
        session_id: str,
        turn_id: str,
        event_name: str,
        content: str,
        platform: str,
        model: str,
        permission_mode: str,
        stop_hook_active: bool,
        mode: str,
    ) -> CaptureResult:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        session_ref = "session-" + self._short_hash(session_id)
        turn_ref = "turn-" + self._short_hash(turn_id)
        capture_id = "capture-" + hashlib.sha256(
            f"{platform}\0{event_name}\0{session_ref}\0{turn_ref}\0{digest}".encode("utf-8")
        ).hexdigest()[:24]
        _, redaction_count = self._redact(content)
        signal = None if stop_hook_active else self._classify(event_name, content)
        if stop_hook_active:
            status = "skipped_continuation"
        elif mode == "metadata":
            status = "metadata_only"
            signal = None
        elif signal is None:
            status = "no_signal"
        else:
            status = "candidate_created"

        observed_at = datetime.now(timezone.utc).isoformat()
        event = self._event(
            signal=signal,
            event_name=event_name,
            content=content,
            capture_id=capture_id,
            session_ref=session_ref,
            turn_ref=turn_ref,
            observed_at=observed_at,
        )
        capture = FeedbackCapture(
            capture_id=capture_id,
            session_ref=session_ref,
            turn_ref=turn_ref,
            event_name=event_name,
            platform=platform,
            model=model,
            permission_mode=permission_mode,
            status=status,
            content_digest=f"sha256:{digest}",
            content_length=len(content),
            redaction_count=redaction_count,
            candidate_event_ids=[event.event_id] if event is not None else [],
            captured_at=observed_at,
        )
        store = FeedbackStore(project_root, self.schema_root)
        if event is not None:
            store.save_event(event)
        created = store.save_capture(capture)
        return CaptureResult(capture, event, duplicate=not created)

    def _event(
        self,
        *,
        signal,
        event_name: str,
        content: str,
        capture_id: str,
        session_ref: str,
        turn_ref: str,
        observed_at: str,
    ) -> FeedbackEvent | None:
        if signal is None:
            return None
        event_type, severity, recurrence_key, expected_behavior, match = signal
        excerpt, _ = self._excerpt(content, match)
        event_id = "feedback-" + hashlib.sha256(
            f"{capture_id}\0{recurrence_key}".encode("utf-8")
        ).hexdigest()[:24]
        is_human = event_name == "UserPromptSubmit"
        return FeedbackEvent(
            event_id=event_id,
            run_id=f"hook-{session_ref}",
            task_id=f"hook-{session_ref}",
            node_id=None,
            turn_id=turn_ref,
            event_type=event_type,
            severity=severity,
            source="human" if is_human else "stop_hook",
            symptom=f"{recurrence_key} signal detected by lifecycle hook.",
            expected_behavior=expected_behavior,
            observed_behavior=excerpt,
            human_action=excerpt if is_human else None,
            evidence_refs=[capture_id],
            recurrence_key=recurrence_key,
            resolution="open",
            reusable_candidate=False,
            sensitivity="internal",
            observed_at=observed_at,
        )

    @staticmethod
    def _required_string(payload: Mapping[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValidationFailure(f"feedback hook field {key} must be a non-empty string")
        return value

    @staticmethod
    def _validate_mode(mode: str) -> None:
        if mode not in FEEDBACK_MODES:
            raise ValidationFailure(
                f"feedback mode must be one of {', '.join(sorted(FEEDBACK_MODES))}"
            )

    @staticmethod
    def _short_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _classify(event_name: str, content: str):
        signals = _STOP_SIGNALS if event_name == "Stop" else _PROMPT_SIGNALS
        for event_type, severity, recurrence_key, expected, pattern in signals:
            match = pattern.search(content)
            if match is not None:
                return event_type, severity, recurrence_key, expected, match
        return None

    @classmethod
    def _excerpt(cls, content: str, match: re.Match[str]) -> tuple[str, int]:
        start = max(0, match.start() - 160)
        end = min(len(content), start + MAX_EXCERPT)
        return cls._redact(content[start:end])

    @staticmethod
    def _redact(content: str) -> tuple[str, int]:
        redacted = content
        count = 0
        for pattern in _SECRET_PATTERNS:
            redacted, replacements = pattern.subn("<redacted>", redacted)
            count += replacements
        return redacted, count


def run_codex_hook(
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    schema_root: Path | str = DEFAULT_REPOSITORY_ROOT / "schemas",
    environment: Mapping[str, str] = os.environ,
) -> int:
    try:
        payload = json.load(input_stream)
        if not isinstance(payload, dict):
            raise ValidationFailure("feedback hook input must be a JSON object")
        mode = environment.get("ENGINEERING_ASSISTANT_FEEDBACK_MODE", "candidates")
        FeedbackCollector(schema_root).collect_codex(payload, mode=mode)
        response = {}
    except Exception as exc:
        response = {
            "systemMessage": f"工程助手反馈采集失败（{type(exc).__name__}），本轮继续执行。"
        }
    json.dump(response, output_stream, ensure_ascii=False)
    output_stream.write("\n")
    output_stream.flush()
    return 0


def main() -> int:
    return run_codex_hook()


if __name__ == "__main__":
    raise SystemExit(main())
