from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.compiler import build_package, verify_package  # noqa: E402


class CompilerAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_codex_and_hermes_packages_have_the_same_core(self) -> None:
        codex = self.root / "codex"
        hermes = self.root / "hermes"
        codex_report = build_package(ROOT, "codex", codex)
        hermes_report = build_package(ROOT, "hermes", hermes)
        self.assertEqual(11, codex_report["skill_count"])
        self.assertTrue((codex / ".codex-plugin/plugin.json").is_file())
        self.assertTrue((hermes / "plugin.yaml").is_file())
        self.assertTrue((hermes / "__init__.py").is_file())
        self.assertEqual(11, len(list((codex / "skills").glob("*/SKILL.md"))))
        self.assertEqual(11, len(list((hermes / "skills").glob("*/SKILL.md"))))
        self.assertFalse((codex / "engineering-assistant/generator").exists())
        verify_package(codex)
        verify_package(hermes)

        for source in sorted((ROOT / "skills").glob("*/SKILL.md")):
            relative = source.relative_to(ROOT / "skills")
            self.assertEqual(source.read_bytes(), (codex / "skills" / relative).read_bytes())
            self.assertEqual(source.read_bytes(), (hermes / "skills" / relative).read_bytes())

    def test_repeated_build_is_byte_deterministic(self) -> None:
        first = build_package(ROOT, "codex", self.root / "first")
        second = build_package(ROOT, "codex", self.root / "second")
        self.assertEqual(first["payload_digest"], second["payload_digest"])
        self.assertEqual(first["payload_files"], second["payload_files"])

    def test_manifest_uses_supported_platform_fields_and_build_manifest_preserves_canonical_version(self) -> None:
        output = self.root / "codex-version"
        build_package(ROOT, "codex", output)
        manifest = json.loads((output / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual("1.0.0-rc.1+build.0", manifest["version"])
        self.assertEqual(
            {"name": "sunliming625@gmail.com", "email": "sunliming625@gmail.com"},
            manifest["author"],
        )
        self.assertNotIn("canonical_version", manifest)
        self.assertNotIn("skill_versions", manifest)
        self.assertTrue(manifest["interface"]["longDescription"])
        self.assertEqual("sunliming625@gmail.com", manifest["interface"]["developerName"])
        self.assertEqual(3, len(manifest["interface"]["defaultPrompt"]))

        build_manifest = json.loads((output / "package-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("1.0.0.0-rc.1", build_manifest["canonical_version"])
        self.assertEqual(11, len(build_manifest["skill_versions"]))
        self.assertEqual({"1.0.0.0-rc.1"}, set(build_manifest["skill_versions"].values()))

    def test_compiled_runtime_validates_and_runs_real_evals(self) -> None:
        output = self.root / "runtime-smoke"
        build_package(ROOT, "codex", output)
        launcher = output / "engineering-assistant/bin/ea"
        validate = subprocess.run(
            [str(launcher), "validate", "--require-sources"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, validate.returncode, validate.stdout + validate.stderr)
        evaluate = subprocess.run(
            [str(launcher), "eval"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, evaluate.returncode, evaluate.stdout + evaluate.stderr)
        report = json.loads(evaluate.stdout)
        self.assertFalse(report["simulation"])
        self.assertGreaterEqual(report["routing"]["case_count"], 100)


if __name__ == "__main__":
    unittest.main()
