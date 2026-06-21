#!/usr/bin/env python3
import json, sys
from pathlib import Path

TASK_KINDS = {"context", "audit", "change", "release", "self_healing"}
EVIDENCE_LEVELS = {"inline", "lite", "standard", "formal"}
PERSISTENCE_MODES = {"inline", "ephemeral", "target_repo", "blocked"}
DECISIONS = {"call", "skip", "unavailable", "blocked"}

errors = []
for arg in sys.argv[1:]:
    path = Path(arg)
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in ["run_id", "task_kind", "evidence_level", "persistence_mode", "route_reason", "capability_decisions"]:
        if field not in data:
            errors.append(f"{path}: 缺少字段 {field}")
    if data.get("task_kind") not in TASK_KINDS:
        errors.append(f"{path}: task_kind 不合法")
    if data.get("evidence_level") not in EVIDENCE_LEVELS:
        errors.append(f"{path}: evidence_level 不合法")
    if data.get("persistence_mode") not in PERSISTENCE_MODES:
        errors.append(f"{path}: persistence_mode 不合法")
    if data.get("persistence_mode") == "target_repo":
        has_allowed_reason = data.get("explicit_user_request") or data.get("formal_evidence_reason") or data.get("delivery_material_confirmed")
        if not has_allowed_reason:
            errors.append(f"{path}: target_repo 持久化必须有明确用户要求、formal evidence 理由或交付资料确认")
        if data.get("delivery_material_confirmed"):
            source = str(data.get("source_run_artifact") or "")
            target = str(data.get("docs_promotion_target") or "")
            if not source.startswith(".run-artifacts/"):
                errors.append(f"{path}: 已确认交付资料必须记录 .run-artifacts/ 下的 source_run_artifact")
            if not target.startswith("docs/"):
                errors.append(f"{path}: 已确认交付资料必须自动提升到 docs/ 下的 docs_promotion_target")
        if data.get("evidence_level") != "formal" and not (data.get("explicit_user_request") or data.get("delivery_material_confirmed")):
            errors.append(f"{path}: 非 formal 证据写入 target_repo 必须有明确用户要求或交付资料确认")
    for index, decision in enumerate(data.get("capability_decisions") or []):
        if decision.get("decision") not in DECISIONS:
            errors.append(f"{path}: capability_decisions[{index}].decision 不合法")
        if not decision.get("reason"):
            errors.append(f"{path}: capability_decisions[{index}].reason 不能为空")
if errors:
    raise SystemExit("\n".join(errors))
print("ok")
