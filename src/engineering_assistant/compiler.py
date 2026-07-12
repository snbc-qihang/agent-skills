"""Deterministic compiler from the platform-neutral authoring tree."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .adapters import CodexAdapter, HermesAdapter
from .catalog import load_catalog
from .validation import ValidationFailure


ADAPTERS = {"codex": CodexAdapter, "hermes": HermesAdapter}


def build_package(
    repository_root: Path | str,
    platform: str,
    output: Path | str,
    *,
    replace: bool = False,
    codex_cachebuster: str | None = None,
) -> dict:
    repository_root = Path(repository_root).resolve()
    output = Path(output).resolve()
    if platform not in ADAPTERS:
        raise ValidationFailure(f"unsupported platform {platform}")
    if codex_cachebuster and platform != "codex":
        raise ValidationFailure("codex_cachebuster is only valid for Codex packages")
    catalog = load_catalog(repository_root, require_sources=True)
    if output == repository_root or repository_root in output.parents:
        raise ValidationFailure("build output must be outside the repository authoring tree")
    if output.exists():
        if not replace:
            raise FileExistsError(f"build output already exists: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True)

    _copy_tree(repository_root / "skills", output / "skills")
    runtime_root = output / "engineering-assistant"
    _copy_tree(repository_root / "catalog", runtime_root / "catalog")
    _copy_tree(repository_root / "schemas", runtime_root / "schemas")
    _copy_tree(repository_root / "packs", runtime_root / "packs")
    _copy_tree(repository_root / "evals", runtime_root / "evals")
    _copy_tree(repository_root / "src/engineering_assistant", runtime_root / "runtime/engineering_assistant")
    shutil.copy2(repository_root / "VERSIONING.md", runtime_root / "VERSIONING.md")
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
    payload_files = _file_digests(output)
    payload_digest = hashlib.sha256(
        "\n".join(f"{path}:{digest}" for path, digest in payload_files.items()).encode("utf-8")
    ).hexdigest()
    report = {
        "status": "built",
        "platform": platform,
        "canonical_version": catalog.version,
        "skill_versions": {skill.id: skill.version for skill in catalog.skills.values()},
        "skill_count": len(catalog.skills),
        "flow_count": len(catalog.flows),
        "pack_count": len(catalog.packs),
        "policy_count": len(catalog.policies),
        "provider_count": len(catalog.providers),
        "payload_digest": f"sha256:{payload_digest}",
        "payload_files": payload_files,
    }
    (output / "package-manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**report, "output": str(output)}


def verify_package(package_root: Path | str) -> dict:
    package_root = Path(package_root).resolve()
    manifest_path = package_root / "package-manifest.json"
    if not manifest_path.is_file():
        raise ValidationFailure(f"missing package manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = _file_digests(package_root, exclude={"package-manifest.json"})
    if actual != manifest.get("payload_files"):
        raise ValidationFailure("package payload differs from its build manifest")
    digest = hashlib.sha256(
        "\n".join(f"{path}:{value}" for path, value in actual.items()).encode("utf-8")
    ).hexdigest()
    if f"sha256:{digest}" != manifest.get("payload_digest"):
        raise ValidationFailure("package payload digest differs from its build manifest")
    return manifest


def _copy_tree(source: Path, target: Path) -> None:
    if not source.is_dir():
        raise ValidationFailure(f"missing compiler input {source}")
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def _file_digests(root: Path, exclude: set[str] | None = None) -> dict[str, str]:
    exclude = exclude or set()
    result: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        result[relative] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return result
