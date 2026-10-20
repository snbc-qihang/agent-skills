"""Bounded verification of an already built plugin; never invokes a build."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .artifact_io import ArtifactIO
from .validation import ValidationFailure
from .environment import AGENTS

_VERSION = re.compile(r"^\d+\.\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


BUILD_FORMAT_VERSION = "2.0"


MAX_BUILD_MANIFEST_BYTES = 1024 * 1024


MAX_BUILD_PAYLOAD_FILE_BYTES = 32 * 1024 * 1024


def verify_package(package_root: Path | str) -> dict:
    raw_package_root = Path(package_root)
    if raw_package_root.is_symlink() or (raw_package_root.exists() and getattr(raw_package_root.lstat(), "st_file_attributes", 0) & 0x400):
        raise ValidationFailure("package root cannot be a symlink")
    package_root = raw_package_root.resolve()
    manifest_path = package_root / "package-manifest.json"
    storage = ArtifactIO(package_root, ".")
    try:
        manifest = storage.read_json_limited(MAX_BUILD_MANIFEST_BYTES, "package-manifest.json")[0]
    except FileNotFoundError as exc:
        raise ValidationFailure(f"missing package manifest: {manifest_path}") from exc
    finally:
        storage.close()
    _validate_build_manifest(manifest, package_root)
    actual = _file_digests(package_root, exclude={"package-manifest.json"},
                           native_git_metadata=manifest["platform"] == "hermes")
    if actual != manifest.get("payload_files"):
        raise ValidationFailure("package payload differs from its build manifest")
    digest = hashlib.sha256(
        "\n".join(f"{path}:{value}" for path, value in actual.items()).encode("utf-8")
    ).hexdigest()
    if f"sha256:{digest}" != manifest.get("payload_digest"):
        raise ValidationFailure("package payload digest differs from its build manifest")
    from .shared_core import make_core_descriptor, read_core_descriptor
    descriptor = read_core_descriptor(package_root / "engineering-assistant") if manifest.get("build_format_version") == "2.0" else None
    if descriptor is not None and descriptor != make_core_descriptor(actual, manifest["canonical_version"], manifest["target"]):
        raise ValidationFailure("shared core contract differs from the distribution payload")
    if manifest.get("build_format_version") == "2.0":
        from .environment import (
            AGENTS,
            PYTHON_VERSION,
            TARGETS,
            _package_lock,
            _read_control,
            environment_key,
        )
        from ..platforms.native_launcher import _binary_target
        lock = _read_control(package_root / "engineering-assistant/runtime-lock.json")
        if isinstance(lock, dict) and lock.get("schema_version") == "1":
            # Existing native caches remain verifiable for backup and restore.
            # Preparation separately requires the artifact-bound v2 contract.
            fields = {"schema_version", "agent", "target", "canonical_version", "python_version",
                      "requirements_digest", "environment_key"}
            if (set(lock) != fields or any(not isinstance(value, str) for value in lock.values())
                or lock["agent"] not in AGENTS or lock["target"] not in TARGETS
                or lock["python_version"] != PYTHON_VERSION
                or re.fullmatch(r"[0-9a-f]{64}", lock["requirements_digest"]) is None
                or lock["environment_key"] != environment_key(lock["canonical_version"], lock["python_version"],
                                                           lock["requirements_digest"], lock["target"])):
                raise ValidationFailure("invalid legacy native Runtime contract")
        elif isinstance(lock, dict) and lock.get("schema_version") == "2":
            if "engineering-assistant/runtime-python-downloads.json" not in actual:
                raise ValidationFailure("package is missing its fixed Python artifact metadata")
            lock = _package_lock(package_root)
        else:
            raise ValidationFailure("unsupported native Runtime contract")
        if (lock["agent"] != manifest["platform"] or lock["target"] != manifest["target"]
            or lock["canonical_version"] != manifest["canonical_version"]
            or lock["environment_key"] != manifest["runtime_environment_key"]):
            raise ValidationFailure("Runtime contract differs from its package manifest")
        requirements_digest = actual["engineering-assistant/runtime-requirements.txt"]
        if requirements_digest != "sha256:" + lock["requirements_digest"]:
            raise ValidationFailure("Runtime dependency lock differs from its package manifest")
        native = package_root / "engineering-assistant/bin" / ("ea.exe" if manifest["target"] == "windows-x64" else "ea")
        if _binary_target(native) != manifest["target"]:
            raise ValidationFailure("native launcher target differs from its package manifest")
    return manifest


def _validate_build_manifest(manifest: object, package_root: Path) -> None:
    required = {
        "build_format_version",
        "status",
        "platform",
        "canonical_version",
        "skill_versions",
        "skill_count",
        "flow_count",
        "pack_count",
        "policy_count",
        "provider_count",
        "source_count",
        "payload_digest",
        "payload_files",
    }
    previous_required = required - {"build_format_version", "source_count"}
    native_required = required | {"target", "runtime_environment_key"}
    if not isinstance(manifest, dict) or set(manifest) not in (
        required,
        previous_required,
        native_required,
    ):
        raise ValidationFailure("package manifest does not match the builder contract")
    previous_contract = set(manifest) == previous_required
    native_contract = set(manifest) == native_required
    if (
        (not previous_contract and manifest["build_format_version"] != (BUILD_FORMAT_VERSION if native_contract else "1.0"))
        or manifest["status"] != "built"
        or manifest["platform"] not in AGENTS
        or not isinstance(manifest["canonical_version"], str)
        or _VERSION.fullmatch(manifest["canonical_version"]) is None
        or not isinstance(manifest["skill_versions"], dict)
        or not isinstance(manifest["payload_files"], dict)
        or not isinstance(manifest["payload_digest"], str)
    ):
        raise ValidationFailure("package manifest does not match the builder contract")
    if native_contract:
        from .environment import TARGETS
        if manifest["target"] not in TARGETS or not isinstance(manifest["runtime_environment_key"], str) or re.fullmatch(r"[0-9a-f]{64}", manifest["runtime_environment_key"]) is None:
            raise ValidationFailure("package native Runtime target is invalid")
    count_keys = [
        "skill_count",
        "flow_count",
        "pack_count",
        "policy_count",
        "provider_count",
    ]
    if not previous_contract:
        count_keys.append("source_count")
    if any(
        not isinstance(manifest[key], int)
        or isinstance(manifest[key], bool)
        or manifest[key] < 0
        for key in count_keys
    ) or len(manifest["skill_versions"]) != manifest["skill_count"]:
        raise ValidationFailure("package manifest counts are invalid")
    if _DIGEST.fullmatch(manifest["payload_digest"]) is None:
        raise ValidationFailure("package manifest digest is invalid")
    for relative, digest in manifest["payload_files"].items():
        if not isinstance(relative, str) or not isinstance(digest, str):
            raise ValidationFailure("package manifest payload entry is invalid")
        candidate = Path(relative)
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or _DIGEST.fullmatch(digest) is None
        ):
            raise ValidationFailure("package manifest payload entry is invalid")
    required_layouts = {
        "codex": (
            ".codex-plugin/plugin.json",
            ".mcp.json",
            "hooks/hooks.json",
            "hooks/feedback_capture.py",
        ),
        "hermes": ("plugin.yaml", "__init__.py"),
        "cursor": (".cursor-plugin/plugin.json", "mcp.json", "hooks/hooks.json"),
        "claude-code": (
            ".claude-plugin/plugin.json",
            ".mcp.json",
            "hooks/hooks.json",
            "hooks/feedback_capture.py",
        ),
    }
    required_files = required_layouts[manifest["platform"]]
    if native_contract:
        executable = "ea.exe" if manifest["target"] == "windows-x64" else "ea"
        required_files += (f"engineering-assistant/bin/{executable}", "engineering-assistant/runtime_boot.py",
                           "engineering-assistant/runtime-lock.json", "engineering-assistant/runtime-requirements.txt")
    if any(
        relative not in manifest["payload_files"]
        or not (package_root / relative).is_file()
        for relative in required_files
    ):
        raise ValidationFailure("package is missing its required platform layout")


def _file_digests(root: Path, exclude: set[str] | None = None,
                  native_git_metadata: bool = False) -> dict[str, str]:
    exclude = exclude or set()
    storage = ArtifactIO(root, ".")
    try:
        if native_git_metadata and storage.entry_exists(".git"):
            # Hermes owns this native clone metadata. Traverse it with the same
            # bounds and no-follow rules; exclude only its top-level namespace
            # from the precompiled payload contract, never plugin files.
            with storage.open_directory(".git"):
                pass
        return {name: digest for name, digest in storage.sha256_file_digests(
            max_file_bytes=MAX_BUILD_PAYLOAD_FILE_BYTES, max_entries=4096,
            max_total_bytes=256 * 1024 * 1024).items()
            if name not in exclude and not (native_git_metadata and name.startswith(".git/"))}
    finally:
        storage.close()
