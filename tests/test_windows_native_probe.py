from __future__ import annotations

import importlib.util
import io
import struct
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
        struct.pack_into("<IIIII", data, 512, 0x1050, 0, 0, 0x10A0, 0x1050)
        data[672:685] = b"KERNEL32.dll\0"
        cursor = 704
        for index, name in enumerate(sorted(probe.IMPORTS)):
            struct.pack_into("<Q", data, 592 + index * 8, cursor - 512 + 0x1000)
            value = b"\0\0" + name.encode("ascii") + b"\0"
            data[cursor:cursor + len(value)] = value
            cursor += len(value)
        return bytes(data)

    @staticmethod
    def output() -> bytes:
        return ("EA_NATIVE_DLL_PROBE_V1\n" + "".join(
            f"LOAD {name}\nRESULT {name} 0x00000000\n" for name in probe.MODULES) + "DONE\n").encode()

    def test_output_reports_only_known_ordered_statuses_and_explicit_completion(self) -> None:
        result = probe.parse_output(self.output())
        self.assertTrue(result["entry"])
        self.assertTrue(result["complete"])
        self.assertEqual(list(probe.MODULES), [item["module"] for item in result["loads"]])
        self.assertEqual({"0x00000000"}, {item["win32_error"] for item in result["loads"]})
        partial = b"EA_NATIVE_DLL_PROBE_V1\nLOAD ucrtbase.dll\nRESULT ucrtbase.dll 0x00000005\nLOAD advapi32.dll\n"
        self.assertEqual("advapi32.dll", probe.parse_output(partial)["pending_module"])
        self.assertFalse(probe.parse_output(partial)["complete"])
        self.assertEqual({"entry": False, "complete": False, "loads": []}, probe.parse_output(b""))

    def test_output_rejects_raw_text_paths_duplicates_reordering_and_truncation(self) -> None:
        bad = (b"user@example.org secret-token C:\\private\n", self.output() + b"secret\n",
               self.output().replace(b"LOAD ucrtbase.dll", b"LOAD shell32.dll", 1),
               self.output().replace(b"0x00000000", b"0x0", 1),
               self.output()[:-1], self.output().replace(b"\n", b"\r\n"),
               b"EA_NATIVE_DLL_PROBE_V1\nRESULT ucrtbase.dll 0x00000000\n",
               b"EA_NATIVE_DLL_PROBE_V1\n" + b"X" * 4096)
        for value in bad:
            with self.subTest(size=len(value)):
                with self.assertRaisesRegex(ValueError, "unrecognized native probe output") as caught:
                    probe.parse_output(value)
                self.assertNotIn("secret", str(caught.exception))
                self.assertNotIn("user@", str(caught.exception))

    def test_actual_pe_gate_accepts_only_amd64_executable_and_kernel32_fixed_apis(self) -> None:
        probe.verify_pe(self.image())
        for offset, value in ((132, b"\x64\xaa"), (150, b"\x02\x20"),
                              (672, b"ADVAPI32.dll\0"), (706, b"CreateProcessW\0")):
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
                with self.assertRaisesRegex(ValueError, "invalid native probe source"):
                    probe.build_probe(base)
                runner.assert_not_called()
            with patch.object(probe.shutil, "which", return_value=str(base / "rustc")), \
                 patch.object(probe, "run_bounded_windows", return_value=(0, b"rustc 1.89.0\n")) as runner:
                with self.assertRaisesRegex(ValueError, "fixed Rust 1.90.0"):
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

    def test_tool_timeout_report_does_not_include_command_paths_or_captured_output(self) -> None:
        import subprocess
        output = io.StringIO()
        failure = subprocess.TimeoutExpired(["C:\\secret-folder\\probe.exe"], 10, output=b"user@example.org secret-token")
        with patch.object(probe.sys, "argv", ["diagnose_windows_native.py"]), \
             patch.object(probe, "diagnose", side_effect=failure), redirect_stdout(output):
            self.assertEqual(1, probe.main())
        self.assertIn("TimeoutExpired", output.getvalue())
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("user@", output.getvalue())

    def test_merged_baseline_stream_cannot_claim_that_stderr_was_absent(self) -> None:
        self.assertNotIn("stderr_present", probe._observe(0, self.output()))
        self.assertIs(probe._observe(0, self.output(), b"")["stderr_present"], False)
        separated = probe._observe(0, self.output(), b"unrecognized secret error")
        self.assertIs(separated["stderr_present"], True)
        self.assertNotIn("secret", str(separated))


if __name__ == "__main__":
    unittest.main()
