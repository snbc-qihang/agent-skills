# GPT-6 适配变更说明：团队版运行、反馈和观测使用独立目录；旧共享目录不自动迁移或合并。
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.artifact_io import ArtifactConflict, ArtifactIO  # noqa: E402
from engineering_assistant.feedback import FeedbackStore  # noqa: E402
from engineering_assistant.model import FeedbackCapture  # noqa: E402
from engineering_assistant.state_store import StateStore  # noqa: E402
from engineering_assistant.usage_observation import UsageObservationStore  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class ArtifactIOTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_observation_lock_timeout_fails_fast_instead_of_waiting(self) -> None:
        artifacts = ArtifactIO(
            self.project,
            ".run-artifacts/teamwork-engineering-assistant",
            lock_timeout_seconds=0.01,
        )

        with patch(
            "engineering_assistant.artifact_io.fcntl.flock",
            side_effect=BlockingIOError,
        ):
            with self.assertRaisesRegex(ValidationFailure, "lock is busy"):
                artifacts.create_immutable_json({"value": 1}, "run", "locked.json")

    def test_limited_json_read_returns_payload_and_exact_raw_bytes(self) -> None:
        artifacts = ArtifactIO(self.project, ".run-artifacts/teamwork-engineering-assistant")
        path = artifacts.path("run", "payload.json")
        path.parent.mkdir(parents=True)
        raw = b'{"value":1}\n'
        path.write_bytes(raw)

        payload, observed_raw = artifacts.read_json_limited(
            64,
            "run",
            "payload.json",
        )

        self.assertEqual({"value": 1}, payload)
        self.assertEqual(raw, observed_raw)

    def test_bounded_tree_hash_rejects_symlinks_entry_overflow_and_total_bytes(self) -> None:
        root = self.project / "hash-source"
        root.mkdir()
        (root / "first.txt").write_bytes(b"ab")
        (root / "second.txt").write_bytes(b"cd")
        artifacts = ArtifactIO(root, ".")
        try:
            with self.assertRaisesRegex(ValidationFailure, "entry limit"):
                artifacts.sha256_file_digests(
                    max_file_bytes=16,
                    max_entries=1,
                    max_total_bytes=16,
                )
            with self.assertRaisesRegex(ValidationFailure, "size limit"):
                artifacts.sha256_file_digests(
                    max_file_bytes=16,
                    max_entries=8,
                    max_total_bytes=3,
                )
            (root / "linked.txt").symlink_to(root / "first.txt")
            with self.assertRaisesRegex(ValidationFailure, "unsafe"):
                artifacts.sha256_file_digests(
                    max_file_bytes=16,
                    max_entries=8,
                    max_total_bytes=16,
                )
        finally:
            artifacts.close()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO is POSIX-only")
    def test_limited_read_rejects_a_fifo_without_blocking(self) -> None:
        fifo = self.project / "payload.json"
        os.mkfifo(fifo)
        artifacts = ArtifactIO(self.project, ".")
        try:
            with self.assertRaisesRegex(ValidationFailure, "regular file"):
                artifacts.read_json_limited(64, "payload.json")
        finally:
            artifacts.close()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO is POSIX-only")
    def test_tree_hash_rejects_a_regular_file_replaced_by_fifo_before_open(self) -> None:
        payload = self.project / "payload.bin"
        payload.write_bytes(b"safe")
        artifacts = ArtifactIO(self.project, ".")
        real_open = os.open
        swapped = False

        def replace_before_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if not swapped and path == payload.name and kwargs.get("dir_fd") is not None:
                payload.unlink()
                os.mkfifo(payload)
                swapped = True
            return real_open(path, flags, *args, **kwargs)

        try:
            with patch(
                "engineering_assistant.artifact_io.os.open",
                side_effect=replace_before_open,
            ):
                with self.assertRaisesRegex(ValidationFailure, "unsafe"):
                    artifacts.sha256_file_digests(
                        max_file_bytes=16,
                        max_entries=8,
                        max_total_bytes=16,
                    )
            self.assertTrue(swapped)
        finally:
            artifacts.close()

    def test_reads_and_immutable_writes_stay_on_the_opened_root_after_parent_swap(self) -> None:
        switch = self.project / "switch"
        trusted_root = switch / "evidence"
        trusted_root.mkdir(parents=True)
        (trusted_root / "payload.json").write_text(
            '{"value":"trusted"}\n', encoding="utf-8"
        )
        (trusted_root / "state.json").write_text(
            '{"revision":0,"value":"trusted"}\n', encoding="utf-8"
        )
        artifacts = ArtifactIO(trusted_root, ".")

        held = self.project / "switch-held"
        switch.rename(held)
        other = self.project / "other"
        outside_root = other / "evidence"
        outside_root.mkdir(parents=True)
        (outside_root / "payload.json").write_text(
            '{"value":"outside"}\n', encoding="utf-8"
        )
        (outside_root / "state.json").write_text(
            '{"revision":0,"value":"outside"}\n', encoding="utf-8"
        )
        switch.symlink_to(other, target_is_directory=True)

        payload, _raw = artifacts.read_json_limited(1024, "payload.json")
        artifacts.create_immutable_json({"created": True}, "created.json")
        artifacts.replace_json_cas(
            {"revision": 1, "value": "updated"},
            "state.json",
            expected_revision=0,
        )

        self.assertEqual({"value": "trusted"}, payload)
        self.assertTrue((held / "evidence/created.json").is_file())
        self.assertFalse((outside_root / "created.json").exists())
        self.assertEqual(
            "updated",
            json.loads((held / "evidence/state.json").read_text(encoding="utf-8"))[
                "value"
            ],
        )
        self.assertEqual(
            "outside",
            json.loads((outside_root / "state.json").read_text(encoding="utf-8"))[
                "value"
            ],
        )

    def test_runtime_stores_reject_the_author_source_tree_as_a_target(self) -> None:
        author_root = self.project / "author"
        for relative in ("catalog", "skills", "src/engineering_assistant", "schemas"):
            (author_root / relative).mkdir(parents=True, exist_ok=True)

        for factory in (StateStore, FeedbackStore, UsageObservationStore):
            with self.subTest(store=factory.__name__):
                with self.assertRaisesRegex(
                    ValidationFailure,
                    "author or installed plugin tree",
                ):
                    factory(author_root, author_root / "schemas")
        self.assertFalse((author_root / ".run-artifacts").exists())

    def test_installed_schema_cannot_write_into_a_separate_author_source(self) -> None:
        author_root = self.project / "author"
        for relative in ("catalog", "skills", "schemas", "src/engineering_assistant"):
            (author_root / relative).mkdir(parents=True, exist_ok=True)

        with self.assertRaisesRegex(
            ValidationFailure,
            "author or installed plugin tree",
        ):
            StateStore(author_root, ROOT / "schemas")
        self.assertFalse((author_root / ".run-artifacts").exists())

    def test_runtime_stores_reject_the_installed_plugin_tree_as_a_target(self) -> None:
        plugin_root = self.project / "plugin"
        runtime_root = plugin_root / "engineering-assistant"
        for relative in ("catalog", "runtime/engineering_assistant", "schemas"):
            (runtime_root / relative).mkdir(parents=True, exist_ok=True)
        (plugin_root / "skills").mkdir()
        (plugin_root / "package-manifest.json").write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(
            ValidationFailure,
            "author or installed plugin tree",
        ):
            StateStore(plugin_root, runtime_root / "schemas")
        self.assertFalse((plugin_root / ".run-artifacts").exists())

    def test_immutable_concurrent_writers_never_overwrite_each_other(self) -> None:
        artifacts = ArtifactIO(self.project, ".run-artifacts/teamwork-engineering-assistant")
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
        artifacts = ArtifactIO(self.project, ".run-artifacts/teamwork-engineering-assistant")
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
        (self.project / ".run-artifacts/teamwork-engineering-assistant").symlink_to(
            outside, target_is_directory=True
        )
        store = StateStore(self.project, ROOT / "schemas")
        with self.assertRaisesRegex(ValidationFailure, "symlink"):
            store.run_dir("run-1")

    def test_static_lock_symlink_is_rejected_without_opening_its_target(self) -> None:
        artifacts = ArtifactIO(self.project, ".run-artifacts/teamwork-engineering-assistant")
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

    def test_fd_relative_delete_cannot_follow_a_replaced_parent_symlink(self) -> None:
        artifacts = ArtifactIO(self.project, ".run-artifacts/teamwork-engineering-assistant")
        staging = artifacts.path("feedback", "staging")
        staging.mkdir(parents=True)
        candidate = staging / "candidate.json"
        candidate.write_text("staged", encoding="utf-8")
        outside = self.project / "outside"
        outside.mkdir()
        outside_candidate = outside / candidate.name
        outside_candidate.write_text("outside", encoding="utf-8")
        moved = staging.with_name("staging-moved")
        real_stat = os.stat
        swapped = False

        def replace_parent_before_stat(path, *args, **kwargs):
            nonlocal swapped
            if not swapped and path == candidate.name and kwargs.get("dir_fd") is not None:
                staging.rename(moved)
                staging.symlink_to(outside, target_is_directory=True)
                swapped = True
            return real_stat(path, *args, **kwargs)

        with patch(
            "engineering_assistant.artifact_io.os.stat",
            side_effect=replace_parent_before_stat,
        ):
            self.assertTrue(
                artifacts.delete_regular_file("feedback", "staging", candidate.name)
            )

        self.assertTrue(swapped)
        self.assertEqual("outside", outside_candidate.read_text(encoding="utf-8"))
        self.assertFalse((moved / candidate.name).exists())

    def test_conditional_stale_delete_preserves_a_refreshed_file(self) -> None:
        artifacts = ArtifactIO(self.project, ".run-artifacts/teamwork-engineering-assistant")
        path = artifacts.create_immutable_json(
            {"revision": 0}, "usage", "ledger.json"
        )
        stale = 1_700_000_000
        os.utime(path, (stale, stale))
        inspected = path.stat()
        artifacts.replace_json_cas(
            {"revision": 1},
            "usage",
            "ledger.json",
            expected_revision=0,
        )

        self.assertFalse(
            artifacts.delete_regular_file_if_unchanged(
                "usage",
                "ledger.json",
                expected_metadata=inspected,
                older_than=stale + 1,
            )
        )
        self.assertEqual(1, artifacts.read_json("usage", "ledger.json")["revision"])

    def test_bounded_immutable_collision_never_parses_an_oversized_file(self) -> None:
        artifacts = ArtifactIO(self.project, ".run-artifacts/teamwork-engineering-assistant")
        path = artifacts.path("canary", "result.json")
        path.parent.mkdir(parents=True)
        path.write_text('{"value":"' + "x" * 1024 + '"}\n', encoding="utf-8")

        with self.assertRaisesRegex(ValidationFailure, "size limit"):
            artifacts.create_immutable_json_with_status(
                {"value": "ours"},
                "canary",
                "result.json",
                existing_max_bytes=64,
            )

    def test_anchored_runtime_target_validation_detects_an_author_tree(self) -> None:
        author = self.project / "author"
        for relative in ("catalog", "skills", "schemas", "src/engineering_assistant"):
            (author / relative).mkdir(parents=True, exist_ok=True)
        artifacts = ArtifactIO(author, ".")

        with self.assertRaisesRegex(
            ValidationFailure,
            "author or installed plugin tree",
        ):
            artifacts.assert_runtime_target(ROOT / "schemas")


if __name__ == "__main__":
    unittest.main()
