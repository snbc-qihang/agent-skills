#!/usr/bin/env python3
import json, sys
from pathlib import Path

VALID_STATUSES = {"aligned", "aligned_with_followups", "drift_detected", "blocked"}
BLOCKING_DRIFT = {"PRODUCT_PLAN_DRIFT", "LOCAL_OPTIMUM_ONLY", "PLAN_SPINE_NOT_UPDATED", "UNINDEXED_FORMAL_DOC"}

errors = []
for arg in sys.argv[1:]:
    path = Path(arg)
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in ["run_id", "product_goal", "capability_path", "accepted_scope", "out_of_scope", "integration_points", "next_plan_update", "alignment_status", "drift_findings", "document_changes", "checked_by"]:
        if field not in data:
            errors.append(f"{path}: 缺少字段 {field}")
    if data.get("alignment_status") not in VALID_STATUSES:
        errors.append(f"{path}: alignment_status 不合法")
    if data.get("alignment_status") in {"drift_detected", "blocked"}:
        errors.append(f"{path}: MISSING_POST_TASK_ALIGNMENT 规划漂移未关闭，任务不得完成")
    for index, finding in enumerate(data.get("drift_findings") or []):
        marker = finding.get("marker")
        if marker in BLOCKING_DRIFT and not finding.get("resolved"):
            errors.append(f"{path}: {marker} drift_findings[{index}] 未解决")
    for index, change in enumerate(data.get("document_changes") or []):
        if change.get("path", "").startswith("docs/") and not change.get("document_index_updated"):
            errors.append(f"{path}: UNINDEXED_FORMAL_DOC document_changes[{index}] 未同步 document-index")
        if change.get("replaces") and not change.get("superseded_previous"):
            errors.append(f"{path}: STALE_PLAN_SOURCE document_changes[{index}] 替代旧文档但未标记 superseded")
if errors:
    raise SystemExit("\n".join(errors))
print("ok")
