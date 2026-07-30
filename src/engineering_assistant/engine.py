"""Executable flow state machine for the engineering kernel."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from .catalog import Catalog
from .evidence import EvidenceStore
from .governance import QualityGate, QualityStore
from .model import (
    FlowNode,
    GateDecision,
    QualitySnapshot,
    RouteIntent,
    RunApprovalGrant,
    RunState,
    StepResult,
)
from .router import route_intent
from .trust import TrustVerifier, parse_time
from .validation import ValidationFailure, load_json, validate_instance


TERMINAL_STATUSES = {"blocked", "cancelled", "completed"}


def criterion_ids(node: FlowNode) -> list[str]:
    return [f"{node.id}:{index}" for index, _ in enumerate(node.completion_criteria, start=1)]


class RuntimeEngine:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def start(
        self,
        task_id: str,
        intent: RouteIntent,
        *,
        profile_id: str = "default",
        run_id: str | None = None,
        context_refs: list[str] | None = None,
        design_source_ref: str | None = None,
    ) -> RunState:
        if profile_id not in self.catalog.profiles:
            raise ValidationFailure(f"unknown profile {profile_id}")
        decision = route_intent(intent, self.catalog, profile_id=profile_id)
        if not decision.flow_id:
            raise ValidationFailure("only a flow route creates persisted run state")
        if decision.flow_id not in self.catalog.flows:
            raise ValidationFailure(f"unknown flow {decision.flow_id}")
        unknown_skills = sorted(set(decision.skill_ids) - set(self.catalog.skills))
        unknown_policies = sorted(set(decision.policy_refs) - set(self.catalog.policies))
        if unknown_skills or unknown_policies:
            raise ValidationFailure(
                f"route decision has unknown references: skills={unknown_skills}, policies={unknown_policies}"
            )
        if decision.decision in {"ask", "block"}:
            raise ValidationFailure(f"cannot start a run from route decision {decision.decision}")
        approvals: list[str] = []
        required = list(decision.approval_required)
        missing = [item for item in required if item not in approvals]
        missing_design_source = decision.flow_id == "domain-design" and not design_source_ref
        status = (
            "waiting_for_input"
            if missing_design_source
            else "waiting_for_approval" if missing else "initialized"
        )
        resolved_context_refs = list(dict.fromkeys(context_refs or []))
        if design_source_ref:
            resolved_context_refs.append(f"design-source:{design_source_ref}")
        state = RunState(
            run_id=run_id or f"run-{uuid4().hex[:16]}",
            task_id=task_id,
            profile_id=profile_id,
            flow_id=decision.flow_id,
            status=status,
            current_node=None,
            completed_nodes=[],
            skipped_nodes=[],
            context_refs=list(dict.fromkeys(resolved_context_refs)),
            evidence_refs=[],
            open_questions=[],
            required_approvals=required,
            approvals=approvals,
            approval_expiries={},
            approval_records=[],
            transition_history=[],
            next_actions=(
                ["provide design_source_ref: project-relative registry path"]
                if missing_design_source
                else [f"obtain approval: {item}" for item in missing]
            ),
            revision=0,
        )
        self._record(state, "start", status, decision.reason, bump=False)
        self._validate_state(state)
        return state

    def apply_approval(
        self,
        state: RunState,
        grant: RunApprovalGrant,
        *,
        verifier: TrustVerifier | None,
        expected_broker_id: str,
        expected_audience: str,
    ) -> GateDecision:
        self._assert_not_terminal(state)
        validate_instance(
            grant.to_dict(),
            load_json(self.catalog.root / "schemas/run-approval-grant.schema.json"),
            "run-approval-grant",
        )
        if verifier is None or not verifier.verify_run_approval(grant):
            raise ValidationFailure("run approval requires a valid external broker grant")
        if grant.broker_id != expected_broker_id:
            raise ValidationFailure("run approval grant has the wrong broker")
        if grant.audience != expected_audience:
            raise ValidationFailure("run approval grant has the wrong audience")
        if grant.run_id != state.run_id or grant.run_revision != state.revision:
            raise ValidationFailure("run approval grant targets a different or stale run")
        now = datetime.now(timezone.utc)
        if parse_time(grant.issued_at) > now or parse_time(grant.expires_at) <= now:
            raise ValidationFailure("run approval grant is not currently valid")
        if grant.approval_id not in state.required_approvals:
            raise ValidationFailure(
                f"approval {grant.approval_id} is not required by this run"
            )
        required_scope = {
            f"flow:{state.flow_id}",
            f"approval:{grant.approval_id}",
        }
        if not required_scope.issubset(grant.scope):
            raise ValidationFailure("run approval grant has insufficient scope")
        if grant.approval_id not in state.approvals:
            state.approvals.append(grant.approval_id)
        state.approval_expiries[grant.approval_id] = grant.expires_at
        approval_record = grant.to_dict()
        approval_record.pop("token", None)
        state.approval_records.append(approval_record)
        missing = self._missing_approvals(state)
        state.next_actions = [f"obtain approval: {item}" for item in missing]
        state.status = "waiting_for_approval" if missing else "initialized"
        self._record(state, "approval", state.status, grant.grant_id)
        decision = "pause_for_approval" if missing else "continue"
        gate = GateDecision(decision, [], missing, "Approval recorded.", None)
        self._validate_gate(gate)
        return gate

    def next(self, state: RunState) -> GateDecision:
        self._assert_not_terminal(state)
        if state.flow_id == "domain-design" and not any(
            ref.startswith("design-source:") for ref in state.context_refs
        ):
            state.status = "waiting_for_input"
            state.next_actions = ["provide design_source_ref: project-relative registry path"]
            gate = GateDecision(
                "pause_for_input",
                [],
                ["design_source_ref"],
                "A domain-design run requires a DesignSourceRegistry.",
                None,
            )
            self._validate_gate(gate)
            return gate
        missing_approvals = self._missing_approvals(state)
        if missing_approvals:
            state.status = "waiting_for_approval"
            state.next_actions = [f"obtain approval: {item}" for item in missing_approvals]
            gate = GateDecision(
                "pause_for_approval", [], missing_approvals, "Required approvals are not complete.", None
            )
            self._validate_gate(gate)
            return gate
        if state.current_node:
            gate = GateDecision(
                "continue", [], [], "Continue the current node.", state.current_node
            )
            self._validate_gate(gate)
            return gate

        ready = self._ready_nodes(state)
        if not ready:
            flow = self.catalog.flows[state.flow_id]
            resolved = set(state.completed_nodes) | set(state.skipped_nodes)
            if len(resolved) == len(flow.nodes):
                state.status = "completed"
                state.next_actions = []
                self._record(state, "complete-run", "completed", "All flow nodes are resolved.")
                gate = GateDecision("complete", list(flow.policy_refs), [], "All flow nodes are resolved.", None)
                self._validate_gate(gate)
                return gate
            state.status = "blocked"
            self._record(state, "block", "blocked", "No runnable node exists; flow dependencies are unresolved.")
            gate = GateDecision("block", [], [], "No runnable node exists; dependencies are unresolved.", None)
            self._validate_gate(gate)
            return gate

        node = ready[0]
        state.current_node = node.id
        state.status = "running"
        state.next_actions = [f"execute node: {node.id}"]
        self._record(state, "select-node", "running", node.id)
        gate = GateDecision("continue", list(node.policy_refs), [], "Next dependency-ready node selected.", node.id)
        self._validate_gate(gate)
        return gate

    def complete_step(
        self,
        state: RunState,
        result: StepResult,
        *,
        evidence_store: EvidenceStore,
        evidence_max_age_seconds: int | None = None,
    ) -> GateDecision:
        self._assert_not_terminal(state)
        validate_instance(
            result.to_dict(),
            load_json(self.catalog.root / "schemas/step-result.schema.json"),
            "step-result",
        )
        if result.run_id != state.run_id or result.node_id != state.current_node:
            raise ValidationFailure("step result does not match the active run and node")
        node = self._node(state, result.node_id)
        referenced = {
            evidence_id
            for criterion in result.criteria_results
            for evidence_id in criterion.evidence_ids
        } | {
            evidence_id
            for finding in result.findings
            for evidence_id in finding.evidence_ids
        }
        criterion_evidence_ids = {
            evidence_id
            for criterion in result.criteria_results
            for evidence_id in criterion.evidence_ids
        }
        evidence = {}
        for evidence_id in referenced:
            try:
                item = evidence_store.get(state.run_id, evidence_id)
            except FileNotFoundError as exc:
                raise ValidationFailure(
                    f"step references unregistered evidence: {evidence_id}"
                ) from exc
            if item.trust_level not in {"observed", "verified"}:
                raise ValidationFailure(
                    f"step evidence {evidence_id} must be observed or verified"
                )
            evidence[evidence_id] = item
        profile_evidence = self.catalog.profiles[state.profile_id].evidence_policy
        fixed_max_age = int(profile_evidence["max_age_seconds"])
        if evidence_max_age_seconds is not None and evidence_max_age_seconds <= 0:
            raise ValidationFailure("evidence_max_age_seconds must be positive")
        effective_max_age = (
            min(fixed_max_age, evidence_max_age_seconds)
            if evidence_max_age_seconds is not None
            else fixed_max_age
        )
        max_future_skew = int(profile_evidence["max_future_skew_seconds"])
        now = datetime.now(timezone.utc)
        stale_or_future = []
        for evidence_id, item in evidence.items():
            age = (now - parse_time(item.observed_at)).total_seconds()
            if age > effective_max_age or age < -max_future_skew:
                stale_or_future.append(evidence_id)
        if stale_or_future:
            raise ValidationFailure(
                "step references stale or future evidence: "
                + ", ".join(sorted(stale_or_future))
            )

        state.evidence_refs = list(dict.fromkeys(state.evidence_refs + sorted(referenced)))
        state.open_questions = list(result.open_questions)

        if result.requested_transition == "cancel":
            return self._terminal_gate(state, "cancelled", "cancel", node, "Run cancelled by explicit transition.")
        if result.status == "skipped":
            if node.when.strip().lower() == "always":
                raise ValidationFailure(f"mandatory node {node.id} cannot be skipped")
            if not result.outputs:
                raise ValidationFailure(f"skipped node {node.id} must record why its condition is not applicable")
            state.skipped_nodes.append(node.id)
            return self._advance_after_resolution(state, node, "Node skipped because its condition is not applicable.")
        if result.status == "blocked" or result.requested_transition == "block":
            return self._terminal_gate(state, "blocked", "block", node, "Step reported a blocking condition.")
        if result.requested_transition == "rework":
            return self._rework_domain_boundary(state, node, result)
        if result.status == "waiting" or result.requested_transition in {"pause_for_input", "pause_for_approval"}:
            transition = result.requested_transition
            if transition not in {"pause_for_input", "pause_for_approval"}:
                transition = "pause_for_input"
            status = "waiting_for_input" if transition == "pause_for_input" else "waiting_for_approval"
            if result.required_approvals:
                self._register_required_approvals(state, node, result.required_approvals)
                transition = "pause_for_approval"
                status = "waiting_for_approval"
            missing_approvals = self._missing_approvals(state)
            state.status = status
            state.next_actions = (
                [f"obtain approval: {item}" for item in missing_approvals]
                if transition == "pause_for_approval" and missing_approvals
                else list(result.open_questions)
            )
            self._record(state, "pause", status, "Step requested a pause.")
            gate = GateDecision(
                transition,
                list(node.policy_refs),
                missing_approvals if transition == "pause_for_approval" else [],
                "Step requested a pause.",
                node.id,
            )
            self._validate_gate(gate)
            return gate
        if result.status == "failed" or result.requested_transition == "retry":
            state.status = "running"
            state.next_actions = [f"retry node: {node.id}"]
            self._record(state, "retry", "running", "Step failed and remains at the current node.")
            gate = GateDecision("retry", list(node.policy_refs), [], "Step failed; retry the current node.", node.id)
            self._validate_gate(gate)
            return gate

        blocker = next((finding for finding in result.findings if finding.severity == "blocker"), None)
        if blocker:
            return self._terminal_gate(state, "blocked", "block", node, blocker.summary)
        if state.flow_id == "domain-design" and node.id == "baseline-approval":
            self._register_required_approvals(
                state,
                node,
                ["domain-business-owner", "domain-architecture-owner"],
            )
            missing_approvals = self._missing_approvals(state)
            if missing_approvals:
                state.status = "waiting_for_approval"
                state.next_actions = [f"obtain approval: {item}" for item in missing_approvals]
                self._record(state, "pause", "waiting_for_approval", "Baseline promotion requires dual approval.")
                gate = GateDecision(
                    "pause_for_approval",
                    list(node.policy_refs),
                    missing_approvals,
                    "Baseline promotion requires business and architecture approval.",
                    node.id,
                )
                self._validate_gate(gate)
                return gate
        if state.flow_id == "implement" and node.id == "quality":
            quality_snapshot = QualityStore(
                evidence_store.state_store, evidence_store
            ).latest_valid(
                state.run_id,
                node.id,
                current_state_revision=state.revision,
            )
            quality_gate = self._evaluate_quality_snapshot(
                state,
                node,
                quality_snapshot,
            )
            if quality_gate is not None:
                return quality_gate
        expected = set(criterion_ids(node))
        actual = {item.criterion_id for item in result.criteria_results}
        missing_criteria = sorted(expected - actual)
        failed_criteria = sorted(item.criterion_id for item in result.criteria_results if not item.passed)
        no_evidence = sorted(
            item.criterion_id for item in result.criteria_results if item.passed and not item.evidence_ids
        )
        missing = missing_criteria + failed_criteria + no_evidence
        if node.evidence_kinds or node.evidence_scope_tags:
            allowed_kinds = set(node.evidence_kinds)
            for criterion in result.criteria_results:
                if not criterion.passed:
                    continue
                items = [evidence[item] for item in criterion.evidence_ids]
                if not any(
                    (not allowed_kinds or item.kind in allowed_kinds)
                    and set(node.evidence_scope_tags).issubset(item.scope_tags)
                    for item in items
                ):
                    missing.append(f"{criterion.criterion_id}:evidence-contract")
        if missing:
            state.status = "running"
            state.next_actions = [f"satisfy criterion: {item}" for item in missing]
            self._record(state, "retry", "running", "Completion criteria are not evidenced.")
            gate = GateDecision("retry", list(node.policy_refs), missing, "Completion criteria are not evidenced.", node.id)
            self._validate_gate(gate)
            return gate
        referenced_kinds = {
            evidence[evidence_id].kind for evidence_id in criterion_evidence_ids
        }
        if not self._missing_approvals(state) and state.required_approvals:
            referenced_kinds.add("approval")
        missing_policy_evidence = []
        for policy_id in node.policy_refs:
            required_kinds = set(self.catalog.policies[policy_id].required_evidence)
            if required_kinds and not referenced_kinds.intersection(required_kinds):
                missing_policy_evidence.append(
                    f"{policy_id}:one-of({','.join(sorted(required_kinds))})"
                )
        if missing_policy_evidence:
            state.status = "running"
            state.next_actions = [
                f"provide policy evidence: {item}" for item in missing_policy_evidence
            ]
            self._record(
                state,
                "retry",
                "running",
                "Node policy evidence requirements are not satisfied.",
            )
            gate = GateDecision(
                "retry",
                list(node.policy_refs),
                missing_policy_evidence,
                "Node policy evidence requirements are not satisfied.",
                node.id,
            )
            self._validate_gate(gate)
            return gate
        state.completed_nodes.append(node.id)
        return self._advance_after_resolution(state, node, "Step completion criteria passed with registered evidence.")

    def _evaluate_quality_snapshot(
        self,
        state: RunState,
        node: FlowNode,
        snapshot: QualitySnapshot | None,
    ) -> GateDecision | None:
        if snapshot is None:
            missing = ["quality-snapshot"]
            reason = "A persisted quality snapshot is required for this node."
        elif snapshot.run_id != state.run_id or snapshot.node_id != node.id:
            raise ValidationFailure("quality snapshot does not match the active run and node")
        elif snapshot.state_revision != state.revision:
            raise ValidationFailure("quality snapshot targets a stale run revision")
        else:
            validate_instance(
                snapshot.to_dict(),
                load_json(self.catalog.root / "schemas/quality-snapshot.schema.json"),
                "quality-snapshot",
            )
            assessment = QualityGate.evaluate(snapshot)
            if assessment.decision == "pass":
                return None
            missing = list(assessment.reasons)
            reason = "Quality snapshot requires repair before the node can complete."
        state.status = "running"
        state.next_actions = [f"repair quality: {item}" for item in missing]
        self._record(state, "retry", "running", reason)
        gate = GateDecision("retry", list(node.policy_refs), missing, reason, node.id)
        self._validate_gate(gate)
        return gate

    def node_payload(self, state: RunState) -> dict | None:
        if not state.current_node:
            return None
        node = self._node(state, state.current_node)
        payload = node.to_dict()
        payload["criterion_ids"] = criterion_ids(node)
        return payload

    def _advance_after_resolution(self, state: RunState, node: FlowNode, reason: str) -> GateDecision:
        state.current_node = None
        state.status = "running"
        state.next_actions = []
        self._record(state, "resolve-node", "running", reason)
        gate = self.next(state)
        if gate.decision == "continue":
            return GateDecision("continue", list(node.policy_refs), [], reason, gate.next_node)
        return gate

    def _terminal_gate(self, state: RunState, status: str, decision: str, node: FlowNode, reason: str) -> GateDecision:
        state.status = status
        state.next_actions = []
        self._record(state, decision, status, reason)
        gate = GateDecision(decision, list(node.policy_refs), [], reason, None)
        self._validate_gate(gate)
        return gate

    def _ready_nodes(self, state: RunState) -> list[FlowNode]:
        resolved = set(state.completed_nodes) | set(state.skipped_nodes)
        return [
            node
            for node in self.catalog.flows[state.flow_id].nodes
            if node.id not in resolved and set(node.depends_on).issubset(resolved)
        ]

    def _register_required_approvals(
        self,
        state: RunState,
        node: FlowNode,
        required_approvals: list[str],
    ) -> None:
        required = ["domain-business-owner", "domain-architecture-owner"]
        if state.flow_id != "domain-design" or node.id != "baseline-approval":
            raise ValidationFailure("step results may request approvals only at domain-design baseline approval")
        if set(required_approvals) != set(required):
            raise ValidationFailure("domain-design baseline approval requires business and architecture owners")
        state.required_approvals = list(dict.fromkeys(state.required_approvals + required))

    def _rework_domain_boundary(
        self,
        state: RunState,
        node: FlowNode,
        result: StepResult,
    ) -> GateDecision:
        if state.flow_id != "domain-design" or node.id != "boundary-validation":
            raise ValidationFailure("rework is allowed only at domain-design boundary-validation")
        if result.status != "failed":
            raise ValidationFailure("boundary rework must report a failed validation")
        findings = [
            finding
            for finding in result.findings
            if finding.severity in {"major", "blocker"} and finding.evidence_ids
        ]
        if not findings:
            raise ValidationFailure(
                "boundary rework requires a major or blocker finding with registered evidence"
            )
        flow = self.catalog.flows[state.flow_id]
        start_index = next(
            index for index, item in enumerate(flow.nodes) if item.id == "strategic-design"
        )
        invalidated = [item.id for item in flow.nodes[start_index:]]
        state.completed_nodes = [item for item in state.completed_nodes if item not in invalidated]
        state.skipped_nodes = [item for item in state.skipped_nodes if item not in invalidated]
        state.current_node = "strategic-design"
        state.status = "running"
        state.next_actions = ["execute node: strategic-design"]
        self._record(
            state,
            "boundary-rework",
            "running",
            "Boundary validation failed; strategic design must be revised.",
            metadata={
                "target_node": "strategic-design",
                "finding_ids": [finding.id for finding in findings],
                "invalidated_nodes": invalidated,
            },
        )
        gate = GateDecision(
            "continue",
            list(node.policy_refs),
            [],
            "Boundary validation failed; return to strategic design.",
            "strategic-design",
        )
        self._validate_gate(gate)
        return gate

    def _node(self, state: RunState, node_id: str) -> FlowNode:
        for node in self.catalog.flows[state.flow_id].nodes:
            if node.id == node_id:
                return node
        raise ValidationFailure(f"flow {state.flow_id} has no node {node_id}")

    @staticmethod
    def _missing_approvals(state: RunState) -> list[str]:
        now = datetime.now(timezone.utc)
        missing = []
        for item in state.required_approvals:
            expiry_text = state.approval_expiries.get(item)
            try:
                expiry = datetime.fromisoformat(expiry_text) if expiry_text else None
                if expiry is not None and expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
            except ValueError:
                expiry = None
            if item not in state.approvals or expiry is None or expiry <= now:
                missing.append(item)
        return missing

    @staticmethod
    def _assert_not_terminal(state: RunState) -> None:
        if state.status in TERMINAL_STATUSES:
            raise ValidationFailure(f"run is terminal: {state.status}")

    def _validate_state(self, state: RunState) -> None:
        validate_instance(state.to_dict(), load_json(self.catalog.root / "schemas/run-state.schema.json"), "run-state")

    def _validate_gate(self, gate: GateDecision) -> None:
        validate_instance(gate.to_dict(), load_json(self.catalog.root / "schemas/gate-decision.schema.json"), "gate")

    @staticmethod
    def _record(
        state: RunState,
        event: str,
        status: str,
        detail: str,
        *,
        bump: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "status": status,
            "detail": detail,
        }
        if metadata:
            record.update(metadata)
        state.transition_history.append(record)
        if bump:
            state.revision += 1
