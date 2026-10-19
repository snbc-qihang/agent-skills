from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.runtime.artifact_io import artifact_fs
from engineering_assistant.runtime.feedback import FeedbackStore
from engineering_assistant.runtime.usage_observation import UsageObservationStore


class _NoDirectoryFdOS:
    """Reproduce Python Windows' missing fd APIs without simulating NT handles."""

    def __getattr__(self, name):
        if name in {"O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"}:
            raise AttributeError(name)
        return getattr(os, name)

    def scandir(self, path):
        if isinstance(path, int):
            raise NotImplementedError("standard Windows os.scandir does not accept directory fds")
        return os.scandir(path)

    def open(self, path, flags, *args, **kwargs):
        if kwargs.get("dir_fd") is not None:
            raise NotImplementedError("standard Windows os.open has no dir_fd")
        return os.open(path, flags, *args, **kwargs)

    def stat(self, path, *args, **kwargs):
        if kwargs.get("dir_fd") is not None:
            raise NotImplementedError("standard Windows os.stat has no dir_fd")
        return os.stat(path, *args, **kwargs)


class ArtifactCallerTests(unittest.TestCase):
    def test_feedback_streaming_uses_the_anchored_filesystem_seam(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FeedbackStore(tmp, ROOT / "schemas")
            try:
                store.artifacts.write_bytes_exclusive(b"{}", "efficiency-candidates", "bad.json")
                store.artifacts.write_bytes_exclusive(b"{}", "events", "bad.json")
                with patch("engineering_assistant.runtime.feedback.os", _NoDirectoryFdOS()), patch(
                    "engineering_assistant.runtime.feedback.artifact_fs", artifact_fs, create=True
                ):
                    self.assertEqual([None], list(store.iter_efficiency_candidates()))
                    self.assertEqual([None], list(store.iter_feedback_events()))
            finally:
                store.artifacts.close()

    def test_usage_pruning_uses_the_anchored_directory_flags_and_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UsageObservationStore(tmp, ROOT / "schemas")
            try:
                path = store.artifacts.write_bytes_exclusive(
                    b"{}", "session-" + "0" * 16, "turn-" + "0" * 16 + ".json"
                )
                os.utime(path, (1, 1))
                with patch("engineering_assistant.runtime.usage_observation.os", _NoDirectoryFdOS()), patch(
                    "engineering_assistant.runtime.usage_observation.artifact_fs", artifact_fs, create=True
                ):
                    self.assertEqual(1, store.prune_stale(now=200_000))
                self.assertFalse(path.exists())
            finally:
                store.artifacts.close()


if __name__ == "__main__":
    unittest.main()
