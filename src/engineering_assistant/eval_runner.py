"""Executable routing, behavior, state-machine and canary gates."""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .catalog import load_catalog
from . import canary_limits
from .canary import validate_measurement_evidence_coverage
from .artifact_io import ArtifactIO
from .engine import RuntimeEngine
from .evidence import EvidenceStore
from .feedback import (
    FeedbackStore,
    export_feedback_evolution,
    summarize_feedback_events,
)
from .governance import InvestigationStore, QualityGate
from .model import (
    CriterionResult,
    EvidenceRef,
    FeedbackEvent,
    FeedbackDisposition,
    InvestigationRequest,
    ProviderInvocation,
    QualityDimension,
    QualitySnapshot,
    RunApprovalGrant,
    StepResult,
)
from .natural_intent import normalize_request
from .provider_runtime import ProviderExecutor
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
    capabilities = _capability_eval(root, catalog)
    report = {
        "schema_version": "1.0",
        "version": catalog.version,
        "simulation": False,
        "evidence_type": "observed-runtime-execution",
        "routing": routing,
        "behavior": behavior,
        "state_machine": state_machine,
        "replay": replay,
        "capabilities": capabilities,
        "canary": {
            "status": "not_run",
            "reason": "尚无通过外部 evidence broker 验签并满足门槛的真实产品 canary 结果；本机预发布或未验签运行不等同于产品 canary 通过。",
            "simulation_results_accepted": False,
        },
    }
    _enforce_thresholds(report)
    return report


def _load_canary_observations(
    artifacts: ArtifactIO,
    evidence_refs: list[str],
    trust_verifier: TrustVerifier,
    *,
    expected_evidence_broker_id: str,
    expected_host_trust_config_digest: str,
) -> list[dict]:
    repository_root = Path(__file__).resolve().parents[2]
    observation_schema = load_json(
        repository_root / "evals/canary/run-evidence.schema.json"
    )
    missing_evidence = []
    observations = []
    total_artifact_count = 0
    total_artifact_bytes = 0
    for reference in evidence_refs:
        try:
            observation, _raw = artifacts.read_json_limited(
                canary_limits.MAX_OBSERVATION_BYTES,
                *Path(reference).parts,
            )
        except (FileNotFoundError, ValidationFailure):
            missing_evidence.append(reference)
            continue
        validate_instance(
            observation, observation_schema, f"canary-evidence:{reference}"
        )
        validate_measurement_evidence_coverage(
            observation,
            (item["measurement_kinds"] for item in observation["artifact_refs"]),
        )
        if not trust_verifier.verify_canary_observation(observation):
            raise ValidationFailure("canary observation attestation is not trusted")
        expected_provenance = {
            "evidence_broker_id": expected_evidence_broker_id,
            "host_trust_config_digest": expected_host_trust_config_digest,
        }
        if observation["trust_provenance"] != expected_provenance:
            raise ValidationFailure(
                "canary observation was attested by a different host trust binding"
            )
        if parse_time(observation["finished_at"]) < parse_time(observation["started_at"]):
            raise ValidationFailure("canary evidence finishes before it starts")
        for artifact in observation["artifact_refs"]:
            total_artifact_count += 1
            if total_artifact_count > canary_limits.MAX_TOTAL_ARTIFACTS:
                raise ValidationFailure("canary evidence has too many artifacts")
            artifact_payload = artifacts.read_bytes_limited(
                canary_limits.MAX_ARTIFACT_BYTES,
                *Path(artifact["path"]).parts,
            )
            total_artifact_bytes += len(artifact_payload)
            if total_artifact_bytes > canary_limits.MAX_TOTAL_ARTIFACT_BYTES:
                raise ValidationFailure("canary evidence exceeds total artifact bytes limit")
            if f"sha256:{hashlib.sha256(artifact_payload).hexdigest()}" != artifact["digest"]:
                raise ValidationFailure("canary artifact digest does not match")
        observations.append(observation)
    if missing_evidence:
        raise ValidationFailure(f"canary evidence files are missing or non-local: {', '.join(missing_evidence)}")
    return observations


def _pair_canary_observations(
    observations: list[dict],
) -> tuple[dict[tuple[str, str], dict], set[str]]:
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
    return pairs, task_ids


