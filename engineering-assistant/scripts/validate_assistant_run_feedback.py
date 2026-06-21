#!/usr/bin/env python3
import json, sys
from pathlib import Path

POLLUTION_MARKERS = {"TARGET_REPO_ARTIFACT_POLLUTION", "PROCESS_DOCUMENTATION_POLLUTION"}

errors = []
for arg in sys.argv[1:]:
    path = Path(arg)
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in ["run_id", "status", "route_decision", "capability_decisions", "capability_health_checked", "target_repo_pollution_findings", "docs_promotions", "rule_violations", "darwin_required", "consumed_by_agent"]:
        if field not in data:
            errors.append(f"{path}: 缺少字段 {field}")
    if data.get("consumed_by_agent") is not True:
        errors.append(f"{path}: assistant-run-feedback 必须由 agent 消费")
    if data.get("capability_health_checked") is not True:
        errors.append(f"{path}: CAPABILITY_HEALTH_NOT_CHECKED")
    route = data.get("route_decision") or {}
    if not route.get("task_kind") or not route.get("evidence_level") or not route.get("persistence_mode"):
        errors.append(f"{path}: route_decision 必须包含 task_kind/evidence_level/persistence_mode")
    if not data.get("capability_decisions"):
        errors.append(f"{path}: capability_decisions 不能为空，必须记录 call/skip/unavailable/blocked 裁决")
    pollution = data.get("target_repo_pollution_findings") or []
    violations = set(data.get("rule_violations") or [])
    if pollution and not (violations & POLLUTION_MARKERS):
        errors.append(f"{path}: 发现目标仓库过程产物污染时必须标记 TARGET_REPO_ARTIFACT_POLLUTION 或 PROCESS_DOCUMENTATION_POLLUTION")
    for index, promotion in enumerate(data.get("docs_promotions") or []):
        source = str(promotion.get("source_run_artifact") or "")
        target = str(promotion.get("docs_promotion_target") or "")
        if not promotion.get("confirmed_as_delivery_material"):
            errors.append(f"{path}: docs_promotions[{index}] 必须声明 confirmed_as_delivery_material=true")
        if not source.startswith(".run-artifacts/"):
            errors.append(f"{path}: docs_promotions[{index}].source_run_artifact 必须来自 .run-artifacts/")
        if not target.startswith("docs/"):
            errors.append(f"{path}: docs_promotions[{index}].docs_promotion_target 必须位于 docs/")
if errors:
    raise SystemExit("\n".join(errors))
print("ok")
