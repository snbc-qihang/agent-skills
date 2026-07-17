from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.mcp_server import (  # noqa: E402
    MAX_MCP_REQUEST_CHARS,
    MCPServer,
    RuntimeTools,
    serve_stdio,
)
from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.engine import RuntimeEngine  # noqa: E402
from engineering_assistant.evidence import EvidenceStore  # noqa: E402
from engineering_assistant.governance import (  # noqa: E402
    InvestigationStore,
    investigation_evidence_contract,
)
from engineering_assistant.model import (  # noqa: E402
    EvidenceRef,
    InvestigationDecisionGrant,
)
from engineering_assistant.natural_intent import normalize_request  # noqa: E402
from engineering_assistant.provider_runtime import ProviderExecutor  # noqa: E402
from engineering_assistant.state_store import StateStore  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class MCPServerTests(unittest.TestCase):
    class TestVerifier:
        def verify_evidence(self, _run_id, evidence) -> bool:
            return evidence.attestation == "mcp-test-receipt"

        def verify_decision(self, grant) -> bool:
            return grant.token == "mcp-test-grant-token"

        def verify_run_approval(self, _grant) -> bool:
            return False

    def setUp(self) -> None:
        self.server = MCPServer(
            RuntimeTools(
                ROOT,
                trust_verifier=self.TestVerifier(),
                evidence_broker_enabled=True,
            )
        )

    def request(self, method: str, params: dict | None = None, request_id: int = 1) -> dict:
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        response = self.server.handle(message)
        self.assertIsNotNone(response)
        return response

    def test_stdio_rejects_oversized_line_before_json_parsing_and_recovers(self) -> None:
        import io

        oversized = "x" * (MAX_MCP_REQUEST_CHARS + 1) + "\n"
        ping = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})
        output = io.StringIO()

        code = serve_stdio(
            self.server,
            input_stream=io.StringIO(oversized + ping + "\n"),
            output_stream=output,
        )

        self.assertEqual(0, code)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(-32700, responses[0]["error"]["code"])
        self.assertEqual({}, responses[1]["result"])

    def test_stdio_recovers_after_excessively_deep_json(self) -> None:
        import io

        deep = "[" * 10_000 + "0" + "]" * 10_000
        ping = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})
        output = io.StringIO()

        code = serve_stdio(
            self.server,
            input_stream=io.StringIO(deep + "\n" + ping + "\n"),
            output_stream=output,
        )

        self.assertEqual(0, code)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(-32700, responses[0]["error"]["code"])
        self.assertEqual({}, responses[1]["result"])

    def test_stdio_explicitly_recovers_from_json_recursion_error(self) -> None:
        import io

        output = io.StringIO()
        ping_message = {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}}

        with patch(
            "engineering_assistant.mcp_server.json.loads",
            side_effect=[RecursionError("deep JSON"), ping_message],
        ):
            code = serve_stdio(
                self.server,
                input_stream=io.StringIO("deep\n{}\n"),
                output_stream=output,
            )

        self.assertEqual(0, code)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(-32700, responses[0]["error"]["code"])
        self.assertEqual({}, responses[1]["result"])

    def test_initialize_and_tools_list_follow_mcp_contract(self) -> None:
        initialized = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        self.assertEqual("2025-06-18", initialized["result"]["protocolVersion"])
        self.assertEqual({"tools": {"listChanged": False}}, initialized["result"]["capabilities"])

        listed = self.request("tools/list", {})
        names = [tool["name"] for tool in listed["result"]["tools"]]
        self.assertEqual(
            [
                "engineering_assistant_route",
                "engineering_assistant_artifact_validate",
                "engineering_assistant_start",
                "engineering_assistant_next",
                "engineering_assistant_complete",
                "engineering_assistant_quality_submit",
                "engineering_assistant_provider_invoke",
                "engineering_assistant_investigation_propose",
                "engineering_assistant_investigation_list",
                "engineering_assistant_investigation_start",
                "engineering_assistant_investigation_finish",
            ],
            names,
        )
        self.assertNotIn("engineering_assistant_approve", names)
        self.assertTrue(listed["result"]["tools"][0]["annotations"]["readOnlyHint"])

    def test_feedback_summary_is_not_exposed_without_a_trusted_workspace_binding(self) -> None:
        tools = RuntimeTools(ROOT)
        names = {item["name"] for item in tools.definitions()}

        self.assertNotIn("engineering_assistant_feedback_summary", names)
        with self.assertRaisesRegex(KeyError, "unknown tool"):
            tools.call("engineering_assistant_feedback_summary", {})

    def test_route_reports_when_persisted_flow_cannot_receive_trusted_evidence(self) -> None:
        intent = normalize_request("Implement the accepted endpoint behavior").to_dict()

        unavailable = RuntimeTools(ROOT).call(
            "engineering_assistant_route",
            {"intent": intent},
        )
        self.assertEqual(
            {
                "external_approval_available": False,
                "external_evidence_available": False,
                "persisted_flow_ready": False,
                "recommended_execution": "skills_only",
                "reason": "host_trust_unavailable",
            },
            unavailable["execution"],
        )

        available = RuntimeTools(
            ROOT,
            trust_verifier=self.TestVerifier(),
            evidence_broker_enabled=True,
        ).call(
            "engineering_assistant_route",
            {"intent": intent},
        )
        self.assertTrue(available["execution"]["persisted_flow_ready"])
        self.assertEqual(
            "persisted_flow",
            available["execution"]["recommended_execution"],
        )

    def test_route_never_recommends_execution_for_ask_confirm_or_block(self) -> None:
        base = {
            "task_kind": "implement",
            "requested_outcome": "change code",
            "scope": ["module-a"],
            "requested_external_actions": [],
            "risk_signals": [],
            "confidence": 0.95,
            "evidence": ["user request"],
        }
        cases = (
            ({**base, "confidence": 0.4}, "ask", "route_requires_input"),
            (
                {**base, "requested_external_actions": ["production write"]},
                "confirm",
                "route_requires_confirmation",
            ),
            (
                {**base, "risk_signals": ["forbidden"]},
                "block",
                "route_blocked",
            ),
        )
        for intent, decision, reason in cases:
            with self.subTest(decision=decision):
                routed = self.server.tools.call(
                    "engineering_assistant_route",
                    {"intent": intent},
                )
                self.assertEqual(decision, routed["decision"]["decision"])
                self.assertFalse(routed["execution"]["persisted_flow_ready"])
                self.assertEqual("stop", routed["execution"]["recommended_execution"])
                self.assertEqual(reason, routed["execution"]["reason"])

        broker_ready = RuntimeTools(
            ROOT,
            trust_verifier=self.TestVerifier(),
            evidence_broker_enabled=True,
            approval_broker_enabled=True,
        ).call(
            "engineering_assistant_route",
            {"intent": {**base, "requested_external_actions": ["production write"]}},
        )
        self.assertEqual("confirm", broker_ready["decision"]["decision"])
        self.assertEqual("stop", broker_ready["execution"]["recommended_execution"])
        self.assertTrue(broker_ready["execution"]["persisted_flow_ready"])

    def test_no_broker_runtime_rejects_flow_start_without_writing_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            tools = RuntimeTools(ROOT)
            intent = normalize_request(
                "Implement the accepted endpoint behavior"
            ).to_dict()
            with self.assertRaisesRegex(ValidationFailure, "evidence broker"):
                tools.call(
                    "engineering_assistant_start",
                    {
                        "intent": intent,
                        "task_id": "no-broker-task",
                        "run_id": "no-broker-run",
                        "project_root": str(project),
                    },
                )
            self.assertFalse(
                (project / ".run-artifacts/engineering-assistant").exists()
            )

    def test_no_broker_runtime_rejects_existing_run_provider_and_investigation_paths(self) -> None:
        tools = RuntimeTools(ROOT)
        with self.assertRaisesRegex(ValidationFailure, "evidence broker"):
            tools._provider_invoke({})
        for method in (
            tools._investigation_propose,
            tools._investigation_list,
            tools._investigation_start,
            tools._investigation_finish,
        ):
            with self.subTest(method=method.__name__):
                with self.assertRaisesRegex(ValidationFailure, "evidence broker"):
                    method({})

    def test_artifact_validator_is_a_direct_readonly_mcp_tool(self) -> None:
        artifact = {
            "run_id": "run-1",
            "node_id": "review",
            "status": "completed",
            "criteria_results": [],
            "outputs": [],
            "findings": [],
            "open_questions": [],
            "requested_transition": "continue",
        }

        result = self.server.tools.call(
            "engineering_assistant_artifact_validate",
            {"kind": "step-result", "artifact": artifact},
        )

        self.assertEqual("passed", result["status"])
        self.assertEqual("step-result", result["kind"])
        definition = next(
            item
            for item in self.server.tools.definitions()
            if item["name"] == "engineering_assistant_artifact_validate"
        )
        self.assertTrue(definition["annotations"]["readOnlyHint"])
        self.assertEqual(
            {"kind", "artifact"}, set(definition["inputSchema"]["properties"])
        )
        self.assertTrue(
            {
                "capability-provider-spec",
                "provider-invocation",
                "provider-result",
                "feedback-capture",
                "feedback-event",
                "feedback-disposition",
                "quality-snapshot",
                "investigation-request",
                "investigation-record",
            }.issubset(definition["inputSchema"]["properties"]["kind"]["enum"])
        )

    def test_artifact_validator_cannot_read_a_model_selected_local_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "additional property project_root"):
            self.server.tools.call(
                "engineering_assistant_artifact_validate",
                {
                    "project_root": "/private",
                    "kind": "step-result",
                    "input": "secret.json",
                },
            )

    def test_artifact_validator_rejects_an_incomplete_quality_contract(self) -> None:
        artifact = {
            "id": "quality-incomplete",
            "run_id": "run-1",
            "node_id": "quality",
            "state_revision": 1,
            "base_ref": "git:base",
            "candidate_ref": "sha256:" + "0" * 64,
            "candidate_evidence_id": "evidence-1",
            "dimensions": [
                {
                    "id": "complexity",
                    "status": "pass",
                    "delta": 0,
                    "summary": "Only one dimension was supplied.",
                    "evidence_ids": ["evidence-1"],
                }
            ],
            "findings": [],
            "required_repairs": [],
            "evidence_refs": ["evidence-1"],
            "observed_at": "2026-07-14T08:00:00+00:00",
        }

        with self.assertRaisesRegex(ValueError, "quality dimensions"):
            self.server.tools.call(
                "engineering_assistant_artifact_validate",
                {"kind": "quality-snapshot", "artifact": artifact},
            )
        duplicate_dimensions = dict(artifact)
        duplicate_dimensions["dimensions"] = artifact["dimensions"] * 6
        with self.assertRaisesRegex(ValueError, "quality dimensions"):
            self.server.tools.call(
                "engineering_assistant_artifact_validate",
                {
                    "kind": "quality-snapshot",
                    "artifact": duplicate_dimensions,
                },
            )

    def test_artifact_validator_does_not_echo_invalid_secret_values(self) -> None:
        secret = "secret-status-value-that-must-not-be-echoed"
        artifact = {
            "run_id": "run-1",
            "node_id": "review",
            "status": secret,
            "criteria_results": [],
            "outputs": [],
            "findings": [],
            "open_questions": [],
            "requested_transition": "continue",
        }

        with self.assertRaises(ValueError) as raised:
            self.server.tools.call(
                "engineering_assistant_artifact_validate",
                {"kind": "step-result", "artifact": artifact},
            )
        self.assertNotIn(secret, str(raised.exception))
        self.assertIn("does not conform", str(raised.exception))

    def test_route_tool_returns_structured_and_text_content(self) -> None:
        response = self.request(
            "tools/call",
            {
                "name": "engineering_assistant_route",
                "arguments": {
                    "intent": {
                        "task_kind": "design",
                        "requested_outcome": "设计一个有边界的变更。",
                        "scope": ["module-a"],
                        "risk_signals": [],
                        "requested_external_actions": [],
                        "confidence": 0.95,
                        "evidence": ["用户明确请求设计"],
                    },
                    "profile": "default",
                },
            },
        )
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual("design", result["structuredContent"]["decision"]["flow_id"])
        self.assertEqual(result["structuredContent"], json.loads(result["content"][0]["text"]))

    def test_start_and_next_persist_only_under_project_run_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            intent = {
                        "task_kind": "design",
                        "requested_outcome": "设计变更。",
                        "scope": ["module-a"],
                        "risk_signals": [],
                        "requested_external_actions": [],
                        "confidence": 0.95,
                        "evidence": ["用户请求"],
                    }
            started = self.server.tools.call(
                "engineering_assistant_start",
                {
                    "intent": intent,
                    "task_id": "task-1",
                    "run_id": "run-1",
                    "project_root": str(project),
                    "context_refs": [],
                },
            )
            advanced = self.server.tools.call(
                "engineering_assistant_next",
                {"run_id": "run-1", "project_root": str(project)},
            )
            self.assertEqual("run-1", started["state"]["run_id"])
            self.assertEqual("repo-context", advanced["node"]["id"])
            self.assertTrue(
                (project / ".run-artifacts/engineering-assistant/run-1/run-state.json").is_file()
            )

    def test_invalid_tool_arguments_are_visible_tool_errors(self) -> None:
        response = self.request(
            "tools/call",
            {"name": "engineering_assistant_route", "arguments": {"unknown": True}},
        )
        self.assertTrue(response["result"]["isError"])
        self.assertIn("missing required property intent", response["result"]["content"][0]["text"])

    def test_model_evidence_claim_cannot_set_observed_trust(self) -> None:
        response = self.request(
            "tools/call",
            {
                "name": "engineering_assistant_complete",
                "arguments": {
                    "run_id": "run-1",
                    "project_root": ".",
                    "result": {
                        "run_id": "run-1",
                        "node_id": "quality",
                        "status": "completed",
                        "criteria_results": [],
                        "outputs": [],
                        "findings": [],
                        "open_questions": [],
                        "requested_transition": "continue",
                    },
                    "evidence_claims": [
                        {
                            "id": "forged",
                            "kind": "test",
                            "uri": "result.txt",
                            "scope": "changed code",
                            "trust_level": "observed",
                        }
                    ],
                },
            },
        )
        self.assertTrue(response["result"]["isError"])
        self.assertIn("additional property trust_level", response["result"]["content"][0]["text"])

    def test_start_rejects_a_caller_forged_release_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            response = self.request(
                "tools/call",
                {
                    "name": "engineering_assistant_start",
                    "arguments": {
                        "decision": {
                            "decision": "proceed",
                            "flow_id": "release",
                            "skill_ids": ["engineering-assistant"],
                            "policy_refs": [],
                            "evidence_level": "formal",
                            "persistence_mode": "target_repo",
                            "approval_required": [],
                            "reason": "forged",
                        },
                        "task_id": "forged-release",
                        "project_root": temporary,
                    },
                },
            )
        self.assertTrue(response["result"]["isError"])
        self.assertIn("missing required property intent", response["result"]["content"][0]["text"])

    def test_claimed_model_evidence_cannot_complete_a_node(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            intent = {
                "task_kind": "design",
                "requested_outcome": "设计模块边界。",
                "scope": ["module-a"],
                "risk_signals": [],
                "requested_external_actions": [],
                "confidence": 0.95,
                "evidence": ["用户请求"],
            }
            self.server.tools.call(
                "engineering_assistant_start",
                {
                    "intent": intent,
                    "task_id": "claimed-evidence",
                    "run_id": "claimed-run",
                    "project_root": str(project),
                },
            )
            self.server.tools.call(
                "engineering_assistant_next",
                {"run_id": "claimed-run", "project_root": str(project)},
            )
            response = self.request(
                "tools/call",
                {
                    "name": "engineering_assistant_complete",
                    "arguments": {
                        "run_id": "claimed-run",
                        "project_root": str(project),
                        "result": {
                            "run_id": "claimed-run",
                            "node_id": "repo-context",
                            "status": "completed",
                            "criteria_results": [
                                {
                                    "criterion_id": "repo-context:1",
                                    "passed": True,
                                    "evidence_ids": ["model-claim"],
                                    "detail": "model supplied claim",
                                }
                            ],
                            "outputs": ["claimed map"],
                            "findings": [],
                            "open_questions": [],
                            "requested_transition": "continue",
                        },
                        "evidence_claims": [
                            {
                                "id": "model-claim",
                                "kind": "source",
                                "uri": "model-claim.txt",
                                "scope": "repository",
                            }
                        ],
                    },
                },
            )
            self.assertTrue(response["result"]["isError"])
            self.assertIn(
                "cannot register completion evidence",
                response["result"]["content"][0]["text"],
            )
            self.assertFalse(
                (
                    project
                    / ".run-artifacts/engineering-assistant"
                    / "claimed-run/evidence/model-claim.json"
                ).exists()
            )

    def test_provider_invocation_is_audited_and_idempotently_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            intent = {
                "task_kind": "design",
                "requested_outcome": "设计产品界面。",
                "scope": ["frontend"],
                "risk_signals": [],
                "requested_external_actions": [],
                "confidence": 0.95,
                "evidence": ["用户请求"],
            }
            self.server.tools.call(
                "engineering_assistant_start",
                {
                    "intent": intent,
                    "task_id": "provider-task",
                    "run_id": "provider-run",
                    "project_root": str(project),
                },
            )
            invocation = {
                "invocation_id": "provider-advice-1",
                "run_id": "provider-run",
                "capability_id": "frontend-design",
                "query": "enterprise dashboard",
                "operation": "design_system",
                "project_name": "Dashboard",
                "domain": None,
                "stack": None,
                "variance": 5,
                "motion": 3,
                "density": 7,
            }
            arguments = {
                "project_root": str(project),
                "provider_root": None,
                "invocation": invocation,
            }
            first = self.server.tools.call(
                "engineering_assistant_provider_invoke", arguments
            )
            second = self.server.tools.call(
                "engineering_assistant_provider_invoke", arguments
            )
            self.assertEqual("fallback", first["result"]["status"])
            self.assertEqual("native-engineering", first["result"]["provider_id"])
            self.assertEqual(first, second)
            self.assertTrue(Path(first["artifact_path"]).is_file())
            conflicting = dict(invocation)
            conflicting["query"] = "healthcare prototype"
            response = self.request(
                "tools/call",
                {
                    "name": "engineering_assistant_provider_invoke",
                    "arguments": {**arguments, "invocation": conflicting},
                },
            )
            self.assertTrue(response["result"]["isError"])
            self.assertIn(
                "bound to different input", response["result"]["content"][0]["text"]
            )

            Path(first["artifact_path"]).unlink()
            recovered = self.server.tools.call(
                "engineering_assistant_provider_invoke", arguments
            )
            self.assertEqual("fallback", recovered["result"]["status"])
            self.assertTrue(Path(recovered["artifact_path"]).is_file())

            failed_invocation = {**invocation, "invocation_id": "provider-crash-1"}
            failed_arguments = {**arguments, "invocation": failed_invocation}
            with patch.object(
                ProviderExecutor, "invoke", side_effect=RuntimeError("executor bug")
            ):
                failed = self.request(
                    "tools/call",
                    {
                        "name": "engineering_assistant_provider_invoke",
                        "arguments": failed_arguments,
                    },
                )
            self.assertTrue(failed["result"]["isError"])
            retried = self.server.tools.call(
                "engineering_assistant_provider_invoke", failed_arguments
            )
            self.assertEqual("fallback", retried["result"]["status"])
            self.assertTrue(Path(retried["artifact_path"]).is_file())

    def test_quality_snapshot_succeeds_through_mcp_tools_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            verifier = self.TestVerifier()
            server = MCPServer(
                RuntimeTools(
                    ROOT,
                    trust_verifier=verifier,
                    evidence_broker_enabled=True,
                )
            )
            state_store = StateStore(project, ROOT / "schemas")
            state = RuntimeEngine(load_catalog(ROOT)).start(
                "mcp-quality-task",
                normalize_request("Implement the accepted endpoint behavior"),
                run_id="mcp-quality-run",
            )
            state.current_node = "quality"
            state.status = "running"
            state_store.create(state)
            evidence_store = EvidenceStore(state_store, verifier)
            candidate = project / "candidate.diff"
            candidate.write_text("observed candidate\n", encoding="utf-8")
            candidate_digest = "sha256:" + hashlib.sha256(
                candidate.read_bytes()
            ).hexdigest()

            evidence_specs = [
                ("candidate-source", "source", candidate, []),
                ("quality-test", "test", project / "quality-test.txt", []),
                ("quality-review", "review", project / "quality-review.txt", []),
                (
                    "performance-test",
                    "test",
                    project / "performance-test.txt",
                    [
                        "quality-dimension:performance",
                        "quality-measurement:benchmark",
                    ],
                ),
            ]
            for evidence_id, kind, path, tags in evidence_specs:
                if not path.exists():
                    path.write_text(f"observed {evidence_id}\n", encoding="utf-8")
                evidence_store.save(
                    state.run_id,
                    EvidenceRef(
                        id=evidence_id,
                        kind=kind,
                        uri=str(path),
                        producer="mcp-test-host",
                        observed_at=datetime.now(timezone.utc).isoformat(),
                        trust_level="observed",
                        scope="candidate-bound quality evidence",
                        scope_tags=tags,
                        subject_digest=candidate_digest,
                        attestation="mcp-test-receipt",
                    ),
                )
            dimension_evidence = {
                "correctness": "quality-test",
                "complexity": "quality-review",
                "redundancy": "quality-review",
                "performance": "performance-test",
                "architecture": "quality-review",
                "test_quality": "quality-test",
            }
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 51,
                    "method": "tools/call",
                    "params": {
                        "name": "engineering_assistant_quality_submit",
                        "arguments": {
                            "project_root": str(project),
                            "snapshot": {
                                "id": "mcp-quality-snapshot",
                                "run_id": state.run_id,
                                "node_id": "quality",
                                "state_revision": state.revision,
                                "base_ref": "base-ref",
                                "candidate_ref": candidate_digest,
                                "candidate_evidence_id": "candidate-source",
                                "dimensions": [
                                    {
                                        "id": dimension,
                                        "status": "pass",
                                        "delta": 0,
                                        "summary": f"{dimension} observed",
                                        "evidence_ids": [evidence_id],
                                    }
                                    for dimension, evidence_id in dimension_evidence.items()
                                ],
                                "findings": [],
                                "required_repairs": [],
                                "evidence_refs": [
                                    "candidate-source",
                                    "quality-test",
                                    "quality-review",
                                    "performance-test",
                                ],
                                "observed_at": datetime.now(timezone.utc).isoformat(),
                            },
                        },
                    },
                }
            )

            result = response["result"]
            self.assertFalse(result["isError"])
            self.assertEqual("pass", result["structuredContent"]["gate"]["decision"])
            self.assertTrue(
                (
                    project
                    / ".run-artifacts/engineering-assistant"
                    / state.run_id
                    / "quality/mcp-quality-snapshot.json"
                ).is_file()
            )

    def test_investigation_host_approval_and_lifecycle_use_mcp_tools_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            verifier = self.TestVerifier()
            server = MCPServer(
                RuntimeTools(
                    ROOT,
                    trust_verifier=verifier,
                    evidence_broker_enabled=True,
                )
            )
            state_store = StateStore(project, ROOT / "schemas")
            state = RuntimeEngine(load_catalog(ROOT)).start(
                "mcp-investigation-task",
                normalize_request("Design the module boundary and interface"),
                run_id="mcp-investigation-run",
            )
            state_store.create(state)
            request = {
                "id": "mcp-investigation",
                "run_id": state.run_id,
                "question": "Which official contract applies?",
                "reason": "The implementation boundary is uncertain.",
                "source_scope": ["official_docs"],
                "reported_blocking": False,
                "mode": "suggest_then_run",
                "estimated_cost": "low",
                "stop_conditions": ["The primary contract is identified."],
                "evidence_requirements": ["Official documentation."],
                "status": "proposed",
            }
            proposed = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 61,
                    "method": "tools/call",
                    "params": {
                        "name": "engineering_assistant_investigation_propose",
                        "arguments": {
                            "project_root": str(project),
                            "request": request,
                        },
                    },
                }
            )["result"]
            self.assertFalse(proposed["isError"])
            self.assertTrue(proposed["structuredContent"]["approval_required"])
            listed = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 611,
                    "method": "tools/call",
                    "params": {
                        "name": "engineering_assistant_investigation_list",
                        "arguments": {
                            "project_root": str(project),
                            "run_id": state.run_id,
                        },
                    },
                }
            )["result"]
            self.assertFalse(listed["isError"])
            self.assertIsNone(listed["structuredContent"]["next_after_id"])
            self.assertEqual(
                ["mcp-investigation"],
                [
                    item["request"]["id"]
                    for item in listed["structuredContent"]["records"]
                ],
            )

            now = datetime.now(timezone.utc)
            evidence_store = EvidenceStore(state_store, verifier)
            host_store = InvestigationStore(state_store, evidence_store)
            host_store.apply_grant(
                InvestigationDecisionGrant(
                    grant_id="mcp-host-grant",
                    broker_id="mcp-test-broker",
                    audience="engineering-assistant",
                    action="investigation.select_mode",
                    run_id=state.run_id,
                    investigation_id="mcp-investigation",
                    run_revision=state.revision,
                    decision="approve",
                    selected_mode="guided",
                    allowed_source_scope=["official_docs"],
                    max_cost="low",
                    issued_at=now.isoformat(),
                    expires_at=(now + timedelta(hours=1)).isoformat(),
                    actor_ref="host-reviewer",
                    nonce="mcp-test-nonce-0001",
                    token="mcp-test-grant-token",
                ),
                verifier=verifier,
                current_run_revision=state.revision,
            )
            started = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 62,
                    "method": "tools/call",
                    "params": {
                        "name": "engineering_assistant_investigation_start",
                        "arguments": {
                            "project_root": str(project),
                            "run_id": state.run_id,
                            "investigation_id": "mcp-investigation",
                        },
                    },
                }
            )["result"]
            self.assertFalse(started["isError"])
            contract = investigation_evidence_contract(
                host_store.load(state.run_id, "mcp-investigation")
            )
            observed = project / "official-contract.txt"
            observed.write_text("observed official contract\n", encoding="utf-8")
            evidence_store.save(
                state.run_id,
                EvidenceRef(
                    id="mcp-investigation-evidence",
                    kind="source",
                    uri=str(observed),
                    producer="mcp-test-host",
                    observed_at=datetime.now(timezone.utc).isoformat(),
                    trust_level="observed",
                    scope="official investigation evidence",
                    scope_tags=[
                        *contract["required_scope_tags"],
                        "investigation-source:official_docs",
                    ],
                    subject_digest=contract["subject_digest"],
                    contract_refs=contract["required_contract_refs"],
                    attestation="mcp-test-receipt",
                ),
            )
            finished = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 63,
                    "method": "tools/call",
                    "params": {
                        "name": "engineering_assistant_investigation_finish",
                        "arguments": {
                            "project_root": str(project),
                            "run_id": state.run_id,
                            "investigation_id": "mcp-investigation",
                            "outcome": "completed",
                            "evidence_refs": ["mcp-investigation-evidence"],
                        },
                    },
                }
            )["result"]

            self.assertFalse(finished["isError"])
            self.assertEqual(
                "completed",
                finished["structuredContent"]["record"]["request"]["status"],
            )

    def test_unknown_method_is_protocol_error(self) -> None:
        response = self.request("unknown/method")
        self.assertEqual(-32601, response["error"]["code"])


if __name__ == "__main__":
    unittest.main()
