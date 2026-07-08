#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from control_runtime import validate_target_project_root

SCHEMA_VERSION = "3.1.0"
PLACEHOLDER_TOKENS = ("待 code-development 阶段写入", "待确认", "todo", "tbd", "placeholder")
STANDARD_METADATA_FIELDS = {"document_number", "document_status", "retention_policy", "owner", "language", "canonical_path", "source_artifacts"}

CONTRACTS = {
    "current-task.json": {
        "required": {"schema_version", "task_id", "title", "language", "workflow_id", "status", "control_dir", "created_at"},
        "allowed": {"schema_version", "task_id", "title", "language", "workflow_id", "active_stage", "status", "control_dir", "created_at", "updated_at", "project_profile", "current_contracts", "supersedes_active_task", "previous_task", "next_action", "active_slice"},
    },
    "current-subtask.json": {
        "required": {"schema_version", "slice_id", "parent_task_id", "status", "control_artifacts", "updated_at"},
        "allowed": {"schema_version", "slice_id", "parent_task_id", "title", "kind", "status", "control_artifacts", "quality_status", "blockers", "browser_evidence", "next_required_action", "updated_at"},
    },
    "design-contract.json": {
        "required": {"schema_version", "task_id", "source_design", "source_checksum", "goals", "acceptance_criteria", "module_boundaries", "assumptions"},
        "allowed": {"schema_version", "task_id", "source_design", "source_checksum", "generated_at", "goals", "acceptance_criteria", "module_boundaries", "risks", "assumptions"} | STANDARD_METADATA_FIELDS,
    },
    "implementation-contract.json": {
        "required": {"schema_version", "task_id", "allowed_modules", "forbidden_modules", "required_files_or_patterns", "architecture_rules", "required_tests", "done_conditions", "expected_interfaces", "expected_services", "expected_repositories_or_mappers", "technology_adoption_contract"},
        "allowed": {"schema_version", "task_id", "allowed_modules", "forbidden_modules", "required_files_or_patterns", "architecture_rules", "required_tests", "done_conditions", "expected_interfaces", "expected_services", "expected_repositories_or_mappers", "technology_adoption_contract", "generated_at"} | STANDARD_METADATA_FIELDS,
        "non_empty": {"allowed_modules", "forbidden_modules", "architecture_rules", "required_tests", "done_conditions"},
    },
    "quality-contract.json": {
        "required": {"schema_version", "task_id", "required_commands", "required_evidence", "quality_gates", "repair_policy"},
        "allowed": {"schema_version", "task_id", "required_commands", "required_evidence", "quality_gates", "repair_policy", "generated_at"} | STANDARD_METADATA_FIELDS,
        "non_empty": {"required_commands", "required_evidence", "quality_gates"},
    },
}

OPTIONAL_CONTRACTS = {
    "quality-run-report.json": {
        "required": {"schema_version", "status", "summary", "results", "errors", "generated_at"},
        "allowed": {"schema_version", "status", "task_id", "summary", "results", "errors", "findings", "generated_at"},
    },
}

ACTIVE_SLICE_ALLOWED = {"schema_version", "slice_id", "parent_task_id", "title", "kind", "status", "quality_status", "control_artifacts", "blockers", "browser_evidence", "next_required_action", "updated_at"}
ACTIVE_SLICE_REQUIRED = {"schema_version", "slice_id", "parent_task_id", "status", "control_artifacts"}


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{path.name}: invalid json: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: expected object")
    return value


def is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def contains_placeholder(value) -> bool:
    text = json.dumps(value, ensure_ascii=False).lower() if not isinstance(value, str) else value.lower()
    return any(token.lower() in text for token in PLACEHOLDER_TOKENS)


def validate_shape(name: str, data: dict, spec: dict) -> list[str]:
    errors = []
    unknown = sorted(set(data) - spec["allowed"])
    if unknown:
        errors.append(f"{name}: unknown fields {unknown}")
    missing = sorted(field for field in spec["required"] if field not in data or is_missing(data.get(field)))
    if missing:
        errors.append(f"{name}: missing required fields {missing}")
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"{name}: schema_version must be {SCHEMA_VERSION}")
    for field in spec.get("non_empty", set()):
        if is_missing(data.get(field)):
            errors.append(f"{name}: {field} must be non-empty")
    return errors


def validate_task_active_slice(task: dict) -> list[str]:
    active = task.get("active_slice")
    if active is None:
        return []
    if not isinstance(active, dict):
        return ["current-task.json: active_slice must be an object"]
    errors = []
    unknown = sorted(set(active) - ACTIVE_SLICE_ALLOWED)
    if unknown:
        errors.append(f"current-task.json.active_slice: unknown fields {unknown}")
    missing = sorted(field for field in ACTIVE_SLICE_REQUIRED if field not in active or is_missing(active.get(field)))
    if missing:
        errors.append(f"current-task.json.active_slice: missing required fields {missing}")
    if active.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"current-task.json.active_slice: schema_version must be {SCHEMA_VERSION}")
    return errors


def validate_quality_commands(quality: dict) -> list[str]:
    errors = []
    commands = quality.get("required_commands")
    if not isinstance(commands, list) or not commands:
        return ["quality-contract.json: required_commands must be a non-empty array"]
    for index, item in enumerate(commands):
        prefix = f"quality-contract.json.required_commands[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: command entry must be an object")
            continue
        unknown = sorted(set(item) - {"id", "command", "cwd", "required", "timeout_seconds"})
        if unknown:
            errors.append(f"{prefix}: unknown fields {unknown}")
        if is_missing(item.get("id")):
            errors.append(f"{prefix}: id is required")
        command = item.get("command")
        if is_missing(command):
            errors.append(f"{prefix}: command is required")
        elif contains_placeholder(command):
            errors.append(f"{prefix}: placeholder command is forbidden")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate strict v2 engineering-assistant control contracts.")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    control = root / "artifacts" / "_control"
    errors = []
    payloads = {}
    for name, spec in CONTRACTS.items():
        path = control / name
        if not path.exists():
            errors.append(f"{name}: missing control contract")
            continue
        try:
            payload = read_json(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        payloads[name] = payload
        errors.extend(validate_shape(name, payload, spec))
    for name, spec in OPTIONAL_CONTRACTS.items():
        path = control / name
        if not path.exists():
            continue
        try:
            payload = read_json(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        errors.extend(validate_shape(name, payload, spec))
    if "current-task.json" in payloads:
        errors.extend(validate_task_active_slice(payloads["current-task.json"]))
    if "quality-contract.json" in payloads:
        errors.extend(validate_quality_commands(payloads["quality-contract.json"]))
    report = {"status": "pass" if not errors else "block", "schema_version": SCHEMA_VERSION, "errors": errors}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
