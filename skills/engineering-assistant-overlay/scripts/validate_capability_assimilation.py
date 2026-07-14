#!/usr/bin/env python3
"""Validate a native Engineering Assistant capability assimilation release."""

import argparse
import json
import re
from pathlib import Path


SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
DECISIONS = {"absorbed", "covered", "deferred", "rejected_router_conflict"}
GATE_LEVELS = {"G0", "G1", "G2"}
SYSTEM_OWNERS = {
    "engineering-assistant",
    "engineering-assistant-overlay",
    "engineering-assistant-council-integration",
}


def load(path):
    return json.loads(path.read_text())


def require(condition, code, errors):
    if not condition:
        errors.append(code)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("registry", type=Path)
    parser.add_argument("overlap_matrix", type=Path)
    parser.add_argument("acceptance_results", type=Path)
    parser.add_argument("--routing-registry", type=Path)
    parser.add_argument("--behavior-evidence", type=Path)
    args = parser.parse_args()

    registry = load(args.registry)
    matrix = load(args.overlap_matrix)
    acceptance = load(args.acceptance_results)
    errors = []

    require(registry.get("controller") == "engineering-assistant", "EXTERNAL_CAPABILITY_ROUTER_CONFLICT", errors)
    require(registry.get("gate_owner") == "engineering-assistant", "EXTERNAL_CAPABILITY_ROUTER_CONFLICT", errors)
    router = registry.get("router_policy", {})
    require(router.get("sole_entrypoint") == "engineering-assistant", "EXTERNAL_CAPABILITY_ROUTER_CONFLICT", errors)
    require(router.get("sole_gate_owner") == "engineering-assistant", "EXTERNAL_CAPABILITY_ROUTER_CONFLICT", errors)
    require(router.get("upstream_router_imported") is False, "EXTERNAL_CAPABILITY_ROUTER_CONFLICT", errors)
    require(router.get("upstream_commands_imported") is False, "EXTERNAL_CAPABILITY_ROUTER_CONFLICT", errors)
    require(registry.get("versioning", {}).get("mode") == "independent", "EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED", errors)
    require(registry.get("versioning", {}).get("upstream_commit_tracking") is False, "EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED", errors)
    require(bool(SEMVER.match(registry.get("local_version", ""))), "EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED", errors)

    capabilities = registry.get("capabilities", [])
    ids = [item.get("capability_id") for item in capabilities]
    require(len(ids) == len(set(ids)) and None not in ids, "EXTERNAL_CAPABILITY_GAP_NOT_PROVEN", errors)
    for item in capabilities:
        required_fields = ["source_skills", "native_owner", "gate_level", "trigger_issue_types", "completion_evidence", "stop_condition", "protected_existing_gates"]
        require(all(item.get(field) for field in required_fields), "EXTERNAL_CAPABILITY_GAP_NOT_PROVEN", errors)
        require(item.get("gate_level") in GATE_LEVELS, "EXTERNAL_CAPABILITY_GATE_LEVEL_MISSING", errors)

    contract = registry.get("acceptance_contract", {})
    expected_candidates = contract.get("audited_candidate_count")
    expected_cases = contract.get("acceptance_case_count")
    expected_behavior_cases = contract.get("behavior_case_count")
    minimum_pass_rate = contract.get("minimum_overall_pass_rate", 0.8)
    maximum_regressions = contract.get("maximum_existing_gate_regressions", 0)

    decisions = matrix.get("decisions", [])
    sources = [item.get("source_skill") for item in decisions]
    require(isinstance(expected_candidates, int) and expected_candidates > 0, "EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED", errors)
    require(matrix.get("audited_candidate_count") == expected_candidates and len(decisions) == expected_candidates, "EXTERNAL_CAPABILITY_OVERLAP_UNCLASSIFIED", errors)
    require(len(sources) == len(set(sources)) and None not in sources, "EXTERNAL_CAPABILITY_OVERLAP_UNCLASSIFIED", errors)
    require(all(item.get("decision") in DECISIONS and item.get("reason") and item.get("owner_skill_ids") for item in decisions), "EXTERNAL_CAPABILITY_OVERLAP_UNCLASSIFIED", errors)
    if args.routing_registry:
        routing_registry = load(args.routing_registry)
        valid_owners = SYSTEM_OWNERS | {item.get("skill_id") for item in routing_registry.get("skills", [])}
        for item in decisions:
            require(all(owner in valid_owners for owner in item.get("owner_skill_ids", [])), "EXTERNAL_CAPABILITY_OWNER_INVALID", errors)
    router_rows = [item for item in decisions if item.get("source_skill") == "using-agent-skills"]
    require(len(router_rows) == 1 and router_rows[0].get("decision") == "rejected_router_conflict", "EXTERNAL_CAPABILITY_ROUTER_CONFLICT", errors)
    for item in decisions:
        if item.get("decision") == "absorbed":
            require(bool(item.get("target_capabilities")), "EXTERNAL_CAPABILITY_GAP_NOT_PROVEN", errors)
            require(all(target in ids for target in item.get("target_capabilities", [])), "EXTERNAL_CAPABILITY_GAP_NOT_PROVEN", errors)

    require(acceptance.get("pack_id") == registry.get("pack_id"), "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED", errors)
    require(acceptance.get("local_version") == registry.get("local_version"), "EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED", errors)
    require(isinstance(expected_cases, int) and expected_cases > 0, "EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED", errors)
    require(acceptance.get("case_count") == expected_cases, "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED", errors)
    require(acceptance.get("g0_pass_rate") == 1, "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED", errors)
    require(acceptance.get("overall_pass_rate", 0) >= minimum_pass_rate, "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED", errors)
    require(acceptance.get("existing_gate_regressions") <= maximum_regressions, "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED", errors)
    if args.behavior_evidence:
        behavior = load(args.behavior_evidence)
        require(behavior.get("passed") is True, "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED", errors)
        require(isinstance(expected_behavior_cases, int) and expected_behavior_cases > 0, "EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED", errors)
        require(behavior.get("case_count") == expected_behavior_cases and behavior.get("passed_count") == expected_behavior_cases, "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED", errors)
        require(bool(behavior.get("source_sha256", {}).get("route_skill.py")), "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED", errors)
    else:
        require(False, "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED", errors)

    if errors:
        print("INVALID_ENGINEERING_ASSISTANT_CAPABILITY_ASSIMILATION")
        for error in sorted(set(errors)):
            print(error)
        return 1
    print("VALID_ENGINEERING_ASSISTANT_CAPABILITY_ASSIMILATION")
    print(f"pack_id={registry['pack_id']}")
    print(f"local_version={registry['local_version']}")
    print(f"absorbed_capabilities={len(capabilities)}")
    print(f"audited_candidates={len(decisions)}")
    print(f"acceptance={acceptance['passed_count']}/{acceptance['case_count']}")
    print(f"g0={acceptance['g0_passed_count']}/{acceptance['g0_case_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
