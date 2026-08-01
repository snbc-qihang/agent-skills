"""Validation for a project-owned domain-design source registry."""

from __future__ import annotations

from pathlib import Path

from .validation import ValidationFailure, load_json, validate_instance


def validate_design_source_registry(
    project_root: Path | str,
    design_source_ref: str,
    schema_root: Path | str,
    *,
    allow_legacy: bool = False,
) -> dict:
    root = Path(project_root).resolve()
    relative = Path(design_source_ref)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValidationFailure("design_source_ref must be a project-relative path")
    registry_path = (root / relative).resolve()
    if registry_path.parent != root and root not in registry_path.parents:
        raise ValidationFailure("design_source_ref escapes project_root")
    if not registry_path.is_file():
        raise ValidationFailure("design_source_ref does not identify an existing file")
    registry = load_json(registry_path)
    validate_instance(
        registry,
        load_json(Path(schema_root) / "design-source-registry.schema.json"),
        "design-source-registry",
    )
    if registry["version"] == "1":
        if not allow_legacy:
            raise ValidationFailure("new domain-design runs require DesignSourceRegistry version 2")
        return registry
    _validate_v2_sources(root, registry["sources"])
    return registry


_SOURCE_KINDS = {
    "requirements",
    "repository",
    "existing-design",
    "interfaces",
    "data",
    "deployment",
}
_REQUIRED_AVAILABLE_KINDS = {"requirements", "repository"}


def _validate_v2_sources(root: Path, sources: list[dict]) -> None:
    kinds = [source["kind"] for source in sources]
    if set(kinds) != _SOURCE_KINDS or len(kinds) != len(set(kinds)):
        raise ValidationFailure("DesignSourceRegistry version 2 requires one source for each required kind")
    for source in sources:
        kind = source["kind"]
        path = source["path"]
        status = source["status"]
        if kind in _REQUIRED_AVAILABLE_KINDS and status != "available":
            raise ValidationFailure(f"DesignSourceRegistry requires an available {kind} source")
        if path is None:
            continue
        candidate = _resolve_source_path(root, path)
        if status == "available" and not candidate.exists():
            raise ValidationFailure(f"available {kind} source path does not exist")


def _resolve_source_path(root: Path, path: str) -> Path:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValidationFailure("source path must be project-relative")
    candidate = (root / relative).resolve()
    if candidate.parent != root and root not in candidate.parents:
        raise ValidationFailure("source path escapes project_root")
    return candidate
