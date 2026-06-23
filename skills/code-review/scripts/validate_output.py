#!/usr/bin/env python3
import json
import sys
from pathlib import Path

REQUIRED_REVIEW_ARTIFACTS = ["code-review-report.md", "code-review-report.html", "review-comments.json", "blocker-list.md"]
HIGH_SEVERITIES = {"blocker", "critical", "major"}
QUALITY_DIMENSIONS = {
    "bug", "vulnerability", "security_hotspot", "code_smell", "complexity", "duplication", "coverage",
    "maintainability", "reliability", "security", "performance", "testability", "observability"
}
CHECKLIST_STATUSES = {"checked", "not_applicable", "missing", "blocked"}
BLOCKING_STATIC_STATUSES = {"tool_unavailable", "missing_input", "missing_config", "download_failed", "failed"}

schema = json.loads(Path(__file__).parents[1].joinpath("output.schema.json").read_text(encoding="utf-8"))
payload_path = Path(sys.argv[1])
payload = json.loads(payload_path.read_text(encoding="utf-8"))
errors = []
missing = [field for field in schema.get("required", []) if field not in payload]
if missing:
    errors.append(f"缺少必填字段: {missing}")
if payload.get("skill_id") != schema["properties"]["skill_id"]["const"]:
    errors.append("skill_id 不匹配")
if payload.get("status") not in schema["properties"]["status"]["enum"]:
    errors.append("status 不合法")
if payload.get("preflight_input_state") not in schema["properties"]["preflight_input_state"]["enum"]:
    errors.append("preflight_input_state 不合法")
if payload.get("status") == "succeeded" and payload.get("preflight_input_state") != "ready":
    errors.append("succeeded 必须满足 preflight_input_state == ready")
if payload.get("status") == "waiting_for_input" and payload.get("preflight_input_state") != "waiting_for_input":
    errors.append("waiting_for_input 必须满足 preflight_input_state == waiting_for_input")
formal_design_artifacts = {"high-level-design.md", "detailed-design.md", "database-design.md", "redis-design.md", "mq-design.xlsx", "interface-contracts.yaml", "test-strategy.md"}
if payload.get("preflight_input_state") != "ready":
    produced = {item.get("name") for item in payload.get("artifacts", []) if isinstance(item, dict)}
    leaked = sorted(formal_design_artifacts & produced)
    if leaked:
        errors.append("preflight 未 ready 时不得生成或登记正式设计文档: " + ", ".join(leaked))

def artifact_map(data):
    return {item.get("name"): item for item in data.get("artifacts", []) if isinstance(item, dict)}

def resolve_artifact(item):
    raw = (item or {}).get("path") or ""
    if not raw:
        return None
    path = Path(raw)
    candidates = [path] if path.is_absolute() else [Path.cwd() / path, payload_path.parent / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]

def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path}: JSON 解析失败: {exc}")
        return None

artifacts = artifact_map(payload)
if payload.get("status") == "succeeded":
    for name in REQUIRED_REVIEW_ARTIFACTS:
        item = artifacts.get(name)
        if not item:
            errors.append("code-review succeeded 必须登记产物: " + name)
            continue
        path = resolve_artifact(item)
        if not path or not path.exists():
            errors.append("code-review succeeded 必须真实生成产物: " + name)
    review_path = resolve_artifact(artifacts.get("review-comments.json")) if artifacts.get("review-comments.json") else None
    review = read_json(review_path) if review_path and review_path.exists() else None
    if review is not None:
        findings = review.get("findings") or review.get("comments") or payload.get("findings") or []
        for index, finding in enumerate(findings, start=1):
            if not isinstance(finding, dict):
                errors.append(f"review-comments.json 第 {index} 个 finding 不是对象")
                continue
            severity = str(finding.get("severity") or "").lower()
            if severity in HIGH_SEVERITIES:
                for field in ["id", "dimension", "category", "problem", "impact", "recommendation", "blocking"]:
                    if finding.get(field) in (None, "", []):
                        errors.append(f"高优先级 finding 第 {index} 缺少字段: {field}")
                if finding.get("dimension") not in QUALITY_DIMENSIONS:
                    errors.append(f"高优先级 finding 第 {index} 的 dimension 不合法或缺失")
                code_evidence = finding.get("code_evidence") or {}
                source_ids = finding.get("source_ids") or []
                if not code_evidence.get("file") and not source_ids:
                    errors.append(f"高优先级 finding 第 {index} 必须有 code_evidence.file 或 source_ids")
        coverage = review.get("checklist_coverage") or []
        if not coverage:
            errors.append("review-comments.json 必须包含 checklist_coverage，显式说明质量维度覆盖情况")
        seen_dimensions = set()
        for index, item in enumerate(coverage, start=1):
            dimension = item.get("dimension") if isinstance(item, dict) else None
            status = item.get("status") if isinstance(item, dict) else None
            if dimension not in QUALITY_DIMENSIONS:
                errors.append(f"checklist_coverage 第 {index} 的 dimension 不合法: {dimension}")
            else:
                seen_dimensions.add(dimension)
            if status not in CHECKLIST_STATUSES:
                errors.append(f"checklist_coverage 第 {index} 的 status 不合法: {status}")
        missing_dimensions = sorted(QUALITY_DIMENSIONS - seen_dimensions)
        if missing_dimensions:
            errors.append("checklist_coverage 缺少质量维度: " + ", ".join(missing_dimensions))
        blocking_dimensions = sorted(item.get("dimension") for item in coverage if isinstance(item, dict) and item.get("status") in {"missing", "blocked"})
        if blocking_dimensions:
            errors.append("code-review succeeded 不得存在未覆盖或阻断的质量维度: " + ", ".join(blocking_dimensions))
        html_path = resolve_artifact(artifacts.get("code-review-report.html")) if artifacts.get("code-review-report.html") else None
        if html_path and html_path.exists():
            html = html_path.read_text(encoding="utf-8")
            for token in ["Quality Dimension", "Checklist Coverage", "问题清单", "人工确认区"]:
                if token not in html:
                    errors.append("code-review-report.html 缺少报告区块: " + token)
    static_item = artifacts.get("static-analysis-report.json")
    static_path = resolve_artifact(static_item) if static_item else None
    if not static_path or not static_path.exists():
        errors.append("code-review succeeded 必须登记并消费 static-analysis-report.json；缺失时不得通过")
    else:
        static = read_json(static_path)
        if static is not None:
            tools = static.get("tools") or []
            if not tools:
                errors.append("static-analysis-report.json 必须包含 tools 执行状态")
            blocking_tools = [tool.get("name", "unknown") for tool in tools if str(tool.get("status") or "").lower() in BLOCKING_STATIC_STATUSES]
            waiver = static.get("waiver", {}) if isinstance(static.get("waiver"), dict) else {}
            if blocking_tools and waiver.get("status") != "accepted":
                errors.append("静态分析工具缺失/失败且没有已接受豁免，不得 succeeded: " + ", ".join(blocking_tools))

if errors:
    raise SystemExit("\n".join(errors))
print("ok")
