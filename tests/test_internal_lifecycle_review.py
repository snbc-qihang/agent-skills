"""Bounded lifecycle regressions; synthetic state does not qualify a native host."""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_internal_installation as fixtures
from engineering_assistant import internal_installation as managed
from engineering_assistant.setup_cli import main
from engineering_assistant.validation import ValidationFailure

SELECT_MARKET = managed._select_market


class InternalLifecycleReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ManagedInstallationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def command(self, name):
        with redirect_stdout(io.StringIO()) as output:
            code = main([name, "--agent", "codex", "--agent-home", str(self.fixture.home),
                         "--data-home", str(self.fixture.data), "--json"])
        return code, json.loads(output.getvalue())

    def test_registered_local_market_selection_never_runs_git_only_upgrade(self):
        source = self.fixture.root / "local-market"
        # Codex 0.159.2 rejects `marketplace upgrade` for sourceType=local.
        with mock.patch.object(managed.runtime, "_marketplace_entry", return_value={"name": managed.MARKETPLACE}), \
                mock.patch.object(managed.runtime, "_verify_marketplace_source"), \
                mock.patch.object(managed.runtime, "_native_call") as native:
            SELECT_MARKET(self.fixture.home, source)
        self.assertEqual([["plugin", "add", "engineering-assistant@engineering-assistant", "--json"]],
                         [call.args[1] for call in native.call_args_list])

    def test_retry_uninstall_finishes_market_cleanup_after_plugin_was_removed(self):
        fixture = self.fixture
        fixture.install()
        fail_once = True

        def native(_agent, arguments, _home):
            nonlocal fail_once
            if arguments[:2] == ["plugin", "remove"]:
                fixture.selected = None
            elif arguments[:3] == ["plugin", "marketplace", "remove"]:
                if fail_once:
                    fail_once = False
                    raise ValidationFailure("controlled marketplace cleanup failure")
                fixture.registered = False
            return "{}"

        with mock.patch.object(managed.runtime, "_native_call", side_effect=native), \
                mock.patch.object(managed.runtime, "_verify_marketplace_source"):
            first_code, first = self.command("uninstall")
            self.assertEqual(2, first_code)
            self.assertEqual("failed", first["status"])
            self.assertIsNone(fixture.selected)
            second_code, second = self.command("uninstall")
        self.assertEqual(0, second_code, second)
        self.assertEqual("uninstalled", second["status"])
        self.assertIsNone(fixture.state())
        self.assertFalse(fixture.registered)

    def test_compensation_uses_the_explicit_uv_path(self):
        fixture = self.fixture
        explicit_uv = fixture.root / "custom tools/uv"

        def prepare(_package, **options):
            if options.get("uv_executable") != explicit_uv:
                raise ValidationFailure("default uv is not available")
            return {"agent": "codex"}

        with mock.patch.object(managed.runtime, "prepare_runtime", side_effect=prepare):
            managed.install_internal_codex(home=fixture.home, data_home=fixture.data, uv_executable=explicit_uv)
            fixture.release("2.3.0.0-rc.3")
            fixture.fail_candidate = True
            result = managed.install_internal_codex(home=fixture.home, data_home=fixture.data,
                uv_executable=explicit_uv, update=True)
        self.assertFalse(result["recovery_required"], result)
        self.assertEqual("previous_selection_restored", result["native_state"])

    def test_state_commit_followed_by_io_error_does_not_leave_active_identity_diverged(self):
        fixture = self.fixture
        fixture.install()
        fixture.release("2.3.0.0-rc.3")
        save = managed._save_state
        failed_once = False

        def save_then_fail(storage, state, old):
            nonlocal failed_once
            result = save(storage, state, old)
            if (not failed_once and state["phase"] == "active"
                    and state["current"]["canonical_version"].endswith("rc.3")):
                failed_once = True
                # replace_json_cas can replace successfully before its directory fsync fails.
                raise OSError("controlled post-replace fsync failure")
            return result

        with mock.patch.object(managed, "_save_state", side_effect=save_then_fail):
            fixture.install(update=True)
        state = fixture.state()
        selected = fixture.package(fixture.selected["package"])
        if state["phase"] == "active":
            self.assertEqual(state["current"]["package_payload_digest"], selected["payload_digest"])
        else:
            repaired = managed.repair_internal_codex(home=fixture.home, data_home=fixture.data)
            self.assertEqual("needs_trust", repaired["status"], repaired)


if __name__ == "__main__":
    unittest.main()
