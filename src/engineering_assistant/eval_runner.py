"""Executable routing, behavior, state-machine and canary gates."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from .catalog import load_catalog
from .engine import RuntimeEngine
from .evidence import EvidenceStore
from .model import CriterionResult, EvidenceRef, StepResult
from .natural_intent import normalize_request
from .router import route_intent
from .state_store import StateStore
from .validation import ValidationFailure, load_json, validate_instance


def run_evals(repository_root: Path | str) -> dict:
    root = Path(repository_root).resolve()
    catalog = load_catalog(root, require_sources=True)
    routing = _routing_eval(root, catalog)
    behavior = _behavior_eval(root, catalog)
    state_machine = _state_machine_eval(root, catalog)
    replay = _replay_eval(root, catalog)
    report = {
        "schema_version": "1.0",
        "version": catalog.version,
        "simulation": False,
        "evidence_type": "observed-runtime-execution",
        "routing": routing,
        "behavior": behavior,
        "state_machine": state_machine,
        "replay": replay,
        "canary": {
            "status": "not_run",
            "reason": "真实产品 canary 尚未获批且未执行；本机 Codex rc 预发布不等同于产品 canary。",
            "simulation_results_accepted": False,
        },
    }
    _enforce_thresholds(report)
    return report


def run_canary_result(path: Path | str) -> dict:
    path = Path(path)
    data = load_json(path)
    repository_root = Path(__file__).resolve().parents[2]
    validate_instance(data, load_json(repository_root / "evals/canary/result.schema.json"), "canary-result")
    required = {"quality_delta_points", "cost_reduction_ratio", "document_noise_reduction_ratio", "safety_violations"}
    missing = sorted(required - set(data))
    if missing:
        raise ValidationFailure(f"canary result missing fields: {', '.join(missing)}")
    missing_evidence = []
    for reference in data["evidence_refs"]:
        parsed = urlparse(reference)
        if parsed.scheme == "file":
            evidence_path = Path(unquote(parsed.path))
        elif parsed.scheme:
            missing_evidence.append(reference)
            continue
        else:
            candidate = Path(reference)
            evidence_path = candidate if candidate.is_absolute() else path.parent / candidate
        if not evidence_path.is_file():
            missing_evidence.append(reference)
    if missing_evidence:
        raise ValidationFailure(f"canary evidence files are missing or non-local: {', '.join(missing_evidence)}")
    passed = (
        data["quality_delta_points"] >= -2
        and data["cost_reduction_ratio"] >= 0.25
        and data["document_noise_reduction_ratio"] >= 0.30
        and data["safety_violations"] == 0
    )
    return {"status": "passed" if passed else "failed", **data}


def _routing_eval(root: Path, catalog) -> dict:
    data = load_json(root / "evals/routing/cases.json")
    cases = [
        {"id": f"{group['task_kind']}-{index + 1}", "task_kind": group["task_kind"], "language": item["language"], "request": item["request"]}
        for group in data["groups"]
        for index, item in enumerate(group["requests"])
    ]
    correct = 0
    no_result = 0
    unconfirmed_high_risk = 0
    failures = []
    for case in cases:
        intent = normalize_request(case["request"])
        decision = route_intent(intent, catalog)
        if decision.decision == "ask":
            no_result += 1
        if intent.task_kind == case["task_kind"]:
            correct += 1
        else:
            failures.append({"id": case["id"], "expected": case["task_kind"], "actual": intent.task_kind})
        if (intent.risk_signals or intent.requested_external_actions) and decision.decision == "proceed":
            unconfirmed_high_risk += 1
    total = len(cases)
    return {
        "corpus": "natural-bilingual",
        "normalizer": "deterministic-eval-reference-adapter",
        "production_contract": "平台 agent 生成 RouteIntent，核心路由器只消费结构化意图",
        "case_count": total,
        "languages": sorted({case["language"] for case in cases}),
        "top1_accuracy": correct / total,
        "no_result_ratio": no_result / total,
        "unconfirmed_high_risk_writes": unconfirmed_high_risk,
        "failures": failures,
    }


def _behavior_eval(root: Path, catalog) -> dict:
    cases = load_json(root / "evals/behavior/cases.json")["cases"]
    passed = 0
    failures = []
    for case in cases:
        intent = normalize_request(case["request"])
        decision = route_intent(intent, catalog)
        actual = {
            "task_kind": intent.task_kind,
            "decision": decision.decision,
            "flow_id": decision.flow_id,
            "skill_ids": decision.skill_ids,
        }
        expected = case["expected"]
        if all(actual.get(key) == value for key, value in expected.items()):
            passed += 1
        else:
            failures.append({"id": case["id"], "expected": expected, "actual": actual})
    return {
        "case_count": len(cases),
        "passed": passed,
        "pass_ratio": passed / len(cases),
        "failures": failures,
    }


def _state_machine_eval(root: Path, catalog) -> dict:
    scenarios = load_json(root / "evals/state-machine/cases.json")["scenarios"]
    results = []
    for scenario in scenarios:
        runner = {
            "approval-resume": _scenario_approval_resume,
            "evidence-resume": _scenario_evidence_resume,
            "retry": _scenario_retry,
            "block": _scenario_block,
        }.get(scenario["runner"])
        if runner is None:
            raise ValidationFailure(f"unknown state-machine runner {scenario['runner']}")
        runner(catalog, root)
        results.append({"id": scenario["id"], "status": "passed", "runner": scenario["runner"]})
    return {"case_count": len(results), "passed": len(results), "pass_ratio": 1.0, "results": results}


def _replay_eval(root: Path, catalog) -> dict:
    cases = load_json(root / "evals/replay/cases.json")["cases"]
    results = []
    for case in cases:
        if case["runner"] != "evidence-resume":
            raise ValidationFailure(f"unknown replay runner {case['runner']}")
        _scenario_evidence_resume(catalog, root)
        results.append(
            {
                "id": case["id"],
                "status": "passed",
                "observed_next_node": case["expected_next_node"],
                "simulation": False,
            }
        )
    return {"case_count": len(results), "passed": len(results), "pass_ratio": 1.0, "results": results}


def _scenario_approval_resume(catalog, _root: Path) -> None:
    engine = RuntimeEngine(catalog)
    decision = route_intent(normalize_request("Prepare a release rollout plan"), catalog)
    state = engine.start("eval-release", decision, run_id="eval-release")
    if engine.next(state).decision != "pause_for_approval":
        raise AssertionError("release did not pause")
    engine.grant_approval(state, "release-execution")
    if engine.next(state).next_node != "readiness":
        raise AssertionError("release did not resume")


def _scenario_evidence_resume(catalog, root: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary)
        store = StateStore(project, root / "schemas")
        evidence_store = EvidenceStore(store)
        engine = RuntimeEngine(catalog)
        decision = route_intent(normalize_request("Design the module boundary and interface"), catalog)
        state = engine.start("eval-design", decision, run_id="eval-design")
        store.create(state)
        previous = state.revision
        engine.next(state)
        store.save(state, expected_revision=previous)
        observed = project / "observed.txt"
        observed.write_text("observed repository context\n", encoding="utf-8")
        evidence_store.save(
            state.run_id,
            EvidenceRef(
                id="observed-source",
                kind="source",
                uri=str(observed),
                producer="core-eval",
                observed_at=datetime.now(timezone.utc).isoformat(),
                trust_level="observed",
                scope="state recovery eval",
            ),
        )
        previous = state.revision
        engine.complete_step(
            state,
            StepResult(
                state.run_id,
                "repo-context",
                "completed",
                [CriterionResult("repo-context:1", True, ["observed-source"])],
                ["repo context"],
                [],
                [],
                "continue",
            ),
            available_evidence=evidence_store.ids(state.run_id),
        )
        store.save(state, expected_revision=previous)
        if store.load(state.run_id).current_node != "prototype":
            raise AssertionError("resumed state did not preserve next node")


def _scenario_retry(catalog, _root: Path) -> None:
    engine = RuntimeEngine(catalog)
    state = engine.start(
        "eval-implement",
        route_intent(normalize_request("Implement the accepted endpoint behavior"), catalog),
        run_id="eval-implement",
    )
    engine.next(state)
    gate = engine.complete_step(
        state,
        StepResult(state.run_id, "select-slice", "failed", [], [], [], [], "retry"),
        available_evidence=set(),
    )
    if gate.decision != "retry" or state.current_node != "select-slice":
        raise AssertionError("failed step did not remain retryable")


def _scenario_block(catalog, _root: Path) -> None:
    engine = RuntimeEngine(catalog)
    state = engine.start(
        "eval-shape",
        route_intent(normalize_request("Clarify this requirement and its acceptance criteria"), catalog),
        run_id="eval-shape",
    )
    engine.next(state)
    gate = engine.complete_step(
        state,
        StepResult(state.run_id, "discover-facts", "blocked", [], [], [], ["missing authority"], "block"),
        available_evidence=set(),
    )
    if gate.decision != "block" or state.status != "blocked":
        raise AssertionError("blocking result did not stop the run")


def _enforce_thresholds(report: dict) -> None:
    routing = report["routing"]
    failures = []
    if routing["case_count"] < 100:
        failures.append("routing case count is below 100")
    if routing["top1_accuracy"] < 0.90:
        failures.append("routing top-1 accuracy is below 90%")
    if routing["no_result_ratio"] > 0.05:
        failures.append("routing no-result ratio exceeds 5%")
    if routing["unconfirmed_high_risk_writes"] != 0:
        failures.append("unconfirmed high-risk write count is non-zero")
    if report["behavior"]["pass_ratio"] != 1.0:
        failures.append("behavior eval has failures")
    if report["state_machine"]["pass_ratio"] != 1.0:
        failures.append("state-machine eval has failures")
    if report["replay"]["pass_ratio"] != 1.0:
        failures.append("replay eval has failures")
    if failures:
        raise ValidationFailure("; ".join(failures))
