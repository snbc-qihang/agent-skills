"""Content identity and read-only lookup of a host-independent Runtime core."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

from .artifact_io import ArtifactIO
from .environment import _read_control
from .validation import ValidationFailure

CORE_DESCRIPTOR = "runtime-core.json"
MAX_CORE_MANIFEST_BYTES = 1024 * 1024
MAX_CORE_FILE_BYTES = 32 * 1024 * 1024


def core_sources(payload_files: dict[str, str]) -> dict[str, str]:
    """Map distribution paths to core paths, excluding native host entry files."""
    result = {}
    for name in sorted(payload_files):
        if name.startswith("engineering-assistant/"):
            relative = name.removeprefix("engineering-assistant/")
            if relative in {"runtime-lock.json", "runtime_boot.py", CORE_DESCRIPTOR} or relative.startswith("bin/"):
                continue
        elif name.startswith("skills/") or name in {"LICENSE", "THIRD_PARTY_NOTICES.md"}:
            if name.startswith("skills/") and "/agents/" in name:
                continue  # Native discovery metadata belongs to its host entry.
            relative = name
        else:
            continue
        if relative in result:
            raise ValidationFailure("distribution paths collide inside the shared core")
        result[relative] = name
    return result


def make_core_descriptor(payload_files: dict[str, str], version: str, target: str) -> dict:
    files = {relative: payload_files[source] for relative, source in core_sources(payload_files).items()}
    identity = {"schema_version": "1", "canonical_version": version, "target": target, "payload_files": files}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**identity, "payload_digest": "sha256:" + digest}


def read_core_descriptor(entry: Path) -> dict | None:
    try:
        storage = ArtifactIO(entry, ".")
    except FileNotFoundError:
        return None
    try:
        try:
            descriptor = storage.read_json_limited(MAX_CORE_MANIFEST_BYTES, CORE_DESCRIPTOR)[0]
        except FileNotFoundError:
            return None
    finally:
        storage.close()
    _validate_descriptor(descriptor)
    return descriptor


def core_descriptor(package: Path) -> dict:
    descriptor = read_core_descriptor(package / "engineering-assistant")
    if descriptor is None:
        raise ValidationFailure("package has no shared core contract")
    return descriptor


def _validate_descriptor(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"schema_version", "canonical_version", "target", "payload_files", "payload_digest"}:
        raise ValidationFailure("invalid shared core contract")
    if (value["schema_version"] != "1" or not isinstance(value["canonical_version"], str)
        or re.fullmatch(r"\d+\.\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", value["canonical_version"]) is None
        or value["target"] not in {"macos-arm64", "windows-x64", "linux-x64"}
        or not isinstance(value["payload_files"], dict) or not 1 <= len(value["payload_files"]) <= 4096):
        raise ValidationFailure("invalid shared core contract")
    for name, digest in value["payload_files"].items():
        if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or PurePosixPath(name).is_absolute() or any(part in {"", ".", ".."} for part in name.split("/"))
            or not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None):
            raise ValidationFailure("invalid shared core file identity")
    required = {"LICENSE", "THIRD_PARTY_NOTICES.md", "runtime/engineering_assistant/__init__.py",
                "runtime/engineering_assistant/runtime/cli.py", "skills/engineering-assistant/SKILL.md"}
    if not required.issubset(value["payload_files"]):
        raise ValidationFailure("shared core is missing required Runtime or skills")
    identity = {key: item for key, item in value.items() if key != "payload_digest"}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if value["payload_digest"] != "sha256:" + digest:
        raise ValidationFailure("shared core digest differs from its contract")


def verify_core(core: Path, expected: dict) -> None:
    _validate_descriptor(expected)
    storage = ArtifactIO(core, ".")
    try:
        actual = storage.read_json_limited(MAX_CORE_MANIFEST_BYTES, "core-manifest.json")[0]
        if actual != expected:
            raise ValidationFailure("shared core identity differs from the selected plugin")
        files = storage.sha256_file_digests(exclude=frozenset({"core-manifest.json"}),
            max_file_bytes=MAX_CORE_FILE_BYTES, max_entries=4096, max_total_bytes=256 * 1024 * 1024)
        if files != expected["payload_files"]:
            raise ValidationFailure("shared core payload differs from its contract; run repair after reviewing the changed files")
    finally:
        storage.close()


def resolve_core(entry: Path, data: Path) -> Path:
    descriptor = read_core_descriptor(entry)
    if descriptor is None:
        return entry  # Pre-existing distributions retain their original bootstrap contract.
    core = data / "cores" / descriptor["payload_digest"][7:]
    verify_core(core, descriptor)
    return core


def default_data_home() -> Path:
    if os.environ.get("ENGINEERING_ASSISTANT_DATA_HOME"):
        result = Path(os.environ["ENGINEERING_ASSISTANT_DATA_HOME"])
    elif sys.platform == "darwin":
        result = Path.home() / "Library/Application Support/engineering-assistant"
    elif os.name == "nt":
        if not os.environ.get("LOCALAPPDATA"):
            raise ValidationFailure("LOCALAPPDATA is required for the shared Runtime")
        result = Path(os.environ["LOCALAPPDATA"]) / "engineering-assistant"
    else:
        result = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "engineering-assistant"
    if not result.is_absolute() or ".." in result.parts:
        raise ValidationFailure("Runtime data home must be absolute without parent traversal")
    return result


def bootstrap_data_home(lock: dict) -> Path:
    data = default_data_home()
    # An explicit installation directory can publish a default locator. Follow
    # the same immutable versioned binding as the native launcher, never PATH.
    versioned = data / "bindings" / lock["agent"] / (lock["environment_key"] + ".json")
    alias = data / "bindings" / (lock["agent"] + ".json")
    for path in (versioned, alias):
        if not path.exists() and not path.is_symlink():
            continue
        binding = _read_control(path)
        if any(binding.get(key) != lock[key] for key in ("schema_version", "agent", "target", "environment_key")):
            raise ValidationFailure("shared core locator differs from this plugin")
        environment = Path(binding["environment"])
        if not environment.is_absolute() or ".." in environment.parts or environment.parent.name != "environments":
            raise ValidationFailure("shared core locator has an invalid environment directory")
        return environment.parent.parent
    return data
