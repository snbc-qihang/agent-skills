#!/usr/bin/env python3
import json, sys
from pathlib import Path
required = ["skill_id", "version", "stage", "type", "entry_control", "inputs", "outputs", "quality_gates", "workflow_interface", "owner"]
for arg in sys.argv[1:]:
    data = json.loads(Path(arg).read_text(encoding="utf-8"))
    missing = [key for key in required if key not in data]
    if missing:
        raise SystemExit(f"{arg}: 缺少字段 {missing}")
    entry = data["entry_control"]
    if entry.get("sole_entrypoint") != "engineering-assistant" or entry.get("controller") != "workflow-orchestrator":
        raise SystemExit(f"{arg}: entry_control 未保持研发助手唯一入口和控制器")
    if entry.get("upstream_router_allowed") is not False:
        raise SystemExit(f"{arg}: upstream router 不得签发阶段入口")
    expected_route = data["skill_id"] != "workflow-orchestrator"
    if entry.get("controller_route_record_required") is not expected_route:
        raise SystemExit(f"{arg}: controller route record 策略不合法")
print("ok")
