"""Strict dictionary-to-model codecs used at runtime boundaries."""

from __future__ import annotations

from typing import Any, Mapping

from .model import (
    CapabilityProviderSpec,
    CriterionResult,
    DesignSourceRef,
    EvidenceRef,
    FeedbackEvent,
    FeedbackCapture,
    Finding,
    InvestigationRecord,
    InvestigationDecisionGrant,
    InvestigationRequest,
    InvestigationTransition,
    ProviderSource,
    ProviderInvocation,
    ProviderResult,
    QualityDimension,
    QualitySnapshot,
    RouteDecision,
    RouteIntent,
    RunApprovalGrant,
    RunState,
    StepResult,
    UsageObservationLedger,
    UsageObservationPlan,
)


def usage_observation_plan_from_dict(data: Mapping[str, Any]) -> UsageObservationPlan:
    return UsageObservationPlan(**data)


def usage_observation_ledger_from_dict(
    data: Mapping[str, Any],
) -> UsageObservationLedger:
    signals = list(data["signals"])
    raw_signal_counts = data.get("signal_counts")
    signal_counts = (
        {signal: 1 for signal in signals}
        if "signal_counts" not in data
        else dict(raw_signal_counts)
    )
    return UsageObservationLedger(
        plan=usage_observation_plan_from_dict(data["plan"]),
        tool_calls=data["tool_calls"],
        shell_calls=data["shell_calls"],
        index_queries=data["index_queries"],
        output_bytes=data["output_bytes"],
        tool_use_signatures=dict(data["tool_use_signatures"]),
        completed_tool_use_ids=list(data["completed_tool_use_ids"]),
        signals=signals,
        signal_counts=signal_counts,
        revision=data["revision"],
    )


def capability_provider_spec_from_dict(data: Mapping[str, Any]) -> CapabilityProviderSpec:
    source = data.get("source")
    return CapabilityProviderSpec(
        **{key: value for key, value in data.items() if key != "source"},
        source=ProviderSource(**source) if source is not None else None,
    )


def provider_invocation_from_dict(data: Mapping[str, Any]) -> ProviderInvocation:
    return ProviderInvocation(**data)


def provider_result_from_dict(data: Mapping[str, Any]) -> ProviderResult:
    return ProviderResult(**data)


def feedback_event_from_dict(data: Mapping[str, Any]) -> FeedbackEvent:
    return FeedbackEvent(**data)


def feedback_capture_from_dict(data: Mapping[str, Any]) -> FeedbackCapture:
    return FeedbackCapture(**data)


def quality_snapshot_from_dict(data: Mapping[str, Any]) -> QualitySnapshot:
    return QualitySnapshot(
        id=data["id"],
        run_id=data["run_id"],
        node_id=data["node_id"],
        state_revision=data["state_revision"],
        base_ref=data["base_ref"],
        candidate_ref=data["candidate_ref"],
        candidate_evidence_id=data["candidate_evidence_id"],
        dimensions=[QualityDimension(**item) for item in data["dimensions"]],
        findings=[Finding(**item) for item in data["findings"]],
        required_repairs=list(data["required_repairs"]),
        evidence_refs=list(data["evidence_refs"]),
        observed_at=data["observed_at"],
    )


def investigation_request_from_dict(data: Mapping[str, Any]) -> InvestigationRequest:
    return InvestigationRequest(**data)


def investigation_record_from_dict(data: Mapping[str, Any]) -> InvestigationRecord:
    return InvestigationRecord(
        request=investigation_request_from_dict(data["request"]),
        decision_ref=data.get("decision_ref"),
        evidence_refs=list(data["evidence_refs"]),
        remaining_source_scope=list(data["remaining_source_scope"]),
        current_source_scope=list(data["current_source_scope"]),
        transition_history=[InvestigationTransition(**item) for item in data["transition_history"]],
        updated_at=data["updated_at"],
        revision=data["revision"],
    )


def investigation_decision_grant_from_dict(data: Mapping[str, Any]) -> InvestigationDecisionGrant:
    return InvestigationDecisionGrant(**data)


def run_approval_grant_from_dict(data: Mapping[str, Any]) -> RunApprovalGrant:
    return RunApprovalGrant(**data)


def route_intent_from_dict(data: Mapping[str, Any]) -> RouteIntent:
    design_source = data.get("design_source")
    return RouteIntent(
        **{key: value for key, value in data.items() if key != "design_source"},
        design_source=(
            DesignSourceRef(**design_source) if design_source is not None else None
        ),
    )


def route_decision_from_dict(data: Mapping[str, Any]) -> RouteDecision:
    return RouteDecision(**data)


def evidence_ref_from_dict(data: Mapping[str, Any]) -> EvidenceRef:
    return EvidenceRef(**data)


def step_result_from_dict(data: Mapping[str, Any]) -> StepResult:
    return StepResult(
        run_id=data["run_id"],
        node_id=data["node_id"],
        status=data["status"],
        criteria_results=[CriterionResult(**item) for item in data["criteria_results"]],
        outputs=list(data["outputs"]),
        findings=[Finding(**item) for item in data["findings"]],
        open_questions=list(data["open_questions"]),
        requested_transition=data["requested_transition"],
    )


def run_state_from_dict(data: Mapping[str, Any]) -> RunState:
    return RunState(
        run_id=data["run_id"],
        task_id=data["task_id"],
        profile_id=data["profile_id"],
        flow_id=data["flow_id"],
        status=data["status"],
        current_node=data.get("current_node"),
        completed_nodes=list(data["completed_nodes"]),
        skipped_nodes=list(data["skipped_nodes"]),
        context_refs=list(data["context_refs"]),
        evidence_refs=list(data["evidence_refs"]),
        open_questions=list(data["open_questions"]),
        required_approvals=list(data["required_approvals"]),
        approvals=list(data["approvals"]),
        approval_expiries=dict(data["approval_expiries"]),
        approval_records=list(data["approval_records"]),
        transition_history=list(data["transition_history"]),
        next_actions=list(data["next_actions"]),
        revision=data["revision"],
    )
