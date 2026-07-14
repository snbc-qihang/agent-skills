#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


RISK_LEVELS = {"L0_FAST", "L1_DIRECT", "L2_SHARED", "L3_CRITICAL"}
FORMAL_DESIGN_SUFFIXES = {".md", ".json", ".yaml", ".yml"}
PILEUP_SIGNALS = {
    "duplicated_business_rule",
    "unrelated_rule_concentration",
    "duplicated_state_transition",
    "domain_leakage",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def non_empty_string(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def non_empty_string_list(value) -> bool:
    return isinstance(value, list) and bool(value) and all(non_empty_string(item) for item in value)


def validate_code_design_decision(decision: dict) -> list[str]:
    errors = []
    if not isinstance(decision, dict):
        return ["code_design_decision must be an object"]
    if not non_empty_string(decision.get("changed_fact")):
        errors.append("changed_fact must be a non-empty string")
    owner = decision.get("owner_domain")
    if not isinstance(owner, dict) or not non_empty_string(owner.get("owner_path")) or not non_empty_string(owner.get("domain_boundary")):
        errors.append("owner_domain must include owner_path and domain_boundary")
    if not non_empty_string_list(decision.get("reuse_evidence")):
        errors.append("reuse_evidence must contain source-backed reuse findings")
    placement = decision.get("placement_decision")
    if not isinstance(placement, dict):
        errors.append("placement_decision must be an object")
    else:
        for field in ["target_module", "target_symbol", "responsibility"]:
            if not non_empty_string(placement.get(field)):
                errors.append(f"placement_decision.{field} must be a non-empty string")
        if not non_empty_string_list(placement.get("alternatives_rejected")):
            errors.append("placement_decision.alternatives_rejected must explain at least one rejected placement")
    if not non_empty_string_list(decision.get("protected_behavior")):
        errors.append("protected_behavior must contain at least one preserved behavior")
    seam = decision.get("test_seam")
    if not isinstance(seam, dict) or not non_empty_string(seam.get("public_interface")) or not non_empty_string_list(seam.get("tests")):
        errors.append("test_seam must include public_interface and behavior tests")
    abstraction = decision.get("abstraction_rationale")
    if not isinstance(abstraction, dict):
        errors.append("abstraction_rationale must be an object")
    else:
        if abstraction.get("decision") not in {"reuse_existing", "no_new_abstraction", "new_abstraction"}:
            errors.append("abstraction_rationale.decision is invalid")
        if not non_empty_string(abstraction.get("rationale")):
            errors.append("abstraction_rationale.rationale must be a non-empty string")
    return errors


def evaluate_pre_code(eligibility: dict, compact_design: dict | None = None) -> dict:
    errors = []
    if not isinstance(eligibility, dict):
        return {"decision": "block", "gate": "CODE_DESIGN_GATE_MISSING", "errors": ["eligibility must be an object"]}
    risk_level = eligibility.get("risk_level")
    if risk_level not in RISK_LEVELS:
        errors.append("risk_level must be L0_FAST, L1_DIRECT, L2_SHARED, or L3_CRITICAL")
    if eligibility.get("change_kind") not in {"local_only", "local_behavior", "shared_contract", "business_capability", "critical_business_flow"}:
        errors.append("change_kind is invalid")
    if not isinstance(eligibility.get("business_capability_change"), bool):
        errors.append("business_capability_change must be boolean")
    if not non_empty_string_list(eligibility.get("source_evidence")):
        errors.append("source_evidence must contain current repository evidence")
    design_evidence = eligibility.get("design_evidence")
    if not isinstance(design_evidence, dict):
        errors.append("design_evidence must be an object")

    if errors:
        return {"decision": "block", "gate": "CODE_DESIGN_GATE_MISSING", "errors": errors}

    selected_path = eligibility.get("selected_path")
    requested_decision = eligibility.get("decision")
    if risk_level == "L0_FAST":
        if selected_path == "direct" and requested_decision == "allow_code" and not eligibility["business_capability_change"]:
            return {"decision": "allow", "gate": None, "errors": []}
        return {
            "decision": "block",
            "gate": "CODE_DESIGN_GATE_MISSING",
            "errors": ["L0_FAST is only valid for a local-only non-business edit"],
        }

    if risk_level == "L1_DIRECT":
        compact_errors = validate_code_design_decision(compact_design)
        compact_ready = (
            selected_path == "compact_design"
            and requested_decision == "allow_code"
            and design_evidence.get("status") == "validated"
            and non_empty_string(design_evidence.get("compact_design_path"))
            and not eligibility["business_capability_change"]
            and not compact_errors
        )
        if compact_ready:
            return {"decision": "allow", "gate": None, "errors": []}
        return {
            "decision": "block",
            "gate": "CODE_DESIGN_GATE_MISSING",
            "errors": compact_errors or ["L1_DIRECT requires a validated compact design and cannot hide a business capability change"],
        }

    formal_path = design_evidence.get("formal_design_path", "")
    formal_ready = (
        selected_path == "formal_design"
        and requested_decision == "allow_code"
        and design_evidence.get("status") in {"approved", "final"}
        and non_empty_string(formal_path)
        and Path(formal_path).suffix.lower() in FORMAL_DESIGN_SUFFIXES
    )
    if formal_ready:
        return {"decision": "allow", "gate": None, "errors": []}
    return {
        "decision": "block",
        "gate": "DESIGN_BEFORE_CODE_GATE_MISSING",
        "errors": ["L2_SHARED and L3_CRITICAL require an approved or final formal design; TDD evidence is not design approval"],
    }


def evaluate_pileup(check: dict | None, business_capability_change: bool) -> dict:
    if not business_capability_change:
        if check is None:
            return {"decision": "pass", "gate": None, "errors": []}
    if not isinstance(check, dict):
        return {
            "decision": "block",
            "gate": "BUSINESS_CODE_PILEUP_UNCHECKED",
            "errors": ["business capability changes require business-code-pileup-check.json"],
        }
    errors = []
    if check.get("business_capability_change") is not business_capability_change:
        errors.append("business_capability_change does not match coding eligibility")
    if not non_empty_string_list(check.get("reviewed_files")):
        errors.append("reviewed_files must contain the final diff files")
    signals = check.get("signals")
    detected = []
    if not isinstance(signals, dict):
        errors.append("signals must be an object")
    else:
        missing = sorted(PILEUP_SIGNALS - set(signals))
        if missing:
            errors.append("signals missing: " + ", ".join(missing))
        for name in sorted(PILEUP_SIGNALS & set(signals)):
            signal = signals[name]
            if not isinstance(signal, dict) or not isinstance(signal.get("detected"), bool) or not isinstance(signal.get("evidence"), list):
                errors.append(f"signals.{name} must include detected and evidence")
                continue
            if signal["detected"] and not non_empty_string_list(signal["evidence"]):
                errors.append(f"signals.{name}.evidence is required when detected")
            if signal["detected"]:
                detected.append(name)
    if not non_empty_string(check.get("rationale")):
        errors.append("rationale must explain the placement outcome")
    if not isinstance(check.get("tests"), list):
        errors.append("tests must be an array")
    if errors:
        return {"decision": "block", "gate": "BUSINESS_CODE_PILEUP_UNCHECKED", "errors": errors}
    if detected:
        if check.get("decision") != "block" or check.get("placement_outcome") != "revise_design":
            return {
                "decision": "block",
                "gate": "BUSINESS_CODE_PILEUP_UNCHECKED",
                "errors": ["detected business pileup must block completion and revise design"],
            }
        return {"decision": "block", "gate": None, "errors": [], "detected_signals": detected}
    if check.get("decision") == "pass" and check.get("placement_outcome") in {"keep_current", "reuse_existing_owner"}:
        return {"decision": "pass", "gate": None, "errors": []}
    return {
        "decision": "block",
        "gate": "BUSINESS_CODE_PILEUP_UNCHECKED",
        "errors": ["a clean pileup review must explicitly pass with a supported placement outcome"],
    }


def run_eval_dataset(dataset: dict) -> dict:
    results = []
    for case in dataset.get("cases", []):
        pre = evaluate_pre_code(case.get("eligibility", {}), case.get("code_design_decision"))
        expected = case.get("expected", {})
        failures = []
        if pre["decision"] != expected.get("pre_code_decision"):
            failures.append(f"expected pre_code_decision={expected.get('pre_code_decision')} got {pre['decision']}")
        if "gate" in expected and pre.get("gate") != expected["gate"]:
            failures.append(f"expected gate={expected['gate']} got {pre.get('gate')}")
        post = None
        if "post_code_decision" in expected:
            post = evaluate_pileup(
                case.get("business_code_pileup_check"),
                bool(case.get("eligibility", {}).get("business_capability_change")),
            )
            if post["decision"] != expected["post_code_decision"]:
                failures.append(f"expected post_code_decision={expected['post_code_decision']} got {post['decision']}")
        results.append({"id": case.get("id"), "status": "pass" if not failures else "block", "pre_code": pre, "post_code": post, "failures": failures})
    passed = sum(1 for item in results if item["status"] == "pass")
    return {
        "status": "pass" if results and passed == len(results) else "block",
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Engineering Assistant design-before-code and business-code-pileup gates.")
    parser.add_argument("--eligibility")
    parser.add_argument("--code-design-decision")
    parser.add_argument("--pileup-check")
    parser.add_argument("--eval-dataset")
    args = parser.parse_args()
    if args.eval_dataset:
        result = run_eval_dataset(read_json(Path(args.eval_dataset)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "pass" else 1
    if not args.eligibility:
        parser.error("--eligibility or --eval-dataset is required")
    eligibility = read_json(Path(args.eligibility))
    compact = read_json(Path(args.code_design_decision)) if args.code_design_decision else None
    pre = evaluate_pre_code(eligibility, compact)
    post = None
    if args.pileup_check:
        post = evaluate_pileup(read_json(Path(args.pileup_check)), bool(eligibility.get("business_capability_change")))
    status = "pass" if pre["decision"] == "allow" and (post is None or post["decision"] == "pass") else "block"
    result = {"status": status, "pre_code": pre, "post_code": post}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
