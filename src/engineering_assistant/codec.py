"""Strict dictionary-to-model codecs used at runtime boundaries."""

from __future__ import annotations

from typing import Any, Mapping

from .model import (
    CriterionResult,
    EvidenceRef,
    Finding,
    RouteDecision,
    RouteIntent,
    RunState,
    StepResult,
)


def route_intent_from_dict(data: Mapping[str, Any]) -> RouteIntent:
    return RouteIntent(**data)


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
        transition_history=list(data["transition_history"]),
        next_actions=list(data["next_actions"]),
        revision=data["revision"],
    )
