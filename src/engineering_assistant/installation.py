"""Prepare an immutable Runtime outside native Agent plugin caches.

Native marketplaces own plugin registration. This control plane prepares the
fixed interpreter, verifies actual protocols and publishes versioned bindings.
It never runs author tests or installs validators on an end user's machine.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Mapping

from .artifact_io import ArtifactConflict, ArtifactIO, artifact_fs
from .catalog import DEFAULT_REPOSITORY_ROOT
from .compiler import verify_package
from .validation import ValidationFailure

AGENTS = ("codex", "hermes", "claude-code")
TARGETS = ("macos-arm64", "macos-x64", "linux-x64", "windows-x64")
PYTHON_PLATFORMS = {
    "macos-arm64": ("darwin", "aarch64", "none", "aarch64-apple-darwin"),
    "macos-x64": ("darwin", "x86_64", "none", "x86_64-apple-darwin"),
    "linux-x64": ("linux", "x86_64", "gnu", "x86_64-unknown-linux-gnu"),
    "windows-x64": ("windows", "x86_64", "none", "x86_64-pc-windows-msvc"),
}
PYTHON_VERSION = "3.13.13"
MAX_CONTROL_BYTES = 65536
_NATIVE_CONTROL = ContextVar("engineering_assistant_native_control", default=None)


@contextmanager
def native_control(data: Path | str | None = None, *, allow_download: bool = False):
    """Share one resolved control CLI inside an installation command."""
    token = _NATIVE_CONTROL.set({"data": data_home(data), "allow_download": allow_download, "executables": {}})
    try:
        yield
    finally:
        _NATIVE_CONTROL.reset(token)


def host_target() -> str:
    machine = platform.machine().lower()
    system = platform.system()
    if system == "Darwin" and machine in {"arm64", "aarch64", "x86_64", "amd64"}:
        if int(platform.mac_ver()[0].split(".")[0]) >= 14:
            return "macos-arm64" if machine in {"arm64", "aarch64"} else "macos-x64"
    if system == "Linux" and machine in {"x86_64", "amd64"}:
        return "linux-x64"
    if system == "Windows" and machine in {"x86_64", "amd64"} and sys.getwindowsversion().build >= 22000:
        return "windows-x64"
    return "unsupported"


def agent_home(agent: str, explicit: Path | str | None = None,
               environment: Mapping[str, str] | None = None, config: Mapping | None = None) -> Path:
    if agent not in AGENTS:
        raise ValidationFailure(f"unsupported agent: {agent}")
    env = os.environ if environment is None else environment
    variable, fallback = {
        "codex": ("CODEX_HOME", ".codex"),
        "hermes": ("HERMES_HOME", ".hermes"),
        "claude-code": ("CLAUDE_CONFIG_DIR", ".claude"),
    }[agent]
    configured = (config or {}).get("agent_homes", {}).get(agent)
    return Path(explicit or env.get(variable) or configured or Path.home() / fallback).expanduser().absolute()


def data_home(explicit: Path | str | None = None, environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    if explicit or env.get("ENGINEERING_ASSISTANT_DATA_HOME"):
        return Path(explicit or env["ENGINEERING_ASSISTANT_DATA_HOME"]).expanduser().absolute()
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library/Application Support/engineering-assistant"
    if system == "Windows":
        if not env.get("LOCALAPPDATA"):
            raise ValidationFailure("LOCALAPPDATA is required to identify the native data directory")
        return Path(env["LOCALAPPDATA"]) / "engineering-assistant"
    return Path(env.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "engineering-assistant"


def environment_key(version: str, python_version: str, requirements_digest: str, target: str,
                    python_artifact_digest: str | None = None) -> str:
    components = [version, python_version, requirements_digest, target]
    if python_artifact_digest is not None:
        components.append(python_artifact_digest)
    return hashlib.sha256(json.dumps(components,
                                    separators=(",", ":")).encode()).hexdigest()


def python_download_metadata(lock: dict) -> bytes:
    artifact = lock["python_artifact"]
    return (json.dumps({artifact["key"]: {key: value for key, value in artifact.items() if key != "key"}},
                       ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def runtime_lock(repository_root: Path, agent: str, target: str, version: str) -> tuple[dict, bytes]:
    specification = json.loads((repository_root / "config/runtime.json").read_text(encoding="utf-8"))
    if (specification.get("schema_version") != "2" or target not in specification["targets"]
        or specification.get("python_downloads") != "runtime-python-downloads.json"):
        raise ValidationFailure(f"unsupported Runtime target: {target}")
    requirements = (repository_root / "config" / specification["requirements"]).read_bytes()
    digest = hashlib.sha256(requirements).hexdigest()
    downloads = json.loads((repository_root / "config" / specification["python_downloads"]).read_text(encoding="utf-8"))
    os_name, arch, libc, _triple = PYTHON_PLATFORMS[target]
    download_key = f"cpython-{specification['python_version']}-{os_name}-{arch}-{libc}"
    lock = {
        "schema_version": "2", "agent": agent, "target": target,
        "canonical_version": version, "python_version": specification["python_version"],
        "requirements_digest": digest,
        "python_artifact": {"key": download_key, **downloads[download_key]},
    }
    lock["python_artifact_digest"] = hashlib.sha256(python_download_metadata(lock)).hexdigest()
    lock["environment_key"] = environment_key(version, specification["python_version"], digest, target,
                                              lock["python_artifact_digest"])
    _validate_runtime_lock(lock)
    return lock, requirements


def _read_control(path: Path) -> dict:
    storage = ArtifactIO(path.parent, ".")
    try:
        return storage.read_json_limited(MAX_CONTROL_BYTES, path.name)[0]
    finally:
        storage.close()


def _validate_runtime_lock(lock: dict) -> None:
    if not isinstance(lock, dict):
        raise ValidationFailure("invalid fixed Python artifact contract")
    artifact = lock.get("python_artifact")
    if (lock.get("schema_version") != "2" or lock.get("agent") not in AGENTS
        or lock.get("target") not in TARGETS or lock.get("python_version") != PYTHON_VERSION
        or not isinstance(artifact, dict)):
        raise ValidationFailure("invalid fixed Python artifact contract")
    os_name, arch, libc, triple = PYTHON_PLATFORMS[lock["target"]]
    expected_fields = {"key", "name", "arch", "os", "libc", "major", "minor", "patch", "prerelease",
                       "url", "sha256", "variant", "build"}
    if (set(artifact) != expected_fields or artifact.get("name") != "cpython"
        or artifact.get("key") != f"cpython-{PYTHON_VERSION}-{os_name}-{arch}-{libc}"
        or artifact.get("arch") != {"family": arch, "variant": None}
        or artifact.get("os") != os_name or artifact.get("libc") != libc
        or [artifact.get(name) for name in ("major", "minor", "patch")] != [3, 13, 13]
        or artifact.get("variant") is not None or artifact.get("prerelease") != ""
        or not isinstance(artifact.get("build"), str) or re.fullmatch(r"[0-9]{8}", artifact["build"]) is None
        or not isinstance(artifact.get("sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is None
        or artifact.get("url") != ("https://github.com/astral-sh/python-build-standalone/releases/download/"
            + artifact["build"] + "/cpython-" + PYTHON_VERSION + "%2B" + artifact["build"] + "-"
            + triple + "-install_only_stripped.tar.gz")
        or lock.get("python_artifact_digest") != hashlib.sha256(python_download_metadata(lock)).hexdigest()
        or lock.get("environment_key") != environment_key(lock.get("canonical_version"),
             lock.get("python_version"), lock.get("requirements_digest"), lock.get("target"),
             lock.get("python_artifact_digest"))):
        raise ValidationFailure("invalid fixed Python artifact contract")


def _package_lock(package: Path) -> dict:
    lock = _read_control(package / "engineering-assistant/runtime-lock.json")
    _validate_runtime_lock(lock)
    storage = ArtifactIO(package / "engineering-assistant", ".")
    try:
        metadata = storage.read_bytes_limited(MAX_CONTROL_BYTES, "runtime-python-downloads.json")
    finally:
        storage.close()
    if metadata != python_download_metadata(lock):
        raise ValidationFailure("Python artifact metadata differs from its package lock")
    return lock


def _uv(explicit: Path | str | None = None) -> Path:
    from .official_validation import _default_uv, _trusted_file
    return _trusted_file(explicit, "uv", executable=True) if explicit else _default_uv()


def _command(command: list[str], *, cwd: Path, environment: dict | None = None) -> str:
    from .official_validation import _run_streaming
    return _run_streaming(command, label="Runtime preparation", repository_root=cwd,
                          environment=dict(os.environ) if environment is None else environment)


def _create_environment(staging: Path, lock: dict, requirements: Path, uv: Path, data: Path) -> None:
    environment = {name: value for name, value in os.environ.items() if not name.upper().startswith("UV_")}
    version = _command([str(uv), "--version"], cwd=data, environment=environment)
    parsed = re.match(r"^uv (\d+)\.(\d+)\.(\d+)(?:\s|$|[+.-])", version)
    if not parsed or tuple(map(int, parsed.groups())) < (0, 8, 14):
        raise ValidationFailure("Runtime preparation requires uv 0.8.14 or newer for the fixed Python build")
    storage = _storage(data)
    try:
        artifact_root = storage.ensure_directory("python", lock["python_artifact_digest"])
        with storage.transaction("python-artifact", lock["python_artifact_digest"]):
            controlled = ArtifactIO(artifact_root, ".")
            try:
                metadata = controlled.create_immutable_json(json.loads(python_download_metadata(lock)),
                                                            "runtime-python-downloads.json")
            finally:
                controlled.close()
            environment.update(UV_PYTHON_INSTALL_DIR=str(artifact_root),
                UV_PYTHON_DOWNLOADS_JSON_URL=str(metadata), UV_PYTHON_CPYTHON_BUILD=lock["python_artifact"]["build"],
                UV_CACHE_DIR=str(data / "download-cache"), UV_NO_PROGRESS="1", UV_PYTHON_INSTALL_BIN="0",
                UV_PYTHON_INSTALL_REGISTRY="0", UV_PYTHON_NO_REGISTRY="1")
            base = artifact_root / lock["python_artifact"]["key"].replace("-darwin-", "-macos-")
            if base.exists():
                _check_python_base(base, lock)
            else:
                download = storage.ensure_directory("staging", "python-" + secrets.token_hex(8), lock["python_artifact_digest"])
                environment["UV_PYTHON_INSTALL_DIR"] = str(download)
                _command([str(uv), "--no-config", "python", "install", lock["python_artifact"]["key"]],
                         cwd=data, environment=environment)
                downloaded_base = download / base.name
                _record_python_artifact(downloaded_base, lock)
                source = ArtifactIO(download, ".")
                destination = ArtifactIO(artifact_root, ".")
                try:
                    with source.open_directory() as source_fd, destination.open_directory() as destination_fd:
                        artifact_fs.rename(base.name, base.name, src_dir_fd=source_fd, dst_dir_fd=destination_fd)
                finally:
                    source.close()
                    destination.close()
                environment["UV_PYTHON_INSTALL_DIR"] = str(artifact_root)
            _command([str(uv), "--no-config", "venv", "--no-project", "--managed-python", "--no-python-downloads", "--python",
                      lock["python_artifact"]["key"], str(staging)], cwd=data, environment=environment)
    finally:
        storage.close()
    python = staging / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _command([str(uv), "--no-config", "pip", "sync", "--python", str(python), "--require-hashes",
              "--only-binary=:all:", str(requirements)], cwd=data, environment=environment)
    if os.name == "nt":
        _normalize_new_windows_environment(staging)
    _verify_interpreter(python, lock, expected_base=base)


def _verify_interpreter(python: Path, lock: dict, *, expected_base: Path | None = None) -> None:
    output = _command([str(python), "-I", "-B", "-c",
        "import json,sys,sysconfig,importlib.metadata;print(json.dumps({'python':'.'.join(map(str,sys.version_info[:3])),"
        "'jsonschema':importlib.metadata.version('jsonschema'),'base_prefix':sys.base_prefix,"
        "'implementation':sys.implementation.name,'gil':not bool(sysconfig.get_config_var('Py_GIL_DISABLED'))}))"], cwd=python.parent)
    actual = json.loads(output)
    _verify_python_facts(actual, lock, expected_base=expected_base)


def _python_receipt(lock: dict) -> dict:
    return {"schema_version": "1", "python_artifact_digest": lock["python_artifact_digest"],
            "python_artifact": lock["python_artifact"]}


def _check_python_base(base: Path, lock: dict, *, require_receipt: bool = True) -> None:
    if (not base.is_absolute() or base.parent.name != lock["python_artifact_digest"]
        or base.name != lock["python_artifact"]["key"].replace("-darwin-", "-macos-")):
        raise ValidationFailure("prepared Python base differs from its artifact contract")
    anchored = ArtifactIO(base, ".")
    try:
        build = anchored.read_bytes_limited(128, "BUILD").decode("ascii").strip()
    finally:
        anchored.close()
    if build != lock["python_artifact"]["build"]:
        raise ValidationFailure("prepared Python build differs from its artifact contract")
    if require_receipt:
        try:
            receipt = _read_control(base / "runtime-python.json")
        except FileNotFoundError:
            raise ValidationFailure("prepared Python artifact receipt is missing") from None
        if receipt != _python_receipt(lock):
            raise ValidationFailure("prepared Python artifact receipt differs from its contract")


def _record_python_artifact(base: Path, lock: dict) -> None:
    if os.name == "nt" and not (base / "runtime-python.json").exists():
        # Only the new, unbound managed base is normalized. Published bases
        # already have a receipt and are checked before uv is invoked.
        anchored = ArtifactIO(base, ".")
        try:
            with anchored.open_directory() as descriptor:
                artifact_fs.set_private_owner(descriptor)
                artifact_fs.assert_private_directory(descriptor)
        finally:
            anchored.close()
    _check_python_base(base, lock, require_receipt=False)
    storage = ArtifactIO(base, ".")
    try:
        storage.create_immutable_json(_python_receipt(lock), "runtime-python.json")
    finally:
        storage.close()


def _verify_python_facts(actual: dict, lock: dict, *, expected_base: Path | None = None) -> None:
    if (actual.get("python") != lock["python_version"] or actual.get("jsonschema") != "4.26.0"
        or actual.get("implementation") != "cpython" or actual.get("gil") is not True):
        raise ValidationFailure("prepared interpreter differs from the fixed Runtime")
    base = Path(actual.get("base_prefix", ""))
    if expected_base is not None and base != expected_base:
        raise ValidationFailure("prepared Python base differs from its binding")
    _check_python_base(base, lock)


def verify_running_python(lock: dict) -> None:
    import importlib.metadata
    import sysconfig
    marker = _read_control(Path(sys.prefix) / "runtime-environment.json")
    if {k: v for k, v in marker.items() if k not in {"agent", "python_base"}} != {k: v for k, v in lock.items() if k != "agent"}:
        raise ValidationFailure("running Python environment differs from its package")
    _verify_python_facts({"python": ".".join(map(str, sys.version_info[:3])),
        "jsonschema": importlib.metadata.version("jsonschema"), "base_prefix": sys.base_prefix,
        "implementation": sys.implementation.name, "gil": not bool(sysconfig.get_config_var("Py_GIL_DISABLED"))}, lock,
        expected_base=Path(marker.get("python_base", "")))


def _storage(data: Path) -> ArtifactIO:
    raw = data.expanduser().absolute()
    for parent in (raw, *raw.parents):
        if parent.exists() and (parent.is_symlink() or getattr(parent.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValidationFailure("Runtime data directory contains a symlink or reparse point")
    # Validate the nearest existing ancestor before creating anything beneath it.
    ancestor = next(parent for parent in (raw, *raw.parents) if parent.exists())
    anchor = ArtifactIO(ancestor, ".")
    try:
        anchor.assert_runtime_target(DEFAULT_REPOSITORY_ROOT / "schemas")
        anchor.ensure_directory(*raw.relative_to(ancestor).parts)
    finally:
        anchor.close()
    storage = ArtifactIO(raw, ".", lock_timeout_seconds=15)
    try:
        storage.assert_runtime_target(DEFAULT_REPOSITORY_ROOT / "schemas")
        with storage.open_directory() as descriptor:
            if os.name == "nt":
                artifact_fs.assert_private_directory(descriptor)
            else:
                metadata = os.fstat(descriptor)
                if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
                    raise ValidationFailure("Runtime data directory must be private and owned by the current user")
    except BaseException:
        storage.close()
        raise
    return storage


@contextmanager
def _preparation_transaction(storage: ArtifactIO, key: str, recovery: dict):
    # Recover under the original lock, before any succeeding preparer can
    # select a replacement at this key. An unlocked rollback loses that owner.
    with storage.transaction("preparation", key):
        try:
            yield
        except BaseException:
            quarantined = recovery.get("quarantined")
            if quarantined:
                with storage.open_directory("environments") as directory:
                    if storage.entry_exists("environments", key):
                        artifact_fs.rename(key, key + "-failed-" + secrets.token_hex(8),
                                           src_dir_fd=directory, dst_dir_fd=directory)
                    artifact_fs.rename(quarantined, key, src_dir_fd=directory, dst_dir_fd=directory)
            raise


def _publish_default_binding(data: Path, binding: dict) -> None:
    default = data_home(environment={k: v for k, v in os.environ.items() if k != "ENGINEERING_ASSISTANT_DATA_HOME"})
    if default == data:
        return
    storage = _storage(default)
    try:
        _publish_versioned_binding(storage, binding)
        _replace_binding(storage, binding, binding["agent"])
    finally:
        storage.close()


def _publish_versioned_binding(storage: ArtifactIO, binding: dict) -> None:
    parts = ("bindings", binding["agent"], binding["environment_key"] + ".json")
    try:
        storage.create_immutable_json(binding, *parts, existing_max_bytes=MAX_CONTROL_BYTES)
    except ArtifactConflict:
        existing = storage.read_json_limited(MAX_CONTROL_BYTES, *parts)[0]
        if {k: v for k, v in existing.items() if k != "uv"} != {k: v for k, v in binding.items() if k != "uv"}:
            raise ValidationFailure("versioned binding differs from its fixed environment")
        # Keep the first preparation's provenance immutable. The active alias
        # records today's preparation tool; neither value is used to run Python.


def _replace_binding(storage: ArtifactIO, binding: dict, agent: str) -> None:
    for _ in range(4):
        try:
            current = storage.read_json_limited(MAX_CONTROL_BYTES, "bindings", agent + ".json")[0]
        except FileNotFoundError:
            try:
                storage.create_immutable_json({**binding, "revision": 1}, "bindings", agent + ".json")
                return
            except ArtifactConflict:
                continue
        revision = current.get("revision", 0)
        try:
            storage.replace_json_cas({**binding, "revision": revision + 1}, "bindings", agent + ".json",
                                     expected_revision=revision)
            return
        except ArtifactConflict:
            continue
    raise ArtifactConflict("Runtime binding changed during preparation")


def _normalize_new_windows_environment(staging: Path) -> None:
    """Normalize copied uv owners only before a new private staging is published."""
    anchored = ArtifactIO(staging, ".")
    try:
        with anchored.open_directory() as root:
            artifact_fs.set_private_owner(root)
            artifact_fs.assert_private_directory(root)
        with anchored.open_directory("Scripts") as scripts:
            artifact_fs.set_private_owner(scripts)
            artifact_fs.assert_private_directory(scripts)
            python = artifact_fs.open("python.exe", os.O_RDONLY | artifact_fs.O_NOFOLLOW, dir_fd=scripts)
            try:
                artifact_fs.set_private_owner(python)
            finally:
                artifact_fs.close(python)
    finally:
        anchored.close()


def prepare_runtime(package: Path | str, *, data_home: Path | str | None = None,
                    uv_executable: Path | str | None = None, publish_default: bool = True,
                    repair: bool = False) -> dict:
    package = Path(package).absolute()
    manifest = verify_package(package)
    target = host_target()
    if target == "unsupported" or manifest.get("target") != target:
        raise ValidationFailure("package target is unsupported on this host")
    lock = _package_lock(package)
    if lock["canonical_version"] != manifest["canonical_version"] or lock["agent"] != manifest["platform"]:
        raise ValidationFailure("Runtime contract is not bound to its package")
    data = globals()["data_home"](data_home)
    storage = _storage(data)
    uv = _uv(uv_executable)
    key = lock["environment_key"]
    environment = data / "environments" / key
    base = data / "python" / lock["python_artifact_digest"] / lock["python_artifact"]["key"].replace("-darwin-", "-macos-")
    environment_record = {**lock, "python_base": str(base)}
    recovery = {}
    try:
        with _preparation_transaction(storage, key, recovery):
            storage.ensure_directory("environments")
            rebuild = not environment.exists()
            if not rebuild and repair:
                try:
                    _verify_interpreter(environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python"), lock,
                                        expected_base=base)
                    _protocol_checks(package, python=environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
                except (OSError, ValueError, ValidationFailure):
                    rebuild = True
            if rebuild:
                requirements = package / "engineering-assistant/runtime-requirements.txt"
                if hashlib.sha256(requirements.read_bytes()).hexdigest() != lock["requirements_digest"]:
                    raise ValidationFailure("Runtime dependency lock differs from its package")
                staging_name = key + "-" + secrets.token_hex(8)
                staging = storage.ensure_directory("staging", staging_name)
                try:
                    _create_environment(staging, lock, requirements, uv, data)
                    staged_io = ArtifactIO(staging, ".")
                    try:
                        staged_io.create_immutable_json(environment_record, "runtime-environment.json")
                    finally:
                        staged_io.close()
                    checks = _protocol_checks(package, python=staging / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
                    if not checks["provider"].get("qualified"):
                        raise ValidationFailure("Provider sandbox qualification failed: " + str(checks["provider"].get("reason")))
                    with storage.open_directory("staging") as source, storage.open_directory("environments") as destination:
                        if environment.exists():
                            quarantined = key + "-retained-" + secrets.token_hex(8)
                            artifact_fs.rename(key, quarantined, src_dir_fd=destination, dst_dir_fd=destination)
                            recovery["quarantined"] = quarantined
                        try:
                            artifact_fs.rename(staging_name, key, src_dir_fd=source, dst_dir_fd=destination)
                        except BaseException:
                            if recovery.get("quarantined"):
                                artifact_fs.rename(recovery.pop("quarantined"), key, src_dir_fd=destination, dst_dir_fd=destination)
                            raise
                except BaseException:
                    # Venvs contain legitimate interpreter links. Retain a failed
                    # attempt without recursively following or deleting them.
                    if staging.exists():
                        storage.ensure_directory("failed-preparations")
                        with storage.open_directory("staging") as source, storage.open_directory("failed-preparations") as destination:
                            artifact_fs.rename(staging_name, staging_name, src_dir_fd=source, dst_dir_fd=destination)
                    raise
            else:
                marker = _read_control(environment / "runtime-environment.json")
                if marker != environment_record:
                    # Agent differs while the shared version/requirements environment is identical.
                    if {k: v for k, v in marker.items() if k != "agent"} != {k: v for k, v in environment_record.items() if k != "agent"}:
                        raise ValidationFailure("existing Runtime environment differs from its version contract")
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            _verify_interpreter(python, lock, expected_base=base)
            checks = _protocol_checks(package, python=python)
            if not checks["provider"].get("qualified"):
                raise ValidationFailure("Provider sandbox qualification failed: " + str(checks["provider"].get("reason")))
            binding = {"schema_version": "2", "agent": lock["agent"], "target": target,
                       "canonical_version": lock["canonical_version"], "environment_key": key,
                       "python_artifact_digest": lock["python_artifact_digest"],
                       "python_build": lock["python_artifact"]["build"], "python_base": str(base),
                       "python": str(python), "uv": str(uv), "environment": str(environment)}
            _publish_versioned_binding(storage, binding)
            # The immutable locator is the native launcher's actual path. Check
            # it before selecting this version as the user's current alias.
            checks = _protocol_checks(package, data=data)
            if publish_default:
                _publish_default_binding(data, binding)
            _replace_binding(storage, binding, lock["agent"])
        return {"status": "prepared", "binding": binding, "package": str(package)}
    finally:
        storage.close()


def _component(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", value) is None:
        raise ValidationFailure(f"invalid native {label}")
    return value


def _native_call(agent: str, arguments: list[str], home: Path) -> str:
    """Keep native CLI output private: it may contain credential-bearing URLs."""
    from .local_publish import _resolve_platform_cli
    ancestor = next(parent for parent in (home, *home.parents) if parent.exists())
    anchor = ArtifactIO(ancestor, ".")
    try:
        anchor.assert_runtime_target(DEFAULT_REPOSITORY_ROOT / "schemas")
    finally:
        anchor.close()
    environment = dict(os.environ)
    environment[{"codex": "CODEX_HOME", "hermes": "HERMES_HOME", "claude-code": "CLAUDE_CONFIG_DIR"}[agent]] = str(home)
    if agent == "codex":
        from .codex_control import resolve_codex_control
        control = _NATIVE_CONTROL.get()
        cached = control["executables"] if control else {}
        if str(home) not in cached:
            cached[str(home)] = str(resolve_codex_control(
                control["data"] if control else data_home(), home,
                explicit=Path(environment["CODEX_CLI"]) if environment.get("CODEX_CLI") else None,
                allow_download=control["allow_download"] if control else False))
        executable = cached[str(home)]
    try:
        if agent != "codex":
            executable = _resolve_platform_cli("claude" if agent == "claude-code" else agent, environment)
        return _command([executable, *arguments], cwd=home if home.is_dir() else Path.home(), environment=environment)
    except Exception:
        raise ValidationFailure("原生插件命令执行失败；已保留 Runtime，请检查宿主状态后重试") from None


def _native_query(agent: str, arguments: list[str], home: Path) -> object:
    raw = _native_call(agent, arguments, home)
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        raise ValidationFailure("native plugin query did not return its JSON contract") from None


class _UnsupportedNativeSource(ValidationFailure):
    """The installed host cannot supply the source identity we must verify."""


def _marketplace_entry(agent: str, home: Path, marketplace: str) -> dict | None:
    payload = _native_query(agent, ["plugin", "marketplace", "list", "--json"], home)
    entries = payload.get("marketplaces") if agent == "codex" and isinstance(payload, dict) else payload
    if not isinstance(entries, list) or len(entries) > 256 or any(not isinstance(entry, dict) for entry in entries):
        raise _UnsupportedNativeSource("native marketplace list has an unsupported identity contract")
    matches = [entry for entry in entries if entry.get("name") == marketplace]
    if len(matches) > 1:
        raise ValidationFailure("native marketplace identity is ambiguous")
    return matches[0] if matches else None


def _native_source_path(value: object) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute() or ".." in Path(value).parts:
        raise _UnsupportedNativeSource("native marketplace root has an unsupported path contract")
    return Path(value).resolve()


def _codex_git_snapshot(home: Path, marketplace: str, snapshot: Path, repository: str, ref: str | None) -> None:
    # Codex 0.159.2 JSON omits ref. Its controlled user config records it,
    # and the native Git checkout supplies independent HEAD/origin evidence.
    expected_url = "https://github.com/" + repository + ".git"
    try:
        storage = ArtifactIO(home, ".")
        try:
            config = tomllib.loads(storage.read_bytes_limited(MAX_CONTROL_BYTES, "config.toml").decode("utf-8"))
        finally:
            storage.close()
        configured = config.get("marketplaces", {}).get(marketplace)
        if not isinstance(configured, dict) or configured.get("source_type") != "git":
            raise _UnsupportedNativeSource("native Codex marketplace has no verifiable Git ref contract")
        if configured.get("source") != expected_url or configured.get("ref") != ref:
            raise ValidationFailure("native marketplace source or ref differs from the requested distribution")
        snapshot_io = ArtifactIO(snapshot, ".")
        try:
            snapshot_io.read_bytes_limited(MAX_CONTROL_BYTES, ".git", "HEAD")
            snapshot_io.read_bytes_limited(MAX_CONTROL_BYTES, ".git", "config")
        finally:
            snapshot_io.close()
        git = shutil.which("git")
        if not git:
            raise _UnsupportedNativeSource("native Codex Git snapshot requires an available Git executable")
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                           GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1")
        prefix = [git, "-c", "core.fsmonitor=false"]
        origin = _command([*prefix, "config", "--local", "--get", "remote.origin.url"], cwd=snapshot, environment=environment).strip()
        head = _command([*prefix, "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"], cwd=snapshot, environment=environment).strip()
        revision = _command([*prefix, "rev-parse", "--verify", "--end-of-options",
                             (ref or "refs/remotes/origin/HEAD") + "^{commit}"], cwd=snapshot, environment=environment).strip()
        if origin != expected_url or head != revision:
            raise ValidationFailure("native marketplace source checkout differs from the requested distribution")
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head) is None:
            raise _UnsupportedNativeSource("native Codex Git snapshot has an unsupported revision contract")
    except ValidationFailure:
        raise
    except Exception:
        raise _UnsupportedNativeSource("native Codex Git snapshot identity cannot be verified") from None


def _verify_marketplace_source(agent: str, home: Path, marketplace: str, source: str,
                               local: Path | None, *, required: bool = False) -> None:
    entry = _marketplace_entry(agent, home, marketplace)
    if entry is None:
        if required:
            raise ValidationFailure("native marketplace source was not registered")
        return
    snapshot = _native_source_path(entry.get("root" if agent == "codex" else "installLocation"))
    if local is not None:
        if agent == "codex":
            descriptor = entry.get("marketplaceSource")
            if descriptor is not None and (not isinstance(descriptor, dict) or descriptor.get("sourceType") != "local"):
                raise ValidationFailure("native marketplace source differs from the requested local distribution")
            origin = _native_source_path(descriptor.get("source")) if descriptor else snapshot
        else:
            if entry.get("source") != "directory":
                raise ValidationFailure("native marketplace source differs from the requested local distribution")
            origin = _native_source_path(entry.get("path"))
        if origin != local or snapshot != local:
            raise ValidationFailure("native marketplace source root differs from the requested local distribution")
        return
    repository, _, ref = source.partition("@")
    ref = ref or None
    if agent == "codex":
        descriptor = entry.get("marketplaceSource")
        if not isinstance(descriptor, dict) or descriptor.get("sourceType") != "git":
            raise _UnsupportedNativeSource("native Codex marketplace has no verifiable Git source contract")
        if descriptor.get("source") != "https://github.com/" + repository + ".git":
            raise ValidationFailure("native marketplace source differs from the requested distribution")
        _codex_git_snapshot(home, marketplace, snapshot, repository, ref)
    else:
        if entry.get("source") != "github":
            raise _UnsupportedNativeSource("native Claude marketplace has an unsupported distribution source contract")
        if not isinstance(entry.get("repo"), str) or entry.get("ref") is not None and not isinstance(entry["ref"], str):
            raise _UnsupportedNativeSource("native Claude marketplace has an unsupported repository or ref contract")
        if entry["repo"] != repository or entry.get("ref") != ref:
            raise ValidationFailure("native marketplace source or ref differs from the requested distribution")


def _installed_identity(agent: str, home: Path, marketplace: str | None = None) -> dict | None:
    if marketplace is not None:
        _component(marketplace, "marketplace")
    arguments = ["plugins", "list", "--user", "--json"] if agent == "hermes" else ["plugin", "list", "--json"]
    payload = _native_query(agent, arguments, home)
    entries = payload.get("installed") if agent == "codex" and isinstance(payload, dict) else payload
    if not isinstance(entries, list) or len(entries) > 256:
        raise ValidationFailure("native installed-plugin list has an unsupported structure")
    matches = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationFailure("invalid native installed-plugin entry")
        if agent == "claude-code":
            identity = entry.get("id", "")
            if not isinstance(identity, str) or not identity.startswith("engineering-assistant@") or entry.get("scope") != "user":
                continue
            selected_marketplace = _component(identity.split("@", 1)[1], "marketplace")
        else:
            if entry.get("name") != "engineering-assistant" or (agent == "codex" and entry.get("installed") is not True):
                continue
            selected_marketplace = _component(entry.get("marketplaceName"), "marketplace") if agent == "codex" else None
            if agent == "codex" and entry.get("pluginId", "engineering-assistant@" + selected_marketplace) != "engineering-assistant@" + selected_marketplace:
                raise ValidationFailure("native plugin identity differs from its marketplace")
        if marketplace is not None and selected_marketplace != marketplace:
            continue
        version = _component(entry.get("version"), "version")
        if agent == "codex":
            package = home / "plugins/cache" / selected_marketplace / "engineering-assistant" / version
        elif agent == "claude-code":
            location = entry.get("installPath")
            if not isinstance(location, str) or not Path(location).is_absolute() or ".." in Path(location).parts:
                raise ValidationFailure("native installed-plugin path is invalid")
            package = Path(location)
        else:
            package = home / "plugins/engineering-assistant"
        matches.append({"marketplace": selected_marketplace, "version": version, "package": package,
                        "enabled": entry.get("status") == "enabled" if agent == "hermes" else entry.get("enabled") is True})
    if len(matches) > 1:
        raise ValidationFailure("ambiguous native plugin sources; select --marketplace explicitly")
    return matches[0] if matches else None


def _verified_package(package: Path, agent: str, version: str | None = None) -> dict:
    manifest = verify_package(package)
    if manifest["platform"] != agent:
        raise ValidationFailure("plugin package belongs to a different Agent")
    if version is not None:
        if agent == "hermes":
            from .version import platform_version
            actual = platform_version(manifest["canonical_version"], supports_four_part=False)
        else:
            directory = ".codex-plugin" if agent == "codex" else ".claude-plugin"
            actual = _read_control(package / directory / "plugin.json").get("version")
        if actual != version:
            raise ValidationFailure("native installed version differs from the verified package version")
    return manifest


def find_package(agent: str, home: Path | str | None = None,
                 marketplace: str | None = None) -> Path | None:
    root = agent_home(agent, home)
    selected = _installed_identity(agent, root, marketplace)
    if selected is None:
        return None
    _verified_package(selected["package"], agent, selected["version"])
    return selected["package"]


def _protocol_run(command: list[str], *, cwd: Path, input_data: bytes = b"",
                  environment: Mapping[str, str] | None = None, timeout: int = 30,
                  expected_exit_code: int = 0) -> bytes:
    """Bound protocol output and terminate the complete child process tree."""
    environment = dict(os.environ if environment is None else environment)
    limit = 1_048_576
    if len(input_data) > limit:
        raise ValidationFailure("protocol input exceeds its bounded limit")
    if os.name == "nt":
        from .windows_process import run_bounded_windows
        code, output = run_bounded_windows(command, cwd=cwd, environment=environment,
            timeout_seconds=timeout, output_limit_bytes=limit, input_data=input_data)
    else:
        with tempfile.TemporaryFile() as request:
            request.write(input_data)
            request.seek(0)
            process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=request,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, shell=False)
            output = bytearray()
            deadline = time.monotonic() + timeout
            selector = selectors.DefaultSelector()
            assert process.stdout is not None
            selector.register(process.stdout, selectors.EVENT_READ)
            try:
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise ValidationFailure("protocol process timed out")
                    for entry, _ in selector.select(min(0.5, deadline - time.monotonic())):
                        chunk = os.read(entry.fd, 8192)
                        if not chunk:
                            selector.unregister(entry.fileobj)
                        output.extend(chunk)
                        if len(output) > limit:
                            raise ValidationFailure("protocol output exceeds its bounded limit")
                code = process.wait(timeout=max(deadline - time.monotonic(), 0.001))
            finally:
                selector.close()
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                process.stdout.close()
            output = bytes(output)
    if code != expected_exit_code:
        raise ValidationFailure("protocol process failed: " + output.decode("utf-8", errors="replace")[:1024])
    return output


def _windows_hook_probe(package: Path, cwd: Path, input_data: bytes, environment: Mapping[str, str]) -> str:
    hooks = _read_control(package / "hooks/hooks.json").get("hooks")
    if not isinstance(hooks, dict):
        raise ValidationFailure("Windows Hook manifest has no executable contract")
    commands = set()
    try:
        for groups in hooks.values():
            for group in groups:
                for hook in group["hooks"]:
                    commands.add(hook["commandWindows"])
        if len(commands) != 1:
            raise ValueError
        command = commands.pop()
        if re.fullmatch(r"powershell\.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand [A-Za-z0-9+/=]+", command) is None:
            raise ValueError
    except (TypeError, KeyError, ValueError):
        raise ValidationFailure("Windows Hook manifest has an unsupported command contract") from None
    system = environment.get("SystemRoot") or environment.get("SYSTEMROOT")
    standard = Path(system) / "System32/WindowsPowerShell/v1.0/powershell.exe" if system else None
    discovered = shutil.which("powershell.exe", path=environment.get("PATH"))
    executable = standard if standard and standard.is_file() else Path(discovered) if discovered else None
    if executable is None or not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
        raise ValidationFailure("Windows PowerShell prerequisite is unavailable for the actual Hook bridge")
    response = _protocol_run([str(executable), *command.split(" ")[1:]], cwd=cwd, input_data=input_data,
                             environment={**environment, "PLUGIN_ROOT": str(package.resolve())}, timeout=15)
    if json.loads(response) != {}:
        raise ValidationFailure("Windows Hook bridge did not return the nonblocking protocol")
    return "passed"


def _protocol_checks(package: Path, *, python: Path | None = None,
                     data: Path | None = None) -> dict:
    runtime = package / "engineering-assistant"
    command = ([str(python), "-I", "-B", "-X", "utf8", str(runtime / "runtime_boot.py")] if python else
               [str(runtime / "bin" / ("ea.exe" if os.name == "nt" else "ea"))])
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "ea-setup", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "engineering_assistant_route", "arguments": {"intent": {
                "task_kind": "explain", "requested_outcome": "安装只读诊断", "scope": ["installation"],
                "risk_signals": [], "requested_external_actions": [], "confirmed_actions": [],
                "read_only": True, "confidence": 1, "evidence": ["ea-setup protocol diagnostic"]}}}},
    ]
    environment = dict(os.environ)
    if data is not None:
        environment["ENGINEERING_ASSISTANT_DATA_HOME"] = str(data)
    with tempfile.TemporaryDirectory(prefix="ea-runtime-probe-") as temporary:
        output = _protocol_run([*command, "mcp-serve"], input_data="".join(json.dumps(x) + "\n" for x in requests).encode(),
                               cwd=Path(temporary), environment=environment)
        responses = [json.loads(line) for line in output.decode("utf-8").splitlines()]
        initialized = next((x for x in responses if x.get("id") == 1), {})
        listed = next((x for x in responses if x.get("id") == 2), {})
        if "error" in initialized or initialized.get("result", {}).get("protocolVersion") != "2025-06-18":
            raise ValidationFailure("MCP initialization did not satisfy the protocol")
        if not listed.get("result", {}).get("tools"):
            raise ValidationFailure("MCP tools/list returned no Runtime tools")
        invoked = next((x for x in responses if x.get("id") == 3), {})
        if "error" in invoked or invoked.get("result", {}).get("isError", True):
            raise ValidationFailure("MCP tools/call did not execute the Runtime route")
        hook = _protocol_run([*command, "hook"], input_data=json.dumps({"cwd": temporary, "hook_event_name": "Stop"}).encode(),
                             cwd=Path(temporary), environment=environment, timeout=15)
        if json.loads(hook) != {}:
            raise ValidationFailure("Hook did not return the nonblocking protocol")
        windows_hook = "not_applicable"
        if os.name == "nt" and _package_lock(package)["agent"] == "codex":
            windows_hook = "requires_prepared_binding" if python else _windows_hook_probe(package, Path(temporary),
                json.dumps({"cwd": temporary, "hook_event_name": "Stop", "prompt": "中文安装验证"}, ensure_ascii=False).encode("utf-8"),
                environment)
        try:
            sandbox = json.loads(_protocol_run([*command, "sandbox-probe"], cwd=Path(temporary), environment=environment, timeout=60))
            if not isinstance(sandbox, dict) or type(sandbox.get("qualified")) is not bool:
                raise ValueError("invalid Provider diagnostic")
        except (OSError, ValueError, subprocess.SubprocessError, ValidationFailure):
            sandbox = {"qualified": False, "reason": "provider_diagnostic_failed"}
        bridge = "not_applicable"
        if _package_lock(package)["agent"] == "hermes":
            rpc = _protocol_run([*command, "hermes-rpc"], cwd=Path(temporary), environment=environment,
                input_data=json.dumps({"operation": "call", "name": "engineering_assistant_route",
                    "args": requests[-1]["params"]["arguments"], "kwargs": {}}).encode())
            if json.loads(rpc).get("decision", {}).get("decision") not in {"proceed", "ask"}:
                raise ValidationFailure("Hermes bridge did not execute the Runtime route")
            bridge = "passed"
        return {"mcp": "passed", "tools_call": "passed", "hook": "passed", "windows_hook_bridge": windows_hook,
                "hermes_bridge": bridge, "provider": sandbox}


def doctor(agent: str, *, package: Path | str | None = None, home: Path | str | None = None,
           data_home: Path | str | None = None, target: str | None = None,
           marketplace: str | None = None, hooks_trusted: bool = False,
           native_activation_verified: bool = False) -> dict:
    actual = host_target()
    if actual == "unsupported" or (target is not None and target != actual):
        return {"status": "unsupported", "ready": False, "target": target or actual}
    selected = None if package else _installed_identity(agent, agent_home(agent, home), marketplace)
    package = Path(package) if package else selected["package"] if selected else None
    if package is None:
        return {"status": "needs_preparation", "ready": False, "reason": "native marketplace plugin not found"}
    manifest = _verified_package(package, agent, selected["version"] if selected else None)
    data = globals()["data_home"](data_home)
    if not (data / "bindings" / (agent + ".json")).is_file():
        return {"status": "needs_preparation", "ready": False, "package": str(package)}
    if manifest.get("target") != actual:
        return {"status": "unsupported", "ready": False, "reason": "package target differs from host"}
    try:
        lock = _package_lock(package)
        binding = _read_control(data / "bindings" / agent / (lock["environment_key"] + ".json"))
        if (any(binding.get(name) != lock[name] for name in ("schema_version", "agent", "target", "environment_key", "python_artifact_digest"))
            or binding.get("python_build") != lock["python_artifact"]["build"]):
            raise ValidationFailure("Runtime binding differs from its Python artifact contract")
        _verify_interpreter(Path(binding["python"]), lock, expected_base=Path(binding["python_base"]))
        checks = _protocol_checks(package, data=data)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, ValidationFailure) as exc:
        return {"status": "failed", "ready": False, "reason": str(exc)}
    runtime_ready = all(checks.get(name) == "passed" for name in ("mcp", "tools_call"))
    provider_ready = checks.get("provider", {}).get("qualified") is True
    qualified = runtime_ready and checks.get("hook") == "passed" and provider_ready
    if not runtime_ready:
        status, reason = "failed", "runtime_protocol_check_failed"
    elif checks.get("hook") != "passed":
        status, reason = "failed", "hook_protocol_check_failed"
    else:
        status, reason = ("ready", None) if provider_ready else ("partial", checks["provider"].get("reason"))
    trust = "not_applicable" if agent == "hermes" else "user_confirmed" if hooks_trusted else "requires_native_host_review"
    activation = "enabled" if native_activation_verified or selected and selected["enabled"] else "disabled" if selected else "not_verified"
    if qualified and activation != "enabled":
        status, reason = "needs_preparation", "requires_native_activation"
    elif qualified and agent != "hermes" and not hooks_trusted:
        status, reason = "needs_trust", "requires_native_hook_review"
    return {"status": status, "ready": status == "ready", "runtime_ready": runtime_ready,
            "provider_ready": provider_ready,
            "agent": agent, "target": actual, "version": manifest["canonical_version"],
            "package": str(package), "checks": checks,
            "hook_trust": trust, "native_activation": activation,
            "python_build": lock["python_artifact"]["build"], "python_artifact_digest": lock["python_artifact_digest"],
            "native_marketplace_session": "not_executed", "reason": reason}


def _candidate_package(agent: str, root: Path, marketplace: str) -> Path:
    """Resolve only an already acquired native snapshot, never a remote plugin URL."""
    if agent == "codex":
        payload = _native_query(agent, ["plugin", "list", "--available", "--marketplace", marketplace, "--json"], root)
        # --available retains installed catalogue entries under `installed`.
        entries = payload.get("available", []) + payload.get("installed", []) if isinstance(payload, dict) else []
        matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("name") == "engineering-assistant"
                   and entry.get("marketplaceName") == marketplace]
        if len(matches) != 1:
            raise ValidationFailure("native marketplace candidate is missing or ambiguous")
        source = matches[0].get("source", {})
        if not isinstance(source, dict) or source.get("source") != "local" or not isinstance(source.get("path"), str):
            raise ValidationFailure("remote plugin source has no prepared snapshot; use a local distribution candidate")
        candidate = Path(source["path"])
        if not candidate.is_absolute() or ".." in candidate.parts:
            raise ValidationFailure("native marketplace candidate path is invalid")
        # An installed entry carries the cache version; its source points to
        # the refreshed catalogue candidate, whose manifest is authoritative.
        _verified_package(candidate, agent)
        return candidate
    payload = _native_query(agent, ["plugin", "marketplace", "list", "--json"], root)
    matches = [entry for entry in payload if isinstance(entry, dict) and entry.get("name") == marketplace] if isinstance(payload, list) else []
    if len(matches) != 1 or not isinstance(matches[0].get("installLocation"), str):
        raise ValidationFailure("native marketplace snapshot is missing or ambiguous")
    snapshot = Path(matches[0]["installLocation"])
    if not snapshot.is_absolute() or ".." in snapshot.parts:
        raise ValidationFailure("native marketplace snapshot path is invalid")
    manifest = _read_control(snapshot / ".claude-plugin/marketplace.json")
    if not isinstance(manifest, dict) or manifest.get("name") != marketplace or not isinstance(manifest.get("plugins"), list):
        raise ValidationFailure("native marketplace snapshot manifest is invalid")
    plugins = [entry for entry in manifest["plugins"] if isinstance(entry, dict) and entry.get("name") == "engineering-assistant"]
    if len(plugins) != 1 or not isinstance(plugins[0].get("source"), str):
        raise ValidationFailure("native marketplace requires one local distribution candidate")
    relative = Path(plugins[0]["source"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValidationFailure("native marketplace source must stay inside its snapshot")
    candidate = snapshot / relative
    if snapshot.resolve() not in candidate.resolve().parents:
        raise ValidationFailure("native marketplace candidate escapes its snapshot")
    _verified_package(candidate, agent)
    return candidate


def _selection_arguments(agent: str, command: str, marketplace: str | None) -> list[str]:
    name = "engineering-assistant" + ("@" + marketplace if marketplace else "")
    if agent == "codex":
        return ["plugin", "add" if command in {"install", "update"} else "remove", name, "--json"]
    if agent == "claude-code":
        return ["plugin", command, name, "--scope", "user"]
    return ["plugins", command if command != "uninstall" else "remove", name]


def _selection_recovery(agent: str, root: Path, marketplace: str | None, expected: dict,
                        previous: dict | None = None) -> dict:
    """Observe native side effects; never promise a version rollback the host lacks."""
    state = "unverified"
    try:
        selected = _installed_identity(agent, root, marketplace)
        if selected is None:
            state = "not_installed"
        else:
            try:
                actual = _verified_package(selected["package"], agent, selected["version"])
                if actual["payload_digest"] == expected["payload_digest"]:
                    state = "verified_candidate"
                elif previous and actual["payload_digest"] == previous["payload_digest"]:
                    state = "previous_selection_retained"
            except Exception:
                pass
            if state == "unverified" and agent in {"claude-code", "hermes"}:
                _native_call(agent, _selection_arguments(agent, "disable", marketplace), root)
                observed = _installed_identity(agent, root, marketplace)
                if observed is not None and not observed["enabled"]:
                    state = "disabled"
    except Exception:
        state = "unverified"
    return {"status": "failed", "ready": False, "agent": agent, "marketplace": marketplace,
            "reason": "native selection could not be completed and verified; native host recovery is required",
            "recovery_required": True, "native_state": state, "retained_runtime_environments": True}


def _verify_selection(agent: str, root: Path, marketplace: str | None, expected: dict,
                      *, data: Path | str | None, hooks_trusted: bool,
                      previous: dict | None = None) -> dict:
    try:
        selected = _installed_identity(agent, root, marketplace)
        if selected is None:
            raise ValidationFailure("native selection did not return the installed plugin")
        actual = _verified_package(selected["package"], agent, selected["version"])
        if actual["payload_digest"] != expected["payload_digest"]:
            raise ValidationFailure("native selection differs from the prepared candidate")
    except Exception:
        return _selection_recovery(agent, root, marketplace, expected, previous)
    result = doctor(agent, package=selected["package"], home=root, data_home=data,
                    hooks_trusted=hooks_trusted, native_activation_verified=selected["enabled"])
    return {**result, "marketplace": marketplace, "retained_runtime_environments": True}


def update_plugin(agent: str, home: Path | str | None = None, marketplace: str | None = None,
                  *, package: Path | str | None = None, data_home: Path | str | None = None,
                  uv_executable: Path | str | None = None, hooks_trusted: bool = False) -> dict:
    root = agent_home(agent, home)
    if agent == "hermes" and package is None:
        raise ValidationFailure("Hermes update requires an explicit controlled --package candidate")
    selected = _installed_identity(agent, root, marketplace)
    if selected is None:
        raise ValidationFailure("native plugin is not installed; use install first")
    marketplace = selected["marketplace"]
    previous = _verified_package(selected["package"], agent, selected["version"])
    if agent != "hermes":
        refresh = "upgrade" if agent == "codex" else "update"
        _native_call(agent, ["plugin", "marketplace", refresh, marketplace], root)
        candidate = _candidate_package(agent, root, marketplace)
        expected = _verified_package(candidate, agent)
        if package is not None and _verified_package(Path(package), agent)["payload_digest"] != expected["payload_digest"]:
            raise ValidationFailure("explicit candidate differs from the native marketplace snapshot")
    else:
        candidate = Path(package).absolute()
        expected = _verified_package(candidate, agent)
    prepare_runtime(candidate, data_home=data_home, uv_executable=uv_executable)
    # Recheck the same snapshot after preparation and before native selection.
    if _verified_package(candidate, agent)["payload_digest"] != expected["payload_digest"]:
        raise ValidationFailure("native candidate changed during Runtime preparation")
    try:
        _native_call(agent, _selection_arguments(agent, "update", marketplace), root)
    except Exception:
        return _selection_recovery(agent, root, marketplace, expected, previous)
    return _verify_selection(agent, root, marketplace, expected, data=data_home,
                             hooks_trusted=hooks_trusted, previous=previous)


def install_plugin(agent: str, source: str, *, home: Path | str | None = None,
                   marketplace: str | None = None, data_home: Path | str | None = None,
                   uv_executable: Path | str | None = None, hooks_trusted: bool = False) -> dict:
    root = agent_home(agent, home)
    local = Path(source).expanduser()
    if local.exists():
        local = local.resolve()
        if local == DEFAULT_REPOSITORY_ROOT or DEFAULT_REPOSITORY_ROOT in local.parents:
            raise ValidationFailure("install source must be a built distribution, not the author repository")
        if not local.is_dir():
            raise ValidationFailure("install source must be a distribution directory")
        source = str(local)
    elif re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*(?:@[A-Za-z0-9][A-Za-z0-9/._-]*)?", source) is None:
        raise ValidationFailure("unsupported distribution source; use owner/repo@ref or a controlled local marketplace")
    if agent == "hermes" and ("@" in source or local.exists() and not (local / ".git").is_dir()):
        return {"status": "unsupported", "ready": False, "reason": "native Hermes install does not support pinned refs or local non-Git distributions"}
    if agent != "hermes":
        marketplace = _component(marketplace, "marketplace")
        if local.exists():
            directory = ".agents/plugins" if agent == "codex" else ".claude-plugin"
            if _read_control(local / directory / "marketplace.json").get("name") != marketplace:
                raise ValidationFailure("local distribution marketplace name differs from --marketplace")
        try:
            _verify_marketplace_source(agent, root, marketplace, source, local if local.exists() else None)
        except _UnsupportedNativeSource as exc:
            return {"status": "unsupported", "ready": False, "reason": str(exc)}
    if _installed_identity(agent, root, marketplace) is not None:
        raise ValidationFailure("native plugin is already installed; use update")
    if agent == "hermes":
        _native_call(agent, ["plugins", "install", local.as_uri() if local.exists() else source, "--no-enable"], root)
        candidate = find_package(agent, root)
        if candidate is None:
            raise ValidationFailure("native install did not acquire the plugin")
    else:
        arguments = ["plugin", "marketplace", "add", source]
        arguments += ["--json"] if agent == "codex" else ["--scope", "user"]
        _native_call(agent, arguments, root)
        try:
            _verify_marketplace_source(agent, root, marketplace, source, local if local.exists() else None, required=True)
        except _UnsupportedNativeSource as exc:
            return {"status": "unsupported", "ready": False, "reason": str(exc)}
        candidate = _candidate_package(agent, root, marketplace)
    expected = _verified_package(candidate, agent)
    prepare_runtime(candidate, data_home=data_home, uv_executable=uv_executable)
    if _verified_package(candidate, agent)["payload_digest"] != expected["payload_digest"]:
        raise ValidationFailure("native candidate changed during Runtime preparation")
    arguments = ["plugins", "enable", "engineering-assistant"] if agent == "hermes" else _selection_arguments(agent, "install", marketplace)
    try:
        _native_call(agent, arguments, root)
    except Exception:
        return _selection_recovery(agent, root, marketplace, expected)
    return _verify_selection(agent, root, marketplace, expected, data=data_home, hooks_trusted=hooks_trusted)


def uninstall(agent: str, home: Path | str | None = None, marketplace: str | None = None) -> dict:
    root = agent_home(agent, home)
    selected = _installed_identity(agent, root, marketplace)
    if selected is None:
        raise ValidationFailure("native plugin is not installed")
    _native_call(agent, _selection_arguments(agent, "uninstall", selected["marketplace"]), root)
    if _installed_identity(agent, root, selected["marketplace"]) is not None:
        raise ValidationFailure("native uninstall did not remove the selected plugin")
    return {"status": "uninstalled", "agent": agent, "retained_runtime_environments": True}
