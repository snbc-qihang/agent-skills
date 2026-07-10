"""Executable flow state machine for the engineering kernel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .catalog import Catalog
from .model import FlowNode, GateDecision, RouteDecision, RunState, StepResult
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
        decision: RouteDecision,
        *,
        run_id: str | None = None,
        context_refs: list[str] | None = None,
        approvals: list[str] | None = None,
        approval_ttl_seconds: int = 3600,
    ) -> RunState:
        validate_instance(
            decision.to_dict(),
            load_json(self.catalog.root / "schemas/route-decision.schema.json"),
            "route-decision",
        )
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
        approvals = list(dict.fromkeys(approvals or []))
        if approval_ttl_seconds <= 0:
            raise ValidationFailure("approval_ttl_seconds must be positive")
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=approval_ttl_seconds)).isoformat()
        required = list(decision.approval_required)
        missing = [item for item in required if item not in approvals]
        status = "waiting_for_approval" if missing else "initialized"
        state = RunState(
            run_id=run_id or f"run-{uuid4().hex[:16]}",
            task_id=task_id,
            flow_id=decision.flow_id,
            status=status,
            current_node=None,
            completed_nodes=[],
            skipped_nodes=[],
            context_refs=list(dict.fromkeys(context_refs or [])),
            evidence_refs=[],
            open_questions=[],
            required_approvals=required,
            approvals=approvals,
            approval_expiries={item: expiry for item in approvals},
            transition_history=[],
            next_actions=[f"obtain approval: {item}" for item in missing],
            revision=0,
        )
        self._record(state, "start", status, decision.reason, bump=False)
        self._validate_state(state)
        return state

    def grant_approval(self, state: RunState, approval_id: str, *, ttl_seconds: int = 3600) -> GateDecision:
        self._assert_not_terminal(state)
        if ttl_seconds <= 0:
            raise ValidationFailure("approval ttl must be positive")
        if approval_id not in state.required_approvals:
            raise ValidationFailure(f"approval {approval_id} is not required by this run")
        if approval_id not in state.approvals:
            state.approvals.append(approval_id)
        state.approval_expiries[approval_id] = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        ).isoformat()
        missing = self._missing_approvals(state)
        state.next_actions = [f"obtain approval: {item}" for item in missing]
        state.status = "waiting_for_approval" if missing else "initialized"
        self._record(state, "approval", state.status, approval_id)
        decision = "pause_for_approval" if missing else "continue"
        gate = GateDecision(decision, [], missing, "Approval recorded.", None)
        self._validate_gate(gate)
        return gate

    def next(self, state: RunState) -> GateDecision:
        self._assert_not_terminal(state)
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
        available_evidence: set[str],
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
        unknown_evidence = sorted(referenced - available_evidence)
        if unknown_evidence:
            raise ValidationFailure(f"step references unregistered evidence: {', '.join(unknown_evidence)}")
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
        if result.status == "waiting" or result.requested_transition in {"pause_for_input", "pause_for_approval"}:
            transition = result.requested_transition
            if transition not in {"pause_for_input", "pause_for_approval"}:
                transition = "pause_for_input"
            status = "waiting_for_input" if transition == "pause_for_input" else "waiting_for_approval"
            state.status = status
            state.next_actions = list(result.open_questions)
            self._record(state, "pause", status, "Step requested a pause.")
            gate = GateDecision(transition, list(node.policy_refs), [], "Step requested a pause.", node.id)
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
        expected = set(criterion_ids(node))
        actual = {item.criterion_id for item in result.criteria_results}
        missing_criteria = sorted(expected - actual)
        failed_criteria = sorted(item.criterion_id for item in result.criteria_results if not item.passed)
        no_evidence = sorted(
            item.criterion_id for item in result.criteria_results if item.passed and not item.evidence_ids
        )
        missing = missing_criteria + failed_criteria + no_evidence
        if missing:
            state.status = "running"
            state.next_actions = [f"satisfy criterion: {item}" for item in missing]
            self._record(state, "retry", "running", "Completion criteria are not evidenced.")
            gate = GateDecision("retry", list(node.policy_refs), missing, "Completion criteria are not evidenced.", node.id)
            self._validate_gate(gate)
            return gate
        state.completed_nodes.append(node.id)
        return self._advance_after_resolution(state, node, "Step completion criteria passed with registered evidence.")

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
    def _record(state: RunState, event: str, status: str, detail: str, *, bump: bool = True) -> None:
        state.transition_history.append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "status": status,
                "detail": detail,
            }
        )
        if bump:
            state.revision += 1
