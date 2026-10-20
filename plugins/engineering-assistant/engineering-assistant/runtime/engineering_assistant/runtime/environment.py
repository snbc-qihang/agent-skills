"""Fixed interpreter and artifact contracts shared by runtime and installer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

from .artifact_io import ArtifactIO, artifact_fs
from .validation import ValidationFailure

AGENTS = ("codex", "hermes", "claude-code", "cursor")


TARGETS = ("macos-arm64", "linux-x64", "windows-x64")


PYTHON_PLATFORMS = {
    "macos-arm64": ("darwin", "aarch64", "none", "aarch64-apple-darwin"),
    "linux-x64": ("linux", "x86_64", "gnu", "x86_64-unknown-linux-gnu"),
    "windows-x64": ("windows", "x86_64", "none", "x86_64-pc-windows-msvc"),
}


PYTHON_VERSION = "3.13.13"


MAX_CONTROL_BYTES = 65536


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
