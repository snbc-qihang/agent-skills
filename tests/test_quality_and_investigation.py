from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.cli import build_parser  # noqa: E402
from engineering_assistant.runtime.evidence import EvidenceStore  # noqa: E402
from engineering_assistant.runtime.governance import (  # noqa: E402
    InvestigationStore,
    QualityGate,
)
from engineering_assistant.runtime.model import (  # noqa: E402
    Finding,
    InvestigationDecisionRecord,
    InvestigationRequest,
    QualityDimension,
    QualitySnapshot,
)
from engineering_assistant.runtime.state_store import StateStore  # noqa: E402
from engineering_assistant.runtime.validation import ValidationFailure  # noqa: E402


class QualityAndInvestigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.state_store = StateStore(self.project, ROOT / "schemas")
        self.evidence_store = EvidenceStore(self.state_store)
        self.investigations = InvestigationStore(
            self.state_store, self.evidence_store
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def quality_snapshot(*, status: str = "pass") -> QualitySnapshot:
        dimensions = [
            QualityDimension(
                id=dimension,
                status=status if dimension == "performance" else "pass",
                delta=0,
                summary=f"{dimension} checked",
                evidence_ids=["quality-evidence"],
            )
            for dimension in (
                "correctness",
                "complexity",
                "redundancy",
                "performance",
                "architecture",
                "test_quality",
            )
        ]
        return QualitySnapshot(
            id="quality-1",
            run_id="run-1",
            node_id="quality",
            state_revision=1,
            base_ref="base",
            candidate_ref="candidate",
            candidate_evidence_id="quality-evidence",
            dimensions=dimensions,
            findings=[],
            required_repairs=[],
            evidence_refs=["quality-evidence"],
            observed_at=datetime.now(timezone.utc).isoformat(),
        )

    def test_quality_gate_requires_all_dimensions_to_pass(self) -> None:
        self.assertEqual("pass", QualityGate.evaluate(self.quality_snapshot()).decision)
        assessment = QualityGate.evaluate(self.quality_snapshot(status="warning"))
        self.assertEqual("repair", assessment.decision)
        self.assertIn("performance is warning", assessment.reasons)

    def test_quality_gate_rejects_open_repairs_and_material_findings(self) -> None:
        snapshot = self.quality_snapshot()
        snapshot = replace(
            snapshot,
            findings=[
                Finding(
                    id="architecture-leak",
                    severity="high",
                    summary="Boundary leak remains.",
                    evidence_ids=["quality-evidence"],
                )
            ],
            required_repairs=["close the boundary leak"],
        )

        assessment = QualityGate.evaluate(snapshot)

        self.assertEqual("repair", assessment.decision)
        self.assertIn("finding architecture-leak is high", assessment.reasons)
        self.assertIn("required repairs remain open", assessment.reasons)

    def test_remote_evidence_cannot_be_promoted_by_the_caller(self) -> None:
        evidence = self.evidence_store.register(
            "run-1",
            evidence_id="remote-1",
            kind="external_state",
            uri="https://example.invalid/status",
            producer="agent",
            scope="remote",
        )
        self.assertEqual("agent_reported", evidence.provenance)
        with self.assertRaisesRegex(ValidationFailure, "provenance"):
            self.evidence_store.save(
                "run-1",
                type(evidence)(
                    **{
                        **evidence.to_dict(),
                        "id": "remote-forged",
                        "provenance": "runtime_observed",
                    }
                ),
            )

    def test_investigation_uses_local_user_decision(self) -> None:
        request = InvestigationRequest(
            id="investigation-1",
            run_id="run-1",
            question="Which contract applies?",
            reason="Implementation is blocked by an unknown contract.",
            source_scope=["official_docs"],
            reported_blocking=True,
            mode="suggest_then_run",
            estimated_cost="low",
            stop_conditions=["contract version found"],
            evidence_requirements=["official contract reference"],
            status="proposed",
        )
        proposed = self.investigations.propose(request)
        decision = InvestigationDecisionRecord(
            record_id="decision-1",
            run_id="run-1",
            investigation_id=request.id,
            run_revision=0,
            decision="approve",
            selected_mode="suggest_then_run",
            allowed_source_scope=["official_docs"],
            max_cost="low",
            actor_ref="conversation-user",
            reason="User approved the bounded lookup.",
            recorded_at=datetime.now(timezone.utc).isoformat(),
            source="user_confirmation",
        )

        approved = self.investigations.apply_decision(
            decision, current_run_revision=0
        )
        running = self.investigations.start("run-1", request.id)

        self.assertEqual("proposed", proposed.request.status)
        self.assertEqual("approved", approved.request.status)
        self.assertEqual("running", running.request.status)
        self.assertTrue(
            self.state_store.artifacts.path(
                "run-1", "investigations", "investigation-1.decision-1.decision.json"
            ).is_file()
        )

    def test_cli_surface_has_local_record_commands_only(self) -> None:
        commands = build_parser()._subparsers._group_actions[0].choices
        self.assertIn("evidence-register", commands)
        self.assertIn("approval-record", commands)
        self.assertIn("investigation-decide", commands)
        self.assertIn("runs-list", commands)
        self.assertIn("run-status", commands)
        self.assertNotIn("evidence-import", commands)
        self.assertNotIn("approval-import", commands)
        self.assertNotIn("investigation-approval-import", commands)
        self.assertNotIn("canary-attestation-import", commands)


if __name__ == "__main__":
    unittest.main()
