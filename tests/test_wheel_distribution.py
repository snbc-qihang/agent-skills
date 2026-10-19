from __future__ import annotations

import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant import catalog  # noqa: E402
from engineering_assistant.artifact_io import ArtifactIO, assert_runtime_artifact_target  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


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
            self.assertEqual(assets.resolve(), catalog._default_repository_root(package / "catalog.py"))
        self.assertEqual(ROOT, catalog.DEFAULT_REPOSITORY_ROOT)

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
