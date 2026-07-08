#!/usr/bin/env python3
import argparse
import html
import json
import re
from pathlib import Path
from control_runtime import checksum, compact_lines, ensure_control_dir, find_file_patterns, now_iso, read_json, update_artifact_index, validate_target_project_root, write_json

SCHEMA_VERSION = "3.1.0"
DEFAULT_FORBIDDEN = [".git/", ".idea/", "node_modules/", "target/", "build/", "dist/", "coverage/"]
DEFAULT_RULES = [
    "Every changed source file must map to design-contract goals or acceptance criteria.",
    "Do not modify forbidden modules or generated dependency/build directories.",
    "Follow existing repository framework, layering, mapper/repository, service, and test conventions.",
    "Record unresolved business decisions in open-questions.json instead of guessing.",
    "A succeeded stage must not contain blocker or major findings, blocked quality gates, or product-completion blockers.",
]
PLACEHOLDER_RE = re.compile(r"(待 code-development 阶段写入|待确认|todo|tbd|placeholder)", re.IGNORECASE)

def is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER_RE.search(value or ""))

def infer_commands(profile: dict, file_patterns: list[str]):
    commands = []
    raw_quality = profile.get("quality_commands", [])
    raw_items = []
    if isinstance(raw_quality, list):
        raw_items.extend(raw_quality)
    elif isinstance(raw_quality, dict):
        for value in raw_quality.values():
            raw_items.extend(value if isinstance(value, list) else [value])
    for item in raw_items:
        if isinstance(item, str) and not is_placeholder(item):
            commands.append({"id": item.split()[0], "command": item, "required": True})
        elif isinstance(item, dict) and item.get("command") and not is_placeholder(item["command"]):
            commands.append({"id": item.get("id", f"cmd-{len(commands) + 1}"), "command": item["command"], "required": item.get("required", True)})
    pattern_text = "\n".join(file_patterns)
    if not commands and re.search(r"(^|/)pom\.xml$|backend/", pattern_text):
        commands.append({"id": "backend-test", "command": "mvn -q test", "required": True})
    if not commands and "frontend/console-web" in pattern_text:
        commands.append({"id": "frontend-test", "command": "cd frontend/console-web && npm test", "required": True})
        commands.append({"id": "frontend-build", "command": "cd frontend/console-web && npm run build", "required": True})
    if not commands:
        commands.append({"id": "repo-test", "command": "python3 -m unittest discover", "required": True})
    return commands

def grep_lines(lines: list[str], keywords: list[str], limit: int = 12) -> list[str]:
    selected = []
    lowered_keywords = [item.lower() for item in keywords]
    for line in lines:
        lowered = line.lower()
        if any(keyword in lowered for keyword in lowered_keywords) and line not in selected:
            selected.append(line[:240])
        if len(selected) >= limit:
            break
    return selected

def backtick_values(text: str) -> list[str]:
    values = []
    for item in re.findall(r"`([^`\n]+)`", text):
        item = item.strip()
        if item and item not in values:
            values.append(item)
    return values

def infer_expected_contracts(text: str, lines: list[str], file_patterns: list[str]) -> dict:
    ticks = backtick_values(text)
    api_like = [item for item in ticks if item.startswith("/") or "/api/" in item or item.lower().endswith(("request", "response", "controller"))]
    service_like = [item for item in ticks if re.search(r"(Service|UseCase|Application|应用服务|用例)$", item)]
    repo_like = [item for item in ticks if re.search(r"(Repository|Mapper|Port|仓储|持久化|MyBatis)", item, re.IGNORECASE)]
    if not api_like:
        api_like = grep_lines(lines, ["api", "接口", "controller", "request", "response"], 8)
    if not service_like:
        service_like = grep_lines(lines, ["application service", "应用服务", "use case", "用例", "领域服务"], 8)
    if not repo_like:
        repo_like = grep_lines(lines, ["repository", "mapper", "port", "仓储", "持久化", "mybatis"], 8)
    if not api_like and any("frontend/" in item or "backend/" in item for item in file_patterns):
        api_like = ["All changed public API contracts must be explicitly mapped to request/response tests."]
    if not service_like and any("backend/" in item for item in file_patterns):
        service_like = ["Each backend use case must identify one application service boundary and one bounded-context owner."]
    if not repo_like and any("backend/" in item for item in file_patterns):
        repo_like = ["Persistence access must go through repository/mapper adapters declared by the task design."]
    return {"expected_interfaces": api_like[:20], "expected_services": service_like[:20], "expected_repositories_or_mappers": repo_like[:20]}

