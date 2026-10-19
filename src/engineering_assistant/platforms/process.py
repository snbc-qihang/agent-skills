"""Bounded native process execution and installer tool discovery."""
from __future__ import annotations

import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping

from ..runtime.validation import ValidationFailure

def _account_home() -> Path:
    """Resolve the portable user home; validator trust comes from pinned hashes."""
    return Path.home().resolve()

def _trusted_file(path: Path | str, label: str, *, executable: bool = False) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ValidationFailure(f"missing trusted {label}: {resolved}")
    if executable and not os.access(resolved, os.X_OK):
        raise ValidationFailure(f"trusted {label} is not executable: {resolved}")
    return resolved


def _default_uv() -> Path:
    configured = os.environ.get("ENGINEERING_ASSISTANT_UV")
    if configured:
        return _trusted_file(configured, "configured uv executable", executable=True)
    discovered = shutil.which("uv")
    if discovered:
        return _trusted_file(discovered, "uv executable from PATH", executable=True)
    name = "uv.exe" if sys.platform == "win32" else "uv"
    candidates = [
        _account_home() / ".local/bin" / name,
        _account_home() / ".cargo/bin" / name,
    ]
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", str(_account_home() / "AppData/Local")))
        candidates.append(local / "uv/bin/uv.exe")
    else:
        candidates.extend((Path("/opt/homebrew/bin/uv"), Path("/usr/local/bin/uv"), Path("/usr/bin/uv")))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise ValidationFailure("缺少 uv，请安装 uv 或设置 ENGINEERING_ASSISTANT_UV")


def _terminate(process: subprocess.Popen) -> None:
    if getattr(process, "_engineering_assistant_group_terminated", False):
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        setattr(process, "_engineering_assistant_group_terminated", True)


def run_streaming(
    command: list[str],
    *,
    label: str,
    repository_root: Path,
    environment: Mapping[str, str],
    timeout_seconds: float = 120,
    output_limit_bytes: int = 65_536,
) -> str:
    if sys.platform == "win32":
        from .windows_process import run_bounded_windows

        try:
            returncode, captured = run_bounded_windows(
                command, cwd=repository_root, environment=environment,
                timeout_seconds=timeout_seconds,
                output_limit_bytes=output_limit_bytes,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValidationFailure(f"{label} timed out") from exc
        except OSError as exc:
            raise ValidationFailure(f"{label} could not run: {exc}") from exc
        rendered = captured.decode("utf-8", errors="replace").strip()
        if returncode != 0:
            raise ValidationFailure(f"{label} failed:\n{rendered}")
        return rendered
    try:
        process = subprocess.Popen(
            command, cwd=repository_root, env=dict(environment),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            shell=False, start_new_session=True,
        )
    except OSError as exc:
        raise ValidationFailure(f"{label} could not run: {exc}") from exc
    output = bytearray()
    deadline = time.monotonic() + timeout_seconds
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValidationFailure(f"{label} timed out")
            for key, _mask in selector.select(min(remaining, 0.5)):
                chunk = os.read(key.fd, 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > output_limit_bytes:
                    raise ValidationFailure(f"{label} exceeded the bounded output limit")
        try:
            returncode = process.wait(timeout=max(deadline - time.monotonic(), 0.001))
        except subprocess.TimeoutExpired as exc:
            raise ValidationFailure(f"{label} timed out") from exc
    finally:
        selector.close()
        _terminate(process)
        process.wait()
        process.stdout.close()
    rendered = bytes(output).decode("utf-8", errors="replace").strip()
    if returncode != 0:
        raise ValidationFailure(f"{label} failed:\n{rendered}")
    return rendered
