# Council Artifact Contract

## Purpose

Council is a bounded adversarial audit of one Engineering Assistant proposal. The main Agent owns the proposal; parallel members own independent audit boundaries. Council does not rank competing plans, write business code, replace deterministic checks, or bypass user review.

## `council-plan.json`

Required shape:

```json
{
  "schema_version": "2.0",
  "run_id": "run-id",
  "capability_id": "engineering_assistant_council",
  "mode": "planning|diagnosis|review|release",
  "task_summary": "bounded task",
  "trigger": {
    "type": "complex_task|repeated_bug|fix_a_break_b|uncertain_root_cause|material_disagreement|explicit_user_request",
    "signals": ["cross_module", "material_design_risk"],
    "attempt_count": 0,
    "evidence": ["source-backed trigger evidence"]
  },
  "frozen_context": {
    "artifact_paths": ["path-or-source-reference"],
    "checksum": "checksum from validate_council_run.py --hash-context",
    "old_context_policy": "historical_only"
  },
  "proposal_owner": {
    "owner_id": "main-agent",
    "responsibility": "author baseline, answer findings, revise proposal",
    "proposal_policy": "single_baseline_then_revision",
    "business_code_write_policy": "none"
  },
  "members": [
    {
      "member_id": "member-1",
      "role": "unique audit role",
      "responsibility": "non-overlapping audit boundary",
      "required_evidence": ["evidence type"],
      "write_policy": "read_only",
      "proposal_policy": "audit_only_no_competing_proposal"
    }
  ],
  "dispatch": {
    "backend": "subagents|visible_windows|ateam",
    "mode": "parallel_ready_set",
    "all_spawned_before_wait": true,
    "explicit_user_authorization": false
  },
  "synthesis": {
    "method": "anonymous_proposal_audit_synthesis",
    "chair_is_not_member": true
  },
  "deliberation": {
    "required": true,
    "mode": "controller_relayed_proposal_audit|direct_peer_proposal_audit",
    "review_object": "single_baseline_proposal",
    "competing_proposals_allowed": false,
    "all_members_must_audit_baseline": true,
    "all_members_must_cross_review": true,
    "minimum_cross_reviews_per_member": 1,
    "author_must_respond_to_every_finding": true,
    "final_proposal_must_be_reviewed_by_all": true,
    "zero_unresolved_blocking_findings_before_user_review": true,
    "user_review_required_before_development": true,
    "unanimity_required": false
  },
  "budgets": {"max_members": 3, "max_rounds": 2},
  "privacy": {"external_model_api_enabled": false},
  "deterministic_gates": ["proposal-evidence-gate"],
  "artifacts": ["council-plan.json", "council-member-outputs.json", "council-decision.json"],
  "status": "planned"
}
```

For `repeated_bug` and `fix_a_break_b`, `attempt_count` is at least 2 and trigger evidence contains `symptom_history`, `prior_fix_diffs`, `failure_logs_or_reproduction`, and `protected_fix_set`.

Visible windows require `explicit_user_authorization=true`. Other backends keep it false unless their own policy requires authorization.

## `council-member-outputs.json`

The filename remains stable, but members now produce audits, not candidate plans.

```json
{
  "schema_version": "2.0",
  "run_id": "run-id",
  "dispatch": {
    "all_started_before_first_wait": true,
    "started_member_ids": ["member-1", "member-2"],
    "recorded_by": "controller",
    "evidence_source": "controller_tool_results",
    "council_target_repo_edits": [],
    "external_model_api_calls": 0
  },
  "identity_tokens": ["member ids, roles, agent ids, model/provider names, nicknames"],
  "baseline_proposal": {
    "proposal_id": "proposal-v1",
    "revision": 1,
    "author_id": "main-agent",
    "status": "complete",
    "content": {
      "title": "proposal title",
      "goal": "confirmed goal",
      "constraints": ["constraint"],
      "assumptions": ["assumption"],
      "approach_steps": ["ordered step"],
      "impacted_components": ["component"],
      "tradeoffs": ["tradeoff"],
      "risk_controls": ["control"],
      "verification_plan": ["verification"],
      "rollback_plan": ["rollback"],
      "open_questions": [],
      "evidence_refs": ["source reference"]
    }
  },
  "audits": [
    {
      "audit_id": "audit-1",
      "member_id": "member-1",
      "role": "audit role",
      "status": "complete",
      "audited_proposal_id": "proposal-v1",
      "findings": [
        {
          "finding_id": "finding-1",
          "severity": "blocker|major|minor",
          "statement": "testable proposal defect",
          "proposal_section": "risk_controls",
          "evidence_refs": ["source reference"],
          "falsification_test": "test that can reject the finding",
          "suggested_correction": "bounded correction, not a replacement plan"
        }
      ],
      "no_blocker_rationale": "required when findings is empty",
      "missing_facts": []
    }
  ],
  "deliberation": {
    "mode": "controller_relayed_proposal_audit",
    "all_members_participated": true,
    "rounds": [
      {
        "round": 1,
        "cross_reviews": [
          {
            "cross_review_id": "cross-review-1",
            "reviewer_audit_id": "audit-1",
            "target_audit_id": "audit-2",
            "reviewed_finding_ids": ["finding-2"],
            "verdict": "support|challenge|refine|no_issue",
            "severity": "blocker|major|minor|none",
            "objection": "required for challenge or refine",
            "evidence_refs": ["source reference"],
            "falsification_test": "check that settles the cross-review"
          }
        ],
        "reviewer_responses": [
          {
            "cross_review_id": "cross-review-1",
            "responder_audit_id": "audit-2",
            "disposition": "resolved|rebutted_with_evidence|withdrawn|refine_required",
            "response": "evidence-backed response",
            "evidence_refs": ["source reference"]
          }
        ],
        "author_responses": [
          {
            "finding_id": "finding-2",
            "author_id": "main-agent",
            "disposition": "resolved|rebutted_with_evidence|experiment_required|human_review_required|accepted_tradeoff|withdrawn_after_cross_review",
            "response": "evidence-backed proposal-owner response",
            "evidence_refs": ["source reference"],
            "proposal_change_refs": ["final_proposal.content.risk_controls"]
          }
        ]
      }
    ]
  },
  "final_proposal": {
    "proposal_id": "proposal-v2",
    "revision": 2,
    "author_id": "main-agent",
    "status": "complete",
    "based_on_proposal_id": "proposal-v1",
    "content": {"same_complete_fields_as_baseline": "expanded in actual artifact"},
    "change_summary": "how audit changed or confirmed the proposal",
    "change_log": [
      {"finding_id": "finding-2", "action": "revised", "proposal_section": "risk_controls"}
    ]
  },
  "final_reviews": [
    {
      "final_review_id": "final-review-1",
      "reviewer_audit_id": "audit-1",
      "audited_proposal_id": "proposal-v2",
      "verdict": "pass|block",
      "unresolved_finding_ids": [],
      "evidence_refs": ["final proposal evidence"]
    }
  ]
}
```

