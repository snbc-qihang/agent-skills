#!/usr/bin/env python3
"""Regression tests for the core models and strict schemas."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.model import (  # noqa: E402
    CompletionCriterion,
    ContextPointer,
    RouteIntent,
    EvidenceRef,
    SkillSpec,
)
from engineering_assistant.validation import (  # noqa: E402
    ValidationFailure,
    load_json,
    validate_instance,
)
from engineering_assistant.version import (  # noqa: E402
    CANONICAL_VERSION,
    CanonicalVersion,
    platform_version,
)


class ModelAndSchemaTests(unittest.TestCase):
    def schema(self, name: str) -> dict:
        return load_json(ROOT / "schemas" / name)

    def test_four_part_version_and_platform_mapping(self) -> None:
        parsed = CanonicalVersion.parse(CANONICAL_VERSION)
        self.assertEqual("1.0.0.0-rc.1", parsed.canonical())
        self.assertEqual("1.0.0-rc.1+build.0", parsed.semver())
        self.assertEqual("1.2.3+build.4", platform_version("1.2.3.4", supports_four_part=False))
        with self.assertRaises(ValueError):
            CanonicalVersion.parse("4.0.0")

    def test_skill_spec_round_trip_and_schema(self) -> None:
        spec = SkillSpec(
            id="repo-context",
            version=CANONICAL_VERSION,
            invocation_mode="model",
            description="Use when repository context and impact evidence are required.",
            leading_words=["impact scope"],
            capabilities=["repo-context"],
            inputs=["repository"],
            completion_criteria=[
                CompletionCriterion("scope", "Every affected module is accounted for.", ["source"])
            ],
            context_pointers=[
                ContextPointer("database changes are present", "references/database.md", "Load database evidence rules.")
            ],
            policy_refs=["evidence-quality"],
            risk_class="read_only",
            source_path="skills/repo-context",
        )
        payload = spec.to_dict()
        validate_instance(payload, self.schema("skill-spec.schema.json"), "skill")
        self.assertEqual(payload, json.loads(json.dumps(payload, ensure_ascii=False)))

    def test_user_invoked_skill_cannot_have_model_description(self) -> None:
        payload = {
            "id": "manual-flow",
            "version": CANONICAL_VERSION,
            "invocation_mode": "user",
            "description": "This should be rejected.",
            "leading_words": [],
            "capabilities": ["manual-flow"],
            "inputs": [],
            "completion_criteria": [{"id": "done", "description": "Done.", "evidence_kinds": []}],
            "context_pointers": [],
            "policy_refs": [],
            "risk_class": "read_only",
            "source_path": "skills/manual-flow"
        }
        with self.assertRaises(ValidationFailure):
            validate_instance(payload, self.schema("skill-spec.schema.json"), "skill")

    def test_route_intent_is_strict(self) -> None:
        intent = RouteIntent(
            task_kind="design",
            requested_outcome="Design a bounded change.",
            scope=["module-a"],
            risk_signals=[],
            requested_external_actions=[],
            confidence=0.9,
            evidence=["user requested design"],
        ).to_dict()
        validate_instance(intent, self.schema("route-intent.schema.json"), "intent")
        intent["unknown"] = True
        with self.assertRaises(ValidationFailure):
            validate_instance(intent, self.schema("route-intent.schema.json"), "intent")

    def test_evidence_date_time_is_validated_by_every_backend(self) -> None:
        evidence = EvidenceRef(
            id="source-1",
            kind="source",
            uri="source.py",
            producer="test",
            observed_at="not-a-date",
            trust_level="observed",
            scope="date-time validation",
        ).to_dict()
        with self.assertRaises(ValidationFailure):
            validate_instance(evidence, self.schema("evidence-ref.schema.json"), "evidence")

    def test_all_nine_core_schemas_are_valid_json(self) -> None:
        expected = {
            "skill-spec.schema.json",
            "flow-spec.schema.json",
            "policy-spec.schema.json",
            "route-intent.schema.json",
            "route-decision.schema.json",
            "run-state.schema.json",
            "step-result.schema.json",
            "gate-decision.schema.json",
            "evidence-ref.schema.json",
        }
        self.assertTrue(expected.issubset({path.name for path in (ROOT / "schemas").glob("*.json")}))
        for name in expected:
            schema = self.schema(name)
            self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])


if __name__ == "__main__":
    unittest.main()
