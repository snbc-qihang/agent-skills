"""Output guards use disposable author fixtures, never the real author tree."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.validation import ValidationFailure

spec = importlib.util.spec_from_file_location("verify_setup_wheel", ROOT / "scripts/verify_setup_wheel.py")
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


class SetupWheelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.author = self.base / "author_fixture"
        for relative in ("catalog/skills", "skills", "schemas", "src/engineering_assistant", "config"):
            (self.author / relative).mkdir(parents=True, exist_ok=True)
        (self.author / "catalog/skills/public.json").write_text(json.dumps({"version": "2.3.0.0-rc.1"}))
        (self.author / "pyproject.toml").write_text('[project]\nversion = "2.3.0rc1"\n')
        self.wheel = self.base / "setup-2.3.0rc1-py3-none-any.whl"
        with zipfile.ZipFile(self.wheel, "w") as archive:
            archive.writestr("setup-2.3.0rc1.dist-info/METADATA", "Name: setup\nVersion: 2.3.0rc1\n")
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(verification, "ROOT", self.author).start()
        self.uv = mock.patch.object(verification, "_uv", return_value=Path(sys.executable)).start()
        self.protocol = mock.patch.object(verification, "_protocol_run", side_effect=self.protocol_result).start()

    @staticmethod
    def protocol_result(command, **kwargs):
        if "-c" in command:
            return (verification.PYTHON_VERSION + "\n").encode()
        if "doctor" in command:
            return b'{"status":"unsupported"}'
        return b""

    def assert_rejected_before_setup(self, output):
        with self.assertRaises((ValueError, ValidationFailure, OSError)):
            verification.verify(self.wheel, output)
        self.uv.assert_not_called()
        self.protocol.assert_not_called()

    def test_author_output_is_rejected_before_environment_preparation(self):
        self.assert_rejected_before_setup(self.author / "new" / "wheel-verification.json")
        self.assertFalse((self.author / "new").exists())

    def test_author_symlink_alias_is_rejected_without_creating_output(self):
        alias = self.base / "author-alias"
        alias.symlink_to(self.author, target_is_directory=True)
        self.assert_rejected_before_setup(alias / "new" / "wheel-verification.json")
        self.assertFalse((self.author / "new").exists())

    def test_parent_traversal_is_rejected_without_creating_output(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.assert_rejected_before_setup(outside / ".." / self.author.name / "wheel-verification.json")
        self.assertFalse((self.author / "wheel-verification.json").exists())

    def test_parent_replacement_cannot_redirect_receipt_into_author_tree(self):
        parent = self.base / "receipts"
        parent.mkdir()
        retained = self.base / "retained-receipts"
        swapped = False

        def replace_during_setup(command, **kwargs):
            nonlocal swapped
            if not swapped:
                parent.rename(retained)
                parent.symlink_to(self.author, target_is_directory=True)
                swapped = True
            return self.protocol_result(command, **kwargs)

        self.protocol.side_effect = replace_during_setup
        try:
            verification.verify(self.wheel, parent / "wheel-verification.json")
        except (ValueError, ValidationFailure, OSError):
            pass  # Failing closed is also valid after a directory replacement.
        self.assertTrue(swapped)
        self.assertFalse((self.author / "wheel-verification.json").exists())

    def test_parent_replacement_before_directory_creation_stays_anchored(self):
        parent = self.base / "receipts"
        parent.mkdir()
        retained = self.base / "retained-receipts"
        original = verification.ArtifactIO.ensure_directory
        swapped = False

        def replace_before_creation(artifact, *parts):
            nonlocal swapped
            if not swapped and artifact.project_root == parent:
                parent.rename(retained)
                parent.symlink_to(self.author, target_is_directory=True)
                swapped = True
            return original(artifact, *parts)

        with mock.patch.object(verification.ArtifactIO, "ensure_directory", replace_before_creation):
            try:
                verification.verify(self.wheel, parent / "new" / "wheel-verification.json")
            except (ValueError, ValidationFailure, OSError):
                pass
        self.assertTrue(swapped)
        self.assertFalse((self.author / "new").exists())

    def test_another_author_tree_is_rejected_before_new_directories(self):
        other = self.base / "other-author"
        for relative in ("catalog", "skills", "schemas", "src/engineering_assistant"):
            (other / relative).mkdir(parents=True, exist_ok=True)
        self.assert_rejected_before_setup(other / "new" / "wheel-verification.json")
        self.assertFalse((other / "new").exists())

    def test_success_preserves_receipt_and_all_smoke_checks(self):
        output = self.base / "outside" / "nested" / "wheel-verification.json"
        report = verification.verify(self.wheel, output)
        self.assertEqual(json.loads(output.read_text()), report)
        self.assertEqual(set(report), {"schema_version", "status", "python_version", "canonical_version",
                                      "wheel_filename", "wheel_digest", "wheel_version", "checks"})
        self.assertEqual(report["wheel_digest"], "sha256:" + hashlib.sha256(self.wheel.read_bytes()).hexdigest())
        self.assertEqual(report["checks"], {"help": "passed", "doctor": "passed",
                                           "source_validation": "passed", "eval": "passed"})
        commands = [call.args[0] for call in self.protocol.call_args_list]
        self.assertEqual(len(commands), 8)
        self.assertEqual(self.protocol.call_args_list[5].kwargs["expected_exit_code"], 2)
        for call in self.protocol.call_args_list[3:]:
            self.assertEqual(call.kwargs["environment"]["PATH"], "")
            self.assertNotIn("PYTHONPATH", call.kwargs["environment"])
            self.assertNotIn("PYTHONHOME", call.kwargs["environment"])

    def test_failed_smoke_never_writes_a_passed_receipt(self):
        output = self.base / "outside" / "wheel-verification.json"
        self.protocol.side_effect = RuntimeError("smoke failed")
        with self.assertRaisesRegex(RuntimeError, "smoke failed"):
            verification.verify(self.wheel, output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
