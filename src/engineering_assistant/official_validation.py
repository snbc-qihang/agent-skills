"""Run trusted official Codex validators for RC preflight."""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Mapping

try:
    import pwd
except ImportError:  # pragma: no cover - official Codex validators run on POSIX hosts
    pwd = None

from .validation import ValidationFailure


PY_YAML_REQUIREMENT = "pyyaml==6.0.2"
VALIDATOR_TIMEOUT_SECONDS = 120
MAX_VALIDATOR_OUTPUT_BYTES = 65_536
_UV_VERSION = re.compile(
    r"^uv [0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?"
    r"(?: \([0-9a-f]{7,64} [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9A-Za-z._-]+\))?$"
)


def _account_home() -> Path:
    """Resolve the OS account home without trusting the caller's HOME value."""
    if pwd is None:
        raise ValidationFailure(
            "official validator trust root requires a POSIX account database"
        )
    return Path(pwd.getpwuid(os.geteuid()).pw_dir).resolve()


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _trusted_file(path: Path | str, label: str, *, executable: bool = False) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ValidationFailure(f"missing trusted {label}: {resolved}")
    if executable and not os.access(resolved, os.X_OK):
        raise ValidationFailure(f"trusted {label} is not executable: {resolved}")
    return resolved


def _default_uv() -> Path:
    candidates = (
        _account_home() / ".local/bin/uv",
        Path("/opt/homebrew/bin/uv"),
        Path("/usr/local/bin/uv"),
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise ValidationFailure("missing trusted uv executable for official validators")


def _terminate(process: subprocess.Popen) -> None:
    if getattr(process, "_engineering_assistant_group_terminated", False):
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:  # pragma: no cover - release hosts are POSIX
            process.kill()
    except ProcessLookupError:
        pass
    finally:
        setattr(process, "_engineering_assistant_group_terminated", True)


def _run_streaming(
    command: list[str],
    *,
    label: str,
    repository_root: Path,
    environment: Mapping[str, str],
) -> str:
    try:
        process = subprocess.Popen(
            command,
            cwd=repository_root,
            env=dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        raise ValidationFailure(f"{label} could not run: {exc}") from exc
    output = bytearray()
    deadline = time.monotonic() + VALIDATOR_TIMEOUT_SECONDS
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate(process)
                process.wait()
                raise ValidationFailure(f"{label} timed out")
            for key, _mask in selector.select(min(remaining, 0.5)):
                chunk = os.read(key.fd, 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > MAX_VALIDATOR_OUTPUT_BYTES:
                    _terminate(process)
                    process.wait()
                    raise ValidationFailure(f"{label} exceeded the bounded output limit")
        returncode = process.wait()
    finally:
        selector.close()
        process.stdout.close()
        _terminate(process)
    rendered = bytes(output).decode("utf-8", errors="replace").strip()
    if returncode != 0:
        raise ValidationFailure(f"{label} failed:\n{rendered}")
    return rendered


def _run_bounded(
    command: list[str],
    *,
    label: str,
    repository_root: Path,
    environment: Mapping[str, str],
    runner: Callable[..., object] | None,
) -> str:
    if runner is None:
        return _run_streaming(
            command,
            label=label,
            repository_root=repository_root,
            environment=environment,
        )
    with tempfile.TemporaryFile(mode="w+b") as output:
        try:
            completed = runner(
                command,
                cwd=repository_root,
                env=dict(environment),
                stdout=output,
                stderr=subprocess.STDOUT,
                check=False,
                shell=False,
                timeout=VALIDATOR_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValidationFailure(f"{label} could not run: {exc}") from exc
        output.flush()
        output.seek(0)
        captured = output.read(MAX_VALIDATOR_OUTPUT_BYTES + 1)
        fake_output = getattr(completed, "stdout", b"") or b""
        if isinstance(fake_output, str):
            fake_output = fake_output.encode("utf-8", errors="replace")
        captured += fake_output
        if len(captured) > MAX_VALIDATOR_OUTPUT_BYTES:
            raise ValidationFailure(f"{label} exceeded the bounded output limit")
        rendered = captured.decode("utf-8", errors="replace").strip()
        if getattr(completed, "returncode", None) != 0:
            raise ValidationFailure(f"{label} failed:\n{rendered}")
        return rendered


def _validator_environment(cache_dir: Path) -> dict[str, str]:
    allowed = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "SSL_CERT_DIR",
            "SSL_CERT_FILE",
            "LANG",
            "LC_ALL",
            "TMPDIR",
        }
    }
    allowed["HOME"] = str(_account_home())
    allowed["UV_CACHE_DIR"] = str(cache_dir)
    return allowed


def validate_with_official_tools(
    repository_root: Path | str,
    codex_package: Path | str | None = None,
    *,
    validate_skills: bool = True,
    validate_plugin: bool = True,
    quick_validate_path: Path | str | None = None,
    plugin_validate_path: Path | str | None = None,
    uv_executable: Path | str | None = None,
    uv_cache_dir: Path | str | None = None,
    runner: Callable[..., object] | None = None,
) -> dict:
    if not validate_skills and not validate_plugin:
        raise ValidationFailure("official validation must select at least one gate")
    repository = Path(repository_root).resolve()
    package = Path(codex_package).resolve() if codex_package is not None else None
    if validate_plugin and (package is None or not package.is_dir()):
        raise ValidationFailure("official plugin validation requires a Codex package")

    skills = sorted(
        path.parent
        for path in (repository / "skills").glob("*/SKILL.md")
        if path.is_file()
    )
    if validate_skills and not skills:
        raise ValidationFailure("no public skills found for official validation")

    codex_system = _account_home() / ".codex/skills/.system"
    quick_validate = (
        _trusted_file(
            quick_validate_path
            or codex_system / "skill-creator/scripts/quick_validate.py",
            "official quick_validate.py",
        )
        if validate_skills
        else None
    )
    plugin_validate = (
        _trusted_file(
            plugin_validate_path
            or codex_system / "plugin-creator/scripts/validate_plugin.py",
            "official plugin validator",
        )
        if validate_plugin
        else None
    )
    uv = _trusted_file(
        uv_executable or _default_uv(),
        "uv executable",
        executable=True,
    )

    temporary_cache: tempfile.TemporaryDirectory[str] | None = None
    if uv_cache_dir is None:
        temporary_cache = tempfile.TemporaryDirectory(
            prefix="engineering-assistant-validator-cache-"
        )
        cache_dir = Path(temporary_cache.name).resolve()
    else:
        cache_dir = Path(uv_cache_dir).expanduser().resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        environment = _validator_environment(cache_dir)
        version = _run_bounded(
            [str(uv), "--version"],
            label="trusted uv identity check",
            repository_root=repository,
            environment=environment,
            runner=runner,
        )
        if _UV_VERSION.fullmatch(version) is None:
            raise ValidationFailure(f"trusted uv identity check returned {version!r}")
        prefix = [
            str(uv),
            "run",
            "--no-project",
            "--with",
            PY_YAML_REQUIREMENT,
            "python",
        ]

        if quick_validate is not None:
            for skill in skills:
                _run_bounded(
                    [*prefix, str(quick_validate), str(skill)],
                    label=f"official quick_validate for {skill.name}",
                    repository_root=repository,
                    environment=environment,
                    runner=runner,
                )
        payload_digest = None
        if plugin_validate is not None and package is not None:
            _run_bounded(
                [*prefix, str(plugin_validate), str(package)],
                label="official plugin validator",
                repository_root=repository,
                environment=environment,
                runner=runner,
            )
            manifest = json.loads(
                (package / "package-manifest.json").read_text(encoding="utf-8")
            )
            payload_digest = manifest.get("payload_digest")
            if not isinstance(payload_digest, str) or not payload_digest.startswith(
                "sha256:"
            ):
                raise ValidationFailure(
                    "officially validated Codex package has no payload digest"
                )
        return {
            "status": "passed",
            "skill_count": len(skills) if validate_skills else 0,
            "quick_validate": "passed" if validate_skills else "not_run",
            "codex_plugin_validate": "passed" if validate_plugin else "not_run",
            "codex_payload_digest": payload_digest,
            "validator_dependency": PY_YAML_REQUIREMENT,
            "quick_validate_digest": (
                _sha256(quick_validate) if quick_validate is not None else None
            ),
            "plugin_validate_digest": (
                _sha256(plugin_validate) if plugin_validate is not None else None
            ),
        }
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationFailure(f"official validation artifact is invalid: {exc}") from exc
    finally:
        if temporary_cache is not None:
            temporary_cache.cleanup()
