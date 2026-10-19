"""Local validation failure gates; these fixtures do not qualify a host."""
from __future__ import annotations

import importlib.util
from contextlib import redirect_stdout
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from engineering_assistant.runtime.validation import ValidationFailure
from engineering_assistant.runtime.artifact_io import ArtifactConflict


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalValidationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "Git is required for source binding")
    def test_source_binding_preserves_checkout_line_endings_and_ignores_git_routing(self):
        validation = script("validate_local")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "source.txt").write_bytes(b"fixture\r\n")
            for arguments in (("init",), ("config", "core.autocrlf", "true"), ("add", "."), ("-c", "user.name=fixture", "-c",
                    "user.email=fixture@example.invalid", "commit", "-m", "build: fixture"),
                    ("remote", "add", "origin", "https://github.com/snbc-qihang/agent-skills.git")):
                subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)
            expected = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            with mock.patch.object(validation, "ROOT", root), mock.patch.dict(os.environ, {
                    "GIT_DIR": str(root / "missing.git"), "GIT_WORK_TREE": str(root / "missing"),
                    "GIT_INDEX_FILE": str(root / "missing.index")}):
                self.assertEqual(expected, validation._source_identity())

    def test_source_identity_refuses_dirty_or_untracked_source(self):
        validation = script("validate_local")
        for status in (" M src/engineering_assistant/runtime/version.py", "?? untracked.py"):
            with mock.patch.object(validation, "_git", side_effect=["a" * 40, status]):
                with self.assertRaisesRegex(ValidationFailure, "未提交"):
                    validation._source_identity()

    def test_local_batch_is_bound_to_source_without_a_ci_identity(self):
        validation = script("validate_local")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "batch.json"
            with mock.patch.object(validation, "_source_identity", return_value="a" * 40):
                result = validation.initialize(path)
            self.assertEqual(result, json.loads(path.read_text()))
            self.assertEqual("local_unattested", result["validation_origin"]["assurance"])
            self.assertEqual("a" * 40, result["source_commit"])
            self.assertNotIn("ci_identity", result)
            with self.assertRaises(ArtifactConflict):
                with mock.patch.object(validation, "_source_identity", return_value="a" * 40):
                    validation.initialize(path)

    def test_other_source_cannot_reuse_a_local_batch(self):
        validation = script("validate_local")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with mock.patch.object(validation, "_source_identity", return_value="a" * 40):
                validation.initialize(root / "batch.json")
            with mock.patch.object(validation, "_source_identity", return_value="b" * 40), \
                    mock.patch.object(validation, "_native_tests") as tests:
                with self.assertRaisesRegex(ValidationFailure, "源码"):
                    validation.run(root / "batch.json", root / "result")
                tests.assert_not_called()
                self.assertFalse((root / "result").exists())

    def test_assembler_cli_reads_the_generated_batch_and_rejects_mixed_ci_arguments(self):
        validation, assembly = script("validate_local"), script("assemble_release")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with mock.patch.object(validation, "_source_identity", return_value="a" * 40):
                batch = validation.initialize(root / "batch.json")
            arguments = ["--validation-origin", str(root / "batch.json"), "--wheel", str(root / "setup.whl"),
                         "--output", str(root / "candidate")]
            with mock.patch.object(assembly, "assemble_release", return_value={"status": "candidate",
                    "canonical_version": "1.0.0.1", "support_qualification": {"status": "not_satisfied"}}) as assemble, \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(0, assembly.main(arguments))
                self.assertEqual(batch["source_commit"], assemble.call_args.kwargs["source_commit"])
                self.assertEqual(batch["validation_origin"], assemble.call_args.kwargs["validation_origin"])
                assemble.reset_mock()
                self.assertEqual(2, assembly.main([*arguments, "--ci-run-id", "123"]))
                assemble.assert_not_called()

    def test_required_native_skip_or_missing_test_cannot_create_a_pass_record(self):
        validation = script("validate_local")
        class Required(unittest.TestCase):
            @unittest.skip("fixture")
            def test_native(self):
                pass
        required = Required("test_native").id()
        for names in ({required}, {"missing.test"}):
            suite = unittest.TestSuite([Required("test_native")])
            with mock.patch.object(validation.unittest.defaultTestLoader, "discover", return_value=suite), \
                    mock.patch.object(validation, "required_native_tests", return_value=names), \
                    mock.patch.object(validation.sys, "stderr", io.StringIO()):
                with self.assertRaisesRegex(ValidationFailure, "原生"):
                    validation._native_tests("macos-arm64")

    def test_source_change_during_validation_leaves_no_bound_pass_records(self):
        validation = script("validate_local")
        with tempfile.TemporaryDirectory() as temporary:
            root, output = Path(temporary).resolve(), Path(temporary).resolve() / "result"
            with mock.patch.object(validation, "_source_identity", return_value="a" * 40):
                validation.initialize(root / "batch.json")
            def protocol(command, **kwargs):
                if "build" in command:
                    (output / "setup/test.whl").write_bytes(b"fixture")
                return b""
            with mock.patch.object(validation, "_source_identity", side_effect=["a" * 40, "b" * 40]), \
                    mock.patch.object(validation, "host_target", return_value="macos-arm64"), \
                    mock.patch.object(validation.platform, "python_version", return_value="3.13.13"), \
                    mock.patch.object(validation, "_native_tests", return_value={}), \
                    mock.patch.object(validation, "load_catalog"), \
                    mock.patch.object(validation, "run_evals", return_value={}), \
                    mock.patch.object(validation, "build_package"), mock.patch.object(validation, "verify_package"), \
                    mock.patch.object(validation, "validate_with_official_tools", return_value={}), \
                    mock.patch.object(validation, "qualify", return_value={}), \
                    mock.patch.object(validation, "_uv", return_value=Path("/fixture/uv")), \
                    mock.patch.object(validation, "_protocol_run", side_effect=protocol), \
                    mock.patch.object(validation, "_verify_wheel", return_value={}):
                with self.assertRaisesRegex(ValidationFailure, "源码"):
                    validation.run(root / "batch.json", output)
            for name in ("host.json", "native-tests.json", "runtime-qualification.json",
                         "official-validation.json", "setup/wheel-verification.json"):
                self.assertFalse((output / name).exists(), name)

    def test_runtime_qualification_does_not_accept_core_success_with_provider_failure(self):
        qualification = script("qualify_installation")
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(qualification, "host_target", return_value="macos-arm64"), \
                mock.patch.object(qualification, "build_package"), \
                mock.patch.object(qualification, "verify_package", return_value={"platform": "codex", "target": "macos-arm64"}), \
                mock.patch.object(qualification, "prepare_runtime"), \
                mock.patch.object(qualification, "doctor", return_value={
                    "runtime_ready": True, "provider_ready": False, "checks": {"hook": "passed"}}):
            with self.assertRaisesRegex(RuntimeError, "qualification failed"):
                qualification.qualify(Path(temporary).resolve())


if __name__ == "__main__":
    unittest.main()
