from __future__ import annotations

import sys
import json
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.policy import PolicyOverride, resolve_policies  # noqa: E402
from engineering_assistant.router import ROUTES  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402
from engineering_assistant.version import CANONICAL_VERSION, STABLE_VERSION  # noqa: E402


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog(ROOT)

    def test_catalog_has_the_approved_public_surface(self) -> None:
        self.assertEqual(11, len(self.catalog.skills))
        self.assertEqual(7, len(self.catalog.flows))
        self.assertEqual(10, len(self.catalog.packs))
        self.assertEqual(2, len(self.catalog.providers))
        self.assertEqual(6, len(self.catalog.sources))
        self.assertEqual("1.0.0.1", self.catalog.version)

    def test_current_version_is_consistent_across_runtime_catalog_wheel_and_local_policy(self):
        version = self.catalog.version
        self.assertEqual(version, CANONICAL_VERSION)
        self.assertEqual(version, STABLE_VERSION)
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(version, project["version"])
        policy = json.loads((ROOT / "config/local-publish-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(version, policy["canonical_version"])
        self.assertFalse(policy["stable_release_allowed"])

        def versions(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "version":
                        yield item
                    else:
                        yield from versions(item)
            elif isinstance(value, list):
                for item in value:
                    yield from versions(item)

        for path in (ROOT / "catalog").rglob("*.json"):
            with self.subTest(source=path.relative_to(ROOT).as_posix()):
                declared = list(versions(json.loads(path.read_text(encoding="utf-8"))))
                self.assertTrue(declared)
                self.assertEqual({version}, set(declared))

    def test_open_source_decisions_are_pinned_and_mapped_to_current_assets(self) -> None:
        decisions = {source.id: source for source in self.catalog.sources.values()}
        self.assertEqual(
            {
                "anthropic-skills": "fuse",
                "obra-superpowers": "fuse",
                "addyosmani-agent-skills": "fuse",
                "taste-skill": "fuse",
                "ui-ux-pro-max-skill": "external_provider",
                "ux-ui-agent-skills": "not_adopted",
            },
            {source_id: source.decision for source_id, source in decisions.items()},
        )
        external = decisions["ui-ux-pro-max-skill"]
        provider = self.catalog.providers[external.provider_id]
        self.assertEqual(provider.source.revision, external.revision)
        for source in decisions.values():
            self.assertRegex(source.revision, r"^[0-9a-f]{40}$")
            self.assertEqual(
                set(source.license_evidence) | set(source.evidence_paths),
                set(source.evidence_digests),
            )
            self.assertTrue(
                all(
                    value.startswith("sha256:") and len(value) == 71
                    for value in source.evidence_digests.values()
                )
            )
            for target_ref in source.target_refs:
                self.assertTrue((ROOT / target_ref).exists(), target_ref)

    def test_all_references_and_flow_dags_are_valid(self) -> None:
        self.assertEqual("engineering-assistant", self.catalog.capabilities["route-engineering"].owner)
        self.assertEqual("tdd", self.catalog.skill_for_capability("tdd").id)
        self.assertIsNone(self.catalog.skill_for_capability("quality-evidence"))
        self.assertEqual(
            "ui-ux-pro-max",
            self.catalog.provider_for_capability("frontend-design").id,
        )

    def test_security_seam_guidance_is_progressive_and_does_not_expand_routing(self) -> None:
        for skill_id in ("tdd", "code-review"):
            pointers = self.catalog.skills[skill_id].context_pointers
            self.assertTrue(
                any(pointer.path == "references/security-seams.md" for pointer in pointers),
                skill_id,
            )
        self.assertEqual(("implement", ("code-review",)), ROUTES["implement"])

    def test_all_skill_and_pack_sources_exist_and_match_catalog(self) -> None:
        sourced = load_catalog(ROOT, require_sources=True)
        self.assertEqual(set(self.catalog.skills), set(sourced.skills))

    def test_domain_modeling_exposes_the_full_context_scoped_contract(self) -> None:
        skill = self.catalog.skills["domain-modeling"]
        self.assertEqual(
            [
                "context-bounded",
                "language-resolved",
                "behavior-validated",
                "consistency-owned",
                "patterns-justified",
                "implementation-reconciled",
            ],
            [criterion.id for criterion in skill.completion_criteria],
        )
        self.assertEqual(
            {
                "references/strategic-modeling.md",
                "references/tactical-modeling.md",
                "references/model-artifact.md",
                "references/design-governance.md",
                "references/scenario-traceability.md",
                "references/integration-consistency.md",
                "references/adr-format.md",
            },
            {pointer.path for pointer in skill.context_pointers},
        )
        self.assertEqual(
            ["document-governance", "evidence-quality", "scope-control"],
            skill.policy_refs,
        )
        domain_policy = self.catalog.policies["domain-design-governance"]
        self.assertTrue(
            {"DDD-009", "DDD-010", "DDD-011"}.issubset(
                {rule.id for rule in domain_policy.rules}
            )
        )

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

    def test_provider_with_unknown_capability_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "catalog", root / "catalog")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            providers = root / "catalog/providers/core.json"
            data = json.loads(providers.read_text(encoding="utf-8"))
            data["providers"][0]["capability_ids"].append("unknown-capability")
            providers.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "unknown references"):
                load_catalog(root)

    def test_source_review_scope_cannot_silently_lose_a_required_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "catalog", root / "catalog")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            sources = root / "catalog/sources/open-source.json"
            data = json.loads(sources.read_text(encoding="utf-8"))
            data["sources"] = []
            sources.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ValidationFailure, "review scope"):
                load_catalog(root)

            data = json.loads((ROOT / "catalog/sources/open-source.json").read_text(encoding="utf-8"))
            removed = data["review_scope"].pop()
            data["sources"] = [item for item in data["sources"] if item["id"] != removed]
            sources.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "review scope"):
                load_catalog(root)

    def test_external_source_decision_cannot_drift_from_its_provider(self) -> None:
        for field, value in (
            ("repository_url", "https://github.com/example/different"),
            ("license", "GPL-3.0"),
            ("integrity", "sha256:" + "0" * 64),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(ROOT / "catalog", root / "catalog")
                shutil.copytree(ROOT / "schemas", root / "schemas")
                sources = root / "catalog/sources/open-source.json"
                data = json.loads(sources.read_text(encoding="utf-8"))
                external = next(
                    item for item in data["sources"]
                    if item["decision"] == "external_provider"
                )
                external[field] = value
                sources.write_text(json.dumps(data), encoding="utf-8")

                with self.assertRaisesRegex(ValidationFailure, "must match provider"):
                    load_catalog(root)

    def test_source_evidence_paths_must_be_safe_repository_relative_paths(self) -> None:
        for unsafe in (
            "../outside",
            "C:\\Windows\\win.ini",
            "https://example.com/evidence",
            "./README.md",
            "docs//README.md",
            "docs/",
        ):
            with self.subTest(path=unsafe), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(ROOT / "catalog", root / "catalog")
                shutil.copytree(ROOT / "schemas", root / "schemas")
                sources = root / "catalog/sources/open-source.json"
                data = json.loads(sources.read_text(encoding="utf-8"))
                data["sources"][0]["evidence_paths"] = [unsafe]
                sources.write_text(json.dumps(data), encoding="utf-8")

                with self.assertRaises(ValidationFailure):
                    load_catalog(root)

    def test_provider_selection_requires_one_highest_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "catalog", root / "catalog")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            providers = root / "catalog/providers/core.json"
            data = json.loads(providers.read_text(encoding="utf-8"))
            duplicate = dict(data["providers"][0])
            duplicate["id"] = "ambiguous-native"
            data["providers"].append(duplicate)
            providers.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "ambiguous highest priority"):
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
