from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.design_intake import (  # noqa: E402
    intake_design_sources,
    recheck_design_sources,
)
from engineering_assistant.engine import RuntimeEngine  # noqa: E402
from engineering_assistant.mcp_server import RuntimeTools  # noqa: E402
from engineering_assistant.model import ApprovalRecord, RouteIntent  # noqa: E402
from engineering_assistant.state_store import StateStore  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


def domain_intent() -> RouteIntent:
    return RouteIntent(
        task_kind="domain-design",
        requested_outcome="建立战略和战术领域设计。",
        scope=["repository"],
        risk_signals=[],
        requested_external_actions=[],
        confirmed_actions=[],
        confidence=0.95,
        evidence=["user request"],
    )


def registry() -> dict:
    return {
        "hld": "docs/hld.md",
        "context_index": "docs/contexts.md",
        "capability_design_root": "docs/capabilities",
        "change_root": "docs/changes",
        "deployment_catalog": "docs/deployments.md",
        "owners": {"business": "business-owner", "architecture": "architecture-owner"},
        "sources": [
            {"id": "requirements", "kind": "requirements", "path": "requirements.md", "status": "available", "reason": "需求基线。"},
            {"id": "repository", "kind": "repository", "path": "src", "status": "available", "reason": "源码基线。"},
            {"id": "existing-design", "kind": "existing-design", "path": None, "status": "not_applicable", "reason": "暂无。"},
            {"id": "interfaces", "kind": "interfaces", "path": None, "status": "unknown", "reason": "待确认。"},
            {"id": "data", "kind": "data", "path": None, "status": "unknown", "reason": "待确认。"},
            {"id": "deployment", "kind": "deployment", "path": None, "status": "unknown", "reason": "待确认。"},
        ],
    }


class TeamworkV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog(ROOT, require_sources=True)

    def test_team_identity_and_dual_domain_entry_are_preserved(self) -> None:
        self.assertEqual("teamwork-engineering-assistant", self.catalog.product.id)
        self.assertEqual("rrq-yq-team", self.catalog.default_profile.id)
        self.assertIn("team-delivery", self.catalog.flows)
        self.assertIn("domain-design", self.catalog.flows)
        direct = RuntimeEngine(self.catalog).start(
            "domain", domain_intent(), profile_id="rrq-yq-team", design_source_ref="docs/registry.json"
        )
        self.assertEqual("domain-design", direct.flow_id)
        delegated = next(node for node in self.catalog.flows["team-delivery"].nodes if node.id == "domain-design-delegation")
        self.assertEqual("domain-design-delegation", delegated.capability)

    def test_local_approval_rejects_actor_outside_profile_allowlist(self) -> None:
        engine = RuntimeEngine(self.catalog)
        state = engine.start("domain", domain_intent(), profile_id="rrq-yq-team", design_source_ref="docs/registry.json")
        state.required_approvals = ["domain-business-owner"]
        record = ApprovalRecord(
            record_id="wrong-actor",
            run_id=state.run_id,
            run_revision=state.revision,
            approval_id="domain-business-owner",
            decision="approved",
            scope=["flow:domain-design", "approval:domain-business-owner"],
            actor_ref="not-authorized",
            reason="attempt",
            recorded_at=datetime.now(timezone.utc).isoformat(),
            source="user_confirmation",
        )
        with self.assertRaisesRegex(ValidationFailure, "not authorized"):
            engine.apply_approval_record(state, record, approval_records=[])

    def test_external_input_is_copied_read_only_and_recheck_marks_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            external = Path(temporary) / "external"
            project.mkdir()
            external.mkdir()
            (external / "requirements.md").write_text("需求 v1", encoding="utf-8")
            (external / "src").mkdir()
            (external / "src" / "model.py").write_text("class Model: pass", encoding="utf-8")
            frozen = intake_design_sources(project, external, registry(), schema_root=ROOT / "schemas", intake_id="req-001")
            self.assertEqual("frozen", frozen["status"])
            self.assertTrue((project / frozen["registry"]).is_file())
            self.assertEqual("current", recheck_design_sources(project, frozen["registry"])["status"])
            (external / "requirements.md").write_text("需求 v2", encoding="utf-8")
            self.assertEqual("stale", recheck_design_sources(project, frozen["registry"])["status"])

    def test_team_delivery_delegates_and_recovers_after_domain_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            external = Path(temporary) / "external"
            project.mkdir()
            external.mkdir()
            (external / "requirements.md").write_text("需求", encoding="utf-8")
            (external / "src").mkdir()
            (external / "src" / "model.py").write_text("class Model: pass", encoding="utf-8")
            frozen = intake_design_sources(project, external, registry(), schema_root=ROOT / "schemas", intake_id="req-002")
            tools = RuntimeTools(ROOT)
            parent_intent = domain_intent().to_dict()
            parent_intent["task_kind"] = "implement"
            started = tools.call(
                "engineering_assistant_start",
                {
                    "intent": parent_intent,
                    "task_id": "team-task",
                    "run_id": "team-run",
                    "project_root": str(project),
                    "profile": "rrq-yq-team",
                    "design_source_ref": frozen["registry"],
                },
            )
            store = StateStore(project, ROOT / "schemas")
            parent = store.load(started["state"]["run_id"])
            previous_revision = parent.revision
            parent.current_node = "domain-design-delegation"
            parent.completed_nodes = ["requirements-facts", "design-source-intake", "decision-convergence"]
            parent.revision += 1
            store.save(parent, expected_revision=previous_revision)
            delegated = tools.call(
                "engineering_assistant_domain_design_delegate",
                {
                    "parent_run_id": parent.run_id,
                    "child_run_id": "domain-run",
                    "task_id": "domain-task",
                    "intent": domain_intent().to_dict(),
                    "project_root": str(project),
                    "profile": "rrq-yq-team",
                    "design_source_ref": frozen["registry"],
                },
            )
            self.assertEqual("domain-design", delegated["child"]["state"]["flow_id"])
            child = store.load("domain-run")
            child_revision = child.revision
            child.status = "completed"
            child.current_node = None
            child.revision += 1
            store.save(child, expected_revision=child_revision)
            resumed = tools.call(
                "engineering_assistant_domain_design_delegation_complete",
                {
                    "parent_run_id": "team-run",
                    "child_run_id": "domain-run",
                    "project_root": str(project),
                    "profile": "rrq-yq-team",
                },
            )
            self.assertEqual("requirements-contract", resumed["state"]["current_node"])
            self.assertIn("domain-design-baseline:domain-run", resumed["state"]["context_refs"])


if __name__ == "__main__":
    unittest.main()
