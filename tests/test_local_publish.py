from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.compiler import build_package, verify_package  # noqa: E402
from engineering_assistant.local_publish import (  # noqa: E402
    _load_policy,
    _publish_one,
    _roll_back,
    _swap_in,
    _update_personal_marketplace,
)
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class LocalPublishTests(unittest.TestCase):
    def test_codex_cachebuster_is_built_before_package_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "codex"
            build_package(ROOT, "codex", output, codex_cachebuster="local-test-1")
            verify_package(output)
            manifest = json.loads((output / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
            self.assertEqual("1.0.0-rc.1+codex.local-test-1", manifest["version"])

    def test_local_publish_policy_allows_both_platforms_without_history(self) -> None:
        policy = ROOT / "config/local-publish-policy.json"
        loaded = _load_policy(policy, ["codex", "hermes"])
        self.assertTrue(loaded["enabled"])
        self.assertEqual("1.0.0.0-rc.1", loaded["canonical_version"])
        self.assertNotIn("reviewer", loaded)
        self.assertNotIn("execution_result", loaded)

    def test_personal_marketplace_is_created_and_updated_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".agents/plugins/marketplace.json"
            previous, changed = _update_personal_marketplace(path)
            self.assertIsNone(previous)
            self.assertTrue(changed)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("personal", payload["name"])
            self.assertEqual("engineering-assistant", payload["plugins"][0]["name"])
            self.assertEqual("./plugins/engineering-assistant", payload["plugins"][0]["source"]["path"])
            _, changed_again = _update_personal_marketplace(path)
            self.assertFalse(changed_again)

    def test_dry_run_builds_both_platforms_without_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            for platform in ["codex", "hermes"]:
                report = _publish_one(
                    ROOT,
                    platform,
                    codex_home=home / ".codex",
                    hermes_home=home / ".hermes",
                    dry_run=True,
                    register=lambda _command, _environment=None: self.fail("dry-run must not register"),
                )
                self.assertEqual("dry_run_passed", report["status"])
                self.assertEqual(11, report["skill_count"])
            self.assertFalse((home / "plugins").exists())
            self.assertFalse((home / ".hermes").exists())

    def test_atomic_swap_can_be_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "engineering-assistant"
            staging = root / ".stage"
            target.mkdir()
            staging.mkdir()
            (target / "version").write_text("old", encoding="utf-8")
            (staging / "version").write_text("new", encoding="utf-8")
            backup = _swap_in(staging, target, "test")
            self.assertEqual("new", (target / "version").read_text(encoding="utf-8"))
            _roll_back(target, backup, "test")
            self.assertEqual("old", (target / "version").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
