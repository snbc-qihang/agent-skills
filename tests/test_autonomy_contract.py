# GPT-6 适配变更说明：验证只读路由不产生运行写入，保留真实外部动作的授权边界。
from pathlib import Path
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from engineering_assistant.mcp_server import RuntimeTools
from engineering_assistant.validation import ValidationFailure

class AutonomyContractTests(unittest.TestCase):
    def setUp(self):
        self.tools = RuntimeTools(ROOT)

    def intent(self, kind="review", **changes):
        data = dict(task_kind=kind, requested_outcome="只读检查生产支付代码，保留风险，不执行外部动作",
                    scope=["fixture"], risk_signals=["production", "security"],
                    requested_external_actions=[], confirmed_actions=[], confidence=.99,
                    evidence=["用户明确只读"], read_only=True)
        data.update(changes)
        return data

    def test_readonly_review_and_design_are_inline_without_writes(self):
        for kind in ["review", "design", "domain-design", "context", "research", "wayfind"]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                result = self.tools.call("engineering_assistant_route", {"intent":self.intent(kind)})
                self.assertEqual("proceed",result["decision"]["decision"])
                self.assertIsNone(result["decision"]["flow_id"])
                self.assertEqual("inline",result["decision"]["persistence_mode"])
                self.assertEqual("inline",result["execution"]["recommended_execution"])
                with self.assertRaises(ValidationFailure):
                    self.tools.call("engineering_assistant_start",dict(intent=self.intent(kind),task_id="readonly",project_root=tmp))
                self.assertEqual([], list(Path(tmp).iterdir()))

    def test_readonly_cannot_hide_mutations_or_denial(self):
        for data in [self.intent("implement"), self.intent("release"),
                     self.intent(requested_external_actions=["push"],confirmed_actions=["push"]),
                     self.intent(risk_signals=["authorization-denied"])]:
            result=self.tools.call("engineering_assistant_route",{"intent":data})
            self.assertEqual("block",result["decision"]["decision"])

    def test_existing_authorization_and_missing_authorization_remain_distinct(self):
        data=self.intent("implement",read_only=False,risk_signals=[],requested_external_actions=["commit","push"],confirmed_actions=["commit","push"])
        self.assertEqual("proceed",self.tools.call("engineering_assistant_route",{"intent":data})["decision"]["decision"])
        data["confirmed_actions"]=["commit"]
        result=self.tools.call("engineering_assistant_route",{"intent":data})
        self.assertEqual("confirm",result["decision"]["decision"])
        self.assertEqual(["push"],result["decision"]["approval_required"])

    def test_legacy_intent_without_readonly_keeps_risk_approval(self):
        data=self.intent(); del data["read_only"]
        self.assertEqual("confirm",self.tools.call("engineering_assistant_route",{"intent":data})["decision"]["decision"])

    def test_explicit_readonly_normalization_retains_risk_and_rejects_write_conflicts(self):
        from engineering_assistant.natural_intent import normalize_request
        for text in ["只读评审生产代码", "read-only review production code"]:
            data = normalize_request(text).to_dict()
            self.assertTrue(data["read_only"])
            self.assertIn("production", data["risk_signals"])
            result = self.tools.call("engineering_assistant_route", {"intent": data})
            self.assertEqual("proceed", result["decision"]["decision"])
        for text in ["只读评审代码并推送", "read-only review code and push"]:
            data = normalize_request(text).to_dict()
            self.assertTrue(data["read_only"])
            self.assertEqual("block", self.tools.call("engineering_assistant_route", {"intent":data})["decision"]["decision"])
