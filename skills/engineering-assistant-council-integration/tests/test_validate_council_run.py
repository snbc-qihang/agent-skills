#!/usr/bin/env python3
"""Bounded regression cases for the proposal-audit Council contract."""

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_council_run.py"
ANONYMIZER = ROOT / "scripts" / "project_anonymous_review.py"


def proposal_content(label):
    return {
        "title": f"{label} transaction-boundary plan",
        "goal": "Repair the failure without changing the accepted transaction owner.",
        "constraints": ["Preserve accepted behavior", "Do not write business code during review"],
        "assumptions": ["Current source and tests are authoritative"],
        "approach_steps": ["Confirm owner", "Apply bounded change", "Run preservation checks"],
        "impacted_components": ["order-service", "payment-adapter"],
        "tradeoffs": ["One extra transaction boundary for deterministic recovery"],
        "risk_controls": ["Protect the prior fix set", "Stop on ambiguous product behavior"],
        "verification_plan": ["Run target test", "Run protected behavior test"],
        "rollback_plan": ["Revert the bounded implementation commit"],
        "open_questions": [],
        "evidence_refs": ["source:owner", "test:protected-behavior"],
    }


def anonymous_projection(outputs):
    baseline = outputs["baseline_proposal"]
    final = outputs["final_proposal"]
    audits = []
    for audit in outputs["audits"]:
        audits.append(
            {
                "audit_id": audit["audit_id"],
                "audited_proposal_id": audit["audited_proposal_id"],
                "findings": audit["findings"],
                "no_blocker_rationale": audit["no_blocker_rationale"],
                "missing_facts": audit["missing_facts"],
            }
        )
    rounds = []
    for round_data in outputs["deliberation"]["rounds"]:
        rounds.append(
            {
                "round": round_data["round"],
                "cross_reviews": round_data["cross_reviews"],
                "reviewer_responses": round_data["reviewer_responses"],
                "author_responses": [
                    {key: value for key, value in response.items() if key != "author_id"}
                    for response in round_data["author_responses"]
                ],
            }
        )
    return {
        "schema_version": "2.0",
        "run_id": outputs["run_id"],
        "baseline_proposal": {
            key: value for key, value in baseline.items() if key != "author_id"
        },
        "audits": sorted(audits, key=lambda item: item["audit_id"]),
        "deliberation": {
            "mode": outputs["deliberation"]["mode"],
            "rounds": rounds,
        },
        "final_proposal": {
            key: value for key, value in final.items() if key != "author_id"
        },
        "final_reviews": outputs["final_reviews"],
    }


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def refresh_digests(outputs, decision):
    projection = anonymous_projection(outputs)
    decision["synthesis_input_sha256"] = hashlib.sha256(
        canonical_json(projection).encode("utf-8")
    ).hexdigest()
    final_projection = {
        key: value
        for key, value in outputs["final_proposal"].items()
        if key != "author_id"
    }
    decision["final_proposal_sha256"] = hashlib.sha256(
        canonical_json(final_projection).encode("utf-8")
    ).hexdigest()


