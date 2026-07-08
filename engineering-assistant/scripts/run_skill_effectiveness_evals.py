#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import re

BASELINES = {"baseline_free_codex", "current_engineering_assistant", "curated_tools"}
CATEGORIES = {"full_stack_minimal_product", "code_drift", "document_noise", "frontend_product_quality", "long_task_recovery", "generator_structure", "schema_strictness", "frontend_delegation", "prototype_gate_quality", "feedback_evolution"}
RECOMMENDATIONS = {"keep_and_slim", "split_capabilities", "delegate_to_curated_tools", "retire_skill"}
REPORT_FIELDS = {"pass_rate_delta", "token_or_time_cost_delta", "quality_findings", "doc_noise_score", "frontend_product_score", "skill_sop_metrics", "recommendation"}
DEFAULT_SPEC = Path("effectiveness-evals/evals.json")
DEFAULT_REPORT = Path("effectiveness-evals/reports/effectiveness-report.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"{path}: missing file")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid JSON: {exc}")


def validate_spec(spec_path: Path) -> tuple[dict, list[str]]:
    errors = []
    spec = load_json(spec_path)
    root = spec_path.parent
    baseline_ids = {item.get("id") for item in spec.get("baselines", [])}
    if baseline_ids != BASELINES:
        errors.append(f"{spec_path}: baselines must be {sorted(BASELINES)}")
    result_contract = spec.get("result_contract", {})
    missing_report_fields = REPORT_FIELDS - set(result_contract.get("required_report_fields", []))
    if missing_report_fields:
        errors.append(f"{spec_path}: result_contract.required_report_fields missing {sorted(missing_report_fields)}")
    if set(result_contract.get("recommendation_values", [])) != RECOMMENDATIONS:
        errors.append(f"{spec_path}: recommendation_values must be {sorted(RECOMMENDATIONS)}")
    evals = spec.get("evals", [])
    categories = {item.get("category") for item in evals}
    if categories != CATEGORIES:
        errors.append(f"{spec_path}: eval categories must be {sorted(CATEGORIES)}")
    if len(evals) != len(CATEGORIES):
        errors.append(f"{spec_path}: expected exactly {len(CATEGORIES)} effectiveness evals")
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


def empty_delta() -> dict:
    return {
        "current_engineering_assistant_vs_baseline_free_codex": None,
        "current_engineering_assistant_vs_curated_tools": None,
        "curated_tools_vs_baseline_free_codex": None,
    }


def normalized_skill_text(text: str) -> str:
    text = re.sub(r"---.*?---", "", text, count=1, flags=re.S)
    return " ".join(text.lower().split())


def average_similarity(items: list[str]) -> float:
    if len(items) < 2:
        return 0.0
    scores = []
    for left_index, left in enumerate(items):
        for right in items[left_index + 1:]:
            scores.append(SequenceMatcher(None, left, right).ratio())
    return sum(scores) / len(scores)


def compute_skill_sop_metrics(skills_root: Path = Path("skills")) -> dict:
    docs = {}
    headings_by_skill = {}
    descriptions = {}
    line_counts = {}
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        skill_id = skill_md.parent.name
        text = skill_md.read_text(encoding="utf-8")
        docs[skill_id] = normalized_skill_text(text)
        headings_by_skill[skill_id] = [match.group(1).strip() for match in re.finditer(r"^#\s+(.+)$", text, flags=re.M)]
        descriptions[skill_id] = next((line for line in text.splitlines() if line.startswith("description: ")), "")
        line_counts[skill_id] = len(text.splitlines())
    common_headings = sorted(set.intersection(*(set(values) for values in headings_by_skill.values()))) if headings_by_skill else []
    route_quality = [
        desc.startswith("description: Use when ")
        and "Do not use" in desc
        and "request is about" not in desc
        for desc in descriptions.values()
    ]
    evidence_ready = [
        "Evidence / Done" in (skills_root / skill_id / "SKILL.md").read_text(encoding="utf-8")
        and "Stop / Escalate" in (skills_root / skill_id / "SKILL.md").read_text(encoding="utf-8")
        for skill_id in docs
    ]
    return {
        "task_sop_skill_count": len(docs),
        "task_sop_average_similarity": round(average_similarity(list(docs.values())), 3),
        "global_average_similarity": round(average_similarity(list(docs.values())), 3),
        "common_heading_count": len(common_headings),
        "common_headings": common_headings,
        "description_route_quality": round(sum(route_quality) / len(route_quality), 3) if route_quality else 0,
        "context_budget": {"max_skill_md_lines": max(line_counts.values()) if line_counts else 0, "pass": all(count <= 120 for count in line_counts.values())},
        "real_output_evidence": {"task_sop_sections_present": all(evidence_ready), "skills_checked": len(evidence_ready)},
    }