def infer_technology_adoption_contract(text: str, file_patterns: list[str], profile: dict) -> dict:
    explicit = profile.get("technology_adoption_contract")
    if isinstance(explicit, dict) and explicit:
        return explicit
    frameworks = profile.get("backend_frameworks", {}) if isinstance(profile.get("backend_frameworks"), dict) else {}
    persistence = frameworks.get("persistence") or profile.get("persistence_framework") or ""
    pattern_text = "\n".join(file_patterns)
    backend_like = bool(re.search(r"backend/|pom\.xml|spring|java", pattern_text + "\n" + text, re.IGNORECASE))
    frontend_like = bool(re.search(r"frontend/|react|vite|tsx|jsx|package\.json", pattern_text + "\n" + text, re.IGNORECASE))
    if backend_like and (not persistence or "mybatis" in str(persistence).lower()):
        return {
            "backend_framework": frameworks.get("web") or profile.get("backend_framework") or "Spring Boot",
            "persistence_framework": persistence or "mybatis-plus",
            "required_indicators": ["BaseMapper", "@Mapper", "extends ServiceImpl", "LambdaQueryWrapper"],
            "forbidden_indicators": ["DriverManager.getConnection", "JdbcTemplate", "java.sql.Statement"],
            "minimum_required_indicators": 1,
            "review_required_for": ["JDBC", "direct SQL bypassing mapper/repository"],
        }
    if frontend_like:
        frontend_stack = profile.get("frontend_stack") or "React/Vite"
        return {
            "frontend_stack": frontend_stack,
            "required_indicators": ["React", "Vite", "useState", "useEffect", "render(", "describe("],
            "forbidden_indicators": ["document.querySelector", "innerHTML"],
            "minimum_required_indicators": 1,
            "review_required_for": ["framework replacement", "component library replacement", "direct DOM mutation"],
        }
    return {"required_indicators": [], "forbidden_indicators": [], "minimum_required_indicators": 0, "review_required_for": []}

def infer_required_tests(text: str, file_patterns: list[str], profile: dict) -> list[str]:
    tests = [item.strip() for item in profile.get("required_tests", []) if isinstance(item, str) and item.strip() and not is_placeholder(item)] if isinstance(profile.get("required_tests"), list) else []
    pattern_text = "\n".join(file_patterns)
    if "backend/" in pattern_text:
        tests.extend(["backend unit tests for domain/application invariants and failure paths", "backend architecture boundary tests for DDD dependencies and high cohesion"])
    if "frontend/console-web" in pattern_text:
        tests.extend(["frontend component tests for forms, guards, and error states", "frontend integration tests for real API client and permission-driven navigation"])
    if re.search(r"真实环境|E2E|验收|release", text, re.IGNORECASE):
        tests.append("real environment smoke or Playwright E2E proving frontend-backend interaction with required dependencies")
    if not tests:
        tests.append("task-specific failing test must be written before implementation and pass before review")
    return list(dict.fromkeys(tests))

def esc(value) -> str:
    return html.escape("" if value is None else str(value))

