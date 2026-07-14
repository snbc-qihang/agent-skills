#!/usr/bin/env python3
"""Generate assistant-run-feedback.json from available Engineering Assistant artifacts."""

import json
import sys
from pathlib import Path

BLOCKER_GATES = {
    "ACTIVE_ENGINEERING_ASSISTANT_CAPABILITY_MISSING",
    "ASSISTANT_CAPABILITY_CLAIM_NOT_VERIFIED",
    "ASSISTANT_FEEDBACK_NOT_GENERATED",
    "ASSISTANT_FEEDBACK_NOT_CONSUMED_BY_AGENT",
    "CAPABILITY_OUTPUT_NOT_CONSUMED",
    "CAPABILITY_OUTPUT_NOT_RECORDED",
    "CAPABILITY_HEALTH_NOT_CHECKED",
    "TARGET_REPO_ARTIFACT_POLLUTION",
    "PROCESS_DOCUMENTATION_POLLUTION",
    "NO_EFFECTIVE_CODE_CHANGE",
    "CHANGE_VERIFICATION_EVIDENCE_MISSING",
    "DUPLICATE_CAPABILITY_RISK",
    "GATE_NOT_ENFORCED",
    "NON_ATOMIC_GIT_COMMIT_PLAN",
    "RUNTIME_ROUTE_NOT_SELECTED",
    "NON_STANDARD_RUNTIME_ROUTE",
    "ASSISTANT_AUDIT_TARGET_REPO_EDIT_FORBIDDEN",
    "CUSTOMER_VISIBLE_SOURCE_RESTRICTION_UNJUSTIFIED",
    "POSITIVE_SKILL_INSTRUCTION_SHAPE_MISSING",
    "FIX_CHAIN_REGRESSION_UNCHECKED",
}

DARWIN_GATES = {
    "ACTIVE_ENGINEERING_ASSISTANT_CAPABILITY_MISSING",
    "ASSISTANT_CAPABILITY_CLAIM_NOT_VERIFIED",
    "CAPABILITY_OUTPUT_NOT_CONSUMED",
    "CAPABILITY_OUTPUT_NOT_RECORDED",
    "CAPABILITY_HEALTH_NOT_CHECKED",
    "TARGET_REPO_ARTIFACT_POLLUTION",
    "PROCESS_DOCUMENTATION_POLLUTION",
    "NO_EFFECTIVE_CODE_CHANGE",
    "CHANGE_VERIFICATION_EVIDENCE_MISSING",
    "DUPLICATE_CAPABILITY_RISK",
    "GATE_NOT_ENFORCED",
    "RUNTIME_ROUTE_NOT_SELECTED",
    "NON_STANDARD_RUNTIME_ROUTE",
    "ASSISTANT_AUDIT_TARGET_REPO_EDIT_FORBIDDEN",
    "CUSTOMER_VISIBLE_SOURCE_RESTRICTION_UNJUSTIFIED",
    "POSITIVE_SKILL_INSTRUCTION_SHAPE_MISSING",
    "FIX_CHAIN_REGRESSION_UNCHECKED",
}

STANDARD_TASK_KIND = {"context", "audit", "change", "release", "self_healing"}
STANDARD_EVIDENCE_LEVEL = {"inline", "lite", "standard", "formal"}
STANDARD_PERSISTENCE_MODE = {"inline", "ephemeral", "target_repo", "blocked"}
CLOSED_LOOP_CONTRACT_VERSION = "2026-07-03"
CHANGE_DIFF_KEYS = {
    "changed_files",
    "target_code_diff",
    "code_diff",
    "diff_summary",
    "implementation",
    "changes",
}
CHANGE_VERIFICATION_KEYS = {
    "verification",
    "verification_evidence",
    "test_evidence",
    "tests",
    "validation",
}


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def gates(run_state):
    return [g.get("code") for g in run_state.get("gates", []) if isinstance(g, dict) and g.get("code")]


def has_any_key(value, keys):
    if isinstance(value, dict):
        if any(key in value and value.get(key) for key in keys):
            return True
        return any(has_any_key(item, keys) for item in value.values())
    if isinstance(value, list):
        return any(has_any_key(item, keys) for item in value)
    return False


