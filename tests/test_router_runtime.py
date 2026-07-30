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
    RunApprovalGrant,
    StepResult,
)
from engineering_assistant.router import ROUTES, route_intent  # noqa: E402
from engineering_assistant.state_store import RevisionConflict, StateStore  # noqa: E402
from engineering_assistant.validation import (  # noqa: E402
    ValidationFailure,
    load_json,
    validate_instance,
)


class FakeTrustVerifier:
    def verify_evidence(self, run_id: str, evidence: EvidenceRef) -> bool:
        return evidence.attestation == f"test-receipt:{run_id}:{evidence.id}"

    def verify_decision(self, grant) -> bool:
        return False

    def verify_run_approval(self, grant) -> bool:
        return grant.token == f"test-run-grant:{grant.grant_id}"


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
                decision = route_intent(intent(kind), self.catalog, profile_id="default")
                self.assertEqual("proceed" if kind != "release" else "confirm", decision.decision)
                if kind == "explain":
                    self.assertEqual([], decision.skill_ids)
                else:
                    self.assertTrue(decision.skill_ids)
                self.assertIn("safety-core", decision.policy_refs)

    def test_low_confidence_asks_without_preloading_a_flow(self) -> None:
        decision = route_intent(
            intent("design", confidence=0.4), self.catalog, profile_id="default"
        )
        self.assertEqual("ask", decision.decision)
        self.assertIsNone(decision.flow_id)
        self.assertEqual(["engineering-assistant"], decision.skill_ids)

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
            route_intent(intent("model"), self.catalog, profile_id="default").skill_ids,
        )

    def test_high_risk_and_external_actions_never_proceed_unconfirmed(self) -> None:
        decision = route_intent(
            intent("implement", risks=["production"], actions=["push"]),
            self.catalog,
            profile_id="default",
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
        self.evidence_store = EvidenceStore(self.state_store, FakeTrustVerifier())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def start(self, *args, **kwargs):
        kwargs.setdefault("profile_id", "default")
        return self.engine.start(*args, **kwargs)

    @staticmethod
    def approval_grant(state, *, grant_id: str = "release-grant") -> RunApprovalGrant:
        return RunApprovalGrant(
            grant_id=grant_id,
            broker_id="test-broker",
            audience="engineering-assistant",
            action="run.approve",
            run_id=state.run_id,
            run_revision=state.revision,
            approval_id="release-execution",
            scope=["flow:release", "approval:release-execution"],
            issued_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            actor_ref="opaque-human",
            nonce="0123456789abcdef",
            token=f"test-run-grant:{grant_id}",
        )

    def apply_approval(self, state) -> None:
        self.engine.apply_approval(
            state,
            self.approval_grant(state),
            verifier=FakeTrustVerifier(),
            expected_broker_id="test-broker",
            expected_audience="engineering-assistant",
        )

    def test_release_waits_for_and_records_explicit_approval(self) -> None:
        state = self.start("task-release", intent("release"), run_id="release-1")
        self.assertEqual("waiting_for_approval", state.status)
        self.assertEqual("pause_for_approval", self.engine.next(state).decision)
        gate = self.engine.apply_approval(
            state,
            self.approval_grant(state),
            verifier=FakeTrustVerifier(),
            expected_broker_id="test-broker",
            expected_audience="engineering-assistant",
        )
        self.assertEqual("continue", gate.decision)
        self.assertEqual("initialized", state.status)
        self.assertEqual(1, len(state.approval_records))
        self.assertNotIn("token", state.approval_records[0])
        self.assertEqual("opaque-human", state.approval_records[0]["actor_ref"])
        self.assertEqual(
            ["flow:release", "approval:release-execution"],
            state.approval_records[0]["scope"],
        )
        invalid = state.to_dict()
        invalid["approval_records"][0]["token"] = "must-not-persist"
        with self.assertRaises(ValidationFailure):
            validate_instance(
                invalid,
                load_json(ROOT / "schemas/run-state.schema.json"),
                "run-state",
            )

    def test_expired_approval_cannot_resume_high_risk_flow(self) -> None:
        state = self.start("task-expiry", intent("release"), run_id="release-expiry")
        self.apply_approval(state)
        state.approval_expiries["release-execution"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        gate = self.engine.next(state)
        self.assertEqual("pause_for_approval", gate.decision)
        self.assertEqual(["release-execution"], gate.missing_evidence)

    def test_run_approval_rejects_forged_or_insufficient_scope_grants(self) -> None:
        state = self.start(
            "task-forged-approval", intent("release"), run_id="release-forged"
        )
        with self.assertRaisesRegex(ValidationFailure, "external broker grant"):
            self.engine.apply_approval(
                state,
                replace(self.approval_grant(state), token="forged-approval-token"),
                verifier=FakeTrustVerifier(),
                expected_broker_id="test-broker",
                expected_audience="engineering-assistant",
            )
        with self.assertRaisesRegex(ValidationFailure, "insufficient scope"):
            self.engine.apply_approval(
                state,
                replace(
                    self.approval_grant(state, grant_id="scope-grant"),
                    scope=["flow:release"],
                ),
                verifier=FakeTrustVerifier(),
                expected_broker_id="test-broker",
                expected_audience="engineering-assistant",
            )
        valid = self.approval_grant(state, grant_id="binding-grant")
        for label, grant, broker, audience, message in (
            ("broker", valid, "other-broker", "engineering-assistant", "wrong broker"),
            ("audience", valid, "test-broker", "other-audience", "wrong audience"),
            (
                "revision",
                replace(valid, run_revision=state.revision + 1),
                "test-broker",
                "engineering-assistant",
                "stale run",
            ),
            (
                "expired",
                replace(
                    valid,
                    expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                ),
                "test-broker",
                "engineering-assistant",
                "not currently valid",
            ),
        ):
            with self.subTest(label=label), self.assertRaisesRegex(
                ValidationFailure, message
            ):
                self.engine.apply_approval(
                    state,
                    grant,
                    verifier=FakeTrustVerifier(),
                    expected_broker_id=broker,
                    expected_audience=audience,
                )

    def test_release_readiness_rejects_stale_or_unrelated_evidence(self) -> None:
        state = self.start(
            "task-release-evidence", intent("release"), run_id="release-evidence"
        )
        self.apply_approval(state)
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
                    trust_level="observed",
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
                    trust_level="observed",
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
        state = self.start("task-design", intent("design"), run_id="design-1")
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
                trust_level="observed",
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

        resumed = self.state_store.load(state.run_id)
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

    def test_stale_evidence_can_be_excluded_by_runtime_policy(self) -> None:
        state = self.start("task-stale", intent("design"), run_id="stale-1")
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
                trust_level="observed",
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
        state = self.start("task-shape", intent("shape"), run_id="shape-1")
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
            attestation=f"test-receipt:{run_id}:{evidence.id}",
        )


if __name__ == "__main__":
    unittest.main()
