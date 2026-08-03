"""Create and recheck immutable v2 domain-design source intake artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .design_sources import validate_design_source_registry
from .validation import ValidationFailure


_KINDS = {"requirements", "repository", "existing-design", "interfaces", "data", "deployment"}


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
    else:
        for item in sorted(path.rglob("*")):
            if item.is_file():
                digest.update(item.relative_to(path).as_posix().encode())
                digest.update(item.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def _safe_member(root: Path, value: str, label: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValidationFailure(f"{label} must be a relative path")
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValidationFailure(f"{label} escapes its root")
    return candidate


def intake_design_sources(
    project_root: Path | str,
    source_root: Path | str,
    registry: Mapping[str, Any],
    *,
    schema_root: Path | str,
    intake_id: str,
) -> dict[str, Any]:
    """Copy declared external inputs into project runtime artifacts and emit v2 registry."""
    project = Path(project_root).resolve()
    external = Path(source_root).resolve()
    if not project.is_dir() or not external.is_dir():
        raise ValidationFailure("project_root and source_root must be existing directories")
    if not intake_id or "/" in intake_id or ".." in intake_id:
        raise ValidationFailure("intake_id is unsafe")
    sources = registry.get("sources")
    if not isinstance(sources, list) or {item.get("kind") for item in sources if isinstance(item, dict)} != _KINDS:
        raise ValidationFailure("source intake requires exactly one source for each v2 kind")
    frozen = json.loads(json.dumps(registry))
    frozen["version"] = "2"
    artifact_root = project / ".run-artifacts" / "engineering-assistant" / "design-inputs" / intake_id
    if artifact_root.exists():
        raise ValidationFailure(f"design input intake already exists: {intake_id}")
    snapshots: list[dict[str, str]] = []
    for source in frozen["sources"]:
        status = source.get("status")
        path = source.get("path")
        if status != "available":
            source["path"] = None
            continue
        if not isinstance(path, str):
            raise ValidationFailure(f"available {source.get('kind')} source has no path")
        original = _safe_member(external, path, "source path")
        if not original.exists():
            raise ValidationFailure(f"source path does not exist: {path}")
        destination = artifact_root / "sources" / source["kind"] / original.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if original.is_dir():
            shutil.copytree(original, destination)
        else:
            shutil.copy2(original, destination)
        source["path"] = destination.relative_to(project).as_posix()
        snapshots.append({"kind": source["kind"], "source_path": path, "digest": _digest(original)})
    registry_path = artifact_root / "design-source-registry.json"
    registry_path.write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "intake_id": intake_id,
        "registry": registry_path.relative_to(project).as_posix(),
        "source_root": str(external),
        "sources": snapshots,
    }
    (artifact_root / "intake-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    validate_design_source_registry(project, manifest["registry"], schema_root)
    return {"registry": manifest["registry"], "intake": manifest, "status": "frozen"}


def recheck_design_sources(project_root: Path | str, registry_ref: str) -> dict[str, Any]:
    """Compare the frozen external source digests before a design review is submitted."""
    project = Path(project_root).resolve()
    registry_path = _safe_member(project, registry_ref, "design_source_ref")
    manifest_path = registry_path.parent / "intake-manifest.json"
    if not manifest_path.is_file():
        raise ValidationFailure("design source registry has no intake manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    external = Path(manifest["source_root"]).resolve()
    changed = []
    for item in manifest["sources"]:
        current = _safe_member(external, item["source_path"], "source path")
        if not current.exists() or _digest(current) != item["digest"]:
            changed.append(item["kind"])
    return {"status": "stale" if changed else "current", "changed_kinds": changed}
