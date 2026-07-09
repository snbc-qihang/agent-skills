#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

BASELINES = {"baseline_free_codex", "current_engineering_assistant", "curated_tools"}
CATEGORIES = {
    "full_stack_minimal_product",
    "code_drift",
    "document_noise",
    "frontend_product_quality",
    "long_task_recovery",
    "generator_structure",
    "schema_strictness",
    "frontend_delegation",
    "prototype_gate_quality",
    "feedback_evolution",
}
RECOMMENDATIONS = {"keep_and_slim", "split_capabilities", "delegate_to_curated_tools", "retire_skill"}
REPORT_FIELDS = {"pass_rate_delta", "token_or_time_cost_delta", "quality_findings", "doc_noise_score", "frontend_product_score", "skill_sop_metrics", "recommendation"}
DEFAULT_SPEC = Path("effectiveness-evals/evals.json")
DEFAULT_REPORT = Path("effectiveness-evals/reports/effectiveness-report.json")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"{path}: missing file")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid JSON: {exc}")


def normalize(text):
    text = re.sub(r"---.*?---", "", text, count=1, flags=re.S)
    text = re.sub(r"# References / Scripts\n.*", "", text, flags=re.S)
    return " ".join(text.lower().split())


def average_similarity(items):
    if len(items) < 2:
        return 0.0
    scores = []
    for index, left in enumerate(items):
        for right in items[index + 1:]:
            scores.append(SequenceMatcher(None, left, right).ratio())
    return sum(scores) / len(scores)


def compute_skill_sop_metrics(skills_root=Path("skills")):
    docs = {}
    headings = {}
    descriptions = {}
    line_counts = {}
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        skill_id = skill_md.parent.name
        text = skill_md.read_text(encoding="utf-8")
        docs[skill_id] = normalize(text)
        headings[skill_id] = [match.group(1).strip() for match in re.finditer(r"^#\s+(.+)$", text, flags=re.M)]
        descriptions[skill_id] = next((line for line in text.splitlines() if line.startswith("description: ")), "")
        line_counts[skill_id] = len(text.splitlines())
    common = sorted(set.intersection(*(set(value) for value in headings.values()))) if headings else []
    route_ok = [
        line.startswith("description: Use when ")
        and "Do not use" in line
        and "request is about" not in line
        for line in descriptions.values()
    ]
    evidence_ok = [
        "Evidence / Done" in (skills_root / skill_id / "SKILL.md").read_text(encoding="utf-8")
        and "Stop / Escalate" in (skills_root / skill_id / "SKILL.md").read_text(encoding="utf-8")
        for skill_id in docs
    ]
    return {
        "task_sop_skill_count": len(docs),
        "task_sop_average_similarity": round(average_similarity(list(docs.values())), 3),
        "global_average_similarity": round(average_similarity(list(docs.values())), 3),
        "common_heading_count": len(common),
        "common_headings": common,
        "description_route_quality": round(sum(route_ok) / len(route_ok), 3) if route_ok else 0,
        "context_budget": {"max_skill_md_lines": max(line_counts.values()) if line_counts else 0, "pass": all(count <= 120 for count in line_counts.values())},
        "real_output_evidence": {"task_sop_sections_present": all(evidence_ok), "skills_checked": len(evidence_ok)},
    }


def empty_delta():
    return {
        "current_engineering_assistant_vs_baseline_free_codex": None,
        "current_engineering_assistant_vs_curated_tools": None,
        "curated_tools_vs_baseline_free_codex": None,
    }


