"""Validation for a project-owned domain-design source registry."""

from __future__ import annotations

from pathlib import Path

from .validation import ValidationFailure, load_json, validate_instance


def validate_design_source_registry(
    project_root: Path | str,
    design_source_ref: str,
    schema_root: Path | str,
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
    return registry