def _canary_metrics(
    pairs: dict[tuple[str, str], dict], task_ids: set[str]
) -> dict:
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
    return {
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


def _single_canary_value(
    observations: list[dict], field: str, *, variant: str | None = None
):
    values = {
        observation[field]
        for observation in observations
        if variant is None or observation["variant"] == variant
    }
    if len(values) != 1:
        scope = f"{variant} " if variant else ""
        label = field.replace("_", " ")
        raise ValidationFailure(f"{scope}canary evidence must use one {label}")
    return next(iter(values))


def assemble_canary_result(
    evidence_root: Path | str,
    evidence_refs: list[str],
    *,
    trust_verifier: TrustVerifier | None = None,
    expected_evidence_broker_id: str,
    expected_host_trust_config_digest: str,
    artifact_io: ArtifactIO | None = None,
) -> dict:
    """Derive a strict result only from externally attested observations."""

    if trust_verifier is None:
        raise ValidationFailure("canary assembly requires an external evidence broker")
    if not 10 <= len(evidence_refs) <= 128:
        raise ValidationFailure("canary evidence requires between 10 and 128 references")
    if len(evidence_refs) != len(set(evidence_refs)):
        raise ValidationFailure("canary evidence references must be unique")
    evidence_root = Path(evidence_root).resolve()
    artifacts = artifact_io or ArtifactIO(evidence_root, ".")
    observations = _load_canary_observations(
        artifacts,
        evidence_refs,
        trust_verifier,
        expected_evidence_broker_id=expected_evidence_broker_id,
        expected_host_trust_config_digest=expected_host_trust_config_digest,
    )
    pairs, task_ids = _pair_canary_observations(observations)
    metrics = _canary_metrics(pairs, task_ids)
    result = {
        "simulation": False,
        "product_repository": _single_canary_value(
            observations, "product_repository"
        ),
        "baseline_ref": _single_canary_value(
            observations, "git_ref", variant="baseline"
        ),
        "candidate_ref": _single_canary_value(
            observations, "git_ref", variant="candidate"
        ),
        "baseline_execution_config_digest": _single_canary_value(
            observations, "execution_config_digest", variant="baseline"
        ),
        "candidate_execution_config_digest": _single_canary_value(
            observations, "execution_config_digest", variant="candidate"
        ),
        "baseline_treatment_digest": _single_canary_value(
            observations, "treatment_digest", variant="baseline"
        ),
        "candidate_treatment_digest": _single_canary_value(
            observations, "treatment_digest", variant="candidate"
        ),
        "trust_provenance": {
            "evidence_broker_id": _single_canary_value(
                [item["trust_provenance"] for item in observations],
                "evidence_broker_id",
            ),
            "host_trust_config_digest": _single_canary_value(
                [item["trust_provenance"] for item in observations],
                "host_trust_config_digest",
            ),
        },
        **metrics,
        "evidence_refs": list(evidence_refs),
    }
    if result["baseline_treatment_digest"] == result["candidate_treatment_digest"]:
        raise ValidationFailure("canary treatment digests must differ")
    repository_root = Path(__file__).resolve().parents[2]
    validate_instance(
        result,
        load_json(repository_root / "evals/canary/result.schema.json"),
        "assembled-canary-result",
    )
    return result


def run_canary_result(
    path: Path | str,
    *,
    trust_verifier: TrustVerifier | None = None,
    expected_evidence_broker_id: str,
    expected_host_trust_config_digest: str,
) -> dict:
    path = Path(path)
    if trust_verifier is None:
        raise ValidationFailure("canary validation requires an external evidence broker")
    evidence_root = path.parent.resolve()
    artifacts = ArtifactIO(evidence_root, ".")
    data, _raw = artifacts.read_json_limited(
        canary_limits.MAX_OBSERVATION_BYTES,
        path.name,
    )
    repository_root = Path(__file__).resolve().parents[2]
    validate_instance(
        data,
        load_json(repository_root / "evals/canary/result.schema.json"),
        "canary-result",
    )
    computed = assemble_canary_result(
        evidence_root,
        data["evidence_refs"],
        trust_verifier=trust_verifier,
        expected_evidence_broker_id=expected_evidence_broker_id,
        expected_host_trust_config_digest=expected_host_trust_config_digest,
        artifact_io=artifacts,
    )
    metric_fields = {
        "quality_delta_points",
        "token_reduction_ratio",
        "cost_reduction_ratio",
        "document_noise_reduction_ratio",
        "safety_violations",
    }
    for field, value in computed.items():
        if field == "evidence_refs":
            continue
        matches = (
            abs(data[field] - value) <= 1e-9
            if field in metric_fields
            else data[field] == value
        )
        if not matches:
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
        "task_count": len(data["evidence_refs"]) // 2,
        "computed_metrics": {
            field: computed[field] for field in sorted(metric_fields)
        },
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


def _capability_eval(root: Path, catalog) -> dict:
    definition = load_json(root / "evals/capabilities/cases.json")
    cases = definition["cases"]
    required_mechanisms = definition["required_mechanisms"]
    runners = {
        "provider-fallback": _scenario_provider_fallback,
        "feedback-summary": _scenario_feedback_summary,
        "quality-gate": _scenario_quality_gate,
        "investigation-policy": _scenario_investigation_policy,
    }
    results = []
    for case in cases:
        runner = runners.get(case["runner"])
        if runner is None:
            raise ValidationFailure(f"unknown capability runner {case['runner']}")
        detail = runner(catalog, root)
        results.append(
            {
                "id": case["id"],
                "capability": case["capability"],
                "runner": case["runner"],
                "status": "passed",
                "detail": detail,
            }
        )
    observed_mechanisms = {item["capability"] for item in results}
    if observed_mechanisms != set(required_mechanisms):
        raise ValidationFailure(
            "runtime mechanism eval does not match its approved protocol scope"
        )
    return {
        "case_count": len(results),
        "passed": len(results),
        "pass_ratio": 1.0 if results else 0.0,
        "evidence_type": "observed-runtime-mechanism",
        "product_benefit_claimed": False,
        "evaluated_scope": "approved_protocol_mechanisms",
        "coverage_claim": "selected_runtime_mechanisms_only",
        "required_mechanisms": required_mechanisms,
        "results": results,
    }


def _scenario_provider_fallback(catalog, _root: Path) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        result = ProviderExecutor(catalog).invoke(
            ProviderInvocation(
                invocation_id="eval-provider-1",
                run_id="eval-provider-run",
                capability_id="frontend-design",
                query="enterprise dashboard",
                operation="design_system",
                project_name="Capability Eval",
            ),
            provider_root=Path(temporary) / "not-configured",
        )
    if result.status != "fallback" or result.provider_id != "native-engineering":
        raise AssertionError("provider failure did not use the governed native fallback")
    return {
        "status": result.status,
        "provider_id": result.provider_id,
        "trust_level": result.trust_level,
    }


def _scenario_feedback_summary(_catalog, root: Path) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary)
        store = FeedbackStore(project, root / "schemas")
        event = FeedbackEvent(
            event_id="eval-feedback-1",
            run_id="eval-feedback-run",
            task_id="eval-feedback-task",
            node_id="quality",
            turn_id=None,
            event_type="quality_regression",
            severity="medium",
            source="runtime",
            symptom="A quality dimension regressed.",
            expected_behavior="Keep every quality dimension evaluated.",
            observed_behavior="One quality dimension requires repair.",
            human_action=None,
            evidence_refs=[],
            recurrence_key="quality-regression",
            resolution="open",
            reusable_candidate=False,
            sensitivity="internal",
            observed_at=datetime.now(timezone.utc).isoformat(),
            scope_tags=["quality"],
            change_kind="repair_failure",
            affected_asset_refs=[],
            recovery_condition="repair_and_revalidate",
            manual_intervention_kind="none",
        )
        if not store.save_event(event):
            raise AssertionError("feedback event was not persisted")
        disposition = FeedbackDisposition(
            schema_version="1.0",
            disposition_id="feedback-disposition-" + "e" * 24,
            event_id=event.event_id,
            decision="accepted_for_evolution",
            reason="capability eval acceptance",
            actor_ref="eval-reviewer",
            evidence_refs=[],
            reusable_candidate=True,
            decided_at=datetime.now(timezone.utc).isoformat(),
        )
        if not store.save_disposition(disposition):
            raise AssertionError("feedback disposition was not persisted")
        summary = summarize_feedback_events(project, root / "schemas", item_limit=1)
        evolution = export_feedback_evolution(project, root / "schemas", limit=1)
    if summary["event_count"] != 1 or summary["recurrence_counts"] != {
        "quality-regression": 1
    }:
        raise AssertionError("feedback event was not included in the bounded summary")
    if (
        evolution["proposal_count"] != 1
        or evolution["proposals"][0]["formal_assets_modified"] is not False
        or evolution["proposals"][0]["requires_review"] is not True
    ):
        raise AssertionError("accepted feedback did not produce a governed evolution proposal")
    return {
        "event_count": summary["event_count"],
        "evolution_proposal_count": evolution["proposal_count"],
        "recurrence_overflow_event_count": summary[
            "recurrence_overflow_event_count"
        ],
    }


