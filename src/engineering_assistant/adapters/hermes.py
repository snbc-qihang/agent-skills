"""Hermes packaging adapter."""

from __future__ import annotations

from pathlib import Path

from ..catalog import Catalog
from ..version import platform_version


class HermesAdapter:
    id = "hermes"

    def write_platform_files(self, package_root: Path, catalog: Catalog) -> list[Path]:
        plugin_yaml = package_root / "plugin.yaml"
        version = platform_version(catalog.version, supports_four_part=False)
        plugin_yaml.write_text(
            "name: engineering-assistant\n"
            f'version: "{version}"\n'
            f'canonical_version: "{catalog.version}"\n'
            'skill_versions_source: "engineering-assistant/catalog/skills/public.json"\n'
            'description: "基于证据的工程原语、受治理流程、状态恢复和人工审批门禁。"\n'
            'author: "sunliming625@gmail.com"\n'
            "kind: standalone\n"
            "platforms:\n"
            "  - linux\n"
            "  - macos\n"
            "  - windows\n",
            encoding="utf-8",
        )
        entrypoint = package_root / "__init__.py"
        entrypoint.write_text(
            '"""Generated Hermes adapter for engineering-assistant."""\n\n'
            "from pathlib import Path\n\n\n"
            "def register(ctx) -> None:\n"
            "    skills_root = Path(__file__).resolve().parent / 'skills'\n"
            "    for skill_md in sorted(skills_root.glob('*/SKILL.md')):\n"
            "        ctx.register_skill(skill_md.parent.name, skill_md)\n",
            encoding="utf-8",
        )
        return [plugin_yaml, entrypoint]
