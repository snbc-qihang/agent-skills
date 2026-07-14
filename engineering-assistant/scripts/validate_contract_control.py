#!/usr/bin/env python3
import json
import sys
from pathlib import Path

REQUIRED = ["artifacts/_control/current-task.json", "artifacts/_control/coding-eligibility.json", "artifacts/_control/code-design-decision.json", "artifacts/_control/design-contract.json", "artifacts/_control/implementation-contract.json", "artifacts/_control/quality-contract.json", "artifacts/_control/task-context.agent.md", "artifacts/_control/artifact-index.json"]
REQUIRED_IMPLEMENTATION_FIELDS = ["allowed_modules", "forbidden_modules", "required_files_or_patterns", "architecture_rules", "required_tests", "done_conditions", "technology_adoption_contract"]
REQUIRED_EXPECTATION_FIELDS = ["expected_interfaces", "expected_services", "expected_repositories_or_mappers"]
REQUIRED_QUALITY_FIELDS = ["required_commands", "required_evidence"]
PLACEHOLDER_TOKENS = {"待 code-development 阶段写入", "待确认", "todo", "tbd", "placeholder"}

def has_value(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return value is not None

def contains_placeholder(value) -> bool:
    text = json.dumps(value, ensure_ascii=False).lower()
    return any(token.lower() in text for token in PLACEHOLDER_TOKENS)

def blocking_open_questions(data: dict) -> list[str]:
    questions = data.get("questions") or data.get("open_questions") or []
    blocking = []
    for item in questions:
        if isinstance(item, dict) and (item.get("blocking") or item.get("severity") in {"blocker", "major"}) and item.get("status", "open") not in {"closed", "resolved", "answered"}:
            blocking.append(item.get("id") or item.get("question") or "blocking_open_question")
    return blocking

def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    errors = []
    missing = [item for item in REQUIRED if not (root / item).exists()]
    if missing:
        errors.append("missing control artifacts: " + ", ".join(missing))
    if errors:
        raise SystemExit("\n".join(errors))
    control = root / "artifacts/_control"
    design_decision = json.loads((control / "code-design-decision.json").read_text(encoding="utf-8"))
    implementation = json.loads((control / "implementation-contract.json").read_text(encoding="utf-8"))
    quality = json.loads((control / "quality-contract.json").read_text(encoding="utf-8"))
    open_questions = json.loads((control / "open-questions.json").read_text(encoding="utf-8")) if (control / "open-questions.json").exists() else {"questions": []}
    for field in ["changed_fact", "owner_domain", "reuse_evidence", "placement_decision", "protected_behavior", "test_seam", "abstraction_rationale"]:
        if not has_value(design_decision.get(field)):
            errors.append(f"code-design-decision.json missing or empty {field}")
    for field in REQUIRED_IMPLEMENTATION_FIELDS:
        if not has_value(implementation.get(field)):
            errors.append(f"implementation-contract.json missing or empty {field}")
    for field in REQUIRED_EXPECTATION_FIELDS:
        if not has_value(implementation.get(field)):
            errors.append(f"implementation-contract.json missing or empty {field}")
    if contains_placeholder(implementation):
        errors.append("implementation-contract.json contains placeholder text")
    commands = quality.get("required_commands", [])
    for field in REQUIRED_QUALITY_FIELDS:
        if not has_value(quality.get(field)):
            errors.append(f"quality-contract.json missing or empty {field}")
    if not commands:
        errors.append("quality-contract.json missing required_commands")
    for index, item in enumerate(commands):
        if not isinstance(item, dict) or not item.get("command"):
            errors.append(f"quality-contract.json required_commands[{index}] missing command")
        elif contains_placeholder(item.get("command")):
            errors.append(f"quality-contract.json required_commands[{index}] contains placeholder command")
    blocking = blocking_open_questions(open_questions)
    if blocking:
        errors.append("open-questions.json contains blocking open questions: " + ", ".join(blocking))
    if errors:
        raise SystemExit("\n".join(errors))
    print("ok")

if __name__ == "__main__":
    main()
