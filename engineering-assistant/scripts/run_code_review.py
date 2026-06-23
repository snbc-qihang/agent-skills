#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

QUALITY_DIMENSIONS = [
    "bug", "vulnerability", "security_hotspot", "code_smell", "complexity", "duplication", "coverage",
    "maintainability", "reliability", "security", "performance", "testability", "observability"
]
BLOCKING_TOOL_STATUSES = {"tool_unavailable", "missing_input", "missing_config", "download_failed", "failed"}


def load_json(path: Path):
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def first_existing(paths):
    for path in paths:
        if path and path.exists():
            return path
    return None


def rel_or_abs(root: Path, value: str):
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def normalize_severity(value) -> str:
    raw = str(value or "").lower()
    if raw in {"blocker", "critical", "major", "minor", "info"}:
        return raw
    if raw in {"error", "high"}:
        return "major"
    if raw in {"warn", "warning", "medium"}:
        return "minor"
    return "info"


def normalize_dimension(value) -> str:
    raw = str(value or "").lower().replace(" ", "_")
    aliases = {
        "bugs": "bug",
        "vulnerabilities": "vulnerability",
        "security-hotspot": "security_hotspot",
        "smell": "code_smell",
        "code-smell": "code_smell",
        "maintainability_issue": "maintainability",
        "reliability_issue": "reliability",
        "performance_issue": "performance",
        "test": "testability",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in QUALITY_DIMENSIONS else "maintainability"


def category_for_dimension(dimension: str) -> str:
    if dimension in {"bug", "reliability"}:
        return "correctness"
    if dimension in {"vulnerability", "security_hotspot", "security"}:
        return "security"
    if dimension == "performance":
        return "performance"
    if dimension in {"coverage", "testability"}:
        return "test"
    if dimension == "observability":
        return "observability"
    return "quality"


def collect_items(payload: dict):
    for key in ["findings", "issues", "comments", "violations"]:
        value = payload.get(key)
        if isinstance(value, list):
            yield from value


def normalize_finding(item: dict, source: str, index: int) -> dict:
    dimension = normalize_dimension(item.get("dimension") or item.get("category") or item.get("type") or item.get("rule_category"))
    file_name = item.get("file") or item.get("path") or item.get("location") or item.get("component") or ""
    line = item.get("line") or item.get("start_line") or item.get("start")
    finding_id = item.get("id") or item.get("rule_id") or item.get("rule") or f"CRR-{source}-{index:03d}"
    message = item.get("problem") or item.get("message") or item.get("title") or item.get("summary") or "代码走查发现问题"
    return {
        "id": str(finding_id),
        "severity": normalize_severity(item.get("severity") or item.get("level") or item.get("priority")),
        "dimension": dimension,
        "category": category_for_dimension(dimension),
        "code_evidence": {
            "file": str(file_name),
            "line_start": int(line) if str(line or "").isdigit() else 1,
            "line_end": int(line) if str(line or "").isdigit() else 1,
            "snippet": str(item.get("snippet") or item.get("evidence") or "")[:2000],
            "source": source,
        },
        "problem": str(message),
        "impact": str(item.get("impact") or item.get("risk") or "影响代码质量、可维护性或发布风险，需要人工确认或修复。"),
        "recommendation": str(item.get("recommendation") or item.get("suggestion") or item.get("fix") or "定位证据后修复，并重跑代码质量与走查门禁。"),
        "rule_refs": item.get("rule_refs") or ([] if not item.get("rule_id") else [str(item.get("rule_id"))]),
        "source_ids": item.get("source_ids") or [f"{source}:{finding_id}"],
        "blocking": normalize_severity(item.get("severity") or item.get("level") or item.get("priority")) in {"blocker", "critical", "major"},
    }


def tool_findings(static_report: dict) -> list[dict]:
    findings = []
    for index, tool in enumerate(static_report.get("tools", []) or [], start=1):
        status = str(tool.get("status") or "").lower()
        if status in BLOCKING_TOOL_STATUSES:
            findings.append({
                "id": f"CRR-STATIC-{index:03d}",
                "severity": "major",
                "dimension": "maintainability",
                "category": "tooling",
                "code_evidence": {"file": "<static-analysis>", "line_start": 1, "line_end": 1, "snippet": tool.get("reason", ""), "source": "static_analysis"},
                "problem": f"静态分析工具 {tool.get('name', 'unknown')} 状态为 {status}",
                "impact": "静态分析未完整执行，代码异味、复杂度、安全热点或可靠性问题可能漏检。",
                "recommendation": "补齐工具配置/凭证/执行环境后重跑；如确需跳过，必须登记已接受的人工豁免。",
                "rule_refs": [],
                "source_ids": [f"static-analysis-report:{tool.get('name', 'unknown')}"],
                "blocking": True,
            })
    return findings


def checklist_coverage(findings: list[dict], static_report: dict) -> list[dict]:
    dimensions_with_findings = {item.get("dimension") for item in findings if item.get("dimension")}
    tools = static_report.get("tools", []) if isinstance(static_report, dict) else []
    blocking_tools = [tool for tool in tools if str(tool.get("status") or "").lower() in BLOCKING_TOOL_STATUSES]
    any_tool_passed = any(str(tool.get("status") or "").lower() == "passed" for tool in tools)
    coverage = []
    for dimension in QUALITY_DIMENSIONS:
        if dimension in dimensions_with_findings:
            status = "checked"
            evidence = [item["id"] for item in findings if item.get("dimension") == dimension]
            reason = "该维度存在 finding 或工具证据。"
        elif blocking_tools and not static_report.get("waiver", {}).get("status") == "accepted":
            status = "blocked"
            evidence = [f"static-analysis-report:{tool.get('name', 'unknown')}" for tool in blocking_tools]
            reason = "静态分析工具缺失或失败，不能确认该维度已覆盖。"
        elif any_tool_passed:
            status = "checked"
            evidence = [f"static-analysis-report:{tool.get('name', 'unknown')}" for tool in tools if str(tool.get("status") or "").lower() == "passed"]
            reason = "静态分析工具已执行，未发现该维度问题。"
        else:
            status = "missing"
            evidence = []
            reason = "缺少可审计静态分析或代码质量输入。"
        coverage.append({"dimension": dimension, "status": status, "evidence": evidence, "reason": reason})
    return coverage


def gate_decision(findings: list[dict], coverage: list[dict], static_report: dict) -> str:
    if any(item.get("blocking") for item in findings):
        return "block"
    if any(item.get("status") in {"missing", "blocked"} for item in coverage):
        return "block"
    tools = static_report.get("tools", []) if isinstance(static_report, dict) else []
    if not tools and static_report.get("waiver", {}).get("status") != "accepted":
        return "block"
    return "pass"


def write_markdown(path: Path, findings: list[dict], coverage: list[dict], decision: str):
    lines = ["# 代码走查报告", "", f"- gate_decision: `{decision}`", f"- findings: `{len(findings)}`", "", "## Findings", "", "| 严重级别 | 代码证据 | 问题描述 | 建议 |", "|---|---|---|---|"]
    for item in findings:
        ev = item.get("code_evidence") or {}
        evidence = f"{ev.get('file', '')}:{ev.get('line_start', '')} ({item.get('dimension')})"
        lines.append(f"| {item.get('severity')} | `{evidence}` | {item.get('problem')} | {item.get('recommendation')} |")
    if not findings:
        lines.append("| info | `-` | 未登记 finding | 继续保留静态分析和人工复核证据 |")
    lines.extend(["", "## Checklist Coverage", "", "| 维度 | 状态 | 证据/原因 |", "|---|---|---|"])
    for item in coverage:
        evidence = ", ".join(item.get("evidence") or []) or item.get("reason", "")
        lines.append(f"| {item.get('dimension')} | {item.get('status')} | {evidence} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_blockers(path: Path, findings: list[dict], coverage: list[dict]):
    lines = ["# Blocker List", ""]
    blockers = [item for item in findings if item.get("blocking")]
    for item in blockers:
        lines.append(f"- [{item.get('severity')}] {item.get('id')}: {item.get('problem')}")
    for item in coverage:
        if item.get("status") in {"missing", "blocked"}:
            lines.append(f"- [coverage:{item.get('status')}] {item.get('dimension')}: {item.get('reason')}")
    if len(lines) == 2:
        lines.append("- 无 blocker")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Generate machine-readable and rich HTML code review artifacts.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="artifacts/code-review")
    parser.add_argument("--code-quality-report", default="")
    parser.add_argument("--static-analysis-report", default="")
    parser.add_argument("--changed-files-report", default="")
    parser.add_argument("--implementation-summary", default="")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--skip-static-analysis-autogen", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output = rel_or_abs(root, args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    plugin_root = Path(__file__).resolve().parents[2]
    quality_report = first_existing([
        rel_or_abs(root, args.code_quality_report),
        root / "artifacts/code-quality-governor/code-quality-report.json",
        root / "artifacts/code-quality/code-quality-report.json",
    ])
    static_report_path = first_existing([
        rel_or_abs(root, args.static_analysis_report),
        root / "artifacts/code-quality-governor/static-analysis-report.json",
        root / "artifacts/code-quality/static-analysis-report.json",
    ])
    if not static_report_path and not args.skip_static_analysis_autogen:
        cmd = [sys.executable, str(plugin_root / "engineering-assistant/scripts/run_static_analysis_tools.py"), "--root", str(root), "--output", str(root / "artifacts/code-quality-governor")]
        if args.allow_download:
            cmd.append("--allow-download")
        subprocess.run(cmd, text=True, check=False)
        static_report_path = root / "artifacts/code-quality-governor/static-analysis-report.json"

    quality = load_json(quality_report) if quality_report else {}
    static = load_json(static_report_path) if static_report_path else {"tools": [], "summary": {}, "missing": "static-analysis-report.json not found"}
    findings = []
    for index, item in enumerate(collect_items(quality), start=1):
        if isinstance(item, dict):
            findings.append(normalize_finding(item, "code_quality", index))
    for index, item in enumerate(collect_items(static), start=1):
        if isinstance(item, dict):
            findings.append(normalize_finding(item, "static_analysis", index))
    findings.extend(tool_findings(static))
    coverage = checklist_coverage(findings, static)
    decision = gate_decision(findings, coverage, static)
    review = {
        "gate_decision": decision,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_artifacts": {
            "code_quality_report": str(quality_report) if quality_report else "",
            "static_analysis_report": str(static_report_path) if static_report_path else "",
        },
        "findings": findings,
        "checklist_coverage": coverage,
        "tool_status": static.get("tools", []),
    }
    review_path = output / "review-comments.json"
    markdown_path = output / "code-review-report.md"
    blocker_path = output / "blocker-list.md"
    html_path = output / "code-review-report.html"
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(markdown_path, findings, coverage, decision)
    write_blockers(blocker_path, findings, coverage)
    render_cmd = [
        sys.executable,
        str(plugin_root / "engineering-assistant/scripts/render_code_review_html.py"),
        "--review-json", str(review_path),
        "--quality-json", str(quality_report or ""),
        "--static-json", str(static_report_path or ""),
        "--markdown", str(markdown_path),
        "--output", str(html_path),
    ]
    subprocess.run(render_cmd, text=True, check=True)
    print(json.dumps({"status": decision, "output": str(output), "artifacts": [str(markdown_path), str(html_path), str(review_path), str(blocker_path)]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