def base_run(trigger_type="complex_task", user_approved=False):
    trigger_evidence = ["approved_scope", "source_fact_packet"]
    trigger_signals = ["cross_module", "material_design_risk"]
    attempt_count = 0
    if trigger_type in {"repeated_bug", "fix_a_break_b"}:
        trigger_signals = ["prior_fix_failed", "root_cause_uncertain"]
        attempt_count = 2
        trigger_evidence = [
            "symptom_history",
            "prior_fix_diffs",
            "failure_logs_or_reproduction",
            "protected_fix_set",
        ]

    member_specs = [
        ("member-1", "architecture_auditor", "Audit ownership and boundaries.", "source_paths"),
        ("member-2", "failure_auditor", "Audit causal completeness.", "failure_logs"),
        ("member-3", "regression_auditor", "Audit protected behavior.", "tests_and_diffs"),
    ]
    plan = {
        "schema_version": "2.0",
        "run_id": "council-test-run",
        "capability_id": "engineering_assistant_council",
        "mode": "diagnosis" if trigger_type != "complex_task" else "planning",
        "task_summary": "Audit one complete proposal before user review.",
        "trigger": {
            "type": trigger_type,
            "signals": trigger_signals,
            "attempt_count": attempt_count,
            "evidence": trigger_evidence,
        },
        "frozen_context": {
            "artifact_paths": ["artifacts/scoped-fact-packet.json"],
            "checksum": hashlib.sha256(b"frozen-context").hexdigest(),
            "old_context_policy": "historical_only",
        },
        "proposal_owner": {
            "owner_id": "main-agent",
            "responsibility": "Author one complete baseline, answer findings, and revise it.",
            "proposal_policy": "single_baseline_then_revision",
            "business_code_write_policy": "none",
        },
        "members": [
            {
                "member_id": member_id,
                "role": role,
                "responsibility": responsibility,
                "required_evidence": [evidence],
                "write_policy": "read_only",
                "proposal_policy": "audit_only_no_competing_proposal",
            }
            for member_id, role, responsibility, evidence in member_specs
        ],
        "dispatch": {
            "backend": "subagents",
            "mode": "parallel_ready_set",
            "all_spawned_before_wait": True,
            "explicit_user_authorization": False,
        },
        "synthesis": {
            "method": "anonymous_proposal_audit_synthesis",
            "chair_is_not_member": True,
        },
        "deliberation": {
            "required": True,
            "mode": "controller_relayed_proposal_audit",
            "review_object": "single_baseline_proposal",
            "competing_proposals_allowed": False,
            "all_members_must_audit_baseline": True,
            "all_members_must_cross_review": True,
            "minimum_cross_reviews_per_member": 1,
            "author_must_respond_to_every_finding": True,
            "final_proposal_must_be_reviewed_by_all": True,
            "zero_unresolved_blocking_findings_before_user_review": True,
            "user_review_required_before_development": True,
            "unanimity_required": False,
        },
        "budgets": {"max_members": 3, "max_rounds": 2},
        "privacy": {"external_model_api_enabled": False},
        "deterministic_gates": ["target_test", "protected_behavior_test"],
        "artifacts": ["council-plan.json", "council-member-outputs.json", "council-decision.json"],
        "status": "planned",
    }

    baseline = {
        "proposal_id": "proposal-v1",
        "revision": 1,
        "author_id": "main-agent",
        "status": "complete",
        "content": proposal_content("Baseline"),
    }
    audits = []
    for index, (member_id, role, _, _) in enumerate(member_specs, start=1):
        audits.append(
            {
                "audit_id": f"audit-{index}",
                "member_id": member_id,
                "role": role,
                "status": "complete",
                "audited_proposal_id": baseline["proposal_id"],
                "findings": [],
                "no_blocker_rationale": "No blocker found in the assigned evidence boundary.",
                "missing_facts": [],
            }
        )
    cross_reviews = []
    for index, audit in enumerate(audits):
        target = audits[(index + 1) % len(audits)]
        cross_reviews.append(
            {
                "cross_review_id": f"cross-review-{index + 1}",
                "reviewer_audit_id": audit["audit_id"],
                "target_audit_id": target["audit_id"],
                "reviewed_finding_ids": [],
                "verdict": "no_issue",
                "severity": "none",
                "objection": "",
                "evidence_refs": [f"cross-check:{index + 1}"],
                "falsification_test": "Repeat this audit if the proposal or target audit changes.",
            }
        )
    final = {
        "proposal_id": "proposal-v2",
        "revision": 2,
        "author_id": "main-agent",
        "status": "complete",
        "based_on_proposal_id": baseline["proposal_id"],
        "content": proposal_content("Final"),
        "change_summary": "No blocking changes were required; evidence wording was tightened.",
        "change_log": [],
    }
    outputs = {
        "schema_version": "2.0",
        "run_id": plan["run_id"],
        "dispatch": {
            "all_started_before_first_wait": True,
            "started_member_ids": [item[0] for item in member_specs],
            "recorded_by": "controller",
            "evidence_source": "controller_tool_results",
            "council_target_repo_edits": [],
            "external_model_api_calls": 0,
        },
        "identity_tokens": [
            "member-1",
            "member-2",
            "member-3",
            "architecture_auditor",
            "failure_auditor",
            "regression_auditor",
        ],
        "baseline_proposal": baseline,
        "audits": audits,
        "deliberation": {
            "mode": "controller_relayed_proposal_audit",
            "all_members_participated": True,
            "rounds": [
                {
                    "round": 1,
                    "cross_reviews": cross_reviews,
                    "reviewer_responses": [],
                    "author_responses": [],
                }
            ],
        },
        "final_proposal": final,
        "final_reviews": [
            {
                "final_review_id": f"final-review-{index + 1}",
                "reviewer_audit_id": audit["audit_id"],
                "audited_proposal_id": final["proposal_id"],
                "verdict": "pass",
                "unresolved_finding_ids": [],
                "evidence_refs": [f"final-check:{index + 1}"],
            }
            for index, audit in enumerate(audits)
        ],
    }

    user_status = "approved" if user_approved else "pending"
    decision = {
        "schema_version": "2.0",
        "run_id": plan["run_id"],
        "status": "recommend" if user_approved else "ready_for_user_review",
        "synthesis_method": "anonymous_proposal_audit_synthesis",
        "final_proposal_id": final["proposal_id"],
        "evaluated_audit_ids": [audit["audit_id"] for audit in audits],
        "accepted_finding_ids": [],
        "rejected_findings": [],
        "disagreements": [],
        "evidence_consumed": ["source:owner", "test:protected-behavior"],
        "deterministic_gate_results": [
            {"gate_id": "target_test", "status": "pass", "evidence_ref": "test-report:target"},
            {
                "gate_id": "protected_behavior_test",
                "status": "pass",
                "evidence_ref": "test-report:protected",
            },
        ],
        "deterministic_gate_status": "pass",
        "deterministic_gate_override": False,
        "deliberation_rounds": 1,
        "unresolved_cross_review_ids": [],
        "unresolved_blocking_finding_ids": [],
        "internal_audit_status": "pass",
        "user_review": {
            "status": user_status,
            "reviewed_proposal_id": final["proposal_id"],
            "evidence_ref": "user-approval:conversation" if user_approved else "",
        },
        "development_gate_status": "pass" if user_approved else "awaiting_user_review",
        "rounds_used": 1,
        "human_review_required": False,
        "scope_guard": {"goal_preserved": True, "new_scope": []},
        "next_action": (
            "Route the user-approved proposal to one implementation owner."
            if user_approved
            else "Present the complete final proposal to the user for audit."
        ),
    }
    refresh_digests(outputs, decision)
    return plan, outputs, decision


