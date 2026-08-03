from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.artifact_validation import validate_artifact_payload  # noqa: E402
from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.design_sources import validate_design_source_registry  # noqa: E402
from engineering_assistant.engine import RuntimeEngine  # noqa: E402
from engineering_assistant.evidence import EvidenceStore  # noqa: E402
from engineering_assistant.model import (  # noqa: E402
    CriterionResult,
    ApprovalRecord,
    EvidenceRef,
    Finding,
    RouteIntent,
    StepResult,
)
from engineering_assistant.router import route_intent  # noqa: E402
from engineering_assistant.state_store import StateStore  # noqa: E402
from engineering_assistant.validation import ValidationFailure, validate_instance  # noqa: E402


class DomainDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog(ROOT, require_sources=True)

    def intent(self) -> RouteIntent:
        return RouteIntent(
            task_kind="domain-design",
            requested_outcome="从需求和源码建立领域、BC、部署单元与详细设计。",
            scope=["repository"],
            risk_signals=[],
            requested_external_actions=[],
            confirmed_actions=[],
            confidence=0.95,
            evidence=["user request"],
        )

    @staticmethod
    def registry_base() -> dict:
        return {
            "hld": "docs/architecture/hld.md",
            "context_index": "docs/architecture/contexts.md",
            "capability_design_root": "docs/architecture/capabilities",
            "change_root": "docs/architecture/changes",
            "deployment_catalog": "docs/architecture/deployments.md",
            "owners": {
                "business": "domain-business-owner",
                "architecture": "domain-architecture-owner",
            },
        }

    @classmethod
    def registry_v2(cls) -> dict:
        registry = cls.registry_base() | {"version": "2"}
        registry["sources"] = [
            {"id": "requirements", "kind": "requirements", "path": "docs/requirements.md", "status": "available", "reason": "当前需求基线。"},
            {"id": "repository", "kind": "repository", "path": "src", "status": "available", "reason": "当前实现。"},
            {"id": "existing-design", "kind": "existing-design", "path": None, "status": "not_applicable", "reason": "项目尚无既有设计。"},
            {"id": "interfaces", "kind": "interfaces", "path": None, "status": "unknown", "reason": "待确认外部契约位置。"},
            {"id": "data", "kind": "data", "path": None, "status": "unknown", "reason": "待确认数据契约位置。"},
            {"id": "deployment", "kind": "deployment", "path": None, "status": "unknown", "reason": "待确认部署证据位置。"},
        ]
        return registry

    def test_catalog_routes_domain_design_through_the_governed_flow(self) -> None:
        decision = route_intent(self.intent(), self.catalog)
        self.assertEqual("domain-design", decision.flow_id)
        self.assertEqual(
            ("repo-context", "domain-modeling", "decision-interview", "codebase-design", "code-review"),
            tuple(decision.skill_ids),
        )
        flow = self.catalog.flows["domain-design"]
        self.assertEqual(
            [
                "resolve-design-sources",
                "discover-domain-facts",
                "strategic-design",
                "resolve-domain-decisions",
                "context-topology",
                "boundary-validation",
                "context-slicing",
                "tactical-modeling",
                "capability-detailed-design",
                "integration-consistency",
                "design-conformance-review",
                "baseline-approval",
            ],
            [node.id for node in flow.nodes],
        )
        self.assertIn("domain-integration", self.catalog.packs)
        self.assertIn("domain-design-governance", self.catalog.policies)

    def test_design_source_registry_v2_requires_typed_input_coverage(self) -> None:
        artifact = self.registry_v2()
        self.assertEqual(
            {"status": "passed", "kind": "design-source-registry"},
            validate_artifact_payload(
                schema_root=ROOT / "schemas", kind="design-source-registry", artifact=artifact
            ),
        )

    def test_registry_schema_accepts_only_declared_v2_fields(self) -> None:
        schema = json.loads((ROOT / "schemas" / "design-source-registry.schema.json").read_text())
        validate_instance(self.registry_v2(), schema, "design-source-registry")
        with self.assertRaises(ValidationFailure):
            validate_instance(
                self.registry_base() | {"version": "1"},
                schema,
                "design-source-registry",
            )
        with self.assertRaises(ValidationFailure):
            validate_instance(
                self.registry_v2() | {"unexpected": "field"},
                schema,
                "design-source-registry",
            )

    def test_registry_requires_v2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "docs").mkdir()
            (project / "docs" / "requirements.md").write_text("需求", encoding="utf-8")
            (project / "src").mkdir()
            registry_path = project / "docs" / "design-sources.json"
            registry_path.write_text(
                json.dumps(self.registry_base() | {"version": "1"}), encoding="utf-8"
            )

            with self.assertRaises(ValidationFailure):
                validate_design_source_registry(project, "docs/design-sources.json", ROOT / "schemas")

            registry_path.write_text(
                json.dumps(self.registry_v2()), encoding="utf-8"
            )
            current = validate_design_source_registry(
                project, "docs/design-sources.json", ROOT / "schemas"
            )
            self.assertEqual("2", current["version"])

    def test_v2_registry_rejects_unavailable_required_sources_and_unsafe_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "docs").mkdir()
            registry = self.registry_v2()
            registry["sources"][0]["path"] = "../requirements.md"
            registry_path = project / "docs" / "design-sources.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "source path"):
                validate_design_source_registry(project, "docs/design-sources.json", ROOT / "schemas")

            registry = self.registry_v2()
            registry["sources"][0]["status"] = "unknown"
            registry["sources"][0]["path"] = None
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "requirements"):
                validate_design_source_registry(project, "docs/design-sources.json", ROOT / "schemas")

    def test_context_slicing_and_tactical_modeling_are_mandatory(self) -> None:
        flow = self.catalog.flows["domain-design"]
        nodes = {node.id: node for node in flow.nodes}
        self.assertEqual(["boundary-validation"], nodes["context-slicing"].depends_on)
        self.assertEqual(["context-slicing"], nodes["tactical-modeling"].depends_on)
        self.assertEqual(["tactical-modeling"], nodes["capability-detailed-design"].depends_on)
        self.assertEqual("always", nodes["context-slicing"].when)
        self.assertEqual("always", nodes["tactical-modeling"].when)

    def test_old_rc_state_selects_new_context_slicing_node_before_completion(self) -> None:
        engine = RuntimeEngine(self.catalog)
        state = engine.start(
            "domain-task",
            self.intent(),
            run_id="domain-old-rc",
            design_source_ref="docs/design-sources.json",
        )
        state.completed_nodes = [
            "resolve-design-sources",
            "discover-domain-facts",
            "strategic-design",
            "resolve-domain-decisions",
            "context-topology",
            "boundary-validation",
        ]
        gate = engine.next(state)
        self.assertEqual("continue", gate.decision)
        self.assertEqual("context-slicing", gate.next_node)

    def test_missing_design_source_waits_without_selecting_a_flow_node(self) -> None:
        state = RuntimeEngine(self.catalog).start("domain-task", self.intent(), run_id="domain-1")
        self.assertEqual("waiting_for_input", state.status)
        gate = RuntimeEngine(self.catalog).next(state)
        self.assertEqual("pause_for_input", gate.decision)
        self.assertIn("design_source_ref", gate.missing_evidence)

    def test_baseline_approval_requires_both_named_approvers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            engine = RuntimeEngine(self.catalog)
            state = engine.start(
                "domain-task",
                self.intent(),
                run_id="domain-approval",
                design_source_ref="docs/design-sources.json",
            )
            state.current_node = "baseline-approval"
            store = StateStore(project, ROOT / "schemas")
            evidence_store = EvidenceStore(store)
            gate = engine.complete_step(
                state,
                StepResult(
                    run_id=state.run_id,
                    node_id="baseline-approval",
                    status="waiting",
                    criteria_results=[],
                    outputs=["HLD and detailed designs remain reviewing."],
                    findings=[],
                    open_questions=["obtain approvals"],
                    requested_transition="pause_for_approval",
                    required_approvals=["domain-business-owner", "domain-architecture-owner"],
                ),
                evidence_store=evidence_store,
            )
            self.assertEqual("pause_for_approval", gate.decision)
            self.assertEqual(
                ["domain-business-owner", "domain-architecture-owner"],
                state.required_approvals,
            )

            records = []
            for index, approval_id in enumerate(state.required_approvals, start=1):
                record = ApprovalRecord(
                    record_id=f"record-{approval_id}",
                    run_id=state.run_id,
                    run_revision=state.revision,
                    approval_id=approval_id,
                    decision="approved",
                    scope=["flow:domain-design", f"approval:{approval_id}"],
                    actor_ref=("business-owner" if index == 1 else "architecture-owner"),
                    reason="explicit owner approval",
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                    source="user_confirmation",
                )
                engine.apply_approval_record(
                    state,
                    record,
                    approval_records=records,
                )
                records.append(record)
            self.assertEqual("initialized", state.status)
            same_actor_records = [
                ApprovalRecord(**{**record.to_dict(), "actor_ref": "same-owner"})
                for record in records
            ]
            self.assertEqual(
                ["domain-architecture-owner"],
                engine._missing_approvals(state, same_actor_records),
            )

    def test_boundary_rework_returns_to_strategic_design_and_keeps_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            engine = RuntimeEngine(self.catalog)
            state = engine.start(
                "domain-task",
                self.intent(),
                run_id="domain-rework",
                design_source_ref="docs/design-sources.json",
            )
            state.completed_nodes = [
                "resolve-design-sources",
                "discover-domain-facts",
                "strategic-design",
                "resolve-domain-decisions",
                "context-topology",
            ]
            state.current_node = "boundary-validation"
            store = StateStore(project, ROOT / "schemas")
            evidence_store = EvidenceStore(store)
            (project / "boundary-review.md").write_text("boundary conflict\n")
            evidence_store.save(
                state.run_id,
                EvidenceRef(
                    id="boundary-review",
                    kind="review",
                    uri="boundary-review.md",
                    producer="domain-review",
                    observed_at=datetime.now(timezone.utc).isoformat(),
                    provenance="runtime_observed",
                    scope="domain boundary validation",
                ),
            )

            gate = engine.complete_step(
                state,
                StepResult(
                    run_id=state.run_id,
                    node_id="boundary-validation",
                    status="failed",
                    criteria_results=[],
                    outputs=[],
                    findings=[
                        Finding(
                            id="boundary-conflict",
                            severity="major",
                            summary="支付规则具有相互冲突的知识语境。",
                            evidence_ids=["boundary-review"],
                        )
                    ],
                    open_questions=[],
                    requested_transition="rework",
                ),
                evidence_store=evidence_store,
            )
            self.assertEqual("continue", gate.decision)
            self.assertEqual("strategic-design", state.current_node)
            self.assertEqual(
                ["resolve-design-sources", "discover-domain-facts"], state.completed_nodes
            )
            self.assertIn("boundary-review", state.evidence_refs)
            self.assertTrue(
                any(item["event"] == "boundary-rework" for item in state.transition_history)
            )

    def test_rework_is_rejected_outside_boundary_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            engine = RuntimeEngine(self.catalog)
            state = engine.start(
                "domain-task",
                self.intent(),
                run_id="domain-invalid-rework",
                design_source_ref="docs/design-sources.json",
            )
            state.current_node = "context-topology"
            evidence_store = EvidenceStore(StateStore(Path(temporary), ROOT / "schemas"))
            with self.assertRaisesRegex(ValidationFailure, "boundary-validation"):
                engine.complete_step(
                    state,
                    StepResult(
                        run_id=state.run_id,
                        node_id="context-topology",
                        status="failed",
                        criteria_results=[],
                        outputs=[],
                        findings=[],
                        open_questions=[],
                        requested_transition="rework",
                    ),
                    evidence_store=evidence_store,
                )

    def test_boundary_rework_requires_evidenced_major_or_blocker_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            engine = RuntimeEngine(self.catalog)
            state = engine.start(
                "domain-task",
                self.intent(),
                run_id="domain-unjustified-rework",
                design_source_ref="docs/design-sources.json",
            )
            state.current_node = "boundary-validation"
            evidence_store = EvidenceStore(StateStore(Path(temporary), ROOT / "schemas"))
            with self.assertRaisesRegex(ValidationFailure, "major or blocker"):
                engine.complete_step(
                    state,
                    StepResult(
                        run_id=state.run_id,
                        node_id="boundary-validation",
                        status="failed",
                        criteria_results=[],
                        outputs=[],
                        findings=[],
                        open_questions=[],
                        requested_transition="rework",
                    ),
                    evidence_store=evidence_store,
                )


if __name__ == "__main__":
    unittest.main()
