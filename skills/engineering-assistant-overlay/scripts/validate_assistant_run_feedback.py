#!/usr/bin/env python3
"""Validate Engineering Assistant overlay assistant-run-feedback.json."""

import json
import sys
from pathlib import Path

VALID_STATUS = {"pass", "warn", "blocked", "pending_evidence"}
VALID_SEVERITY = {"advisory", "warn", "blocker"}
VALID_DARWIN = {"not_needed", "triggered", "blocked", "pending_evidence"}
VALID_TASK_KIND = {"context", "audit", "change", "release", "self_healing", "unknown"}
VALID_EVIDENCE_LEVEL = {"inline", "lite", "standard", "formal", "unknown"}
VALID_PERSISTENCE_MODE = {"inline", "ephemeral", "target_repo", "blocked", "unknown"}
STANDARD_TASK_KIND = {"context", "audit", "change", "release", "self_healing"}
STANDARD_EVIDENCE_LEVEL = {"inline", "lite", "standard", "formal"}
STANDARD_PERSISTENCE_MODE = {"inline", "ephemeral", "target_repo", "blocked"}


def fail(message):
    print(f"INVALID_ASSISTANT_RUN_FEEDBACK: {message}", file=sys.stderr)
    return 1


def main():
    if len(sys.argv) != 2:
        return fail("usage: validate_assistant_run_feedback.py assistant-run-feedback.json")
    try:
        data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except Exception as exc:
        return fail(f"cannot read JSON: {exc}")
    required = [
        "run_id", "overall_status", "feedback_owner", "agent_review_required",
        "human_review_required", "route", "capability_feedback", "artifact_feedback",
        "rule_violations", "darwin_self_healing", "assistant_response_contract", "summary"
    ]
    for key in required:
        if key not in data:
            return fail(f"missing {key}")
    if data["overall_status"] not in VALID_STATUS:
        return fail("invalid overall_status")
    if data["feedback_owner"] != "codex_agent":
        return fail("feedback_owner must be codex_agent")
    if data["agent_review_required"] is not True:
        return fail("agent_review_required must be true")
    route = data["route"]
    for key in ["task_kind", "evidence_level", "persistence_mode"]:
        if not isinstance(route, dict) or not route.get(key):
            return fail(f"route.{key} missing")
    if route["task_kind"] not in VALID_TASK_KIND:
        return fail("route.task_kind invalid")
    if route["evidence_level"] not in VALID_EVIDENCE_LEVEL:
        return fail("route.evidence_level invalid")
    if route["persistence_mode"] not in VALID_PERSISTENCE_MODE:
        return fail("route.persistence_mode invalid")
    standard_route = (
        route["task_kind"] in STANDARD_TASK_KIND
        and route["evidence_level"] in STANDARD_EVIDENCE_LEVEL
        and route["persistence_mode"] in STANDARD_PERSISTENCE_MODE
    )
    violation_codes = {
        item.get("code")
        for item in data.get("rule_violations", [])
        if isinstance(item, dict)
    }
    if not standard_route and data["overall_status"] == "pass":
        return fail("non-standard route cannot have overall_status=pass")
    if not standard_route and not ({"RUNTIME_ROUTE_NOT_SELECTED", "NON_STANDARD_RUNTIME_ROUTE"} & violation_codes):
        return fail("non-standard route requires route violation")
    capability = data["capability_feedback"]
    for key in ["decisions_present", "ledger_present", "health_checked", "called_outputs_consumed"]:
        if not isinstance(capability.get(key), bool):
            return fail(f"capability_feedback.{key} must be boolean")
    artifact = data["artifact_feedback"]
    if artifact.get("artifact_budget_status") not in VALID_STATUS:
        return fail("artifact_budget_status invalid")
    for item in data["rule_violations"]:
        if not item.get("code") or item.get("severity") not in VALID_SEVERITY or not item.get("agent_action_required"):
            return fail("invalid rule violation")
    darwin = data["darwin_self_healing"]
    if darwin.get("status") not in VALID_DARWIN:
        return fail("invalid darwin status")
    contract = data["assistant_response_contract"]
    for key in [
        "must_read_feedback_before_final_response",
        "must_report_overall_status",
        "must_report_blockers",
        "must_not_ask_user_to_audit_artifacts",
    ]:
        if contract.get(key) is not True:
            return fail(f"assistant_response_contract.{key} must be true")
    print("VALID_ASSISTANT_RUN_FEEDBACK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
