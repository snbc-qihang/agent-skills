#!/usr/bin/env python3
"""Classify Engineering Assistant run artifacts for L4-entry evidence."""

import json
import sys
from pathlib import Path

STANDARD_TASK_KIND = {"context", "audit", "change", "release", "self_healing"}
STANDARD_EVIDENCE_LEVEL = {"inline", "lite", "standard", "formal"}
STANDARD_PERSISTENCE_MODE = {"inline", "ephemeral", "target_repo", "blocked"}
REQUIRED_FILES = {
    "run_state.json",
    "runtime-route-decision.json",
    "artifact-persistence-policy.json",
    "capability-invocation-ledger.json",
    "capability-health.json",
    "capability-output-consumption.json",
    "assistant-run-feedback.json",
    "assistant-run-feedback.summary.md",
}

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


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def has_any_key(value, keys):
    if isinstance(value, dict):
        if any(key in value and value.get(key) for key in keys):
            return True
        return any(has_any_key(item, keys) for item in value.values())
    if isinstance(value, list):
        return any(has_any_key(item, keys) for item in value)
    return False


def normalize_route(value):
    if isinstance(value, dict):
        return value, []
    if value in (None, ""):
        return {}, ["missing route"]
    return {}, [f"legacy route type {type(value).__name__}: {value!r}"]


def classify(root: Path):
    feedback = root / "assistant-run-feedback.json"
    if not feedback.exists():
        return "not_evidence", ["missing assistant-run-feedback.json"]
    data = load_json(feedback, {})
    route, route_reasons = normalize_route(data.get("route", {}))
    missing = sorted(name for name in REQUIRED_FILES if not (root / name).exists())
    route_ok = (
        route.get("task_kind") in STANDARD_TASK_KIND
        and route.get("evidence_level") in STANDARD_EVIDENCE_LEVEL
        and route.get("persistence_mode") in STANDARD_PERSISTENCE_MODE
    )
    if data.get("overall_status") != "pass":
        return "failed_or_blocked", [f"overall_status={data.get('overall_status')}"]
    if missing:
        return "weak", ["missing files: " + ", ".join(missing)]
    if not route_ok:
        reasons = route_reasons + [f"non-standard route: {route}"]
        return "partial", reasons
    capability_feedback = data.get("capability_feedback", {})
    if capability_feedback.get("ledger_present") is not True:
        return "partial", ["capability ledger not confirmed"]
    if capability_feedback.get("health_checked") is not True:
        return "partial", ["capability health not confirmed"]
    if capability_feedback.get("called_outputs_consumed") is not True:
        return "partial", ["called capability outputs not confirmed consumed"]
    ledger = load_json(root / "capability-invocation-ledger.json", {})
    consumption = load_json(root / "capability-output-consumption.json", {})
    invocations = ledger.get("invocations", ledger if isinstance(ledger, list) else [])
    consumptions = consumption.get("consumptions", []) if isinstance(consumption, dict) else []
    consumed = {
        (item.get("capability"), item.get("source_artifact"))
        for item in consumptions
        if isinstance(item, dict)
    }
    output_reasons = []
    for item in invocations:
        if not isinstance(item, dict) or item.get("invocation_status") != "called":
            continue
        capability = item.get("capability")
        artifacts = item.get("output_artifacts", [])
        if not artifacts and not item.get("no_artifact_rationale"):
            output_reasons.append(f"called capability has no recorded output: {capability}")
        for artifact in artifacts:
            if (capability, artifact) not in consumed:
                output_reasons.append(f"called output not consumed: {capability} -> {artifact}")
    if output_reasons:
        return "partial", output_reasons
    run_state = load_json(root / "run_state.json", {})
    if route.get("task_kind") == "change":
        if not has_any_key(run_state, CHANGE_DIFF_KEYS):
            return "partial", ["change run missing target-code diff evidence in run_state"]
        if not has_any_key(run_state, CHANGE_VERIFICATION_KEYS):
            return "partial", ["change run missing verification evidence in run_state"]
    return "strict_l4", []


def main():
    if len(sys.argv) != 2:
        print("usage: classify_l4_evidence.py /path/to/run-artifacts-root", file=sys.stderr)
        return 1
    root = Path(sys.argv[1])
    if not root.exists():
        print("INVALID_L4_EVIDENCE_ROOT: root does not exist", file=sys.stderr)
        return 1
    results = []
    for feedback in sorted(root.rglob("assistant-run-feedback.json")):
        run_root = feedback.parent
        label, reasons = classify(run_root)
        results.append({"root": str(run_root), "classification": label, "reasons": reasons})
    summary = {
        "strict_l4": sum(1 for item in results if item["classification"] == "strict_l4"),
        "partial": sum(1 for item in results if item["classification"] == "partial"),
        "weak": sum(1 for item in results if item["classification"] == "weak"),
        "failed_or_blocked": sum(1 for item in results if item["classification"] == "failed_or_blocked"),
        "not_evidence": sum(1 for item in results if item["classification"] == "not_evidence"),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
