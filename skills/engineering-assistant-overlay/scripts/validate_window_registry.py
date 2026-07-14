#!/usr/bin/env python3
"""Validate multi-window coordination window-registry.json."""

import json
import sys
from pathlib import Path

VALID_STATUS = {
    "available",
    "planned",
    "running",
    "blocked",
    "waiting_for_input",
    "waiting_for_review",
    "missing",
    "inaccessible",
    "invalid_scope",
    "completed",
    "failed",
}

VALID_HEALTH_RESULTS = {
    "available",
    "missing",
    "inaccessible",
    "invalid_scope",
    "recreated",
}

BANNED_TERMS = {
    "子线程",
    "隐藏线程",
    "内部线程",
    "subthread",
    "hidden thread",
    "internal thread",
}

REQUIRED_USER_INPUTS = {
    "project_path",
    "target_branch",
    "business_goal",
    "in_scope",
    "out_of_scope",
    "acceptance_criteria",
    "test_environment",
    "window_creation_authorized",
    "write_permission",
    "worktree_allowed",
}

REQUIRED_TEST_WINDOWS = {
    "api_tester": "api-test-report.md",
    "module_flow_tester": "module-flow-test-report.md",
    "page_acceptance_tester": "page-acceptance-report.md",
}

REQUIRED_ANTI_REWORK_GATES = {
    "REQUIREMENT_FREEZE_REQUIRED",
    "API_CONTRACT_REQUIRED",
    "TRACEABILITY_MATRIX_REQUIRED",
    "DEVELOPER_CONFIRMATION_REQUIRED",
    "INDEPENDENT_TEST_REQUIRED",
    "SELF_REVIEW_FORBIDDEN",
    "REPEATED_FIX_DIAGNOSTIC_RESET_REQUIRED",
}

RECREATE_ONLY_WHEN = {
    "thread_not_found",
    "thread_inaccessible",
    "host_unavailable_and_handoff_failed",
    "window_role_or_module_scope_unrecoverable",
    "user_explicitly_requests_recreate",
}

NEVER_RECREATE_WHEN = {
    "window_is_idle",
    "window_has_old_context_but_same_role_and_module",
    "window_title_changed_but_threadId_is_valid",
}

AUTHORITATIVE_INPUTS = {
    "approved_requirements.md",
    "approved_business-rules.md",
    "approved_architecture-design.md",
    "module-task-brief.md",
    "allowed-files.json",
    "forbidden-scope.json",
}


def fail(message):
    print(f"INVALID_WINDOW_REGISTRY: {message}", file=sys.stderr)
    return 1


def non_empty_list(value):
    return isinstance(value, list) and bool(value)


def contains_banned_terms(value):
    text = json.dumps(value, ensure_ascii=False).lower()
    return [term for term in BANNED_TERMS if term.lower() in text]


