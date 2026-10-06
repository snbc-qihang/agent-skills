from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
import os
import socket
import ssl
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.error import HTTPError, URLError


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
    def test_default_uv_uses_path_without_a_codex_account_directory(self) -> None:
        from engineering_assistant.official_validation import _default_uv

        with tempfile.TemporaryDirectory() as temporary:
            uv = Path(temporary).resolve() / ("uv.exe" if os.name == "nt" else "uv")
            uv.write_text("fixture\n", encoding="utf-8")
            uv.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": str(uv.parent)}, clear=True), mock.patch(
                "engineering_assistant.official_validation._account_home",
                return_value=Path(temporary) / "account-without-uv",
            ), mock.patch.object(
                Path, "is_file", autospec=True,
                side_effect=lambda candidate: candidate == uv,
            ), mock.patch(
                "engineering_assistant.official_validation.os.access",
                side_effect=lambda candidate, _mode: Path(candidate) == uv,
            ):
                self.assertEqual(uv.resolve(), _default_uv())

    def source(self, payload: bytes) -> dict[str, str]:
        return {
            "url": "https://raw.githubusercontent.com/openai/skills/" + "a" * 40 + "/quick_validate.py",
            "revision": "a" * 40,
            "filename": "quick_validate.py",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def test_verified_cache_bootstraps_without_codex_and_reuses_offline(self) -> None:
        from engineering_assistant.official_validation import _open_cache, _validator_bytes

        payload = b"print('official')\n"
        with tempfile.TemporaryDirectory() as temporary:
            cache = _open_cache(Path(temporary) / "cache", ROOT)
            try:
                with mock.patch(
                    "engineering_assistant.official_validation._download_validator", return_value=payload
                ) as download:
                    self.assertEqual(payload, _validator_bytes(self.source(payload), cache))
                    self.assertEqual(payload, _validator_bytes(self.source(payload), cache))
                    self.assertEqual(1, download.call_count)
            finally:
                cache.close()

    def test_invalid_download_preserves_corrupt_old_cache(self) -> None:
        from engineering_assistant.official_validation import _open_cache, _validator_bytes

        payload = b"print('official')\n"
        source = self.source(payload)
        with tempfile.TemporaryDirectory() as temporary:
            cache = _open_cache(Path(temporary) / "cache", ROOT)
            try:
                cache.write_bytes_exclusive(b"old-corrupt", source["sha256"], source["filename"])
                with mock.patch(
                    "engineering_assistant.official_validation._download_validator", return_value=b"wrong"
                ) as download:
                    with self.assertRaisesRegex(ValidationFailure, "digest"):
                        _validator_bytes(source, cache)
                download.assert_called_once()
                self.assertEqual(b"old-corrupt", cache.read_bytes_limited(64, source["sha256"], source["filename"]))
            finally:
                cache.close()

    def test_symlink_cache_and_repository_cache_are_rejected(self) -> None:
        from engineering_assistant.official_validation import _open_cache

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            outside = root / "outside"
            outside.mkdir()
            linked = root / "cache"
            linked.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValidationFailure, "symlink|reparse"):
                _open_cache(linked, ROOT)
            with self.assertRaisesRegex(ValidationFailure, "outside"):
                _open_cache(ROOT / "validator-cache", ROOT)
            self.assertEqual([], list(outside.iterdir()))

    def test_download_is_bounded_and_redirects_never_run(self) -> None:
        from engineering_assistant.official_validation import _download_validator, MAX_VALIDATOR_SCRIPT_BYTES

        url = self.source(b"x")["url"]
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = url
        response.read.return_value = b"x" * (MAX_VALIDATOR_SCRIPT_BYTES + 1)
        with mock.patch("engineering_assistant.official_validation.urlopen", return_value=response) as download:
            with self.assertRaisesRegex(ValidationFailure, "bounded|size"):
                _download_validator(url)
        download.assert_called_once()
        response.read.assert_called_once_with(MAX_VALIDATOR_SCRIPT_BYTES + 1)
        response.geturl.return_value = "https://example.com/replacement.py"
        with mock.patch("engineering_assistant.official_validation.urlopen", return_value=response) as download:
            with self.assertRaisesRegex(ValidationFailure, "redirect"):
                _download_validator(url)
        download.assert_called_once()

    def test_transient_download_failures_retry_then_verify_and_reuse_cache(self) -> None:
        from engineering_assistant.official_validation import _open_cache, _validator_bytes

        payload = b"print('official')\n"
        source = self.source(payload)
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = source["url"]
        response.read.return_value = payload
        failures = (
            URLError(socket.gaierror(8, "temporary DNS resolution failure")),
            URLError(TimeoutError("temporary connection timeout")),
            HTTPError(source["url"], 503, "temporarily unavailable", {}, None),
        )
        for failure in failures:
            with self.subTest(error=type(failure.reason).__name__), tempfile.TemporaryDirectory() as temporary:
                cache = _open_cache(Path(temporary) / "cache", ROOT)
                try:
                    with mock.patch("engineering_assistant.official_validation.urlopen", side_effect=[failure, response]) as download, mock.patch(
                        "engineering_assistant.official_validation.time.sleep"
                    ) as sleep:
                        self.assertEqual(payload, _validator_bytes(source, cache))
                        self.assertEqual(payload, _validator_bytes(source, cache))
                    self.assertEqual(2, download.call_count)
                    for call in download.call_args_list:
                        self.assertEqual(source["url"], call.args[0].full_url)
                        self.assertEqual({"timeout": 30}, call.kwargs)
                    sleep.assert_called_once_with(1)
                finally:
                    cache.close()

    def test_download_retry_budget_exhaustion_keeps_cache_unpublished(self) -> None:
        from engineering_assistant.official_validation import _open_cache, _validator_bytes

        source = self.source(b"official")
        failure = URLError(socket.gaierror(8, "temporary DNS resolution failure"))
        with tempfile.TemporaryDirectory() as temporary:
            cache = _open_cache(Path(temporary) / "cache", ROOT)
            try:
                with mock.patch("engineering_assistant.official_validation.urlopen", side_effect=failure) as download, mock.patch(
                    "engineering_assistant.official_validation.time.sleep"
                ) as sleep:
                    with self.assertRaisesRegex(ValidationFailure, "failed after 3 attempt") as raised:
                        _validator_bytes(source, cache)
                self.assertEqual(3, download.call_count)
                self.assertIs(failure, raised.exception.__cause__)
                self.assertEqual([mock.call(1), mock.call(2)], sleep.call_args_list)
                self.assertEqual([], list(cache.path(source["sha256"]).iterdir()))
            finally:
                cache.close()

    def test_download_trust_failures_never_retry(self) -> None:
        from engineering_assistant.official_validation import _download_validator

        url = self.source(b"official")["url"]
        failures = (
            URLError(ssl.SSLCertVerificationError("untrusted certificate")),
            HTTPError(url, 403, "forbidden", {}, None),
            HTTPError(url, 404, "missing pinned revision", {}, None),
        )
        for failure in failures:
            with self.subTest(error=type(failure).__name__), mock.patch(
                "engineering_assistant.official_validation.urlopen", side_effect=failure
            ) as download, mock.patch("engineering_assistant.official_validation.time.sleep") as sleep:
                with self.assertRaisesRegex(ValidationFailure, "download failed"):
                    _download_validator(url)
                download.assert_called_once()
                sleep.assert_not_called()

    def test_cache_leaf_symlink_is_rejected_without_download(self) -> None:
        from engineering_assistant.official_validation import _open_cache, _validator_bytes

        payload = b"print('official')\n"
        source = self.source(payload)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            cache = _open_cache(root / "cache", ROOT)
            try:
                cache.ensure_directory(source["sha256"])
                outside = root / "outside.py"
                outside.write_bytes(payload)
                cache.path(source["sha256"]).joinpath(source["filename"]).symlink_to(outside)
                with mock.patch("engineering_assistant.official_validation._download_validator") as download:
                    with self.assertRaises(ValidationFailure):
                        _validator_bytes(source, cache)
                download.assert_not_called()
                self.assertEqual(payload, outside.read_bytes())
            finally:
                cache.close()

    def test_failed_cache_write_removes_partial_staging(self) -> None:
        from engineering_assistant.artifact_io import ArtifactIO
        from engineering_assistant.official_validation import _open_cache, _validator_bytes

        payload = b"print('official')\n"
        source = self.source(payload)
        with tempfile.TemporaryDirectory() as temporary:
            cache = _open_cache(Path(temporary) / "cache", ROOT)
            original = ArtifactIO.write_bytes_exclusive

            def interrupted(instance, content, *parts, **kwargs):
                original(instance, content, *parts, **kwargs)
                raise OSError("simulated interrupted staging write")

            try:
                with mock.patch("engineering_assistant.official_validation._download_validator", return_value=payload), mock.patch.object(
                    ArtifactIO, "write_bytes_exclusive", interrupted
                ):
                    with self.assertRaisesRegex(OSError, "interrupted"):
                        _validator_bytes(source, cache)
                with cache.open_directory(source["sha256"]):
                    self.assertEqual([".artifact.lock"], [path.name for path in cache.path(source["sha256"]).iterdir()])
            finally:
                cache.close()

    def test_concurrent_downloads_publish_one_intact_validator(self) -> None:
        from engineering_assistant.official_validation import _open_cache, _validator_bytes

        payload = b"print('official')\n"
        source = self.source(payload)
        with tempfile.TemporaryDirectory() as temporary:
            cache = _open_cache(Path(temporary) / "cache", ROOT)
            try:
                with mock.patch("engineering_assistant.official_validation._download_validator", return_value=payload):
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        outputs = list(pool.map(lambda _index: _validator_bytes(source, cache), range(8)))
                self.assertEqual([payload] * 8, outputs)
                self.assertEqual(payload, cache.read_bytes_limited(256, source["sha256"], source["filename"]))
                names = [path.name for path in cache.path(source["sha256"]).iterdir()]
                self.assertEqual({".artifact.lock", source["filename"]}, set(names))
            finally:
                cache.close()

    def test_uv_configuration_precedes_path(self) -> None:
        from engineering_assistant.official_validation import _default_uv

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            configured, discovered = root / "configured-uv", root / "path-uv"
            for path in (configured, discovered):
                path.write_text("fixture\n", encoding="utf-8")
                path.chmod(0o755)
            with mock.patch.dict(os.environ, {"ENGINEERING_ASSISTANT_UV": str(configured)}), mock.patch(
                "engineering_assistant.official_validation.shutil.which", return_value=str(discovered)
            ) as which:
                self.assertEqual(configured, _default_uv())
                which.assert_not_called()

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
                ["run", "--no-project", "--python", "3.13.13", "--managed-python", "--with", PY_YAML_REQUIREMENT],
                command[1:8],
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

    def test_caller_home_and_cache_swap_cannot_replace_execution_snapshot(self) -> None:
        from engineering_assistant.official_validation import OFFICIAL_VALIDATORS

        payload = b"print('official')\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package, tools = self.fixture(root)
            home = root / "attacker-home"
            attacker = home / ".codex/skills/.system/skill-creator/scripts/quick_validate.py"
            attacker.parent.mkdir(parents=True)
            attacker.write_bytes(b"print('attacker')\n")
            pins = {}
            for key, old in OFFICIAL_VALIDATORS.items():
                pins[key] = {**self.source(payload), "filename": old["filename"]}
            seen = []

            def runner(command, **_kwargs):
                if command[1:] == ["--version"]:
                    cached = root / "tools-cache" / pins["quick_validate"]["sha256"] / "quick_validate.py"
                    cached.write_bytes(b"changed-after-verification")
                    return SimpleNamespace(returncode=0, stdout="uv 0.8.0\n")
                path = Path(command[-2])
                seen.append(path)
                self.assertEqual(payload, path.read_bytes())
                self.assertNotIn(str(home), str(path))
                return SimpleNamespace(returncode=0, stdout="passed\n")

            with mock.patch.dict(os.environ, {"HOME": str(home)}), mock.patch(
                "engineering_assistant.official_validation.OFFICIAL_VALIDATORS", pins
            ), mock.patch(
                "engineering_assistant.official_validation._download_validator", return_value=payload
            ):
                report = validate_with_official_tools(
                    root / "repository", package, runner=runner,
                    uv_executable=tools["uv_executable"], uv_cache_dir=root / "uv-cache",
                    official_tools_cache_dir=root / "tools-cache",
                )
            self.assertEqual("passed", report["status"])
            self.assertEqual(2, len(seen))
            self.assertTrue(all(not path.exists() for path in seen))
            self.assertEqual("sha256:" + hashlib.sha256(payload).hexdigest(), report["quick_validate_digest"])

    def test_windows_output_uses_native_job_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch("engineering_assistant.official_validation.sys.platform", "win32"), mock.patch(
                "engineering_assistant.windows_process.run_bounded_windows", return_value=(0, b"passed\n")
            ) as run:
                result = _run_streaming(
                    [sys.executable, "-c", "print('passed')"], label="native fixture",
                    repository_root=Path(temporary), environment={},
                )
            self.assertEqual("passed", result)
            self.assertEqual(MAX_VALIDATOR_OUTPUT_BYTES, run.call_args.kwargs["output_limit_bytes"])

    def test_closed_stdout_does_not_escape_timeout(self) -> None:
        if os.name != "posix":
            self.skipTest("POSIX stdout descriptor fixture")
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch("engineering_assistant.official_validation.VALIDATOR_TIMEOUT_SECONDS", 0.2):
                with self.assertRaisesRegex(ValidationFailure, "timed out"):
                    _run_streaming(
                        [sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(30)"],
                        label="closed pipe fixture", repository_root=Path(temporary), environment={},
                    )

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
