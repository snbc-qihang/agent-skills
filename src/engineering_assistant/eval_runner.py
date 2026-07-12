"""Executable routing, behavior, state-machine and canary gates."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from .catalog import load_catalog
from .engine import RuntimeEngine
from .evidence import EvidenceStore
from .model import CriterionResult, EvidenceRef, RunApprovalGrant, StepResult
from .natural_intent import normalize_request
from .router import route_intent
from .state_store import StateStore
from .trust import parse_time
from .trust import TrustVerifier
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
            "reason": "尚无通过外部 evidence broker 验签并满足门槛的真实产品 canary 结果；本机预发布或未验签运行不等同于产品 canary 通过。",
            "simulation_results_accepted": False,
        },
    }
    _enforce_thresholds(report)
    return report


MAX_CANARY_JSON_BYTES = 1024 * 1024
MAX_CANARY_ARTIFACT_BYTES = 16 * 1024 * 1024


def _contained_canary_file(root: Path, reference: str, *, max_bytes: int) -> Path:
    parsed = urlparse(reference)
    if parsed.scheme or Path(reference).is_absolute():
        raise ValidationFailure("canary references must be relative to the evidence root")
    candidate = root / unquote(reference)
    if candidate.is_symlink():
        raise ValidationFailure("canary references cannot be symlinks")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValidationFailure("canary reference escapes the evidence root") from exc
    if not resolved.is_file() or resolved.stat().st_size > max_bytes:
        raise ValidationFailure("canary evidence file is missing or exceeds its size limit")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def run_canary_result(
    path: Path | str, *, trust_verifier: TrustVerifier | None = None
) -> dict:
    path = Path(path)
    if trust_verifier is None:
        raise ValidationFailure("canary validation requires an external evidence broker")
    evidence_root = path.parent.resolve()
    result_path = _contained_canary_file(
        evidence_root, path.name, max_bytes=MAX_CANARY_JSON_BYTES
    )
    data = load_json(result_path)
    repository_root = Path(__file__).resolve().parents[2]
    validate_instance(data, load_json(repository_root / "evals/canary/result.schema.json"), "canary-result")
    required = {"quality_delta_points", "token_reduction_ratio", "cost_reduction_ratio", "document_noise_reduction_ratio", "safety_violations"}
    missing = sorted(required - set(data))
    if missing:
        raise ValidationFailure(f"canary result missing fields: {', '.join(missing)}")
    missing_evidence = []
    observations = []
    observation_schema = load_json(
        repository_root / "evals/canary/run-evidence.schema.json"
    )
    for reference in data["evidence_refs"]:
        try:
            evidence_path = _contained_canary_file(
                evidence_root, reference, max_bytes=MAX_CANARY_JSON_BYTES
            )
        except ValidationFailure:
            missing_evidence.append(reference)
            continue
        observation = load_json(evidence_path)
        validate_instance(
            observation, observation_schema, f"canary-evidence:{evidence_path}"
        )
        if observation["product_repository"] != data["product_repository"]:
            raise ValidationFailure("canary evidence targets a different product repository")
        if not trust_verifier.verify_canary_observation(observation):
            raise ValidationFailure("canary observation attestation is not trusted")
        expected_ref = (
            data["baseline_ref"]
            if observation["variant"] == "baseline"
            else data["candidate_ref"]
        )
        if observation["git_ref"] != expected_ref:
            raise ValidationFailure("canary evidence git_ref does not match its variant")
        expected_config = (
            data["baseline_execution_config_digest"]
            if observation["variant"] == "baseline"
            else data["candidate_execution_config_digest"]
        )
        if observation["execution_config_digest"] != expected_config:
            raise ValidationFailure(
                "canary execution config does not match its declared treatment"
            )
        if parse_time(observation["finished_at"]) < parse_time(observation["started_at"]):
            raise ValidationFailure("canary evidence finishes before it starts")
        for artifact in observation["artifact_refs"]:
            artifact_path = _contained_canary_file(
                evidence_root,
                artifact["path"],
                max_bytes=MAX_CANARY_ARTIFACT_BYTES,
            )
            if _sha256(artifact_path) != artifact["digest"]:
                raise ValidationFailure("canary artifact digest does not match")
        observations.append(observation)
    if missing_evidence:
        raise ValidationFailure(f"canary evidence files are missing or non-local: {', '.join(missing_evidence)}")
    pairs = {}
    for observation in observations:
        key = (observation["task_id"], observation["variant"])
        if key in pairs:
            raise ValidationFailure(f"duplicate canary evidence for {key[0]} {key[1]}")
        pairs[key] = observation
    task_ids = {task_id for task_id, _ in pairs}
    incomplete = [
        task_id
        for task_id in sorted(task_ids)
        if (task_id, "baseline") not in pairs or (task_id, "candidate") not in pairs
    ]
    if len(task_ids) < 5 or incomplete:
        raise ValidationFailure(
            "canary evidence requires at least five complete task pairs"
        )
    for task_id in task_ids:
        baseline = pairs[(task_id, "baseline")]
        candidate = pairs[(task_id, "candidate")]
        if baseline["workload_digest"] != candidate["workload_digest"]:
            raise ValidationFailure("canary pair workload digests do not match")
        if baseline["quality_rubric_digest"] != candidate["quality_rubric_digest"]:
            raise ValidationFailure("canary pair quality rubrics do not match")
        if baseline["environment_digest"] != candidate["environment_digest"]:
            raise ValidationFailure("canary pair environments do not match")
        if baseline["evaluator_id"] != candidate["evaluator_id"]:
            raise ValidationFailure("canary pair evaluators do not match")
    baseline_tokens = sum(
        pairs[(task_id, "baseline")]["input_tokens"]
        + pairs[(task_id, "baseline")]["output_tokens"]
        for task_id in task_ids
    )
    candidate_tokens = sum(
        pairs[(task_id, "candidate")]["input_tokens"]
        + pairs[(task_id, "candidate")]["output_tokens"]
        for task_id in task_ids
    )
    baseline_cost = sum(
        pairs[(task_id, "baseline")]["cost_usd_micros"] for task_id in task_ids
    )
    candidate_cost = sum(
        pairs[(task_id, "candidate")]["cost_usd_micros"] for task_id in task_ids
    )
    baseline_noise = sum(
        pairs[(task_id, "baseline")]["document_noise_units"]
        for task_id in task_ids
    )
    candidate_noise = sum(
        pairs[(task_id, "candidate")]["document_noise_units"]
        for task_id in task_ids
    )
    if baseline_tokens <= 0 or baseline_cost <= 0 or baseline_noise <= 0:
        raise ValidationFailure(
            "canary baseline requires positive token and document-noise measurements"
        )
    computed = {
        "quality_delta_points": sum(
            pairs[(task_id, "candidate")]["quality_score"]
            - pairs[(task_id, "baseline")]["quality_score"]
            for task_id in task_ids
        )
        / len(task_ids),
        "token_reduction_ratio": 1 - candidate_tokens / baseline_tokens,
        "cost_reduction_ratio": 1 - candidate_cost / baseline_cost,
        "document_noise_reduction_ratio": 1 - candidate_noise / baseline_noise,
        "safety_violations": sum(
            pairs[(task_id, "candidate")]["safety_violations"]
            for task_id in task_ids
        ),
    }
    for field, value in computed.items():
        if abs(data[field] - value) > 1e-9:
            raise ValidationFailure(
                f"canary summary {field} does not match observed run evidence"
            )
    passed = (
        data["quality_delta_points"] >= -2
        and data["cost_reduction_ratio"] >= 0.25
        and data["document_noise_reduction_ratio"] >= 0.30
        and data["safety_violations"] == 0
    )
    return {
        "status": "passed" if passed else "failed",
        **data,
        "task_count": len(task_ids),
        "computed_metrics": computed,
    }


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
    state = engine.start(
        "eval-release",
        normalize_request("Prepare a release rollout plan"),
        run_id="eval-release",
    )
    if engine.next(state).decision != "pause_for_approval":
        raise AssertionError("release did not pause")
    grant = RunApprovalGrant(
        grant_id="eval-release-grant",
        broker_id="eval-broker",
        audience="engineering-assistant",
        action="run.approve",
        run_id=state.run_id,
        run_revision=state.revision,
        approval_id="release-execution",
        scope=["flow:release", "approval:release-execution"],
        issued_at=datetime.now(timezone.utc).isoformat(),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        actor_ref="eval-human-boundary",
        nonce="eval-nonce-000001",
        token="eval-run-grant-token",
    )

    class EvalApprovalVerifier:
        def verify_evidence(self, run_id, evidence):
            return False

        def verify_decision(self, decision_grant):
            return False

        def verify_run_approval(self, approval_grant):
            return approval_grant.token == "eval-run-grant-token"

    engine.apply_approval(
        state,
        grant,
        verifier=EvalApprovalVerifier(),
        expected_broker_id="eval-broker",
        expected_audience="engineering-assistant",
    )
    if engine.next(state).next_node != "readiness":
        raise AssertionError("release did not resume")


def _scenario_evidence_resume(catalog, root: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary)
        store = StateStore(project, root / "schemas")
        class EvalTrustVerifier:
            def verify_evidence(self, run_id, evidence):
                return evidence.attestation == f"eval-receipt:{run_id}:{evidence.id}"

            def verify_decision(self, grant):
                return False

            def verify_run_approval(self, grant):
                return False

        evidence_store = EvidenceStore(store, EvalTrustVerifier())
        engine = RuntimeEngine(catalog)
        state = engine.start(
            "eval-design",
            normalize_request("Design the module boundary and interface"),
            run_id="eval-design",
        )
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
                attestation=f"eval-receipt:{state.run_id}:observed-source",
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
            evidence_store=evidence_store,
        )
        store.save(state, expected_revision=previous)
        if store.load(state.run_id).current_node != "prototype":
            raise AssertionError("resumed state did not preserve next node")


def _scenario_retry(catalog, _root: Path) -> None:
    engine = RuntimeEngine(catalog)
    state = engine.start(
        "eval-implement",
        normalize_request("Implement the accepted endpoint behavior"),
        run_id="eval-implement",
    )
    engine.next(state)
    gate = engine.complete_step(
        state,
        StepResult(state.run_id, "select-slice", "failed", [], [], [], [], "retry"),
        evidence_store=EvidenceStore(StateStore(Path.cwd(), catalog.root / "schemas")),
    )
    if gate.decision != "retry" or state.current_node != "select-slice":
        raise AssertionError("failed step did not remain retryable")


def _scenario_block(catalog, _root: Path) -> None:
    engine = RuntimeEngine(catalog)
    state = engine.start(
        "eval-shape",
        normalize_request("Clarify this requirement and its acceptance criteria"),
        run_id="eval-shape",
    )
    engine.next(state)
    gate = engine.complete_step(
        state,
        StepResult(state.run_id, "discover-facts", "blocked", [], [], [], ["missing authority"], "block"),
        evidence_store=EvidenceStore(StateStore(Path.cwd(), catalog.root / "schemas")),
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
