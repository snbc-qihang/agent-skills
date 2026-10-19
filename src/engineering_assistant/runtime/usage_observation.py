"""Turn-scoped, non-blocking usage observation for engineering-assistant hooks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable, Mapping

from .artifact_io import ArtifactConflict, ArtifactIO, artifact_fs
from .codec import usage_observation_ledger_from_dict
from .hook_gate import (
    OBSERVATION_ROOT,
    hashed_ref,
    is_explicit_plugin_request,
    is_observation_exempt_tool,
    is_plugin_tool,
)
from .model import UsageObservationLedger, UsageObservationPlan
from .validation import ValidationFailure, load_json, validate_instance


DEFAULT_REFERENCE_TOOL_CALLS = 12
DEFAULT_REFERENCE_SHELL_CALLS = 6
DEFAULT_REFERENCE_INDEX_QUERIES = 1
DEFAULT_REFERENCE_OUTPUT_BYTES = 64_000
MAX_CAS_ATTEMPTS = 8
MAX_RETAINED_TOOL_EVENTS = 256
MAX_OBSERVATION_LEDGER_BYTES = 524_288
LARGE_SINGLE_OUTPUT_BYTES = 32_000
HOOK_LOCK_TIMEOUT_SECONDS = 0.1
STALE_LEDGER_TTL_SECONDS = 24 * 60 * 60
MAX_STALE_LEDGER_SCAN_FILES = 256
MAX_STALE_LEDGER_SCAN_DIRECTORIES = 256
_SESSION_REF = re.compile(r"^session-[0-9a-f]{16}$")
_TURN_FILE = re.compile(r"^turn-[0-9a-f]{16}\.json$")
_SHELL_WRAPPER = re.compile(
    r"^(?:/bin/)?(?:ba|z)?sh\s+-lc\s+([\"'])(.*)\1$",
    re.DOTALL,
)
_FILE_READER_COMMAND = re.compile(
    r"(?:^|&&|\|\||[;|])\s*(?:(?:command|exec)\s+)?"
    r"(?:[^\s;&|\"']*/)?(?:awk|cat|head|less|more|nl|sed|tail)\b"
)

class UsageObservationStore:
    def __init__(self, project_root: Path | str, schema_root: Path | str) -> None:
        self.project_root = Path(project_root).resolve()
        self.schema_root = Path(schema_root).resolve()
        self.artifacts = ArtifactIO(
            self.project_root,
            self.project_root / OBSERVATION_ROOT,
            lock_timeout_seconds=HOOK_LOCK_TIMEOUT_SECONDS,
        )
        self.artifacts.assert_runtime_target(self.schema_root)
        self.plan_schema = load_json(
            self.schema_root / "usage-observation-plan.schema.json"
        )
        self.ledger_schema = load_json(
            self.schema_root / "usage-observation-ledger.schema.json"
        )

    @staticmethod
    def parts(session_ref: str, turn_ref: str) -> tuple[str, str]:
        return session_ref, f"{turn_ref}.json"

    def exists(self, session_ref: str, turn_ref: str) -> bool:
        return self.artifacts.regular_file_exists(*self.parts(session_ref, turn_ref))

    def create(self, ledger: UsageObservationLedger) -> UsageObservationLedger:
        self._validate(ledger)
        with self.artifacts.transaction():
            try:
                _, created = self.artifacts.create_immutable_json_with_status(
                    ledger.to_dict(),
                    *self.parts(ledger.plan.session_ref, ledger.plan.turn_ref),
                )
            except ArtifactConflict:
                return self._load_unlocked(
                    ledger.plan.session_ref, ledger.plan.turn_ref
                )
            if created:
                return ledger
            return self._load_unlocked(ledger.plan.session_ref, ledger.plan.turn_ref)

    def load(self, session_ref: str, turn_ref: str) -> UsageObservationLedger:
        with self.artifacts.transaction():
            return self._load_unlocked(session_ref, turn_ref)

    def _load_unlocked(
        self, session_ref: str, turn_ref: str
    ) -> UsageObservationLedger:
        payload, _raw = self.artifacts.read_json_limited(
            MAX_OBSERVATION_LEDGER_BYTES,
            *self.parts(session_ref, turn_ref),
        )
        ledger = usage_observation_ledger_from_dict(payload)
        self._validate(ledger)
        return ledger

    def save(
        self, ledger: UsageObservationLedger, *, expected_revision: int
    ) -> UsageObservationLedger:
        self._validate(ledger)
        with self.artifacts.transaction():
            self.artifacts.replace_json_cas(
                ledger.to_dict(),
                *self.parts(ledger.plan.session_ref, ledger.plan.turn_ref),
                expected_revision=expected_revision,
            )
        return ledger

    def delete(self, session_ref: str, turn_ref: str) -> bool:
        with self.artifacts.transaction():
            deleted = self.artifacts.delete_regular_file(
                *self.parts(session_ref, turn_ref)
            )
            if deleted:
                self.artifacts.remove_empty_directory(session_ref)
            return deleted

    def finalize_snapshot(self, snapshot: UsageObservationLedger) -> str:
        session_ref = snapshot.plan.session_ref
        turn_ref = snapshot.plan.turn_ref
        parts = self.parts(session_ref, turn_ref)
        with self.artifacts.transaction():
            try:
                current = self._load_unlocked(session_ref, turn_ref)
            except FileNotFoundError:
                return "missing"
            if current.plan.observation_id != snapshot.plan.observation_id:
                return "advanced"
            if current.revision == snapshot.revision:
                deleted = self.artifacts.delete_regular_file(*parts)
                if deleted:
                    self.artifacts.remove_empty_directory(session_ref)
                    return "deleted"
                return "missing"
            if current.revision < snapshot.revision:
                return "stale"

            snapshot_completed = set(snapshot.completed_tool_use_ids)
            rebased = UsageObservationLedger(
                plan=replace(
                    current.plan,
                    observation_id=hashed_ref(
                        "observation-",
                        (
                            f"{current.plan.observation_id}\0"
                            f"{snapshot.revision}\0{current.revision}"
                        ),
                        24,
                    ),
                ),
                tool_calls=current.tool_calls - snapshot.tool_calls,
                shell_calls=current.shell_calls - snapshot.shell_calls,
                index_queries=current.index_queries - snapshot.index_queries,
                output_bytes=current.output_bytes - snapshot.output_bytes,
                tool_use_signatures={
                    key: value
                    for key, value in current.tool_use_signatures.items()
                    if snapshot.tool_use_signatures.get(key) != value
                },
                completed_tool_use_ids=[
                    key
                    for key in current.completed_tool_use_ids
                    if key not in snapshot_completed
                ],
                signals=[
                    signal
                    for signal, count in current.signal_counts.items()
                    if count - snapshot.signal_counts.get(signal, 0) > 0
                ],
                signal_counts={
                    signal: count - snapshot.signal_counts.get(signal, 0)
                    for signal, count in current.signal_counts.items()
                    if count - snapshot.signal_counts.get(signal, 0) > 0
                },
                revision=0,
            )
            self._validate(rebased)
            self.artifacts.replace_json_cas(
                rebased.to_dict(),
                *parts,
                expected_revision=current.revision,
            )
            return "rebased"

    def prune_stale(self, *, now: float | None = None) -> int:
        with self.artifacts.transaction():
            root = self.artifacts.path()
            try:
                root_fd = self.artifacts._open_directory_fd(root)
            except (FileNotFoundError, ValidationFailure):
                return 0
            cutoff = (time.time() if now is None else now) - STALE_LEDGER_TTL_SECONDS
            removed = 0
            scanned = 0
            scanned_directories = 0
            directory_flags = artifact_fs.O_RDONLY
            if hasattr(artifact_fs, "O_DIRECTORY"):
                directory_flags |= artifact_fs.O_DIRECTORY
            if hasattr(artifact_fs, "O_NOFOLLOW"):
                directory_flags |= artifact_fs.O_NOFOLLOW
            try:
                with artifact_fs.scandir(root_fd) as sessions:
                    for session_entry in sessions:
                        session_name = session_entry.name
                        if not _SESSION_REF.fullmatch(session_name):
                            continue
                        if scanned_directories >= MAX_STALE_LEDGER_SCAN_DIRECTORIES:
                            break
                        scanned_directories += 1
                        try:
                            session_fd = artifact_fs.open(
                                session_name,
                                directory_flags,
                                dir_fd=root_fd,
                            )
                        except OSError:
                            continue
                        try:
                            if not stat.S_ISDIR(artifact_fs.fstat(session_fd).st_mode):
                                continue
                            with artifact_fs.scandir(session_fd) as turns:
                                for turn_entry in turns:
                                    if scanned >= MAX_STALE_LEDGER_SCAN_FILES:
                                        break
                                    turn_name = turn_entry.name
                                    if not _TURN_FILE.fullmatch(turn_name):
                                        continue
                                    scanned += 1
                                    try:
                                        metadata = artifact_fs.stat(
                                            turn_name,
                                            dir_fd=session_fd,
                                            follow_symlinks=False,
                                        )
                                    except OSError:
                                        continue
                                    if (
                                        stat.S_ISREG(metadata.st_mode)
                                        and metadata.st_mtime < cutoff
                                    ):
                                        removed += int(
                                            self.artifacts.delete_regular_file_if_unchanged(
                                                session_name,
                                                turn_name,
                                                expected_metadata=metadata,
                                                older_than=cutoff,
                                            )
                                        )
                        finally:
                            artifact_fs.close(session_fd)
                        self.artifacts.remove_empty_directory(session_name)
                        if scanned >= MAX_STALE_LEDGER_SCAN_FILES:
                            break
            finally:
                artifact_fs.close(root_fd)
            return removed

    def _validate(self, ledger: UsageObservationLedger) -> None:
        validate_instance(
            ledger.plan.to_dict(), self.plan_schema, "usage-observation-plan"
        )
        validate_instance(
            ledger.to_dict(), self.ledger_schema, "usage-observation-ledger"
        )
        if ledger.shell_calls > ledger.tool_calls:
            raise ValidationFailure("shell observation count exceeds tool calls")
        if ledger.index_queries > ledger.tool_calls:
            raise ValidationFailure("index observation count exceeds tool calls")
        if len(ledger.tool_use_signatures) > MAX_RETAINED_TOOL_EVENTS:
            raise ValidationFailure("too many retained tool signatures")
        if len(ledger.completed_tool_use_ids) > MAX_RETAINED_TOOL_EVENTS:
            raise ValidationFailure("too many retained completed tool ids")
        if set(ledger.signal_counts) != set(ledger.signals):
            raise ValidationFailure("usage observation signal counts do not match signals")
        if len(ledger.tool_use_signatures) > ledger.tool_calls:
            raise ValidationFailure("retained tool signatures exceed tool calls")


class UsageObservationController:
    """Collects metrics and signals without making tool permission decisions."""

    def __init__(
        self,
        schema_root: Path | str,
        *,
        coverage: tuple[str, ...] = ("mcp",),
    ) -> None:
        self.schema_root = Path(schema_root).resolve()
        self.coverage = list(coverage)

    def handle(
        self,
        payload: Mapping[str, object],
        environment: Mapping[str, str],
    ) -> dict:
        event_name = payload.get("hook_event_name")
        if event_name == "UserPromptSubmit":
            return self._on_prompt(payload, environment)
        if event_name == "PreToolUse":
            return self._before_tool(payload, environment)
        if event_name == "PostToolUse":
            return self._after_tool(payload)
        return {}

    def is_active(self, payload: Mapping[str, object]) -> bool:
        session_ref, turn_ref, store = self._context(payload)
        return store.exists(session_ref, turn_ref)

    def current_ledger(self, payload: Mapping[str, object]) -> UsageObservationLedger:
        session_ref, turn_ref, store = self._context(payload)
        return store.load(session_ref, turn_ref)

    def discard_ledger(self, payload: Mapping[str, object]) -> bool:
        session_ref, turn_ref, store = self._context(payload)
        return store.delete(session_ref, turn_ref)

    def finalize_ledger(
        self,
        payload: Mapping[str, object],
        snapshot: UsageObservationLedger,
    ) -> str:
        session_ref, turn_ref, store = self._context(payload)
        if (
            session_ref != snapshot.plan.session_ref
            or turn_ref != snapshot.plan.turn_ref
        ):
            raise ValidationFailure("usage observation snapshot context changed")
        return store.finalize_snapshot(snapshot)

    @staticmethod
    def is_explicit_plugin_request(prompt: str) -> bool:
        return is_explicit_plugin_request(prompt)

    @staticmethod
    def is_plugin_tool(tool_name: str) -> bool:
        return is_plugin_tool(tool_name)

    def _on_prompt(
        self,
        payload: Mapping[str, object],
        environment: Mapping[str, str],
    ) -> dict:
        prompt = self._required_string(payload, "prompt")
        session_ref, turn_ref, store = self._context(payload)
        if self.is_explicit_plugin_request(prompt):
            source = "explicit_prompt"
        else:
            return {}
        self._activate(payload, environment, prompt, source)
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    "工程助手本轮使用采集已启用：只采集工具计数、输出规模和重复调用等信号，"
                    "不会拒绝、阻断或缩减任务执行。"
                ),
            }
        }

    def _before_tool(
        self,
        payload: Mapping[str, object],
        environment: Mapping[str, str],
    ) -> dict:
        tool_name = self._required_string(payload, "tool_name")
        if is_observation_exempt_tool(tool_name):
            return {}
        session_ref, turn_ref, store = self._context(payload)
        if not store.exists(session_ref, turn_ref):
            if not self.is_plugin_tool(tool_name):
                return {}
            canonical = json.dumps(
                payload.get("tool_input"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            self._activate(payload, environment, canonical, "plugin_tool")

        tool_use_id = self._required_string(payload, "tool_use_id")
        tool_key = hashed_ref("tool-", tool_use_id, 16)
        signature = self._signature(tool_name, payload.get("tool_input"))

        def mutate(ledger: UsageObservationLedger) -> UsageObservationLedger:
            existing = ledger.tool_use_signatures.get(tool_key)
            if existing is not None:
                signal = "replayed_tool_event" if existing == signature else "tool_use_id_reused"
                return self._with_signals(ledger, signal)
            is_shell = tool_name.casefold() == "bash"
            is_index = "codegraph" in tool_name.casefold()
            signatures = dict(ledger.tool_use_signatures)
            duplicate = signature in signatures.values()
            truncated = False
            if len(signatures) >= MAX_RETAINED_TOOL_EVENTS:
                signatures.pop(next(iter(signatures)))
                truncated = True
            signatures[tool_key] = signature
            updated = replace(
                ledger,
                tool_calls=ledger.tool_calls + 1,
                shell_calls=ledger.shell_calls + int(is_shell),
                index_queries=ledger.index_queries + int(is_index),
                tool_use_signatures=signatures,
                revision=ledger.revision + 1,
            )
            signals: list[str] = []
            if duplicate:
                signals.append("duplicate_call")
            if self._is_plugin_skill_self_read(tool_name, payload.get("tool_input")):
                signals.append("plugin_skill_self_read")
            if truncated:
                signals.append("retention_truncated")
            if updated.tool_calls > updated.plan.reference_tool_calls:
                signals.append("tool_call_reference_exceeded")
            if updated.shell_calls > updated.plan.reference_shell_calls:
                signals.append("shell_call_reference_exceeded")
            if updated.index_queries > updated.plan.reference_index_queries:
                signals.append("index_query_reference_exceeded")
            return self._with_signals(updated, *signals, increment_revision=False)

        self._mutate(store, session_ref, turn_ref, mutate)
        return {}

    def _after_tool(self, payload: Mapping[str, object]) -> dict:
        tool_name = self._required_string(payload, "tool_name")
        if is_observation_exempt_tool(tool_name):
            return {}
        session_ref, turn_ref, store = self._context(payload)
        if not store.exists(session_ref, turn_ref):
            return {}
        tool_use_id = self._required_string(payload, "tool_use_id")
        tool_key = hashed_ref("tool-", tool_use_id, 16)
        response_bytes = len(
            json.dumps(
                payload.get("tool_response"), ensure_ascii=False, sort_keys=True
            ).encode("utf-8")
        )

        def mutate(ledger: UsageObservationLedger) -> UsageObservationLedger:
            if tool_key in ledger.completed_tool_use_ids:
                return ledger
            completed = list(ledger.completed_tool_use_ids)
            truncated = False
            if len(completed) >= MAX_RETAINED_TOOL_EVENTS:
                completed.pop(0)
                truncated = True
            completed.append(tool_key)
            updated = replace(
                ledger,
                output_bytes=ledger.output_bytes + response_bytes,
                completed_tool_use_ids=completed,
                revision=ledger.revision + 1,
            )
            signals: list[str] = []
            if response_bytes > LARGE_SINGLE_OUTPUT_BYTES:
                signals.append("large_single_output")
            if truncated:
                signals.append("retention_truncated")
            if (
                tool_key not in ledger.tool_use_signatures
                and "retention_truncated" not in ledger.signals
            ):
                signals.append("post_without_pre")
            if updated.output_bytes > updated.plan.reference_output_bytes:
                signals.append("output_reference_exceeded")
            return self._with_signals(updated, *signals, increment_revision=False)

        self._mutate(store, session_ref, turn_ref, mutate)
        return {}

    @staticmethod
    def _is_plugin_skill_self_read(tool_name: str, tool_input: object) -> bool:
        if tool_name.casefold() != "bash" or not isinstance(tool_input, Mapping):
            return False
        command = tool_input.get("command")
        if not isinstance(command, str):
            return False
        normalized = command.casefold().replace("\\", "/")
        wrapped = _SHELL_WRAPPER.match(normalized.strip())
        candidate = wrapped.group(2).strip() if wrapped is not None else normalized
        return (
            _FILE_READER_COMMAND.search(candidate) is not None
            and "engineering-assistant/" in normalized
            and "/skills/" in normalized
            and "/skill.md" in normalized
        )

    def _activate(
        self,
        payload: Mapping[str, object],
        environment: Mapping[str, str],
        task_material: str,
        source: str,
    ) -> UsageObservationLedger:
        session_ref, turn_ref, store = self._context(payload)
        try:
            store.prune_stale()
        except Exception:
            pass
        digest = hashlib.sha256(task_material.encode("utf-8")).hexdigest()
        plan = UsageObservationPlan(
            observation_id=hashed_ref(
                "observation-", f"{session_ref}\0{turn_ref}\0{digest}", 24
            ),
            session_ref=session_ref,
            turn_ref=turn_ref,
            task_digest=f"sha256:{digest}",
            activation_source=source,
            reference_tool_calls=self._positive_int(
                environment,
                "ENGINEERING_ASSISTANT_OBSERVE_TOOL_CALLS",
                DEFAULT_REFERENCE_TOOL_CALLS,
            ),
            reference_shell_calls=self._nonnegative_int(
                environment,
                "ENGINEERING_ASSISTANT_OBSERVE_SHELL_CALLS",
                DEFAULT_REFERENCE_SHELL_CALLS,
            ),
            reference_index_queries=self._nonnegative_int(
                environment,
                "ENGINEERING_ASSISTANT_OBSERVE_INDEX_QUERIES",
                DEFAULT_REFERENCE_INDEX_QUERIES,
            ),
            reference_output_bytes=self._positive_int(
                environment,
                "ENGINEERING_ASSISTANT_OBSERVE_OUTPUT_BYTES",
                DEFAULT_REFERENCE_OUTPUT_BYTES,
            ),
            coverage=list(self.coverage),
        )
        ledger = store.create(
            UsageObservationLedger(
                plan=plan,
                tool_calls=0,
                shell_calls=0,
                index_queries=0,
                output_bytes=0,
                tool_use_signatures={},
                completed_tool_use_ids=[],
                signals=[],
                signal_counts={},
                revision=0,
            )
        )
        return ledger

    def _mutate(
        self,
        store: UsageObservationStore,
        session_ref: str,
        turn_ref: str,
        callback: Callable[[UsageObservationLedger], UsageObservationLedger],
    ) -> None:
        for _ in range(MAX_CAS_ATTEMPTS):
            ledger = store.load(session_ref, turn_ref)
            updated = callback(ledger)
            if updated == ledger:
                return
            try:
                store.save(updated, expected_revision=ledger.revision)
                return
            except ArtifactConflict:
                continue
        raise ValidationFailure("usage observation changed too frequently")

    @staticmethod
    def _with_signals(
        ledger: UsageObservationLedger,
        *signals: str,
        increment_revision: bool = True,
    ) -> UsageObservationLedger:
        merged = list(ledger.signals)
        counts = dict(ledger.signal_counts)
        for signal in signals:
            if not signal:
                continue
            counts[signal] = counts.get(signal, 0) + 1
            if signal not in merged:
                merged.append(signal)
        if merged == ledger.signals and counts == ledger.signal_counts:
            return ledger
        return replace(
            ledger,
            signals=merged,
            signal_counts=counts,
            revision=ledger.revision + int(increment_revision),
        )

    def _context(
        self, payload: Mapping[str, object]
    ) -> tuple[str, str, UsageObservationStore]:
        session_id = self._required_string(payload, "session_id")
        turn_id = self._required_string(payload, "turn_id")
        project_root = self._required_string(payload, "cwd")
        return (
            hashed_ref("session-", session_id, 16),
            hashed_ref("turn-", turn_id, 16),
            UsageObservationStore(project_root, self.schema_root),
        )

    @staticmethod
    def _signature(tool_name: str, tool_input: object) -> str:
        encoded = json.dumps(
            {"tool_name": tool_name, "tool_input": tool_input},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _required_string(payload: Mapping[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValidationFailure(
                f"usage observation hook field {key} must be a non-empty string"
            )
        return value

    @staticmethod
    def _positive_int(environment: Mapping[str, str], key: str, default: int) -> int:
        value = int(environment.get(key, str(default)))
        if value < 1:
            raise ValidationFailure(f"{key} must be positive")
        return value

    @staticmethod
    def _nonnegative_int(
        environment: Mapping[str, str], key: str, default: int
    ) -> int:
        value = int(environment.get(key, str(default)))
        if value < 0:
            raise ValidationFailure(f"{key} must be nonnegative")
        return value