def build_initial_traceability(design_contract: dict, implementation_contract: dict, quality_contract: dict) -> dict:
    rows = []
    seeds = design_contract.get("acceptance_criteria") or design_contract.get("goals") or ["Implement the approved design without expanding scope."]
    for index, item in enumerate(seeds[:20], start=1):
        rows.append({
            "requirement_id": f"REQ-{index:03d}",
            "requirement": item,
            "design_refs": [design_contract.get("source_design", "")],
            "implementation_targets": implementation_contract.get("allowed_modules", []),
            "changed_files": [],
            "tests": implementation_contract.get("required_tests", []),
            "validation_status": "pending_code_development",
            "evidence": {
                "design_contract": "artifacts/_control/design-contract.json",
                "implementation_contract": "artifacts/_control/implementation-contract.json",
                "quality_contract": "artifacts/_control/quality-contract.json",
            },
            "gaps": ["等待 code-development 阶段写入 design-to-code-mapping.yaml、changed-files-report.json 并刷新追踪报告"],
        })
    return {
        "task_id": design_contract.get("task_id"),
        "status": "pending_code_development",
        "source_of_truth": "artifacts/_control/traceability-matrix.json",
        "human_readable_report": "docs/human-readable/traceability-report.html",
        "html_policy": "HTML is human-only and cannot be consumed as agent source evidence",
        "summary": {"requirements": len(rows), "mapped_rows": 0, "gap_rows": len(rows)},
        "rows": rows,
        "required_evidence": quality_contract.get("required_evidence", []),
        "generated_at": now_iso(),
    }

def render_traceability_html(matrix: dict) -> str:
    rows = matrix.get("rows", [])
    summary = matrix.get("summary", {})
    table_rows = []
    for row in rows:
        gaps = row.get("gaps") or []
        status = row.get("validation_status") or "unknown"
        design_cell = "<br>".join(esc(item) for item in row.get("design_refs", [])) or '<span class="muted">未登记</span>'
        target_cell = "<br>".join(esc(item) for item in row.get("implementation_targets", [])) or '<span class="muted">待实现</span>'
        changed_cell = "<br>".join(esc(item) for item in row.get("changed_files", [])) or '<span class="muted">待写入</span>'
        tests_cell = "<br>".join(esc(item) for item in row.get("tests", [])) or '<span class="muted">待确认</span>'
        gaps_cell = "<br>".join(esc(item) for item in gaps)
        table_rows.append(
            "<tr>"
            f"<td><strong>{esc(row.get('requirement_id'))}</strong><div class='muted'>{esc(row.get('requirement'))}</div></td>"
            f"<td>{design_cell}</td>"
            f"<td>{target_cell}</td>"
            f"<td>{changed_cell}</td>"
            f"<td>{tests_cell}</td>"
            f"<td><span class='status'>{esc(status)}</span><div class='gap'>{gaps_cell}</div></td>"
            "</tr>"
        )
    return "\n".join([
        "<!doctype html>",
        '<html lang="zh-CN" data-human-readable-report="traceability">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>需求-设计-代码追踪报告</title>",
        "<style>",
        'body{margin:0;background:#f5f7fb;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}',
        "header{background:#111827;color:#fff;padding:28px 36px}main{padding:24px 36px 56px}",
        "section{background:#fff;border:1px solid #dbe3ef;border-radius:8px;margin:0 0 18px;padding:18px}h1,h2{margin:0 0 12px}",
        ".notice{color:#bfdbfe;margin-top:8px}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}",
        ".metric{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:12px}.metric strong{display:block;font-size:26px;margin-top:4px}",
        "table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid #e5eaf0;padding:9px;text-align:left;vertical-align:top}th{background:#f1f5f9}",
        ".muted{color:#64748b;margin-top:4px}.status{display:inline-block;border-radius:999px;padding:3px 8px;background:#e0f2fe;color:#075985}.gap{color:#9a3412;margin-top:6px}.source{font-size:13px;color:#475569}",
        "</style>",
        "</head><body><header>",
        "<h1>需求-设计-代码追踪报告</h1>",
        f"<div>task_id: <strong>{esc(matrix.get('task_id'))}</strong> · status: <strong>{esc(matrix.get('status'))}</strong></div>",
        '<div class="notice">人工阅览入口。机读事实源是 artifacts/_control/traceability-matrix.json，agent 不得反向读取本 HTML 作为事实输入。</div>',
        "</header><main>",
        '<section class="metrics">',
        f'<div class="metric">需求条目<strong>{esc(summary.get("requirements", len(rows)))}</strong></div>',
        f'<div class="metric">已映射<strong>{esc(summary.get("mapped_rows", 0))}</strong></div>',
        f'<div class="metric">存在缺口<strong>{esc(summary.get("gap_rows", 0))}</strong></div>',
        "</section>",
        "<section><h2>追踪矩阵</h2><table><thead><tr><th>需求</th><th>设计依据</th><th>实现目标</th><th>代码文件</th><th>测试/验证</th><th>状态与缺口</th></tr></thead><tbody>",
        "".join(table_rows) or '<tr><td colspan="6" class="muted">暂无追踪条目</td></tr>',
        "</tbody></table></section>",
        "<section class=\"source\"><h2>证据文件</h2><div>design-contract.json · implementation-contract.json · quality-contract.json · design-to-code-mapping.yaml · changed-files-report.json · design-to-code-validation.json</div></section>",
        "</main></body></html>",
    ])

