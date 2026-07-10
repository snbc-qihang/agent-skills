from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.engine import RuntimeEngine  # noqa: E402
from engineering_assistant.evidence import EvidenceStore  # noqa: E402
from engineering_assistant.model import CriterionResult, EvidenceRef, RouteIntent, StepResult  # noqa: E402
from engineering_assistant.router import ROUTES, route_intent  # noqa: E402
from engineering_assistant.state_store import RevisionConflict, StateStore  # noqa: E402


def intent(kind: str, *, risks=None, actions=None, confidence: float = 0.9) -> RouteIntent:
    return RouteIntent(
        task_kind=kind,
        requested_outcome=f"Complete a bounded {kind} task.",
        scope=["repository"],
        risk_signals=list(risks or []),
        requested_external_actions=list(actions or []),
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

    def test_release_waits_for_and_records_explicit_approval(self) -> None:
        decision = route_intent(intent("release"), self.catalog)
        state = self.engine.start("task-release", decision, run_id="release-1")
        self.assertEqual("waiting_for_approval", state.status)
        self.assertEqual("pause_for_approval", self.engine.next(state).decision)
        gate = self.engine.grant_approval(state, "release-execution")
        self.assertEqual("continue", gate.decision)
        self.assertEqual("initialized", state.status)

    def test_expired_approval_cannot_resume_high_risk_flow(self) -> None:
        decision = route_intent(intent("release"), self.catalog)
        state = self.engine.start("task-expiry", decision, run_id="release-expiry")
        self.engine.grant_approval(state, "release-execution")
        state.approval_expiries["release-execution"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        gate = self.engine.next(state)
        self.assertEqual("pause_for_approval", gate.decision)
        self.assertEqual(["release-execution"], gate.missing_evidence)

    def test_evidenced_completion_skip_and_resume_are_real_state_transitions(self) -> None:
        decision = route_intent(intent("design"), self.catalog)
        state = self.engine.start("task-design", decision, run_id="design-1")
        self.state_store.create(state)
        previous = state.revision
        gate = self.engine.next(state)
        self.assertEqual("repo-context", gate.next_node)
        self.state_store.save(state, expected_revision=previous)

        evidence_file = self.project / "repo-map.txt"
        evidence_file.write_text("module-a -> module-b\n", encoding="utf-8")
        evidence = self.evidence_store.save(
            state.run_id,
            EvidenceRef(
                id="repo-map",
                kind="source",
                uri=str(evidence_file),
                producer="test",
                observed_at=datetime.now(timezone.utc).isoformat(),
                trust_level="observed",
                scope="design repository context",
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
            available_evidence=self.evidence_store.ids(state.run_id),
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
            available_evidence=self.evidence_store.ids(resumed.run_id),
        )
        self.assertIn("prototype", resumed.skipped_nodes)
        self.assertEqual("architecture", gate.next_node)
        self.state_store.save(resumed, expected_revision=previous)

    def test_stale_evidence_can_be_excluded_by_runtime_policy(self) -> None:
        decision = route_intent(intent("design"), self.catalog)
        state = self.engine.start("task-stale", decision, run_id="stale-1")
        self.state_store.create(state)
        evidence_file = self.project / "stale.txt"
        evidence_file.write_text("old observation\n", encoding="utf-8")
        self.evidence_store.save(
            state.run_id,
            EvidenceRef(
                id="stale-source",
                kind="source",
                uri=str(evidence_file),
                producer="test",
                observed_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                trust_level="observed",
                scope="staleness eval",
            ),
        )
        self.assertIn("stale-source", self.evidence_store.ids(state.run_id))
        self.assertNotIn(
            "stale-source",
            self.evidence_store.ids(state.run_id, max_age_seconds=60),
        )

    def test_state_store_rejects_stale_writer(self) -> None:
        decision = route_intent(intent("shape"), self.catalog)
        state = self.engine.start("task-shape", decision, run_id="shape-1")
        self.state_store.create(state)
        stale = self.state_store.load(state.run_id)
        fresh = self.state_store.load(state.run_id)
        old_revision = fresh.revision
        self.engine.next(fresh)
        self.state_store.save(fresh, expected_revision=old_revision)
        self.engine.next(stale)
        with self.assertRaises(RevisionConflict):
            self.state_store.save(stale, expected_revision=old_revision)


if __name__ == "__main__":
    unittest.main()
