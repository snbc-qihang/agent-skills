#!/usr/bin/env python3
"""Validate Engineering Assistant project/module overlay hierarchy files."""

from pathlib import Path
import json
import sys

ROOT = Path("/Users/fengtianyangyang/.codex/skills/engineering-assistant-overlay")
PROJECT_ROOT = ROOT / "project-overlays" / "projects"
TEMPLATES = [
    ROOT / "templates" / "project-overlay.template.json",
    ROOT / "templates" / "module-overlay.template.json",
]
REFERENCE = ROOT / "references" / "overlay-scope-hierarchy.md"

COMMON_REQUIRED = {
    "overlay_layer",
    "project_slug",
    "applies_to",
    "rules",
    "gates",
    "evidence_sources",
    "owner",
    "review_after",
}


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid json: {exc}") from exc


def require(condition, message, errors):
    if not condition:
        errors.append(message)


def validate_overlay(path, data, expected_layer, errors):
    is_template = "templates" in path.parts
    missing = sorted(COMMON_REQUIRED - set(data))
    require(not missing, f"{path}: missing fields {missing}", errors)
    require(data.get("overlay_layer") == expected_layer, f"{path}: expected overlay_layer={expected_layer}", errors)
    require(bool(data.get("project_slug")), f"{path}: project_slug required", errors)
    require(isinstance(data.get("rules"), list), f"{path}: rules must be list", errors)
    require(isinstance(data.get("gates"), list), f"{path}: gates must be list", errors)
    if expected_layer == "module":
        require(bool(data.get("module_slug")), f"{path}: module_slug required for module overlay", errors)
        if not is_template:
            require(path.stem == data.get("module_slug"), f"{path}: filename must match module_slug", errors)
    else:
        require("module_slug" not in data or not data.get("module_slug"), f"{path}: project overlay must not set module_slug", errors)
        if not is_template:
            require(path.parent.name == data.get("project_slug"), f"{path}: directory must match project_slug", errors)


def main():
    errors = []
    require(REFERENCE.exists(), f"{REFERENCE}: missing hierarchy reference", errors)
    for template in TEMPLATES:
        require(template.exists(), f"{template}: missing template", errors)
        if template.exists():
            expected = "module" if "module" in template.name else "project"
            validate_overlay(template, load_json(template), expected, errors)

    if PROJECT_ROOT.exists():
        for project_dir in sorted(p for p in PROJECT_ROOT.iterdir() if p.is_dir()):
            project_file = project_dir / "project-overlay.json"
            if project_file.exists():
                validate_overlay(project_file, load_json(project_file), "project", errors)
            modules_dir = project_dir / "modules"
            if modules_dir.exists():
                for module_file in sorted(modules_dir.glob("*.json")):
                    validate_overlay(module_file, load_json(module_file), "module", errors)

    if errors:
        print("INVALID_OVERLAY_HIERARCHY", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("VALID_OVERLAY_HIERARCHY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
