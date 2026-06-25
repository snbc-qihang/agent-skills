#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, update_artifact_index, validate_target_project_root, write_json

def run_step(name: str, command: list[str], root: Path) -> dict:
    result = subprocess.run(command, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return {"step": name, "command": command, "returncode": result.returncode, "output": result.stdout[-12000:]}

def main():
    parser = argparse.ArgumentParser(description="Run the bounded implementation control loop.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--mode", choices=["repair", "validate", "audit-readonly"], default="repair")
    parser.add_argument("--task-type", default="code-development")
    parser.add_argument("--rule-evidence", action="append", default=[])
    parser.add_argument("--max-repair-attempts", type=int, default=2)
    parser.add_argument("--changed-files-report", default="artifacts/_control/changed-files-report.json")
    parser.add_argument("--output", default="artifacts/_control/repair-attempts.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    ensure_control_dir(root)
    here = Path(__file__).resolve().parent
    py = sys.executable
    if args.mode == "audit-readonly":
        steps = [
            ("validate_strict_control_contracts", [py, str(here / "validate_strict_control_contracts.py"), "--root", str(root)]),
            ("validate_contract_control", [py, str(here / "validate_contract_control.py"), str(root)]),
            ("validate_control_plane_readonly", [py, str(here / "validate_control_plane_readonly.py"), "--root", str(root), "--changed-files-report", args.changed_files_report]),
        ]
        failures = []
        for name, command in steps:
            result = run_step(name, command, root)
            if result["returncode"] != 0:
                failures.append(result)
                break
        print(json.dumps({"status": "pass" if not failures else "blocked", "mode": args.mode, "failures": failures}, ensure_ascii=False, indent=2))
        if failures:
            raise SystemExit(1)
        return
    steps = [
        ("validate_strict_control_contracts", [py, str(here / "validate_strict_control_contracts.py"), "--root", str(root)]),
        ("validate_contract_control", [py, str(here / "validate_contract_control.py"), str(root)]),
        ("validate_control_health", [py, str(here / "validate_control_health.py"), "--root", str(root), "--task-type", args.task_type]),
        ("collect_changed_files", [py, str(here / "collect_changed_files.py"), "--root", str(root)]),
        ("validate_control_plane_readonly", [py, str(here / "validate_control_plane_readonly.py"), "--root", str(root), "--changed-files-report", args.changed_files_report]),
        ("validate_design_to_code", [py, str(here / "validate_design_to_code.py"), "--root", str(root), "--allow-major"]),
        ("build_traceability_report", [py, str(here / "build_traceability_report.py"), "--root", str(root)]),
        ("validate_technology_adoption", [py, str(here / "validate_technology_adoption.py"), "--root", str(root)]),
        ("validate_spring_boot_quality", [py, str(here / "validate_spring_boot_quality.py"), "--root", str(root)]),
        ("run_quality_commands", [py, str(here / "run_quality_commands.py"), "--root", str(root)]),
    ]
    rule_command = [py, str(here / "validate_rule_consumption.py"), "--root", str(root), "--task-type", args.task_type]
    for evidence in args.rule_evidence:
        rule_command.extend(["--evidence", evidence])
    steps.append(("validate_rule_consumption", rule_command))
    failures = []
    for name, command in steps:
        result = run_step(name, command, root)
        if result["returncode"] != 0:
            failures.append(result)
            break
    status = "pass" if not failures else "blocked"
    output = root / args.output
    report = {"status": status, "max_attempts": args.max_repair_attempts, "attempts_used": args.max_repair_attempts if failures else 0, "failures": failures, "generated_at": now_iso()}
    write_json(output, report)
    update_artifact_index(root, output.name, output, "json", "run_controlled_task")
    print(output)
    if failures:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
