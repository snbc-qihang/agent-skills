#!/usr/bin/env python3
import argparse
import html
import json
import re
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, read_json, update_artifact_index, validate_target_project_root, write_json

PATH_RE = re.compile(r"[A-Za-z0-9_./{}*-]+\.(?:java|kt|go|py|ts|tsx|js|jsx|vue|xml|sql|yaml|yml|json|md)$")
REQ_RE = re.compile(r"\bREQ[-_]?\d+\b", re.IGNORECASE)

def esc(value) -> str:
    return html.escape("" if value is None else str(value))

def unique(items):
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result

def existing_json(root: Path, *candidates: str) -> dict:
    for item in candidates:
        path = root / item
        if path.exists():
            return read_json(path, {})
    return {}

def existing_text(root: Path, *candidates: str) -> tuple[str, str]:
    for item in candidates:
        path = root / item
        if path.exists():
            return item, path.read_text(encoding="utf-8")
    return "", ""

def mapping_from_text(text: str) -> dict:
    result = {"requirement_refs": [], "design_refs": [], "changed_files": [], "tests": []}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        result["requirement_refs"].extend(REQ_RE.findall(line))
        for token in re.split(r"[,，\s]+", line):
            token = token.strip().strip("`'\"[](){}，,.;；:")
            if PATH_RE.search(token):
                if re.search(r"test|spec|自测|测试", token, re.IGNORECASE):
                    result["tests"].append(token)
                else:
                    result["changed_files"].append(token)
        if any(word in line.lower() for word in ["design", "详细设计", "概要设计", "section", "章节"]):
            result["design_refs"].append(line[:240])
    return {key: unique(value) for key, value in result.items()}

def rows_from_contracts(design: dict, implementation: dict, quality: dict, changed_report: dict, validation: dict, mapping: dict) -> list[dict]:
    seeds = design.get("acceptance_criteria") or design.get("goals") or ["Implement the approved design without expanding scope."]
    changed_files = changed_report.get("changed_files") or mapping.get("changed_files") or []
    validation_status = validation.get("status") or "pending_validation"
    validation_findings = validation.get("findings") or []
    rows = []
    explicit_req_ids = mapping.get("requirement_refs") or []
    for index, item in enumerate(seeds[:40], start=1):
        req_id = explicit_req_ids[index - 1] if index <= len(explicit_req_ids) else f"REQ-{index:03d}"
        row_files = changed_files
        gaps = []
        if not row_files:
            gaps.append("尚未登记 changed-files-report.json 或 design-to-code-mapping.yaml")
        if not mapping.get("requirement_refs"):
            gaps.append("design-to-code-mapping.yaml 未提供逐需求稳定编号映射")
        if validation_status != "pass":
            gaps.append("design-to-code-validation.json 未通过或尚未生成")
        rows.append({
            "requirement_id": req_id,
            "requirement": item,
            "design_refs": unique([design.get("source_design", "")] + mapping.get("design_refs", [])),
            "implementation_targets": implementation.get("allowed_modules", []),
            "changed_files": row_files,
            "tests": unique((implementation.get("required_tests") or []) + mapping.get("tests", [])),
            "validation_status": validation_status,
            "validation_findings": validation_findings,
            "evidence": {
                "design_contract": "artifacts/_control/design-contract.json",
                "implementation_contract": "artifacts/_control/implementation-contract.json",
                "quality_contract": "artifacts/_control/quality-contract.json",
                "changed_files_report": "artifacts/_control/changed-files-report.json",
                "design_to_code_validation": "artifacts/_control/design-to-code-validation.json",
                "design_to_code_mapping": "artifacts/code-development/design-to-code-mapping.yaml",
            },
            "gaps": unique(gaps),
        })
    return rows

