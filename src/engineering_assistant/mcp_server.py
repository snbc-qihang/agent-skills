"""Dependency-free MCP stdio boundary for the engineering runtime kernel."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TextIO

from .artifact_validation import ARTIFACT_SCHEMAS, validate_artifact_payload
from .catalog import DEFAULT_REPOSITORY_ROOT, load_catalog
from .artifact_io import ArtifactConflict
from .codec import (
    approval_record_from_dict,
    investigation_decision_record_from_dict,
    investigation_request_from_dict,
    quality_snapshot_from_dict,
    provider_invocation_from_dict,
    provider_result_from_dict,
    route_intent_from_dict,
    step_result_from_dict,
)
from .engine import RuntimeEngine
from .design_sources import validate_design_source_registry
from .evidence import EvidenceStore
from .governance import (
    InvestigationStore,
    QualityGate,
    QualityStore,
    investigation_evidence_contract,
)
from .model import ApprovalRecord, InvestigationDecisionRecord, ProviderResult
from .provider_runtime import ProviderExecutor
from .router import ROUTES, route_intent
from .state_store import ApprovalStore, StateStore
from .validation import ValidationFailure, load_json, validate_instance
from .version import CANONICAL_VERSION


PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", PROTOCOL_VERSION}
MAX_MCP_REQUEST_CHARS = 1_048_576


def _object_schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


class RuntimeTools:
    """Small model-facing API over the existing router and state machine."""

    def __init__(
        self,
        repository_root: Path | str = DEFAULT_REPOSITORY_ROOT,
    ) -> None:
        self.catalog = load_catalog(repository_root)
        schemas = self.catalog.root / "schemas"
        self._route_intent_schema = load_json(schemas / "route-intent.schema.json")
        self._step_result_schema = load_json(schemas / "step-result.schema.json")
        self._evidence_schema = load_json(schemas / "evidence-ref.schema.json")
        self._quality_snapshot_schema = load_json(schemas / "quality-snapshot.schema.json")
        self._provider_invocation_schema = load_json(
            schemas / "provider-invocation.schema.json"
        )
        self._investigation_request_schema = load_json(schemas / "investigation-request.schema.json")
        self._approval_record_schema = load_json(schemas / "approval-record.schema.json")
        self._investigation_decision_schema = load_json(
            schemas / "investigation-decision-record.schema.json"
        )
        self._definitions = self._build_definitions()

    def _build_definitions(self) -> list[dict]:
        project_root = {
            "type": "string",
            "minLength": 1,
            "description": "目标项目绝对路径或当前工作目录相对路径。",
        }
        profile = {"type": "string", "minLength": 1, "default": "default"}
        return [
            {
                "name": "engineering_assistant_route",
                "title": "工程任务路由",
                "description": "把已结构化的工程意图路由到唯一的 flow、skills 和治理策略；不执行写入。",
                "inputSchema": _object_schema(
                    {"intent": self._route_intent_schema, "profile": profile},
                    ["intent"],
                ),
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_artifact_validate",
                "title": "校验工程产物",
                "description": "直接使用当前 Runtime schema 校验调用参数中的结构化产物；不读取本地路径、不修改产物。",
                "inputSchema": _object_schema(
                    {
                        "kind": {"enum": sorted(ARTIFACT_SCHEMAS)},
                        "artifact": {"type": "object"},
                    },
                    ["kind", "artifact"],
                ),
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_feedback_summary",
                "title": "读取反馈汇总",
                "description": "按当前项目和可选 run 读取结构化反馈汇总；不会修改正式资产。",
                "inputSchema": _object_schema(
                    {
                        "project_root": project_root,
                        "run_id": {"type": ["string", "null"], "minLength": 1},
                        "limit": {"type": "integer", "minimum": 0, "maximum": 1000},
                    },
                    ["project_root"],
                ),
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_start",
                "title": "启动受治理工程运行",
                "description": "服务端重新路由结构化意图并创建可恢复运行状态；不能接受调用方自造决策或代替人工授予审批。",
                "inputSchema": _object_schema(
                    {
                        "intent": self._route_intent_schema,
                        "task_id": {"type": "string", "minLength": 1},
                        "run_id": {"type": ["string", "null"]},
                        "project_root": project_root,
                        "profile": profile,
                        "context_refs": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "uniqueItems": True,
                        },
                        "design_source_ref": {"type": "string", "minLength": 1},
                    },
                    ["intent", "task_id", "project_root"],
                ),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_next",
                "title": "推进工程运行",
                "description": "按依赖、证据和审批门禁选择下一个节点，并持久化状态变更。",
                "inputSchema": _object_schema(
                    {
                        "run_id": {"type": "string", "minLength": 1},
                        "project_root": project_root,
                        "profile": profile,
                    },
                    ["run_id", "project_root"],
                ),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_runs_list",
                "title": "列出持久化运行",
                "description": "分页读取项目中的运行；默认只返回未终止运行。",
                "inputSchema": _object_schema(
                    {
                        "project_root": project_root,
                        "profile": profile,
                        "include_terminal": {"type": "boolean", "default": False},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                        "after_run_id": {"type": ["string", "null"]},
                    },
                    ["project_root"],
                ),
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_run_status",
                "title": "读取运行状态",
                "description": "读取一个运行的当前状态、节点和执行指导。",
                "inputSchema": _object_schema(
                    {
                        "run_id": {"type": "string", "minLength": 1},
                        "project_root": project_root,
                        "profile": profile,
                    },
                    ["run_id", "project_root"],
                ),
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_evidence_register",
                "title": "登记本地运行证据",
                "description": "登记证据；项目内文件由 Runtime 校验边界并计算摘要，远程引用固定为 agent_reported。",
                "inputSchema": _object_schema(
                    {
                        "run_id": {"type": "string", "minLength": 1},
                        "project_root": project_root,
                        "evidence_id": {"type": "string", "minLength": 1},
                        "kind": self._evidence_schema["properties"]["kind"],
                        "uri": {"type": "string", "minLength": 1},
                        "producer": {"type": "string", "minLength": 1},
                        "scope": {"type": "string", "minLength": 1},
                        "scope_tags": self._evidence_schema["properties"]["scope_tags"],
                        "contract_refs": self._evidence_schema["properties"]["contract_refs"],
                        "subject_digest": self._evidence_schema["properties"]["subject_digest"],
                        "profile": profile,
                    },
                    ["run_id", "project_root", "evidence_id", "kind", "uri", "producer", "scope", "scope_tags", "contract_refs"],
                ),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_approval_record",
                "title": "记录用户审批决定",
                "description": "记录对话中的明确用户决定；只提供本地追溯，不声明身份验签。",
                "inputSchema": _object_schema(
                    {
                        key: value
                        for key, value in self._approval_record_schema["properties"].items()
                        if key != "recorded_at"
                    } | {"project_root": project_root, "profile": profile},
                    [key for key in self._approval_record_schema["required"] if key != "recorded_at"] + ["project_root"],
                ),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_complete",
                "title": "提交节点结果",
                "description": "验证节点结果及已登记证据，执行门禁并持久化下一状态。",
                "inputSchema": _object_schema(
                    {
                        "run_id": {"type": "string", "minLength": 1},
                        "project_root": project_root,
                        "result": self._step_result_schema,
                        "evidence_max_age_seconds": {"type": ["integer", "null"], "minimum": 1},
                        "profile": profile,
                    },
                    ["run_id", "project_root", "result"],
                ),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_quality_submit",
                "title": "提交代码质量快照",
                "description": "持久化基于真实证据的质量快照；复杂度、冗余、性能等任一维度告警、失败或未评估都会要求修复。",
                "inputSchema": _object_schema(
                    {
                        "project_root": project_root,
                        "snapshot": self._quality_snapshot_schema,
                        "profile": profile,
                    },
                    ["project_root", "snapshot"],
                ),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_provider_invoke",
                "title": "调用受治理能力 Provider",
                "description": "验证固定来源后调用可选只读 UI/UX Provider，并把结果审计到当前 run；缺失或失败时明确回退原生能力。",
                "inputSchema": _object_schema(
                    {
                        "project_root": project_root,
                        "provider_root": {"type": ["string", "null"]},
                        "invocation": self._provider_invocation_schema,
                        "profile": profile,
                    },
                    ["project_root", "invocation"],
                ),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_investigation_propose",
                "title": "提议主动调研",
                "description": "当未知事实会阻断实现或造成重复劳动时，创建带成本、停止条件和证据要求的调研提议；不会自行批准。",
                "inputSchema": _object_schema(
                    {
                        "project_root": project_root,
                        "request": self._investigation_request_schema,
                        "profile": profile,
                    },
                    ["project_root", "request"],
                ),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_investigation_list",
                "title": "查看调研队列",
                "description": "读取当前运行的持久化调研提议、人工选择和执行状态。",
                "inputSchema": _object_schema(
                    {
                        "run_id": {"type": "string", "minLength": 1},
                        "project_root": project_root,
                        "profile": profile,
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                        "after_id": {"type": ["string", "null"], "minLength": 1},
                    },
                    ["run_id", "project_root"],
                ),
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_investigation_decide",
                "title": "记录调研决定",
                "description": "记录用户对调研范围、模式和成本的明确决定；不执行身份验签。",
                "inputSchema": _object_schema(
                    {
                        key: value
                        for key, value in self._investigation_decision_schema["properties"].items()
                        if key != "recorded_at"
                    } | {"project_root": project_root, "profile": profile},
                    [key for key in self._investigation_decision_schema["required"] if key != "recorded_at"] + ["project_root"],
                ),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "engineering_assistant_investigation_start",
                "title": "启动已批准调研",
                "description": "仅把已由人工批准的调研置为运行中；未批准提议会被门禁拒绝。",
                "inputSchema": _object_schema(
                    {
                        "run_id": {"type": "string", "minLength": 1},
                        "investigation_id": {"type": "string", "minLength": 1},
                        "project_root": project_root,
                        "profile": profile,
                    },
                    ["run_id", "investigation_id", "project_root"],
                ),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": False,
                    "openWorldHint": True,
                },
            },
            {
                "name": "engineering_assistant_investigation_finish",
                "title": "提交调研结果",
                "description": "以已登记证据结束或阻断运行中的调研，不接受无证据结论。",
                "inputSchema": _object_schema(
                    {
                        "run_id": {"type": "string", "minLength": 1},
                        "investigation_id": {"type": "string", "minLength": 1},
                        "outcome": {"enum": ["completed", "blocked"]},
                        "evidence_refs": {
                            "type": "array",
                            "minItems": 1,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "project_root": project_root,
                        "profile": profile,
                    },
                    ["run_id", "investigation_id", "outcome", "evidence_refs", "project_root"],
                ),
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": False,
                    "openWorldHint": True,
                },
            },
        ]

    def definitions(self) -> list[dict]:
        return deepcopy(self._definitions)

    def call(self, name: str, arguments: Mapping[str, Any]) -> dict:
        definition = next((item for item in self._definitions if item["name"] == name), None)
        if definition is None:
            raise KeyError(f"unknown tool: {name}")
        payload = dict(arguments)
        validate_instance(payload, definition["inputSchema"], name)
        handler = getattr(self, "_" + name.removeprefix("engineering_assistant_"))
        return handler(payload)

    def _stores(self, project_root: str, profile_id: str):
        if profile_id not in self.catalog.profiles:
            raise ValidationFailure(f"unknown profile {profile_id}")
        profile = self.catalog.profiles[profile_id]
        state_store = StateStore(
            project_root,
            self.catalog.root / "schemas",
            profile.store["run_root"],
        )
        return state_store, EvidenceStore(state_store)

    def _guidance(self, state, node: dict | None, gate: dict) -> dict | None:
        if node is None:
            return None
        capability_id = node["capability"]
        skill = self.catalog.skill_for_capability(capability_id)
        if skill is None:
            fallback_skill_ids = next(
                (
                    skill_ids
                    for flow_id, skill_ids in ROUTES.values()
                    if flow_id == state.flow_id
                ),
                (),
            )
            skill = (
                self.catalog.skills.get(fallback_skill_ids[0])
                if fallback_skill_ids
                else None
            )
        policy_rules = []
        for policy_id in node.get("policy_refs", []):
            policy = self.catalog.policies[policy_id]
            policy_rules.extend(
                {
                    "policy_id": policy_id,
                    "rule_id": rule.id,
                    "condition": rule.condition,
                    "effect": rule.effect,
                    "severity": rule.severity,
                }
                for rule in policy.rules
            )
        return {
            "capability": capability_id,
            "skill": skill.id if skill is not None else None,
            "skill_source": skill.source_path if skill is not None else None,
            "node_goal": node["completion_criteria"],
            "completion_criteria": [
                {"id": criterion_id, "description": description}
                for criterion_id, description in zip(
                    node["criterion_ids"], node["completion_criteria"]
                )
            ],
            "condition": node["when"],
            "evidence_contract": {
                "kinds": node.get("evidence_kinds", []),
                "scope_tags": node.get("evidence_scope_tags", []),
                "requires_registered_evidence": True,
            },
            "policy_rules": policy_rules,
            "next_action": (
                state.next_actions[0]
                if state.next_actions
                else gate.get("reason", "inspect run status")
            ),
        }

    @staticmethod
    def _load_state(state_store: StateStore, run_id: str, profile_id: str):
        state = state_store.load(run_id)
        if state.profile_id != profile_id:
            raise ValidationFailure(
                f"run {run_id} is bound to profile {state.profile_id}, not {profile_id}"
            )
        return state

    def _route(self, arguments: dict) -> dict:
        decision = route_intent(
            route_intent_from_dict(arguments["intent"]),
            self.catalog,
            profile_id=arguments.get("profile", "default"),
        )
        has_flow = bool(decision.flow_id)
        persisted_flow_ready = bool(
            decision.decision == "proceed" and has_flow
        )
        if decision.decision != "proceed":
            recommended_execution = "stop"
            reason = {
                "ask": "route_requires_input",
                "confirm": "route_requires_confirmation",
                "block": "route_blocked",
            }[decision.decision]
        elif not has_flow:
            recommended_execution = "inline"
            reason = "no_persisted_flow"
        else:
            recommended_execution = "persisted_flow"
            reason = "local_persistence_ready"
        return {
            "decision": decision.to_dict(),
            "execution": {
                "persisted_flow_ready": persisted_flow_ready,
                "recommended_execution": recommended_execution,
                "reason": reason,
            },
        }

    def _artifact_validate(self, arguments: dict) -> dict:
        return validate_artifact_payload(
            schema_root=self.catalog.root / "schemas",
            kind=arguments["kind"],
            artifact=arguments["artifact"],
        )

    def _feedback_summary(self, arguments: dict) -> dict:
        # Keep the MCP runtime usable when optional feedback collection is unavailable.
        from .feedback import summarize_feedback_events

        return summarize_feedback_events(
            arguments["project_root"],
            self.catalog.root / "schemas",
            item_limit=arguments.get("limit", 100),
            run_id=arguments.get("run_id"),
        )

    def _start(self, arguments: dict) -> dict:
        profile_id = arguments.get("profile", "default")
        decision = route_intent(
            route_intent_from_dict(arguments["intent"]),
            self.catalog,
            profile_id=profile_id,
        )
        if decision.decision != "proceed":
            raise ValidationFailure(
                f"cannot start route decision {decision.decision}; resolve it first"
            )
        design_source_ref = arguments.get("design_source_ref")
        if design_source_ref:
            validate_design_source_registry(
                arguments["project_root"],
                design_source_ref,
                self.catalog.root / "schemas",
            )
        intent = route_intent_from_dict(arguments["intent"])
        engine = RuntimeEngine(self.catalog)
        state = engine.start(
            arguments["task_id"],
            intent,
            profile_id=profile_id,
            run_id=arguments.get("run_id"),
            context_refs=arguments.get("context_refs", []),
            design_source_ref=design_source_ref,
        )
        state_store, _ = self._stores(
            arguments["project_root"], profile_id
        )
        manifest = {
            "schema_version": "2",
            "product_version": CANONICAL_VERSION,
            "build_version": os.environ.get(
                "ENGINEERING_ASSISTANT_BUILD_VERSION", CANONICAL_VERSION
            ),
            "run_id": state.run_id,
            "task_id": state.task_id,
            "intent": intent.to_dict(),
            "route_decision": decision.to_dict(),
            "profile_id": profile_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        path = state_store.create(state, manifest=manifest)
        approval_store = ApprovalStore(state_store)
        for index, action in enumerate(intent.confirmed_actions, start=1):
            approval_store.save(
                ApprovalRecord(
                    record_id=f"route-confirmation-{index}",
                    run_id=state.run_id,
                    run_revision=state.revision,
                    approval_id=action,
                    decision="approved",
                    scope=[f"flow:{state.flow_id}", f"approval:{action}"],
                    actor_ref="conversation-user",
                    reason="Action was explicitly confirmed in RouteIntent.confirmed_actions.",
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                    source="user_confirmation",
                )
            )
        previous_revision = state.revision
        gate = engine.next(state, approval_records=[])
        if state.revision != previous_revision:
            state_store.save(state, expected_revision=previous_revision)
        node = engine.node_payload(state)
        gate_payload = gate.to_dict()
        return {
            "gate": gate_payload,
            "node": node,
            "guidance": self._guidance(state, node, gate_payload),
            "state": state.to_dict(),
            "state_path": str(path),
        }

    def _next(self, arguments: dict) -> dict:
        state_store, _ = self._stores(
            arguments["project_root"], arguments.get("profile", "default")
        )
        state = self._load_state(
            state_store, arguments["run_id"], arguments.get("profile", "default")
        )
        previous_revision = state.revision
        engine = RuntimeEngine(self.catalog)
        gate = engine.next(
            state,
            approval_records=ApprovalStore(state_store).list(state.run_id),
        )
        if state.revision != previous_revision:
            state_store.save(state, expected_revision=previous_revision)
        gate_payload = gate.to_dict()
        node = engine.node_payload(state)
        return {
            "gate": gate_payload,
            "node": node,
            "guidance": self._guidance(state, node, gate_payload),
            "state": state.to_dict(),
        }

    def _runs_list(self, arguments: dict) -> dict:
        state_store, _ = self._stores(
            arguments["project_root"], arguments.get("profile", "default")
        )
        states, cursor = state_store.list_states(
            include_terminal=arguments.get("include_terminal", False),
            limit=arguments.get("limit", 50),
            after_run_id=arguments.get("after_run_id"),
        )
        return {
            "runs": [state.to_dict() for state in states],
            "next_cursor": cursor,
        }

    def _run_status(self, arguments: dict) -> dict:
        profile_id = arguments.get("profile", "default")
        state_store, _ = self._stores(arguments["project_root"], profile_id)
        state = self._load_state(state_store, arguments["run_id"], profile_id)
        engine = RuntimeEngine(self.catalog)
        node = engine.node_payload(state)
        gate = {
            "decision": "continue" if node else "inspect",
            "evaluated_policies": node.get("policy_refs", []) if node else [],
            "missing_evidence": [],
            "reason": "Recovered current persisted run state.",
            "next_node": state.current_node,
        }
        return {
            "state": state.to_dict(),
            "node": node,
            "guidance": self._guidance(state, node, gate),
        }

    def _evidence_register(self, arguments: dict) -> dict:
        profile_id = arguments.get("profile", "default")
        state_store, evidence_store = self._stores(
            arguments["project_root"], profile_id
        )
        self._load_state(state_store, arguments["run_id"], profile_id)
        evidence = evidence_store.register(
            arguments["run_id"],
            evidence_id=arguments["evidence_id"],
            kind=arguments["kind"],
            uri=arguments["uri"],
            producer=arguments["producer"],
            scope=arguments["scope"],
            scope_tags=arguments["scope_tags"],
            contract_refs=arguments["contract_refs"],
            subject_digest=arguments.get("subject_digest"),
        )
        return {"evidence": evidence.to_dict()}

    def _approval_record(self, arguments: dict) -> dict:
        profile_id = arguments.get("profile", "default")
        state_store, _ = self._stores(arguments["project_root"], profile_id)
        state = self._load_state(state_store, arguments["run_id"], profile_id)
        record_payload = {
            key: value
            for key, value in arguments.items()
            if key not in {"project_root", "profile"}
        }
        record_payload["recorded_at"] = datetime.now(timezone.utc).isoformat()
        record = approval_record_from_dict(record_payload)
        existing = ApprovalStore(state_store).list(state.run_id)
        previous_revision = state.revision
        engine = RuntimeEngine(self.catalog)
        gate = engine.apply_approval_record(
            state,
            record,
            approval_records=existing,
        )
        ApprovalStore(state_store).save(record)
        state_store.save(state, expected_revision=previous_revision)
        if gate.decision == "continue" and state.current_node is None:
            previous_revision = state.revision
            gate = engine.next(
                state,
                approval_records=[*existing, record],
            )
            if state.revision != previous_revision:
                state_store.save(state, expected_revision=previous_revision)
        node = engine.node_payload(state)
        gate_payload = gate.to_dict()
        return {
            "record": record.to_dict(),
            "gate": gate_payload,
            "state": state.to_dict(),
            "node": node,
            "guidance": self._guidance(state, node, gate_payload),
        }

    def _complete(self, arguments: dict) -> dict:
        state_store, evidence_store = self._stores(
            arguments["project_root"], arguments.get("profile", "default")
        )
        state = self._load_state(
            state_store, arguments["run_id"], arguments.get("profile", "default")
        )
        previous_revision = state.revision
        result = step_result_from_dict(arguments["result"])
        if result.run_id != state.run_id or result.node_id != state.current_node:
            raise ValidationFailure("step result does not match the active run and node")
        engine = RuntimeEngine(self.catalog)
        gate = engine.complete_step(
            state,
            result,
            evidence_store=evidence_store,
            evidence_max_age_seconds=arguments.get("evidence_max_age_seconds"),
            approval_records=ApprovalStore(state_store).list(state.run_id),
        )
        node = engine.node_payload(state)
        state_store.save_with_step(
            state,
            expected_revision=previous_revision,
            result=result.to_dict(),
            gate=gate.to_dict(),
            node_output=node,
        )
        gate_payload = gate.to_dict()
        return {
            "gate": gate_payload,
            "node": node,
            "guidance": self._guidance(state, node, gate_payload),
            "state": state.to_dict(),
        }

    def _quality_submit(self, arguments: dict) -> dict:
        state_store, evidence_store = self._stores(
            arguments["project_root"], arguments.get("profile", "default")
        )
        snapshot = quality_snapshot_from_dict(arguments["snapshot"])
        state = self._load_state(
            state_store, snapshot.run_id, arguments.get("profile", "default")
        )
        if state.current_node != snapshot.node_id:
            raise ValidationFailure("quality snapshot does not match the active run and node")
        saved = QualityStore(state_store, evidence_store).save(
            snapshot,
            current_state_revision=state.revision,
        )
        return {"snapshot": saved.to_dict(), "gate": QualityGate.evaluate(saved).to_dict()}

    def _provider_invoke(self, arguments: dict) -> dict:
        profile_id = arguments.get("profile", "default")
        state_store, _ = self._stores(arguments["project_root"], profile_id)
        invocation = provider_invocation_from_dict(arguments["invocation"])
        self._load_state(state_store, invocation.run_id, profile_id)
        executor = ProviderExecutor(self.catalog)
        invocation_digest = executor.invocation_digest(invocation)
        claim_parts = (
            invocation.run_id,
            "providers",
            f"{invocation.invocation_id}.invocation.json",
        )
        result_parts = (
            invocation.run_id,
            "providers",
            f"{invocation.invocation_id}.result.json",
        )
        claim_path = state_store.artifacts.path(*claim_parts)
        result_path = state_store.artifacts.path(*result_parts)
        if result_path.is_file():
            existing = provider_result_from_dict(
                state_store.artifacts.read_json(*result_parts)
            )
            if existing.invocation_digest != invocation_digest:
                raise ValidationFailure(
                    "provider invocation id is already bound to different input"
                )
            return {
                "result": existing.to_dict(),
                "claim_path": str(claim_path),
                "artifact_path": str(result_path),
            }
        claim = {
            "invocation_digest": invocation_digest,
            "invocation": invocation.to_dict(),
        }
        try:
            _, created = state_store.artifacts.create_immutable_json_with_status(
                claim, *claim_parts
            )
        except ArtifactConflict as exc:
            raise ValidationFailure(
                "provider invocation id is already bound to different input"
            ) from exc
        provider = self.catalog.provider_for_capability(invocation.capability_id)
        execution_lease_index = 0
        if created:
            self._write_provider_owner(
                state_store,
                invocation.run_id,
                invocation.invocation_id,
                0,
            )
        if not created:
            lease_seconds = max(
                (provider.timeout_seconds if provider else 0) + 5,
                10,
            )
            active_lease_path = claim_path
            lease_index = 0
            while True:
                candidate = state_store.artifacts.path(
                    invocation.run_id,
                    "providers",
                    f"{invocation.invocation_id}.lease.{lease_index + 1}.json",
                )
                if not candidate.is_file():
                    break
                lease_index += 1
                active_lease_path = candidate
            owner_active = self._provider_owner_active(
                state_store,
                invocation.run_id,
                invocation.invocation_id,
                lease_index,
            )
            if not owner_active and (
                self._provider_owner_exists(
                    state_store,
                    invocation.run_id,
                    invocation.invocation_id,
                    lease_index,
                )
                or time.time() - active_lease_path.stat().st_mtime > lease_seconds
            ):
                lease_parts = (
                    invocation.run_id,
                    "providers",
                    f"{invocation.invocation_id}.lease.{lease_index + 1}.json",
                )
                _, created = state_store.artifacts.create_immutable_json_with_status(
                    {
                        "invocation_digest": invocation_digest,
                        "lease_index": lease_index + 1,
                    },
                    *lease_parts,
                )
                if created:
                    execution_lease_index = lease_index + 1
                    self._write_provider_owner(
                        state_store,
                        invocation.run_id,
                        invocation.invocation_id,
                        lease_index + 1,
                    )
                if created and result_path.is_file():
                    existing = provider_result_from_dict(
                        state_store.artifacts.read_json(*result_parts)
                    )
                    if existing.invocation_digest != invocation_digest:
                        raise ValidationFailure(
                            "provider invocation id is already bound to different input"
                        )
                    return {
                        "result": existing.to_dict(),
                        "claim_path": str(claim_path),
                        "artifact_path": str(result_path),
                    }
            if not created:
                pending = ProviderResult(
                    invocation_id=invocation.invocation_id,
                    invocation_digest=invocation_digest,
                    requested_provider_id=provider.id if provider else "unknown",
                    provider_id=provider.id if provider else "unknown",
                    capability_id=invocation.capability_id,
                    status="in_progress",
                    output="Provider invocation is already in progress.",
                    trust_level="untrusted_advisory",
                    source_revision=(
                        provider.source.revision if provider and provider.source else None
                    ),
                    expected_source_integrity=(
                        provider.source.integrity if provider and provider.source else None
                    ),
                    observed_source_integrity=None,
                    observed_at=datetime.now(timezone.utc).isoformat(),
                    next_action="retry",
                    warning="A matching first-writer invocation has not finished yet.",
                    fallback_provider_id=(
                        provider.fallback_provider_id if provider else None
                    ),
                )
                return {
                    "result": pending.to_dict(),
                    "claim_path": str(claim_path),
                    "artifact_path": None,
                }
        try:
            result = executor.invoke(
                invocation,
                provider_root=arguments.get("provider_root"),
                denied_roots=[arguments["project_root"]],
            )
            try:
                state_store.artifacts.create_immutable_json(
                    result.to_dict(), *result_parts
                )
            except ArtifactConflict:
                result = provider_result_from_dict(
                    state_store.artifacts.read_json(*result_parts)
                )
                if result.invocation_digest != invocation_digest:
                    raise ValidationFailure(
                        "provider invocation result conflicts with its immutable claim"
                    )
        except Exception as exc:
            self._write_provider_terminal(
                state_store,
                invocation.run_id,
                invocation.invocation_id,
                execution_lease_index,
                "failed",
                type(exc).__name__,
            )
            raise
        else:
            self._write_provider_terminal(
                state_store,
                invocation.run_id,
                invocation.invocation_id,
                execution_lease_index,
                "completed",
                None,
            )
        return {
            "result": result.to_dict(),
            "claim_path": str(claim_path),
            "artifact_path": str(result_path),
        }

    @staticmethod
    def _provider_owner_parts(run_id: str, invocation_id: str, index: int) -> tuple[str, ...]:
        return (
            run_id,
            "providers",
            f"{invocation_id}.lease.{index}.owner.json",
        )

    @staticmethod
    def _process_identity(pid: int) -> str | None:
        proc_stat = Path(f"/proc/{pid}/stat")
        if proc_stat.is_file():
            fields = proc_stat.read_text(encoding="utf-8").split()
            return fields[21] if len(fields) > 21 else None
        try:
            result = subprocess.run(
                ["/bin/ps", "-p", str(pid), "-o", "lstart="],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        identity = result.stdout.strip()
        return identity or None

    def _write_provider_owner(
        self, state_store: StateStore, run_id: str, invocation_id: str, index: int
    ) -> None:
        state_store.artifacts.create_immutable_json(
            {"pid": os.getpid(), "process_identity": self._process_identity(os.getpid())},
            *self._provider_owner_parts(run_id, invocation_id, index),
        )

    def _provider_owner_exists(
        self, state_store: StateStore, run_id: str, invocation_id: str, index: int
    ) -> bool:
        return state_store.artifacts.path(
            *self._provider_owner_parts(run_id, invocation_id, index)
        ).is_file()

    @staticmethod
    def _provider_terminal_parts(
        run_id: str, invocation_id: str, index: int
    ) -> tuple[str, ...]:
        return (
            run_id,
            "providers",
            f"{invocation_id}.lease.{index}.terminal.json",
        )

    def _write_provider_terminal(
        self,
        state_store: StateStore,
        run_id: str,
        invocation_id: str,
        index: int,
        status: str,
        error_type: str | None,
    ) -> None:
        state_store.artifacts.create_immutable_json(
            {"status": status, "error_type": error_type},
            *self._provider_terminal_parts(run_id, invocation_id, index),
        )

    def _provider_owner_active(
        self, state_store: StateStore, run_id: str, invocation_id: str, index: int
    ) -> bool:
        parts = self._provider_owner_parts(run_id, invocation_id, index)
        terminal_path = state_store.artifacts.path(
            *self._provider_terminal_parts(run_id, invocation_id, index)
        )
        if terminal_path.is_file():
            return False
        path = state_store.artifacts.path(*parts)
        if not path.is_file():
            return False
        owner = state_store.artifacts.read_json(*parts)
        pid = owner.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except (OSError, PermissionError):
            return False
        expected = owner.get("process_identity")
        current = self._process_identity(pid)
        return expected is None or current == expected

    def _investigation_propose(self, arguments: dict) -> dict:
        state_store, _ = self._stores(
            arguments["project_root"], arguments.get("profile", "default")
        )
        request = investigation_request_from_dict(arguments["request"])
        profile_id = arguments.get("profile", "default")
        self._load_state(state_store, request.run_id, profile_id)
        profile = self.catalog.profiles[profile_id]
        record = InvestigationStore(state_store).propose(
            request,
            investigation_policy=dict(profile.investigation_policy),
        )
        return {
            "record": record.to_dict(),
            "evidence_contract": investigation_evidence_contract(record),
            "approval_required": record.request.status == "proposed",
            "choices": ["auto_readonly", "suggest_then_run", "guided", "disabled"],
        }

    def _investigation_list(self, arguments: dict) -> dict:
        state_store, _ = self._stores(
            arguments["project_root"], arguments.get("profile", "default")
        )
        self._load_state(
            state_store, arguments["run_id"], arguments.get("profile", "default")
        )
        records, next_after_id = InvestigationStore(state_store).list(
            arguments["run_id"],
            limit=arguments.get("limit", 50),
            after_id=arguments.get("after_id"),
        )
        return {
            "records": [item.to_dict() for item in records],
            "evidence_contracts": {
                item.request.id: investigation_evidence_contract(item)
                for item in records
            },
            "next_after_id": next_after_id,
        }

    def _investigation_decide(self, arguments: dict) -> dict:
        profile_id = arguments.get("profile", "default")
        state_store, evidence_store = self._stores(
            arguments["project_root"], profile_id
        )
        state = self._load_state(state_store, arguments["run_id"], profile_id)
        payload = {
            key: value
            for key, value in arguments.items()
            if key not in {"project_root", "profile"}
        }
        payload["recorded_at"] = datetime.now(timezone.utc).isoformat()
        decision = investigation_decision_record_from_dict(payload)
        record = InvestigationStore(state_store, evidence_store).apply_decision(
            decision,
            current_run_revision=state.revision,
        )
        return {"decision": decision.to_dict(), "record": record.to_dict()}

    def _investigation_start(self, arguments: dict) -> dict:
        state_store, _ = self._stores(
            arguments["project_root"], arguments.get("profile", "default")
        )
        self._load_state(
            state_store, arguments["run_id"], arguments.get("profile", "default")
        )
        record = InvestigationStore(state_store).start(
            arguments["run_id"], arguments["investigation_id"]
        )
        return {
            "record": record.to_dict(),
            "evidence_contract": investigation_evidence_contract(record),
        }

    def _investigation_finish(self, arguments: dict) -> dict:
        state_store, evidence_store = self._stores(
            arguments["project_root"], arguments.get("profile", "default")
        )
        self._load_state(
            state_store, arguments["run_id"], arguments.get("profile", "default")
        )
        record = InvestigationStore(state_store, evidence_store).finish(
            arguments["run_id"],
            arguments["investigation_id"],
            outcome=arguments["outcome"],
            evidence_refs=arguments["evidence_refs"],
        )
        return {
            "record": record.to_dict(),
            "evidence_contract": investigation_evidence_contract(record),
        }

class MCPServer:
    def __init__(self, tools: RuntimeTools | None = None) -> None:
        self.tools = tools or RuntimeTools()

    @staticmethod
    def _success(request_id: Any, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def handle(self, message: Mapping[str, Any]) -> dict | None:
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self._error(message.get("id"), -32600, "Invalid Request")
        request_id = message.get("id")
        method = message["method"]
        if request_id is None:
            if method == "notifications/initialized":
                return None
            return None
        params = message.get("params", {})
        if not isinstance(params, dict):
            return self._error(request_id, -32602, "Invalid params")
        if method == "initialize":
            requested = params.get("protocolVersion")
            negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
            return self._success(
                request_id,
                {
                    "protocolVersion": negotiated,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "engineering-assistant",
                        "version": CANONICAL_VERSION,
                    },
                },
            )
        if method == "ping":
            return self._success(request_id, {})
        if method == "tools/list":
            return self._success(request_id, {"tools": self.tools.definitions()})
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return self._error(request_id, -32602, "Invalid tool call params")
            try:
                structured = self.tools.call(name, arguments)
            except KeyError as exc:
                return self._error(request_id, -32602, str(exc))
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                return self._success(
                    request_id,
                    {"content": [{"type": "text", "text": detail}], "isError": True},
                )
            encoded = json.dumps(structured, ensure_ascii=False, sort_keys=True)
            return self._success(
                request_id,
                {
                    "content": [{"type": "text", "text": encoded}],
                    "structuredContent": structured,
                    "isError": False,
                },
            )
        return self._error(request_id, -32601, f"Method not found: {method}")


def serve_stdio(
    server: MCPServer | None = None,
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    server = server or MCPServer()
    while True:
        line = input_stream.readline(MAX_MCP_REQUEST_CHARS + 1)
        if not line:
            break
        if len(line) > MAX_MCP_REQUEST_CHARS:
            while line and not line.endswith("\n"):
                line = input_stream.readline(MAX_MCP_REQUEST_CHARS + 1)
            response = MCPServer._error(None, -32700, "Parse error: request is too large")
            output_stream.write(
                json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            output_stream.flush()
            continue
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("message must be an object")
            response = server.handle(message)
        except (json.JSONDecodeError, ValueError, RecursionError) as exc:
            response = MCPServer._error(None, -32700, f"Parse error: {exc}")
        if response is not None:
            output_stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            output_stream.flush()
    return 0
