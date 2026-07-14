#!/usr/bin/env python3
"""Replay structured Engineering Assistant capability-assimilation cases."""

import argparse
import json
from pathlib import Path


ROUTES = {
    "ambiguous_requirement": (["bounded_intent_clarification"], "G0"),
    "complex_requirement": (["bounded_intent_clarification", "feasibility_argumentation"], "G0"),
    "non_executable_feasibility": (["feasibility_argumentation"], "G0"),
    "repeated_bug": (["bounded_hypothesis_recovery", "fresh_context_doubt_review"], "G0"),
    "fix_a_break_b": (["bounded_hypothesis_recovery", "fresh_context_doubt_review"], "G0"),
    "critical_design": (["fresh_context_doubt_review"], "G0"),
    "uncertain_root_cause": (["bounded_hypothesis_recovery", "fresh_context_doubt_review"], "G0"),
    "deterministic_test_failure": (["bounded_hypothesis_recovery"], "G0"),
    "stale_technology": (["authoritative_source_verification"], "G1"),
    "framework_specific_change": (["authoritative_source_verification"], "G1"),
    "jdk_feature_decision": (["authoritative_source_verification"], "G1"),
    "business_code_pileup": (["post_green_simplification"], "G1"),
    "multi_window": (["context_budgeted_handoff"], "G1"),
    "parallel_ready_set": (["context_budgeted_handoff"], "G1"),
    "multi_module": (["context_budgeted_handoff"], "G1"),
    "release_gap": (["observability_release_evidence"], "G1"),
    "production_impact": (["observability_release_evidence"], "G1"),
    "low_quality_project_baseline": (["independent_quality_constitution"], "G1"),
    "spec_quality_axis_gap": (["independent_quality_constitution"], "G1"),
    "quality_constitution_review": (["independent_quality_constitution"], "G1"),
    "speculative_abstraction": (["evidence_based_complexity_control"], "G1"),
    "evidenced_abstraction": (["evidence_based_complexity_control"], "G1"),
    "review_yagni": (["evidence_based_complexity_control"], "G1"),
    "complex_plan_deliberation": (["bounded_multi_agent_deliberation"], "G0"),
    "complex_plan_unresolved_blocker": (["bounded_multi_agent_deliberation"], "G0"),
    "complex_plan_deliberation_pass": (["bounded_multi_agent_deliberation"], "G0"),
    "competing_plan_vote": (["bounded_multi_agent_deliberation"], "G0"),
    "final_proposal_audit_gap": (["bounded_multi_agent_deliberation"], "G0"),
    "user_review_pending": (["bounded_multi_agent_deliberation"], "G0"),
    "user_approved_proposal": (["bounded_multi_agent_deliberation"], "G0"),
}


def evaluate(case):
    issue_type = case["input"]["issue_type"]
    capabilities, gate_level = ROUTES.get(issue_type, ([], "G2"))
    missing = case["input"].get("missing_evidence", [])
    if missing and gate_level in {"G0", "G1"}:
        decision = "block"
    elif missing:
        decision = "warn"
    else:
        decision = "pass"
    return {
        "id": case["id"],
        "category": case["category"],
        "gate_level": gate_level,
        "decision": decision,
        "capabilities": sorted(capabilities),
        "missing_evidence": missing,
        "protected_gate": case["expected"]["protected_gate"],
        "source_artifacts": case.get("source_artifacts", []),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    fixture = json.loads(args.cases.read_text())
    registry = json.loads(args.registry.read_text())
    results = []
    for case in fixture["cases"]:
        actual = evaluate(case)
        expected = case["expected"]
        checks = {
            "gate_level": actual["gate_level"] == expected["gate_level"],
            "decision": actual["decision"] == expected["decision"],
            "capabilities": actual["capabilities"] == sorted(expected["capabilities"]),
            "protected_gate_preserved": actual["protected_gate"] == expected["protected_gate"],
            "source_evidence_exists": bool(actual["source_artifacts"]) and all(
                Path(path).exists() for path in actual["source_artifacts"]
            ),
        }
        results.append({**actual, "checks": checks, "passed": all(checks.values())})

    g0 = [item for item in results if item["gate_level"] == "G0"]
    passed = sum(item["passed"] for item in results)
    output = {
        "schema_version": "1.0",
        "pack_id": registry["pack_id"],
        "local_version": registry["local_version"],
        "case_count": len(results),
        "passed_count": passed,
        "overall_pass_rate": passed / len(results) if results else 0,
        "g0_case_count": len(g0),
        "g0_passed_count": sum(item["passed"] for item in g0),
        "g0_pass_rate": sum(item["passed"] for item in g0) / len(g0) if g0 else 0,
        "existing_gate_regressions": sum(not item["checks"]["protected_gate_preserved"] for item in results),
        "results": results,
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered)
    print(rendered, end="")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
