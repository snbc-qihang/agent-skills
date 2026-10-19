from __future__ import annotations

import sys
import tempfile
import unittest
import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.runtime import catalog
from engineering_assistant.runtime.artifact_io import ArtifactIO, assert_runtime_artifact_target  # noqa: E402
from engineering_assistant.runtime.validation import ValidationFailure  # noqa: E402


class WheelDistributionTests(unittest.TestCase):
    def test_distribution_staging_is_outside_author_source_and_omits_local_metadata(self) -> None:
        specification = importlib.util.spec_from_file_location("ea_test_backend", ROOT / "ea_build_backend.py")
        backend = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(backend)
        with backend._staged_source() as stage:
            self.assertNotIn(ROOT, stage.parents)
            self.assertTrue((stage / "catalog/skills/public.json").is_file())
            self.assertTrue((stage / "config/runtime.json").is_file())
            for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
                self.assertEqual((ROOT / name).read_bytes(), (stage / name).read_bytes())
            self.assertFalse(list(stage.rglob(".DS_Store")))
            self.assertFalse(list(stage.rglob("*.egg-info")))
            self.assertFalse(list(stage.rglob("__pycache__")))
        self.assertFalse(stage.exists())
        with self.assertRaisesRegex(ValueError, "outside the author repository"):
            backend._output_directory(str(ROOT / "dist"))

    def test_wheel_assets_are_the_default_catalog_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "site-packages/engineering_assistant"
            assets = package / "_assets"
            for relative in ("catalog", "skills", "schemas"):
                (assets / relative).mkdir(parents=True)
            (package / "__init__.py").touch()
            self.assertEqual(assets.resolve(), catalog._default_repository_root(package / "runtime/catalog.py"))
        self.assertEqual(ROOT, catalog.DEFAULT_REPOSITORY_ROOT)

    def test_wheel_source_validation_requires_consumer_assets_without_author_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "engineering_assistant"
            assets = package / "_assets"
            for name in ("catalog", "skills", "packs", "schemas"):
                shutil.copytree(ROOT / name, assets / name)
            for name in ("runtime", "platforms"):
                shutil.copytree(ROOT / "src/engineering_assistant" / name, package / name,
                                ignore=shutil.ignore_patterns("__pycache__"))
            self.assertFalse((package / "tools").exists())
            self.assertEqual(catalog.load_catalog(ROOT).version,
                             catalog.load_catalog(assets, require_sources=True).version)
            (package / "runtime/governance.py").unlink()
            with self.assertRaisesRegex(ValidationFailure, "invalid target reference"):
                catalog.load_catalog(assets, require_sources=True)

    def test_author_tool_references_remain_strict_and_cannot_escape_wheel_assets(self) -> None:
        for layout in ("source", "wheel", "source_named_assets"):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / ("author" if layout == "source" else "_assets")
                for name in ("catalog", "skills", "packs", "schemas"):
                    shutil.copytree(ROOT / name, root / name)
                if layout == "source_named_assets":
                    (root / "src/engineering_assistant").mkdir(parents=True)
                    (root.parent / "runtime").mkdir()
                    (root.parent / "runtime/catalog.py").touch()
                source_path = root / "catalog/sources/open-source.json"
                data = json.loads(source_path.read_text())
                data["sources"][0]["target_refs"] = [
                    "src/engineering_assistant/tools/../missing.py" if layout == "wheel"
                    else "src/engineering_assistant/tools/missing.py"]
                source_path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValidationFailure, "source anthropic-skills: invalid target reference"):
                    catalog.load_catalog(root, require_sources=True)

    def test_wheel_package_and_assets_cannot_receive_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "site-packages/engineering_assistant"
            assets = package / "_assets"
            for relative in ("catalog", "skills", "schemas"):
                (assets / relative).mkdir(parents=True)
            (package / "__init__.py").touch()
            for target in (package, assets, assets / "skills"):
                with self.subTest(target=target):
                    with self.assertRaisesRegex(ValidationFailure, "installed plugin tree"):
                        assert_runtime_artifact_target(target, assets / "schemas")
                    artifacts = ArtifactIO(target, ".")
                    try:
                        with self.assertRaisesRegex(ValidationFailure, "installed plugin tree"):
                            artifacts.assert_runtime_target(assets / "schemas", allow_author_repository=True)
                    finally:
                        artifacts.close()
            self.assertFalse((package / ".run-artifacts").exists())


if __name__ == "__main__":
    unittest.main()
