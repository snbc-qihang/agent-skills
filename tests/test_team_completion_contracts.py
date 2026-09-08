from __future__ import annotations

import tempfile
from dataclasses import replace
import unittest
from pathlib import Path

from engineering_assistant.catalog import load_catalog
from engineering_assistant.engine import RuntimeEngine, criterion_ids
from engineering_assistant.evidence import EvidenceStore
from engineering_assistant.model import CriterionResult, RouteIntent, StepResult
from engineering_assistant.state_store import StateStore

ROOT = Path(__file__).resolve().parents[1]


class TeamCompletionContractsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.catalog = load_catalog(ROOT)
        self.engine = RuntimeEngine(self.catalog)
        self.store = StateStore(self.project, ROOT / "schemas")
        self.evidence = EvidenceStore(self.store)

    def fixture(self, node_id, kinds, task_kind="implement", rules=True):
        intent = RouteIntent(task_kind, "完成授权阶段", [], [], [], ["release-execution"] if task_kind == "release" else [], .99, ["用户指令"])
        state = self.engine.start("task", intent, profile_id="rrq-yq-team", run_id="fixture-" + node_id)
        flow = self.catalog.flows[state.flow_id]
        index = next(i for i, node in enumerate(flow.nodes) if node.id == node_id)
        node = flow.nodes[index]
        # Isolate the active node; preceding work is not claimed as real execution.
        state.completed_nodes = [n.id for n in flow.nodes[:index]]
        state.current_node = node_id
        state.status = "running"
        refs = [f"rule:{r.id}" for r in self.catalog.rule_catalogs["rrq-yq-team-rules"].rules.values()
                if node.capability in r.capability_refs] if rules else []
        for kind in kinds:
            (self.project / f"{kind}.txt").write_text("Synthetic completion contract fixture.")
            self.evidence.register(state.run_id, evidence_id=kind, kind=kind,
                                   uri=f"{kind}.txt", producer="test", scope="node",
                                   scope_tags=node.evidence_scope_tags, contract_refs=refs)
        result = StepResult(state.run_id, node_id, "completed",
                            [CriterionResult(cid, True, kinds, "fixture") for cid in criterion_ids(node)],
                            ["fixture"], [], [], "continue")
        return state, node, result

    def test_quality_node_requires_persisted_snapshot(self):
        state, _, result = self.fixture("quality-gate", ["test", "build", "ci", "review"])
        gate = self.engine.complete_step(state, result, evidence_store=self.evidence)
        self.assertEqual("retry", gate.decision)
        self.assertNotIn("quality-gate", state.completed_nodes)

    def test_release_requires_both_ci_and_external_state(self):
        state, _, result = self.fixture("release-verification", ["ci"])
        gate = self.engine.complete_step(state, result, evidence_store=self.evidence)
        self.assertEqual("retry", gate.decision)
        self.assertNotIn("release-verification", state.completed_nodes)

    def test_release_can_complete_with_all_required_evidence(self):
        state, _, result = self.fixture("release-verification", ["ci", "external_state"])
        self.engine.complete_step(state, result, evidence_store=self.evidence)
        self.assertIn("release-verification", state.completed_nodes)

    def test_applicable_rules_need_contract_references(self):
        state, _, result = self.fixture("requirements-facts", ["source"], rules=False)
        gate = self.engine.complete_step(state, result, evidence_store=self.evidence)
        self.assertEqual("retry", gate.decision)
        self.assertNotIn("requirements-facts", state.completed_nodes)

    def test_applicable_rule_references_allow_completion(self):
        state, _, result = self.fixture("requirements-facts", ["source"])
        self.engine.complete_step(state, result, evidence_store=self.evidence)
        self.assertIn("requirements-facts", state.completed_nodes)

    def test_stage_scope_survives_state_reload(self):
        for kind, end in [("shape", "requirements-contract"), ("design", "design-approval"),
                          ("implement", "code-confirmation"), ("release", "release-verification")]:
            with self.subTest(kind=kind):
                state, _, _ = self.fixture(end, [], task_kind=kind, rules=False)
                state.completed_nodes.append(end)
                state.current_node = None
                self.store.create(state)
                restored = self.store.load(state.run_id)
                gate = self.engine.next(restored)
                self.assertEqual("complete", gate.decision)
                self.assertEqual("completed", restored.status)

    def test_manual_approval_is_still_required(self):
        state, _, result = self.fixture("design-approval", ["review"], task_kind="design", rules=False)
        gate = self.engine.complete_step(state, result, evidence_store=self.evidence)
        self.assertEqual("pause_for_approval", gate.decision)
        self.assertNotIn("design-approval", state.completed_nodes)

    def test_route_and_guidance_expose_only_matching_rules(self):
        from engineering_assistant.mcp_server import RuntimeTools
        tools = RuntimeTools(ROOT)
        intent = RouteIntent("context", "梳理模块", [], [], [], [], .99, ["用户指令"])
        response = tools.call("engineering_assistant_route", {"intent": intent.to_dict()})
        self.assertEqual("inline", response["execution"]["recommended_execution"])
        self.assertIn("QIN1", {r["id"] for r in response["team_context"]["rules"]})
        state, _, _ = self.fixture("requirements-facts", ["source"])
        guidance = tools._guidance(state, self.engine.node_payload(state), {})
        self.assertEqual(response["team_context"]["rules"], guidance["team_context"]["rules"])

    def quality_fixture(self):
        import hashlib
        from datetime import datetime, timezone
        from engineering_assistant.governance import QualityStore
        from engineering_assistant.model import QualitySnapshot, QualityDimension
        state, node, result = self.fixture('quality-gate', [])
        source = self.project / 'candidate.py'
        source.write_text('behavior = 1\n')
        digest = 'sha256:' + hashlib.sha256(source.read_bytes()).hexdigest()
        ids = ['test', 'build', 'ci', 'review']
        rules = [f'rule:{rule.id}' for rule in self.catalog.rules_for_capability(state.profile_id,node.capability)]
        self.evidence.register(state.run_id, evidence_id='candidate',kind='source',uri=source.name,
                               producer='test',scope='candidate',subject_digest=digest)
        for kind in ids:
            path=self.project / (kind+'.txt');path.write_text('Synthetic '+kind+' result for candidate.')
            self.evidence.register(state.run_id,evidence_id=kind,kind=kind,uri=path.name,
                                   producer='test',scope='quality',subject_digest=digest,
                                   contract_refs=rules,scope_tags=node.evidence_scope_tags+[
                                       'quality-dimension:performance','quality-measurement:benchmark'])
        dimensions=[QualityDimension(id=d,status='pass',delta=0,summary='synthetic fixture',
                                      evidence_ids=['test' if d in {'correctness','performance','test_quality'} else 'review'])
                    for d in ['correctness','complexity','redundancy','performance','architecture','test_quality']]
        snapshot=QualitySnapshot('q-1',state.run_id,node.id,state.revision,'base',digest,'candidate',
                                 dimensions,[],[],['candidate']+ids,datetime.now(timezone.utc).isoformat())
        QualityStore(self.store,self.evidence).save(snapshot,current_state_revision=state.revision)
        result=replace(result,criteria_results=[CriterionResult(cid,True,ids,'fixture') for cid in criterion_ids(node)])
        return state,result,source

    def test_valid_quality_snapshot_can_complete_node(self):
        state,result,_=self.quality_fixture()
        self.engine.complete_step(state,result,evidence_store=self.evidence)
        self.assertIn('quality-gate',state.completed_nodes)

    def test_stale_revision_quality_snapshot_rejected(self):
        state,result,_=self.quality_fixture();state.revision+=1
        gate=self.engine.complete_step(state,result,evidence_store=self.evidence)
        self.assertEqual('retry',gate.decision)
        self.assertNotIn('quality-gate',state.completed_nodes)

    def test_changed_candidate_quality_snapshot_rejected(self):
        state,result,source=self.quality_fixture();source.write_text('behavior = 2\n')
        gate=self.engine.complete_step(state,result,evidence_store=self.evidence)
        self.assertEqual('retry',gate.decision)
        self.assertNotIn('quality-gate',state.completed_nodes)

    def test_expired_quality_snapshot_rejected(self):
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch
        state,result,_=self.quality_fixture()
        class Later(datetime):
            @classmethod
            def now(cls,tz=None):
                return datetime.now(tz)+timedelta(hours=2)
        with patch('engineering_assistant.governance.datetime',Later):
            gate=self.engine.complete_step(state,result,evidence_store=self.evidence)
        self.assertEqual('retry',gate.decision)
        self.assertNotIn('quality-gate',state.completed_nodes)

    def test_readonly_review_gate_does_not_require_implementation_snapshot(self):
        state, _, result = self.fixture("gate", ["review"], task_kind="review")
        gate = self.engine.complete_step(state, result, evidence_store=self.evidence)
        self.assertIn("gate", state.completed_nodes)
        self.assertNotEqual("retry", gate.decision)

    def test_database_node_rejects_plain_report_without_validated_payload(self):
        state, _, result = self.fixture("database-design", ["review"], task_kind="design")
        gate = self.engine.complete_step(state, result, evidence_store=self.evidence)
        self.assertEqual("retry", gate.decision)
        self.assertNotIn("database-design", state.completed_nodes)