def base_report(mode: str, spec: dict, status: str, state: str, findings: list[dict]) -> dict:
    return {
        "status": status,
        "mode": mode,
        "evaluation_state": state,
        "baselines": [item["id"] for item in spec.get("baselines", [])],
        "evals": [item["id"] for item in spec.get("evals", [])],
        "metrics": {
            "eval_count": len(spec.get("evals", [])),
            "baseline_count": len(spec.get("baselines", [])),
            "real_result_count": 0,
        },
        "pass_rate_delta": empty_delta(),
        "token_or_time_cost_delta": empty_delta(),
        "quality_findings": findings,
        "doc_noise_score": None,
        "frontend_product_score": None,
        "skill_sop_metrics": compute_skill_sop_metrics(),
        "recommendation": "keep_and_slim",
        "recommendation_reason": "provisional default until real with-plugin/baseline runs are graded",
        "generated_at": now_iso(),
    }


def load_result_files(results_dir: Path) -> list[dict]:
    if not results_dir.exists():
        return []
    return [load_json(path) for path in sorted(results_dir.glob("*.json"))]


def score_results(spec: dict, result_files: list[dict]) -> dict:
    if not result_files:
        return base_report(
            "grade",
            spec,
            "waiting_for_input",
            "waiting_for_results",
            [{"id": "EFFECTIVENESS-RESULTS-MISSING", "severity": "major", "summary": "缺少真实 baseline/current/curated_tools 运行结果，不能判断插件是否有效。"}],
        )
    by_baseline = {baseline: [] for baseline in BASELINES}
    cost_by_baseline = {baseline: [] for baseline in BASELINES}
    findings = []
    doc_noise_scores = []
    frontend_scores = []
    for result in result_files:
        baseline = result.get("baseline")
        eval_id = result.get("eval_id")
        if baseline not in BASELINES:
            findings.append({"id": "UNKNOWN-BASELINE", "severity": "blocker", "summary": f"{eval_id}: unknown baseline {baseline}"})
            continue
        score = result.get("pass_rate")
        if not isinstance(score, (int, float)):
            findings.append({"id": "MISSING-PASS-RATE", "severity": "blocker", "summary": f"{eval_id}/{baseline}: pass_rate missing"})
            continue
        by_baseline[baseline].append(float(score))
        if isinstance(result.get("token_or_time_cost"), (int, float)):
            cost_by_baseline[baseline].append(float(result["token_or_time_cost"]))
        if isinstance(result.get("doc_noise_score"), (int, float)):
            doc_noise_scores.append(float(result["doc_noise_score"]))
        if isinstance(result.get("frontend_product_score"), (int, float)):
            frontend_scores.append(float(result["frontend_product_score"]))
        findings.extend(result.get("quality_findings", []))
    means = {key: (sum(values) / len(values) if values else None) for key, values in by_baseline.items()}
    deltas = {
        "current_engineering_assistant_vs_baseline_free_codex": None if means["current_engineering_assistant"] is None or means["baseline_free_codex"] is None else means["current_engineering_assistant"] - means["baseline_free_codex"],
        "current_engineering_assistant_vs_curated_tools": None if means["current_engineering_assistant"] is None or means["curated_tools"] is None else means["current_engineering_assistant"] - means["curated_tools"],
            "curated_tools_vs_baseline_free_codex": None if means["curated_tools"] is None or means["baseline_free_codex"] is None else means["curated_tools"] - means["baseline_free_codex"],
    }
    cost_means = {key: (sum(values) / len(values) if values else None) for key, values in cost_by_baseline.items()}
    cost_deltas = {
        "current_engineering_assistant_vs_baseline_free_codex": None if cost_means["current_engineering_assistant"] is None or cost_means["baseline_free_codex"] is None else cost_means["current_engineering_assistant"] - cost_means["baseline_free_codex"],
        "current_engineering_assistant_vs_curated_tools": None if cost_means["current_engineering_assistant"] is None or cost_means["curated_tools"] is None else cost_means["current_engineering_assistant"] - cost_means["curated_tools"],
        "curated_tools_vs_baseline_free_codex": None if cost_means["curated_tools"] is None or cost_means["baseline_free_codex"] is None else cost_means["curated_tools"] - cost_means["baseline_free_codex"],
    }
    recommendation = "keep_and_slim"
    current_vs_free = deltas["current_engineering_assistant_vs_baseline_free_codex"]
    current_vs_curated = deltas["current_engineering_assistant_vs_curated_tools"]
    if current_vs_free is not None and current_vs_curated is not None:
        if current_vs_free < 0 and current_vs_curated < 0:
            recommendation = "retire_skill"
        elif current_vs_curated < 0:
            recommendation = "delegate_to_curated_tools"
        elif current_vs_free < 0.05:
            recommendation = "split_capabilities"
    status = "block" if any(item.get("severity") == "blocker" for item in findings) else "pass"
    return {
        "status": status,
        "mode": "grade",
        "evaluation_state": "graded" if status == "pass" else "blocked",
        "baselines": [item["id"] for item in spec.get("baselines", [])],
        "evals": [item["id"] for item in spec.get("evals", [])],
        "metrics": {"eval_count": len(spec.get("evals", [])), "baseline_count": len(spec.get("baselines", [])), "real_result_count": len(result_files), "mean_pass_rate": means, "mean_token_or_time_cost": cost_means},
        "pass_rate_delta": deltas,
        "token_or_time_cost_delta": cost_deltas,
        "quality_findings": findings,
        "doc_noise_score": sum(doc_noise_scores) / len(doc_noise_scores) if doc_noise_scores else None,
        "frontend_product_score": sum(frontend_scores) / len(frontend_scores) if frontend_scores else None,
        "skill_sop_metrics": compute_skill_sop_metrics(),
        "recommendation": recommendation,
        "generated_at": now_iso(),
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Validate and report engineering-assistant skill effectiveness evals.")
    parser.add_argument("--mode", choices=["spec", "grade", "report"], default="spec")
    parser.add_argument("--spec", default=str(DEFAULT_SPEC))
    parser.add_argument("--results-dir", default="effectiveness-evals/results")
    parser.add_argument("--output", default=str(DEFAULT_REPORT))
    parser.add_argument("--no-write-report", action="store_true")
    args = parser.parse_args()
    spec_path = Path(args.spec)
    spec, errors = validate_spec(spec_path)
    if errors:
        report = base_report(args.mode, spec if isinstance(spec, dict) else {}, "block", "blocked", [{"id": "EFFECTIVENESS-SPEC-INVALID", "severity": "blocker", "summary": item} for item in errors])
    elif args.mode == "spec":
        report = base_report(args.mode, spec, "pass", "spec_ready", [{"id": "EFFECTIVENESS-SPEC-READY", "severity": "info", "summary": "评测规格、baseline、fixture 和报告字段已就绪；尚未运行真实对照任务。"}])
    else:
        report = score_results(spec, load_result_files(Path(args.results_dir)))
        if args.mode == "report":
            report["mode"] = "report"
    if not args.no_write_report:
        write_report(Path(args.output), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "block":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
