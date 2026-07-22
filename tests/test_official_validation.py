from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.official_validation import (  # noqa: E402
    MAX_VALIDATOR_OUTPUT_BYTES,
    PY_YAML_REQUIREMENT,
    _run_streaming,
    validate_with_official_tools,
)
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class OfficialValidationTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, dict[str, Path]]:
        repository = root / "repository"
        skill = repository / "skills/research"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: research\ndescription: test\n---\n",
            encoding="utf-8",
        )
        package = root / "codex-package"
        (package / ".codex-plugin").mkdir(parents=True)
        (package / ".codex-plugin/plugin.json").write_text("{}\n", encoding="utf-8")
        (package / "package-manifest.json").write_text(
            '{"payload_digest":"sha256:' + "a" * 64 + '"}\n',
            encoding="utf-8",
        )
        quick = root / "quick_validate.py"
        plugin = root / "validate_plugin.py"
        uv = root / "uv"
        for path in (quick, plugin, uv):
            path.write_text("fixture\n", encoding="utf-8")
        uv.chmod(0o755)
        return package, {
            "quick_validate_path": quick,
            "plugin_validate_path": plugin,
            "uv_executable": uv,
            "uv_cache_dir": root / "uv-cache",
        }

    def test_all_public_skills_and_codex_package_use_pinned_official_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, tools = self.fixture(root)
            calls = []

            def runner(command, **kwargs):
                calls.append((command, kwargs))
                stdout = "uv 0.8.0\n" if command[1:] == ["--version"] else "passed\n"
                return SimpleNamespace(returncode=0, stdout=stdout)

            report = validate_with_official_tools(
                root / "repository",
                package,
                runner=runner,
                **tools,
            )

        self.assertEqual("passed", report["status"])
        self.assertEqual(1, report["skill_count"])
        self.assertEqual(3, len(calls))
        self.assertEqual([str(tools["uv_executable"].resolve()), "--version"], calls[0][0])
        for command, kwargs in calls[1:]:
            self.assertEqual(
                ["run", "--no-project", "--with", PY_YAML_REQUIREMENT],
                command[1:5],
            )
            self.assertFalse(kwargs.get("shell", False))
            self.assertTrue(kwargs["check"] is False)
            self.assertEqual(
                str(tools["uv_cache_dir"].resolve()),
                kwargs["env"]["UV_CACHE_DIR"],
            )
        self.assertEqual(
            str((root / "repository/skills/research").resolve()),
            calls[1][0][-1],
        )
        self.assertEqual(str(package.resolve()), calls[2][0][-1])
        self.assertEqual("sha256:" + "a" * 64, report["codex_payload_digest"])

    def test_official_validator_failure_is_a_hard_preflight_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, tools = self.fixture(root)
            call_count = 0

            def runner(command, **_kwargs):
                nonlocal call_count
                call_count += 1
                if command[1:] == ["--version"]:
                    return SimpleNamespace(returncode=0, stdout="uv 0.8.0\n")
                return SimpleNamespace(returncode=1, stdout="invalid skill")

            with self.assertRaisesRegex(ValidationFailure, "official quick_validate"):
                validate_with_official_tools(
                    root / "repository",
                    package,
                    runner=runner,
                    **tools,
                )

    def test_missing_official_validator_never_soft_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, tools = self.fixture(root)
            tools["plugin_validate_path"].unlink()

            with self.assertRaisesRegex(ValidationFailure, "official plugin validator"):
                validate_with_official_tools(
                    root / "repository",
                    package,
                    runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="uv 0.8.0"),
                    **tools,
                )

    def test_validator_output_is_hard_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, tools = self.fixture(root)

            with self.assertRaisesRegex(ValidationFailure, "bounded output"):
                validate_with_official_tools(
                    root / "repository",
                    package,
                    runner=lambda *_args, **_kwargs: SimpleNamespace(
                        returncode=0,
                        stdout="x" * (MAX_VALIDATOR_OUTPUT_BYTES + 1),
                    ),
                    **tools,
                )

    def test_trusted_uv_identity_accepts_official_build_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, tools = self.fixture(root)

            report = validate_with_official_tools(
                root / "repository",
                package,
                runner=lambda command, **_kwargs: SimpleNamespace(
                    returncode=0,
                    stdout=(
                        "uv 0.11.7 (9d177269e 2026-04-15 aarch64-apple-darwin)\n"
                        if command[1:] == ["--version"]
                        else "passed\n"
                    ),
                ),
                **tools,
            )

        self.assertEqual("passed", report["status"])

    def test_trusted_uv_identity_accepts_linux_target_only_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, tools = self.fixture(root)

            report = validate_with_official_tools(
                root / "repository",
                package,
                runner=lambda command, **_kwargs: SimpleNamespace(
                    returncode=0,
                    stdout=(
                        "uv 0.11.7 (x86_64-unknown-linux-gnu)\n"
                        if command[1:] == ["--version"]
                        else "passed\n"
                    ),
                ),
                **tools,
            )

        self.assertEqual("passed", report["status"])

    def test_trusted_uv_identity_rejects_unstructured_parenthetical_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, tools = self.fixture(root)

            with self.assertRaisesRegex(ValidationFailure, "trusted uv identity check"):
                validate_with_official_tools(
                    root / "repository",
                    package,
                    runner=lambda command, **_kwargs: SimpleNamespace(
                        returncode=0,
                        stdout=(
                            "uv 0.11.7 (unexpected)\n"
                            if command[1:] == ["--version"]
                            else "passed\n"
                        ),
                    ),
                    **tools,
                )

    def test_streaming_output_limit_does_not_limit_validator_file_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = _run_streaming(
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('cache.bin').write_bytes(b'x' * 131072); print('passed')",
                ],
                label="fixture validator",
                repository_root=root,
                environment={},
            )

            self.assertEqual("passed", output)
            self.assertEqual(131072, (root / "cache.bin").stat().st_size)

    def test_streaming_runner_terminates_excessive_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValidationFailure, "bounded output"):
                _run_streaming(
                    [
                        sys.executable,
                        "-c",
                        f"import sys; sys.stdout.write('x' * {MAX_VALIDATOR_OUTPUT_BYTES + 1})",
                    ],
                    label="fixture validator",
                    repository_root=Path(temporary),
                    environment={},
                )

    def test_caller_home_cannot_replace_default_official_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, _tools = self.fixture(root)
            trusted_home = root / "trusted-home"
            quick = trusted_home / ".codex/skills/.system/skill-creator/scripts/quick_validate.py"
            plugin = trusted_home / ".codex/skills/.system/plugin-creator/scripts/validate_plugin.py"
            uv = trusted_home / ".local/bin/uv"
            for path in (quick, plugin, uv):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("trusted fixture\n", encoding="utf-8")
            uv.chmod(0o755)
            calls = []

            def runner(command, **_kwargs):
                calls.append(command)
                return SimpleNamespace(
                    returncode=0,
                    stdout="uv 0.8.0\n" if command[1:] == ["--version"] else "passed\n",
                )

            with mock.patch.dict("os.environ", {"HOME": str(root / "attacker-home")}), mock.patch(
                "engineering_assistant.official_validation._account_home",
                return_value=trusted_home,
            ):
                report = validate_with_official_tools(
                    root / "repository",
                    package,
                    runner=runner,
                    uv_cache_dir=root / "cache",
                )

        self.assertEqual("passed", report["status"])
        self.assertEqual(str(uv.resolve()), calls[0][0])
        self.assertEqual(str(quick.resolve()), calls[1][-2])
        self.assertEqual(str(plugin.resolve()), calls[2][-2])

    @unittest.skipUnless(os.name == "posix", "process-group cleanup is POSIX-specific")
    def test_timeout_cleans_child_after_validator_parent_exits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = (
                "import pathlib, subprocess, sys; "
                "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
                "pathlib.Path('child.pid').write_text(str(child.pid))"
            )
            with mock.patch(
                "engineering_assistant.official_validation.VALIDATOR_TIMEOUT_SECONDS",
                0.2,
            ):
                with self.assertRaisesRegex(ValidationFailure, "timed out"):
                    _run_streaming(
                        [sys.executable, "-c", script],
                        label="child-leak fixture",
                        repository_root=root,
                        environment={},
                    )
            child_pid = int((root / "child.pid").read_text(encoding="utf-8"))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                self.fail("validator child process survived timeout cleanup")


if __name__ == "__main__":
    unittest.main()
