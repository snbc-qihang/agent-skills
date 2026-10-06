"""Deterministic compiler from the platform-neutral authoring tree."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path

from .adapters import ClaudeCodeAdapter, CodexAdapter, HermesAdapter
from .artifact_io import ArtifactIO
from .catalog import load_catalog
from .validation import ValidationFailure


ADAPTERS = {
    "claude-code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "hermes": HermesAdapter,
}
BUILD_FORMAT_VERSION = "2.0"
MAX_BUILD_MANIFEST_BYTES = 1024 * 1024
MAX_BUILD_PAYLOAD_FILE_BYTES = 32 * 1024 * 1024
_VERSION = re.compile(r"^\d+\.\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class _BuildPath:
    """Minimal Path-like writer backed by an anchored ArtifactIO root."""

    def __init__(self, artifact_io: ArtifactIO, parts: tuple[str, ...] = ()) -> None:
        self._artifact_io = artifact_io
        self._parts = parts

    def __truediv__(self, child: str) -> "_BuildPath":
        return _BuildPath(self._artifact_io, (*self._parts, child))

    @property
    def parent(self) -> "_BuildPath":
        return _BuildPath(self._artifact_io, self._parts[:-1])

    def mkdir(self, *, parents: bool = False, exist_ok: bool = False) -> None:
        del parents, exist_ok
        self._artifact_io.ensure_directory(*self._parts)

    def write_bytes(self, payload: bytes, *, mode: int = 0o600) -> int:
        self._artifact_io.write_bytes_exclusive(
            payload,
            *self._parts,
            mode=mode,
        )
        return len(payload)

    def write_text(self, text: str, *, encoding: str) -> int:
        return self.write_bytes(text.encode(encoding))

    def chmod(self, mode: int) -> None:
        self._artifact_io.chmod_regular_file(mode, *self._parts)

    def directory_io(self) -> ArtifactIO:
        with self._artifact_io.open_directory(*self._parts) as descriptor:
            return ArtifactIO.from_open_directory_fd(
                self._artifact_io.path(*self._parts),
                descriptor,
            )


def build_package(
    repository_root: Path | str,
    platform: str,
    output: Path | str,
    *,
    replace: bool = False,
    codex_cachebuster: str | None = None,
    target: str | None = None,
) -> dict:
    from .native_launcher import host_target
    target = target or host_target()
    repository_root = Path(repository_root).resolve()
    raw_output = Path(output).absolute()
    if raw_output.is_symlink():
        raise ValidationFailure("build output cannot be a symlink")
    if not raw_output.parent.is_dir():
        raise ValidationFailure("build output parent must already exist")
    output_parent = raw_output.parent.resolve()
    output = output_parent / raw_output.name
    if platform not in ADAPTERS:
        raise ValidationFailure(f"unsupported platform {platform}")
    if codex_cachebuster and platform != "codex":
        raise ValidationFailure("codex_cachebuster is only valid for Codex packages")
    catalog = load_catalog(repository_root, require_sources=True)
    if (
        output == repository_root
        or repository_root in output.parents
        or output in repository_root.parents
    ):
        raise ValidationFailure("build output must be outside the repository authoring tree")
    output_io = ArtifactIO(output_parent, ".")
    output_io.assert_runtime_target(repository_root / "schemas")
    if output_io.entry_exists(output.name):
        if not replace:
            raise FileExistsError(f"build output already exists: {output}")
        raise ValidationFailure(
            "build replacement is non-destructive; choose a new empty output directory"
        )
    temporary_name = ""
    temporary_io = None
    temporary_metadata = None
    for _attempt in range(16):
        temporary_name = (
            f".engineering-assistant-build-{secrets.token_hex(12)}"
        )
        try:
            temporary_root, temporary_fd, temporary_metadata = (
                output_io.create_directory_exclusive_open(temporary_name)
            )
        except FileExistsError:
            continue
        temporary_io = ArtifactIO.from_open_directory_fd(
            temporary_root,
            temporary_fd,
        )
        os.close(temporary_fd)
        break
    else:
        raise ValidationFailure("unable to reserve a temporary build directory")

    working, working_fd, _working_metadata = (
        temporary_io.create_directory_exclusive_open("package")
    )
    working_io = ArtifactIO.from_open_directory_fd(working, working_fd)
    try:
        report = _compile_package(
            repository_root,
            platform,
            working_io,
            catalog,
            codex_cachebuster,
            target,
        )
        _output_path, output_fd, output_metadata = (
            output_io.create_directory_exclusive_open(output.name)
        )
        final_io = ArtifactIO.from_open_directory_fd(output, output_fd)
        os.close(output_fd)
        try:
            working_io.copy_contents_to(
                final_io,
                max_file_bytes=MAX_BUILD_PAYLOAD_FILE_BYTES,
            )
            if not output_io.child_directory_matches(output.name, output_metadata):
                raise ValidationFailure("build output directory identity changed")
        except Exception:
            try:
                final_io.remove_all_contents()
                output_io.remove_child_directory_if_matches(
                    output.name,
                    output_metadata,
                )
            except Exception:
                pass
            raise
        finally:
            final_io.close()
        return {**report, "output": str(output)}
    finally:
        os.close(working_fd)
        working_io.close()
        try:
            temporary_io.remove_all_contents()
            output_io.remove_child_directory_if_matches(
                temporary_name,
                temporary_metadata,
            )
        except Exception:
            pass
        temporary_io.close()


def _compile_package(
    repository_root: Path,
    platform: str,
    output_io: ArtifactIO,
    catalog,
    codex_cachebuster: str | None,
    target: str,
) -> dict:
    from .installation import runtime_lock, python_download_metadata
    from .native_launcher import build_launcher
    output = _BuildPath(output_io)
    _copy_tree(repository_root / "skills", output / "skills")
    runtime_root = output / "engineering-assistant"
    _copy_tree(repository_root / "catalog", runtime_root / "catalog")
    _copy_tree(repository_root / "schemas", runtime_root / "schemas")
    _copy_tree(repository_root / "packs", runtime_root / "packs")
    _copy_tree(repository_root / "evals", runtime_root / "evals")
    _copy_tree(repository_root / "src/engineering_assistant", runtime_root / "runtime/engineering_assistant")
    repository_io = ArtifactIO(repository_root, ".")
    try:
        (runtime_root / "VERSIONING.md").write_bytes(
            repository_io.read_bytes_limited(
                MAX_BUILD_PAYLOAD_FILE_BYTES,
                "VERSIONING.md",
            )
        )
    finally:
        repository_io.close()
    lock, requirements = runtime_lock(repository_root, platform, target, catalog.version)
    (runtime_root / "runtime-lock.json").write_text(json.dumps(lock, sort_keys=True) + "\n", encoding="utf-8")
    (runtime_root / "runtime-requirements.txt").write_bytes(requirements)
    (runtime_root / "runtime-python-downloads.json").write_bytes(python_download_metadata(lock))
    _copy_tree(repository_root / "config", runtime_root / "config")
    (runtime_root / "runtime_boot.py").write_bytes((repository_root / "src/engineering_assistant/runtime_boot.py").read_bytes())
    launcher = runtime_root / ("bin/ea.exe" if target == "windows-x64" else "bin/ea")
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(build_launcher(repository_root, target).read_bytes())
    launcher.chmod(0o755)

    adapter = ADAPTERS[platform](cachebuster=codex_cachebuster, target=target) if platform == "codex" else ADAPTERS[platform](target=target)
    adapter.write_platform_files(output, catalog)
    payload_files = output_io.sha256_file_digests(
        max_file_bytes=MAX_BUILD_PAYLOAD_FILE_BYTES,
    )
    payload_digest = hashlib.sha256(
        "\n".join(f"{path}:{digest}" for path, digest in payload_files.items()).encode("utf-8")
    ).hexdigest()
    report = {
        "build_format_version": BUILD_FORMAT_VERSION,
        "target": target,
        "runtime_environment_key": lock["environment_key"],
        "status": "built",
        "platform": platform,
        "canonical_version": catalog.version,
        "skill_versions": {skill.id: skill.version for skill in catalog.skills.values()},
        "skill_count": len(catalog.skills),
        "flow_count": len(catalog.flows),
        "pack_count": len(catalog.packs),
        "policy_count": len(catalog.policies),
        "provider_count": len(catalog.providers),
        "source_count": len(catalog.sources),
        "payload_digest": f"sha256:{payload_digest}",
        "payload_files": payload_files,
    }
    (output / "package-manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


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
    if manifest.get("build_format_version") == "2.0":
        from .installation import AGENTS, PYTHON_VERSION, TARGETS, _package_lock, _read_control, environment_key
        from .native_launcher import _binary_target
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
        or manifest["platform"] not in ADAPTERS
        or not isinstance(manifest["canonical_version"], str)
        or _VERSION.fullmatch(manifest["canonical_version"]) is None
        or not isinstance(manifest["skill_versions"], dict)
        or not isinstance(manifest["payload_files"], dict)
        or not isinstance(manifest["payload_digest"], str)
    ):
        raise ValidationFailure("package manifest does not match the builder contract")
    if native_contract:
        from .installation import TARGETS
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


def _copy_tree(source: Path, target: _BuildPath) -> None:
    if not source.is_dir():
        raise ValidationFailure(f"missing compiler input {source}")
    target.mkdir(parents=True)
    destination = target.directory_io()
    source_io = ArtifactIO(source, ".")
    try:
        source_io.copy_contents_to(
            destination,
            max_file_bytes=MAX_BUILD_PAYLOAD_FILE_BYTES,
            ignored_names=frozenset({"__pycache__", ".DS_Store"}),
            ignored_suffixes=(".pyc",),
        )
    finally:
        source_io.close()
        destination.close()


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
