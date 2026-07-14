#!/usr/bin/env python3
import json
import sys
from pathlib import Path

FORMAL_DESIGN_ARTIFACTS = ['high-level-design.md', 'detailed-design.md', 'database-design.md', 'redis-design.md', 'mq-design.xlsx', 'interface-contracts.yaml', 'test-strategy.md']

payload_path = Path(sys.argv[1])
schema = json.loads(Path(__file__).parents[1].joinpath("output.schema.json").read_text(encoding="utf-8"))
payload = json.loads(payload_path.read_text(encoding="utf-8"))
missing = [field for field in schema.get("required", []) if field not in payload]
if missing:
    raise SystemExit(f"缺少必填字段: {missing}")
if payload.get("skill_id") != schema["properties"]["skill_id"]["const"]:
    raise SystemExit("skill_id 不匹配")
if payload.get("status") not in schema["properties"]["status"]["enum"]:
    raise SystemExit("status 不合法")
if payload.get("preflight_input_state") not in schema["properties"]["preflight_input_state"]["enum"]:
    raise SystemExit("preflight_input_state 不合法")

errors = []
status = payload.get("status")
preflight = payload.get("preflight_input_state")
artifacts = payload.get("artifacts", [])
artifact_names = {artifact.get("name") for artifact in artifacts if artifact.get("name")}
if status == "succeeded" and preflight != "ready":
    errors.append("succeeded 时 preflight_input_state 必须为 ready")
if status == "waiting_for_input" and preflight != "waiting_for_input":
    errors.append("waiting_for_input 时 preflight_input_state 必须为 waiting_for_input")
if status == "waiting_for_human_review" and preflight != "waiting_for_human_review":
    errors.append("waiting_for_human_review 时 preflight_input_state 必须为 waiting_for_human_review")
if preflight != "ready":
    leaked = sorted(name for name in artifact_names if name in FORMAL_DESIGN_ARTIFACTS)
    if leaked:
        errors.append(f"preflight_input_state={preflight} 时不得产出正式设计工件: {', '.join(leaked)}")

if errors:
    raise SystemExit("\n".join(errors))
print("ok")
