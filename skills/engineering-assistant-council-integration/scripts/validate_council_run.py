#!/usr/bin/env python3
"""Validate a bounded, single-proposal Engineering Assistant Council run."""

import hashlib
import json
import re
import sys
from pathlib import Path

TRIGGERS = {
    "complex_task",
    "repeated_bug",
    "fix_a_break_b",
    "uncertain_root_cause",
    "material_disagreement",
    "explicit_user_request",
}
MODES = {"planning", "diagnosis", "review", "release"}
BACKENDS = {"subagents", "visible_windows", "ateam"}
DECISION_STATUSES = {
    "ready_for_user_review",
    "recommend",
    "experiment_required",
    "waiting_for_input",
    "human_review_required",
    "blocked",
}
GATE_STATUSES = {"pass", "pending", "fail"}
DELIBERATION_MODES = {"controller_relayed_proposal_audit", "direct_peer_proposal_audit"}
FINDING_SEVERITIES = {"blocker", "major", "minor"}
CROSS_REVIEW_VERDICTS = {"support", "challenge", "refine", "no_issue"}
CROSS_REVIEW_SEVERITIES = {"blocker", "major", "minor", "none"}
REVIEWER_RESPONSE_DISPOSITIONS = {
    "resolved",
    "rebutted_with_evidence",
    "withdrawn",
    "refine_required",
}
AUTHOR_RESPONSE_DISPOSITIONS = {
    "resolved",
    "rebutted_with_evidence",
    "experiment_required",
    "human_review_required",
    "accepted_tradeoff",
    "withdrawn_after_cross_review",
}
CLOSED_CROSS_REVIEW_DISPOSITIONS = {"resolved", "rebutted_with_evidence", "withdrawn"}
CLOSED_BLOCKING_FINDING_DISPOSITIONS = {
    "resolved",
    "rebutted_with_evidence",
    "withdrawn_after_cross_review",
}
REPEATED_BUG_EVIDENCE = {
    "symptom_history",
    "prior_fix_diffs",
    "failure_logs_or_reproduction",
    "protected_fix_set",
}
CORE_ARTIFACTS = {
    "council-plan.json",
    "council-member-outputs.json",
    "council-decision.json",
}
PROPOSAL_CONTENT_LISTS = {
    "constraints",
    "assumptions",
    "approach_steps",
    "impacted_components",
    "tradeoffs",
    "risk_controls",
    "verification_plan",
    "rollback_plan",
    "evidence_refs",
}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def require_text_list(value, field, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        suffix = "a list" if allow_empty else "a non-empty list"
        raise ValueError(f"{field} must be {suffix}")
    for index, item in enumerate(value):
        require_text(item, f"{field}[{index}]")
    return value


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def proposal_projection(proposal):
    return {key: value for key, value in proposal.items() if key != "author_id"}


def anonymous_projection(outputs):
    audits = []
    for audit in outputs.get("audits", []):
        audits.append(
            {
                "audit_id": audit.get("audit_id"),
                "audited_proposal_id": audit.get("audited_proposal_id"),
                "findings": audit.get("findings"),
                "no_blocker_rationale": audit.get("no_blocker_rationale"),
                "missing_facts": audit.get("missing_facts"),
            }
        )
    deliberation = outputs.get("deliberation", {})
    projected_rounds = []
    for round_data in deliberation.get("rounds", []):
        projected_rounds.append(
            {
                "round": round_data.get("round"),
                "cross_reviews": round_data.get("cross_reviews"),
                "reviewer_responses": round_data.get("reviewer_responses"),
                "author_responses": [
                    {key: value for key, value in response.items() if key != "author_id"}
                    for response in round_data.get("author_responses", [])
                ],
            }
        )
    return {
        "schema_version": "2.0",
        "run_id": outputs.get("run_id"),
        "baseline_proposal": proposal_projection(outputs.get("baseline_proposal", {})),
        "audits": sorted(audits, key=lambda item: item["audit_id"] or ""),
        "deliberation": {
            "mode": deliberation.get("mode"),
            "rounds": projected_rounds,
        },
        "final_proposal": proposal_projection(outputs.get("final_proposal", {})),
        "final_reviews": outputs.get("final_reviews"),
    }


def frozen_context_checksum(paths):
    digest = hashlib.sha256()
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            raise ValueError(f"frozen context artifact is not a readable file: {raw_path}")
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_identity_projection(outputs, projection):
    projected_text = canonical_json(projection).casefold()
    identity_tokens = require_text_list(outputs.get("identity_tokens"), "outputs.identity_tokens")
    leaked = [token for token in identity_tokens if token.casefold() in projected_text]
    if leaked:
        raise ValueError("anonymous projection contains identity tokens: " + ",".join(leaked))


def validate_proposal_content(content, field):
    if not isinstance(content, dict):
        raise ValueError(f"{field} must be an object")
    require_text(content.get("title"), f"{field}.title")
    require_text(content.get("goal"), f"{field}.goal")
    for name in sorted(PROPOSAL_CONTENT_LISTS):
        require_text_list(content.get(name), f"{field}.{name}")
    require_text_list(content.get("open_questions"), f"{field}.open_questions", allow_empty=True)


def validate_proposal(proposal, field, owner_id, baseline_id=None):
    if not isinstance(proposal, dict):
        if field == "outputs.baseline_proposal":
            raise ValueError("Council requires one complete baseline proposal before any audit")
        raise ValueError(f"{field} must be an object")
    proposal_id = require_text(proposal.get("proposal_id"), f"{field}.proposal_id")
    revision = proposal.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise ValueError(f"{field}.revision must be a positive integer")
    if proposal.get("author_id") != owner_id:
        raise ValueError(f"{field}.author_id must match the planned proposal owner")
    if proposal.get("status") != "complete":
        raise ValueError(f"{field}.status must be complete")
    validate_proposal_content(proposal.get("content"), f"{field}.content")
    if baseline_id is not None:
        if proposal.get("based_on_proposal_id") != baseline_id:
            raise ValueError("final proposal must revise the single baseline proposal")
        require_text(proposal.get("change_summary"), f"{field}.change_summary")
        if not isinstance(proposal.get("change_log"), list):
            raise ValueError(f"{field}.change_log must be a list")
    return proposal_id, revision


def validate_plan(plan):
    if plan.get("schema_version") != "2.0":
        raise ValueError("plan schema_version must be 2.0")
    run_id = require_text(plan.get("run_id"), "plan.run_id")
    if plan.get("capability_id") != "engineering_assistant_council":
        raise ValueError("plan capability_id must be engineering_assistant_council")
    if plan.get("mode") not in MODES:
        raise ValueError("plan mode is invalid")
    require_text(plan.get("task_summary"), "plan.task_summary")

    trigger = plan.get("trigger", {})
    trigger_type = trigger.get("type")
    if trigger_type not in TRIGGERS:
        raise ValueError("plan trigger.type is invalid")
    signals = require_text_list(trigger.get("signals"), "plan.trigger.signals")
    trigger_evidence = set(require_text_list(trigger.get("evidence"), "plan.trigger.evidence"))
    attempt_count = trigger.get("attempt_count")
    if not isinstance(attempt_count, int) or attempt_count < 0:
        raise ValueError("plan trigger.attempt_count must be a non-negative integer")
    if trigger_type == "complex_task" and len(set(signals)) < 2:
        raise ValueError("complex task Council requires at least two distinct complexity signals")
    if trigger_type in {"repeated_bug", "fix_a_break_b"}:
        if attempt_count < 2:
            raise ValueError("repeated bug Council requires attempt_count >= 2")
        missing = REPEATED_BUG_EVIDENCE - trigger_evidence
        if missing:
            raise ValueError("repeated bug trigger evidence missing: " + ",".join(sorted(missing)))

    frozen = plan.get("frozen_context", {})
    frozen_paths = require_text_list(frozen.get("artifact_paths"), "plan.frozen_context.artifact_paths")
    checksum = require_text(frozen.get("checksum"), "plan.frozen_context.checksum")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("plan frozen context checksum must be 64 lowercase hex characters")
    if checksum != frozen_context_checksum(frozen_paths):
        raise ValueError("plan frozen context checksum does not match current artifact contents")
    if frozen.get("old_context_policy") != "historical_only":
        raise ValueError("plan old_context_policy must be historical_only")

    owner = plan.get("proposal_owner", {})
    owner_id = require_text(owner.get("owner_id"), "plan.proposal_owner.owner_id")
    require_text(owner.get("responsibility"), "plan.proposal_owner.responsibility")
    if owner.get("proposal_policy") != "single_baseline_then_revision":
        raise ValueError("proposal owner must author one baseline and one revision")
    if owner.get("business_code_write_policy") != "none":
        raise ValueError("proposal owner cannot write business code during Council review")

    budgets = plan.get("budgets", {})
    max_members = budgets.get("max_members")
    max_rounds = budgets.get("max_rounds")
    if not isinstance(max_members, int) or not 2 <= max_members <= 4:
        raise ValueError("plan max_members must be an integer from 2 to 4")
    if not isinstance(max_rounds, int) or not 1 <= max_rounds <= 2:
        raise ValueError("plan max_rounds must be an integer from 1 to 2")

    members = plan.get("members")
    if not isinstance(members, list) or not 2 <= len(members) <= max_members:
        raise ValueError("plan members must contain 2..max_members audit entries")
    member_ids = []
    member_roles = {}
    roles = []
    for index, member in enumerate(members):
        member_id = require_text(member.get("member_id"), f"plan.members[{index}].member_id")
        role = require_text(member.get("role"), f"plan.members[{index}].role")
        require_text(member.get("responsibility"), f"plan.members[{index}].responsibility")
        require_text_list(member.get("required_evidence"), f"plan.members[{index}].required_evidence")
        if member.get("write_policy") != "read_only":
            raise ValueError(f"plan member {member_id} must be read_only")
        if member.get("proposal_policy") != "audit_only_no_competing_proposal":
            raise ValueError(f"plan member {member_id} must audit and cannot author a competing proposal")
        member_ids.append(member_id)
        member_roles[member_id] = role
        roles.append(role)
    if owner_id in member_ids:
        raise ValueError("proposal owner must be separate from audit members")
    if len(set(member_ids)) != len(member_ids) or len(set(roles)) != len(roles):
        raise ValueError("plan member_id and role values must be unique")

    dispatch = plan.get("dispatch", {})
    backend = dispatch.get("backend")
    if backend not in BACKENDS:
        raise ValueError("plan dispatch.backend is invalid")
    if dispatch.get("mode") != "parallel_ready_set":
        raise ValueError("plan dispatch.mode must be parallel_ready_set")
    if dispatch.get("all_spawned_before_wait") is not True:
        raise ValueError("plan must spawn all ready members before the first wait")
    if backend == "visible_windows" and dispatch.get("explicit_user_authorization") is not True:
        raise ValueError("visible window Council requires explicit user authorization")

    synthesis = plan.get("synthesis", {})
    if synthesis.get("method") != "anonymous_proposal_audit_synthesis":
        raise ValueError("plan synthesis.method must be anonymous_proposal_audit_synthesis")
    if synthesis.get("chair_is_not_member") is not True:
        raise ValueError("plan synthesizer must be independent from audit members")

    deliberation = plan.get("deliberation", {})
    required_pairs = {
        "required": True,
        "review_object": "single_baseline_proposal",
        "competing_proposals_allowed": False,
        "all_members_must_audit_baseline": True,
        "all_members_must_cross_review": True,
        "author_must_respond_to_every_finding": True,
        "final_proposal_must_be_reviewed_by_all": True,
        "zero_unresolved_blocking_findings_before_user_review": True,
        "user_review_required_before_development": True,
        "unanimity_required": False,
    }
    for key, expected in required_pairs.items():
        if deliberation.get(key) != expected:
            raise ValueError(f"plan deliberation.{key} must be {expected!r}")
    if deliberation.get("mode") not in DELIBERATION_MODES:
        raise ValueError("plan deliberation.mode is invalid")
    minimum_cross_reviews = deliberation.get("minimum_cross_reviews_per_member")
    if not isinstance(minimum_cross_reviews, int) or minimum_cross_reviews < 1:
        raise ValueError("plan minimum_cross_reviews_per_member must be at least 1")
    if plan.get("privacy", {}).get("external_model_api_enabled") is not False:
        raise ValueError("external model API must be disabled unless a separately approved policy is implemented")
    deterministic_gates = set(require_text_list(plan.get("deterministic_gates"), "plan.deterministic_gates"))
    if set(require_text_list(plan.get("artifacts"), "plan.artifacts")) != CORE_ARTIFACTS:
        raise ValueError("plan artifacts must be exactly the three Council core artifacts")
    if plan.get("status") != "planned":
        raise ValueError("plan status must be planned")
    return (
        run_id,
        owner_id,
        member_roles,
        max_rounds,
        backend,
        deterministic_gates,
        minimum_cross_reviews,
    )


def validate_outputs(
    outputs,
    run_id,
    owner_id,
    member_roles,
    backend,
    max_rounds,
    minimum_cross_reviews,
):
    member_ids = set(member_roles)
    if outputs.get("schema_version") != "2.0" or outputs.get("run_id") != run_id:
        raise ValueError("member outputs schema_version or run_id mismatch")
    if "candidates" in outputs:
        raise ValueError("Council requires one complete baseline proposal; competing candidate proposals are forbidden")
    dispatch = outputs.get("dispatch", {})
    if dispatch.get("all_started_before_first_wait") is not True:
        raise ValueError("member outputs prove a wait occurred before all members started")
    if set(require_text_list(dispatch.get("started_member_ids"), "outputs.dispatch.started_member_ids")) != member_ids:
        raise ValueError("started_member_ids must match every planned audit member")
    expected_source = "multi_window_dispatch_ledger" if backend == "visible_windows" else "controller_tool_results"
    if dispatch.get("recorded_by") != "controller" or dispatch.get("evidence_source") != expected_source:
        raise ValueError("parallel dispatch evidence source does not match the selected backend")
    if backend == "visible_windows":
        require_text(dispatch.get("dispatch_ledger_path"), "outputs.dispatch.dispatch_ledger_path")
    if dispatch.get("council_target_repo_edits") != []:
        raise ValueError("read-only Council introduced target repository edits")
    if dispatch.get("external_model_api_calls") != 0:
        raise ValueError("Council external model API calls must be zero")

    baseline_id, baseline_revision = validate_proposal(
        outputs.get("baseline_proposal"), "outputs.baseline_proposal", owner_id
    )
    if baseline_revision != 1:
        raise ValueError("baseline proposal revision must be 1")

    audits = outputs.get("audits")
    if not isinstance(audits, list) or len(audits) != len(member_ids):
        raise ValueError("member outputs must contain exactly one audit per planned member")
    audit_ids = []
    output_member_ids = []
    audit_owners = {}
    finding_ids = set()
    finding_owners = {}
    finding_severity = {}
    has_missing_facts = False
    for index, audit in enumerate(audits):
        audit_id = require_text(audit.get("audit_id"), f"outputs.audits[{index}].audit_id")
        member_id = require_text(audit.get("member_id"), f"outputs.audits[{index}].member_id")
        role = require_text(audit.get("role"), f"outputs.audits[{index}].role")
        if member_roles.get(member_id) != role:
            raise ValueError(f"audit {audit_id} role does not match the planned member role")
        if audit.get("status") != "complete":
            raise ValueError(f"audit {audit_id} is not complete")
        if audit.get("audited_proposal_id") != baseline_id:
            raise ValueError(f"audit {audit_id} must review the single baseline proposal")
        findings = audit.get("findings")
        if not isinstance(findings, list):
            raise ValueError(f"audit {audit_id}.findings must be a list")
        no_blocker_rationale = audit.get("no_blocker_rationale", "")
        if not findings:
            require_text(no_blocker_rationale, f"audit {audit_id}.no_blocker_rationale")
        elif not isinstance(no_blocker_rationale, str):
            raise ValueError(f"audit {audit_id}.no_blocker_rationale must be a string")
        for finding_index, finding in enumerate(findings):
            finding_id = require_text(
                finding.get("finding_id"), f"audit {audit_id} finding[{finding_index}].finding_id"
            )
            if finding_id in finding_ids:
                raise ValueError(f"duplicate finding_id {finding_id}")
            if finding.get("severity") not in FINDING_SEVERITIES:
                raise ValueError(f"finding {finding_id}.severity is invalid")
            require_text(finding.get("statement"), f"finding {finding_id}.statement")
            require_text(finding.get("proposal_section"), f"finding {finding_id}.proposal_section")
            require_text_list(finding.get("evidence_refs"), f"finding {finding_id}.evidence_refs")
            require_text(finding.get("falsification_test"), f"finding {finding_id}.falsification_test")
            require_text(finding.get("suggested_correction"), f"finding {finding_id}.suggested_correction")
            finding_ids.add(finding_id)
            finding_owners[finding_id] = audit_id
            finding_severity[finding_id] = finding["severity"]
        missing_facts = audit.get("missing_facts")
        if not isinstance(missing_facts, list):
            raise ValueError(f"audit {audit_id}.missing_facts must be a list")
        if missing_facts:
            require_text_list(missing_facts, f"audit {audit_id}.missing_facts")
            has_missing_facts = True
        audit_ids.append(audit_id)
        output_member_ids.append(member_id)
        audit_owners[audit_id] = member_id
    if len(set(audit_ids)) != len(audit_ids):
        raise ValueError("audit_id values must be unique")
    if set(output_member_ids) != member_ids or len(set(output_member_ids)) != len(member_ids):
        raise ValueError("audit member_id values must match planned members one-to-one")
    audit_id_set = set(audit_ids)

    deliberation = outputs.get("deliberation", {})
    if deliberation.get("mode") not in DELIBERATION_MODES:
        raise ValueError("outputs deliberation.mode is invalid")
    if deliberation.get("all_members_participated") is not True:
        raise ValueError("outputs deliberation must confirm all members participated")
    rounds = deliberation.get("rounds")
    if not isinstance(rounds, list) or not 1 <= len(rounds) <= max_rounds:
        raise ValueError("outputs deliberation rounds must contain 1..max_rounds entries")

    cross_review_ids = set()
    cross_reviewer_counts = {audit_id: 0 for audit_id in audit_id_set}
    cross_reviewed_audits = set()
    cross_challenges = {}
    reviewer_responses = {}
    author_responses = {}
    for expected_round, round_data in enumerate(rounds, start=1):
        if round_data.get("round") != expected_round:
            raise ValueError("deliberation round numbers must be consecutive from 1")
        cross_reviews = round_data.get("cross_reviews")
        if not isinstance(cross_reviews, list) or not cross_reviews:
            raise ValueError(f"deliberation round {expected_round} must contain cross reviews")
        for review_index, review in enumerate(cross_reviews):
            review_id = require_text(
                review.get("cross_review_id"),
                f"round {expected_round} cross_review[{review_index}].cross_review_id",
            )
            if review_id in cross_review_ids:
                raise ValueError(f"duplicate cross_review_id {review_id}")
            reviewer = require_text(review.get("reviewer_audit_id"), f"cross review {review_id}.reviewer_audit_id")
            target = require_text(review.get("target_audit_id"), f"cross review {review_id}.target_audit_id")
            if reviewer not in audit_id_set or target not in audit_id_set or reviewer == target:
                raise ValueError(f"cross review {review_id} must target another known audit")
            reviewed_finding_ids = set(
                require_text_list(
                    review.get("reviewed_finding_ids"),
                    f"cross review {review_id}.reviewed_finding_ids",
                    allow_empty=True,
                )
            )
            if any(finding_owners.get(finding_id) != target for finding_id in reviewed_finding_ids):
                raise ValueError(f"cross review {review_id} includes a finding not owned by its target audit")
            verdict = review.get("verdict")
            severity = review.get("severity")
            if verdict not in CROSS_REVIEW_VERDICTS or severity not in CROSS_REVIEW_SEVERITIES:
                raise ValueError(f"cross review {review_id} verdict or severity is invalid")
            require_text_list(review.get("evidence_refs"), f"cross review {review_id}.evidence_refs")
            require_text(review.get("falsification_test"), f"cross review {review_id}.falsification_test")
            objection = review.get("objection", "")
            if verdict in {"challenge", "refine"}:
                require_text(objection, f"cross review {review_id}.objection")
                if severity == "none":
                    raise ValueError(f"cross review {review_id} cannot use severity none")
                cross_challenges[review_id] = {"target": target, "severity": severity}
            elif severity != "none" or (isinstance(objection, str) and objection.strip()):
                raise ValueError(f"{verdict} cross review {review_id} must use severity none and no objection")
            cross_review_ids.add(review_id)
            cross_reviewer_counts[reviewer] += 1
            cross_reviewed_audits.add(target)

        responses = round_data.get("reviewer_responses")
        if not isinstance(responses, list):
            raise ValueError(f"deliberation round {expected_round}.reviewer_responses must be a list")
        for response_index, response in enumerate(responses):
            review_id = require_text(
                response.get("cross_review_id"),
                f"round {expected_round} reviewer_response[{response_index}].cross_review_id",
            )
            if review_id in reviewer_responses:
                raise ValueError(f"duplicate reviewer response for cross review {review_id}")
            challenge = cross_challenges.get(review_id)
            if not challenge:
                raise ValueError(f"reviewer response references unknown or non-challenge review {review_id}")
            responder = require_text(
                response.get("responder_audit_id"), f"reviewer response {review_id}.responder_audit_id"
            )
            if responder != challenge["target"]:
                raise ValueError(f"reviewer response {review_id} must come from the challenged audit")
            disposition = response.get("disposition")
            if disposition not in REVIEWER_RESPONSE_DISPOSITIONS:
                raise ValueError(f"reviewer response {review_id}.disposition is invalid")
            require_text(response.get("response"), f"reviewer response {review_id}.response")
            require_text_list(response.get("evidence_refs"), f"reviewer response {review_id}.evidence_refs")
            reviewer_responses[review_id] = disposition

        responses = round_data.get("author_responses")
        if not isinstance(responses, list):
            raise ValueError(f"deliberation round {expected_round}.author_responses must be a list")
        for response_index, response in enumerate(responses):
            finding_id = require_text(
                response.get("finding_id"),
                f"round {expected_round} author_response[{response_index}].finding_id",
            )
            if finding_id not in finding_ids:
                raise ValueError(f"author response references unknown finding {finding_id}")
            if finding_id in author_responses:
                raise ValueError(f"duplicate author response for finding {finding_id}")
            if response.get("author_id") != owner_id:
                raise ValueError(f"author response {finding_id} must come from the proposal owner")
            disposition = response.get("disposition")
            if disposition not in AUTHOR_RESPONSE_DISPOSITIONS:
                raise ValueError(f"author response {finding_id}.disposition is invalid")
            if disposition == "accepted_tradeoff" and finding_severity[finding_id] in {"blocker", "major"}:
                raise ValueError(f"blocking finding {finding_id} cannot close as accepted_tradeoff")
            require_text(response.get("response"), f"author response {finding_id}.response")
            require_text_list(response.get("evidence_refs"), f"author response {finding_id}.evidence_refs")
            change_refs = require_text_list(
                response.get("proposal_change_refs"),
                f"author response {finding_id}.proposal_change_refs",
                allow_empty=True,
            )
            if disposition == "resolved" and not change_refs:
                raise ValueError(f"resolved finding {finding_id} must reference the final proposal change")
            author_responses[finding_id] = disposition

    if any(count < minimum_cross_reviews for count in cross_reviewer_counts.values()):
        raise ValueError("every audit member must complete the minimum cross reviews")
    if cross_reviewed_audits != audit_id_set:
        raise ValueError("every audit must be cross-reviewed by another audit member")
    if set(reviewer_responses) != set(cross_challenges):
        raise ValueError("every reviewer challenge must receive exactly one target-auditor response")
    if set(author_responses) != finding_ids:
        raise ValueError("proposal author must respond exactly once to every audit finding")

    unresolved_cross_reviews = {
        review_id
        for review_id, disposition in reviewer_responses.items()
        if disposition not in CLOSED_CROSS_REVIEW_DISPOSITIONS
    }
    unresolved_blocking_findings = {
        finding_id
        for finding_id, severity in finding_severity.items()
        if severity in {"blocker", "major"}
        and author_responses.get(finding_id) not in CLOSED_BLOCKING_FINDING_DISPOSITIONS
    }

    final_id, final_revision = validate_proposal(
        outputs.get("final_proposal"), "outputs.final_proposal", owner_id, baseline_id=baseline_id
    )
    if final_id == baseline_id or final_revision <= baseline_revision:
        raise ValueError("final proposal must be a new revision of the baseline")
    for index, change in enumerate(outputs["final_proposal"]["change_log"]):
        finding_id = require_text(change.get("finding_id"), f"final change_log[{index}].finding_id")
        if finding_id not in finding_ids:
            raise ValueError(f"final proposal change_log references unknown finding {finding_id}")
        require_text(change.get("action"), f"final change_log[{index}].action")
        require_text(change.get("proposal_section"), f"final change_log[{index}].proposal_section")

    final_reviews = outputs.get("final_reviews")
    if not isinstance(final_reviews, list) or len(final_reviews) != len(audit_id_set):
        raise ValueError("final proposal must be reviewed by every auditor")
    final_reviewer_ids = []
    final_review_ids = set()
    final_review_blocking_findings = set()
    all_final_reviews_pass = True
    for index, review in enumerate(final_reviews):
        review_id = require_text(review.get("final_review_id"), f"final_reviews[{index}].final_review_id")
        if review_id in final_review_ids:
            raise ValueError(f"duplicate final_review_id {review_id}")
        reviewer = require_text(review.get("reviewer_audit_id"), f"final review {review_id}.reviewer_audit_id")
        if reviewer not in audit_id_set:
            raise ValueError(f"final review {review_id} has an unknown reviewer audit")
        if review.get("audited_proposal_id") != final_id:
            raise ValueError(f"final review {review_id} must review the final proposal")
        verdict = review.get("verdict")
        if verdict not in {"pass", "block"}:
            raise ValueError(f"final review {review_id}.verdict is invalid")
        unresolved = set(
            require_text_list(
                review.get("unresolved_finding_ids"),
                f"final review {review_id}.unresolved_finding_ids",
                allow_empty=True,
            )
        )
        if unresolved - finding_ids:
            raise ValueError(f"final review {review_id} references an unknown finding")
        if verdict == "pass" and unresolved:
            raise ValueError(f"passing final review {review_id} cannot list unresolved findings")
        if verdict == "block" and not unresolved:
            raise ValueError(f"blocking final review {review_id} must list unresolved findings")
        require_text_list(review.get("evidence_refs"), f"final review {review_id}.evidence_refs")
        final_review_ids.add(review_id)
        final_reviewer_ids.append(reviewer)
        final_review_blocking_findings.update(unresolved)
        all_final_reviews_pass = all_final_reviews_pass and verdict == "pass"
    if set(final_reviewer_ids) != audit_id_set or len(set(final_reviewer_ids)) != len(audit_id_set):
        raise ValueError("final proposal must be reviewed by every auditor exactly once")
    unresolved_blocking_findings.update(final_review_blocking_findings)
    final_digest = hashlib.sha256(canonical_json(proposal_projection(outputs["final_proposal"])).encode("utf-8")).hexdigest()
    return {
        "audit_ids": audit_id_set,
        "finding_ids": finding_ids,
        "has_missing_facts": has_missing_facts,
        "deliberation_rounds": len(rounds),
        "unresolved_cross_reviews": unresolved_cross_reviews,
        "unresolved_blocking_findings": unresolved_blocking_findings,
        "final_proposal_id": final_id,
        "final_proposal_sha256": final_digest,
        "all_final_reviews_pass": all_final_reviews_pass,
    }


def validate_decision(decision, run_id, output_state, max_rounds, deterministic_gates):
    if decision.get("schema_version") != "2.0" or decision.get("run_id") != run_id:
        raise ValueError("decision schema_version or run_id mismatch")
    status = decision.get("status")
    if status not in DECISION_STATUSES:
        raise ValueError("decision status is invalid")
    if decision.get("synthesis_method") != "anonymous_proposal_audit_synthesis":
        raise ValueError("decision must use anonymous_proposal_audit_synthesis")
    if decision.get("final_proposal_id") != output_state["final_proposal_id"]:
        raise ValueError("decision final_proposal_id must match the reviewed final proposal")
    if decision.get("final_proposal_sha256") != output_state["final_proposal_sha256"]:
        raise ValueError("decision final_proposal_sha256 does not match the final proposal")
    evaluated = set(require_text_list(decision.get("evaluated_audit_ids"), "decision.evaluated_audit_ids"))
    if evaluated != output_state["audit_ids"]:
        raise ValueError("decision must evaluate every anonymized audit exactly once")
    accepted = set(
        require_text_list(
            decision.get("accepted_finding_ids"),
            "decision.accepted_finding_ids",
            allow_empty=True,
        )
    )
    if accepted - output_state["finding_ids"]:
        raise ValueError("decision accepted an unknown finding")
    for index, rejected in enumerate(decision.get("rejected_findings", [])):
        if rejected.get("finding_id") not in output_state["finding_ids"]:
            raise ValueError("decision rejected an unknown finding")
        require_text(rejected.get("reason"), f"decision.rejected_findings[{index}].reason")

    material_blocks_review = False
    for index, disagreement in enumerate(decision.get("disagreements", [])):
        require_text(disagreement.get("topic"), f"decision.disagreements[{index}].topic")
        require_text_list(disagreement.get("evidence_refs"), f"decision.disagreements[{index}].evidence_refs")
        resolution = disagreement.get("resolution")
        if disagreement.get("material") is True:
            if resolution not in {"experiment", "human_review", "accepted_tradeoff"}:
                raise ValueError("material disagreement lacks experiment, human review, or accepted tradeoff")
            if resolution in {"experiment", "human_review"}:
                material_blocks_review = True

    gate_results = decision.get("deterministic_gate_results")
    if not isinstance(gate_results, list) or not gate_results:
        raise ValueError("decision deterministic_gate_results must be a non-empty list")
    result_gate_ids = set()
    result_statuses = []
    for index, result in enumerate(gate_results):
        gate_id = require_text(result.get("gate_id"), f"decision.deterministic_gate_results[{index}].gate_id")
        if result.get("status") not in GATE_STATUSES:
            raise ValueError(f"deterministic gate {gate_id} status is invalid")
        require_text(result.get("evidence_ref"), f"deterministic gate {gate_id}.evidence_ref")
        result_gate_ids.add(gate_id)
        result_statuses.append(result["status"])
    if result_gate_ids != deterministic_gates or len(result_gate_ids) != len(gate_results):
        raise ValueError("decision deterministic gate results must match the planned gates one-to-one")
    derived_gate_status = "fail" if "fail" in result_statuses else ("pending" if "pending" in result_statuses else "pass")
    if decision.get("deterministic_gate_status") != derived_gate_status:
        raise ValueError("decision deterministic_gate_status does not match gate results")
    if decision.get("deterministic_gate_override") is not False:
        raise ValueError("Council attempted to override a deterministic gate")

    if decision.get("deliberation_rounds") != output_state["deliberation_rounds"]:
        raise ValueError("decision deliberation_rounds must match the validated transcript")
    declared_cross = decision.get("unresolved_cross_review_ids")
    if not isinstance(declared_cross, list) or set(declared_cross) != output_state["unresolved_cross_reviews"]:
        raise ValueError("decision unresolved_cross_review_ids must match the deliberation transcript")
    declared_findings = decision.get("unresolved_blocking_finding_ids")
    if not isinstance(declared_findings, list) or set(declared_findings) != output_state["unresolved_blocking_findings"]:
        raise ValueError("decision unresolved_blocking_finding_ids must match the deliberation transcript")

    internal_pass = (
        not output_state["has_missing_facts"]
        and not output_state["unresolved_cross_reviews"]
        and not output_state["unresolved_blocking_findings"]
        and output_state["all_final_reviews_pass"]
        and not material_blocks_review
    )
    derived_internal_status = "pass" if internal_pass else "block"
    if decision.get("internal_audit_status") != derived_internal_status:
        raise ValueError("decision internal_audit_status does not match the proposal audit transcript")

    user_review = decision.get("user_review", {})
    user_review_status = user_review.get("status")
    if user_review_status not in {"pending", "approved", "changes_requested"}:
        raise ValueError("decision user_review.status is invalid")
    if user_review.get("reviewed_proposal_id") != output_state["final_proposal_id"]:
        raise ValueError("user review must target the final proposal")
    evidence_ref = user_review.get("evidence_ref", "")
    if user_review_status in {"approved", "changes_requested"}:
        require_text(evidence_ref, "decision.user_review.evidence_ref")
    elif not isinstance(evidence_ref, str) or evidence_ref.strip():
        raise ValueError("pending user review must not claim approval evidence")

    if status == "ready_for_user_review":
        if not internal_pass or derived_gate_status != "pass":
            raise ValueError("proposal cannot be presented for user review with unresolved audit blockers")
        if user_review_status != "pending":
            raise ValueError("ready_for_user_review requires pending user review")
        derived_development_gate = "awaiting_user_review"
    elif status == "recommend":
        if not internal_pass or derived_gate_status != "pass":
            raise ValueError("decision cannot recommend development before proposal audit gates pass")
        if user_review_status != "approved":
            raise ValueError("decision cannot recommend development before user review approves the final proposal")
        derived_development_gate = "pass"
    else:
        derived_development_gate = "block"
    if decision.get("development_gate_status") != derived_development_gate:
        raise ValueError("decision development_gate_status does not match audit and user review state")

    rounds_used = decision.get("rounds_used")
    if not isinstance(rounds_used, int) or not 1 <= rounds_used <= max_rounds:
        raise ValueError("decision rounds_used exceeds the bounded plan")
    if rounds_used != output_state["deliberation_rounds"]:
        raise ValueError("decision rounds_used must match deliberation rounds")
    if status == "human_review_required" and decision.get("human_review_required") is not True:
        raise ValueError("human_review_required status must set human_review_required=true")
    if output_state["has_missing_facts"] and status != "waiting_for_input":
        raise ValueError("audit missing facts require waiting_for_input")
    scope_guard = decision.get("scope_guard", {})
    if scope_guard.get("goal_preserved") is not True:
        raise ValueError("decision scope_guard must preserve the confirmed goal")
    new_scope = scope_guard.get("new_scope")
    if not isinstance(new_scope, list):
        raise ValueError("decision scope_guard.new_scope must be a list")
    if new_scope and status not in {"human_review_required", "waiting_for_input"}:
        raise ValueError("new Council scope requires human review or input")
    require_text_list(decision.get("evidence_consumed"), "decision.evidence_consumed")
    require_text(decision.get("next_action"), "decision.next_action")


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--hash-context":
        try:
            print(frozen_context_checksum(sys.argv[2:]))
        except (OSError, ValueError) as error:
            print(f"INVALID_COUNCIL_FROZEN_CONTEXT: {error}", file=sys.stderr)
            return 1
        return 0
    if len(sys.argv) != 4:
        print(
            "INVALID_ENGINEERING_ASSISTANT_COUNCIL_RUN: usage: validate_council_run.py council-plan.json council-member-outputs.json council-decision.json",
            file=sys.stderr,
        )
        return 1
    try:
        plan = load(sys.argv[1])
        outputs = load(sys.argv[2])
        decision = load(sys.argv[3])
        (
            run_id,
            owner_id,
            member_roles,
            max_rounds,
            backend,
            deterministic_gates,
            minimum_cross_reviews,
        ) = validate_plan(plan)
        output_state = validate_outputs(
            outputs,
            run_id,
            owner_id,
            member_roles,
            backend,
            max_rounds,
            minimum_cross_reviews,
        )
        projection = anonymous_projection(outputs)
        validate_identity_projection(outputs, projection)
        expected_digest = hashlib.sha256(canonical_json(projection).encode("utf-8")).hexdigest()
        if decision.get("synthesis_input_sha256") != expected_digest:
            raise ValueError("decision synthesis_input_sha256 does not match the anonymous proposal-audit projection")
        validate_decision(decision, run_id, output_state, max_rounds, deterministic_gates)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"INVALID_ENGINEERING_ASSISTANT_COUNCIL_RUN: {error}", file=sys.stderr)
        return 1
    print("VALID_ENGINEERING_ASSISTANT_COUNCIL_RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
