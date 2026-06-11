#!/usr/bin/env python3
"""Regression checks for generic eval/reference assets backported from teamwork."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GenericReferenceAssetTests(unittest.TestCase):
    def test_high_level_design_generic_evals_exist(self) -> None:
        eval_dir = ROOT / "skills" / "high-level-design" / "evals"
        event_eval = json.loads((eval_dir / "event-driven-sequence-not-too-simple.yaml").read_text(encoding="utf-8"))
        participant_eval = json.loads((eval_dir / "no-invented-participant-for-data-scope.yaml").read_text(encoding="utf-8"))

        self.assertEqual("event-driven-sequence-not-too-simple", event_eval["case_type"])
        self.assertIn("内部关键阶段", event_eval["scenario"]["material"])
        self.assertIn("preflight_input_state", "\n".join(event_eval["pass_criteria"]))

        self.assertEqual("no-invented-participant-for-data-scope", participant_eval["case_type"])
        self.assertIn("participant-evidence-map.json", "\n".join(participant_eval["pass_criteria"]))
        self.assertIn("不生成外部权限服务 participant", participant_eval["scenario"]["material"])

    def test_generic_reference_docs_exist(self) -> None:
        hld_ref = (ROOT / "skills" / "high-level-design" / "references" / "participant-evidence-map.md").read_text(encoding="utf-8")
        ddd_ref = (ROOT / "skills" / "high-level-design" / "references" / "ddd-architecture-inspection-blueprint.md").read_text(encoding="utf-8")
        repo_ref = (ROOT / "skills" / "repo-context-miner" / "references" / "codegraph-project-inspection.md").read_text(encoding="utf-8")
        workflow_ref = (ROOT / "skills" / "workflow-orchestrator" / "references" / "design-governance-loop.md").read_text(encoding="utf-8")
        code_ref = (ROOT / "skills" / "code-development" / "references" / "plugin-feedback-to-generic-rules.md").read_text(encoding="utf-8")
        mq_ref = (ROOT / "skills" / "mq-design" / "references" / "mq-xlsx-template-xml-write.md").read_text(encoding="utf-8")

        self.assertIn("participant-evidence-map.json", hld_ref)
        self.assertIn("validator 会拒绝以下状态", hld_ref)
        self.assertIn("DDD-first architecture inspection blueprint", ddd_ref)
        self.assertIn("Convert implementation evidence into candidate business domains", ddd_ref)
        self.assertIn("Feign 调用矩阵", repo_ref)
        self.assertIn("Do not generate formal design documents until `preflight_input_state == ready`", workflow_ref)
        self.assertIn("Generic team-engineering rules", code_ref)
        self.assertIn("Do not hard-code a single requirement", code_ref)
        self.assertIn("styles.xml", mq_ref)
        self.assertIn("死信", mq_ref)

    def test_generic_design_templates_and_evals_exist(self) -> None:
        dd_eval = json.loads((ROOT / "skills" / "detailed-design" / "evals" / "detailed-design-db-redis-mq-flow-required.yaml").read_text(encoding="utf-8"))
        db_eval = json.loads((ROOT / "skills" / "database-design" / "evals" / "database-design-template-not-truncated.yaml").read_text(encoding="utf-8"))
        redis_eval = json.loads((ROOT / "skills" / "redis-design" / "evals" / "redis-term-must-be-explicit.yaml").read_text(encoding="utf-8"))

        self.assertIn("事务、回滚、重试、死信和人工处理", dd_eval["scenario"]["material"])
        self.assertEqual("database-design-template-not-truncated", db_eval["case_type"])
        self.assertEqual("waiting_for_input", db_eval["expected_status"])
        self.assertIn("Redis 不作为事实源", redis_eval["scenario"]["material"])
        self.assertIn("状态处理记录", redis_eval["scenario"]["material"])

        detailed_template = (ROOT / "skills" / "detailed-design" / "assets" / "detailed-design-template.md").read_text(encoding="utf-8")
        high_level_template = (ROOT / "skills" / "high-level-design" / "assets" / "high-level-design-template.md").read_text(encoding="utf-8")
        oltp_template = (ROOT / "skills" / "database-design" / "assets" / "database-oltp-template.md").read_text(encoding="utf-8")
        olap_template = (ROOT / "skills" / "database-design" / "assets" / "database-olap-template.md").read_text(encoding="utf-8")
        redis_template = (ROOT / "skills" / "redis-design" / "assets" / "redis-design-template.md").read_text(encoding="utf-8")
        mq_template = (ROOT / "skills" / "mq-design" / "assets" / "mq-design-template.xlsx").read_bytes()

        self.assertIn("原始需求与原型引用矩阵", detailed_template)
        self.assertIn("原始需求与原型追溯", high_level_template)
        self.assertIn("跨服务服务间时序图", high_level_template)
        self.assertIn("禁止操作", oltp_template)
        self.assertIn("ORDER BY", olap_template)
        self.assertIn("ttl", redis_template)
        self.assertTrue(mq_template.startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
