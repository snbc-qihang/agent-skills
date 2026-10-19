"""Deterministic compiler from the platform-neutral authoring tree."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path

from ..platforms.adapters import ClaudeCodeAdapter, CodexAdapter, HermesAdapter
from ..runtime.artifact_io import ArtifactIO
from ..runtime.catalog import load_catalog
from ..runtime.validation import ValidationFailure


ADAPTERS = {
    "claude-code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "hermes": HermesAdapter,
}


from ..runtime.package import (
    BUILD_FORMAT_VERSION, MAX_BUILD_MANIFEST_BYTES, MAX_BUILD_PAYLOAD_FILE_BYTES, verify_package, _validate_build_manifest, _file_digests
)

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
    from ..platforms.native_launcher import host_target
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
    from ..runtime.environment import runtime_lock, python_download_metadata
    from ..platforms.native_launcher import build_launcher
    output = _BuildPath(output_io)
    _copy_tree(repository_root / "skills", output / "skills")
    runtime_root = output / "engineering-assistant"
    _copy_tree(repository_root / "catalog", runtime_root / "catalog")
    _copy_tree(repository_root / "schemas", runtime_root / "schemas")
    _copy_tree(repository_root / "packs", runtime_root / "packs")
    package_source = repository_root / "src/engineering_assistant"
    package_output = runtime_root / "runtime/engineering_assistant"
    package_output.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "cli.py"):
        (package_output / name).write_bytes((package_source / name).read_bytes())
    for name in ("runtime", "platforms"):
        _copy_tree(package_source / name, package_output / name)
    repository_io = ArtifactIO(repository_root, ".")
    try:
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            (output / name).write_bytes(repository_io.read_bytes_limited(MAX_BUILD_PAYLOAD_FILE_BYTES, name))
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
