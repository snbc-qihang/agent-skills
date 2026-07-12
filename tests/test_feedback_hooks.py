from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.feedback import (  # noqa: E402
    FeedbackCollector,
    FeedbackStore,
    run_codex_hook,
)
from engineering_assistant.validation import load_json, validate_instance  # noqa: E402


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
                / ".run-artifacts/engineering-assistant/feedback"
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
        self.assertNotIn("session-sensitive-id", json.dumps(capture))

    def test_normal_stop_records_metadata_without_creating_feedback_noise(self) -> None:
        result = self.collector.collect_codex(self.stop_payload("实现完成，所有验证均已通过。"))
        self.assertEqual("no_signal", result.capture.status)
        self.assertEqual([], self.artifacts("events"))
        self.assertEqual(1, len(self.artifacts("captures")))

    def test_continued_stop_is_loop_guarded(self) -> None:
        result = self.collector.collect_codex(
            self.stop_payload("测试失败，需要继续修复。", active=True)
        )
        self.assertEqual("skipped_continuation", result.capture.status)
        self.assertEqual([], self.artifacts("events"))

    def test_user_correction_is_redacted_and_promoted_to_feedback(self) -> None:
        secret = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
        payload = self.prompt_payload(f"刚才的实现不对，请改为复用现有接口。API_KEY={secret}")
        result = self.collector.collect_codex(payload)
        event = result.event
        self.assertIsNotNone(event)
        self.assertEqual("human_correction", event.event_type)
        self.assertEqual("human", event.source)
        artifact_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [*self.artifacts("captures"), *self.artifacts("events")]
        )
        self.assertNotIn(secret, artifact_text)
        self.assertIn("<redacted>", artifact_text)

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
        self.assertNotIn("decision", json.loads(invalid_output.getvalue()))
        self.assertIn("systemMessage", json.loads(invalid_output.getvalue()))

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
        feedback_root = self.project / ".run-artifacts/engineering-assistant/feedback"
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
