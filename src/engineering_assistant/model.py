"""Core data models for the engineering-assistant protocol."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


class Serializable:
    def to_dict(self) -> Dict[str, Any]:
        return _clean(asdict(self))


@dataclass(frozen=True)
class ContextPointer(Serializable):
    when: str
    path: str
    purpose: str


@dataclass(frozen=True)
class CompletionCriterion(Serializable):
    id: str
    description: str
    evidence_kinds: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillSpec(Serializable):
    id: str
    version: str
    invocation_mode: str
    description: Optional[str]
    leading_words: List[str]
    capabilities: List[str]
    inputs: List[str]
    completion_criteria: List[CompletionCriterion]
    context_pointers: List[ContextPointer]
    policy_refs: List[str]
    risk_class: str
    source_path: str


@dataclass(frozen=True)
class FlowNode(Serializable):
    id: str
    capability: str
    depends_on: List[str]
    when: str
    completion_criteria: List[str]
    policy_refs: List[str]
    evidence_kinds: List[str] = field(default_factory=list)
    evidence_scope_tags: List[str] = field(default_factory=list)
    required_evidence_kinds: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class FlowSpec(Serializable):
    id: str
    version: str
    entry_conditions: List[str]
    nodes: List[FlowNode]
    terminal_conditions: List[str]
    policy_refs: List[str]


@dataclass(frozen=True)
class PolicyRule(Serializable):
    id: str
    condition: str
    effect: str
    severity: str


@dataclass(frozen=True)
class PolicySpec(Serializable):
    id: str
    version: str
    policy_class: str
    immutable: bool
    applies_when: List[str]
    rules: List[PolicyRule]
    required_evidence: List[str]
    on_violation: str


@dataclass(frozen=True)
class RouteIntent(Serializable):
    task_kind: str
    requested_outcome: str
    scope: List[str]
    risk_signals: List[str]
    requested_external_actions: List[str]
    confirmed_actions: List[str]
    confidence: float
    evidence: List[str]


@dataclass(frozen=True)
class RouteDecision(Serializable):
    decision: str
    flow_id: Optional[str]
    skill_ids: List[str]
    policy_refs: List[str]
    evidence_level: str
    persistence_mode: str
    approval_required: List[str]
    reason: str


@dataclass(frozen=True)
class EvidenceRef(Serializable):
    id: str
    kind: str
    uri: str
    producer: str
    observed_at: str
    provenance: str
    scope: str
    scope_tags: List[str] = field(default_factory=list)
    contract_refs: List[str] = field(default_factory=list)
    subject_digest: Optional[str] = None
    digest: Optional[str] = None


@dataclass(frozen=True)
class ProviderSource(Serializable):
    url: str
    revision: str
    integrity: str
    license: str


@dataclass(frozen=True)
class CapabilityProviderSpec(Serializable):
    id: str
    version: str
    mode: str
    capability_ids: List[str]
    input_schema_ref: str
    output_schema_ref: str
    risk_class: str
    network_policy: str
    timeout_seconds: int
    evidence_contract: List[str]
    failure_action: str
    fallback_provider_id: Optional[str]
    source: Optional[ProviderSource]
    priority: int = 0


@dataclass(frozen=True)
class ProviderInvocation(Serializable):
    invocation_id: str
    run_id: str
    capability_id: str
    query: str
    operation: str
    project_name: Optional[str] = None
    domain: Optional[str] = None
    stack: Optional[str] = None
    variance: Optional[int] = None
    motion: Optional[int] = None
    density: Optional[int] = None


@dataclass(frozen=True)
class ProviderResult(Serializable):
    invocation_id: str
    invocation_digest: str
    requested_provider_id: str
    provider_id: str
    capability_id: str
    status: str
    output: str
    trust_level: str
    source_revision: Optional[str]
    expected_source_integrity: Optional[str]
    observed_source_integrity: Optional[str]
    observed_at: str
    next_action: str
    warning: Optional[str] = None
    fallback_provider_id: Optional[str] = None


@dataclass(frozen=True)
class FeedbackEvent(Serializable):
    event_id: str
    run_id: str
    task_id: str
    node_id: Optional[str]
    turn_id: Optional[str]
    event_type: str
    severity: str
    source: str
    symptom: str
    expected_behavior: str
    observed_behavior: str
    human_action: Optional[str]
    evidence_refs: List[str]
    recurrence_key: str
    resolution: str
    reusable_candidate: bool
    sensitivity: str
    observed_at: str
    flow_id: Optional[str] = None
    scope_tags: List[str] = field(default_factory=lambda: ["unknown"])
    change_kind: str = "unknown"
    affected_asset_refs: List[str] = field(default_factory=list)
    recovery_condition: str = "unknown"
    manual_intervention_kind: str = "none"


@dataclass(frozen=True)
class FeedbackDisposition(Serializable):
    schema_version: str
    disposition_id: str
    event_id: str
    decision: str
    reason: str
    actor_ref: str
    evidence_refs: List[str]
    reusable_candidate: bool
    decided_at: str


@dataclass(frozen=True)
class FeedbackCapture(Serializable):
    capture_id: str
    session_ref: str
    turn_ref: str
    event_name: str
    platform: str
    model: str
    permission_mode: str
    status: str
    content_digest: str
    content_length: int
    redaction_count: int
    candidate_event_ids: List[str]
    captured_at: str


@dataclass(frozen=True)
class UsageObservationPlan(Serializable):
    observation_id: str
    session_ref: str
    turn_ref: str
    task_digest: str
    activation_source: str
    reference_tool_calls: int
    reference_shell_calls: int
    reference_index_queries: int
    reference_output_bytes: int
    coverage: List[str]


@dataclass(frozen=True)
class UsageObservationLedger(Serializable):
    plan: UsageObservationPlan
    tool_calls: int
    shell_calls: int
    index_queries: int
    output_bytes: int
    tool_use_signatures: Dict[str, str]
    completed_tool_use_ids: List[str]
    signals: List[str]
    signal_counts: Dict[str, int]
    revision: int


@dataclass(frozen=True)
class UsageEfficiencyFeedback(Serializable):
    schema_version: str
    candidate_id: str
    source: str
    status: str
    tool_calls: int
    shell_calls: int
    index_queries: int
    output_bytes: int
    reference_tool_calls: int
    reference_shell_calls: int
    reference_index_queries: int
    reference_output_bytes: int
    signals: List[str]
    coverage: List[str]
    ledger_revision: int
    reusable_candidate: bool


@dataclass(frozen=True)
class QualityDimension(Serializable):
    id: str
    status: str
    delta: int
    summary: str
    evidence_ids: List[str]


@dataclass(frozen=True)
class QualitySnapshot(Serializable):
    id: str
    run_id: str
    node_id: str
    state_revision: int
    base_ref: str
    candidate_ref: str
    candidate_evidence_id: str
    dimensions: List[QualityDimension]
    findings: List["Finding"]
    required_repairs: List[str]
    evidence_refs: List[str]
    observed_at: str


@dataclass(frozen=True)
class InvestigationRequest(Serializable):
    id: str
    run_id: str
    question: str
    reason: str
    source_scope: List[str]
    reported_blocking: bool
    mode: str
    estimated_cost: str
    stop_conditions: List[str]
    evidence_requirements: List[str]
    status: str


@dataclass(frozen=True)
class InvestigationTransition(Serializable):
    from_status: str
    to_status: str
    action: str
    decision_ref: Optional[str]
    observed_at: str


@dataclass(frozen=True)
class InvestigationRecord(Serializable):
    request: InvestigationRequest
    decision_ref: Optional[str]
    evidence_refs: List[str]
    remaining_source_scope: List[str]
    current_source_scope: List[str]
    transition_history: List[InvestigationTransition]
    updated_at: str
    revision: int = 0


@dataclass(frozen=True)
class InvestigationDecisionRecord(Serializable):
    record_id: str
    run_id: str
    investigation_id: str
    run_revision: int
    decision: str
    selected_mode: str
    allowed_source_scope: List[str]
    max_cost: str
    actor_ref: str
    reason: str
    recorded_at: str
    source: str


@dataclass(frozen=True)
class ApprovalRecord(Serializable):
    record_id: str
    run_id: str
    run_revision: int
    approval_id: str
    decision: str
    scope: List[str]
    actor_ref: str
    reason: str
    recorded_at: str
    source: str


@dataclass(frozen=True)
class CriterionResult(Serializable):
    criterion_id: str
    passed: bool
    evidence_ids: List[str]
    detail: str = ""


@dataclass(frozen=True)
class Finding(Serializable):
    id: str
    severity: str
    summary: str
    evidence_ids: List[str]


@dataclass(frozen=True)
class StepResult(Serializable):
    run_id: str
    node_id: str
    status: str
    criteria_results: List[CriterionResult]
    outputs: List[str]
    findings: List[Finding]
    open_questions: List[str]
    requested_transition: str
    required_approvals: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class GateDecision(Serializable):
    decision: str
    evaluated_policies: List[str]
    missing_evidence: List[str]
    reason: str
    next_node: Optional[str] = None


@dataclass
class RunState(Serializable):
    schema_version: str
    run_id: str
    task_id: str
    profile_id: str
    flow_id: str
    status: str
    current_node: Optional[str]
    completed_nodes: List[str]
    skipped_nodes: List[str]
    context_refs: List[str]
    evidence_refs: List[str]
    open_questions: List[str]
    required_approvals: List[str]
    transition_history: List[Dict[str, Any]]
    next_actions: List[str]
    revision: int = 0