def validate(plan, outputs, decision, tamper_context_checksum=False):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plan = copy.deepcopy(plan)
        outputs = copy.deepcopy(outputs)
        decision = copy.deepcopy(decision)
        fact = root / "scoped-fact-packet.json"
        fact.write_text('{"fact":"current-source"}', encoding="utf-8")
        plan["frozen_context"]["artifact_paths"] = [str(fact)]
        checksum = subprocess.run(
            ["python3", str(VALIDATOR), "--hash-context", str(fact)],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        plan["frozen_context"]["checksum"] = "0" * 64 if tamper_context_checksum else checksum
        paths = []
        for name, value in [("plan.json", plan), ("outputs.json", outputs), ("decision.json", decision)]:
            path = root / name
            path.write_text(json.dumps(value), encoding="utf-8")
            paths.append(path)
        return subprocess.run(
            ["python3", str(VALIDATOR), *(str(path) for path in paths)],
            text=True,
            capture_output=True,
            check=False,
        )


def add_blocking_finding(outputs, disposition="experiment_required"):
    finding = {
        "finding_id": "finding-1",
        "severity": "blocker",
        "statement": "The baseline does not prove the transaction owner is preserved.",
        "proposal_section": "risk_controls",
        "evidence_refs": ["source:transaction-owner"],
        "falsification_test": "Run the transaction owner integration test.",
        "suggested_correction": "Add explicit owner preservation evidence.",
    }
    outputs["audits"][0]["findings"] = [finding]
    outputs["audits"][0]["no_blocker_rationale"] = ""
    outputs["deliberation"]["rounds"][0]["author_responses"] = [
        {
            "finding_id": finding["finding_id"],
            "author_id": "main-agent",
            "disposition": disposition,
            "response": "The final plan now records the owner evidence." if disposition == "resolved" else "Run the experiment first.",
            "evidence_refs": ["test:transaction-owner"],
            "proposal_change_refs": ["final_proposal.content.risk_controls"] if disposition == "resolved" else [],
        }
    ]
    outputs["final_proposal"]["change_log"] = [
        {
            "finding_id": finding["finding_id"],
            "action": "revised" if disposition == "resolved" else "deferred",
            "proposal_section": "risk_controls",
        }
    ]
    return finding


class CouncilValidationTests(unittest.TestCase):
    def test_01_accepts_one_proposal_ready_for_user_review(self):
        plan, outputs, decision = base_run()
        outputs["audits"][0]["provider"] = "secret-model-identity"
        self.assertEqual(validate(plan, outputs, decision).returncode, 0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outputs.json"
            path.write_text(json.dumps(outputs), encoding="utf-8")
            projected = subprocess.run(
                ["python3", str(ANONYMIZER), str(path)], text=True, capture_output=True, check=True
            ).stdout
            self.assertNotIn("member_id", projected)
            self.assertNotIn("architecture_auditor", projected)
            self.assertNotIn("secret-model-identity", projected)

    def test_02_accepts_user_approved_proposal_for_development(self):
        plan, outputs, decision = base_run(user_approved=True)
        self.assertEqual(validate(plan, outputs, decision).returncode, 0)

    def test_03_rejects_serial_dispatch(self):
        plan, outputs, decision = base_run()
        plan["dispatch"]["all_spawned_before_wait"] = False
        result = validate(plan, outputs, decision)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("spawn all ready members", result.stderr)

    def test_04_rejects_unbound_evidence_and_identity_leak(self):
        plan, outputs, decision = base_run()
        outputs["baseline_proposal"]["content"]["evidence_refs"] = []
        result = validate(plan, outputs, decision)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("evidence_refs", result.stderr)
        plan, outputs, decision = base_run()
        result = validate(plan, outputs, decision, tamper_context_checksum=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum does not match", result.stderr)
        plan, outputs, decision = base_run()
        outputs["baseline_proposal"]["content"]["goal"] = "architecture_auditor identity leaked"
        refresh_digests(outputs, decision)
        result = validate(plan, outputs, decision)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity tokens", result.stderr)

    def test_05_rejects_deterministic_gate_override(self):
        plan, outputs, decision = base_run()
        decision["deterministic_gate_results"][0]["status"] = "fail"
        decision["deterministic_gate_status"] = "fail"
        decision["deterministic_gate_override"] = True
        result = validate(plan, outputs, decision)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("override", result.stderr)

    def test_06_rejects_unbounded_rounds(self):
        plan, outputs, decision = base_run()
        plan["budgets"]["max_rounds"] = 3
        result = validate(plan, outputs, decision)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("max_rounds", result.stderr)

    def test_07_rejects_legacy_competing_candidates_without_one_baseline(self):
        plan, outputs, decision = base_run()
        outputs["candidates"] = [
            {"candidate_id": "candidate-A", "complete_plan": proposal_content("A")},
            {"candidate_id": "candidate-B", "complete_plan": proposal_content("B")},
        ]
        del outputs["baseline_proposal"]
        result = validate(plan, outputs, decision)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("one complete baseline proposal", result.stderr)

    def test_08_rejects_missing_cross_review_participation(self):
        plan, outputs, decision = base_run()
        outputs["deliberation"]["rounds"][0]["cross_reviews"].pop()
        refresh_digests(outputs, decision)
        result = validate(plan, outputs, decision)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("every audit member must complete", result.stderr)

    def test_09_rejects_unanswered_reviewer_challenge(self):
        plan, outputs, decision = base_run()
        cross_review = outputs["deliberation"]["rounds"][0]["cross_reviews"][0]
        cross_review.update(
            {
                "verdict": "challenge",
                "severity": "major",
                "objection": "The target audit did not inspect the rollback evidence.",
            }
        )
        refresh_digests(outputs, decision)
        result = validate(plan, outputs, decision)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("every reviewer challenge", result.stderr)

    def test_10_rejects_unresolved_author_blocker(self):
        plan, outputs, decision = base_run()
        finding = add_blocking_finding(outputs)
        decision["unresolved_blocking_finding_ids"] = [finding["finding_id"]]
        decision["internal_audit_status"] = "block"
        decision["status"] = "experiment_required"
        decision["development_gate_status"] = "block"
        refresh_digests(outputs, decision)
        result = validate(plan, outputs, decision)
        self.assertEqual(result.returncode, 0)
        decision["status"] = "ready_for_user_review"
        decision["internal_audit_status"] = "pass"
        decision["unresolved_blocking_finding_ids"] = []
        decision["development_gate_status"] = "awaiting_user_review"
        result = validate(plan, outputs, decision)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unresolved_blocking_finding_ids", result.stderr)

    def test_11_accepts_evidence_resolved_blocker_after_final_review(self):
        plan, outputs, decision = base_run()
        finding = add_blocking_finding(outputs, disposition="resolved")
        decision["accepted_finding_ids"] = [finding["finding_id"]]
        refresh_digests(outputs, decision)
        self.assertEqual(validate(plan, outputs, decision).returncode, 0)

    def test_12_rejects_final_proposal_not_reviewed_by_every_auditor(self):
        plan, outputs, decision = base_run()
        outputs["final_reviews"].pop()
        refresh_digests(outputs, decision)
        result = validate(plan, outputs, decision)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("final proposal must be reviewed by every auditor", result.stderr)

    def test_13_rejects_development_before_user_reviews_final_proposal(self):
        plan, outputs, decision = base_run()
        decision["status"] = "recommend"
        decision["development_gate_status"] = "pass"
        result = validate(plan, outputs, decision)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("user review", result.stderr)


if __name__ == "__main__":
    unittest.main()