def is_assistant_audit_context(run_state, route):
    context = run_state.get("assistant_context", {})
    if context.get("assistant_rule_or_capability_audit") is True:
        return True
    if route.get("task_kind") in {"audit", "self_healing"}:
        signals = " ".join(str(item) for item in route.get("trigger_signals", []))
        markers = [
            "研发助手",
            "Engineering Assistant",
            "skill",
            "overlay",
            "规则缺陷",
            "能力问题",
            "SkillOpt-Sleep",
            "Darwin",
        ]
        return any(marker in signals for marker in markers)
    return False


def project_code_change_requested(run_state, route):
    context = run_state.get("assistant_context", {})
    return bool(
        context.get("explicit_project_code_change_requested")
        or route.get("explicit_project_code_change_requested")
    )


def has_target_repo_edits(run_state):
    edits = run_state.get("target_repo_edits")
    if isinstance(edits, list) and edits:
        return True
    if isinstance(edits, dict) and edits:
        return True
    return False


def has_unjustified_customer_visible_source_restriction(run_state):
    context = run_state.get("business_data_context", {})
    materialized = bool(
        context.get("materialized_to_business_tables")
        or context.get("accepted_as_current_system_data")
        or context.get("current_system_accepts_data")
    )
    if not materialized:
        return False
    restrictions = run_state.get("customer_visible_source_restrictions", [])
    if not isinstance(restrictions, list):
        return False
    for restriction in restrictions:
        if not isinstance(restriction, dict):
            continue
        customer_visible = bool(
            restriction.get("user_visible_message")
            or restriction.get("customer_visible_label")
            or restriction.get("blocks_current_business_data")
            or restriction.get("restriction_type")
        )
        if not customer_visible:
            continue
        has_business_rule = bool(restriction.get("business_rule_evidence"))
        has_external_side_effect = bool(restriction.get("external_side_effect_evidence"))
        has_protective_effect = bool(restriction.get("protective_effect"))
        if not (has_business_rule or (has_external_side_effect and has_protective_effect)):
            return True
    return False


def has_positive_skill_instruction_shape_missing(run_state):
    review = run_state.get("skill_instruction_review")
    if not isinstance(review, dict) or review.get("not_applicable") is True:
        return False

    required_flags = (
        "description_is_trigger_only",
        "positive_target_behavior_present",
        "completion_checks_present",
    )
    if any(review.get(flag) is False for flag in required_flags):
        return True
    if review.get("gate_only_or_prohibition_first") is True:
        return True

    shape = review.get("instruction_shape")
    if isinstance(shape, dict) and shape:
        required_shape = ("trigger", "do", "checks", "gate")
        return any(not shape.get(key) for key in required_shape)
    return False


def as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def as_list(value):
    if isinstance(value, list):
        return value
    if value in (None, "", {}):
        return []
    return [value]


def bool_or_unknown(value):
    if isinstance(value, bool):
        return value
    return "unknown"


def test_evidence_from(run_state):
    value = (
        run_state.get("test_evidence")
        or run_state.get("verification_evidence")
        or run_state.get("verification")
        or run_state.get("tests")
        or run_state.get("validation")
    )
    if isinstance(value, dict):
        return as_list(value.get("commands") or value.get("tests") or value.get("evidence"))
    return as_list(value)


def external_evidence_status(run_state):
    raw = run_state.get("external_evidence") or run_state.get("external_feedback") or {}
    keys = {
        "sentry": "pending_external_connector",
        "mlflow_trace": "pending_external_connector",
        "ci_test_platform": "pending_external_connector",
        "performance_monitoring": "pending_external_connector",
        "git_pr_review": "pending_external_connector",
    }
    if not isinstance(raw, dict):
        return keys
    valid = {"available", "not_configured", "not_checked", "pending_external_connector"}
    for key in keys:
        value = raw.get(key)
        if value in valid:
            keys[key] = value
    return keys