def validate_spec(path):
    errors = []
    spec = load_json(path)
    root = path.parent
    baseline_ids = {item.get("id") for item in spec.get("baselines", [])}
    if baseline_ids != BASELINES:
        errors.append(f"{path}: baselines must be {sorted(BASELINES)}")
    result_contract = spec.get("result_contract", {})
    missing_fields = REPORT_FIELDS - set(result_contract.get("required_report_fields", []))
    if missing_fields:
        errors.append(f"{path}: result_contract.required_report_fields missing {sorted(missing_fields)}")
    if set(result_contract.get("recommendation_values", [])) != RECOMMENDATIONS:
        errors.append(f"{path}: recommendation_values must be {sorted(RECOMMENDATIONS)}")
    evals = spec.get("evals", [])
    categories = {item.get("category") for item in evals}
    if categories != CATEGORIES:
        errors.append(f"{path}: eval categories must be {sorted(CATEGORIES)}")
    if len(evals) != len(CATEGORIES):
        errors.append(f"{path}: expected exactly {len(CATEGORIES)} effectiveness evals")
    for item in evals:
        eval_id = item.get("id", "<missing>")
        if not item.get("prompt") or len(item["prompt"]) < 80:
            errors.append(f"{eval_id}: prompt must be realistic and at least 80 chars")
        if set(item.get("baselines", [])) != BASELINES:
            errors.append(f"{eval_id}: baselines must include all comparison groups")
        if len(item.get("assertions", [])) < 5:
            errors.append(f"{eval_id}: assertions must include at least 5 checks")
        if len(item.get("grading_dimensions", [])) < 5:
            errors.append(f"{eval_id}: grading_dimensions must include at least 5 dimensions")
        for rel in item.get("input_files", []):
            fixture = root / rel
            if not fixture.exists():
                errors.append(f"{eval_id}: missing input fixture {rel}")
                continue
            payload = load_json(fixture)
            if payload.get("fixture_id") != eval_id:
                errors.append(f"{eval_id}: fixture_id mismatch in {rel}")
    return spec, errors


def base_report(mode, spec, status, state, findings):
    return {
        "status": status,
        "mode": mode,
        "evaluation_state": state,
        "baselines": [item["id"] for item in spec.get("baselines", [])],
        "evals": [item["id"] for item in spec.get("evals", [])],
        "metrics": {"eval_count": len(spec.get("evals", [])), "baseline_count": len(spec.get("baselines", [])), "real_result_count": 0},
        "pass_rate_delta": empty_delta(),
        "token_or_time_cost_delta": empty_delta(),
        "quality_findings": findings,
        "doc_noise_score": None,
        "frontend_product_score": None,
        "skill_sop_metrics": compute_skill_sop_metrics(),
        "recommendation": "keep_and_slim",
        "recommendation_reason": "teamwork spec gate validates short SOP, prototype gate, and feedback evolution before real baseline runs are graded",
        "generated_at": now_iso(),
    }


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Validate and report teamwork skill effectiveness evals.")
    parser.add_argument("--mode", choices=["spec", "grade", "report"], default="spec")
    parser.add_argument("--spec", default=str(DEFAULT_SPEC))
    parser.add_argument("--output", default=str(DEFAULT_REPORT))
    parser.add_argument("--no-write-report", action="store_true")
    args = parser.parse_args()
    spec, errors = validate_spec(Path(args.spec))
    if errors:
        report = base_report(args.mode, spec if isinstance(spec, dict) else {}, "block", "blocked", [{"id": "EFFECTIVENESS-SPEC-INVALID", "severity": "blocker", "summary": item} for item in errors])
    elif args.mode == "spec":
        report = base_report(args.mode, spec, "pass", "spec_ready", [{"id": "EFFECTIVENESS-SPEC-READY", "severity": "info", "summary": "teamwork effectiveness spec, fixtures, and short-SOP metrics are ready."}])
    else:
        report = base_report(args.mode, spec, "waiting_for_input", "waiting_for_results", [{"id": "EFFECTIVENESS-RESULTS-MISSING", "severity": "major", "summary": "缺少真实 baseline/current/curated_tools 运行结果，不能判断插件真实交付收益。"}])
        if args.mode == "report":
            report["mode"] = "report"
    if not args.no_write_report:
        write_report(Path(args.output), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "block":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
