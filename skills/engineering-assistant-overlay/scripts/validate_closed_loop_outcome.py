#!/usr/bin/env python3
"""Validate Engineering Assistant closed-loop-outcome.json."""

import json
import sys
from pathlib import Path

VALID_SCORE_STATUS = {"scored", "pending_metrics"}
VALID_EXTERNAL_STATUS = {"available", "not_configured", "not_checked", "pending_external_connector"}
VALID_TASK_KIND = {"context", "audit", "change", "release", "self_healing", "unknown"}
VALID_EVIDENCE_LEVEL = {"inline", "lite", "standard", "formal", "unknown"}
VALID_PERSISTENCE_MODE = {"inline", "ephemeral", "target_repo", "blocked", "unknown"}


def fail(message):
    print(f"INVALID_CLOSED_LOOP_OUTCOME: {message}", file=sys.stderr)
    return 1


def require_dict(data, key):
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be object")
    return value


def main():
    if len(sys.argv) != 2:
        return fail("usage: validate_closed_loop_outcome.py closed-loop-outcome.json")
    try:
        data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except Exception as exc:
        return fail(f"cannot read JSON: {exc}")

    required = [
        "run_id",
        "feedback_owner",
        "loop_contract_version",
        "route",
        "execution_feedback",
        "trajectory_distillation",
        "compression_augmentation",
        "reinforcement_signal",
        "external_evidence",
        "independent_review",
        "project_memory",
        "next_run_context",
    ]
    for key in required:
        if key not in data:
            return fail(f"missing {key}")
    if data["feedback_owner"] != "codex_agent":
        return fail("feedback_owner must be codex_agent")

    try:
        route = require_dict(data, "route")
        execution = require_dict(data, "execution_feedback")
        distillation = require_dict(data, "trajectory_distillation")
        compression = require_dict(data, "compression_augmentation")
        reward = require_dict(data, "reinforcement_signal")
        external = require_dict(data, "external_evidence")
        independent = require_dict(data, "independent_review")
        project_memory = require_dict(data, "project_memory")
        next_run = require_dict(data, "next_run_context")
    except ValueError as exc:
        return fail(str(exc))

    if route.get("task_kind") not in VALID_TASK_KIND:
        return fail("route.task_kind invalid")
    if route.get("evidence_level") not in VALID_EVIDENCE_LEVEL:
        return fail("route.evidence_level invalid")
    if route.get("persistence_mode") not in VALID_PERSISTENCE_MODE:
        return fail("route.persistence_mode invalid")

    for key in ["first_pass_success", "repeated_fix", "introduced_regression"]:
        if key not in execution:
            return fail(f"execution_feedback.{key} missing")
    if not isinstance(execution.get("fix_attempt_count"), int):
        return fail("execution_feedback.fix_attempt_count must be integer")
    if not isinstance(execution.get("user_correction_count"), int):
        return fail("execution_feedback.user_correction_count must be integer")

    if not isinstance(distillation.get("samples"), list):
        return fail("trajectory_distillation.samples must be array")
    if not isinstance(compression.get("candidate_gate_changes"), list):
        return fail("compression_augmentation.candidate_gate_changes must be array")

    if reward.get("score_status") not in VALID_SCORE_STATUS:
        return fail("reinforcement_signal.score_status invalid")
    if reward.get("score_status") == "scored" and not isinstance(reward.get("task_score"), (int, float)):
        return fail("reinforcement_signal.task_score required when scored")
    if reward.get("score_status") == "pending_metrics" and not isinstance(reward.get("missing_metric_sources"), list):
        return fail("reinforcement_signal.missing_metric_sources required when pending_metrics")

    for key, value in external.items():
        if value not in VALID_EXTERNAL_STATUS:
            return fail(f"external_evidence.{key} invalid")

    for key in ["developer_verified", "independent_reviewed", "independent_review_required"]:
        if not isinstance(independent.get(key), bool):
            return fail(f"independent_review.{key} must be boolean")
    if not isinstance(project_memory.get("candidate_updates"), list):
        return fail("project_memory.candidate_updates must be array")
    if not isinstance(next_run.get("must_consume_artifacts"), list):
        return fail("next_run_context.must_consume_artifacts must be array")

    print("VALID_CLOSED_LOOP_OUTCOME")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
