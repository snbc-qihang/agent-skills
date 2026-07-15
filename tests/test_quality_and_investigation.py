from __future__ import annotations

import sys
import tempfile
import unittest
import hashlib
import io
from contextlib import redirect_stderr
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.cli import build_parser  # noqa: E402
from engineering_assistant.engine import RuntimeEngine  # noqa: E402
from engineering_assistant.evidence import EvidenceStore  # noqa: E402
from engineering_assistant.governance import (  # noqa: E402
    InvestigationStore,
    QualityGate,
    QualityStore,
    investigation_evidence_contract,
)
from engineering_assistant.mcp_server import RuntimeTools  # noqa: E402
from engineering_assistant.model import (  # noqa: E402
    CriterionResult,
    EvidenceRef,
    InvestigationRequest,
    InvestigationDecisionGrant,
    QualityDimension,
    QualitySnapshot,
    RouteIntent,
    StepResult,
)
from engineering_assistant.state_store import StateStore  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402
from engineering_assistant.trust import TrustVerifier  # noqa: E402


DIMENSIONS = (
    "correctness",
    "complexity",
    "redundancy",
    "performance",
    "architecture",
    "test_quality",
)


class FakeTrustVerifier:
    def verify_evidence(self, run_id: str, evidence: EvidenceRef) -> bool:
        return evidence.attestation == f"test-receipt:{run_id}:{evidence.id}"

    def verify_decision(self, grant: InvestigationDecisionGrant) -> bool:
        return grant.token == f"test-grant:{grant.grant_id}"

    def verify_run_approval(self, grant) -> bool:
        return False


class GovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(ROOT)
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.state_store = StateStore(self.project, ROOT / "schemas")
        self.verifier: TrustVerifier = FakeTrustVerifier()
        self.evidence_store = EvidenceStore(self.state_store, self.verifier)
        self.quality_store = QualityStore(self.state_store, self.evidence_store)
        self.investigation_store = InvestigationStore(
            self.state_store, self.evidence_store
        )
        self.now = datetime.now(timezone.utc).isoformat()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def evidence(self, run_id: str, evidence_id: str = "quality-observation") -> None:
        candidate_digest = "sha256:" + hashlib.sha256(
            b"observed candidate source\n"
        ).hexdigest()
        observed = self.project / f"{evidence_id}.txt"
        observed.write_text("observed quality result\n", encoding="utf-8")
        evidence = EvidenceRef(
            id=evidence_id,
            kind="test",
            uri=str(observed),
            producer="test",
            observed_at=self.now,
            trust_level="observed",
            scope="changed code",
            subject_digest=candidate_digest,
        )
        self.evidence_store.save(
            run_id,
            self.attest_local(run_id, evidence),
        )
        performance_path = self.project / "performance-observation.txt"
        performance_path.write_text("observed benchmark result\n", encoding="utf-8")
        performance = EvidenceRef(
            id="performance-observation",
            kind="test",
            uri=str(performance_path),
            producer="benchmark-runner",
            observed_at=self.now,
            trust_level="observed",
            scope="changed code benchmark workload",
            scope_tags=[
                "quality-dimension:performance",
                "quality-measurement:benchmark",
            ],
            subject_digest=candidate_digest,
        )
        self.evidence_store.save(
            run_id,
            self.attest_local(run_id, performance),
        )
        review_path = self.project / "quality-review.txt"
        review_path.write_text("independent quality review\n", encoding="utf-8")
        review = EvidenceRef(
            id="quality-review",
            kind="review",
            uri=str(review_path),
            producer="review-provider",
            observed_at=self.now,
            trust_level="observed",
            scope="complexity redundancy performance architecture and tests",
            subject_digest=candidate_digest,
        )
        self.evidence_store.save(
            run_id,
            self.attest_local(run_id, review),
        )
        candidate = self.project / "candidate.diff"
        candidate.write_text("observed candidate source\n", encoding="utf-8")
        candidate_evidence = EvidenceRef(
            id="candidate-source",
            kind="source",
            uri=str(candidate),
            producer="runtime-observer",
            observed_at=self.now,
            trust_level="observed",
            scope="changed code candidate",
            subject_digest=candidate_digest,
        )
        self.evidence_store.save(
            run_id,
            self.attest_local(run_id, candidate_evidence),
        )

    @staticmethod
    def attest_local(run_id: str, evidence: EvidenceRef) -> EvidenceRef:
        digest = "sha256:" + hashlib.sha256(Path(evidence.uri).read_bytes()).hexdigest()
        return replace(
            evidence,
            digest=digest,
            attestation=f"test-receipt:{run_id}:{evidence.id}",
        )

    def investigation_evidence(
        self,
        record,
        evidence_id: str,
        source_scope: str,
        *,
        kind: str = "source",
        covered_contract_refs: list[str] | None = None,
    ) -> EvidenceRef:
        contract = investigation_evidence_contract(record)
        observed = self.project / f"{evidence_id}.txt"
        observed.write_text("observed investigation result\n", encoding="utf-8")
        evidence = EvidenceRef(
            id=evidence_id,
            kind=kind,
            uri=str(observed),
            producer="research-host",
            observed_at=self.now,
            trust_level="observed",
            scope="investigation evidence",
            scope_tags=[
                *contract["required_scope_tags"],
                f"investigation-source:{source_scope}",
            ],
            contract_refs=(
                contract["required_contract_refs"]
                if covered_contract_refs is None
                else covered_contract_refs
            ),
            subject_digest=contract["subject_digest"],
        )
        return self.evidence_store.save(
            record.request.run_id,
            self.attest_local(record.request.run_id, evidence),
        )

    def snapshot(self, run_id: str, *, status: str = "pass") -> QualitySnapshot:
        return QualitySnapshot(
            id="quality-1",
            run_id=run_id,
            node_id="quality",
            state_revision=0,
            base_ref="base-sha",
            candidate_ref="sha256:"
            + hashlib.sha256(b"observed candidate source\n").hexdigest(),
            candidate_evidence_id="candidate-source",
            dimensions=[
                QualityDimension(
                    item,
                    status,
                    0,
                    f"{item} was observed",
                    [
                        "performance-observation"
                        if item == "performance"
                        else "quality-observation"
                        if item in {"correctness", "test_quality"}
                        else "quality-review"
                    ],
                )
                for item in DIMENSIONS
            ],
            findings=[],
            required_repairs=[],
            evidence_refs=[
                "quality-observation",
                "performance-observation",
                "quality-review",
                "candidate-source",
            ],
            observed_at=self.now,
        )

    def test_quality_store_requires_all_dimensions_and_registered_evidence(self) -> None:
        self.evidence("run-quality")
        incomplete = self.snapshot("run-quality")
        incomplete = replace(incomplete, dimensions=incomplete.dimensions[:-1])
        with self.assertRaisesRegex(ValidationFailure, "exactly once"):
            self.quality_store.save(incomplete)

        with self.assertRaisesRegex(ValidationFailure, "unregistered evidence"):
            missing = self.snapshot("run-quality")
            missing = replace(
                missing,
                dimensions=[
                    replace(item, evidence_ids=["missing-evidence"])
                    if item.id == "correctness"
                    else item
                    for item in missing.dimensions
                ],
            )
            self.quality_store.save(missing)

    def test_generic_test_evidence_cannot_satisfy_performance_quality(self) -> None:
        self.evidence("run-performance-generic")
        snapshot = self.snapshot("run-performance-generic")
        snapshot = replace(
            snapshot,
            dimensions=[
                replace(item, evidence_ids=["quality-observation"])
                if item.id == "performance"
                else item
                for item in snapshot.dimensions
            ],
        )
        with self.assertRaisesRegex(
            ValidationFailure,
            "performance.*benchmark or profile",
        ):
            self.quality_store.save(snapshot)

    def test_claimed_evidence_cannot_satisfy_a_quality_gate(self) -> None:
        claimed = self.project / "claimed.txt"
        claimed.write_text("model claim only\n", encoding="utf-8")
        self.evidence_store.save(
            "run-quality",
            EvidenceRef(
                id="claimed-quality",
                kind="review",
                uri=str(claimed),
                producer="model",
                observed_at=self.now,
                trust_level="claimed",
                scope="changed code",
            ),
        )
        self.assertNotIn(
            "claimed-quality",
            self.evidence_store.ids("run-quality", minimum_trust_level="observed"),
        )

    def test_observed_evidence_without_host_attestation_is_rejected(self) -> None:
        observed = self.project / "forged.txt"
        observed.write_text("forged observation\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationFailure, "host attestation"):
            self.evidence_store.save(
                "run-quality",
                EvidenceRef(
                    id="forged-observed",
                    kind="test",
                    uri=str(observed),
                    producer="model",
                    observed_at=self.now,
                    trust_level="observed",
                    scope="changed code",
                ),
            )

    def test_governance_store_rejects_nested_symlink_escape(self) -> None:
        self.evidence("run-quality")
        outside = self.project / "outside"
        outside.mkdir()
        run_directory = self.state_store.run_dir("run-quality")
        run_directory.mkdir(parents=True, exist_ok=True)
        (run_directory / "quality").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValidationFailure, "symlink|escapes"):
            self.quality_store.save(
                self.snapshot("run-quality"),
            )

    def test_quality_gate_rejects_warn_fail_not_evaluated_and_repairs(self) -> None:
        for status in ("warn", "fail", "not_evaluated"):
            with self.subTest(status=status):
                assessment = QualityGate.evaluate(self.snapshot("run-quality", status=status))
                self.assertEqual("repair", assessment.decision)
        snapshot = self.snapshot("run-quality")
        snapshot = replace(snapshot, required_repairs=["remove duplicate path"])
        self.assertEqual("repair", QualityGate.evaluate(snapshot).decision)

    def test_passing_snapshot_allows_mandatory_quality_node_completion(self) -> None:
        engine = RuntimeEngine(self.catalog)
        task_intent = RouteIntent(
                task_kind="implement",
                requested_outcome="Implement accepted behavior.",
                scope=["repository"],
                risk_signals=[],
                requested_external_actions=[],
                confidence=0.95,
                evidence=["explicit request"],
        )
        state = engine.start("task-quality", task_intent, run_id="run-quality")
        state.current_node = "quality"
        state.status = "running"
        self.evidence(state.run_id)
        candidate = self.evidence_store.get(state.run_id, "candidate-source")
        snapshot = replace(
            self.snapshot(state.run_id),
            state_revision=state.revision,
            candidate_ref=candidate.digest,
        )
        result = StepResult(
            run_id=state.run_id,
            node_id="quality",
            status="completed",
            criteria_results=[CriterionResult("quality:1", True, ["quality-observation"])],
            outputs=["quality snapshot: quality-1"],
            findings=[],
            open_questions=[],
            requested_transition="continue",
        )
        without_snapshot = engine.complete_step(
            state,
            result,
            evidence_store=self.evidence_store,
        )
        self.assertEqual("retry", without_snapshot.decision)
        snapshot = self.quality_store.save(
            replace(snapshot, id="quality-2", state_revision=state.revision),
            current_state_revision=state.revision,
        )
        with_snapshot = engine.complete_step(
            state,
            result,
            evidence_store=self.evidence_store,
        )
        self.assertNotEqual("retry", with_snapshot.decision)
        self.assertIn("quality", state.completed_nodes)

        candidate_path = self.project / "candidate.diff"
        candidate_path.write_text("candidate changed after review\n", encoding="utf-8")
        self.assertIsNone(
            self.quality_store.latest_valid(
                state.run_id, "quality", current_state_revision=state.revision
            )
        )

    def test_design_review_gate_does_not_require_a_code_quality_snapshot(self) -> None:
        engine = RuntimeEngine(self.catalog)
        task_intent = RouteIntent(
                task_kind="review",
                requested_outcome="Review a design contract.",
                scope=["design"],
                risk_signals=[],
                requested_external_actions=[],
                confidence=0.95,
                evidence=["explicit request"],
        )
        state = engine.start("design-review", task_intent, run_id="design-review")
        state.current_node = "gate"
        state.status = "running"
        review_path = self.project / "design-review.txt"
        review_path.write_text("observed design review\n", encoding="utf-8")
        review_evidence = EvidenceRef(
            id="review-evidence",
            kind="review",
            uri=str(review_path),
            producer="review-provider",
            observed_at=self.now,
            trust_level="observed",
            scope="design gate",
        )
        self.evidence_store.save(
            state.run_id, self.attest_local(state.run_id, review_evidence)
        )
        gate = engine.complete_step(
            state,
            StepResult(
                run_id=state.run_id,
                node_id="gate",
                status="completed",
                criteria_results=[CriterionResult("gate:1", True, ["review-evidence"])],
                outputs=["design review gate"],
                findings=[],
                open_questions=[],
                requested_transition="continue",
            ),
            evidence_store=self.evidence_store,
        )
        self.assertNotEqual("retry", gate.decision)

    def test_candidate_change_invalidates_a_passing_snapshot(self) -> None:
        self.evidence("run-candidate")
        candidate = self.evidence_store.get("run-candidate", "candidate-source")
        snapshot = self.quality_store.save(
            replace(self.snapshot("run-candidate"), candidate_ref=candidate.digest),
            current_state_revision=0,
        )
        self.assertEqual(
            snapshot,
            self.quality_store.latest_valid(
                "run-candidate", "quality", current_state_revision=0
            ),
        )
        (self.project / "candidate.diff").write_text("changed after snapshot\n", encoding="utf-8")
        self.assertIsNone(
            self.quality_store.latest_valid(
                "run-candidate", "quality", current_state_revision=0
            )
        )

    def test_changed_dimension_evidence_invalidates_a_passing_snapshot(self) -> None:
        self.evidence("run-dimension-change")
        candidate = self.evidence_store.get("run-dimension-change", "candidate-source")
        self.quality_store.save(
            replace(
                self.snapshot("run-dimension-change"), candidate_ref=candidate.digest
            ),
            current_state_revision=0,
        )
        (self.project / "quality-review.txt").write_text(
            "review changed after the snapshot\n", encoding="utf-8"
        )
        self.assertIsNone(
            self.quality_store.latest_valid(
                "run-dimension-change", "quality", current_state_revision=0
            )
        )

    def test_quality_snapshot_rejects_stale_future_and_wrong_revision(self) -> None:
        self.evidence("run-time-boundary")
        stale = replace(
            self.snapshot("run-time-boundary"),
            id="quality-stale",
            observed_at=(
                datetime.now(timezone.utc)
                - timedelta(seconds=self.quality_store.MAX_AGE_SECONDS + 1)
            ).isoformat(),
        )
        with self.assertRaisesRegex(ValidationFailure, "stale"):
            self.quality_store.save(
                stale, current_state_revision=0
            )
        future = replace(
            self.snapshot("run-time-boundary"),
            id="quality-future",
            observed_at=(
                datetime.now(timezone.utc)
                + timedelta(seconds=self.quality_store.MAX_FUTURE_SKEW_SECONDS + 1)
            ).isoformat(),
        )
        with self.assertRaisesRegex(ValidationFailure, "future"):
            self.quality_store.save(
                future, current_state_revision=0
            )
        wrong_revision = replace(
            self.snapshot("run-time-boundary"),
            id="quality-wrong-revision",
            state_revision=1,
        )
        with self.assertRaisesRegex(ValidationFailure, "stale run revision"):
            self.quality_store.save(
                wrong_revision,
                current_state_revision=0,
            )

    def test_fresh_snapshot_cannot_reuse_stale_quality_evidence(self) -> None:
        current = self.now
        self.now = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        self.evidence("run-stale-quality-evidence")
        self.now = current
        candidate = self.evidence_store.get(
            "run-stale-quality-evidence", "candidate-source"
        )
        with self.assertRaisesRegex(ValidationFailure, "stale"):
            self.quality_store.save(
                replace(
                    self.snapshot("run-stale-quality-evidence"),
                    candidate_ref=candidate.digest,
                    observed_at=datetime.now(timezone.utc).isoformat(),
                ),
                current_state_revision=0,
            )

    def test_quality_evidence_for_an_old_candidate_cannot_be_reused(self) -> None:
        self.evidence("run-old-evidence")
        old_path = self.project / "old-review.txt"
        old_path.write_text("review of another candidate\n", encoding="utf-8")
        old_review = EvidenceRef(
            id="old-review",
            kind="review",
            uri=str(old_path),
            producer="review-provider",
            observed_at=self.now,
            trust_level="observed",
            scope="old candidate",
            subject_digest="sha256:" + "f" * 64,
        )
        self.evidence_store.save(
            "run-old-evidence",
            self.attest_local("run-old-evidence", old_review),
        )
        candidate = self.evidence_store.get("run-old-evidence", "candidate-source")
        snapshot = replace(
            self.snapshot("run-old-evidence"),
            id="quality-old-evidence",
            candidate_ref=candidate.digest,
            dimensions=[
                replace(item, evidence_ids=["old-review"])
                if item.id == "complexity"
                else item
                for item in self.snapshot("run-old-evidence").dimensions
            ],
            evidence_refs=[
                "quality-observation",
                "quality-review",
                "candidate-source",
                "old-review",
            ],
        )
        with self.assertRaisesRegex(ValidationFailure, "not bound to the candidate"):
            self.quality_store.save(
                snapshot,
                current_state_revision=0,
            )

    def test_quality_node_can_report_a_real_blocker_before_a_snapshot_exists(self) -> None:
        engine = RuntimeEngine(self.catalog)
        task_intent = RouteIntent(
                task_kind="implement",
                requested_outcome="Implement accepted behavior.",
                scope=["repository"],
                risk_signals=[],
                requested_external_actions=[],
                confidence=0.95,
                evidence=["explicit request"],
        )
        state = engine.start(
            "task-blocked-quality", task_intent, run_id="run-blocked-quality"
        )
        state.current_node = "quality"
        state.status = "running"
        gate = engine.complete_step(
            state,
            StepResult(
                run_id=state.run_id,
                node_id="quality",
                status="blocked",
                criteria_results=[],
                outputs=[],
                findings=[],
                open_questions=["required benchmark environment is unavailable"],
                requested_transition="block",
            ),
            evidence_store=self.evidence_store,
        )
        self.assertEqual("block", gate.decision)
        self.assertEqual("blocked", state.status)

    def request(self, *, mode: str = "suggest_then_run") -> InvestigationRequest:
        return InvestigationRequest(
            id="investigate-1",
            run_id="run-investigation",
            question="Which official API contract applies?",
            reason="The implementation boundary is uncertain.",
            source_scope=["official_docs", "source_repository"],
            reported_blocking=True,
            mode=mode,
            estimated_cost="low",
            stop_conditions=["The primary contract is identified."],
            evidence_requirements=["Official documentation or source code."],
            status="proposed",
        )

    def test_investigation_requires_audited_human_decision_and_valid_transitions(self) -> None:
        record = self.investigation_store.propose(self.request())
        self.assertEqual("proposed", record.request.status)
        with self.assertRaisesRegex(ValidationFailure, "approved"):
            self.investigation_store.start("run-investigation", "investigate-1")

        grant = InvestigationDecisionGrant(
                grant_id="human-review-42",
                broker_id="test-broker",
                audience="engineering-assistant",
                action="investigation.select_mode",
                run_id="run-investigation",
                investigation_id="investigate-1",
                run_revision=0,
                decision="approve",
                selected_mode="guided",
                allowed_source_scope=["official_docs"],
                max_cost="low",
                issued_at=self.now,
                expires_at="2099-01-01T00:00:00+00:00",
                actor_ref="opaque-human",
                nonce="0123456789abcdef",
                token="test-grant:human-review-42",
            )
        approved = self.investigation_store.apply_grant(
            grant,
            verifier=self.verifier,
            current_run_revision=0,
        )
        self.assertEqual("approved", approved.request.status)
        self.assertEqual("guided", approved.request.mode)
        self.assertEqual(["official_docs"], approved.current_source_scope)
        self.assertEqual(["source_repository"], approved.remaining_source_scope)
        self.assertEqual("human-review-42", approved.decision_ref)
        running = self.investigation_store.start("run-investigation", "investigate-1")
        self.assertEqual("running", running.request.status)
        with self.assertRaisesRegex(ValidationFailure, "evidence"):
            self.investigation_store.finish(
                "run-investigation", "investigate-1", outcome="completed", evidence_refs=[]
            )
        official_evidence = self.investigation_evidence(
            running,
            "investigation-official-docs",
            "official_docs",
            covered_contract_refs=investigation_evidence_contract(running)[
                "required_contract_refs"
            ][:1],
        )
        next_step = self.investigation_store.finish(
            "run-investigation",
            "investigate-1",
            outcome="completed",
            evidence_refs=[official_evidence.id],
        )
        self.assertEqual("proposed", next_step.request.status)
        self.assertEqual(["source_repository"], next_step.remaining_source_scope)

        second = replace(
            grant,
            grant_id="human-review-43",
            allowed_source_scope=["source_repository"],
            nonce="fedcba9876543210",
            token="test-grant:human-review-43",
        )
        approved_second = self.investigation_store.apply_grant(
            second, verifier=self.verifier, current_run_revision=0
        )
        self.assertEqual(["source_repository"], approved_second.current_source_scope)
        running_second = self.investigation_store.start(
            "run-investigation", "investigate-1"
        )
        source_evidence = self.investigation_evidence(
            running_second,
            "investigation-source-repository",
            "source_repository",
            covered_contract_refs=investigation_evidence_contract(running_second)[
                "required_contract_refs"
            ][1:],
        )
        completed = self.investigation_store.finish(
            "run-investigation",
            "investigate-1",
            outcome="completed",
            evidence_refs=[source_evidence.id],
        )
        self.assertEqual("completed", completed.request.status)
        self.assertEqual(
            [official_evidence.id, source_evidence.id],
            completed.evidence_refs,
        )

    def test_investigation_list_is_bounded_and_cursor_paginated(self) -> None:
        for investigation_id in ("investigate-a", "investigate-b", "investigate-c"):
            self.investigation_store.propose(
                replace(self.request(), id=investigation_id)
            )

        first, next_after_id = self.investigation_store.list(
            "run-investigation", limit=2
        )
        self.assertEqual(
            ["investigate-a", "investigate-b"],
            [item.request.id for item in first],
        )
        self.assertEqual("investigate-b", next_after_id)

        second, next_after_id = self.investigation_store.list(
            "run-investigation", limit=2, after_id=next_after_id
        )
        self.assertEqual(["investigate-c"], [item.request.id for item in second])
        self.assertIsNone(next_after_id)

    def test_investigation_can_finish_blocked_with_bound_runtime_evidence(self) -> None:
        running = self.investigation_store.propose(
            replace(
                self.request(mode="auto_readonly"),
                id="blocked-research",
                source_scope=["official_docs"],
            ),
            investigation_policy={
                "default_mode": "auto_readonly",
                "auto_readonly": {
                    "enabled": True,
                    "authorization_id": "profile-choice",
                    "allowed_source_scope": ["official_docs"],
                    "max_cost": "low",
                },
            },
        )
        blocker = self.investigation_evidence(
            running,
            "official-docs-unavailable",
            "official_docs",
            kind="external_state",
            covered_contract_refs=[],
        )

        blocked = self.investigation_store.finish(
            "run-investigation",
            "blocked-research",
            outcome="blocked",
            evidence_refs=[blocker.id],
        )

        self.assertEqual("blocked", blocked.request.status)
        self.assertEqual([blocker.id], blocked.evidence_refs)

    def test_investigation_rejects_observed_evidence_not_bound_to_its_contract(
        self,
    ) -> None:
        running = self.investigation_store.propose(
            replace(self.request(), id="bound-evidence", mode="auto_readonly"),
            investigation_policy={
                "default_mode": "auto_readonly",
                "auto_readonly": {
                    "enabled": True,
                    "authorization_id": "profile-choice",
                    "allowed_source_scope": ["official_docs", "source_repository"],
                    "max_cost": "low",
                },
            },
        )
        self.assertEqual("running", running.request.status)
        self.evidence("run-investigation")
        with self.assertRaisesRegex(ValidationFailure, "subject digest"):
            self.investigation_store.finish(
                "run-investigation",
                "bound-evidence",
                outcome="completed",
                evidence_refs=["quality-observation"],
            )

    def test_investigation_rejects_evidence_outside_approved_source_scope(
        self,
    ) -> None:
        running = self.investigation_store.propose(
            replace(self.request(), id="bounded-source", mode="auto_readonly"),
            investigation_policy={
                "default_mode": "auto_readonly",
                "auto_readonly": {
                    "enabled": True,
                    "authorization_id": "profile-choice",
                    "allowed_source_scope": ["official_docs", "source_repository"],
                    "max_cost": "low",
                },
            },
        )
        contract = investigation_evidence_contract(running)
        self.assertEqual(
            [
                "investigation-source:official_docs",
                "investigation-source:source_repository",
            ],
            contract["source_scope_tags"],
        )
        outside = self.investigation_evidence(running, "outside-scope", "issues")

        with self.assertRaisesRegex(ValidationFailure, "approved source scope"):
            self.investigation_store.finish(
                "run-investigation",
                "bounded-source",
                outcome="completed",
                evidence_refs=[outside.id],
            )

    def test_investigation_requires_evidence_for_each_contract_clause(self) -> None:
        running = self.investigation_store.propose(
            replace(self.request(), id="incomplete-contract", mode="auto_readonly"),
            investigation_policy={
                "default_mode": "auto_readonly",
                "auto_readonly": {
                    "enabled": True,
                    "authorization_id": "profile-choice",
                    "allowed_source_scope": ["official_docs", "source_repository"],
                    "max_cost": "low",
                },
            },
        )
        contract = investigation_evidence_contract(running)
        incomplete = self.investigation_evidence(
            running,
            "incomplete-contract-evidence",
            "official_docs",
            covered_contract_refs=contract["required_contract_refs"][:1],
        )

        with self.assertRaisesRegex(ValidationFailure, "cover every requirement"):
            self.investigation_store.finish(
                "run-investigation",
                "incomplete-contract",
                outcome="completed",
                evidence_refs=[incomplete.id],
            )

    def test_investigation_rejects_incompatible_evidence_kind(self) -> None:
        running = self.investigation_store.propose(
            replace(self.request(), id="wrong-evidence-kind", mode="auto_readonly"),
            investigation_policy={
                "default_mode": "auto_readonly",
                "auto_readonly": {
                    "enabled": True,
                    "authorization_id": "profile-choice",
                    "allowed_source_scope": ["official_docs", "source_repository"],
                    "max_cost": "low",
                },
            },
        )
        incompatible = self.investigation_evidence(
            running,
            "wrong-kind-evidence",
            "official_docs",
            kind="build",
        )

        with self.assertRaisesRegex(ValidationFailure, "incompatible kind"):
            self.investigation_store.finish(
                "run-investigation",
                "wrong-evidence-kind",
                outcome="completed",
                evidence_refs=[incompatible.id],
            )

    def test_investigation_finish_validates_only_submitted_evidence(self) -> None:
        running = self.investigation_store.propose(
            replace(self.request(), id="bounded-evidence-read", mode="auto_readonly"),
            investigation_policy={
                "default_mode": "auto_readonly",
                "auto_readonly": {
                    "enabled": True,
                    "authorization_id": "profile-choice",
                    "allowed_source_scope": ["official_docs", "source_repository"],
                    "max_cost": "low",
                },
            },
        )
        submitted = self.investigation_evidence(
            running,
            "bounded-evidence",
            "official_docs",
        )

        with mock.patch.object(
            self.evidence_store,
            "ids",
            side_effect=AssertionError("must not scan unrelated evidence"),
        ):
            completed = self.investigation_store.finish(
                "run-investigation",
                "bounded-evidence-read",
                outcome="completed",
                evidence_refs=[submitted.id],
            )

        self.assertEqual("completed", completed.request.status)

    def test_forged_investigation_grant_cannot_approve(self) -> None:
        self.investigation_store.propose(replace(self.request(), id="forged-grant"))
        forged = InvestigationDecisionGrant(
            grant_id="forged",
            broker_id="test-broker",
            audience="engineering-assistant",
            action="investigation.select_mode",
            run_id="run-investigation",
            investigation_id="forged-grant",
            run_revision=0,
            decision="approve",
            selected_mode="suggest_then_run",
            allowed_source_scope=["official_docs", "source_repository"],
            max_cost="low",
            issued_at=self.now,
            expires_at="2099-01-01T00:00:00+00:00",
            actor_ref="model",
            nonce="0123456789abcdef",
            token="forged-token-without-external-root",
        )
        with self.assertRaisesRegex(ValidationFailure, "external broker grant"):
            self.investigation_store.apply_grant(
                forged, verifier=self.verifier, current_run_revision=0
            )

    def test_declined_investigation_does_not_require_or_consume_scope_and_cost(self) -> None:
        self.investigation_store.propose(
            replace(self.request(), id="declined-grant", estimated_cost="high")
        )
        declined = self.investigation_store.apply_grant(
            InvestigationDecisionGrant(
                grant_id="decline-without-allowance",
                broker_id="test-broker",
                audience="engineering-assistant",
                action="investigation.select_mode",
                run_id="run-investigation",
                investigation_id="declined-grant",
                run_revision=0,
                decision="decline",
                selected_mode="disabled",
                allowed_source_scope=[],
                max_cost="low",
                issued_at=self.now,
                expires_at="2099-01-01T00:00:00+00:00",
                actor_ref="opaque-human",
                nonce="0123456789abcdef",
                token="test-grant:decline-without-allowance",
            ),
            verifier=self.verifier,
            current_run_revision=0,
        )

        self.assertEqual("declined", declined.request.status)
        self.assertEqual("disabled", declined.request.mode)
        self.assertEqual([], declined.current_source_scope)
        self.assertEqual(
            ["official_docs", "source_repository"],
            declined.remaining_source_scope,
        )

    def test_investigation_modes_follow_profile_authorization(self) -> None:
        disabled = self.investigation_store.propose(
            replace(self.request(), id="disabled"),
            investigation_policy={"default_mode": "disabled"},
        )
        self.assertEqual("declined", disabled.request.status)

        automatic = self.investigation_store.propose(
            replace(self.request(), id="automatic"),
            investigation_policy={
                "default_mode": "auto_readonly",
                "auto_readonly": {
                    "enabled": True,
                    "authorization_id": "profile-choice",
                    "allowed_source_scope": ["official_docs", "source_repository"],
                    "max_cost": "low",
                },
            },
        )
        self.assertEqual("running", automatic.request.status)

        bounded = self.investigation_store.propose(
            replace(self.request(), id="bounded", estimated_cost="high"),
            investigation_policy={
                "default_mode": "auto_readonly",
                "auto_readonly": {
                    "enabled": True,
                    "authorization_id": "profile-choice",
                    "allowed_source_scope": ["official_docs", "source_repository"],
                    "max_cost": "low",
                },
            },
        )
        self.assertEqual("proposed", bounded.request.status)
        self.assertEqual("suggest_then_run", bounded.request.mode)

    def test_concurrent_investigation_decisions_allow_only_one_transition(self) -> None:
        self.investigation_store.propose(replace(self.request(), id="concurrent"))

        def grant(grant_id: str, decision: str) -> InvestigationDecisionGrant:
            return InvestigationDecisionGrant(
                    grant_id=grant_id,
                    broker_id="test-broker",
                    audience="engineering-assistant",
                    action="investigation.select_mode",
                    run_id="run-investigation",
                    investigation_id="concurrent",
                    run_revision=0,
                    decision=decision,
                    selected_mode="suggest_then_run",
                    allowed_source_scope=["official_docs", "source_repository"],
                    max_cost="low",
                    issued_at=self.now,
                    expires_at="2099-01-01T00:00:00+00:00",
                    actor_ref="opaque-human",
                    nonce=grant_id + "-nonce-value",
                    token=f"test-grant:{grant_id}",
                )

        def apply(item: tuple[str, str]) -> str:
            try:
                self.investigation_store.apply_grant(
                    grant(*item), verifier=self.verifier, current_run_revision=0
                )
                return "saved"
            except ValidationFailure:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(apply, (("approve-grant", "approve"), ("decline-grant", "decline"))))
        self.assertEqual(["conflict", "saved"], sorted(outcomes))

    def test_free_text_investigation_decide_cli_is_removed(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["investigation-decide"])

    def test_artifact_validator_has_a_stable_discoverable_cli(self) -> None:
        args = build_parser().parse_args(
            ["artifact-validate", "--kind", "step-result", "--input", "result.json"]
        )
        self.assertEqual("artifact-validate", args.command)

        summary = build_parser().parse_args(
            ["feedback-summary", "--project-root", "/tmp/product"]
        )
        self.assertEqual("feedback-summary", summary.command)
        self.assertEqual("/tmp/product", summary.project_root)
        evolution = build_parser().parse_args(
            [
                "feedback-evolution-export",
                "--project-root",
                "/tmp/product",
                "--limit",
                "25",
            ]
        )
        self.assertEqual("feedback-evolution-export", evolution.command)
        self.assertEqual(25, evolution.limit)
        self.assertEqual("step-result", args.kind)

    def test_model_facing_tools_cannot_approve_investigations(self) -> None:
        definitions = RuntimeTools(ROOT).definitions()
        names = [item["name"] for item in definitions]
        self.assertIn("engineering_assistant_investigation_propose", names)
        self.assertIn("engineering_assistant_investigation_list", names)
        self.assertIn("engineering_assistant_investigation_start", names)
        self.assertIn("engineering_assistant_investigation_finish", names)
        self.assertNotIn("engineering_assistant_investigation_approve", names)
        self.assertNotIn("engineering_assistant_investigation_decide", names)
        listing = next(
            item
            for item in definitions
            if item["name"] == "engineering_assistant_investigation_list"
        )
        properties = listing["inputSchema"]["properties"]
        self.assertEqual(100, properties["limit"]["maximum"])
        self.assertIn("after_id", properties)


if __name__ == "__main__":
    unittest.main()
