#!/usr/bin/env python3
import json, sys
from pathlib import Path

MIN_REPEAT_FOR_REGRESSION = 3
VALID_VERDICTS = {"accepted_candidate", "rejected_noise", "needs_more_evidence", "merged_with_existing", "waiting_for_human_review"}

errors = []
for arg in sys.argv[1:]:
    path = Path(arg)
    data = json.loads(path.read_text(encoding="utf-8"))
    events = data.get("events") if isinstance(data.get("events"), list) else [data]
    if not events:
        errors.append(f"{path}: feedback events 不能为空")
    for index, event in enumerate(events):
        prefix = f"{path}: events[{index}]"
        for field in ["event_id", "source_task_id", "source_run_id", "triggered_skill_id", "event_type", "severity", "symptom", "evidence_paths", "repeat_count", "recommended_action", "regression_case_candidate", "consumed_by_evolution_review"]:
            if field not in event:
                errors.append(f"{prefix}: 缺少字段 {field}")
        if not event.get("evidence_paths"):
            errors.append(f"{prefix}: FEEDBACK_EVENT_MISSING_EVIDENCE")
        if event.get("consumed_by_evolution_review") is not True and data.get("mode") == "evolution_review":
            errors.append(f"{prefix}: FEEDBACK_EVENT_NOT_CONSUMED")
        if event.get("repeat_count", 0) >= MIN_REPEAT_FOR_REGRESSION and event.get("regression_case_candidate") is not True:
            errors.append(f"{prefix}: REGRESSION_CANDIDATE_REQUIRED")
        verdict = event.get("verdict")
        if verdict is not None and verdict not in VALID_VERDICTS:
            errors.append(f"{prefix}: verdict 不合法")
        if verdict == "rejected_noise" and not event.get("reject_reason"):
            errors.append(f"{prefix}: rejected_noise 必须包含 reject_reason")
    candidates = data.get("skill_evolution_candidates") or data.get("candidates") or []
    for index, candidate in enumerate(candidates):
        prefix = f"{path}: candidates[{index}]"
        if candidate.get("human_approval_required") is not True:
            errors.append(f"{prefix}: 正式 skill 演进候选必须 human_approval_required=true")
        if candidate.get("auto_apply") is True:
            errors.append(f"{prefix}: 不允许 auto_apply 正式 skill 变更")
        if candidate.get("verdict") not in VALID_VERDICTS:
            errors.append(f"{prefix}: verdict 不合法")
if errors:
    raise SystemExit("\n".join(errors))
print("ok")
