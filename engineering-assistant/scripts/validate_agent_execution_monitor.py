#!/usr/bin/env python3
import json, sys
from pathlib import Path

REQUIRED_MONITOR_CHECKS = {"scope_adherence", "evidence_returned", "independent_verification", "artifact_consumed_by_orchestrator", "no_unverified_success_claim"}

errors = []
for arg in sys.argv[1:]:
    path = Path(arg)
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in ["run_id", "task_id", "agents", "monitor_checks", "consumed_by_orchestrator"]:
        if field not in data:
            errors.append(f"{path}: 缺少字段 {field}")
    if data.get("consumed_by_orchestrator") is not True:
        errors.append(f"{path}: MONITOR_CHECK_NOT_CONSUMED")
    observed_checks = {check.get("check_id") for check in data.get("monitor_checks") or []}
    missing_checks = REQUIRED_MONITOR_CHECKS - observed_checks
    if missing_checks:
        errors.append(f"{path}: 缺少严格监控检查 {sorted(missing_checks)}")
    for index, agent in enumerate(data.get("agents") or []):
        for field in ["agent_id", "role", "assigned_scope", "forbidden_scope", "expected_outputs", "required_checks", "status"]:
            if field not in agent:
                errors.append(f"{path}: agents[{index}] 缺少字段 {field}")
        if agent.get("status") == "succeeded" and not agent.get("observed_evidence"):
            errors.append(f"{path}: SUBAGENT_EVIDENCE_MISSING agents[{index}] 成功结论缺少 observed_evidence")
        if agent.get("status") == "succeeded" and agent.get("independent_verification") is not True:
            errors.append(f"{path}: SUBAGENT_UNVERIFIED_SUCCESS agents[{index}] 成功结论必须独立验证")
if errors:
    raise SystemExit("\n".join(errors))
print("ok")
