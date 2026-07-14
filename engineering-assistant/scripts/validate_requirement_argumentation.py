#!/usr/bin/env python3
"""Validate bounded clarification and feasibility argumentation artifacts."""

import json
import sys
from pathlib import Path


EVIDENCE_FIELDS = {
    "architecture_and_code",
    "dependencies_and_reuse",
    "data_and_external_systems",
    "risks_and_rollback",
    "tests",
    "cost",
}
VERDICTS = {"executable", "executable_after_conditions", "not_executable"}


def fail(message: str) -> None:
    raise SystemExit(message)


def validate(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    clarity = data.get("clarity", {})
    required_clarity = {"objective", "target_user", "success_criteria", "constraints", "non_goals", "remaining_material_ambiguity", "questions_asked"}
    if not required_clarity <= set(clarity):
        fail(f"{path}: clarity fields missing")
    if not 0 <= clarity["questions_asked"] <= 6:
        fail(f"{path}: questions_asked must be 0..6")
    if clarity["remaining_material_ambiguity"] and data.get("verdict") == "executable":
        fail(f"{path}: ambiguous requirement cannot be executable")
    evidence = data.get("evidence", {})
    if data.get("risk_level") in {"L2_SHARED", "L3_CRITICAL"}:
        missing = EVIDENCE_FIELDS - {key for key, value in evidence.items() if isinstance(value, list) and value}
        if missing:
            fail(f"{path}: complex argumentation evidence missing: {sorted(missing)}")
    candidates = data.get("candidates", [])
    if not 1 <= len(candidates) <= 3:
        fail(f"{path}: candidates must contain 1..3 paths")
    verdict = data.get("verdict")
    if verdict not in VERDICTS:
        fail(f"{path}: invalid verdict")
    conditions = data.get("conditions", [])
    if verdict == "executable_after_conditions" and not conditions:
        fail(f"{path}: conditional verdict requires conditions")
    if verdict == "executable" and conditions:
        fail(f"{path}: executable verdict cannot have unmet conditions")
    if verdict == "not_executable" and data.get("selected_path") is not None:
        fail(f"{path}: not_executable cannot select an implementation path")
    if verdict != "not_executable" and not data.get("selected_path"):
        fail(f"{path}: executable verdict requires selected_path")
    print(f"VALID_REQUIREMENT_ARGUMENTATION {path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        fail("usage: validate_requirement_argumentation.py <artifact.json>")
    validate(Path(sys.argv[1]))
