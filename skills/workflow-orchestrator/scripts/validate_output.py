#!/usr/bin/env python3
import json
import sys
from pathlib import Path

schema = json.loads(Path(__file__).parents[1].joinpath("output.schema.json").read_text(encoding="utf-8"))
payload_path = Path(sys.argv[1])
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
if payload.get("status") == "succeeded" and payload.get("preflight_input_state") != "ready":
    errors.append("succeeded 必须满足 preflight_input_state == ready")
if payload.get("status") == "waiting_for_input" and payload.get("preflight_input_state") != "waiting_for_input":
    errors.append("waiting_for_input 必须满足 preflight_input_state == waiting_for_input")

def artifact_map(payload):
    return {item.get("name"): item for item in payload.get("artifacts", [])}

def resolve_artifact(item):
    raw = (item or {}).get("path") or ""
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path
    return payload_path.parent / path

def read_text_artifact(name):
    path = resolve_artifact(artifact_map(payload).get(name))
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    return ""

def read_json_artifact(name):
    text = read_text_artifact(name)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{name} 不是合法 JSON: {exc}")
        return None

validator_summary = read_json_artifact("validator-summary.json")
if payload.get("status") == "succeeded":
    if validator_summary is None:
        errors.append("workflow-orchestrator succeeded 必须登记并生成 validator-summary.json，汇总所有专项 validator 结果")
    else:
        validators = validator_summary.get("validators") or validator_summary.get("results") or []
        if not validators:
            errors.append("validator-summary.json 必须包含 validators/results 列表")
        required_validators = {"high-level-design", "detailed-design", "database-design", "mq-design", "redis-design"}
        seen = {str(item.get("stage") or item.get("skill_id") or item.get("validator") or item.get("name") or "") for item in validators if isinstance(item, dict)}
        missing_validators = sorted(required_validators - seen)
        if missing_validators:
            errors.append("design-only workflow succeeded 前必须汇总所有相关专项 validator，缺少: " + ", ".join(missing_validators))
        for item in validators:
            status = str(item.get("status") or item.get("result") or "").lower()
            exit_code = item.get("exit_code")
            if status in {"failed", "fail", "error", "blocked"} or (exit_code not in (None, 0, "0")):
                skill_id = item.get("skill_id") or item.get("validator") or item.get("name") or "unknown"
                errors.append(f"专项 validator 失败必须向 workflow-orchestrator 冒泡为 blocked，不得 succeeded: {skill_id}")
if validator_summary is not None:
    validators = validator_summary.get("validators") or validator_summary.get("results") or []
    for index, item in enumerate(validators, start=1):
        status = str(item.get("status") or item.get("result") or "").lower() if isinstance(item, dict) else ""
        exit_code = item.get("exit_code") if isinstance(item, dict) else None
        if status in {"failed", "fail", "error", "blocked"} or (exit_code not in (None, 0, "0")):
            for field in ["stage", "validator", "failed_rule", "error_message", "suggested_repair"]:
                if not item.get(field):
                    errors.append(f"validator-summary.json 第 {index} 个失败项缺少字段: {field}")

quality_defect_terms = ["脱离代码实际", "模板裁剪", "validator 失败", "门禁失败", "产物质量问题", "用户指出"]
quality_text = json.dumps(payload.get("findings", []), ensure_ascii=False) + "\n" + read_text_artifact("workflow-summary.md")
if payload.get("status") == "succeeded" and any(term in quality_text for term in quality_defect_terms):
    defect_analysis = read_json_artifact("defect-analysis.json")
    if defect_analysis is None:
        errors.append("发现产物质量缺陷或用户指出问题时，workflow-orchestrator 必须生成 defect-analysis.json 并记录 root_cause，不得直接 succeeded")
    elif not defect_analysis.get("root_cause"):
        errors.append("defect-analysis.json 缺少 root_cause")

if errors:
    raise SystemExit("\n".join(errors))
print("ok")
