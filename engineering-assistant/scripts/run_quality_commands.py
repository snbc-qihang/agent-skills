#!/usr/bin/env python3
import argparse
import subprocess
import sys
import time
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, read_json, update_artifact_index, validate_target_project_root, write_json

SCHEMA_VERSION = "2.0.0"
PLACEHOLDER_TOKENS = ("待 code-development 阶段写入", "待确认", "todo", "tbd", "placeholder")
QUALITY_BLOCKER_ID = "QR-BLOCKER-001"

def is_placeholder(command: str) -> bool:
    lowered = command.lower()
    return any(token.lower() in lowered for token in PLACEHOLDER_TOKENS)

def excerpt(value: str, limit: int = 12000) -> str:
    return (value or "")[-limit:]

def safe_cwd(root: Path, cwd_value: str | None) -> Path:
    cwd = root / (cwd_value or ".")
    resolved = cwd.resolve()
    if root.resolve() not in [resolved, *resolved.parents]:
        raise SystemExit(f"quality command cwd escapes project root: {cwd_value}")
    return resolved

def run_command(root: Path, item: dict) -> dict:
    command = item["command"]
    cwd = safe_cwd(root, item.get("cwd"))
    timeout = item.get("timeout_seconds")
    started = time.monotonic()
    if not cwd.exists():
        return {
            "id": item.get("id", command),
            "command": command,
            "cwd": str(cwd.relative_to(root)),
            "required": item.get("required", True),
            "exit_code": 127,
            "returncode": 127,
            "duration_ms": 0,
            "timed_out": False,
            "blocking": bool(item.get("required", True)),
            "stdout_excerpt": "",
            "stderr_excerpt": f"cwd does not exist: {cwd.relative_to(root)}",
            "output": f"cwd does not exist: {cwd.relative_to(root)}",
        }
    try:
        run = subprocess.run(command, cwd=cwd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        exit_code = run.returncode
        stdout = run.stdout
        stderr = run.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        timed_out = True
    duration_ms = int((time.monotonic() - started) * 1000)
    required = item.get("required", True)
    return {
        "id": item.get("id", command),
        "command": command,
        "cwd": str(cwd.relative_to(root)),
        "required": required,
        "exit_code": exit_code,
        "returncode": exit_code,
        "duration_ms": duration_ms,
        "timed_out": timed_out,
        "blocking": bool(required and exit_code != 0),
        "stdout_excerpt": excerpt(stdout),
        "stderr_excerpt": excerpt(stderr),
        "output": excerpt((stdout or "") + (stderr or "")),
    }

def current_slice(root: Path, task: dict) -> dict:
    control = ensure_control_dir(root)
    subtask = read_json(control / "current-subtask.json", {})
    active = task.get("active_slice") if isinstance(task.get("active_slice"), dict) else {}
    result = {**subtask, **active}
    parent = task.get("task_id") or result.get("parent_task_id") or result.get("slice_id") or "unknown-task"
    result["schema_version"] = SCHEMA_VERSION
    result.setdefault("slice_id", result.get("slice_id") or parent)
    result.setdefault("parent_task_id", parent)
    result.setdefault("title", task.get("title") or result.get("slice_id"))
    result.setdefault("kind", "quality_contract")
    result.setdefault("control_artifacts", {})
    result["control_artifacts"].update({
        "current_task": "artifacts/_control/current-task.json",
        "current_subtask": "artifacts/_control/current-subtask.json",
        "quality_contract": "artifacts/_control/quality-contract.json",
        "quality_run_report": "artifacts/_control/quality-run-report.json",
        "open_questions": "artifacts/_control/open-questions.json",
    })
    return result

def sync_control_plane(root: Path, report: dict, output: Path) -> None:
    control = ensure_control_dir(root)
    task_path = control / "current-task.json"
    subtask_path = control / "current-subtask.json"
    questions_path = control / "open-questions.json"
    task = read_json(task_path, {"schema_version": SCHEMA_VERSION, "task_id": report.get("task_id") or "unknown-task", "status": "initialized", "control_dir": "artifacts/_control"})
    task["schema_version"] = SCHEMA_VERSION
    active = current_slice(root, task)
    blockers = [finding for finding in report.get("findings", []) if finding.get("severity") == "blocker"]
    active["quality_status"] = report["status"]
    active["status"] = "blocked" if report["status"] == "block" else "succeeded"
    active["blockers"] = blockers
    active["updated_at"] = now_iso()
    task["active_slice"] = active
    task["status"] = "blocked" if report["status"] == "block" else task.get("status", "quality_running")
    task["updated_at"] = now_iso()
    write_json(task_path, task)
    write_json(subtask_path, active)
    questions = read_json(questions_path, {"questions": []})
    existing = {item.get("id"): item for item in questions.get("questions", []) if isinstance(item, dict)}
    if blockers:
        existing[QUALITY_BLOCKER_ID] = {
            "id": QUALITY_BLOCKER_ID,
            "severity": "blocker",
            "status": "open",
            "blocking": True,
            "question": "quality-contract required commands failed; inspect artifacts/_control/quality-run-report.json before continuing",
            "source_artifact": str(output.relative_to(root)),
            "updated_at": now_iso(),
        }
    elif QUALITY_BLOCKER_ID in existing:
        existing[QUALITY_BLOCKER_ID]["status"] = "resolved"
        existing[QUALITY_BLOCKER_ID]["blocking"] = False
        existing[QUALITY_BLOCKER_ID]["updated_at"] = now_iso()
    questions["questions"] = list(existing.values())
    questions["updated_at"] = now_iso()
    write_json(questions_path, questions)
    for path, name, producer in [
        (task_path, "current-task.json", "run_quality_contract"),
        (subtask_path, "current-subtask.json", "run_quality_contract"),
        (questions_path, "open-questions.json", "run_quality_contract"),
        (output, output.name, "run_quality_contract"),
    ]:
        update_artifact_index(root, name, path, "json", producer)

def refresh_project_quality_inputs(root: Path) -> list[dict]:
    refresh_scripts = [
        root / "scripts/quality/generate_quality_inputs.py",
        root / "scripts/quality/generate_code_review_artifacts.py",
    ]
    if not all(path.is_file() for path in refresh_scripts):
        return []
    results = []
    for script in refresh_scripts:
        rel = script.relative_to(root)
        run = subprocess.run([sys.executable, str(rel)], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        results.append({
            "id": rel.as_posix(),
            "command": f"{sys.executable} {rel.as_posix()}",
            "exit_code": run.returncode,
            "returncode": run.returncode,
            "stdout_excerpt": excerpt(run.stdout),
            "stderr_excerpt": excerpt(run.stderr),
        })
        if run.returncode != 0:
            break
    return results

def build_report(contract: dict, commands: list[dict], results: list[dict], errors: list[str]) -> dict:
    findings = []
    required_failures = [item for item in results if item.get("required") and item.get("exit_code") != 0]
    make_validate_passed = any("make validate" in item.get("command", "") and item.get("exit_code") == 0 for item in results)
    for item in required_failures:
        findings.append({"id": f"QUALITY-COMMAND-FAILED-{item['id']}", "severity": "blocker", "summary": f"required quality command failed: {item['id']}", "command": item["command"], "exit_code": item["exit_code"]})
    if make_validate_passed and required_failures:
        findings.append({"id": "QUALITY-CONTRACT-REQUIRED-FAILED-DESPITE-MAKE-VALIDATE", "severity": "blocker", "summary": "make validate passed, but quality-contract required command failed; quality contract remains blocking."})
    for error in errors:
        findings.append({"id": "QUALITY-CONTRACT-RUNNER-ERROR", "severity": "blocker", "summary": error})
    status = "block" if errors or required_failures or not commands else "pass"
    if not commands and "no required quality commands declared" not in errors:
        errors.append("no required quality commands declared")
        findings.append({"id": "QUALITY-CONTRACT-NO-REQUIRED-COMMANDS", "severity": "blocker", "summary": "no required quality commands declared"})
        status = "block"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "task_id": contract.get("task_id"),
        "summary": {
            "commands_total": len(commands),
            "required_total": sum(1 for item in commands if item.get("required", True)),
            "required_failed": len(required_failures),
            "optional_failed": sum(1 for item in results if not item.get("required") and item.get("exit_code") != 0),
            "make_validate_passed": make_validate_passed,
        },
        "errors": errors,
        "findings": findings,
        "results": results,
        "generated_at": now_iso(),
    }

def main():
    parser = argparse.ArgumentParser(description="Run quality commands declared in quality-contract.json.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--contract", default="artifacts/_control/quality-contract.json")
    parser.add_argument("--output", default="artifacts/_control/quality-run-report.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    contract = read_json(root / args.contract, {})
    commands = contract.get("required_commands", [])
    results = []
    errors = []
    for item in commands:
        command = item.get("command") if isinstance(item, dict) else None
        if not command:
            errors.append(f"quality command {item.get('id', '<missing-id>') if isinstance(item, dict) else '<invalid>'} is missing command")
            continue
        if is_placeholder(command):
            errors.append(f"quality command {item.get('id', command)} contains placeholder text")
            continue
        results.append(run_command(root, item))
    report = build_report(contract, commands, results, errors)
    output = root / args.output
    write_json(output, report)
    sync_control_plane(root, report, output)
    refresh_results = refresh_project_quality_inputs(root)
    refresh_failures = [item for item in refresh_results if item.get("exit_code") != 0]
    if refresh_failures and report["status"] != "block":
        report["status"] = "block"
        report["errors"].append("post-sync quality input refresh failed")
        report["findings"].append({
            "id": "QUALITY-CONTRACT-POST-SYNC-REFRESH-FAILED",
            "severity": "blocker",
            "summary": "post-sync quality input refresh failed after quality-run-report/control-plane updates",
            "results": refresh_failures,
        })
        write_json(output, report)
        sync_control_plane(root, report, output)
    print(output)
    if report["status"] == "block":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