def build_closed_loop_outcome(root, run_state, route, feedback, codes):
    route_data = feedback["route"]
    fix_attempt_count = as_int(
        run_state.get(
            "fix_attempt_count",
            run_state.get("repair_attempt_count", run_state.get("attempt_count", 0)),
        )
    )
    user_correction_count = as_int(run_state.get("user_correction_count", 0))
    repeated_fix = fix_attempt_count >= 2 or any(code.startswith("REPEATED_FIX") for code in codes)
    first_pass_success = (
        True
        if feedback["overall_status"] == "pass" and fix_attempt_count == 0 and user_correction_count == 0
        else False
    )
    pattern_codes = [
        code
        for code in codes
        if code.startswith("REPEATED_FIX")
        or code
        in {
            "FLOW_PERFORMANCE_REGRESSION_UNCHECKED",
            "API_PERFORMANCE_BUDGET_MISSING",
            "GIT_CONFLICT_FEATURE_PRESERVATION_UNCHECKED",
            "CODE_DESIGN_GATE_MISSING",
            "BUSINESS_CODE_PILEUP_UNCHECKED",
            "FRAMEWORK_INTEGRATION_NOT_EVALUATED",
            "SYNC_DATA_USABILITY_NOT_VERIFIED",
        }
    ]
    reward = run_state.get("reward_signal") if isinstance(run_state.get("reward_signal"), dict) else {}
    task_score = reward.get("task_score")
    scored = isinstance(task_score, (int, float))
    independent = run_state.get("independent_review") if isinstance(run_state.get("independent_review"), dict) else {}
    project_memory = run_state.get("project_memory") if isinstance(run_state.get("project_memory"), dict) else {}
    candidate_updates = as_list(project_memory.get("candidate_updates"))
    if pattern_codes and not candidate_updates:
        candidate_updates = [{"type": "rule_or_flow_candidate", "source_codes": pattern_codes}]
    return {
        "run_id": feedback["run_id"],
        "feedback_owner": "codex_agent",
        "loop_contract_version": CLOSED_LOOP_CONTRACT_VERSION,
        "route": route_data,
        "execution_feedback": {
            "overall_status": feedback["overall_status"],
            "first_pass_success": first_pass_success,
            "fix_attempt_count": fix_attempt_count,
            "repeated_fix": repeated_fix,
            "introduced_regression": bool_or_unknown(run_state.get("introduced_regression")),
            "user_correction_count": user_correction_count,
            "tests_executed": test_evidence_from(run_state),
            "runtime_refresh": run_state.get("runtime_refresh", {"status": "not_recorded"}),
            "verification_evidence_present": bool(test_evidence_from(run_state)),
            "rule_violations": codes,
        },
        "trajectory_distillation": {
            "samples": as_list(run_state.get("trajectory_samples")),
            "sample_classification": {
                "success": feedback["overall_status"] == "pass",
                "failure": feedback["overall_status"] in {"blocked", "warn"},
                "repeated_fix": repeated_fix,
                "performance": any("PERFORMANCE" in code or "CPU" in code for code in codes),
                "conflict": "GIT_CONFLICT_FEATURE_PRESERVATION_UNCHECKED" in codes,
                "design": any(code in {"CODE_DESIGN_GATE_MISSING", "BUSINESS_CODE_PILEUP_UNCHECKED"} for code in codes),
            },
            "pattern_candidates": as_list(run_state.get("pattern_candidates")) or pattern_codes,
            "distillation_required": bool(pattern_codes or repeated_fix),
        },
        "compression_augmentation": {
            "candidate_gate_changes": as_list(run_state.get("candidate_gate_changes")),
            "duplicate_or_overlap_reviewed": bool(run_state.get("skill_gate_compression_review")),
            "project_scope": run_state.get("project_scope", route.get("project", "unknown")),
            "human_approval_required": bool(run_state.get("candidate_gate_changes") or run_state.get("project_memory")),
        },
        "reinforcement_signal": {
            "score_status": "scored" if scored else "pending_metrics",
            "task_score": task_score if scored else None,
            "missing_metric_sources": [] if scored else [
                "first_pass_success_rate",
                "fix_attempt_count",
                "regression_rate",
                "user_correction_count",
                "test_pass_rate",
                "independent_review_result",
                "production_error_rate",
                "api_latency_cpu_memory_slow_sql",
            ],
        },
        "external_evidence": external_evidence_status(run_state),
        "independent_review": {
            "developer_verified": bool(independent.get("developer_verified") or run_state.get("developer_verified")),
            "independent_reviewed": bool(independent.get("independent_reviewed") or run_state.get("independent_reviewed")),
            "independent_review_required": route_data.get("task_kind") in {"change", "release"},
        },
        "project_memory": {
            "project": run_state.get("project") or route.get("project") or "unknown",
            "candidate_updates": candidate_updates,
            "formal_promotion_allowed": False,
        },
        "next_run_context": {
            "must_consume_artifacts": [
                str(root / "assistant-run-feedback.json"),
                str(root / "closed-loop-outcome.json"),
            ],
            "reason": "Use prior execution feedback before related planning, fixes, review, or skill evolution.",
        },
    }


