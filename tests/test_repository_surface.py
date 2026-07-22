from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.compiler import build_package  # noqa: E402


HAN = re.compile(r"[\u4e00-\u9fff]")


class RepositorySurfaceTests(unittest.TestCase):
    def test_ci_bootstraps_pinned_official_validators_for_clean_runner(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("branches: [main, teamwork]", workflow)
        self.assertIn(
            "openai/skills/49f948faa9258a0c61caceaf225e179651397431/"
            "skills/.system/skill-creator/scripts/quick_validate.py",
            workflow,
        )
        self.assertIn(
            "openai/codex/963cda85aa2a4cfb85e52d771d22d9f3069951fa/"
            "codex-rs/skills/src/assets/samples/plugin-creator/scripts/validate_plugin.py",
            workflow,
        )
        self.assertIn(
            "6cc9dc3199c935916cf6f73fcbbbb0e3bb1b58c8f5109fefa499978908164f51",
            workflow,
        )
        self.assertIn(
            "ebda00d55d7518b127f675f062fb5c6e7a1ffdc0a99df1a55ac594400d7d3228",
            workflow,
        )
        self.assertIn(
            '$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py',
            workflow,
        )
        self.assertIn(
            '$HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py',
            workflow,
        )
        self.assertIn('uv==0.11.7', workflow)
        self.assertIn('"$HOME/.local/bin/uv" --version', workflow)

    def test_repository_contains_only_current_product_surfaces(self) -> None:
        catalog = load_catalog(ROOT, require_sources=True)
        absent = [
            "generator",
            "engineering-assistant",
            "effectiveness-evals",
            "artifacts",
            ".agent",
            "v4",
            "docs/migration",
            "docs/decisions",
            "docs/research",
            "src/engineering_assistant/migration.py",
            "src/engineering_assistant/publisher.py",
        ]
        for relative in absent:
            self.assertFalse((ROOT / relative).exists(), relative)

        self.assertEqual(
            set(catalog.skills),
            {path.name for path in (ROOT / "skills").iterdir() if path.is_dir()},
        )
        self.assertEqual(
            {pack.source_path for pack in catalog.packs.values()},
            {path.relative_to(ROOT).as_posix() for path in (ROOT / "packs").glob("*.md")},
        )
        self.assertEqual([ROOT / ".github/workflows/ci.yml"], list((ROOT / ".github/workflows").glob("*.yml")))

    def test_active_sources_have_no_upgrade_process_dependencies(self) -> None:
        active_files = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "VERSIONING.md"]
        for base in [ROOT / "catalog", ROOT / "config", ROOT / "src", ROOT / "scripts", ROOT / ".github"]:
            active_files.extend(
                path
                for path in base.rglob("*")
                if path.is_file() and path.suffix in {".md", ".json", ".py", ".yml", ".yaml", ".toml"}
            )
        corpus = "\n".join(path.read_text(encoding="utf-8") for path in active_files)
        forbidden = [
            "docs/migration",
            "legacy-skills.json",
            "validate_legacy_migration",
            "HISTORICAL_V3_MAPPING",
            "402fe0625e449eff5080e0af20eb8caf77fe82be",
            "implementation-backlog",
            "decision-matrix",
        ]
        for marker in forbidden:
            self.assertNotIn(marker, corpus, marker)

    def test_public_skills_and_packs_are_simplified_chinese(self) -> None:
        catalog = load_catalog(ROOT, require_sources=True)
        for skill in catalog.skills.values():
            self.assertRegex(skill.description or "", HAN, skill.id)
            source = ROOT / skill.source_path / "SKILL.md"
            text = source.read_text(encoding="utf-8")
            self.assertRegex(text, HAN, source)
            self.assertIn(f"description: {skill.description}", text)
        for pack in catalog.packs.values():
            self.assertRegex((ROOT / pack.source_path).read_text(encoding="utf-8"), HAN, pack.id)

    def test_platform_metadata_uses_the_configured_developer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            hermes = root / "hermes"
            build_package(ROOT, "codex", codex)
            build_package(ROOT, "hermes", hermes)
            manifest = json.loads((codex / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
            self.assertEqual("sunliming625@gmail.com", manifest["author"]["email"])
            self.assertEqual("sunliming625@gmail.com", manifest["interface"]["developerName"])
            self.assertIn('author: "sunliming625@gmail.com"', (hermes / "plugin.yaml").read_text(encoding="utf-8"))

        cases = json.loads((ROOT / "evals/routing/cases.json").read_text(encoding="utf-8"))
        languages = {item["language"] for group in cases["groups"] for item in group["requests"]}
        self.assertEqual({"zh-CN", "en"}, languages)


if __name__ == "__main__":
    unittest.main()
