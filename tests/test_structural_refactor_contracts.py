#!/usr/bin/env python3
"""Structural regression checks for engineering-assistant generator and contracts."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_SCHEMA_FILES = [
    "design-contract.schema.json",
    "implementation-contract.schema.json",
    "quality-contract.schema.json",
    "quality-run-report.schema.json",
    "task-control.schema.json",
]
ALLOWED_TRUE_SUFFIXES = (".extensions", ".metadata")


def true_additional_properties(node: object, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(node, dict):
        if node.get("additionalProperties") is True:
            findings.append(path)
        for key, value in node.items():
            findings.extend(true_additional_properties(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            findings.extend(true_additional_properties(value, f"{path}[{index}]"))
    return findings


class StructuralRefactorContractTests(unittest.TestCase):
    def test_generator_entrypoint_is_thin_and_modules_exist(self) -> None:
        entrypoint = ROOT / "generate_engineering_assistant_assets.py"
        self.assertLessEqual(len(entrypoint.read_text(encoding="utf-8").splitlines()), 1500)
        self.assertIn("from generator.legacy_generator import main", entrypoint.read_text(encoding="utf-8"))

        for module in ["catalog", "schema", "skills", "workflows", "scripts", "plugin_manifest", "evals", "runtime_ir", "tests_support"]:
            self.assertTrue((ROOT / "generator" / f"{module}.py").exists(), f"missing generator/{module}.py")

    def test_shared_governance_protocol_reduces_skill_document_noise(self) -> None:
        shared = ROOT / "engineering-assistant" / "shared" / "governance-protocol.md"
        self.assertTrue(shared.exists())
        self.assertIn("前端产品级交付必须优先委派", shared.read_text(encoding="utf-8"))

        for skill_md in (ROOT / "skills").glob("*/SKILL.md"):
            text = skill_md.read_text(encoding="utf-8")
            self.assertIn("engineering-assistant/shared/governance-protocol.md", text, str(skill_md))
            self.assertNotIn("# 工程治理主控", text, str(skill_md))
            self.assertNotIn("# 能力编排与降级", text, str(skill_md))

    def test_core_control_schemas_only_allow_extensions_or_metadata_open_maps(self) -> None:
        for file_name in CORE_SCHEMA_FILES:
            schema = json.loads((ROOT / "engineering-assistant" / "schemas" / file_name).read_text(encoding="utf-8"))
            offenders = [
                path
                for path in true_additional_properties(schema)
                if not path.endswith(ALLOWED_TRUE_SUFFIXES)
            ]
            self.assertEqual([], offenders, f"{file_name} has non-whitelisted additionalProperties=true")

    def test_capability_dependencies_make_frontend_delegation_explicit(self) -> None:
        registry = json.loads((ROOT / "engineering-assistant" / "registry" / "capability-dependencies.yaml").read_text(encoding="utf-8"))
        frontend = registry["dependencies"]["frontend_product_execution"]
        self.assertIn("build-web-apps", frontend["recommended"])
        self.assertIn("browser", frontend["recommended"])
        self.assertEqual("block_browser_level_acceptance", frontend["missing_behavior"])
        self.assertIn("code-level validation", frontend["claim_boundary"])

    def test_schema_migration_fixture_exists(self) -> None:
        fixture = ROOT / "engineering-assistant" / "schemas" / "fixtures" / "legacy-v2-control-contract.json"
        self.assertTrue(fixture.exists())
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual("blocked_or_extensions", payload["migration_expectation"])
        self.assertTrue((ROOT / "engineering-assistant" / "schemas" / "control-contract-migration.md").exists())


if __name__ == "__main__":
    unittest.main()
