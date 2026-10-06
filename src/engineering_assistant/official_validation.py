"""Run pinned official Codex validators without depending on an Agent installation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import selectors
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .artifact_io import ArtifactIO, artifact_fs
from .validation import ValidationFailure


PY_YAML_REQUIREMENT = "pyyaml==6.0.2"
VALIDATOR_PYTHON_VERSION = "3.13.13"
VALIDATOR_TIMEOUT_SECONDS = 120
VALIDATOR_DOWNLOAD_ATTEMPTS = 3
VALIDATOR_DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_VALIDATOR_OUTPUT_BYTES = 65_536
MAX_VALIDATOR_SCRIPT_BYTES = 262_144
OFFICIAL_VALIDATORS = {
    "quick_validate": {
        "revision": "49f948faa9258a0c61caceaf225e179651397431",
        "url": "https://raw.githubusercontent.com/openai/skills/49f948faa9258a0c61caceaf225e179651397431/skills/.system/skill-creator/scripts/quick_validate.py",
        "sha256": "6cc9dc3199c935916cf6f73fcbbbb0e3bb1b58c8f5109fefa499978908164f51",
        "filename": "quick_validate.py",
    },
    "plugin_validate": {
        "revision": "963cda85aa2a4cfb85e52d771d22d9f3069951fa",
        "url": "https://raw.githubusercontent.com/openai/codex/963cda85aa2a4cfb85e52d771d22d9f3069951fa/codex-rs/skills/src/assets/samples/plugin-creator/scripts/validate_plugin.py",
        "sha256": "ebda00d55d7518b127f675f062fb5c6e7a1ffdc0a99df1a55ac594400d7d3228",
        "filename": "validate_plugin.py",
    },
}
_UV_VERSION = re.compile(
    r"^uv [0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?"
    r"(?: \((?:[0-9a-f]{7,64} [0-9]{4}-[0-9]{2}-[0-9]{2} )?"
    r"[0-9A-Za-z._]+(?:-[0-9A-Za-z._]+){2,}\))?$"
)


def _account_home() -> Path:
    """Resolve the portable user home; validator trust comes from pinned hashes."""
    return Path.home().resolve()


def _default_tools_cache() -> Path:
    configured = os.environ.get("ENGINEERING_ASSISTANT_VALIDATOR_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(_account_home() / "AppData/Local")))
    elif sys.platform == "darwin":
        base = _account_home() / "Library/Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", str(_account_home() / ".cache")))
    return base / "engineering-assistant/official-validators"


def _open_cache(path: Path, repository: Path) -> ArtifactIO:
    """Anchor cache creation below an existing directory, outside the author source."""
    requested = path.expanduser().absolute()
    resolved = requested.resolve()
    if resolved == repository or repository in resolved.parents:
        raise ValidationFailure("official validator cache must be outside the author repository")
    try:
        metadata = requested.lstat()
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValidationFailure("official validator cache contains a symlink or reparse point")
    anchor = requested.parent
    while not anchor.exists():
        anchor = anchor.parent
    metadata = anchor.lstat()
    if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
        raise ValidationFailure("official validator cache contains a symlink or reparse point")
    relative = requested.relative_to(anchor)
    anchor = anchor.resolve()
    cache = ArtifactIO(anchor, anchor / relative, lock_timeout_seconds=5)
    try:
        cache.ensure_directory()
    except BaseException:
        cache.close()
        raise
    return cache


def _download_validator(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "engineering-assistant-official-validator"})
    for attempt in range(VALIDATOR_DOWNLOAD_ATTEMPTS):
        try:
            with urlopen(request, timeout=VALIDATOR_DOWNLOAD_TIMEOUT_SECONDS) as response:
                if response.geturl() != url:
                    raise ValidationFailure("official validator download redirected away from its pinned source")
                payload = response.read(MAX_VALIDATOR_SCRIPT_BYTES + 1)
            if len(payload) > MAX_VALIDATOR_SCRIPT_BYTES:
                raise ValidationFailure("official validator download exceeded the bounded script size")
            return payload
        except (OSError, URLError) as exc:
            if isinstance(exc, HTTPError):
                transient = exc.code in {429, 500, 502, 503, 504}
                exc.close()
            else:
                reason = exc.reason if isinstance(exc, URLError) else exc
                transient = isinstance(reason, (socket.gaierror, TimeoutError, ConnectionError))
            if transient and attempt + 1 < VALIDATOR_DOWNLOAD_ATTEMPTS:
                time.sleep(attempt + 1)
                continue
            raise ValidationFailure(
                f"official validator download failed after {attempt + 1} attempt(s); "
                "retry with network access or a verified cache"
            ) from exc


def _validator_bytes(source: Mapping[str, str], cache: ArtifactIO) -> bytes:
    digest, filename = source["sha256"], source["filename"]
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None or re.fullmatch(r"[a-z_]+\.py", filename) is None:
        raise ValidationFailure("invalid pinned official validator descriptor")
    cache.ensure_directory(digest)

    def cached_payload() -> bytes | None:
        try:
            payload = cache.read_bytes_limited(MAX_VALIDATOR_SCRIPT_BYTES, digest, filename)
        except FileNotFoundError:
            return None
        return payload if hashlib.sha256(payload).hexdigest() == digest else None

    current = cached_payload()
    if current is not None:
        return current
    # Network operations do not hold the cache writer lock. Never replace old bytes
    # until the new download satisfies both the size and pinned digest contracts.
    downloaded = _download_validator(source["url"])
    if len(downloaded) > MAX_VALIDATOR_SCRIPT_BYTES:
        raise ValidationFailure("official validator download exceeded the bounded script size")
    if hashlib.sha256(downloaded).hexdigest() != digest:
        raise ValidationFailure("official validator download digest does not match its pinned source")
    with cache.transaction(digest):
        current = cached_payload()
        if current is not None:
            return current
        staging = ".validator-" + secrets.token_hex(12)
        with cache.open_directory(digest) as directory_fd:
            try:
                cache.write_bytes_exclusive(downloaded, digest, staging)
                artifact_fs.replace(staging, filename, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                artifact_fs.fsync(directory_fd)
            finally:
                try:
                    artifact_fs.unlink(staging, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
        current = cached_payload()
        if current is None:
            raise ValidationFailure("official validator cache changed after publication")
        return current


def _script_bytes(path: Path | str, label: str) -> bytes:
    requested = Path(path).expanduser().absolute()
    # Explicit paths remain a developer injection seam. A leaf link or special
    # file is still rejected, and the bounded bytes are snapshotted before running.
    parent = requested.parent.resolve()
    try:
        reader = ArtifactIO(parent, parent)
        try:
            return reader.read_bytes_limited(MAX_VALIDATOR_SCRIPT_BYTES, requested.name)
        finally:
            reader.close()
    except (OSError, ValidationFailure) as exc:
        raise ValidationFailure(f"missing or invalid trusted {label}: {requested}") from exc


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
    raise ValidationFailure("missing uv for official validators; install uv or set ENGINEERING_ASSISTANT_UV")


def _terminate(process: subprocess.Popen) -> None:
    if getattr(process, "_engineering_assistant_group_terminated", False):
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
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
    if sys.platform == "win32":
        from .windows_process import run_bounded_windows

        try:
            returncode, captured = run_bounded_windows(
                command, cwd=repository_root, environment=environment,
                timeout_seconds=VALIDATOR_TIMEOUT_SECONDS,
                output_limit_bytes=MAX_VALIDATOR_OUTPUT_BYTES,
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
    deadline = time.monotonic() + VALIDATOR_TIMEOUT_SECONDS
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
                if len(output) > MAX_VALIDATOR_OUTPUT_BYTES:
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


def _run_bounded(
    command: list[str],
    *,
    label: str,
    repository_root: Path,
    environment: Mapping[str, str],
    runner: Callable[..., object] | None,
) -> str:
    if runner is None:
        return _run_streaming(command, label=label, repository_root=repository_root, environment=environment)
    with tempfile.TemporaryFile(mode="w+b") as output:
        try:
            completed = runner(
                command, cwd=repository_root, env=dict(environment), stdout=output,
                stderr=subprocess.STDOUT, check=False, shell=False,
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
    keys = {
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_DIR", "SSL_CERT_FILE",
        "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP", "SYSTEMROOT", "SystemRoot",
        "WINDIR", "LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
        "UV_DEFAULT_INDEX", "UV_OFFLINE", "UV_NATIVE_TLS", "UV_PYTHON_INSTALL_DIR",
    }
    allowed = {key: value for key, value in os.environ.items() if key in keys}
    allowed.update({
        "HOME": str(_account_home()), "UV_CACHE_DIR": str(cache_dir),
        "UV_NO_CONFIG": "1", "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1",
    })
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
    official_tools_cache_dir: Path | str | None = None,
    runner: Callable[..., object] | None = None,
) -> dict:
    if not validate_skills and not validate_plugin:
        raise ValidationFailure("official validation must select at least one gate")
    repository = Path(repository_root).resolve()
    package = Path(codex_package).resolve() if codex_package is not None else None
    if validate_plugin and (package is None or not package.is_dir()):
        raise ValidationFailure("official plugin validation requires a Codex package")
    skills = sorted(path.parent for path in (repository / "skills").glob("*/SKILL.md") if path.is_file())
    if validate_skills and not skills:
        raise ValidationFailure("no public skills found for official validation")
    uv = _trusted_file(uv_executable or _default_uv(), "uv executable", executable=True)
    tools_root = Path(official_tools_cache_dir) if official_tools_cache_dir is not None else _default_tools_cache()
    tools_cache = None
    dependency_cache = None
    try:
        if (validate_skills and quick_validate_path is None) or (validate_plugin and plugin_validate_path is None):
            tools_cache = _open_cache(tools_root, repository)
        dependency_root = Path(uv_cache_dir) if uv_cache_dir is not None else tools_root.parent / "uv"
        dependency_cache = _open_cache(dependency_root, repository)
        environment = _validator_environment(dependency_cache.artifact_root)
        scripts = {}
        for key, active, injected in (
            ("quick_validate", validate_skills, quick_validate_path),
            ("plugin_validate", validate_plugin, plugin_validate_path),
        ):
            if active:
                source = OFFICIAL_VALIDATORS[key]
                label = "official quick_validate.py" if key == "quick_validate" else "official plugin validator"
                scripts[key] = _script_bytes(injected, label) if injected is not None else _validator_bytes(source, tools_cache)
        # The cache is never executed directly: retain these exact verified bytes
        # in an operation-private directory, unaffected by cache updates or swaps.
        with tempfile.TemporaryDirectory(prefix="engineering-assistant-validator-snapshot-") as temporary:
            snapshot = Path(temporary).resolve()
            paths = {}
            digests = {}
            for key, payload in scripts.items():
                target = snapshot / OFFICIAL_VALIDATORS[key]["filename"]
                target.write_bytes(payload)
                paths[key] = target
                digests[key] = "sha256:" + hashlib.sha256(payload).hexdigest()
            version = _run_bounded(
                [str(uv), "--version"], label="trusted uv identity check",
                repository_root=repository, environment=environment, runner=runner,
            )
            if _UV_VERSION.fullmatch(version) is None:
                raise ValidationFailure(f"trusted uv identity check returned {version!r}")
            prefix = [
                str(uv), "run", "--no-project", "--python", VALIDATOR_PYTHON_VERSION,
                "--managed-python", "--with", PY_YAML_REQUIREMENT, "python",
            ]
            if "quick_validate" in paths:
                for skill in skills:
                    _run_bounded(
                        [*prefix, str(paths["quick_validate"]), str(skill)],
                        label=f"official quick_validate for {skill.name}",
                        repository_root=repository, environment=environment, runner=runner,
                    )
            payload_digest = None
            if "plugin_validate" in paths and package is not None:
                _run_bounded(
                    [*prefix, str(paths["plugin_validate"]), str(package)],
                    label="official plugin validator", repository_root=repository,
                    environment=environment, runner=runner,
                )
                manifest = json.loads((package / "package-manifest.json").read_text(encoding="utf-8"))
                payload_digest = manifest.get("payload_digest")
                if not isinstance(payload_digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", payload_digest) is None:
                    raise ValidationFailure("officially validated Codex package has no payload digest")
            return {
                "status": "passed", "skill_count": len(skills) if validate_skills else 0,
                "quick_validate": "passed" if validate_skills else "not_run",
                "codex_plugin_validate": "passed" if validate_plugin else "not_run",
                "codex_payload_digest": payload_digest,
                "validator_dependency": PY_YAML_REQUIREMENT,
                "validator_python": VALIDATOR_PYTHON_VERSION,
                "quick_validate_digest": digests.get("quick_validate"),
                "plugin_validate_digest": digests.get("plugin_validate"),
                "validator_sources": {
                    key: dict(OFFICIAL_VALIDATORS[key]) if injected is None else {"source": "explicit", "digest": digests[key]}
                    for key, active, injected in (
                        ("quick_validate", validate_skills, quick_validate_path),
                        ("plugin_validate", validate_plugin, plugin_validate_path),
                    ) if active
                },
            }
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationFailure(f"official validation artifact is invalid: {exc}") from exc
    finally:
        if tools_cache is not None:
            tools_cache.close()
        if dependency_cache is not None:
            dependency_cache.close()
