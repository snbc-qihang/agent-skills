from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("native_probe", ROOT / "scripts/diagnose_windows_native.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class WindowsNativeProbeContractTests(unittest.TestCase):
    """Portable hostile-input contracts, not native LPAC startup evidence."""

    @staticmethod
    def image() -> bytes:
        data = bytearray(2048)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 60, 128)
        data[128:132] = b"PE\0\0"
        struct.pack_into("<HH", data, 132, 0x8664, 1)
        struct.pack_into("<HH", data, 148, 240, 2)
        optional = 152
        struct.pack_into("<H", data, optional, 0x20B)
        struct.pack_into("<I", data, optional + 16, 0x1000)
        struct.pack_into("<I", data, optional + 108, 16)
        struct.pack_into("<II", data, optional + 120, 0x1000, 40)
        struct.pack_into("<IIII", data, 400, 1536, 0x1000, 1536, 512)
        struct.pack_into("<IIIII", data, 512, 0x1050, 0, 0, 0x10E0, 0x1050)
        data[736:749] = b"KERNEL32.dll\0"
        cursor = 768
        for index, name in enumerate(sorted(probe.IMPORTS)):
            struct.pack_into("<Q", data, 592 + index * 8, cursor - 512 + 0x1000)
            value = b"\0\0" + name.encode("ascii") + b"\0"
            data[cursor:cursor + len(value)] = value
            cursor += len(value)
        return bytes(data)

    @staticmethod
    def output() -> bytes:
        return ("EA_NATIVE_DLL_PROBE_V4\n" + "".join(
            f"CHECK {operation} python313.dll\nCHECK_RESULT {operation} python313.dll 0x00000000\n"
            for operation in ("file_read", "file_read_execute", "sec_image", "view_sec_image",
                              "sec_image_no_execute", "view_sec_image_no_execute", "actctx_core_manifest")) + "".join(
            f"LOAD {name}\nRESULT {name} 0x00000000\n" for name in probe.MODULES) + "DONE\n").encode()

    def test_output_reports_only_known_ordered_statuses_and_explicit_completion(self) -> None:
        result = probe.parse_output(self.output())
        self.assertTrue(result["entry"])
        self.assertTrue(result["complete"])
        self.assertEqual(list(probe.MODULES), [item["module"] for item in result["loads"]])
        self.assertEqual({"0x00000000"}, {item["win32_error"] for item in result["loads"]})
        self.assertEqual(list(probe.FILE_CHECKS), [item["operation"] for item in result["checks"]])
        self.assertEqual({"0x00000000"}, {item["win32_error"] for item in result["checks"]})
        prefix = self.output().split(b"LOAD ucrtbase.dll\n", 1)[0]
        partial = prefix + b"LOAD ucrtbase.dll\nRESULT ucrtbase.dll 0x00000005\nLOAD advapi32.dll\n"
        self.assertEqual("advapi32.dll", probe.parse_output(partial)["pending_module"])
        self.assertFalse(probe.parse_output(partial)["complete"])
        self.assertEqual({"entry": False, "complete": False, "checks": [], "loads": []}, probe.parse_output(b""))

    def test_file_failure_records_unattempted_mapping_without_fabricating_an_error(self) -> None:
        output = self.output().replace(b"file_read python313.dll 0x00000000", b"file_read python313.dll 0x00000005")
        output = output.replace(b"file_read_execute python313.dll 0x00000000", b"file_read_execute python313.dll 0x00000005")
        for operation in (b"sec_image", b"view_sec_image", b"sec_image_no_execute", b"view_sec_image_no_execute"):
            output = output.replace(operation + b" python313.dll 0x00000000", operation + b" python313.dll SKIPPED")
        result = probe.parse_output(output)
        self.assertEqual("0x00000005", result["checks"][0]["win32_error"])
        self.assertEqual([{"operation": operation, "module": "python313.dll", "not_attempted": True}
                          for operation in ("sec_image", "view_sec_image", "sec_image_no_execute",
                                            "view_sec_image_no_execute")], result["checks"][2:6])
        self.assertTrue(result["complete"])
        partial = b"EA_NATIVE_DLL_PROBE_V4\nCHECK file_read python313.dll\n"
        self.assertEqual("file_read", probe.parse_output(partial)["pending_check"])
        self.assertFalse(probe.parse_output(partial)["complete"])

    def test_each_mapping_requires_its_own_sufficient_read_or_execute_handle(self) -> None:
        for failed, skipped in ((b"file_read", b"sec_image_no_execute"), (b"file_read_execute", b"sec_image")):
            with self.subTest(failed=failed):
                output = self.output().replace(failed + b" python313.dll 0x00000000", failed + b" python313.dll 0x00000005")
                output = output.replace(skipped + b" python313.dll 0x00000000", skipped + b" python313.dll SKIPPED")
                output = output.replace(b"view_" + skipped + b" python313.dll 0x00000000", b"view_" + skipped + b" python313.dll SKIPPED")
                result = probe.parse_output(output)
                mapping = {item["operation"]: item for item in result["checks"][2:]}
                self.assertIs(mapping[skipped.decode()]["not_attempted"], True)
                other = "sec_image" if skipped == b"sec_image_no_execute" else "sec_image_no_execute"
                self.assertEqual("0x00000000", mapping[other]["win32_error"])
                with self.assertRaisesRegex(ValueError, "unrecognized native probe output"):
                    probe.parse_output(output.replace(skipped + b" python313.dll SKIPPED", skipped + b" python313.dll 0x00000000"))

    def test_view_result_requires_successful_section_and_distinguishes_map_failure(self) -> None:
        for section in (b"sec_image", b"sec_image_no_execute"):
            with self.subTest(section=section):
                prefix = b"CHECK_RESULT " + section + b" python313.dll "
                view_prefix = b"CHECK_RESULT view_" + section + b" python313.dll "
                denied = self.output().replace(view_prefix + b"0x00000000", view_prefix + b"0x00000005")
                result = {item["operation"]: item for item in probe.parse_output(denied)["checks"]}
                self.assertEqual("0x00000000", result[section.decode()]["win32_error"])
                self.assertEqual("0x00000005", result["view_" + section.decode()]["win32_error"])
                failed = self.output().replace(prefix + b"0x00000000", prefix + b"0x00000005")
                with self.assertRaisesRegex(ValueError, "unrecognized native probe output"):
                    probe.parse_output(failed)
                result = probe.parse_output(failed.replace(view_prefix + b"0x00000000", view_prefix + b"SKIPPED"))
                observed = {item["operation"]: item for item in result["checks"]}
                self.assertIs(observed["view_" + section.decode()]["not_attempted"], True)
                with self.assertRaisesRegex(ValueError, "unrecognized native probe output"):
                    probe.parse_output(self.output().replace(view_prefix + b"0x00000000", view_prefix + b"SKIPPED"))

    def test_view_partial_output_and_old_protocol_cannot_claim_completion(self) -> None:
        partial = self.output().split(b"CHECK_RESULT view_sec_image python313.dll", 1)[0]
        self.assertEqual("view_sec_image", probe.parse_output(partial)["pending_check"])
        self.assertFalse(probe.parse_output(partial)["complete"])
        for old in (b"EA_NATIVE_DLL_PROBE_V1", b"EA_NATIVE_DLL_PROBE_V2", b"EA_NATIVE_DLL_PROBE_V3"):
            with self.assertRaisesRegex(ValueError, "unrecognized native probe output"):
                probe.parse_output(self.output().replace(b"EA_NATIVE_DLL_PROBE_V4", old))

    def test_manifest_context_is_independent_numeric_observation_and_cannot_be_skipped(self) -> None:
        prefix = b"CHECK_RESULT actctx_core_manifest python313.dll "
        result = probe.parse_output(self.output().replace(prefix + b"0x00000000", prefix + b"0x00000005"))
        self.assertEqual({"operation": "actctx_core_manifest", "module": "python313.dll", "win32_error": "0x00000005"},
                         result["checks"][-1])
        self.assertTrue(result["complete"])
        partial = self.output().split(prefix, 1)[0]
        self.assertEqual("actctx_core_manifest", probe.parse_output(partial)["pending_check"])
        self.assertFalse(probe.parse_output(partial)["complete"])
        for changed in (prefix + b"SKIPPED", prefix + b"0x5", b"CHECK_RESULT actctx_core_manifest C:\\secret\\python313.dll 0x00000000"):
            with self.assertRaisesRegex(ValueError, "unrecognized native probe output"):
                probe.parse_output(self.output().replace(prefix + b"0x00000000", changed))

    def test_check_parser_rejects_missing_results_reordered_checks_and_false_mapping_receipts(self) -> None:
        bad = (self.output().replace(b"CHECK file_read", b"CHECK sec_image", 1),
               self.output().replace(b"CHECK_RESULT file_read python313.dll 0x00000000", b"CHECK_RESULT file_read python313.dll SKIPPED"),
               self.output().replace(b"CHECK_RESULT sec_image python313.dll 0x00000000", b"CHECK_RESULT sec_image python313.dll SKIPPED"),
               self.output().replace(b"file_read python313.dll 0x00000000", b"file_read python313.dll 0x00000005"),
               self.output().replace(b"CHECK_RESULT sec_image python313.dll", b"CHECK_RESULT sec_image C:\\secret\\python313.dll"),
               self.output().replace(b"EA_NATIVE_DLL_PROBE_V4", b"EA_NATIVE_DLL_PROBE_V1"))
        for value in bad:
            with self.subTest(size=len(value)), self.assertRaisesRegex(ValueError, "unrecognized native probe output"):
                probe.parse_output(value)

    def test_fixed_probe_covers_real_crt_imports_and_only_required_kernel32_apis(self) -> None:
        expected = tuple("api-ms-win-crt-" + name + "-l1-1-0.dll" for name in (
            "stdio", "environment", "string", "heap", "runtime", "locale", "convert", "math", "time",
            "process", "conio", "filesystem"))
        self.assertEqual(expected, probe.CRT_MODULES)
        self.assertEqual(("file_read", "file_read_execute", "sec_image", "view_sec_image",
                          "sec_image_no_execute", "view_sec_image_no_execute", "actctx_core_manifest"), probe.FILE_CHECKS)
        self.assertEqual({"GetStdHandle", "WriteFile", "LoadLibraryExW", "GetLastError", "FreeLibrary",
                          "ExitProcess", "GetModuleFileNameW", "CreateFileW", "CreateFileMappingW", "CloseHandle",
                          "MapViewOfFile", "UnmapViewOfFile", "CreateActCtxW", "ReleaseActCtx"},
                         probe.IMPORTS)
        self.assertEqual(1, probe.MODULES.count("python313.dll"))
        self.assertEqual("python313.dll", probe.MODULES[-1])
        self.assertLessEqual(len(self.output()), 4096)

    def test_output_rejects_raw_text_paths_duplicates_reordering_and_truncation(self) -> None:
        bad = (b"user@example.org secret-token C:\\private\n", self.output() + b"secret\n",
               self.output().replace(b"LOAD ucrtbase.dll", b"LOAD shell32.dll", 1),
               self.output().replace(b"0x00000000", b"0x0", 1),
               self.output()[:-1], self.output().replace(b"\n", b"\r\n"),
               b"EA_NATIVE_DLL_PROBE_V4\nRESULT ucrtbase.dll 0x00000000\n",
               b"EA_NATIVE_DLL_PROBE_V4\n" + b"X" * 4096)
        for value in bad:
            with self.subTest(size=len(value)):
                with self.assertRaisesRegex(ValueError, "unrecognized native probe output") as caught:
                    probe.parse_output(value)
                self.assertNotIn("secret", str(caught.exception))
                self.assertNotIn("user@", str(caught.exception))

    def test_actual_pe_gate_accepts_only_amd64_executable_and_kernel32_fixed_apis(self) -> None:
        probe.verify_pe(self.image())
        for offset, value in ((132, b"\x64\xaa"), (150, b"\x02\x20"),
                              (736, b"ADVAPI32.dll\0"), (770, b"CreateProcessW\0")):
            data = bytearray(self.image())
            data[offset:offset + len(value)] = value
            with self.assertRaisesRegex(ValueError, "invalid native probe PE"):
                probe.verify_pe(bytes(data))

    def test_pe_gate_rejects_delay_imports_bad_rvas_ordinals_and_missing_terminators(self) -> None:
        for offset, value in ((152 + 112 + 13 * 8, struct.pack("<II", 0x1000, 40)),
                              (152 + 112 + 9 * 8, struct.pack("<II", 0x1000, 40)),
                              (512, struct.pack("<I", 0x40000000)),
                              (592, struct.pack("<Q", 0x8000000000000012)),
                              (632, b"\xff" * 16), (532, b"\xff" * 20)):
            data = bytearray(self.image())
            data[offset:offset + len(value)] = value
            with self.assertRaisesRegex(ValueError, "invalid native probe PE"):
                probe.verify_pe(bytes(data))
        for value in (b"", self.image()[:500], self.image() + b"\0" * 1048576):
            with self.assertRaisesRegex(ValueError, "invalid native probe PE"):
                probe.verify_pe(value)

    def test_replacement_retains_full_runtime_assets_and_checks_copied_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "runtime"
            def original(path):
                path.mkdir()
                (path / "python.exe").write_bytes(b"old executable")
                (path / "python313.dll").write_bytes(b"retained DLL")
                return path / "python.exe"
            executable = probe.replace_runtime(destination, self.image(), original)
            self.assertEqual(self.image(), executable.read_bytes())
            self.assertEqual(b"retained DLL", (destination / "python313.dll").read_bytes())

    def test_replacement_rejects_reparse_or_different_leaf_and_tampered_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "outside.exe"
            outside.write_bytes(b"outside unchanged")
            def original(path):
                path.mkdir()
                (path / "python.exe").write_bytes(b"unmodified executable")
                return path / "python.exe"
            # Portable refusal seam; native reparse enforcement is separately
            # qualified by the real Windows Provider/ACL tests. No admin-only
            # symlink creation is needed by this hostile-input unit contract.
            with patch.object(probe.windows, "_reparse", side_effect=lambda path: path.name == "python.exe"):
                with self.assertRaisesRegex(ValueError, "invalid native probe runtime"):
                    probe.replace_runtime(base / "runtime", self.image(), original)
            self.assertEqual(b"unmodified executable", (base / "runtime/python.exe").read_bytes())
            self.assertEqual(b"outside unchanged", outside.read_bytes())
            with self.assertRaisesRegex(ValueError, "invalid native probe runtime"):
                probe.replace_runtime(base / "other", self.image(), lambda _: outside)
            def direct(path):
                path.mkdir()
                (path / "python.exe").write_bytes(b"old")
                return path / "python.exe"
            write = Path.write_bytes
            def corrupt(path, value):
                return write(path, value[:-1] + b"X")
            with patch.object(Path, "write_bytes", corrupt):
                with self.assertRaisesRegex(ValueError, "invalid native probe runtime"):
                    probe.replace_runtime(base / "tampered", self.image(), direct)

    def test_fixed_compiler_keeps_rustc_shim_dispatch_and_rejects_option_injection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            rustup = base / "rustup"
            rustup.write_bytes(b"unused tool seam")
            compiler = base / "rustc"
            compiler.write_bytes(b"unused shim seam")
            calls = []
            def run(command, **options):
                calls.append(command)
                self.assertEqual(str(compiler), command[0])
                self.assertEqual("+1.90.0", command[1])
                self.assertNotIn("CL", options["environment"])
                self.assertNotIn("RUSTC_WRAPPER", options["environment"])
                self.assertTrue(options["output_limit_bytes"] <= 65536)
                if command[-1] == "--version":
                    return 0, b"rustc 1.90.0 (1159e78c4 2025-09-14)\n"
                self.assertIn("link-arg=/NODEFAULTLIB", command)
                self.assertIn("link-arg=/ENTRY:probe_entry", command)
                self.assertEqual("x86_64-pc-windows-msvc", command[command.index("--target") + 1])
                Path(command[-1]).write_bytes(self.image())
                return 0, b"discard compiler output"
            with patch.object(probe.shutil, "which", return_value=str(compiler)), \
                 patch.object(probe, "run_bounded_windows", side_effect=run), \
                 patch.object(Path, "resolve", return_value=rustup), \
                 patch.dict(probe.os.environ, {"CL": "injected", "RUSTC_WRAPPER": "injected"}):
                self.assertEqual(self.image(), probe.build_probe(base))
            self.assertEqual(2, len(calls))

    def test_source_and_toolchain_mismatch_cannot_produce_an_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = base / "tests/fixtures"
            fixture.mkdir(parents=True)
            (fixture / "windows_startup_probe.rs").write_bytes(b"changed source")
            with patch.object(probe, "ROOT", base), patch.object(probe, "run_bounded_windows") as runner:
                with self.assertRaisesRegex(ValueError, "source_identity_mismatch"):
                    probe.build_probe(base)
                runner.assert_not_called()
            with patch.object(probe.shutil, "which", return_value=str(base / "rustc")), \
                 patch.object(probe, "run_bounded_windows", return_value=(0, b"rustc 1.89.0\n")) as runner:
                with self.assertRaisesRegex(ValueError, "version_mismatch"):
                    probe.build_probe(base)
                self.assertEqual(1, runner.call_count)
            self.assertFalse((base / "probe.exe").exists())

    def test_cli_cannot_accept_arbitrary_command_or_promote_diagnostic_to_qualification(self) -> None:
        output = io.StringIO()
        with patch.object(probe.sys, "argv", ["diagnose_windows_native.py", "private-user.exe"]), \
             patch.object(probe, "diagnose") as diagnose, redirect_stdout(output):
            self.assertEqual(1, probe.main())
            diagnose.assert_not_called()
        self.assertNotIn("private-user", output.getvalue())
        with patch.object(probe.windows, "capability", return_value={"supported": False, "reason": "not Windows"}):
            report = probe.diagnose()
        self.assertIs(report["qualified"], False)
        self.assertIs(report["diagnostic_only"], True)
        self.assertEqual("FILE_MAP_READ", report["image_view_access_flag"])
        self.assertEqual("PE_section_permissions", report["sec_image_view_protection"])
        self.assertIs(report["sec_image_desired_access_ignored"], True)
        self.assertIs(report["image_view_contents_accessed"], False)
        self.assertNotIn("image_views_mapped", report)
        self.assertEqual(2, report["core_manifest_resource_id"])
        self.assertEqual(8, report["activation_context_flags"])
        self.assertEqual(56, report["activation_context_struct_size"])
        self.assertIs(report["activation_context_activated"], False)

    def test_mapping_success_is_not_a_qualified_provider_or_an_acceptable_failed_control(self) -> None:
        report = {"diagnostic_only": True, "qualified": False, "baseline": probe._observe(0, self.output()),
                  "strict_lpac": {}, "detached_console": {}}
        for operation in (2, 3, 6):
            for value, expected in (("0x00000000", 0), ("0x00000005", 1)):
                with self.subTest(operation=operation, value=value):
                    report["baseline"] = probe._observe(0, self.output())
                    report["baseline"]["checks"][operation]["win32_error"] = value
                    output = io.StringIO()
                    with patch.object(probe.sys, "argv", ["diagnose_windows_native.py"]), \
                         patch.object(probe, "diagnose", return_value=report), redirect_stdout(output):
                        self.assertEqual(expected, probe.main())
                    self.assertIs(json.loads(output.getvalue())["qualified"], False)

    def test_tool_timeout_report_does_not_include_command_paths_or_captured_output(self) -> None:
        import subprocess
        output = io.StringIO()
        failure = subprocess.TimeoutExpired(["C:\\secret-folder\\probe.exe"], 10, output=b"user@example.org secret-token")
        with patch.object(probe.sys, "argv", ["diagnose_windows_native.py"]), \
             patch.object(probe, "diagnose", side_effect=failure), redirect_stdout(output):
            self.assertEqual(1, probe.main())
        self.assertEqual({"stage": "diagnostic", "error": "operation_timeout"},
                         json.loads(output.getvalue())["error"])
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("user@", output.getvalue())

    def test_merged_baseline_stream_cannot_claim_that_stderr_was_absent(self) -> None:
        self.assertNotIn("stderr_present", probe._observe(0, self.output()))
        self.assertIs(probe._observe(0, self.output(), b"")["stderr_present"], False)
        separated = probe._observe(0, self.output(), b"unrecognized secret error")
        self.assertIs(separated["stderr_present"], True)
        self.assertNotIn("secret", str(separated))

    def test_crlf_source_is_rejected_before_compiler_with_specific_identity_error(self) -> None:
        source = (ROOT / "tests/fixtures/windows_startup_probe.rs").read_bytes()
        self.assertEqual(probe.SOURCE_SHA256, hashlib.sha256(source).hexdigest())
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = base / "tests/fixtures/windows_startup_probe.rs"
            fixture.parent.mkdir(parents=True)
            fixture.write_bytes(source.replace(b"\n", b"\r\n"))
            with patch.object(probe, "ROOT", base), patch.object(probe, "run_bounded_windows") as runner:
                with self.assertRaises(probe.ProbeFailure) as caught:
                    probe.build_probe(base)
                self.assertEqual({"stage": "source", "error": "source_identity_mismatch"},
                                 probe._error_record(caught.exception))
                runner.assert_not_called()

    def test_fixture_lf_rule_preserves_bound_bytes_in_autocrlf_checkout(self) -> None:
        rule = (ROOT / ".gitattributes").read_text(encoding="utf-8").encode("utf-8")
        source = (ROOT / "tests/fixtures/windows_startup_probe.rs").read_bytes()
        for newline in (b"\n", b"\r\n"):
            with self.subTest(newline=newline), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                attributes_source = base / "attributes-source"
                attributes_source.write_bytes(rule.replace(b"\r\n", b"\n").replace(b"\n", newline))
                checkout_rule = attributes_source.read_text(encoding="utf-8").encode("utf-8")
                self.assertEqual(b"tests/fixtures/windows_startup_probe.rs text eol=lf\n", checkout_rule)
                fixture = base / "tests/fixtures/windows_startup_probe.rs"
                fixture.parent.mkdir(parents=True)
                fixture.write_bytes(source)
                (base / ".gitattributes").write_bytes(checkout_rule)
                def git(*args):
                    result = subprocess.run(["git", *args], cwd=base, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, timeout=10, check=False)
                    self.assertEqual(0, result.returncode, "isolated Git fixture operation failed")
                git("init", "-q")
                git("config", "core.autocrlf", "true")
                git("add", ".gitattributes", "tests/fixtures/windows_startup_probe.rs")
                fixture.unlink()
                git("checkout-index", "--", "tests/fixtures/windows_startup_probe.rs")
                checked_out = fixture.read_bytes()
                self.assertNotIn(b"\r", checked_out)
                self.assertEqual(probe.SOURCE_SHA256, hashlib.sha256(checked_out).hexdigest())

    def test_build_failures_identify_fixed_stage_without_raw_messages(self) -> None:
        cases = (("source_read_failed", "source", OSError(5, "secret-token C:\\private")),
                 ("version_mismatch", "toolchain", (0, b"secret-token unknown compiler")),
                 ("compiler_rejected", "build", (17, b"user@example.org C:\\private")),
                 ("image_contract_rejected", "pe", b"secret-token invalid image"))
        for error, stage, value in cases:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                def run(command, **_):
                    if command[-1] == "--version":
                        return value if stage == "toolchain" else (0, b"rustc 1.90.0 (1159e78c4 2025-09-14)\n")
                    if stage == "build":
                        return value
                    Path(command[-1]).write_bytes(value)
                    return 0, b"discard compiler output"
                with patch.object(probe.shutil, "which", return_value=str(base / "rustc")), \
                     patch.object(probe, "run_bounded_windows", side_effect=run):
                    if stage == "source":
                        with patch.object(probe, "_read_file", side_effect=value), \
                             self.assertRaises(probe.ProbeFailure) as caught:
                            probe.build_probe(base)
                    else:
                        with self.assertRaises(probe.ProbeFailure) as caught:
                            probe.build_probe(base)
                record = probe._error_record(caught.exception)
                self.assertEqual(stage, record["stage"])
                self.assertEqual(error, record["error"])
                self.assertNotIn("secret", json.dumps(record))
                self.assertNotIn("user@", json.dumps(record))
                self.assertNotIn("private", str(caught.exception))
                output = io.StringIO()
                with patch.object(probe.sys, "argv", ["diagnose_windows_native.py"]), \
                     patch.object(probe, "diagnose", side_effect=caught.exception), redirect_stdout(output):
                    self.assertEqual(1, probe.main())
                self.assertEqual(record, json.loads(output.getvalue())["error"])

    def test_fixed_native_probe_covers_pythoncore_system_dependencies_before_python(self) -> None:
        expected = ("version.dll", "ws2_32.dll", "bcrypt.dll", "api-ms-win-core-path-l1-1-0.dll")
        source = (ROOT / "tests/fixtures/windows_startup_probe.rs").read_text(encoding="utf-8")
        positions = []
        for name in expected:
            self.assertIn(name, probe.MODULES)
            call = f'load(handle, b"{name}", wide(b"{name}\\0").as_ptr(), 0x800);'
            self.assertIn(call, source)
            self.assertLess(probe.MODULES.index(name), probe.MODULES.index("python313.dll"))
            positions.append(source.index(call))
        self.assertEqual(sorted(positions), positions)
        self.assertLess(positions[-1], source.index('private_load(handle, b"python313.dll"'))
        self.assertEqual(probe.SOURCE_SHA256, hashlib.sha256(
            (ROOT / "tests/fixtures/windows_startup_probe.rs").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
