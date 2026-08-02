"""Privacy-aware feedback capture shared by platform lifecycle hooks."""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import re
import secrets
import stat
import sys
from bisect import insort
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping, TextIO

from .artifact_io import ArtifactConflict, ArtifactIO
from .catalog import DEFAULT_REPOSITORY_ROOT
from .model import (
    FeedbackCapture,
    FeedbackDisposition,
    FeedbackEvent,
    UsageEfficiencyFeedback,
    UsageObservationLedger,
)
from .usage_observation import UsageObservationController
from .validation import ValidationFailure, load_json, validate_instance


FEEDBACK_ROOT = ".run-artifacts/engineering-assistant/feedback"
FEEDBACK_MODES = {"candidates", "metadata", "disabled"}
MAX_HOOK_INPUT_BYTES = 1_048_576
HOOK_LOCK_TIMEOUT_SECONDS = 0.1
MAX_FEEDBACK_ARTIFACT_BYTES = 65_536
MAX_DISPOSITION_CLOCK_SKEW_SECONDS = 300
MAX_SUMMARY_RECURRENCE_KEYS = 256
MAX_EVOLUTION_EXPORT_ITEMS = 1000


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(
        r"(?<![A-Za-z0-9])/(?:Users|home|private|tmp|var|etc|opt|Volumes)/[^\s,;]+"
    ),
    re.compile(r"\b[A-Za-z]:\\(?:Users|Temp|Windows)\\[^\s,;]+", re.IGNORECASE),
]
_ASSET_PATTERNS = [
    re.compile(
        r"(?<![A-Za-z0-9])/(?:Users|home|private|tmp|var|etc|opt|Volumes)/[^\s,;]+"
    ),
    re.compile(
        r"(?<![A-Za-z0-9._/-])(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+\.[A-Za-z0-9]+"
    ),
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

_EVENT_ACTION_CONTEXT = {
    "blocker": (
        ["task-execution"],
        "resolve_blocker",
        "requires_user_or_external_input",
        "human_approval_or_input",
    ),
    "human_correction": (
        ["requirements"],
        "correct_behavior",
        "apply_corrected_constraint",
        "user_correction",
    ),
    "rework": (
        ["quality"],
        "rework_output",
        "repair_and_revalidate",
        "none",
    ),
    "scope_change": (
        ["requirements"],
        "expand_scope",
        "recheck_scope_and_acceptance",
        "scope_change",
    ),
    "tool_failure": (
        ["tooling"],
        "repair_failure",
        "repair_and_revalidate",
        "none",
    ),
}


@dataclass(frozen=True)
class CaptureResult:
    capture: FeedbackCapture | None
    event: FeedbackEvent | None
    duplicate: bool = False


class FeedbackStore:
    def __init__(
        self,
        project_root: Path | str,
        schema_root: Path | str,
        *,
        allow_author_repository: bool = False,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.schema_root = Path(schema_root).resolve()
        self.root = self.project_root / FEEDBACK_ROOT
        self.artifacts = ArtifactIO(
            self.project_root,
            self.root,
            lock_timeout_seconds=HOOK_LOCK_TIMEOUT_SECONDS,
        )
        author_mode = allow_author_repository or os.environ.get(
            "ENGINEERING_ASSISTANT_AUTHOR_MODE"
        ) == "1"
        self.artifacts.assert_runtime_target(
            self.schema_root,
            allow_author_repository=author_mode,
        )
        self.artifacts.path()

    def capture_path(self, capture_id: str) -> Path:
        return self.artifacts.path("captures", f"{capture_id}.json")

    def event_path(self, event_id: str) -> Path:
        return self.artifacts.path("events", f"{event_id}.json")

    def efficiency_candidate_path(self, candidate_id: str) -> Path:
        return self.artifacts.path("efficiency-candidates", f"{candidate_id}.json")

    def disposition_path(self, disposition_id: str) -> Path:
        return self.artifacts.path("dispositions", f"{disposition_id}.json")

    def save_capture(self, capture: FeedbackCapture) -> bool:
        self._assert_artifact_size(capture.to_dict())
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
        self._assert_artifact_size(event.to_dict())
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

    def save_disposition(self, disposition: FeedbackDisposition) -> bool:
        payload = disposition.to_dict()
        self._assert_artifact_size(payload)
        if disposition.decision != "accepted_for_evolution" and disposition.reusable_candidate:
            raise ValidationFailure(
                "only accepted_for_evolution feedback may be reusable"
            )
        decided_at = parse_time(disposition.decided_at)
        if decided_at.timestamp() > datetime.now(timezone.utc).timestamp() + MAX_DISPOSITION_CLOCK_SKEW_SECONDS:
            raise ValidationFailure("feedback disposition time is too far in the future")
        validate_instance(
            payload,
            load_json(self.schema_root / "feedback-disposition.schema.json"),
            "feedback-disposition",
        )
        event, _raw = self.artifacts.read_json_limited(
            MAX_FEEDBACK_ARTIFACT_BYTES,
            "events",
            f"{disposition.event_id}.json",
        )
        validate_instance(
            event,
            load_json(self.schema_root / "feedback-event.schema.json"),
            "feedback-event",
        )
        state_id = hashlib.sha256(disposition.event_id.encode("utf-8")).hexdigest()
        state_parts = ("disposition-state", f"{state_id}.json")
        with self.artifacts.transaction("disposition-catalog-transaction"):
            with self.artifacts.transaction("disposition-transactions", state_id):
                _, created = self.artifacts.create_immutable_json_with_status(
                    payload,
                    "dispositions",
                    f"{disposition.disposition_id}.json",
                )
                try:
                    current, _raw = self.artifacts.read_json_limited(
                        MAX_FEEDBACK_ARTIFACT_BYTES,
                        *state_parts,
                    )
                except FileNotFoundError:
                    current = None
                if current is not None:
                    self._validate_disposition_state(current, disposition.event_id)
                    current_order = (
                        parse_time(current["decided_at"]),
                        current["disposition_id"],
                    )
                    incoming_order = (decided_at, disposition.disposition_id)
                    if incoming_order <= current_order:
                        return created
                self._advance_disposition_snapshot_revision()
                state = {
                    "schema_version": "1.0",
                    "event_id": disposition.event_id,
                    "disposition_id": disposition.disposition_id,
                    "decision": disposition.decision,
                    "reusable_candidate": disposition.reusable_candidate,
                    "decided_at": disposition.decided_at,
                    "revision": 0 if current is None else current["revision"] + 1,
                }
                if current is None:
                    self.artifacts.create_immutable_json(state, *state_parts)
                else:
                    self.artifacts.replace_json_cas(
                        state,
                        *state_parts,
                        expected_revision=current["revision"],
                    )
                return created

    def save_efficiency_candidate(self, candidate: UsageEfficiencyFeedback) -> bool:
        self._assert_artifact_size(candidate.to_dict())
        validate_instance(
            candidate.to_dict(),
            load_json(self.schema_root / "usage-efficiency-feedback.schema.json"),
            "usage-efficiency-feedback",
        )
        try:
            _, created = self.artifacts.create_immutable_json_with_status(
                candidate.to_dict(),
                "efficiency-candidates",
                f"{candidate.candidate_id}.json",
            )
        except ArtifactConflict:
            return False
        return created

    def stage_efficiency_candidate(
        self,
        marker_id: str,
        candidate: UsageEfficiencyFeedback,
    ) -> UsageEfficiencyFeedback:
        self._assert_artifact_size(candidate.to_dict())
        validate_instance(
            candidate.to_dict(),
            load_json(self.schema_root / "usage-efficiency-feedback.schema.json"),
            "usage-efficiency-feedback",
        )
        parts = ("efficiency-candidate-staging", f"{marker_id}.json")
        try:
            _, created = self.artifacts.create_immutable_json_with_status(
                candidate.to_dict(),
                *parts,
            )
        except ArtifactConflict:
            created = False
        if created:
            return candidate
        payload = self.artifacts.read_json(*parts)
        validate_instance(
            payload,
            load_json(self.schema_root / "usage-efficiency-feedback.schema.json"),
            "usage-efficiency-feedback",
        )
        return UsageEfficiencyFeedback(**payload)

    @contextmanager
    def efficiency_transaction(self):
        with self.artifacts.transaction("efficiency-transaction"):
            yield

    def cleanup_efficiency_staging(self, marker_id: str) -> None:
        self.artifacts.delete_regular_file(
            "efficiency-candidate-staging",
            f"{marker_id}.json",
        )

    def reserve_efficiency_observation(
        self,
        observation_id: str,
    ) -> tuple[str, int | None]:
        marker_id = hashlib.sha256(observation_id.encode("utf-8")).hexdigest()
        parts = ("efficiency-candidate-index", f"{marker_id}.json")
        payload = {"schema_version": "1.0", "status": "pending", "revision": 0}
        try:
            _, created = self.artifacts.create_immutable_json_with_status(
                payload,
                *parts,
            )
        except ArtifactConflict:
            created = False
        if created:
            return marker_id, 0
        current = self.artifacts.read_json(*parts)
        if current.get("status") == "committed":
            return marker_id, None
        if (
            current.get("schema_version") != "1.0"
            or current.get("status") != "pending"
            or not isinstance(current.get("revision"), int)
        ):
            raise ValidationFailure("invalid efficiency candidate reservation")
        return marker_id, current["revision"]

    def commit_efficiency_observation(
        self,
        marker_id: str,
        *,
        expected_revision: int,
        ledger_revision: int,
    ) -> None:
        parts = ("efficiency-candidate-index", f"{marker_id}.json")
        try:
            self.artifacts.replace_json_cas(
                {
                    "schema_version": "1.0",
                    "status": "committed",
                    "revision": expected_revision + 1,
                    "ledger_revision": ledger_revision,
                },
                *parts,
                expected_revision=expected_revision,
            )
        except ArtifactConflict:
            current = self.artifacts.read_json(*parts)
            if current.get("status") != "committed":
                raise

    def committed_efficiency_ledger_revision(
        self,
        observation_id: str,
    ) -> int | None:
        marker_id = hashlib.sha256(observation_id.encode("utf-8")).hexdigest()
        try:
            current = self.artifacts.read_json(
                "efficiency-candidate-index", f"{marker_id}.json"
            )
        except FileNotFoundError:
            return None
        ledger_revision = current.get("ledger_revision")
        if (
            current.get("schema_version") != "1.0"
            or current.get("status") != "committed"
            or not isinstance(ledger_revision, int)
            or ledger_revision < 0
        ):
            return None
        return ledger_revision

    def iter_efficiency_candidates(self) -> Iterator[dict | None]:
        try:
            directory_context = self.artifacts.open_directory(
                "efficiency-candidates"
            )
            directory_fd = directory_context.__enter__()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ValidationFailure(
                "efficiency candidate directory is not a safe directory"
            ) from exc
        try:
            metadata = os.fstat(directory_fd)
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValidationFailure(
                    "efficiency candidate directory is not a safe directory"
                )
            schema = load_json(
                self.schema_root / "usage-efficiency-feedback.schema.json"
            )
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    name = entry.name
                    if not name.endswith(".json"):
                        continue
                    try:
                        payload = self._read_safe_candidate(directory_fd, name)
                        validate_instance(
                            payload,
                            schema,
                            "usage-efficiency-feedback",
                        )
                        candidate_id = payload["candidate_id"]
                        if name != f"{candidate_id}.json":
                            raise ValidationFailure("invalid efficiency candidate identity")
                    except Exception:
                        yield None
                        continue
                    yield payload
        finally:
            directory_context.__exit__(None, None, None)

    def iter_feedback_events(self) -> Iterator[dict | None]:
        yield from self._iter_feedback_artifacts(
            "events",
            "feedback-event.schema.json",
            "event_id",
        )

    def iter_feedback_dispositions(self) -> Iterator[dict | None]:
        yield from self._iter_feedback_artifacts(
            "dispositions",
            "feedback-disposition.schema.json",
            "disposition_id",
        )

    def _iter_feedback_artifacts(
        self,
        directory_name: str,
        schema_name: str,
        identity_key: str,
    ) -> Iterator[dict | None]:
        try:
            directory_context = self.artifacts.open_directory(directory_name)
            directory_fd = directory_context.__enter__()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ValidationFailure("feedback artifact directory is unsafe") from exc
        try:
            if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
                raise ValidationFailure("feedback artifact directory is unsafe")
            schema = load_json(self.schema_root / schema_name)
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    name = entry.name
                    if not name.endswith(".json"):
                        continue
                    try:
                        payload = self._read_safe_candidate(directory_fd, name)
                        validate_instance(payload, schema, schema_name.removesuffix(".schema.json"))
                        identity = payload[identity_key]
                        if name != f"{identity}.json":
                            raise ValidationFailure("invalid feedback artifact identity")
                    except Exception:
                        yield None
                        continue
                    yield payload
        finally:
            directory_context.__exit__(None, None, None)

    @staticmethod
    def _read_safe_candidate(directory_fd: int, name: str) -> dict:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValidationFailure("efficiency candidate is not a regular file")
            if metadata.st_size > MAX_FEEDBACK_ARTIFACT_BYTES:
                raise ValidationFailure("efficiency candidate is too large")
            raw = os.read(descriptor, MAX_FEEDBACK_ARTIFACT_BYTES + 1)
            if len(raw) > MAX_FEEDBACK_ARTIFACT_BYTES:
                raise ValidationFailure("efficiency candidate is too large")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValidationFailure("efficiency candidate must be an object")
            return payload
        finally:
            os.close(descriptor)

    @staticmethod
    def _assert_artifact_size(payload: dict) -> None:
        encoded = ArtifactIO.canonical_json_bytes(payload)
        if len(encoded) > MAX_FEEDBACK_ARTIFACT_BYTES:
            raise ValidationFailure("feedback artifact is too large")

    @staticmethod
    def _validate_disposition_state(payload: dict, event_id: str) -> None:
        required = {
            "schema_version",
            "event_id",
            "disposition_id",
            "decision",
            "reusable_candidate",
            "decided_at",
            "revision",
        }
        if (
            set(payload) != required
            or payload.get("schema_version") != "1.0"
            or payload.get("event_id") != event_id
            or not isinstance(payload.get("revision"), int)
            or payload["revision"] < 0
            or payload.get("decision")
            not in {"accepted_for_evolution", "resolved", "rejected", "deferred"}
            or not isinstance(payload.get("reusable_candidate"), bool)
        ):
            raise ValidationFailure("invalid feedback disposition state")
        parse_time(payload["decided_at"])

    def disposition_snapshot_revision(self) -> int:
        try:
            payload, _raw = self.artifacts.read_json_limited(
                MAX_FEEDBACK_ARTIFACT_BYTES,
                "disposition-catalog-state",
                "state.json",
            )
        except FileNotFoundError:
            return 0
        if (
            set(payload) != {"schema_version", "revision"}
            or payload.get("schema_version") != "1.0"
            or not isinstance(payload.get("revision"), int)
            or isinstance(payload.get("revision"), bool)
            or payload["revision"] < 0
        ):
            raise ValidationFailure("invalid feedback disposition catalog state")
        return payload["revision"]

    def _advance_disposition_snapshot_revision(self) -> int:
        current = self.disposition_snapshot_revision()
        payload = {"schema_version": "1.0", "revision": current + 1}
        if current == 0:
            path = self.artifacts.path("disposition-catalog-state", "state.json")
            if not path.exists():
                self.artifacts.create_immutable_json(
                    payload,
                    "disposition-catalog-state",
                    "state.json",
                )
                return 1
        self.artifacts.replace_json_cas(
            payload,
            "disposition-catalog-state",
            "state.json",
            expected_revision=current,
        )
        return current + 1


class FeedbackCollector:
    def __init__(self, schema_root: Path | str) -> None:
        self.schema_root = Path(schema_root).resolve()

    def collect_codex(self, payload: Mapping[str, object], *, mode: str = "candidates") -> CaptureResult:
        self._validate_mode(mode)
        if mode == "disabled":
            return CaptureResult(None, None)
        event_name = payload.get("hook_event_name")
        if event_name == "PostToolUse":
            return self.collect_tool_result(payload, mode=mode, platform="codex")
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

    def collect_usage_efficiency(
        self,
        *,
        project_root: Path | str,
        ledger: UsageObservationLedger,
        source: str = "stop_hook",
    ) -> UsageEfficiencyFeedback | None:
        signals = set(ledger.signals)
        if "retention_truncated" not in signals and (
            set(ledger.tool_use_signatures) - set(ledger.completed_tool_use_ids)
        ):
            signals.add("tool_without_post")
        if not signals:
            return None
        store = FeedbackStore(project_root, self.schema_root)
        with store.efficiency_transaction():
            marker_id, marker_revision = store.reserve_efficiency_observation(
                ledger.plan.observation_id
            )
            if marker_revision is None:
                store.cleanup_efficiency_staging(marker_id)
                return None
            candidate_id = "efficiency-" + secrets.token_hex(12)
            candidate = store.stage_efficiency_candidate(
                marker_id,
                UsageEfficiencyFeedback(
                    schema_version="1.0",
                    candidate_id=candidate_id,
                    source=source,
                    status="pending",
                    tool_calls=ledger.tool_calls,
                    shell_calls=ledger.shell_calls,
                    index_queries=ledger.index_queries,
                    output_bytes=ledger.output_bytes,
                    reference_tool_calls=ledger.plan.reference_tool_calls,
                    reference_shell_calls=ledger.plan.reference_shell_calls,
                    reference_index_queries=ledger.plan.reference_index_queries,
                    reference_output_bytes=ledger.plan.reference_output_bytes,
                    signals=sorted(signals),
                    coverage=list(ledger.plan.coverage),
                    ledger_revision=ledger.revision,
                    reusable_candidate=False,
                ),
            )
            store.save_efficiency_candidate(candidate)
            store.commit_efficiency_observation(
                marker_id,
                expected_revision=marker_revision,
                ledger_revision=candidate.ledger_revision,
            )
            store.cleanup_efficiency_staging(marker_id)
            return candidate

    def committed_usage_efficiency_revision(
        self,
        *,
        project_root: Path | str,
        observation_id: str,
    ) -> int | None:
        return FeedbackStore(
            project_root,
            self.schema_root,
        ).committed_efficiency_ledger_revision(observation_id)
    def collect_tool_result(
        self,
        payload: Mapping[str, object],
        *,
        mode: str,
        platform: str,
    ) -> CaptureResult:
        self._validate_mode(mode)
        if mode == "disabled":
            return CaptureResult(None, None)
        failure_kind = self._tool_failure_kind(
            payload.get("tool_response"),
            tool_name=str(payload.get("tool_name") or ""),
        )
        if failure_kind is None:
            return CaptureResult(None, None)
        session_id = self._required_string(payload, "session_id")
        turn_id = self._required_string(payload, "turn_id")
        project_root = self._required_string(payload, "cwd")
        tool_name = self._required_string(payload, "tool_name")
        response_summary = json.dumps(
            payload.get("tool_response"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(response_summary.encode("utf-8")).hexdigest()
        session_ref = "session-" + self._short_hash(session_id)
        turn_ref = "turn-" + self._short_hash(turn_id)
        category = self._tool_category(tool_name)
        recurrence_key = f"reported-tool-failure-{category}-{failure_kind}"
        capture_id = "capture-" + hashlib.sha256(
            f"{platform}\0PostToolUse\0{session_ref}\0{turn_ref}\0{digest}".encode("utf-8")
        ).hexdigest()[:24]
        event_id = "feedback-" + hashlib.sha256(
            f"{capture_id}\0{recurrence_key}".encode("utf-8")
        ).hexdigest()[:24]
        observed_at = datetime.now(timezone.utc).isoformat()
        _, redaction_count = self._redact(response_summary)
        run_id, task_id, flow_id, node_id = self._runtime_context(
            payload.get("tool_response")
        )
        event = None
        if mode == "candidates":
            event = FeedbackEvent(
                event_id=event_id,
                run_id=run_id or f"hook-{session_ref}",
                task_id=task_id or run_id or f"hook-{session_ref}",
                node_id=node_id,
                flow_id=flow_id,
                turn_id=turn_ref,
                event_type="tool_failure",
                severity="info",
                source="tool_hook",
                symptom=f"{recurrence_key} signal detected by lifecycle hook.",
                expected_behavior="工具失败信号应先记录并结合任务意图确认。",
                observed_behavior=(
                    f"{category} tool reported {failure_kind}; raw tool content was omitted."
                ),
                human_action=None,
                evidence_refs=[capture_id],
                scope_tags=["tooling"],
                change_kind="unknown",
                affected_asset_refs=[
                    "tool-ref-sha256:"
                    + hashlib.sha256(tool_name.encode("utf-8")).hexdigest()
                ],
                recovery_condition="unknown",
                manual_intervention_kind="none",
                recurrence_key=recurrence_key,
                resolution="open",
                reusable_candidate=False,
                sensitivity="internal",
                observed_at=observed_at,
            )
        capture = FeedbackCapture(
            capture_id=capture_id,
            session_ref=session_ref,
            turn_ref=turn_ref,
            event_name="PostToolUse",
            platform=platform,
            model=str(payload.get("model") or "unknown"),
            permission_mode=str(payload.get("permission_mode") or "unknown"),
            status="candidate_created" if event is not None else "metadata_only",
            content_digest=f"sha256:{digest}",
            content_length=len(response_summary),
            redaction_count=redaction_count,
            candidate_event_ids=[event.event_id] if event is not None else [],
            captured_at=observed_at,
        )
        store = FeedbackStore(project_root, self.schema_root)
        if event is not None:
            store.save_event(event)
        created = store.save_capture(capture)
        return CaptureResult(capture, event, duplicate=not created)

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
        if mode == "disabled":
            return []
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
            return CaptureResult(None, None)
        else:
            status = "candidate_created"

        observed_at = datetime.now(timezone.utc).isoformat()
        runtime_context = self._active_run_context(project_root)
        event = self._event(
            signal=signal,
            event_name=event_name,
            capture_id=capture_id,
            session_ref=session_ref,
            turn_ref=turn_ref,
            observed_at=observed_at,
            affected_asset_refs=self._asset_refs(content),
            runtime_context=runtime_context,
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
        capture_id: str,
        session_ref: str,
        turn_ref: str,
        observed_at: str,
        affected_asset_refs: list[str],
        runtime_context: tuple[str, str, str, str | None] | None,
    ) -> FeedbackEvent | None:
        if signal is None:
            return None
        event_type, severity, recurrence_key, expected_behavior, _match = signal
        scope_tags, change_kind, recovery_condition, intervention_kind = (
            _EVENT_ACTION_CONTEXT[event_type]
        )
        event_id = "feedback-" + hashlib.sha256(
            f"{capture_id}\0{recurrence_key}".encode("utf-8")
        ).hexdigest()[:24]
        is_human = event_name == "UserPromptSubmit"
        run_id = runtime_context[0] if runtime_context else f"hook-{session_ref}"
        task_id = runtime_context[1] if runtime_context else f"hook-{session_ref}"
        flow_id = runtime_context[2] if runtime_context else None
        node_id = runtime_context[3] if runtime_context else None
        return FeedbackEvent(
            event_id=event_id,
            run_id=run_id,
            task_id=task_id,
            node_id=node_id,
            flow_id=flow_id,
            turn_id=turn_ref,
            event_type=event_type,
            severity=severity,
            source="human" if is_human else "stop_hook",
            symptom=f"{recurrence_key} signal detected by lifecycle hook.",
            expected_behavior=expected_behavior,
            observed_behavior=(
                f"{recurrence_key} signal detected; raw hook content was omitted."
            ),
            human_action=(
                "User supplied a correction or scope change; raw hook content was omitted."
                if is_human
                else None
            ),
            evidence_refs=[capture_id],
            scope_tags=scope_tags,
            change_kind=change_kind,
            affected_asset_refs=affected_asset_refs,
            recovery_condition=recovery_condition,
            manual_intervention_kind=intervention_kind,
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

    @staticmethod
    def _redact(content: str) -> tuple[str, int]:
        redacted = content
        count = 0
        for pattern in _SECRET_PATTERNS:
            redacted, replacements = pattern.subn("<redacted>", redacted)
            count += replacements
        return redacted, count

    @staticmethod
    def _tool_failure_kind(response: object, *, tool_name: str = "") -> str | None:
        pending = [(response, True)]
        visited = 0
        tool_error = False
        bash_response = tool_name.casefold() == "bash"
        while pending and visited < 64:
            current, is_root = pending.pop()
            visited += 1
            if isinstance(current, list):
                pending.extend((item, False) for item in current)
                continue
            if not isinstance(current, Mapping):
                continue
            command_execution = current.get("type") == "command_execution"
            exit_code = current.get("exit_code", current.get("exitCode"))
            if (
                (is_root or command_execution or bash_response)
                and isinstance(exit_code, int)
                and not isinstance(exit_code, bool)
                and exit_code != 0
            ):
                return "nonzero-exit"
            error = current.get("error")
            status = current.get("status")
            if (
                (is_root and (current.get("isError") is True or bool(error)))
                or (
                    (is_root or command_execution)
                    and isinstance(status, str)
                    and status.casefold() in {"error", "failed", "failure"}
                )
            ):
                tool_error = True
            pending.extend((value, False) for value in current.values())
        return "tool-error" if tool_error else None

    @staticmethod
    def _runtime_context(
        response: object,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        pending = [response]
        visited = 0
        while pending and visited < 64:
            current = pending.pop()
            visited += 1
            if isinstance(current, str):
                try:
                    decoded = json.loads(current)
                except (json.JSONDecodeError, TypeError):
                    continue
                pending.append(decoded)
                continue
            if isinstance(current, list):
                pending.extend(current)
                continue
            if not isinstance(current, Mapping):
                continue
            state = current.get("state")
            if isinstance(state, Mapping) and isinstance(state.get("run_id"), str):
                return (
                    state["run_id"],
                    state.get("task_id") if isinstance(state.get("task_id"), str) else None,
                    state.get("flow_id") if isinstance(state.get("flow_id"), str) else None,
                    state.get("current_node") if isinstance(state.get("current_node"), str) else None,
                )
            pending.extend(current.values())
        return None, None, None, None

    @staticmethod
    def _active_run_context(
        project_root: Path | str,
    ) -> tuple[str, str, str, str | None] | None:
        run_root = Path(project_root).resolve() / ".run-artifacts/engineering-assistant"
        if not run_root.is_dir():
            return None
        active = []
        try:
            for path in sorted(run_root.glob("*/run-state.json"))[:256]:
                if path.stat().st_size > 262_144:
                    continue
                state = json.loads(path.read_text(encoding="utf-8"))
                if (
                    state.get("schema_version") == "2"
                    and state.get("status") not in {"blocked", "cancelled", "completed"}
                    and all(
                        isinstance(state.get(key), str) and state.get(key)
                        for key in ("run_id", "task_id", "flow_id")
                    )
                ):
                    active.append(state)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if len(active) != 1:
            return None
        state = active[0]
        node_id = state.get("current_node")
        return (
            state["run_id"],
            state["task_id"],
            state["flow_id"],
            node_id if isinstance(node_id, str) else None,
        )

    @staticmethod
    def _tool_category(tool_name: str) -> str:
        lowered = tool_name.casefold()
        if lowered == "bash":
            return "shell"
        if lowered.startswith("mcp__"):
            return "mcp"
        return "tool"

    @staticmethod
    def _asset_refs(content: str) -> list[str]:
        refs: list[str] = []
        for pattern in _ASSET_PATTERNS:
            for match in pattern.finditer(content):
                reference = (
                    "asset-ref-sha256:"
                    + hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()
                )
                if reference not in refs:
                    refs.append(reference)
                if len(refs) >= 32:
                    return refs
        return refs


def summarize_usage_efficiency(
    project_root: Path | str,
    schema_root: Path | str = DEFAULT_REPOSITORY_ROOT / "schemas",
) -> dict:
    candidates = FeedbackStore(project_root, schema_root).iter_efficiency_candidates()
    totals = {
        "tool_calls": 0,
        "shell_calls": 0,
        "index_queries": 0,
        "output_bytes": 0,
    }
    status_counts: dict[str, int] = {}
    signal_counts: dict[str, int] = {}
    coverage: set[str] = set()
    candidate_count = 0
    skipped_invalid_count = 0
    for candidate in candidates:
        if candidate is None:
            skipped_invalid_count += 1
            continue
        candidate_count += 1
        for key in totals:
            totals[key] += candidate[key]
        status = candidate["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        for signal in candidate["signals"]:
            signal_counts[signal] = signal_counts.get(signal, 0) + 1
        coverage.update(candidate["coverage"])
    return {
        "schema_version": "1.0",
        "candidate_count": candidate_count,
        "skipped_invalid_count": skipped_invalid_count,
        "status_counts": dict(sorted(status_counts.items())),
        "signal_counts": dict(sorted(signal_counts.items())),
        "totals": totals,
        "coverage": sorted(coverage),
        "feedback_events": summarize_feedback_events(
            project_root,
            schema_root,
        ),
    }


def summarize_feedback_events(
    project_root: Path | str,
    schema_root: Path | str = DEFAULT_REPOSITORY_ROOT / "schemas",
    *,
    item_limit: int = 100,
    run_id: str | None = None,
) -> dict:
    if item_limit < 0 or item_limit > 1000:
        raise ValidationFailure("feedback summary item limit must be between 0 and 1000")
    store = FeedbackStore(project_root, schema_root)
    skipped_invalid_disposition_count = 0
    event_type_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    recurrence_counts: dict[str, int] = {}
    recurrence_overflow_event_count = 0
    decision_counts: dict[str, int] = {"open": 0}
    recent_heap: list[tuple[str, str, dict]] = []
    event_count = 0
    reusable_candidate_count = 0
    skipped_invalid_event_count = 0
    for event in store.iter_feedback_events():
        if event is None:
            skipped_invalid_event_count += 1
            continue
        if run_id is not None and event.get("run_id") != run_id:
            continue
        event_count += 1
        event_type_counts[event["event_type"]] = event_type_counts.get(event["event_type"], 0) + 1
        severity_counts[event["severity"]] = severity_counts.get(event["severity"], 0) + 1
        recurrence_key = event["recurrence_key"]
        if recurrence_key in recurrence_counts:
            recurrence_counts[recurrence_key] += 1
        elif len(recurrence_counts) < MAX_SUMMARY_RECURRENCE_KEYS:
            recurrence_counts[recurrence_key] = 1
        else:
            recurrence_overflow_event_count += 1
        state_id = hashlib.sha256(event["event_id"].encode("utf-8")).hexdigest()
        try:
            disposition, _raw = store.artifacts.read_json_limited(
                MAX_FEEDBACK_ARTIFACT_BYTES,
                "disposition-state",
                f"{state_id}.json",
            )
            store._validate_disposition_state(disposition, event["event_id"])
        except FileNotFoundError:
            disposition = None
        except Exception:
            skipped_invalid_disposition_count += 1
            disposition = None
        decision = disposition["decision"] if disposition else event["resolution"]
        reusable = bool(disposition and disposition["reusable_candidate"])
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        reusable_candidate_count += int(reusable)
        item = {
                "event_id": event["event_id"],
                "event_type": event["event_type"],
                "severity": event["severity"],
                "recurrence_key": event["recurrence_key"],
                "decision": decision,
                "reusable_candidate": reusable,
                "change_kind": event.get("change_kind", "unknown"),
                "recovery_condition": event.get("recovery_condition", "unknown"),
                "manual_intervention_kind": event.get("manual_intervention_kind", "none"),
                "observed_at": event["observed_at"],
            }
        if item_limit:
            heap_item = (item["observed_at"], item["event_id"], item)
            if len(recent_heap) < item_limit:
                heapq.heappush(recent_heap, heap_item)
            elif heap_item[:2] > recent_heap[0][:2]:
                heapq.heapreplace(recent_heap, heap_item)
    if decision_counts["open"] == 0:
        decision_counts.pop("open")
    return {
        "schema_version": "1.0",
        "event_count": event_count,
        "reusable_candidate_count": reusable_candidate_count,
        "event_type_counts": dict(sorted(event_type_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
        "recurrence_counts": dict(sorted(recurrence_counts.items())),
        "recurrence_overflow_event_count": recurrence_overflow_event_count,
        "decision_counts": dict(sorted(decision_counts.items())),
        "recent_items": [
            item
            for _observed_at, _event_id, item in sorted(
                recent_heap,
                reverse=True,
            )
        ],
        "skipped_invalid_event_count": skipped_invalid_event_count,
        "skipped_invalid_disposition_count": skipped_invalid_disposition_count,
    }


def export_feedback_evolution(
    project_root: Path | str,
    schema_root: Path | str = DEFAULT_REPOSITORY_ROOT / "schemas",
    *,
    limit: int = 100,
    after_event_ref: str | None = None,
    snapshot_revision: int | None = None,
) -> dict:
    """Export review inputs from current accepted dispositions without changing assets."""
    if limit < 1 or limit > MAX_EVOLUTION_EXPORT_ITEMS:
        raise ValidationFailure(
            "feedback evolution export limit must be between 1 and 1000"
        )
    if after_event_ref is not None and not after_event_ref:
        raise ValidationFailure("feedback evolution cursor must not be empty")
    if after_event_ref is not None and snapshot_revision is None:
        raise ValidationFailure(
            "feedback evolution pagination requires a snapshot revision"
        )
    if after_event_ref is None and snapshot_revision is not None:
        raise ValidationFailure(
            "feedback evolution snapshot revision requires a cursor"
        )
    store = FeedbackStore(project_root, schema_root)
    disposition_schema = load_json(
        store.schema_root / "feedback-disposition.schema.json"
    )
    with store.artifacts.transaction("disposition-catalog-transaction"):
        current_snapshot_revision = store.disposition_snapshot_revision()
        if (
            snapshot_revision is not None
            and snapshot_revision != current_snapshot_revision
        ):
            raise ValidationFailure(
                "feedback evolution snapshot changed; restart from the first page"
            )
    selected: list[tuple[str, dict]] = []
    skipped_invalid_event_count = 0
    skipped_invalid_disposition_count = 0
    for event in store.iter_feedback_events():
        if event is None:
            skipped_invalid_event_count += 1
            continue
        event_id = event["event_id"]
        event_ref = _opaque_feedback_ref("feedback-event", event_id)
        if after_event_ref is not None and event_ref <= after_event_ref:
            continue
        state_id = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
        try:
            state, _raw = store.artifacts.read_json_limited(
                MAX_FEEDBACK_ARTIFACT_BYTES,
                "disposition-state",
                f"{state_id}.json",
            )
            store._validate_disposition_state(state, event_id)
            disposition, _raw = store.artifacts.read_json_limited(
                MAX_FEEDBACK_ARTIFACT_BYTES,
                "dispositions",
                f"{state['disposition_id']}.json",
            )
            validate_instance(
                disposition,
                disposition_schema,
                "feedback-disposition",
            )
            if any(
                disposition.get(key) != state.get(key)
                for key in (
                    "event_id",
                    "disposition_id",
                    "decision",
                    "reusable_candidate",
                    "decided_at",
                )
            ):
                raise ValidationFailure(
                    "feedback disposition does not match its current state"
                )
        except FileNotFoundError:
            continue
        except Exception:
            skipped_invalid_disposition_count += 1
            continue
        if (
            state["decision"] != "accepted_for_evolution"
            or state["reusable_candidate"] is not True
        ):
            continue
        proposal = _feedback_evolution_proposal(event, disposition)
        insort(selected, (event_ref, proposal))
        if len(selected) > limit + 1:
            selected.pop()
    with store.artifacts.transaction("disposition-catalog-transaction"):
        if store.disposition_snapshot_revision() != current_snapshot_revision:
            raise ValidationFailure(
                "feedback evolution snapshot changed; restart from the first page"
            )

    has_more = len(selected) > limit
    page = selected[:limit]
    payload = {
        "schema_version": "1.0",
        "proposal_count": len(page),
        "proposals": [proposal for _event_ref, proposal in page],
        "next_after_event_ref": page[-1][0] if has_more and page else None,
        "snapshot_revision": current_snapshot_revision,
        "skipped_invalid_event_count": skipped_invalid_event_count,
        "skipped_invalid_disposition_count": skipped_invalid_disposition_count,
    }
    validate_instance(
        payload,
        load_json(store.schema_root / "feedback-evolution-export.schema.json"),
        "feedback-evolution-export",
    )
    return payload


def _feedback_evolution_proposal(event: dict, disposition: dict) -> dict:
    scope_map = {
        "blocker": {"feedback", "state_machine"},
        "human_correction": {"behavior", "feedback"},
        "rework": {"feedback", "quality"},
        "quality_regression": {"feedback", "quality"},
        "tool_failure": {"feedback", "hook"},
        "scope_change": {"behavior", "feedback"},
        "positive_outcome": {"capability", "feedback"},
    }
    scopes = set(scope_map[event["event_type"]])
    if "quality" in event.get("scope_tags", []):
        scopes.add("quality")
    if "tooling" in event.get("scope_tags", []):
        scopes.add("hook")
    identity = f"{event['event_id']}\0{disposition['disposition_id']}"
    return {
        "schema_version": "1.0",
        "proposal_id": "feedback-evolution-"
        + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
        "event_ref": _opaque_feedback_ref("feedback-event", event["event_id"]),
        "disposition_id": disposition["disposition_id"],
        "decision": "accepted_for_evolution",
        "event_type": event["event_type"],
        "severity": event["severity"],
        "recurrence_key_digest": _opaque_feedback_ref(
            "recurrence-key", event["recurrence_key"]
        ),
        "scope_tags": list(event.get("scope_tags", ["unknown"])),
        "change_kind": event.get("change_kind", "unknown"),
        "affected_asset_ref_digests": [
            _opaque_feedback_ref("asset-ref", reference)
            for reference in event.get("affected_asset_refs", [])
        ],
        "recovery_condition": event.get("recovery_condition", "unknown"),
        "manual_intervention_kind": event.get(
            "manual_intervention_kind", "none"
        ),
        "evidence_ref_digests": [
            _opaque_feedback_ref("evidence-ref", reference)
            for reference in event["evidence_refs"]
        ],
        "suggested_regression_scopes": sorted(scopes),
        "requires_review": True,
        "formal_assets_modified": False,
        "accepted_at": disposition["decided_at"],
    }


def _opaque_feedback_ref(kind: str, value: str) -> str:
    return f"{kind}-sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def run_codex_hook(
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    schema_root: Path | str = DEFAULT_REPOSITORY_ROOT / "schemas",
    environment: Mapping[str, str] = os.environ,
) -> int:
    response: dict = {}
    try:
        raw = input_stream.read(MAX_HOOK_INPUT_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_HOOK_INPUT_BYTES:
            raise ValidationFailure("engineering-assistant hook input is too large")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValidationFailure("feedback hook input must be a JSON object")
        if payload.get("hook_event_name") not in {
            "PreToolUse",
            "PostToolUse",
            "Stop",
            "UserPromptSubmit",
        }:
            raise ValidationFailure("unsupported engineering-assistant hook event")
    except Exception:
        json.dump({}, output_stream, ensure_ascii=False)
        output_stream.write("\n")
        output_stream.flush()
        return 0

    observer = UsageObservationController(schema_root)
    try:
        response = observer.handle(payload, environment)
        active = observer.is_active(payload)
    except Exception:
        try:
            active = observer.is_active(payload)
        except Exception:
            active = False

    if active and payload.get("hook_event_name") in {
        "PostToolUse",
        "Stop",
        "UserPromptSubmit",
    }:
        event_name = payload.get("hook_event_name")
        tool_name = payload.get("tool_name")
        scoped_plugin_completion = (
            event_name == "PostToolUse"
            and isinstance(tool_name, str)
            and observer.is_plugin_tool(tool_name)
        )
        mode = environment.get("ENGINEERING_ASSISTANT_FEEDBACK_MODE", "candidates")
        collector = FeedbackCollector(schema_root)
        efficiency_complete = mode != "candidates"
        efficiency_signal_observed = mode != "candidates"
        reported_ledger_revision: int | None = None
        ledger: UsageObservationLedger | None = None
        feedback_complete = False
        if (
            (
                scoped_plugin_completion
                or (
                    event_name == "Stop"
                    and not bool(payload.get("stop_hook_active", False))
                )
            )
            and mode == "candidates"
        ):
            try:
                ledger = observer.current_ledger(payload)
                pending_tool_uses = set(ledger.tool_use_signatures) - set(
                    ledger.completed_tool_use_ids
                )
                if not scoped_plugin_completion or not pending_tool_uses:
                    candidate = collector.collect_usage_efficiency(
                        project_root=str(payload.get("cwd") or ""),
                        ledger=ledger,
                        source=(
                            "tool_hook" if scoped_plugin_completion else "stop_hook"
                        ),
                    )
                    efficiency_complete = True
                    efficiency_signal_observed = (
                        candidate is not None or bool(ledger.signals)
                    )
                    if candidate is not None:
                        reported_ledger_revision = candidate.ledger_revision
                    elif ledger.signals:
                        reported_ledger_revision = (
                            collector.committed_usage_efficiency_revision(
                                project_root=str(payload.get("cwd") or ""),
                                observation_id=ledger.plan.observation_id,
                            )
                        )
                    elif event_name == "Stop":
                        reported_ledger_revision = ledger.revision
            except Exception:
                pass
        try:
            collector.collect_codex(payload, mode=mode)
            feedback_complete = True
        except Exception:
            pass
        if (
            (
                (
                    scoped_plugin_completion
                    and efficiency_signal_observed
                )
                or (
                    event_name == "Stop"
                    and not bool(payload.get("stop_hook_active", False))
                )
            )
            and efficiency_complete
            and feedback_complete
        ):
            try:
                if mode != "candidates":
                    observer.discard_ledger(payload)
                elif (
                    ledger is not None
                    and reported_ledger_revision == ledger.revision
                ):
                    observer.finalize_ledger(payload, ledger)
            except Exception:
                pass
    json.dump(response, output_stream, ensure_ascii=False)
    output_stream.write("\n")
    output_stream.flush()
    return 0


def main() -> int:
    return run_codex_hook()


if __name__ == "__main__":
    raise SystemExit(main())
