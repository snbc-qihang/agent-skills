#!/usr/bin/env python3
import argparse
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, read_json, update_artifact_index, validate_target_project_root, write_json

REQUIRED_CONTROL_FILES = [
    "current-task.json",
    "artifact-index.json",
    "coding-eligibility.json",
    "code-design-decision.json",
    "design-contract.json",
    "implementation-contract.json",
    "quality-contract.json",
    "task-context.agent.md",
]

def blocking_open_questions(data: dict) -> list[str]:
    questions = data.get("questions") or data.get("open_questions") or []
    blocking = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        status = item.get("status", "open")
        if (item.get("blocking") or item.get("severity") in {"blocker", "major"}) and status not in {"closed", "resolved", "answered"}:
            blocking.append(item.get("id") or item.get("question") or "blocking_open_question")
    return blocking

def add(finding_list: list[dict], severity: str, reason: str, **extra):
    item = {"severity": severity, "reason": reason}
    item.update(extra)
    finding_list.append(item)

def main():
    parser = argparse.ArgumentParser(description="Validate task control-plane health before implementation or review.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--task-type", default="code-development")
    parser.add_argument("--output", default="artifacts/_control/control-health-report.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    control = ensure_control_dir(root)
    findings = []
    for name in REQUIRED_CONTROL_FILES:
        if not (control / name).exists():
            add(findings, "blocker", "missing control artifact", artifact=name)
    implementation = read_json(control / "implementation-contract.json", {})
    quality = read_json(control / "quality-contract.json", {})
    design_decision = read_json(control / "code-design-decision.json", {})
    if not design_decision.get("placement_decision") or not design_decision.get("test_seam"):
        add(findings, "blocker", "invalid code design decision", artifact="code-design-decision.json")
    if not implementation.get("technology_adoption_contract"):
        add(findings, "blocker", "missing technology_adoption_contract", artifact="implementation-contract.json")
    if not quality.get("required_evidence"):
        add(findings, "blocker", "missing required_evidence", artifact="quality-contract.json")
    rule_pack_path = root / "artifacts/rule-governance/task-rule-packs" / f"{args.task_type}.json"
    rule_pack = read_json(rule_pack_path, {})
    if not rule_pack_path.exists() or not rule_pack.get("rule_count") or not rule_pack.get("rules"):
        add(findings, "blocker", "missing task rule pack", artifact=str(rule_pack_path.relative_to(root)))
    open_questions = read_json(control / "open-questions.json", {"questions": []})
    blocking = blocking_open_questions(open_questions)
    if blocking:
        add(findings, "blocker", "blocking open question", questions=blocking)
    status = "pass" if not any(item["severity"] == "blocker" for item in findings) else "block"
    output = root / args.output
    report = {"status": status, "task_type": args.task_type, "findings": findings, "generated_at": now_iso()}
    write_json(output, report)
    update_artifact_index(root, output.name, output, "json", "validate_control_health")
    print(output)
    if status == "block":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
