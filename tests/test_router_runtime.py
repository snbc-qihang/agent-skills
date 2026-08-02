from __future__ import annotations

import sys
import tempfile
import unittest
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.engine import RuntimeEngine  # noqa: E402
from engineering_assistant.evidence import EvidenceStore  # noqa: E402
from engineering_assistant.model import (  # noqa: E402
    CriterionResult,
    EvidenceRef,
    RouteIntent,
    StepResult,
)
from engineering_assistant.router import ROUTES, route_intent  # noqa: E402
from engineering_assistant.state_store import RevisionConflict, StateStore  # noqa: E402
from engineering_assistant.validation import (  # noqa: E402
    ValidationFailure,
    load_json,
    validate_instance,
)


def intent(kind: str, *, risks=None, actions=None, confirmed=None, confidence: float = 0.9) -> RouteIntent:
    return RouteIntent(
        task_kind=kind,
        requested_outcome=f"Complete a bounded {kind} task.",
        scope=["repository"],
        risk_signals=list(risks or []),
        requested_external_actions=list(actions or []),
        confirmed_actions=list(confirmed or []),
        confidence=confidence,
        evidence=["explicit user request"],
    )


class RouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog(ROOT)

    def test_every_semantic_kind_has_a_valid_route(self) -> None:
        for kind in ROUTES:
            with self.subTest(kind=kind):
                decision = route_intent(intent(kind), self.catalog)
                self.assertEqual("proceed" if kind != "release" else "confirm", decision.decision)
                if kind == "explain":
                    self.assertEqual([], decision.skill_ids)
                else:
                    self.assertTrue(decision.skill_ids)
                self.assertIn("safety-core", decision.policy_refs)

    def test_low_confidence_asks_without_preloading_a_flow(self) -> None:
        decision = route_intent(intent("design", confidence=0.4), self.catalog)
        self.assertEqual("ask", decision.decision)
        self.assertIsNone(decision.flow_id)
        self.assertEqual(["engineering-assistant"], decision.skill_ids)

    def test_high_risk_and_external_actions_never_proceed_unconfirmed(self) -> None:
        decision = route_intent(
            intent("implement", risks=["production"], actions=["push"]),
            self.catalog,
        )
        self.assertEqual("confirm", decision.decision)
        self.assertEqual(["push", "production"], decision.approval_required)

    def test_shape_and_design_routes_include_domain_modeling(self) -> None:
        self.assertEqual(
            ("shape", ("repo-context", "domain-modeling", "decision-interview")),
            ROUTES["shape"],
        )
        self.assertEqual(
            ("design", ("repo-context", "domain-modeling", "codebase-design")),
            ROUTES["design"],
        )
        self.assertEqual(
            ["domain-modeling"],
            route_intent(intent("model"), self.catalog).skill_ids,
        )


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(ROOT)
        self.engine = RuntimeEngine(self.catalog)
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.state_store = StateStore(self.project, ROOT / "schemas")
        self.evidence_store = EvidenceStore(self.state_store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_release_requires_same_intent_with_confirmed_action(self) -> None:
        with self.assertRaisesRegex(ValidationFailure, "route decision confirm"):
            self.engine.start("task-release", intent("release"), run_id="release-1")
        state = self.engine.start(
            "task-release",
            intent("release", confirmed=["release-execution"]),
            run_id="release-1",
        )
        self.assertEqual("readiness", self.engine.next(state).next_node)

    def test_release_readiness_rejects_stale_or_unrelated_evidence(self) -> None:
        state = self.engine.start(
            "task-release-evidence",
            intent("release", confirmed=["release-execution"]),
            run_id="release-evidence",
        )
        self.engine.next(state)
        old_path = self.project / "old-approval.txt"
        old_path.write_text("unrelated old approval\n", encoding="utf-8")
        self.evidence_store.save(
            state.run_id,
            self.attest_local(
                state.run_id,
                EvidenceRef(
                    id="old-unrelated-approval",
                    kind="approval",
                    uri=str(old_path),
                    producer="test-broker",
                    observed_at="2000-01-01T00:00:00+00:00",
                    provenance="runtime_observed",
                    scope="unrelated approval",
                ),
            ),
        )
        result = StepResult(
            state.run_id,
            "readiness",
            "completed",
            [
                CriterionResult(
                    "readiness:1", True, ["old-unrelated-approval"], "old evidence"
                )
            ],
            ["readiness"],
            [],
            [],
            "continue",
        )
        with self.assertRaisesRegex(ValidationFailure, "stale"):
            self.engine.complete_step(
                state, result, evidence_store=self.evidence_store
            )

        fresh_path = self.project / "fresh-unrelated.txt"
        fresh_path.write_text("fresh but unrelated\n", encoding="utf-8")
        self.evidence_store.save(
            state.run_id,
            self.attest_local(
                state.run_id,
                EvidenceRef(
                    id="fresh-unrelated-source",
                    kind="source",
                    uri=str(fresh_path),
                    producer="test-runner",
                    observed_at=datetime.now(timezone.utc).isoformat(),
                    provenance="runtime_observed",
                    scope="unrelated:not-flow:release",
                    scope_tags=["not-flow:release"],
                ),
            ),
        )
        unrelated = replace(
            result,
            criteria_results=[
                CriterionResult(
                    "readiness:1", True, ["fresh-unrelated-source"], "wrong scope"
                )
            ],
        )
        gate = self.engine.complete_step(
            state, unrelated, evidence_store=self.evidence_store
        )
        self.assertEqual("retry", gate.decision)
        self.assertIn("readiness:1:evidence-contract", gate.missing_evidence)
    def test_evidenced_completion_skip_and_resume_are_real_state_transitions(self) -> None:
        state = self.engine.start("task-design", intent("design"), run_id="design-1")
        self.state_store.create(state)
        previous = state.revision
        gate = self.engine.next(state)
        self.assertEqual("repo-context", gate.next_node)
        self.state_store.save(state, expected_revision=previous)

        evidence_file = self.project / "repo-map.txt"
        evidence_file.write_text("module-a -> module-b\n", encoding="utf-8")
        evidence = self.evidence_store.save(
            state.run_id,
            self.attest_local(
                state.run_id,
                EvidenceRef(
                id="repo-map",
                kind="source",
                uri=str(evidence_file),
                producer="test",
                observed_at=datetime.now(timezone.utc).isoformat(),
                provenance="runtime_observed",
                scope="design repository context",
            ),
            ),
        )
        self.assertTrue(evidence.digest.startswith("sha256:"))

        previous = state.revision
        gate = self.engine.complete_step(
            state,
            StepResult(
                run_id=state.run_id,
                node_id="repo-context",
                status="completed",
                criteria_results=[CriterionResult("repo-context:1", True, ["repo-map"])],
                outputs=["repo map"],
                findings=[],
                open_questions=[],
                requested_transition="continue",
            ),
            evidence_store=self.evidence_store,
        )
        self.assertEqual("prototype", gate.next_node)
        self.state_store.save(state, expected_revision=previous)

        resumed = self.state_store.load(state.run_id)
        self.assertEqual("prototype", resumed.current_node)
        previous = resumed.revision
        gate = self.engine.complete_step(
            resumed,
            StepResult(
                run_id=resumed.run_id,
                node_id="prototype",
                status="skipped",
                criteria_results=[],
                outputs=["UI prototype is not applicable to this backend-only design."],
                findings=[],
                open_questions=[],
                requested_transition="continue",
            ),
            evidence_store=self.evidence_store,
        )
        self.assertIn("prototype", resumed.skipped_nodes)
        self.assertEqual("domain-model", gate.next_node)
        self.assertEqual(
            "domain-modeling",
            self.engine.node_payload(resumed)["capability"],
        )
        self.state_store.save(resumed, expected_revision=previous)
        resumed = self.state_store.load(resumed.run_id)
        previous = resumed.revision
        gate = self.engine.complete_step(
            resumed,
            StepResult(
                run_id=resumed.run_id,
                node_id="domain-model",
                status="skipped",
                criteria_results=[],
                outputs=["Domain modeling is not applicable to this bounded infrastructure design."],
                findings=[],
                open_questions=[],
                requested_transition="continue",
            ),
            evidence_store=self.evidence_store,
        )
        self.assertIn("domain-model", resumed.skipped_nodes)
        self.assertEqual("architecture", gate.next_node)
        self.state_store.save(resumed, expected_revision=previous)

    def test_shape_domain_model_precedes_decision_interview_and_can_be_skipped(self) -> None:
        state = self.engine.start("task-shape-domain", intent("shape"), run_id="shape-domain-1")
        gate = self.engine.next(state)
        self.assertEqual("discover-facts", gate.next_node)
        gate = self.engine.complete_step(
            state,
            StepResult(
                run_id=state.run_id,
                node_id="discover-facts",
                status="skipped",
                criteria_results=[],
                outputs=["The request provides all repository facts needed for shaping."],
                findings=[],
                open_questions=[],
                requested_transition="continue",
            ),
            evidence_store=self.evidence_store,
        )
        self.assertEqual("domain-model", gate.next_node)
        gate = self.engine.complete_step(
            state,
            StepResult(
                run_id=state.run_id,
                node_id="domain-model",
                status="skipped",
                criteria_results=[],
                outputs=["No domain ambiguity changes scope, acceptance, or risk."],
                findings=[],
                open_questions=[],
                requested_transition="continue",
            ),
            evidence_store=self.evidence_store,
        )
        self.assertEqual("resolve-decisions", gate.next_node)

    def test_stale_evidence_can_be_excluded_by_runtime_policy(self) -> None:
        state = self.engine.start("task-stale", intent("design"), run_id="stale-1")
        self.state_store.create(state)
        evidence_file = self.project / "stale.txt"
        evidence_file.write_text("old observation\n", encoding="utf-8")
        self.evidence_store.save(
            state.run_id,
            self.attest_local(
                state.run_id,
                EvidenceRef(
                id="stale-source",
                kind="source",
                uri=str(evidence_file),
                producer="test",
                observed_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                provenance="runtime_observed",
                scope="staleness eval",
            ),
            ),
        )
        self.assertIn("stale-source", self.evidence_store.ids(state.run_id))
        self.assertNotIn(
            "stale-source",
            self.evidence_store.ids(state.run_id, max_age_seconds=60),
        )

    def test_state_store_rejects_stale_writer(self) -> None:
        state = self.engine.start("task-shape", intent("shape"), run_id="shape-1")
        self.state_store.create(state)
        stale = self.state_store.load(state.run_id)
        fresh = self.state_store.load(state.run_id)
        old_revision = fresh.revision
        self.engine.next(fresh)
        self.state_store.save(fresh, expected_revision=old_revision)
        self.engine.next(stale)
        with self.assertRaises(RevisionConflict):
            self.state_store.save(stale, expected_revision=old_revision)

    @staticmethod
    def attest_local(run_id: str, evidence: EvidenceRef) -> EvidenceRef:
        digest = "sha256:" + hashlib.sha256(Path(evidence.uri).read_bytes()).hexdigest()
        return replace(
            evidence,
            digest=digest,
        )


if __name__ == "__main__":
    unittest.main()
