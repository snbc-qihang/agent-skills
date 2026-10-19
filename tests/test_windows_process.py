from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.platforms.windows_process import run_bounded_windows  # noqa: E402


@unittest.skipUnless(sys.platform == "win32", "native Windows Job Object integration")
class WindowsProcessTests(unittest.TestCase):
    def run_process(self, command, cwd, *, timeout=5, limit=65536, input_data=None):
        environment = dict(os.environ)
        environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        return run_bounded_windows(
            command, cwd=cwd, environment=environment,
            timeout_seconds=timeout, output_limit_bytes=limit, input_data=input_data,
        )

    def test_unicode_arguments_and_space_paths_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ea windows ") as temporary:
            root = Path(temporary) / "中文 空格"
            root.mkdir()
            code, output = self.run_process(
                [sys.executable, "-c", "import sys; print(sys.argv[1])", '中文 arg "quoted"'], root
            )
            self.assertEqual(0, code)
            self.assertEqual('中文 arg "quoted"', output.decode("utf-8").strip())

    def test_bounded_stdin_reaches_eof_without_pipe_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            payload = b"x" * 1_048_576
            code, output = self.run_process(
                [sys.executable, "-c", "import sys; print(len(sys.stdin.buffer.read()))"],
                Path(temporary), input_data=payload,
            )
            self.assertEqual(0, code)
            self.assertEqual(b"1048576", output.strip())
            with self.assertRaisesRegex(ValueError, "bounded bytes"):
                self.run_process([sys.executable, "-c", "print('unexpected')"], Path(temporary), input_data=payload + b"x")

    def test_output_limit_terminates_the_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(OSError, "bounded output"):
                self.run_process(
                    [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x'*131072)"],
                    Path(temporary), limit=1024,
                )

    def test_timeout_terminates_parent_and_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sentinel = root / "child-survived"
            child = "import pathlib, time; time.sleep(1.5); pathlib.Path('child-survived').write_text('bad')"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); print('started',flush=True); time.sleep(30)"
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                self.run_process([sys.executable, "-c", parent, child], root, timeout=0.5)
            self.assertIn(b"started", raised.exception.output)
            time.sleep(1.6)
            self.assertFalse(sentinel.exists())

    def test_parent_exit_also_cleans_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = "import pathlib,time; time.sleep(1); pathlib.Path('child-survived').write_text('bad')"
            parent = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); print('passed',flush=True)"
            code, output = self.run_process([sys.executable, "-c", parent, child], root)
            self.assertEqual(0, code)
            self.assertIn(b"passed", output)
            time.sleep(1.2)
            self.assertFalse((root / "child-survived").exists())


if __name__ == "__main__":
    unittest.main()
