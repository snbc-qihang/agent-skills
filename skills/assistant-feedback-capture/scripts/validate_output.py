#!/usr/bin/env python3
import json
import sys
from pathlib import Path

schema = json.loads(Path(__file__).parents[1].joinpath("output.schema.json").read_text(encoding="utf-8"))
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
missing = [field for field in schema.get("required", []) if field not in payload]
if missing:
    raise SystemExit(f"缺少必填字段: {missing}")
if payload.get("skill_id") != schema["properties"]["skill_id"]["const"]:
    raise SystemExit("skill_id 不匹配")
if payload.get("status") not in schema["properties"]["status"]["enum"]:
    raise SystemExit("status 不合法")
if payload.get("preflight_input_state") not in schema["properties"]["preflight_input_state"]["enum"]:
    raise SystemExit("preflight_input_state 不合法")
if payload.get("status") == "succeeded" and payload.get("preflight_input_state") != "ready":
    raise SystemExit("succeeded 必须满足 preflight_input_state == ready")
if payload.get("status") == "waiting_for_input" and payload.get("preflight_input_state") != "waiting_for_input":
    raise SystemExit("waiting_for_input 必须满足 preflight_input_state == waiting_for_input")
formal_design_artifacts = {"high-level-design.md", "detailed-design.md", "database-design.md", "redis-design.md", "mq-design.xlsx", "interface-contracts.yaml", "test-strategy.md"}
if payload.get("preflight_input_state") != "ready":
    produced = {item.get("name") for item in payload.get("artifacts", []) if isinstance(item, dict)}
    leaked = sorted(formal_design_artifacts & produced)
    if leaked:
        raise SystemExit("preflight 未 ready 时不得生成或登记正式设计文档: " + ", ".join(leaked))
print("ok")