def main():
    if len(sys.argv) != 2:
        return fail("usage: validate_window_registry.py window-registry.json")

    path = Path(sys.argv[1])
    data = json.loads(path.read_text(encoding="utf-8"))

    for key in [
        "registry_version",
        "capability_id",
        "run_id",
        "project",
        "user_required_inputs",
        "window_reuse_policy",
        "authoritative_input_policy",
        "controller_window",
        "windows",
        "test_windows",
        "anti_rework_gates",
        "gates",
    ]:
        if key not in data:
            return fail(f"{key} required")
    if data["capability_id"] != "multi_window_coordination":
        return fail("capability_id must be multi_window_coordination")

    banned = contains_banned_terms(data)
    if banned:
        return fail("banned user-facing terms: " + ",".join(sorted(banned)))

    user_required_inputs = data["user_required_inputs"]
    if not isinstance(user_required_inputs, dict):
        return fail("user_required_inputs must be an object")
    missing_inputs = sorted(REQUIRED_USER_INPUTS - set(user_required_inputs))
    if missing_inputs:
        return fail("user_required_inputs missing: " + ",".join(missing_inputs))
    empty_inputs = sorted(key for key in REQUIRED_USER_INPUTS if not user_required_inputs.get(key))
    if empty_inputs:
        return fail("user_required_inputs empty: " + ",".join(empty_inputs))

    reuse_policy = data["window_reuse_policy"]
    if not isinstance(reuse_policy, dict):
        return fail("window_reuse_policy must be an object")
    if reuse_policy.get("default") != "reuse_registered_window_first":
        return fail("window_reuse_policy.default must be reuse_registered_window_first")
    missing_recreate = sorted(RECREATE_ONLY_WHEN - set(reuse_policy.get("recreate_only_when", [])))
    if missing_recreate:
        return fail("window_reuse_policy.recreate_only_when missing: " + ",".join(missing_recreate))
    missing_never = sorted(NEVER_RECREATE_WHEN - set(reuse_policy.get("never_recreate_when", [])))
    if missing_never:
        return fail("window_reuse_policy.never_recreate_when missing: " + ",".join(missing_never))

    authoritative_input_policy = data["authoritative_input_policy"]
    if not isinstance(authoritative_input_policy, dict):
        return fail("authoritative_input_policy must be an object")
    if authoritative_input_policy.get("old_window_context_policy") != "historical_only":
        return fail("old_window_context_policy must be historical_only")
    if authoritative_input_policy.get("must_not_reuse_unverified_prior_conclusions") is not True:
        return fail("must_not_reuse_unverified_prior_conclusions must be true")
    missing_authoritative_inputs = sorted(AUTHORITATIVE_INPUTS - set(authoritative_input_policy.get("inputs", [])))
    if missing_authoritative_inputs:
        return fail("authoritative_input_policy.inputs missing: " + ",".join(missing_authoritative_inputs))

    controller = data["controller_window"]
    for key in ["threadId", "name", "role", "responsibilities"]:
        if key not in controller:
            return fail(f"controller_window missing {key}")
    if controller["role"] != "controller":
        return fail("controller_window.role must be controller")
    if not controller["threadId"] or not controller["name"]:
        return fail("controller_window threadId and name required")
    if not non_empty_list(controller["responsibilities"]):
        return fail("controller_window responsibilities must be non-empty")

    windows = data["windows"]
    if not non_empty_list(windows):
        return fail("windows must be non-empty")

    names = set()
    thread_ids = set()
    window_keys = set()
    window_roles = set()
    window_names = set()
    for index, window in enumerate(windows):
        for key in [
            "window_key",
            "threadId",
            "name",
            "role",
            "project",
            "module_id",
            "responsibility_key",
            "module_scope",
            "responsibilities",
            "may_edit_code",
            "reuse_policy",
            "last_health_check",
            "replacement",
            "status",
        ]:
            if key not in window:
                return fail(f"window {index} missing {key}")
        if not window["threadId"] or not window["name"]:
            return fail(f"window {index} threadId and name required")
        if window["window_key"] in window_keys:
            return fail(f"window {index} duplicate window_key")
        if window["threadId"] in thread_ids:
            return fail(f"window {index} duplicate threadId")
        if window["name"] in names:
            return fail(f"window {index} duplicate name")
        expected_window_key = f"{window['project']}:{window['module_id']}:{window['role']}:{window['responsibility_key']}"
        if window["window_key"] != expected_window_key:
            return fail(f"window {index} window_key must be {expected_window_key}")
        if window["reuse_policy"] != "reuse_registered_window_first":
            return fail(f"window {index} reuse_policy must be reuse_registered_window_first")
        health = window["last_health_check"]
        if not isinstance(health, dict) or not health.get("checked_at") or health.get("result") not in VALID_HEALTH_RESULTS:
            return fail(f"window {index} invalid last_health_check")
        replacement = window["replacement"]
        if not isinstance(replacement, dict) or "replaced" not in replacement:
            return fail(f"window {index} invalid replacement")
        if replacement["replaced"] not in {True, False}:
            return fail(f"window {index} replacement.replaced must be boolean")
        if replacement["replaced"]:
            if not replacement.get("previous_threadId"):
                return fail(f"window {index} replacement.previous_threadId required")
            if replacement.get("reason") not in RECREATE_ONLY_WHEN:
                return fail(f"window {index} invalid replacement.reason")
        thread_ids.add(window["threadId"])
        names.add(window["name"])
        window_keys.add(window["window_key"])
        window_roles.add(window["role"])
        window_names.add(window["name"])
        if not non_empty_list(window["responsibilities"]):
            return fail(f"window {index} responsibilities must be non-empty")
        if window["status"] not in VALID_STATUS:
            return fail(f"window {index} invalid status")
        if window["may_edit_code"] not in {True, False}:
            return fail(f"window {index} may_edit_code must be boolean")

        if window["may_edit_code"]:
            for key in ["isolation", "reviewer_window", "test_window"]:
                if key not in window:
                    return fail(f"write window {index} missing {key}")
            isolation = window["isolation"]
            if not isinstance(isolation, dict) or not isolation.get("mode"):
                return fail(f"write window {index} isolation.mode required")
            if window["reviewer_window"] in {window["name"], window["threadId"]}:
                return fail(f"write window {index} cannot review itself")
            if window["test_window"] in {window["name"], window["threadId"]}:
                return fail(f"write window {index} cannot test itself")

    test_windows = data["test_windows"]
    if not non_empty_list(test_windows):
        return fail("test_windows must be non-empty")
    test_window_roles = set()
    for index, test_window in enumerate(test_windows):
        for key in ["role", "name", "window_key", "output"]:
            if key not in test_window:
                return fail(f"test_window {index} missing {key}")
        role = test_window["role"]
        test_window_roles.add(role)
        expected_output = REQUIRED_TEST_WINDOWS.get(role)
        if expected_output and test_window["output"] != expected_output:
            return fail(f"test_window {index} output must be {expected_output}")
        if test_window["name"] not in window_names:
            return fail(f"test_window {index} must be registered in windows")
        if test_window["window_key"] not in window_keys:
            return fail(f"test_window {index} window_key must be registered in windows")

    missing_test_roles = sorted(set(REQUIRED_TEST_WINDOWS) - test_window_roles)
    if missing_test_roles:
        return fail("missing test window roles: " + ",".join(missing_test_roles))
    missing_registered_test_roles = sorted(set(REQUIRED_TEST_WINDOWS) - window_roles)
    if missing_registered_test_roles:
        return fail("test roles missing from windows: " + ",".join(missing_registered_test_roles))

    anti_rework_gates = set(data["anti_rework_gates"])
    missing_anti_rework = sorted(REQUIRED_ANTI_REWORK_GATES - anti_rework_gates)
    if missing_anti_rework:
        return fail("missing anti_rework_gates: " + ",".join(missing_anti_rework))

    gates = set(data["gates"])
    required_gates = {
        "EXPLICIT_WINDOW_CREATION_REQUIRED",
        "REQUIRED_INFORMATION_REQUESTS_MISSING",
        "WINDOW_REGISTRY_MISSING",
        "WINDOW_SCOPE_UNCLASSIFIED",
        "WINDOW_NAME_MISSING",
        "BUSINESS_REVIEW_PENDING",
        "DESIGN_REVIEW_REQUIRED",
        "REQUIREMENT_FREEZE_REQUIRED",
        "API_CONTRACT_REQUIRED",
        "TRACEABILITY_MATRIX_REQUIRED",
        "DEVELOPER_CONFIRMATION_REQUIRED",
        "INDEPENDENT_TEST_REQUIRED",
        "SELF_REVIEW_FORBIDDEN",
        "MULTI_WINDOW_FILE_CONFLICT_UNCHECKED",
        "MULTI_WINDOW_PARALLEL_DISPATCH_SKIPPED",
        "WORKER_WINDOW_OUTPUT_NOT_CONSUMED",
        "REPEATED_FIX_DIAGNOSTIC_RESET_REQUIRED",
        "WINDOW_REGISTRY_REUSE_SKIPPED",
        "WINDOW_REPLACEMENT_NOT_RECORDED",
        "STALE_WINDOW_CONTEXT_USED_AS_FACT",
    }
    missing = sorted(required_gates - gates)
    if missing:
        return fail("missing gates: " + ",".join(missing))

    print("VALID_WINDOW_REGISTRY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
