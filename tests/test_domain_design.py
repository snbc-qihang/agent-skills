from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.artifact_validation import validate_artifact_payload  # noqa: E402
from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.engine import RuntimeEngine  # noqa: E402
from engineering_assistant.evidence import EvidenceStore  # noqa: E402
from engineering_assistant.model import (  # noqa: E402
    CriterionResult,
    EvidenceRef,
    Finding,
    RouteIntent,
    RunApprovalGrant,
    StepResult,
)
from engineering_assistant.router import route_intent  # noqa: E402
from engineering_assistant.state_store import StateStore  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class Trust:
    def verify_evidence(self, _run_id, _evidence) -> bool:
        return True

    def verify_run_approval(self, grant) -> bool:
        return grant.token.startswith("approved:")


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
            confidence=0.95,
            evidence=["user request"],
        )

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
                "capability-detailed-design",
                "integration-consistency",
                "design-conformance-review",
                "baseline-approval",
            ],
            [node.id for node in flow.nodes],
        )
        self.assertIn("domain-integration", self.catalog.packs)
        self.assertIn("domain-design-governance", self.catalog.policies)

    def test_design_source_registry_requires_topology_and_formal_locations(self) -> None:
        artifact = {
            "version": "1",
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
        self.assertEqual(
            {"status": "passed", "kind": "design-source-registry"},
            validate_artifact_payload(
                schema_root=ROOT / "schemas", kind="design-source-registry", artifact=artifact
            ),
        )

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
            evidence_store = EvidenceStore(store, Trust())
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

            for approval_id in state.required_approvals:
                grant = RunApprovalGrant(
                    grant_id=f"grant-{approval_id}",
                    broker_id="test-broker",
                    audience="engineering-assistant",
                    action="run.approve",
                    run_id=state.run_id,
                    run_revision=state.revision,
                    approval_id=approval_id,
                    scope=["flow:domain-design", f"approval:{approval_id}"],
                    issued_at=datetime.now(timezone.utc).isoformat(),
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    actor_ref="opaque-human",
                    nonce="0123456789abcdef",
                    token=f"approved:{approval_id}",
                )
                engine.apply_approval(
                    state,
                    grant,
                    verifier=Trust(),
                    expected_broker_id="test-broker",
                    expected_audience="engineering-assistant",
                )
            self.assertEqual("initialized", state.status)

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
            evidence_store = EvidenceStore(store, Trust())
            evidence_store.save(
                state.run_id,
                EvidenceRef(
                    id="boundary-review",
                    kind="review",
                    uri="boundary-review.md",
                    producer="domain-review",
                    observed_at=datetime.now(timezone.utc).isoformat(),
                    trust_level="observed",
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
            evidence_store = EvidenceStore(StateStore(Path(temporary), ROOT / "schemas"), Trust())
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
            evidence_store = EvidenceStore(StateStore(Path(temporary), ROOT / "schemas"), Trust())
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
