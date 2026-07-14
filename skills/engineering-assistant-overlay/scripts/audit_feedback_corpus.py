#!/usr/bin/env python3
"""Audit historical Engineering Assistant feedback without rewriting evidence."""

import argparse
import json
from collections import Counter
from pathlib import Path


STANDARD_STATUS = {"pass", "warn", "blocked", "pending_evidence"}
STANDARD_TASK_KIND = {"context", "audit", "change", "release", "self_healing"}
STANDARD_EVIDENCE = {"inline", "lite", "standard", "formal"}
STANDARD_PERSISTENCE = {"inline", "ephemeral", "target_repo", "blocked"}
CLOSED_REQUIRED = {
    "execution_feedback",
    "trajectory_distillation",
    "compression_augmentation",
    "reinforcement_signal",
    "external_evidence",
    "independent_review",
    "project_memory",
    "next_run_context",
}


def load(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=100)
    args = parser.parse_args()

    feedback_paths = sorted(args.root.rglob("assistant-run-feedback.json"))
    closed_paths = sorted(args.root.rglob("closed-loop-outcome.json"))
    status_counts = Counter()
    route_counts = Counter()
    candidates = []
    parse_errors = 0
    pair_count = 0
    contract_complete = 0

    for path in feedback_paths:
        data = load(path)
        reasons = []
        if data is None:
            parse_errors += 1
            reasons.append("feedback_parse_error")
        else:
            status = data.get("overall_status", "missing")
            status_counts[status] += 1
            if status not in STANDARD_STATUS:
                reasons.append("nonstandard_or_missing_status")
            route = data.get("route")
            if not isinstance(route, dict):
                route = {}
                reasons.append("malformed_route")
            route_tuple = (
                route.get("task_kind", "missing"),
                route.get("evidence_level", "missing"),
                route.get("persistence_mode", "missing"),
            )
            route_counts["|".join(route_tuple)] += 1
            if not (
                route_tuple[0] in STANDARD_TASK_KIND
                and route_tuple[1] in STANDARD_EVIDENCE
                and route_tuple[2] in STANDARD_PERSISTENCE
            ):
                reasons.append("nonstandard_or_missing_route")
            contract = data.get("assistant_response_contract", {})
            if isinstance(contract, dict) and contract.get("must_read_feedback_before_final_response") is True and contract.get("must_not_ask_user_to_audit_artifacts") is True:
                contract_complete += 1
            else:
                reasons.append("feedback_consumption_contract_missing")
        if (path.parent / "closed-loop-outcome.json").exists():
            pair_count += 1
        else:
            reasons.append("closed_loop_pair_missing")
        if reasons and len(candidates) < args.candidate_limit:
            candidates.append({"path": str(path), "reasons": sorted(set(reasons)), "action": "normalize_copy_not_source"})

    closed_complete = 0
    closed_incomplete = 0
    closed_parse_errors = 0
    trajectory_present = 0
    compression_present = 0
    scored_reward = 0
    for path in closed_paths:
        data = load(path)
        if data is None:
            closed_parse_errors += 1
            continue
        if CLOSED_REQUIRED <= set(data):
            closed_complete += 1
        else:
            closed_incomplete += 1
        trajectory_present += bool(data.get("trajectory_distillation"))
        compression_present += bool(data.get("compression_augmentation"))
        scored_reward += data.get("reinforcement_signal", {}).get("score_status") == "scored"

    total = len(feedback_paths)
    report = {
        "schema_version": "1.0",
        "source_root": str(args.root),
        "source_mutated": False,
        "feedback": {
            "total": total,
            "parse_errors": parse_errors,
            "status_counts": dict(status_counts),
            "contract_complete": contract_complete,
            "paired_with_closed_loop": pair_count,
            "pair_rate": pair_count / total if total else 0,
            "route_counts": dict(route_counts),
        },
        "closed_loop": {
            "total": len(closed_paths),
            "parse_errors": closed_parse_errors,
            "complete_current_shape": closed_complete,
            "incomplete_shape": closed_incomplete,
            "trajectory_present": trajectory_present,
            "compression_present": compression_present,
            "scored_reward": scored_reward,
        },
        "normalization_candidates": candidates,
        "candidate_count_limited": len(candidates) == args.candidate_limit,
        "status": "pass" if total and pair_count == total and not candidates else "warn",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("AUDITED_ENGINEERING_ASSISTANT_FEEDBACK_CORPUS")
    print(f"feedback={total}")
    print(f"closed_loop={len(closed_paths)}")
    print(f"pair_rate={report['feedback']['pair_rate']:.4f}")
    print(f"status={report['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
