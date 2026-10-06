#!/usr/bin/env python3
"""Regression tests for the core models and strict schemas."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.codec import feedback_event_from_dict  # noqa: E402
from engineering_assistant.model import (  # noqa: E402
    CapabilityProviderSpec,
    CompletionCriterion,
    ContextPointer,
    EvidenceRef,
    FeedbackEvent,
    Finding,
    InvestigationRequest,
    ProviderSource,
    QualityDimension,
    QualitySnapshot,
    RouteIntent,
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
        self.assertEqual("2.3.0.0-rc.1", parsed.canonical())
        self.assertEqual("2.3.0-rc.1+build.0", parsed.semver())
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
            confirmed_actions=[],
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
            provenance="runtime_observed",
            scope="date-time validation",
        ).to_dict()
        with self.assertRaises(ValidationFailure):
            validate_instance(evidence, self.schema("evidence-ref.schema.json"), "evidence")

    def test_supported_validation_errors_are_stable_with_every_backend(self) -> None:
        class AcceptingValidator:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def iter_errors(self, _instance: object) -> list[object]:
                return []

        cases = (
            (
                {},
                {"type": "object", "required": ["intent"]},
                "payload:$: missing required property intent",
            ),
            (
                {"unknown": True},
                {"type": "object", "additionalProperties": False},
                "payload:$: additional property unknown is not allowed",
            ),
            (
                "not-a-date",
                {"type": "string", "format": "date-time"},
                "payload:$: string is not an RFC 3339 date-time",
            ),
        )
        with mock.patch(
            "engineering_assistant.validation.Draft202012Validator",
            AcceptingValidator,
        ), mock.patch(
            "engineering_assistant.validation.FormatChecker",
            lambda: None,
        ):
            for instance, schema, expected in cases:
                with self.subTest(expected=expected):
                    with self.assertRaises(ValidationFailure) as raised:
                        validate_instance(instance, schema, "payload")
                    self.assertEqual(expected, str(raised.exception))

    def test_builtin_validator_covers_repository_string_and_object_constraints(self) -> None:
        cases = (
            ("too-long", {"type": "string", "maxLength": 3}),
            ({}, {"type": "object", "minProperties": 1}),
            (
                {"INVALID": "value"},
                {
                    "type": "object",
                    "propertyNames": {"pattern": "^[a-z]+$"},
                },
            ),
            ("invalid-email", {"type": "string", "format": "email"}),
        )
        with mock.patch(
            "engineering_assistant.validation.Draft202012Validator",
            None,
        ):
            for instance, schema in cases:
                with self.subTest(instance=instance, schema=schema):
                    with self.assertRaises(ValidationFailure):
                        validate_instance(instance, schema, "builtin")

    def test_provider_feedback_quality_and_investigation_protocols_are_strict(self) -> None:
        provider = CapabilityProviderSpec(
            id="native-engineering",
            version=CANONICAL_VERSION,
            mode="native",
            capability_ids=["repo-context", "tdd"],
            input_schema_ref="schemas/run-state.schema.json",
            output_schema_ref="schemas/step-result.schema.json",
            risk_class="workspace_write",
            network_policy="deny",
            timeout_seconds=300,
            evidence_contract=["source", "test"],
            failure_action="block",
            fallback_provider_id=None,
            source=None,
        ).to_dict()
        feedback = FeedbackEvent(
            event_id="feedback-1",
            run_id="run-1",
            task_id="task-1",
            node_id="implement",
            turn_id="turn-1",
            event_type="human_correction",
            severity="medium",
            source="stop_hook",
            symptom="实现引入了无必要抽象。",
            expected_behavior="保持变更局部且接口最小。",
            observed_behavior="新增了未被调用的抽象层。",
            human_action="删除抽象层并直接复用现有接口。",
            evidence_refs=["evidence-1"],
            scope_tags=["quality"],
            change_kind="correct_behavior",
            affected_asset_refs=["source.py"],
            recovery_condition="apply_corrected_constraint",
            manual_intervention_kind="user_correction",
            recurrence_key="unnecessary-abstraction",
            resolution="repaired",
            reusable_candidate=True,
            sensitivity="internal",
            observed_at="2026-07-11T10:00:00+08:00",
        ).to_dict()
        quality = QualitySnapshot(
            id="quality-1",
            run_id="run-1",
            node_id="implement",
            state_revision=1,
            base_ref="git:base",
            candidate_ref="sha256:" + "0" * 64,
            candidate_evidence_id="evidence-1",
            dimensions=[
                QualityDimension(
                    id=dimension,
                    status="pass",
                    delta=0,
                    summary=f"{dimension} 已评估。",
                    evidence_ids=["evidence-1"],
                )
                for dimension in (
                    "correctness",
                    "complexity",
                    "redundancy",
                    "performance",
                    "architecture",
                    "test_quality",
                )
            ],
            findings=[Finding("finding-1", "low", "无阻断问题。", ["evidence-1"])],
            required_repairs=[],
            evidence_refs=["evidence-1"],
            observed_at="2026-07-11T10:00:00+08:00",
        ).to_dict()
        investigation = InvestigationRequest(
            id="investigation-1",
            run_id="run-1",
            question="当前依赖是否提供官方扩展接口？",
            reason="避免复制已有能力。",
            source_scope=["official_docs", "source_repository"],
            reported_blocking=True,
            mode="suggest_then_run",
            estimated_cost="low",
            stop_conditions=["找到官方接口定义"],
            evidence_requirements=["可引用的一手资料"],
            status="proposed",
        ).to_dict()

        cases = {
            "capability-provider-spec.schema.json": provider,
            "feedback-event.schema.json": feedback,
            "quality-snapshot.schema.json": quality,
            "investigation-request.schema.json": investigation,
        }
        for schema_name, payload in cases.items():
            with self.subTest(schema=schema_name):
                validate_instance(payload, self.schema(schema_name), schema_name)
                invalid = dict(payload)
                invalid["unknown"] = True
                with self.assertRaises(ValidationFailure):
                    validate_instance(invalid, self.schema(schema_name), schema_name)

    def test_legacy_feedback_event_remains_readable_with_unknown_action_context(
        self,
    ) -> None:
        legacy = {
            "event_id": "feedback-legacy",
            "run_id": "run-1",
            "task_id": "task-1",
            "node_id": None,
            "turn_id": "turn-1",
            "event_type": "human_correction",
            "severity": "medium",
            "source": "human",
            "symptom": "legacy event",
            "expected_behavior": "apply correction",
            "observed_behavior": "correction requested",
            "human_action": None,
            "evidence_refs": [],
            "recurrence_key": "legacy-correction",
            "resolution": "open",
            "reusable_candidate": False,
            "sensitivity": "internal",
            "observed_at": "2026-07-13T10:00:00+08:00",
        }

        validate_instance(
            legacy,
            self.schema("feedback-event.schema.json"),
            "legacy-feedback",
        )
        decoded = feedback_event_from_dict(legacy)
        self.assertEqual(["unknown"], decoded.scope_tags)
        self.assertEqual("unknown", decoded.change_kind)
        self.assertEqual("unknown", decoded.recovery_condition)

    def test_external_provider_requires_pinned_source(self) -> None:
        provider = CapabilityProviderSpec(
            id="external-ui",
            version=CANONICAL_VERSION,
            mode="external_cli",
            capability_ids=["frontend-design"],
            input_schema_ref="schemas/run-state.schema.json",
            output_schema_ref="schemas/step-result.schema.json",
            risk_class="read_only",
            network_policy="allow_readonly",
            timeout_seconds=120,
            evidence_contract=["source"],
            failure_action="fallback",
            fallback_provider_id="native-engineering",
            source=ProviderSource(
                url="https://example.invalid/provider.git",
                revision="0123456789abcdef0123456789abcdef01234567",
                integrity="sha256:" + "0" * 64,
                license="MIT",
            ),
        ).to_dict()
        validate_instance(provider, self.schema("capability-provider-spec.schema.json"), "provider")
        provider["source"] = None
        with self.assertRaises(ValidationFailure):
            validate_instance(provider, self.schema("capability-provider-spec.schema.json"), "provider")

    def test_all_core_schemas_are_valid_json(self) -> None:
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
            "capability-provider-spec.schema.json",
            "feedback-event.schema.json",
            "feedback-capture.schema.json",
            "quality-snapshot.schema.json",
            "investigation-request.schema.json",
            "investigation-record.schema.json",
            "investigation-decision-record.schema.json",
            "approval-record.schema.json",
            "run-manifest.schema.json",
            "step-record.schema.json",
            "provider-invocation.schema.json",
            "provider-result.schema.json",
            "usage-efficiency-feedback.schema.json",
        }
        self.assertTrue(expected.issubset({path.name for path in (ROOT / "schemas").glob("*.json")}))
        for name in expected:
            schema = self.schema(name)
            self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])

    def test_investigation_record_embeds_the_full_request_contract(self) -> None:
        request_schema = self.schema("investigation-request.schema.json")
        record_schema = self.schema("investigation-record.schema.json")
        request_contract = {
            key: value
            for key, value in request_schema.items()
            if key not in {"$schema", "$id"}
        }

        self.assertEqual(
            request_contract,
            record_schema["$defs"]["investigation_request"],
        )
        invalid_record = {
            "request": {},
            "decision_ref": None,
            "evidence_refs": [],
            "remaining_source_scope": [],
            "current_source_scope": [],
            "transition_history": [
                {
                    "from_status": "",
                    "to_status": "proposed",
                    "action": "propose",
                    "decision_ref": None,
                    "observed_at": "2026-07-14T00:00:00+00:00",
                }
            ],
            "updated_at": "2026-07-14T00:00:00+00:00",
            "revision": 0,
        }
        with self.assertRaises(ValidationFailure):
            validate_instance(
                invalid_record,
                record_schema,
                "investigation-record",
            )

    def test_builtin_validator_enforces_ref_sibling_constraints(self) -> None:
        schema = {
            "$defs": {"text": {"type": "string"}},
            "$ref": "#/$defs/text",
            "minLength": 3,
        }
        with mock.patch(
            "engineering_assistant.validation.Draft202012Validator", None
        ):
            with self.assertRaises(ValidationFailure):
                validate_instance("x", schema, "ref-sibling")


if __name__ == "__main__":
    unittest.main()
