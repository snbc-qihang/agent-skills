"""Deterministic compiler from the platform-neutral authoring tree."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path

from .adapters import CodexAdapter, HermesAdapter
from .artifact_io import ArtifactIO
from .catalog import load_catalog
from .validation import ValidationFailure


ADAPTERS = {"codex": CodexAdapter, "hermes": HermesAdapter}
BUILD_FORMAT_VERSION = "1.0"
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
) -> dict:
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
) -> dict:
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
    launcher = runtime_root / "bin/ea"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))\n"
        "from engineering_assistant.cli import main\n"
        "raise SystemExit(main())\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    adapter = ADAPTERS[platform](cachebuster=codex_cachebuster) if platform == "codex" else ADAPTERS[platform]()
    adapter.write_platform_files(output, catalog)
    payload_files = output_io.sha256_file_digests(
        max_file_bytes=MAX_BUILD_PAYLOAD_FILE_BYTES,
    )
    payload_digest = hashlib.sha256(
        "\n".join(f"{path}:{digest}" for path, digest in payload_files.items()).encode("utf-8")
    ).hexdigest()
    report = {
        "build_format_version": BUILD_FORMAT_VERSION,
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
    if raw_package_root.is_symlink():
        raise ValidationFailure("package root cannot be a symlink")
    package_root = raw_package_root.resolve()
    manifest_path = package_root / "package-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValidationFailure(f"missing package manifest: {manifest_path}")
    if manifest_path.stat().st_size > MAX_BUILD_MANIFEST_BYTES:
        raise ValidationFailure("package manifest is too large")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationFailure("package manifest contains invalid JSON") from exc
    _validate_build_manifest(manifest, package_root)
    actual = _file_digests(package_root, exclude={"package-manifest.json"})
    if actual != manifest.get("payload_files"):
        raise ValidationFailure("package payload differs from its build manifest")
    digest = hashlib.sha256(
        "\n".join(f"{path}:{value}" for path, value in actual.items()).encode("utf-8")
    ).hexdigest()
    if f"sha256:{digest}" != manifest.get("payload_digest"):
        raise ValidationFailure("package payload digest differs from its build manifest")
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
    if not isinstance(manifest, dict) or set(manifest) not in (
        required,
        previous_required,
    ):
        raise ValidationFailure("package manifest does not match the builder contract")
    previous_contract = set(manifest) == previous_required
    if (
        (not previous_contract and manifest["build_format_version"] != BUILD_FORMAT_VERSION)
        or manifest["status"] != "built"
        or manifest["platform"] not in ADAPTERS
        or not isinstance(manifest["canonical_version"], str)
        or _VERSION.fullmatch(manifest["canonical_version"]) is None
        or not isinstance(manifest["skill_versions"], dict)
        or not isinstance(manifest["payload_files"], dict)
        or not isinstance(manifest["payload_digest"], str)
    ):
        raise ValidationFailure("package manifest does not match the builder contract")
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
    }
    required_files = required_layouts[manifest["platform"]]
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


def _file_digests(root: Path, exclude: set[str] | None = None) -> dict[str, str]:
    exclude = exclude or set()
    result: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        result[relative] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return result
