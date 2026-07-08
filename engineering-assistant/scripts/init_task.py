#!/usr/bin/env python3
import argparse
import re
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, read_json, validate_target_project_root, write_json

SCHEMA_VERSION = "3.1.0"

def slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return value or "task"

def main():
    parser = argparse.ArgumentParser(description="Initialize engineering-assistant task control files.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--title", required=True)
    parser.add_argument("--language", choices=["zh-CN", "en"], default="zh-CN")
    parser.add_argument("--workflow-id", default="contract-driven-development")
    parser.add_argument("--project-profile")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    control = ensure_control_dir(root)
    task_id = args.task_id or slug(args.title)
    profile = read_json(Path(args.project_profile), {}) if args.project_profile else {}
    active_slice = {
        "schema_version": SCHEMA_VERSION,
        "slice_id": task_id,
        "parent_task_id": task_id,
        "title": args.title,
        "kind": "initial_task",
        "status": "initialized",
        "control_artifacts": {
            "current_task": "artifacts/_control/current-task.json",
            "current_subtask": "artifacts/_control/current-subtask.json",
            "open_questions": "artifacts/_control/open-questions.json",
        },
        "blockers": [],
        "updated_at": now_iso(),
    }
    task = {"schema_version": SCHEMA_VERSION, "task_id": task_id, "title": args.title, "language": args.language, "workflow_id": args.workflow_id, "status": "initialized", "control_dir": str(control.relative_to(root)), "project_profile": profile, "current_contracts": {}, "active_slice": active_slice, "created_at": now_iso(), "updated_at": now_iso()}
    write_json(control / "current-task.json", task)
    write_json(control / "current-subtask.json", active_slice)
    write_json(control / "artifact-index.json", {"artifacts": {}, "updated_at": now_iso()})
    write_json(control / "decision-log.json", {"decisions": []})
    write_json(control / "open-questions.json", {"questions": []})
    write_json(control / "approval-log.json", {"approvals": []})
    context = [
        "# Task Context",
        "",
        "## Read First",
        "- This file is the short control-plane entry for the current task.",
        "- Do not bulk-read all docs before checking the rule pack and contracts listed here.",
        "- Stop when a blocking open question, missing approval, or failed quality gate is present.",
        "",
        "## Task",
        f"- task_id: {task_id}",
        f"- title: {args.title}",
        f"- language: {args.language}",
        f"- workflow_id: {args.workflow_id}",
        "",
        "## Control Artifacts",
        "- current_task: artifacts/_control/current-task.json",
        "- current_subtask: artifacts/_control/current-subtask.json",
        "- implementation_contract: artifacts/_control/implementation-contract.json",
        "- quality_contract: artifacts/_control/quality-contract.json",
        "- open_questions: artifacts/_control/open-questions.json",
        "- task_rule_pack: artifacts/rule-governance/task-rule-packs/code-development.json",
        "",
        "## Mandatory Entry Checks",
        "- python3 engineering-assistant/scripts/validate_strict_control_contracts.py --root <project-root>",
        "- python3 engineering-assistant/scripts/validate_contract_control.py <project-root>",
        "- python3 engineering-assistant/scripts/validate_control_health.py --root <project-root>",
        "- python3 engineering-assistant/scripts/run_controlled_task.py --root <project-root> --mode audit-readonly",
        "",
    ]
    (control / "task-context.agent.md").write_text("\n".join(context), encoding="utf-8")
    print(control / "current-task.json")

if __name__ == "__main__":
    main()
