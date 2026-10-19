"""Implementation method selection and one-way Runtime progression."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from engineering_assistant.runtime.mcp_server import RuntimeTools
from engineering_assistant.runtime.engine import RuntimeEngine
from engineering_assistant.runtime.codec import route_intent_from_dict
from engineering_assistant.runtime.validation import ValidationFailure


def intent(**changes):
    value = dict(task_kind="implement", requested_outcome="修正文档中的错别字",
                 scope=["README.md"], risk_signals=[], requested_external_actions=[],
                 confirmed_actions=[], confidence=.99, evidence=["用户明确授权局部修改"],
                 implementation_mode="inline")
    value.update(changes)
    return value


class ImplementationSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tools = RuntimeTools(ROOT)

    def route(self, data, **extra):
        return self.tools.call("engineering_assistant_route", {"intent": data, "profile": "default", **extra})

    def test_bounded_inline_implementation_needs_neither_tdd_nor_run(self):
        result = self.route(intent())
        self.assertEqual("proceed", result["decision"]["decision"])
        self.assertEqual("inline", result["execution"]["recommended_execution"])
        self.assertEqual([], result["decision"]["skill_ids"])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValidationFailure):
                self.tools.call("engineering_assistant_start", dict(
                    intent=intent(), task_id="bounded", project_root=tmp, profile="default"))
            self.assertEqual([], list(Path(tmp).iterdir()))

    def test_legacy_implementation_keeps_flow_without_preselecting_tdd(self):
        data = intent()
        del data["implementation_mode"]
        result = self.route(data)
        self.assertEqual("implement", result["decision"]["flow_id"])
        self.assertNotIn("tdd", result["decision"]["skill_ids"])

    def test_inline_never_removes_risk_external_or_team_gates(self):
        for changes in [dict(risk_signals=["security"]),
                        dict(risk_signals=["production"], confirmed_actions=["production"]),
                        dict(requested_external_actions=["push"]),
                        dict(requested_external_actions=["push"], confirmed_actions=["push"]),
                        dict(risk_signals=["project-manual-gate"])]:
            with self.subTest(changes=changes):
                result = self.route(intent(**changes))
                self.assertEqual("implement", result["decision"]["flow_id"])
        self.assertEqual("confirm", self.route(intent(risk_signals=["security"]))["decision"]["decision"])
        self.assertEqual("block", self.route(intent(risk_signals=["authorization-denied"]))["decision"]["decision"])
        self.assertEqual("block", self.route(intent(read_only=True))["decision"]["decision"])
        if "rrq-yq-team" in self.tools.catalog.profiles:
            result = self.route(intent(), profile="rrq-yq-team")
            self.assertEqual("team-delivery", result["decision"]["flow_id"])

    def test_inline_is_not_a_general_flow_bypass(self):
        for changes in [dict(task_kind="release"), dict(implementation_mode="unknown")]:
            with self.subTest(changes=changes), self.assertRaises(ValidationFailure):
                self.route(intent(**changes))

    def test_internal_nodes_do_not_fallback_to_unrelated_public_skills(self):
        engine = RuntimeEngine(self.tools.catalog)
        state = engine.start("guidance", route_intent_from_dict(intent(implementation_mode="flow")))
        for node in ["select-slice", "implementation", "quality", "red-green"]:
            state.current_node = node
            guidance = self.tools._guidance(state, engine.node_payload(state), {})
            with self.subTest(node=node):
                self.assertEqual("tdd" if node == "red-green" else None, guidance["skill"])
                self.assertTrue(guidance["node_goal"])

    def test_skip_tdd_advances_once_and_resume_does_not_restore_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = dict(project_root=tmp, run_id="method-selection", profile="default")
            self.tools.call("engineering_assistant_start", dict(
                **run, task_id="method-selection", intent=intent(implementation_mode="flow")))
            Path(tmp, "slice.md").write_text("行为保持重构，复用现有回归，不采用 TDD。")
            self.tools.call("engineering_assistant_evidence_register", dict(
                **run, evidence_id="slice", kind="source", uri="slice.md",
                producer="agent", scope="approved-slice", scope_tags=[], contract_refs=[]))
            self.tools.call("engineering_assistant_complete", dict(**run, result=dict(
                run_id=run["run_id"], node_id="select-slice", status="completed",
                criteria_results=[dict(criterion_id="select-slice:1", passed=True,
                    evidence_ids=["slice"], detail="测试方法与范围已明确")],
                outputs=["slice.md"], findings=[], open_questions=[], requested_transition="continue")))
            skipped = dict(run_id=run["run_id"], node_id="red-green", status="skipped",
                criteria_results=[], outputs=["保持行为，已有回归足够；没有明确 TDD 要求"],
                findings=[], open_questions=[], requested_transition="continue")
            result = self.tools.call("engineering_assistant_complete", dict(**run, result=skipped))
            self.assertEqual("implementation", result["node"]["id"])
            self.assertIsNone(result["guidance"]["skill"])
            for _ in range(2):
                resumed = self.tools.call("engineering_assistant_next", run)
                self.assertEqual("implementation", resumed["node"]["id"])
                self.assertEqual(["red-green"], resumed["state"]["skipped_nodes"])
            with self.assertRaises(ValidationFailure):
                self.tools.call("engineering_assistant_complete", dict(**run, result=skipped))
            status = self.tools.call("engineering_assistant_run_status", run)
            self.assertEqual("implementation", status["node"]["id"])