Each member produces exactly one audit of `proposal-v1`. A member cannot produce a second complete proposal. `no_blocker_rationale` is required when an audit has no findings.

Cross-review uses audit ids, not member identities. Every auditor reviews another audit and every audit is reviewed. `support` and `no_issue` are valid, use severity `none`, and prevent manufactured objections. Every `challenge` or `refine` receives one target-auditor response.

The proposal owner responds once to every finding. Blocker and major findings close only with `resolved`, `rebutted_with_evidence`, or `withdrawn_after_cross_review`. `accepted_tradeoff` closes only a minor finding. A resolved finding references the changed final proposal section.

Every auditor reviews the same final proposal revision. `pass` has no unresolved finding ids. `block` lists known unresolved finding ids.

Before synthesis, `project_anonymous_review.py` removes `member_id`, role, author identity, model/provider, thread, and session identity. The anonymous projection retains proposal content, audit ids and findings, cross-review, responses, final proposal, and final reviews.

## `council-decision.json`

```json
{
  "schema_version": "2.0",
  "run_id": "run-id",
  "status": "ready_for_user_review|recommend|experiment_required|waiting_for_input|human_review_required|blocked",
  "synthesis_method": "anonymous_proposal_audit_synthesis",
  "synthesis_input_sha256": "sha256 of the anonymous proposal-audit projection",
  "final_proposal_id": "proposal-v2",
  "final_proposal_sha256": "sha256 of the identity-stripped final proposal",
  "evaluated_audit_ids": ["audit-1", "audit-2"],
  "accepted_finding_ids": ["finding-1"],
  "rejected_findings": [
    {"finding_id": "finding-2", "reason": "evidence-backed rejection"}
  ],
  "disagreements": [
    {
      "topic": "material topic",
      "material": true,
      "resolution": "experiment|human_review|accepted_tradeoff",
      "evidence_refs": ["evidence reference"]
    }
  ],
  "evidence_consumed": ["source reference"],
  "deterministic_gate_results": [
    {"gate_id": "planned-gate", "status": "pass|pending|fail", "evidence_ref": "actual command or report"}
  ],
  "deterministic_gate_status": "pass|pending|fail",
  "deterministic_gate_override": false,
  "deliberation_rounds": 1,
  "unresolved_cross_review_ids": [],
  "unresolved_blocking_finding_ids": [],
  "internal_audit_status": "pass|block",
  "user_review": {
    "status": "pending|approved|changes_requested",
    "reviewed_proposal_id": "proposal-v2",
    "evidence_ref": "empty while pending; required after a user decision"
  },
  "development_gate_status": "awaiting_user_review|pass|block",
  "rounds_used": 1,
  "human_review_required": false,
  "scope_guard": {"goal_preserved": true, "new_scope": []},
  "next_action": "present the final proposal to the user or route the approved proposal"
}
```

`ready_for_user_review` requires a passing internal audit, passing deterministic gates, all-auditor final review, no unresolved cross-reviews or blocker/major findings, `user_review.status=pending`, and `development_gate_status=awaiting_user_review`.

`recommend` additionally requires user approval of the exact final proposal with an evidence reference and `development_gate_status=pass`. Internal Agent agreement alone never unlocks development.

Missing facts require `waiting_for_input`. A material experiment or human decision keeps development blocked. Reaching two rounds with unresolved material disagreement cannot produce `ready_for_user_review` or `recommend`.
