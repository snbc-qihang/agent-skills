from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("qualification_diagnostic", ROOT / "scripts/qualify_installation.py")
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)

from engineering_assistant.installer import installation as inst
from engineering_assistant.runtime.validation import ValidationFailure


class WindowsQualificationDiagnosticTests(unittest.TestCase):
    """Portable failure-collection contracts, not native Windows qualification."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.lock = inst.runtime_lock(ROOT, "codex", "windows-x64", "2.3.0.0-rc.1")[0]
        package = self.base / "packages/codex/engineering-assistant"
        package.mkdir(parents=True)
        (package / "runtime-lock.json").write_text(json.dumps(self.lock))
        (package / "runtime-python-downloads.json").write_bytes(inst.python_download_metadata(self.lock))
        self.python_base = (self.base / "Runtime 数据/python" / self.lock["python_artifact_digest"]
                            / self.lock["python_artifact"]["key"])
        self.python_base.mkdir(parents=True)
        (self.python_base / "BUILD").write_text(self.lock["python_artifact"]["build"])
        (self.python_base / "runtime-python.json").write_text(json.dumps(inst._python_receipt(self.lock)))
        self.python = self.python_base / "python.exe"
        self.python.write_bytes(b"fixed interpreter fixture; never executed")

    @staticmethod
    def child_report():
        return {"diagnostic_only": True, "qualified": False, "baseline": {"entry": True},
                "detached_console": {"entry": True, "complete": True}}

    def test_uses_only_verified_artifact_base_and_fixed_argument_free_script(self):
        with patch.object(qualification, "run_bounded_windows", return_value=(0, json.dumps(self.child_report()).encode())) as run, \
             patch.dict(os.environ, {"PYTHONHOME": "other-runtime", "PYTHONPATH": "untrusted-code",
                                     "PYTHONINSPECT": "1", "PYTHONPLATLIBDIR": "other-lib",
                                     "RUSTUP_TOOLCHAIN": "1.90.0", "CARGO_HOME": "fixed-toolchain"}):
            report = qualification._windows_native_failure_diagnostic(self.base)
        args, options = run.call_args
        self.assertEqual([str(self.python), "-I", str(ROOT / "scripts/diagnose_windows_native.py")], args[0])
        self.assertEqual(ROOT, options["cwd"])
        self.assertEqual(180, options["timeout_seconds"])
        self.assertEqual(65536, options["output_limit_bytes"])
        self.assertEqual("1.90.0", options["environment"]["RUSTUP_TOOLCHAIN"])
        self.assertEqual("fixed-toolchain", options["environment"]["CARGO_HOME"])
        self.assertEqual("uv_managed", report["runtime_distribution"])
        self.assertIs(report["qualified"], False)
        self.assertIs(report["diagnostic_only"], True)
        self.assertEqual(0, report["diagnostic_exit_code"])
        self.assertNotEqual("runtime_qualified", report.get("status"))

    def test_wrong_schema_target_agent_or_artifact_lock_never_spawns(self):
        for field, value in (("schema_version", "1"), ("target", "linux-x64"), ("agent", "hermes"),
                             ("python_artifact_digest", "a" * 64)):
            with self.subTest(field=field):
                lock = copy.deepcopy(self.lock)
                lock[field] = value
                path = self.base / "packages/codex/engineering-assistant/runtime-lock.json"
                path.write_text(json.dumps(lock))
                with patch.object(qualification, "run_bounded_windows") as run, self.assertRaises(ValidationFailure):
                    qualification._windows_native_failure_diagnostic(self.base)
                run.assert_not_called()
        path.write_text(json.dumps(self.lock))

    def test_missing_or_wrong_receipt_and_build_never_spawn(self):
        receipt = self.python_base / "runtime-python.json"
        build = self.python_base / "BUILD"
        for name, path, value in (("missing_receipt", receipt, None), ("wrong_receipt", receipt, "{}"),
                                  ("wrong_build", build, "20260602")):
            with self.subTest(case=name):
                old = path.read_bytes()
                if value is None:
                    path.unlink()
                else:
                    path.write_text(value)
                with patch.object(qualification, "run_bounded_windows") as run, self.assertRaises(ValidationFailure):
                    qualification._windows_native_failure_diagnostic(self.base)
                run.assert_not_called()
                path.write_bytes(old)

    def test_missing_directory_symlink_or_reparse_interpreter_never_spawn(self):
        kinds = ["missing", "directory", "reparse"]
        if os.name != "nt":
            kinds.append("symlink")  # Windows symlink creation requires a separate host privilege.
        for kind in kinds:
            with self.subTest(kind=kind):
                self.python.unlink()
                if kind == "directory":
                    self.python.mkdir()
                elif kind == "symlink":
                    self.python.symlink_to(ROOT / "scripts/qualify_installation.py")
                elif kind == "reparse":
                    self.python.write_bytes(b"fixture")
                with patch.object(qualification, "run_bounded_windows") as run, \
                     patch.object(qualification, "_diagnostic_reparse", side_effect=lambda path:
                                  kind == "reparse" and path == self.python), \
                     self.assertRaises((OSError, ValidationFailure)):
                    qualification._windows_native_failure_diagnostic(self.base)
                run.assert_not_called()
                if self.python.is_dir():
                    self.python.rmdir()
                elif self.python.exists() or self.python.is_symlink():
                    self.python.unlink()
                self.python.write_bytes(b"fixture")

    def test_reparse_in_any_prepared_base_directory_never_spawns(self):
        data = self.base / "Runtime 数据"
        directories = (self.base, data, data / "python", self.python_base.parent, self.python_base)
        for directory in directories:
            with self.subTest(directory=directory.name), \
                 patch.object(qualification, "_diagnostic_reparse", side_effect=lambda path: path == directory), \
                 patch.object(qualification, "run_bounded_windows") as run, self.assertRaises(ValidationFailure):
                qualification._windows_native_failure_diagnostic(self.base)
            run.assert_not_called()

    def test_child_cannot_promote_diagnostic_to_qualification(self):
        for child in ({"diagnostic_only": True, "qualified": True},
                      {"diagnostic_only": False, "qualified": False},
                      {"diagnostic_only": 1, "qualified": 0}, [False, True], "not-json"):
            with self.subTest(child_type=type(child).__name__), \
                 patch.object(qualification, "run_bounded_windows", return_value=(0, json.dumps(child).encode())), \
                 self.assertRaises(ValidationFailure):
                qualification._windows_native_failure_diagnostic(self.base)
        with patch.object(qualification, "run_bounded_windows", return_value=(1, json.dumps(self.child_report()).encode())):
            report = qualification._windows_native_failure_diagnostic(self.base)
        self.assertEqual(1, report["diagnostic_exit_code"])
        self.assertIs(report["qualified"], False)

    def run_main(self, *, opted_in=True, windows=True, qualify_error=None, diagnostic_error=None):
        output = self.base / "result/runtime-qualification.json"
        argv = ["qualify_installation.py", "--output", str(output)]
        if opted_in:
            argv.append("--diagnose-windows-native-on-failure")
        success = {"status": "runtime_qualified", "target": "windows-x64", "results": []}
        with patch.object(qualification.sys, "argv", argv), \
             patch.object(qualification.sys, "platform", "win32" if windows else "linux"), \
             patch.object(qualification, "qualify", side_effect=qualify_error, return_value=success), \
             patch.object(qualification, "_windows_native_failure_diagnostic", side_effect=diagnostic_error,
                          return_value={"diagnostic_only": True, "qualified": False, "runtime_distribution": "uv_managed",
                                        "diagnostic_exit_code": 0, "diagnostic": self.child_report()}) as diagnostic, \
             redirect_stdout(io.StringIO()):
            if qualify_error is not None:
                with self.assertRaises(type(qualify_error)) as caught:
                    qualification.main()
                self.assertIs(qualify_error, caught.exception)
            else:
                self.assertEqual(0, qualification.main())
        return output, diagnostic

    def test_failure_opt_in_writes_only_separate_diagnostic_and_preserves_original_error(self):
        error = ValidationFailure("original Provider positive probe failed")
        output, diagnostic = self.run_main(qualify_error=error)
        diagnostic.assert_called_once()
        self.assertFalse(output.exists())
        result = json.loads((output.parent / "uv-native-diagnostic.json").read_text())
        self.assertIs(result["qualified"], False)
        self.assertIs(result["diagnostic_only"], True)
        self.assertEqual("uv_managed", result["runtime_distribution"])

    def test_success_nonwindows_and_absent_opt_in_do_not_collect(self):
        for options in ({}, {"windows": False, "qualify_error": ValidationFailure("original")},
                        {"opted_in": False, "qualify_error": ValidationFailure("original")}):
            with self.subTest(options=options):
                _, diagnostic = self.run_main(**options)
                diagnostic.assert_not_called()

    def test_diagnostic_runs_before_prepared_temporary_base_is_cleaned(self):
        observed = []
        def observe(base):
            self.assertTrue(base.is_dir())
            observed.append(base)
            return {"runtime_distribution": "uv_managed", "qualified": False, "diagnostic_only": True}
        self.run_main(qualify_error=ValidationFailure("original"), diagnostic_error=observe)
        self.assertEqual(1, len(observed))
        self.assertFalse(observed[0].exists())

    def test_collector_json_or_write_failure_never_replaces_original_qualification_error(self):
        for failure in (OSError("collector failed"), ValueError("invalid child JSON"), RuntimeError("collector failed")):
            with self.subTest(failure_type=type(failure).__name__):
                self.run_main(qualify_error=ValidationFailure("original"), diagnostic_error=failure)
        with patch.object(Path, "write_text", side_effect=OSError("artifact write failed")):
            self.run_main(qualify_error=ValidationFailure("original"))

    def test_ci_opt_in_is_confined_to_failed_windows_path(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertEqual(1, workflow.count("--diagnose-windows-native-on-failure"))
        position = workflow.index("--diagnose-windows-native-on-failure")
        self.assertGreater(position, workflow.index("Windows 启动失败后验证实际 uv Runtime"))
        self.assertLess(position, workflow.index("全量回归与不可跳过的原生安全验证"))
        self.assertIn('"overall_gate": "blocked"', workflow[:position])


if __name__ == "__main__":
    unittest.main()