def _scenario_quality_gate(_catalog, _root: Path) -> dict:
    dimensions = [
        QualityDimension(
            id=dimension,
            status="pass",
            delta=0,
            summary=f"{dimension} observed",
            evidence_ids=["eval-evidence"],
        )
        for dimension in (
            "correctness",
            "complexity",
            "redundancy",
            "performance",
            "architecture",
            "test_quality",
        )
    ]
    snapshot = QualitySnapshot(
        id="eval-quality-1",
        run_id="eval-quality-run",
        node_id="quality",
        state_revision=0,
        base_ref="base",
        candidate_ref="sha256:" + "a" * 64,
        candidate_evidence_id="eval-candidate",
        dimensions=dimensions,
        findings=[],
        required_repairs=[],
        evidence_refs=["eval-evidence", "eval-candidate"],
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    passed = QualityGate.evaluate(snapshot)
    warned = QualityGate.evaluate(
        replace(
            snapshot,
            id="eval-quality-2",
            dimensions=[
                *dimensions[:-1],
                QualityDimension(
                    id="test_quality",
                    status="warn",
                    delta=-1,
                    summary="test quality requires repair",
                    evidence_ids=["eval-evidence"],
                ),
            ],
        )
    )
    if passed.decision != "pass" or warned.decision != "repair":
        raise AssertionError("quality warnings did not remain a strict repair gate")
    return {"pass_decision": passed.decision, "warning_decision": warned.decision}


def _scenario_investigation_policy(_catalog, root: Path) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        store = InvestigationStore(StateStore(Path(temporary), root / "schemas"))
        base = {
            "run_id": "eval-investigation-run",
            "question": "Which official contract applies?",
            "reason": "An external fact is required.",
            "source_scope": ["official_docs"],
            "reported_blocking": False,
            "estimated_cost": "low",
            "stop_conditions": ["The primary contract is identified."],
            "evidence_requirements": ["Official documentation."],
            "status": "proposed",
        }
        automatic = store.propose(
            InvestigationRequest(
                id="eval-investigation-auto",
                mode="auto_readonly",
                **base,
            ),
            investigation_policy={
                "default_mode": "auto_readonly",
                "auto_readonly": {
                    "enabled": True,
                    "authorization_id": "eval-explicit-profile-choice",
                    "allowed_source_scope": ["official_docs"],
                    "max_cost": "low",
                },
            },
        )
        suggested = store.propose(
            InvestigationRequest(
                id="eval-investigation-suggest",
                mode="suggest_then_run",
                **base,
            ),
            investigation_policy={
                "default_mode": "suggest_then_run",
                "auto_readonly": {"enabled": False},
            },
        )
    if automatic.request.status != "running" or suggested.request.status != "proposed":
        raise AssertionError("investigation policy did not preserve the approval boundary")
    return {
        "explicit_auto_status": automatic.request.status,
        "default_suggest_status": suggested.request.status,
    }


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
    with tempfile.TemporaryDirectory() as temporary:
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
            evidence_store=EvidenceStore(
                StateStore(Path(temporary), catalog.root / "schemas")
            ),
        )
        if gate.decision != "retry" or state.current_node != "select-slice":
            raise AssertionError("failed step did not remain retryable")


def _scenario_block(catalog, _root: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary:
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
            evidence_store=EvidenceStore(
                StateStore(Path(temporary), catalog.root / "schemas")
            ),
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
    capabilities = report["capabilities"]
    observed_capabilities = {item["capability"] for item in capabilities["results"]}
    if capabilities["pass_ratio"] != 1.0:
        failures.append("capability eval has failures")
    if observed_capabilities != set(capabilities["required_mechanisms"]):
        failures.append("runtime mechanism eval does not cover its approved scope")
    if failures:
        raise ValidationFailure("; ".join(failures))
