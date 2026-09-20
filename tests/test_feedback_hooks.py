# GPT-6 适配变更说明：团队版运行、反馈和观测使用独立目录；旧共享目录不自动迁移或合并。
from __future__ import annotations

import io
import hashlib
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.feedback import (  # noqa: E402
    FeedbackCollector,
    FeedbackStore,
    export_feedback_evolution,
    run_codex_hook,
    summarize_feedback_events,
    summarize_usage_efficiency,
)
from engineering_assistant.model import (  # noqa: E402
    FeedbackDisposition,
    FeedbackEvent,
    UsageEfficiencyFeedback,
)
from engineering_assistant.validation import (  # noqa: E402
    ValidationFailure,
    load_json,
    validate_instance,
)
from engineering_assistant.artifact_io import ArtifactConflict  # noqa: E402


class FeedbackHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.collector = FeedbackCollector(ROOT / "schemas")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def stop_payload(self, message: str, *, active: bool = False) -> dict:
        return {
            "session_id": "session-sensitive-id",
            "turn_id": "turn-1",
            "transcript_path": "/unstable/transcript.jsonl",
            "cwd": str(self.project),
            "hook_event_name": "Stop",
            "model": "gpt-test",
            "permission_mode": "default",
            "stop_hook_active": active,
            "last_assistant_message": message,
        }

    def prompt_payload(self, prompt: str) -> dict:
        return {
            "session_id": "session-sensitive-id",
            "turn_id": "turn-2",
            "transcript_path": None,
            "cwd": str(self.project),
            "hook_event_name": "UserPromptSubmit",
            "model": "gpt-test",
            "permission_mode": "default",
            "prompt": prompt,
        }

    def artifacts(self, kind: str) -> list[Path]:
        return sorted(
            (
                self.project
                / ".run-artifacts/teamwork-engineering-assistant/feedback"
                / kind
            ).glob("*.json")
        )

    def test_stop_hook_captures_blocker_once_without_requesting_continuation(self) -> None:
        payload = self.stop_payload("当前被权限问题阻断，等待人工审批后继续。")
        first = self.collector.collect_codex(payload)
        second = self.collector.collect_codex(payload)

        self.assertFalse(first.duplicate)
        self.assertTrue(second.duplicate)
        self.assertEqual(1, len(self.artifacts("captures")))
        self.assertEqual(1, len(self.artifacts("events")))
        capture = load_json(self.artifacts("captures")[0])
        event = load_json(self.artifacts("events")[0])
        validate_instance(
            capture,
            load_json(ROOT / "schemas/feedback-capture.schema.json"),
            "capture",
        )
        validate_instance(
            event,
            load_json(ROOT / "schemas/feedback-event.schema.json"),
            "event",
        )
        self.assertEqual("candidate_created", capture["status"])
        self.assertEqual("blocker", event["event_type"])
        self.assertEqual(["task-execution"], event["scope_tags"])
        self.assertEqual("resolve_blocker", event["change_kind"])
        self.assertEqual(
            "requires_user_or_external_input", event["recovery_condition"]
        )
        self.assertEqual(
            "human_approval_or_input", event["manual_intervention_kind"]
        )
        self.assertEqual([], event["affected_asset_refs"])
        self.assertNotIn("session-sensitive-id", json.dumps(capture))

    def test_normal_stop_records_metadata_without_creating_feedback_noise(self) -> None:
        result = self.collector.collect_codex(self.stop_payload("实现完成，所有验证均已通过。"))
        self.assertIsNone(result.capture)
        self.assertEqual([], self.artifacts("events"))
        self.assertEqual([], self.artifacts("captures"))

    def test_stop_feedback_uses_the_single_active_run_context(self) -> None:
        state = self.project / ".run-artifacts/teamwork-engineering-assistant/run-real/run-state.json"
        state.parent.mkdir(parents=True)
        state.write_text(
            json.dumps(
                {
                    "schema_version": "2",
                    "run_id": "run-real",
                    "task_id": "task-real",
                    "flow_id": "implement",
                    "status": "running",
                    "current_node": "red-green",
                }
            )
        )

        event = self.collector.collect_codex(
            self.stop_payload("当前被测试失败阻断，需要返工。")
        ).event

        self.assertEqual("run-real", event.run_id)
        self.assertEqual("task-real", event.task_id)
        self.assertEqual("red-green", event.node_id)
        self.assertEqual("implement", event.flow_id)

    def test_post_tool_feedback_extracts_runtime_identity_from_result(self) -> None:
        result = self.collector.collect_tool_result(
            {
                "session_id": "session-sensitive-id",
                "turn_id": "turn-runtime",
                "cwd": str(self.project),
                "tool_name": "mcp__engineering_assistant__engineering_assistant_complete",
                "tool_response": {
                    "status": "failed",
                    "state": {
                        "run_id": "run-result",
                        "task_id": "task-result",
                        "flow_id": "design",
                        "current_node": "architecture",
                    },
                },
            },
            mode="candidates",
            platform="codex",
        )

        self.assertEqual("run-result", result.event.run_id)
        self.assertEqual("task-result", result.event.task_id)
        self.assertEqual("design", result.event.flow_id)
        self.assertEqual("architecture", result.event.node_id)

    def test_continued_stop_is_loop_guarded(self) -> None:
        result = self.collector.collect_codex(
            self.stop_payload("测试失败，需要继续修复。", active=True)
        )
        self.assertEqual("skipped_continuation", result.capture.status)
        self.assertEqual([], self.artifacts("events"))

    def test_user_correction_omits_raw_content_and_is_promoted_to_feedback(self) -> None:
        secret = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
        payload = self.prompt_payload(f"刚才的实现不对，请改为复用现有接口。API_KEY={secret}")
        result = self.collector.collect_codex(payload)
        event = result.event
        self.assertIsNotNone(event)
        self.assertEqual("human_correction", event.event_type)
        self.assertEqual("human", event.source)
        self.assertEqual(["requirements"], event.scope_tags)
        self.assertEqual("correct_behavior", event.change_kind)
        self.assertEqual("apply_corrected_constraint", event.recovery_condition)
        self.assertEqual("user_correction", event.manual_intervention_kind)
        self.assertEqual([], event.affected_asset_refs)
        artifact_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [*self.artifacts("captures"), *self.artifacts("events")]
        )
        self.assertNotIn(secret, artifact_text)
        self.assertNotIn("复用现有接口", artifact_text)
        self.assertIn("raw hook content was omitted", artifact_text)

    def test_feedback_mode_can_disable_or_limit_capture(self) -> None:
        disabled = self.collector.collect_codex(
            self.stop_payload("当前阻断。"), mode="disabled"
        )
        self.assertIsNone(disabled.capture)
        self.assertEqual([], self.artifacts("captures"))

        metadata = self.collector.collect_codex(
            self.stop_payload("当前阻断。"), mode="metadata"
        )
        self.assertEqual("metadata_only", metadata.capture.status)
        self.assertEqual([], self.artifacts("events"))

    def test_efficiency_candidates_have_a_read_only_anonymous_summary(self) -> None:
        store = FeedbackStore(self.project, ROOT / "schemas")
        for index, signal in enumerate(
            ["duplicate_call", "output_reference_exceeded"], start=1
        ):
            store.save_efficiency_candidate(
                UsageEfficiencyFeedback(
                    schema_version="1.0",
                    candidate_id=f"efficiency-{index:024x}",
                    source="stop_hook",
                    status="pending",
                    tool_calls=index + 1,
                    shell_calls=index,
                    index_queries=0,
                    output_bytes=index * 100,
                    reference_tool_calls=12,
                    reference_shell_calls=6,
                    reference_index_queries=1,
                    reference_output_bytes=64_000,
                    signals=[signal],
                    coverage=["bash", "mcp"],
                    ledger_revision=index,
                    reusable_candidate=False,
                )
            )

        summary = summarize_usage_efficiency(self.project, ROOT / "schemas")

        self.assertEqual(2, summary["candidate_count"])
        self.assertEqual(0, summary["skipped_invalid_count"])
        self.assertEqual(5, summary["totals"]["tool_calls"])
        self.assertEqual(300, summary["totals"]["output_bytes"])
        self.assertEqual(1, summary["signal_counts"]["duplicate_call"])
        self.assertEqual(
            1, summary["signal_counts"]["output_reference_exceeded"]
        )
        self.assertEqual(["bash", "mcp"], summary["coverage"])
        serialized = json.dumps(summary)
        self.assertNotIn("candidate_id", serialized)
        self.assertNotIn("session", serialized)
        self.assertNotIn("turn", serialized)

    def test_efficiency_summary_streams_past_invalid_candidates_without_leaking(
        self,
    ) -> None:
        directory = (
            self.project
            / ".run-artifacts/teamwork-engineering-assistant/feedback/efficiency-candidates"
        )
        directory.mkdir(parents=True)
        secret = "private-invalid-candidate-value"
        (directory / "efficiency-000000000000000000000001.json").write_text(
            json.dumps({"unexpected": secret}),
            encoding="utf-8",
        )

        summary = summarize_usage_efficiency(self.project, ROOT / "schemas")

        self.assertEqual(0, summary["candidate_count"])
        self.assertEqual(1, summary["skipped_invalid_count"])
        self.assertNotIn(secret, json.dumps(summary))

    def test_feedback_summaries_stream_directories_without_listdir(self) -> None:
        self.collector.collect_codex(self.stop_payload("当前阻断。"))
        with patch(
            "engineering_assistant.feedback.os.listdir",
            side_effect=AssertionError("summary must stream directory entries"),
        ):
            efficiency = summarize_usage_efficiency(self.project, ROOT / "schemas")
            events = summarize_feedback_events(self.project, ROOT / "schemas")

        self.assertEqual(1, events["event_count"])
        self.assertEqual(0, efficiency["candidate_count"])

    def test_feedback_summary_bounds_distinct_recurrence_keys(self) -> None:
        from engineering_assistant.feedback import MAX_SUMMARY_RECURRENCE_KEYS

        events = []
        for index in range(MAX_SUMMARY_RECURRENCE_KEYS + 3):
            events.append(
                {
                    "event_id": f"feedback-{index}",
                    "event_type": "rework",
                    "severity": "medium",
                    "recurrence_key": f"key-{index}",
                    "resolution": "open",
                    "observed_at": "2026-07-14T08:00:00+00:00",
                }
            )
        with patch(
            "engineering_assistant.feedback.FeedbackStore.iter_feedback_events",
            return_value=iter(events),
        ), patch(
            "engineering_assistant.feedback.ArtifactIO.read_json_limited",
            side_effect=FileNotFoundError,
        ):
            summary = summarize_feedback_events(
                self.project,
                ROOT / "schemas",
                item_limit=0,
            )

        self.assertLessEqual(
            len(summary["recurrence_counts"]),
            MAX_SUMMARY_RECURRENCE_KEYS,
        )
        self.assertEqual(3, summary["recurrence_overflow_event_count"])

    def test_feedback_events_can_be_summarized_and_auditably_dispositioned(self) -> None:
        event = self.collector.collect_codex(
            self.stop_payload("当前被权限问题阻断，等待人工审批后继续。")
        ).event
        self.assertIsNotNone(event)
        store = FeedbackStore(self.project, ROOT / "schemas")
        store.save_disposition(
            FeedbackDisposition(
                schema_version="1.0",
                disposition_id="feedback-disposition-" + "a" * 24,
                event_id=event.event_id,
                decision="accepted_for_evolution",
                reason="应增加权限前置检查。",
                actor_ref="reviewer-opaque-ref",
                evidence_refs=[],
                reusable_candidate=True,
                decided_at="2026-07-14T08:00:00+00:00",
            )
        )

        summary = summarize_feedback_events(
            self.project,
            ROOT / "schemas",
            item_limit=10,
        )

        self.assertEqual(1, summary["event_count"])
        self.assertEqual(1, summary["decision_counts"]["accepted_for_evolution"])
        self.assertEqual(1, summary["reusable_candidate_count"])
        self.assertEqual("accepted_for_evolution", summary["recent_items"][0]["decision"])
        serialized = json.dumps(summary, ensure_ascii=False)
        self.assertNotIn("session-sensitive-id", serialized)
        self.assertNotIn("应增加权限前置检查", serialized)

    def test_accepted_feedback_exports_a_read_only_privacy_safe_evolution_proposal(self) -> None:
        event = self.collector.collect_codex(
            self.stop_payload("当前被权限问题阻断，等待人工审批后继续。")
        ).event
        self.assertIsNotNone(event)
        disposition = FeedbackDisposition(
            schema_version="1.0",
            disposition_id="feedback-disposition-" + "7" * 24,
            event_id=event.event_id,
            decision="accepted_for_evolution",
            reason="敏感处置原因不得进入导出。",
            actor_ref="reviewer-sensitive-ref",
            evidence_refs=["evidence:review-1"],
            reusable_candidate=True,
            decided_at="2026-07-14T08:00:00+00:00",
        )
        FeedbackStore(self.project, ROOT / "schemas").save_disposition(disposition)

        exported = export_feedback_evolution(
            self.project,
            ROOT / "schemas",
            limit=10,
        )

        self.assertEqual(1, exported["proposal_count"])
        self.assertIsNone(exported["next_after_event_ref"])
        proposal = exported["proposals"][0]
        self.assertRegex(proposal["event_ref"], r"^feedback-event-sha256:[0-9a-f]{64}$")
        self.assertEqual(disposition.disposition_id, proposal["disposition_id"])
        self.assertEqual("accepted_for_evolution", proposal["decision"])
        self.assertEqual(["feedback", "state_machine"], proposal["suggested_regression_scopes"])
        self.assertTrue(proposal["requires_review"])
        self.assertFalse(proposal["formal_assets_modified"])
        validate_instance(
            exported,
            load_json(ROOT / "schemas/feedback-evolution-export.schema.json"),
            "feedback-evolution-export",
        )
        serialized = json.dumps(exported, ensure_ascii=False)
        self.assertNotIn("敏感处置原因", serialized)
        self.assertNotIn("reviewer-sensitive-ref", serialized)
        self.assertNotIn("等待人工审批", serialized)
        self.assertNotIn(event.event_id, serialized)

        rejected = FeedbackDisposition(
            schema_version="1.0",
            disposition_id="feedback-disposition-" + "8" * 24,
            event_id=event.event_id,
            decision="rejected",
            reason="later review",
            actor_ref="reviewer",
            evidence_refs=[],
            reusable_candidate=False,
            decided_at="2026-07-14T09:00:00+00:00",
        )
        FeedbackStore(self.project, ROOT / "schemas").save_disposition(rejected)
        self.assertEqual(
            0,
            export_feedback_evolution(self.project, ROOT / "schemas")["proposal_count"],
        )

    def test_evolution_export_hashes_restricted_event_references(self) -> None:
        event = FeedbackEvent(
            event_id="customer-acme-sensitive-event",
            run_id="run-sensitive",
            task_id="task-sensitive",
            node_id="quality",
            turn_id=None,
            event_type="quality_regression",
            severity="high",
            source="human",
            symptom="sensitive symptom",
            expected_behavior="repair",
            observed_behavior="regressed",
            human_action=None,
            evidence_refs=["s3://sensitive-bucket/customer/acme"],
            recurrence_key="customer-acme-secret",
            resolution="open",
            reusable_candidate=False,
            sensitivity="restricted",
            observed_at="2026-07-14T07:00:00+00:00",
            scope_tags=["quality"],
            change_kind="repair_failure",
            affected_asset_refs=["/private/customer/acme/secret.txt"],
            recovery_condition="repair_and_revalidate",
            manual_intervention_kind="none",
        )
        store = FeedbackStore(self.project, ROOT / "schemas")
        store.save_event(event)
        store.save_disposition(
            FeedbackDisposition(
                schema_version="1.0",
                disposition_id="feedback-disposition-" + "9" * 24,
                event_id=event.event_id,
                decision="accepted_for_evolution",
                reason="accepted",
                actor_ref="reviewer",
                evidence_refs=[],
                reusable_candidate=True,
                decided_at="2026-07-14T08:00:00+00:00",
            )
        )

        exported = export_feedback_evolution(self.project, ROOT / "schemas")
        serialized = json.dumps(exported, ensure_ascii=False)

        self.assertNotIn("customer-acme-sensitive-event", serialized)
        self.assertNotIn("sensitive-bucket", serialized)
        self.assertNotIn("/private/customer", serialized)
        self.assertNotIn("customer-acme-secret", serialized)
        proposal = exported["proposals"][0]
        self.assertRegex(proposal["event_ref"], r"^feedback-event-sha256:[0-9a-f]{64}$")
        self.assertEqual(1, len(proposal["evidence_ref_digests"]))
        self.assertEqual(1, len(proposal["affected_asset_ref_digests"]))
        self.assertRegex(
            proposal["recurrence_key_digest"],
            r"^recurrence-key-sha256:[0-9a-f]{64}$",
        )

    def test_evolution_pagination_rejects_a_changed_disposition_snapshot(self) -> None:
        store = FeedbackStore(self.project, ROOT / "schemas")

        def accept(identifier: str) -> None:
            event = FeedbackEvent(
                event_id=identifier,
                run_id="run-pagination",
                task_id="task-pagination",
                node_id="quality",
                turn_id=None,
                event_type="rework",
                severity="medium",
                source="runtime",
                symptom="rework required",
                expected_behavior="repair",
                observed_behavior="rework",
                human_action=None,
                evidence_refs=[],
                recurrence_key="rework-required",
                resolution="open",
                reusable_candidate=False,
                sensitivity="internal",
                observed_at="2026-07-14T07:00:00+00:00",
                scope_tags=["quality"],
                change_kind="rework_output",
                affected_asset_refs=[],
                recovery_condition="repair_and_revalidate",
                manual_intervention_kind="none",
            )
            store.save_event(event)
            store.save_disposition(
                FeedbackDisposition(
                    schema_version="1.0",
                    disposition_id="feedback-disposition-"
                    + hashlib.sha256(identifier.encode()).hexdigest()[:24],
                    event_id=identifier,
                    decision="accepted_for_evolution",
                    reason="accepted",
                    actor_ref="reviewer",
                    evidence_refs=[],
                    reusable_candidate=True,
                    decided_at="2026-07-14T08:00:00+00:00",
                )
            )

        accept("event-page-a")
        accept("event-page-b")
        first = export_feedback_evolution(self.project, ROOT / "schemas", limit=1)
        self.assertIsNotNone(first["next_after_event_ref"])
        accept("event-page-c")

        with self.assertRaisesRegex(ValidationFailure, "snapshot changed"):
            export_feedback_evolution(
                self.project,
                ROOT / "schemas",
                limit=1,
                after_event_ref=first["next_after_event_ref"],
                snapshot_revision=first["snapshot_revision"],
            )

    def test_evolution_scan_does_not_hold_the_disposition_write_lock(self) -> None:
        event = self.collector.collect_codex(
            self.stop_payload("当前被权限问题阻断，等待人工审批后继续。")
        ).event
        store = FeedbackStore(self.project, ROOT / "schemas")
        store.save_disposition(
            FeedbackDisposition(
                schema_version="1.0",
                disposition_id="feedback-disposition-" + "a" * 24,
                event_id=event.event_id,
                decision="accepted_for_evolution",
                reason="accepted",
                actor_ref="reviewer",
                evidence_refs=[],
                reusable_candidate=True,
                decided_at="2026-07-14T08:00:00+00:00",
            )
        )
        scan_started = threading.Event()
        allow_scan = threading.Event()
        original_iter = FeedbackStore.iter_feedback_events

        def slow_iter(instance: FeedbackStore):
            for item in original_iter(instance):
                scan_started.set()
                self.assertTrue(allow_scan.wait(1))
                yield item

        outcome: list[BaseException | dict] = []

        def export() -> None:
            try:
                outcome.append(
                    export_feedback_evolution(self.project, ROOT / "schemas")
                )
            except BaseException as exc:
                outcome.append(exc)

        with patch.object(FeedbackStore, "iter_feedback_events", slow_iter):
            worker = threading.Thread(target=export)
            worker.start()
            self.assertTrue(scan_started.wait(1))
            self.assertTrue(
                store.save_disposition(
                    FeedbackDisposition(
                        schema_version="1.0",
                        disposition_id="feedback-disposition-" + "b" * 24,
                        event_id=event.event_id,
                        decision="rejected",
                        reason="rejected during scan",
                        actor_ref="reviewer",
                        evidence_refs=[],
                        reusable_candidate=False,
                        decided_at="2026-07-14T09:00:00+00:00",
                    )
                )
            )
            allow_scan.set()
            worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(1, len(outcome))
        self.assertIsInstance(outcome[0], ValidationFailure)
        self.assertIn("snapshot changed", str(outcome[0]))

    def test_legacy_feedback_event_can_be_summarized_and_dispositioned(self) -> None:
        legacy = {
            "event_id": "feedback-legacy",
            "run_id": "run-legacy",
            "task_id": "task-legacy",
            "node_id": None,
            "turn_id": None,
            "event_type": "rework",
            "severity": "medium",
            "source": "runtime",
            "symptom": "legacy",
            "expected_behavior": "repair",
            "observed_behavior": "rework",
            "human_action": None,
            "evidence_refs": [],
            "recurrence_key": "legacy-rework",
            "resolution": "open",
            "reusable_candidate": False,
            "sensitivity": "internal",
            "observed_at": "2026-07-14T07:00:00+00:00",
        }
        events = self.project / ".run-artifacts/teamwork-engineering-assistant/feedback/events"
        events.mkdir(parents=True)
        (events / "feedback-legacy.json").write_text(json.dumps(legacy), encoding="utf-8")
        disposition = FeedbackDisposition(
            schema_version="1.0",
            disposition_id="feedback-disposition-" + "b" * 24,
            event_id="feedback-legacy",
            decision="resolved",
            reason="legacy handled",
            actor_ref="reviewer",
            evidence_refs=[],
            reusable_candidate=False,
            decided_at="2026-07-14T08:00:00+00:00",
        )
        self.assertTrue(FeedbackStore(self.project, ROOT / "schemas").save_disposition(disposition))

        summary = summarize_feedback_events(self.project, ROOT / "schemas")

        self.assertEqual(1, summary["event_count"])
        self.assertEqual("unknown", summary["recent_items"][0]["change_kind"])
        self.assertEqual("resolved", summary["recent_items"][0]["decision"])

    def test_disposition_rejects_conflicts_invalid_reuse_and_oversize(self) -> None:
        event = self.collector.collect_codex(self.stop_payload("当前阻断。")).event
        store = FeedbackStore(self.project, ROOT / "schemas")
        base = dict(
            schema_version="1.0",
            disposition_id="feedback-disposition-" + "c" * 24,
            event_id=event.event_id,
            decision="rejected",
            reason="not reusable",
            actor_ref="reviewer",
            evidence_refs=[],
            reusable_candidate=False,
            decided_at="2026-07-14T08:00:00+00:00",
        )
        self.assertTrue(store.save_disposition(FeedbackDisposition(**base)))
        self.assertFalse(store.save_disposition(FeedbackDisposition(**base)))
        with self.assertRaises(ArtifactConflict):
            store.save_disposition(
                FeedbackDisposition(**{**base, "decision": "deferred"})
            )
        with self.assertRaisesRegex(ValidationFailure, "reusable"):
            store.save_disposition(
                FeedbackDisposition(
                    **{
                        **base,
                        "disposition_id": "feedback-disposition-" + "d" * 24,
                        "reusable_candidate": True,
                    }
                )
            )
        with self.assertRaisesRegex(ValidationFailure, "too large"):
            store.save_disposition(
                FeedbackDisposition(
                    **{
                        **base,
                        "disposition_id": "feedback-disposition-" + "e" * 24,
                        "decision": "accepted_for_evolution",
                        "reason": "x" * 70_000,
                        "reusable_candidate": True,
                    }
                )
            )

    def test_feedback_size_limit_matches_the_exact_bytes_written(self) -> None:
        event = self.collector.collect_codex(self.stop_payload("当前阻断。")).event
        payload = event.to_dict()
        payload["evidence_refs"] = [
            f"{index:02d}-" + "x" * 2007 for index in range(32)
        ]
        compact_size = len(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        written_size = len(
            (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
                "utf-8"
            )
        )
        self.assertLessEqual(compact_size, 65_536)
        self.assertGreater(written_size, 65_536)

        with self.assertRaisesRegex(ValidationFailure, "too large"):
            FeedbackStore(self.project, ROOT / "schemas").save_event(
                FeedbackEvent(**payload)
            )

    def test_disposition_replay_never_rewinds_current_state(self) -> None:
        event = self.collector.collect_codex(self.stop_payload("当前阻断。")).event
        store = FeedbackStore(self.project, ROOT / "schemas")
        first = FeedbackDisposition(
            schema_version="1.0",
            disposition_id="feedback-disposition-" + "1" * 24,
            event_id=event.event_id,
            decision="rejected",
            reason="first decision",
            actor_ref="reviewer",
            evidence_refs=[],
            reusable_candidate=False,
            decided_at="2026-07-14T08:00:00+00:00",
        )
        later = FeedbackDisposition(
            schema_version="1.0",
            disposition_id="feedback-disposition-" + "2" * 24,
            event_id=event.event_id,
            decision="accepted_for_evolution",
            reason="later decision",
            actor_ref="reviewer",
            evidence_refs=[],
            reusable_candidate=True,
            decided_at="2026-07-14T09:00:00+00:00",
        )

        self.assertTrue(store.save_disposition(first))
        self.assertTrue(store.save_disposition(later))
        self.assertFalse(store.save_disposition(first))

        summary = summarize_feedback_events(self.project, ROOT / "schemas")
        self.assertEqual("accepted_for_evolution", summary["recent_items"][0]["decision"])

    def test_disposition_state_uses_stable_total_order(self) -> None:
        event = self.collector.collect_codex(self.stop_payload("当前阻断。")).event
        store = FeedbackStore(self.project, ROOT / "schemas")

        def disposition(identifier: str, decision: str, decided_at: str) -> FeedbackDisposition:
            return FeedbackDisposition(
                schema_version="1.0",
                disposition_id="feedback-disposition-" + identifier * 24,
                event_id=event.event_id,
                decision=decision,
                reason=f"{decision} decision",
                actor_ref="reviewer",
                evidence_refs=[],
                reusable_candidate=decision == "accepted_for_evolution",
                decided_at=decided_at,
            )

        newest = disposition("c", "accepted_for_evolution", "2026-07-14T09:00:00+00:00")
        same_time_lower_id = disposition("b", "resolved", "2026-07-14T09:00:00+00:00")
        older = disposition("d", "rejected", "2026-07-14T08:00:00+00:00")

        self.assertTrue(store.save_disposition(newest))
        self.assertTrue(store.save_disposition(same_time_lower_id))
        self.assertTrue(store.save_disposition(older))
        self.assertFalse(store.save_disposition(older))

        summary = summarize_feedback_events(self.project, ROOT / "schemas")
        self.assertEqual("accepted_for_evolution", summary["recent_items"][0]["decision"])

    def test_disposition_retry_repairs_state_after_initial_state_write_failure(
        self,
    ) -> None:
        event = self.collector.collect_codex(self.stop_payload("当前阻断。")).event
        store = FeedbackStore(self.project, ROOT / "schemas")
        disposition = FeedbackDisposition(
            schema_version="1.0",
            disposition_id="feedback-disposition-" + "4" * 24,
            event_id=event.event_id,
            decision="accepted_for_evolution",
            reason="recover state",
            actor_ref="reviewer",
            evidence_refs=[],
            reusable_candidate=True,
            decided_at="2026-07-14T09:00:00+00:00",
        )
        original_create = store.artifacts.create_immutable_json

        def fail_state_once(payload: dict, *parts: str):
            if parts and parts[0] == "disposition-state":
                raise OSError("injected state write failure")
            return original_create(payload, *parts)

        with patch.object(
            store.artifacts,
            "create_immutable_json",
            side_effect=fail_state_once,
        ):
            with self.assertRaises(OSError):
                store.save_disposition(disposition)

        self.assertFalse(store.save_disposition(disposition))
        summary = summarize_feedback_events(self.project, ROOT / "schemas")
        self.assertEqual("accepted_for_evolution", summary["recent_items"][0]["decision"])

    def test_disposition_retry_repairs_state_after_cas_failure(self) -> None:
        event = self.collector.collect_codex(self.stop_payload("当前阻断。")).event
        store = FeedbackStore(self.project, ROOT / "schemas")
        first = FeedbackDisposition(
            schema_version="1.0",
            disposition_id="feedback-disposition-" + "5" * 24,
            event_id=event.event_id,
            decision="rejected",
            reason="initial decision",
            actor_ref="reviewer",
            evidence_refs=[],
            reusable_candidate=False,
            decided_at="2026-07-14T08:00:00+00:00",
        )
        later = FeedbackDisposition(
            schema_version="1.0",
            disposition_id="feedback-disposition-" + "6" * 24,
            event_id=event.event_id,
            decision="accepted_for_evolution",
            reason="updated decision",
            actor_ref="reviewer",
            evidence_refs=[],
            reusable_candidate=True,
            decided_at="2026-07-14T09:00:00+00:00",
        )
        self.assertTrue(store.save_disposition(first))

        with patch.object(
            store.artifacts,
            "replace_json_cas",
            side_effect=OSError("injected state update failure"),
        ):
            with self.assertRaises(OSError):
                store.save_disposition(later)

        self.assertFalse(store.save_disposition(later))
        summary = summarize_feedback_events(self.project, ROOT / "schemas")
        self.assertEqual("accepted_for_evolution", summary["recent_items"][0]["decision"])

    def test_codex_hook_always_returns_nonblocking_json_even_on_invalid_input(self) -> None:
        output = io.StringIO()
        code = run_codex_hook(
            input_stream=io.StringIO(json.dumps(self.stop_payload("当前阻断。"))),
            output_stream=output,
            schema_root=ROOT / "schemas",
            environment={"ENGINEERING_ASSISTANT_FEEDBACK_MODE": "candidates"},
        )
        self.assertEqual(0, code)
        self.assertEqual({}, json.loads(output.getvalue()))

        invalid_output = io.StringIO()
        code = run_codex_hook(
            input_stream=io.StringIO("{}"),
            output_stream=invalid_output,
            schema_root=ROOT / "schemas",
            environment={},
        )
        self.assertEqual(0, code)
        self.assertEqual({}, json.loads(invalid_output.getvalue()))

    def test_hermes_turn_uses_same_collector_for_prompt_and_response(self) -> None:
        results = self.collector.collect_hermes_turn(
            project_root=self.project,
            session_id="hermes-session",
            turn_id="hermes-turn",
            user_message="补充一个要求：不要增加新依赖。",
            assistant_response="当前被构建错误阻断。",
            model="test-model",
            platform="cli",
        )
        self.assertEqual(2, len(results))
        self.assertEqual(2, len(self.artifacts("events")))
        self.assertEqual(
            {"scope_change", "blocker"},
            {load_json(path)["event_type"] for path in self.artifacts("events")},
        )

    def test_feedback_store_rejects_run_artifact_symlink_escape(self) -> None:
        outside = self.project.parent / f"{self.project.name}-outside"
        outside.mkdir()
        try:
            (self.project / ".run-artifacts").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink|escapes"):
                FeedbackStore(self.project, ROOT / "schemas")
        finally:
            for child in outside.iterdir():
                child.unlink()
            outside.rmdir()

    def test_feedback_store_rejects_nested_event_symlink_escape(self) -> None:
        outside = self.project.parent / f"{self.project.name}-nested-outside"
        outside.mkdir()
        feedback_root = self.project / ".run-artifacts/teamwork-engineering-assistant/feedback"
        feedback_root.mkdir(parents=True)
        (feedback_root / "events").symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError, "symlink|escapes"):
                self.collector.collect_codex(self.stop_payload("当前阻断。"))
            self.assertEqual([], list(outside.iterdir()))
        finally:
            for child in outside.iterdir():
                child.unlink()
            outside.rmdir()


if __name__ == "__main__":
    unittest.main()