def main():
    if len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}:
        print("usage: generate_assistant_run_feedback.py artifact-root")
        return 0
    if len(sys.argv) != 2:
        print("usage: generate_assistant_run_feedback.py artifact-root", file=sys.stderr)
        return 1
    root = Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=True)
    run_state = load_json(root / "run_state.json", {})
    route = load_json(root / "runtime-route-decision.json", {})
    policy = load_json(root / "artifact-persistence-policy.json", {})
    ledger = load_json(root / "capability-invocation-ledger.json", {})
    health = load_json(root / "capability-health.json", {})
    consumption = load_json(root / "capability-output-consumption.json", {})
    codes = gates(run_state)
    route_task_kind = route.get("task_kind", "unknown")
    route_evidence_level = route.get("evidence_level", "unknown")
    route_persistence_mode = route.get("persistence_mode", "unknown")
    if route_task_kind == "unknown" or route_evidence_level == "unknown" or route_persistence_mode == "unknown":
        codes.append("RUNTIME_ROUTE_NOT_SELECTED")
    elif (
        route_task_kind not in STANDARD_TASK_KIND
        or route_evidence_level not in STANDARD_EVIDENCE_LEVEL
        or route_persistence_mode not in STANDARD_PERSISTENCE_MODE
    ):
        codes.append("NON_STANDARD_RUNTIME_ROUTE")
    if route_task_kind == "change":
        if not has_any_key(run_state, CHANGE_DIFF_KEYS):
            codes.append("NO_EFFECTIVE_CODE_CHANGE")
        if not has_any_key(run_state, CHANGE_VERIFICATION_KEYS):
            codes.append("CHANGE_VERIFICATION_EVIDENCE_MISSING")
    if (
        is_assistant_audit_context(run_state, route)
        and not project_code_change_requested(run_state, route)
        and has_target_repo_edits(run_state)
    ):
        codes.append("ASSISTANT_AUDIT_TARGET_REPO_EDIT_FORBIDDEN")
    if has_unjustified_customer_visible_source_restriction(run_state):
        codes.append("CUSTOMER_VISIBLE_SOURCE_RESTRICTION_UNJUSTIFIED")
    if has_positive_skill_instruction_shape_missing(run_state):
        codes.append("POSITIVE_SKILL_INSTRUCTION_SHAPE_MISSING")
    if run_state.get("capability_decisions") and not ledger:
        codes.append("ASSISTANT_CAPABILITY_CLAIM_NOT_VERIFIED")
    invocations = ledger.get("invocations", ledger if isinstance(ledger, list) else [])
    called_without_recorded_output = [
        i.get("capability")
        for i in invocations
        if isinstance(i, dict)
        and i.get("invocation_status") == "called"
        and not i.get("output_artifacts")
        and not i.get("no_artifact_rationale")
    ]
    if called_without_recorded_output:
        codes.append("CAPABILITY_OUTPUT_NOT_RECORDED")
    called_outputs = [
        (i.get("capability"), a)
        for i in invocations
        if isinstance(i, dict) and i.get("invocation_status") == "called"
        for a in i.get("output_artifacts", [])
    ]
    consumed = {
        (c.get("capability"), c.get("source_artifact"))
        for c in consumption.get("consumptions", [])
        if isinstance(c, dict)
    } if isinstance(consumption, dict) else set()
    called_outputs_consumed = (
        not called_without_recorded_output
        and (all(pair in consumed for pair in called_outputs) if called_outputs else True)
    )
    if called_outputs and not called_outputs_consumed:
        codes.append("CAPABILITY_OUTPUT_NOT_CONSUMED")
    health_checked = bool(isinstance(health, dict) and health.get("capabilities"))
    capability_names = [d.get("capability", "") for d in run_state.get("capability_decisions", []) if isinstance(d, dict)]
    if any("codegraph" in c or "understand" in c for c in capability_names) and not health_checked:
        codes.append("CAPABILITY_HEALTH_NOT_CHECKED")
    target_repo_pollution = bool(policy.get("target_repo_write_allowed") and route.get("persistence_mode") in {"inline", "ephemeral"})
    if target_repo_pollution:
        codes.append("TARGET_REPO_ARTIFACT_POLLUTION")
    codes = sorted(set(codes))
    status = "blocked" if any(c in BLOCKER_GATES for c in codes) else ("warn" if codes else "pass")
    feedback = {
        "run_id": run_state.get("run_id") or route.get("run_id") or root.name,
        "overall_status": status,
        "feedback_owner": "codex_agent",
        "agent_review_required": True,
        "human_review_required": False,
        "route": {
            "task_kind": route_task_kind,
            "evidence_level": route_evidence_level,
            "persistence_mode": route_persistence_mode,
        },
        "capability_feedback": {
            "decisions_present": bool(run_state.get("capability_decisions")),
            "ledger_present": bool(ledger),
            "health_checked": health_checked,
            "called_outputs_consumed": called_outputs_consumed,
            "missing_required_capability_feedback": [],
        },
        "artifact_feedback": {
            "persistence_policy_present": bool(policy),
            "artifact_budget_status": "pass",
            "target_repo_pollution_risk": target_repo_pollution,
        },
        "rule_violations": [
            {"code": code, "severity": "blocker" if code in BLOCKER_GATES else "warn", "agent_action_required": "Codex must handle this before claiming completion."}
            for code in codes
        ],
        "darwin_self_healing": {
            "required": any(code in DARWIN_GATES for code in codes),
            "reason": ", ".join(code for code in codes if code in DARWIN_GATES),
            "status": "triggered" if any(code in DARWIN_GATES for code in codes) else "not_needed",
        },
        "assistant_response_contract": {
            "must_read_feedback_before_final_response": True,
            "must_report_overall_status": True,
            "must_report_blockers": True,
            "must_not_ask_user_to_audit_artifacts": True,
        },
        "summary": "Codex must inspect this feedback and report the conclusion. The user is not expected to audit raw Engineering Assistant artifacts.",
    }
    (root / "assistant-run-feedback.json").write_text(json.dumps(feedback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "assistant-run-feedback.summary.md").write_text(
        f"# Assistant Run Feedback\n\n- overall_status: {status}\n- blockers: {', '.join(codes) if codes else 'none'}\n- owner: codex_agent\n",
        encoding="utf-8",
    )
    closed_loop = build_closed_loop_outcome(root, run_state, route, feedback, codes)
    (root / "closed-loop-outcome.json").write_text(
        json.dumps(closed_loop, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "closed-loop-outcome.summary.md").write_text(
        "# Closed-loop Outcome\n\n"
        f"- overall_status: {status}\n"
        f"- distillation_required: {closed_loop['trajectory_distillation']['distillation_required']}\n"
        f"- score_status: {closed_loop['reinforcement_signal']['score_status']}\n"
        f"- independent_review_required: {closed_loop['independent_review']['independent_review_required']}\n",
        encoding="utf-8",
    )
    print("GENERATED_ASSISTANT_RUN_FEEDBACK")
    print("GENERATED_CLOSED_LOOP_OUTCOME")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
