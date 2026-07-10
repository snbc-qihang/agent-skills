from __future__ import annotations

import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.policy import PolicyOverride, resolve_policies  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog(ROOT)

    def test_catalog_has_the_approved_public_surface(self) -> None:
        self.assertEqual(11, len(self.catalog.skills))
        self.assertEqual(6, len(self.catalog.flows))
        self.assertEqual(9, len(self.catalog.packs))
        self.assertEqual("1.0.0.0-rc.1", self.catalog.version)

    def test_all_references_and_flow_dags_are_valid(self) -> None:
        self.assertEqual("engineering-assistant", self.catalog.capabilities["route-engineering"].owner)
        self.assertEqual("tdd", self.catalog.skill_for_capability("tdd").id)
        self.assertIsNone(self.catalog.skill_for_capability("quality-evidence"))

    def test_all_skill_and_pack_sources_exist_and_match_catalog(self) -> None:
        sourced = load_catalog(ROOT, require_sources=True)
        self.assertEqual(set(self.catalog.skills), set(sourced.skills))

    def test_entry_version_conflict_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "catalog", root / "catalog")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            public = root / "catalog/skills/public.json"
            data = json.loads(public.read_text(encoding="utf-8"))
            data["skills"][0]["version"] = "1.0.0.1-rc.1"
            public.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "mismatched versions"):
                load_catalog(root)


class PolicyResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog(ROOT)

    def test_resolution_is_deduplicated_and_records_provenance(self) -> None:
        result = resolve_policies(
            self.catalog,
            flow_id="implement",
            skill_ids=["tdd"],
            task_policy_refs=["frontend-product"],
        )
        self.assertEqual(len(result.policy_ids), len(set(result.policy_ids)))
        self.assertIn("safety-core", result.policy_ids)
        self.assertIn("frontend-product", result.policy_ids)
        self.assertIn("SAFE-001", result.rules)
        self.assertEqual("block", result.strongest_violation)
        self.assertTrue(any(item.source == "global" for item in result.provenance))

    def test_immutable_policy_cannot_be_disabled_even_with_approval(self) -> None:
        with self.assertRaisesRegex(ValidationFailure, "immutable policy"):
            resolve_policies(
                self.catalog,
                overrides=[PolicyOverride("safety-core", "disable", "test", "human-1")],
            )

    def test_lowering_nonimmutable_policy_requires_approval(self) -> None:
        with self.assertRaisesRegex(ValidationFailure, "requires approval_id"):
            resolve_policies(
                self.catalog,
                overrides=[PolicyOverride("scope-control", "disable", "bounded exception")],
            )
        result = resolve_policies(
            self.catalog,
            overrides=[PolicyOverride("scope-control", "disable", "bounded exception", "human-2")],
        )
        self.assertNotIn("scope-control", result.policy_ids)
        self.assertEqual("human-2", result.applied_overrides[0].approval_id)


if __name__ == "__main__":
    unittest.main()
