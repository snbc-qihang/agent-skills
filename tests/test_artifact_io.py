from __future__ import annotations

import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.artifact_io import ArtifactConflict, ArtifactIO  # noqa: E402
from engineering_assistant.feedback import FeedbackStore  # noqa: E402
from engineering_assistant.model import FeedbackCapture  # noqa: E402
from engineering_assistant.state_store import StateStore  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class ArtifactIOTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_immutable_concurrent_writers_never_overwrite_each_other(self) -> None:
        artifacts = ArtifactIO(self.project, ".run-artifacts/engineering-assistant")
        barrier = Barrier(2)

        def write(value: int) -> str:
            barrier.wait()
            try:
                artifacts.create_immutable_json({"value": value}, "run", "same.json")
                return "created"
            except ArtifactConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(write, (1, 2)))
        self.assertEqual(["conflict", "created"], sorted(outcomes))
        payload = json.loads(artifacts.path("run", "same.json").read_text(encoding="utf-8"))
        self.assertIn(payload["value"], {1, 2})

    def test_cas_allows_only_one_writer_from_the_same_revision(self) -> None:
        artifacts = ArtifactIO(self.project, ".run-artifacts/engineering-assistant")
        artifacts.create_immutable_json({"revision": 0, "winner": None}, "run", "state.json")
        barrier = Barrier(2)

        def update(value: int) -> str:
            barrier.wait()
            try:
                artifacts.replace_json_cas(
                    {"revision": 1, "winner": value},
                    "run",
                    "state.json",
                    expected_revision=0,
                )
                return "saved"
            except ArtifactConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(update, (1, 2)))
        self.assertEqual(["conflict", "saved"], sorted(outcomes))

    def test_state_store_rejects_run_root_symlink_escape(self) -> None:
        outside = self.project / "outside"
        outside.mkdir()
        (self.project / ".run-artifacts").mkdir()
        (self.project / ".run-artifacts/engineering-assistant").symlink_to(
            outside, target_is_directory=True
        )
        store = StateStore(self.project, ROOT / "schemas")
        with self.assertRaisesRegex(ValidationFailure, "symlink"):
            store.run_dir("run-1")

    def test_static_lock_symlink_is_rejected_without_opening_its_target(self) -> None:
        artifacts = ArtifactIO(self.project, ".run-artifacts/engineering-assistant")
        directory = artifacts.path("run")
        directory.mkdir(parents=True)
        target = self.project / "outside-lock-target"
        target.write_text("unchanged", encoding="utf-8")
        (directory / ".artifact.lock").symlink_to(target)
        with self.assertRaisesRegex(ValidationFailure, "safe regular file"):
            artifacts.create_immutable_json({"value": 1}, "run", "value.json")
        self.assertEqual("unchanged", target.read_text(encoding="utf-8"))

    def test_feedback_duplicate_capture_is_first_writer_wins(self) -> None:
        store = FeedbackStore(self.project, ROOT / "schemas")
        capture = FeedbackCapture(
            capture_id="capture-" + "0" * 24,
            session_ref="session-" + "0" * 16,
            turn_ref="turn-" + "0" * 16,
            event_name="Stop",
            platform="codex",
            model="test",
            permission_mode="test",
            status="no_signal",
            content_digest="sha256:" + "0" * 64,
            content_length=1,
            redaction_count=0,
            candidate_event_ids=[],
            captured_at="2026-07-11T10:00:00+08:00",
        )
        barrier = Barrier(2)

        def save(_: int) -> bool:
            barrier.wait()
            return store.save_capture(capture)

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(save, (1, 2)))
        self.assertEqual([False, True], sorted(outcomes))


if __name__ == "__main__":
    unittest.main()