def write_traceability_outputs(root: Path, control: Path, matrix: dict) -> None:
    matrix_path = control / "traceability-matrix.json"
    html_path = root / "docs/human-readable/traceability-report.html"
    write_json(matrix_path, matrix)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_traceability_html(matrix), encoding="utf-8")
    update_artifact_index(root, matrix_path.name, matrix_path, "json", "implementation-controller")
    update_artifact_index(root, html_path.name, html_path, "html", "implementation-controller")

def main():
    parser = argparse.ArgumentParser(description="Compile an approved design artifact into machine-readable control contracts.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--design", required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--profile")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    design_path = Path(args.design)
    if not design_path.is_absolute():
        design_path = root / design_path
    if design_path.suffix.lower() in {".html", ".htm"}:
        raise SystemExit("HTML artifacts are human-only. Provide the approved MD/JSON/YAML design artifact instead.")
    control = ensure_control_dir(root)
    task = read_json(control / "current-task.json", {})
    profile = read_json(Path(args.profile), {}) if args.profile else task.get("project_profile", {})
    task_id = args.task_id or task.get("task_id") or design_path.stem
    text = design_path.read_text(encoding="utf-8")
    lines = compact_lines(text, 32)
    file_patterns = find_file_patterns(text)
    expected = infer_expected_contracts(text, lines, file_patterns)
    design_contract = {"schema_version": SCHEMA_VERSION, "task_id": task_id, "source_design": str(design_path.relative_to(root)), "source_checksum": checksum(design_path), "generated_at": now_iso(), "goals": lines[:8] or ["Implement the approved design without expanding scope."], "acceptance_criteria": lines[:12], "module_boundaries": {"allowed_from_design": file_patterns, "source": "compiled_from_design_artifact"}, "assumptions": ["The human-approved design is the source of truth for implementation scope."]}
    implementation_contract = {"schema_version": SCHEMA_VERSION, "task_id": task_id, "allowed_modules": file_patterns, "forbidden_modules": DEFAULT_FORBIDDEN, "required_files_or_patterns": file_patterns, "expected_interfaces": expected["expected_interfaces"], "expected_services": expected["expected_services"], "expected_repositories_or_mappers": expected["expected_repositories_or_mappers"], "technology_adoption_contract": infer_technology_adoption_contract(text, file_patterns, profile), "architecture_rules": DEFAULT_RULES, "required_tests": infer_required_tests(text, file_patterns, profile), "done_conditions": ["No changed file is outside allowed scope unless approved.", "Design-to-code validation passes with no blocker or major findings.", "Technology adoption validation passes.", "Rule consumption validation passes.", "Required quality commands pass; missing commands are blocking.", "Open blocking questions are empty."], "generated_at": now_iso()}
    quality_contract = {"schema_version": SCHEMA_VERSION, "task_id": task_id, "required_commands": infer_commands(profile, file_patterns), "required_evidence": ["control_health", "design_to_code_mapping", "traceability_matrix", "traceability_report_html", "technology_adoption", "rule_consumption", "quality_commands"], "quality_gates": ["control_health", "design_to_code_mapping", "traceability_matrix", "technology_adoption", "rule_consumption", "architecture_boundary", "build_lint_test", "semantic_review"], "repair_policy": {"max_attempts": 2, "ask_human_only_for": ["approved design conflict", "business decision missing", "high risk approval", "production action", "repair attempts exhausted"]}, "generated_at": now_iso()}
    write_json(control / "design-contract.json", design_contract)
    write_json(control / "implementation-contract.json", implementation_contract)
    write_json(control / "quality-contract.json", quality_contract)
    traceability_matrix = build_initial_traceability(design_contract, implementation_contract, quality_contract)
    write_traceability_outputs(root, control, traceability_matrix)
    context = ["# Agent Context Pack", "", "## Read First", "- This is the task-scoped context pack. Consume it before broad doc search.", "- Required rule ids must come from `artifacts/rule-governance/task-rule-packs/code-development.json`.", "- A stale changed-files report, missing rule pack, blocking open question, or failed gate means stop and report blocked.", "- Human-readable traceability is in `docs/human-readable/traceability-report.html`; agent source of truth is `artifacts/_control/traceability-matrix.json`.", "", f"- task_id: {task_id}", f"- source_design: {design_contract['source_design']}", f"- source_checksum: {design_contract['source_checksum']}", f"- task_rule_pack: artifacts/rule-governance/task-rule-packs/code-development.json", "", "## Goals", *[f"- {item}" for item in design_contract["goals"]], "", "## Allowed Modules", *[f"- {item}" for item in implementation_contract["allowed_modules"]], "", "## Technology Adoption Contract", f"- {json.dumps(implementation_contract['technology_adoption_contract'], ensure_ascii=False)}", "", "## Required Evidence", *[f"- {item}" for item in quality_contract["required_evidence"]], "", "## Fast Validation Commands", "- python3 engineering-assistant/scripts/validate_strict_control_contracts.py --root <project-root>", "- python3 engineering-assistant/scripts/run_controlled_task.py --root <project-root> --mode audit-readonly", "- python3 engineering-assistant/scripts/run_controlled_task.py --root <project-root> --rule-evidence <evidence-json>", ""]
    (control / "task-context.agent.md").write_text("\n".join(context), encoding="utf-8")
    for name, rel, artifact_type in [("current-subtask.json", control / "current-subtask.json", "json"), ("design-contract.json", control / "design-contract.json", "json"), ("implementation-contract.json", control / "implementation-contract.json", "json"), ("quality-contract.json", control / "quality-contract.json", "json"), ("task-context.agent.md", control / "task-context.agent.md", "markdown")]:
        update_artifact_index(root, name, rel, artifact_type, "implementation-controller")
    active_slice = {
        "schema_version": SCHEMA_VERSION,
        "slice_id": task_id,
        "parent_task_id": task.get("task_id") or task_id,
        "title": task.get("title") or design_path.stem,
        "kind": "implementation_contract",
        "status": "contract_compiled",
        "control_artifacts": {
            "current_task": "artifacts/_control/current-task.json",
            "current_subtask": "artifacts/_control/current-subtask.json",
            "design_contract": str((control / "design-contract.json").relative_to(root)),
            "implementation_contract": str((control / "implementation-contract.json").relative_to(root)),
            "quality_contract": str((control / "quality-contract.json").relative_to(root)),
            "quality_run_report": "artifacts/_control/quality-run-report.json",
            "traceability_matrix": str((control / "traceability-matrix.json").relative_to(root)),
            "traceability_report": "docs/human-readable/traceability-report.html",
            "context_pack": str((control / "task-context.agent.md").relative_to(root)),
        },
        "blockers": [],
        "updated_at": now_iso(),
    }
    task.update({"schema_version": SCHEMA_VERSION, "task_id": task.get("task_id") or task_id, "status": "contract_compiled", "active_slice": active_slice, "current_contracts": active_slice["control_artifacts"], "updated_at": now_iso()})
    write_json(control / "current-task.json", task)
    write_json(control / "current-subtask.json", active_slice)
    print(control / "implementation-contract.json")

if __name__ == "__main__":
    main()