def render_html(matrix: dict) -> str:
    rows = matrix.get("rows", [])
    summary = matrix.get("summary", {})
    table = []
    for row in rows:
        design = "<br>".join(esc(item) for item in row.get("design_refs", [])) or '<span class="muted">未登记</span>'
        targets = "<br>".join(esc(item) for item in row.get("implementation_targets", [])) or '<span class="muted">未登记</span>'
        files = "<br>".join(esc(item) for item in row.get("changed_files", [])) or '<span class="muted">待实现</span>'
        tests = "<br>".join(esc(item) for item in row.get("tests", [])) or '<span class="muted">待确认</span>'
        gaps = "<br>".join(esc(item) for item in row.get("gaps", [])) or '<span class="ok">无</span>'
        table.append(
            "<tr>"
            f"<td><strong>{esc(row.get('requirement_id'))}</strong><div class='sub'>{esc(row.get('requirement'))}</div></td>"
            f"<td>{design}</td><td>{targets}</td><td>{files}</td><td>{tests}</td>"
            f"<td><span class='pill'>{esc(row.get('validation_status'))}</span><div class='gap'>{gaps}</div></td>"
            "</tr>"
        )
    evidence_items = matrix.get("evidence_files", [])
    evidence = "".join(f"<li>{esc(item)}</li>" for item in evidence_items)
    return "\n".join([
        "<!doctype html>",
        '<html lang="zh-CN" data-human-readable-report="traceability">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>需求-设计-代码追踪报告</title>",
        "<style>",
        'body{margin:0;background:#f4f6fa;color:#18212f;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}',
        "header{background:#111827;color:#fff;padding:30px 36px}",
        "main{padding:24px 36px 60px}",
        "section{background:#fff;border:1px solid #d8e1ee;border-radius:8px;margin-bottom:18px;padding:18px}",
        "h1,h2{margin:0 0 12px}.notice{color:#c7d2fe}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}",
        ".metric{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:12px}.metric strong{display:block;font-size:26px;margin-top:4px}",
        "table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid #e5eaf0;padding:9px;text-align:left;vertical-align:top}th{background:#f1f5f9}",
        ".sub,.muted{color:#64748b;margin-top:4px}.pill{display:inline-block;border-radius:999px;padding:3px 8px;background:#e0f2fe;color:#075985}.gap{margin-top:6px;color:#9a3412}.ok{color:#166534}",
        "</style>",
        "</head>",
        "<body>",
        "<header>",
        "<h1>需求-设计-代码追踪报告</h1>",
        f"<div>task_id: <strong>{esc(matrix.get('task_id'))}</strong> · status: <strong>{esc(matrix.get('status'))}</strong></div>",
        '<div class="notice">人工阅览入口。机读事实源是 artifacts/_control/traceability-matrix.json；agent 不得反向读取本 HTML 作为事实输入。</div>',
        "</header>",
        "<main>",
        '<section class="metrics">',
        f'<div class="metric">需求条目<strong>{esc(summary.get("requirements", len(rows)))}</strong></div>',
        f'<div class="metric">已映射代码<strong>{esc(summary.get("rows_with_code", 0))}</strong></div>',
        f'<div class="metric">存在缺口<strong>{esc(summary.get("gap_rows", 0))}</strong></div>',
        "</section>",
        "<section><h2>追踪矩阵</h2><table><thead><tr><th>需求</th><th>设计依据</th><th>实现目标</th><th>代码文件</th><th>测试/验证</th><th>状态与缺口</th></tr></thead><tbody>",
        "".join(table) or '<tr><td colspan="6" class="muted">暂无追踪条目</td></tr>',
        "</tbody></table></section>",
        f"<section><h2>证据文件</h2><ul>{evidence}</ul></section>",
        "</main></body></html>",
    ])

def main():
    parser = argparse.ArgumentParser(description="Build machine-readable traceability matrix and rich human-readable HTML report.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", default="artifacts/_control/traceability-matrix.json")
    parser.add_argument("--html-output", default="docs/human-readable/traceability-report.html")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    control = ensure_control_dir(root)
    design = read_json(control / "design-contract.json", {})
    implementation = read_json(control / "implementation-contract.json", {})
    quality = read_json(control / "quality-contract.json", {})
    changed_report = existing_json(root, "artifacts/_control/changed-files-report.json", "artifacts/code-development/changed-files-report.json")
    validation = existing_json(root, "artifacts/_control/design-to-code-validation.json")
    mapping_path, mapping_text = existing_text(root, "artifacts/code-development/design-to-code-mapping.yaml", "artifacts/_control/design-to-code-mapping.yaml")
    mapping = mapping_from_text(mapping_text)
    rows = rows_from_contracts(design, implementation, quality, changed_report, validation, mapping)
    matrix = {
        "task_id": design.get("task_id") or implementation.get("task_id"),
        "status": "pass" if rows and all(not row.get("gaps") for row in rows) else "needs_attention",
        "source_of_truth": args.output,
        "human_readable_report": args.html_output,
        "html_policy": "HTML is human-only and cannot be consumed as agent source evidence",
        "mapping_source": mapping_path,
        "summary": {"requirements": len(rows), "rows_with_code": sum(1 for row in rows if row.get("changed_files")), "gap_rows": sum(1 for row in rows if row.get("gaps"))},
        "rows": rows,
        "evidence_files": unique(["artifacts/_control/design-contract.json", "artifacts/_control/implementation-contract.json", "artifacts/_control/quality-contract.json", mapping_path, "artifacts/_control/changed-files-report.json", "artifacts/_control/design-to-code-validation.json"]),
        "generated_at": now_iso(),
    }
    matrix_path = root / args.output
    html_path = root / args.html_output
    write_json(matrix_path, matrix)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(matrix), encoding="utf-8")
    update_artifact_index(root, matrix_path.name, matrix_path, "json", "build_traceability_report")
    update_artifact_index(root, html_path.name, html_path, "html", "build_traceability_report")
    print(json.dumps({"matrix": str(matrix_path), "html": str(html_path), "status": matrix["status"]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
