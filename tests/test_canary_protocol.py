from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant import canary_protocol  # noqa: E402
from engineering_assistant.canary_protocol import audit_canary_protocol  # noqa: E402
from engineering_assistant.cli import build_parser, command_canary_audit  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


def digest(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def fixed_digest(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def bytes_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class CanaryProtocolAuditTests(unittest.TestCase):
    def test_arm_prompt_digest_is_required_by_the_protocol_schema(self) -> None:
        schema = json.loads(
            (ROOT / "evals/canary/experiment-protocol.schema.json").read_text()
        )
        arm_schema = schema["properties"]["arms"]["items"]
        self.assertIn("prompt_digest", arm_schema["required"])
        self.assertEqual(
            {"$ref": "#/$defs/digest"},
            arm_schema["properties"]["prompt_digest"],
        )

    def test_protocol_declares_a_machine_auditable_delegation_ablation(self) -> None:
        schema = json.loads(
            (ROOT / "evals/canary/experiment-protocol.schema.json").read_text()
        )
        self.assertEqual(
            ["routing_ablation", "delegation_ablation"],
            schema["properties"]["experiment_kind"]["enum"],
        )
        arm_ids = set(schema["properties"]["arms"]["items"]["properties"]["arm_id"]["enum"])
        self.assertTrue(
            {
                "minimum_matrix_inline",
                "minimum_matrix_risk_delegation",
                "full_local_control",
            }.issubset(arm_ids)
        )
        workload_schema = schema["properties"]["workloads"]["items"]
        self.assertIn("deliverable_capture", workload_schema["required"])
        self.assertEqual(
            {"final_response", "workspace_patch", "workspace_tree"},
            set(schema["$defs"]["deliverable_capture"]["properties"]["capture_kind"]["enum"]),
        )

    def test_run_prompt_digest_is_required_by_the_run_record_schema(self) -> None:
        schema = json.loads(
            (ROOT / "evals/canary/run-record.schema.json").read_text()
        )
        local_contract = next(
            item["then"]
            for item in schema["allOf"]
            if item["if"]["properties"]["evidence_status"].get("const")
            == "local_structural"
        )
        self.assertIn("prompt_digest", local_contract["required"])
        self.assertEqual(
            {"$ref": "#/$defs/digest"},
            schema["properties"]["prompt_digest"],
        )

    def test_local_run_schema_requires_execution_and_prompt_provenance(self) -> None:
        schema = json.loads(
            (ROOT / "evals/canary/run-record.schema.json").read_text()
        )
        local_contract = next(
            item["then"]
            for item in schema["allOf"]
            if item["if"]["properties"]["evidence_status"].get("const")
            == "local_structural"
        )
        self.assertIn("process_exit_code", local_contract["required"])
        self.assertIn("prompt_artifact", local_contract["required"])
        self.assertEqual(
            ["not_exposed", "captured"],
            schema["properties"]["treatment_observation"]["properties"][
                "read_path_capture_status"
            ]["enum"],
        )

    def test_current_local_run_requires_attempt_outcome_binding(self) -> None:
        schema = json.loads(
            (ROOT / "evals/canary/run-record.schema.json").read_text()
        )
        local_contract = next(
            item["then"]
            for item in schema["allOf"]
            if item["if"]["properties"]["evidence_status"].get("const")
            == "local_structural"
        )
        self.assertIn("outcome_artifact", local_contract["required"])
        self.assertEqual(
            {"$ref": "#/$defs/artifact_ref"},
            schema["properties"]["outcome_artifact"],
        )
        self.assertTrue((ROOT / "evals/canary/attempt-outcome.schema.json").is_file())

    def test_shared_evidence_kind_is_a_closed_machine_contract(self) -> None:
        schema = json.loads(
            (ROOT / "evals/canary/run-record.schema.json").read_text()
        )
        self.assertEqual(
            {
                "fixed_workload_input", "fixed_diff", "adapter_contract",
                "security_regression_fixture", "quality_rubric",
                "fixed_environment_snapshot",
            },
            set(schema["$defs"]["shareable_evidence_kind"]["enum"]),
        )

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.evidence_root = Path(temporary.name)
        self.plugin_root = self.evidence_root / "plugin"
        self.plugin_skill_digests = {}
        for skill_id in ("engineering-assistant", "tdd", "code-review"):
            path = self.plugin_root / "skills" / skill_id / "SKILL.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = f"---\nname: {skill_id}\ndescription: test\n---\n# {skill_id}\n"
            path.write_text(payload, encoding="utf-8")
            self.plugin_skill_digests[skill_id] = bytes_digest(payload.encode())
        package_layout = {
            ".codex-plugin/plugin.json": b"{}\n",
            ".mcp.json": b"{}\n",
            "hooks/hooks.json": b"{}\n",
            "hooks/feedback_capture.py": b"#!/usr/bin/env python3\n",
            "engineering-assistant/runtime/engine.py": b"RUNTIME = True\n",
        }
        for relative, payload in package_layout.items():
            path = self.plugin_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        payload_files = {
            path.relative_to(self.plugin_root).as_posix(): bytes_digest(path.read_bytes())
            for path in sorted(self.plugin_root.rglob("*"))
            if path.is_file()
        }
        package_payload_digest = bytes_digest(
            "\n".join(
                f"{path}:{digest}" for path, digest in payload_files.items()
            ).encode()
        )
        package_manifest = {
            "build_format_version": "1.0",
            "status": "built",
            "platform": "codex",
            "canonical_version": "2.0.0.0-rc.1",
            "skill_versions": {
                skill_id: "2.0.0.0-rc.1" for skill_id in self.plugin_skill_digests
            },
            "skill_count": len(self.plugin_skill_digests),
            "flow_count": 0,
            "pack_count": 0,
            "policy_count": 0,
            "provider_count": 0,
            "source_count": 0,
            "payload_digest": package_payload_digest,
            "payload_files": payload_files,
        }
        package_manifest_raw = (
            json.dumps(package_manifest, indent=2, sort_keys=True) + "\n"
        ).encode()
        (self.plugin_root / "package-manifest.json").write_bytes(package_manifest_raw)
        self.package_manifest_artifact = {
            "ref": "package-manifest.json",
            "digest": bytes_digest(package_manifest_raw),
        }
        self.workloads = []
        for workload_id in ("w1", "w2"):
            payload = f"{workload_id} frozen workload input\n".encode()
            ref = f"fixed/{workload_id}.input"
            (self.evidence_root / ref).parent.mkdir(parents=True, exist_ok=True)
            (self.evidence_root / ref).write_bytes(payload)
            artifact = {"ref": ref, "digest": bytes_digest(payload)}
            self.workloads.append(
                {
                    "workload_id": workload_id,
                    "workload_digest": artifact["digest"],
                    "input_artifact": artifact,
                    "deliverable_capture": {"capture_kind": "final_response"},
                }
            )
        environment_payload = b"frozen environment snapshot\n"
        rubric_payload = b"frozen independent quality rubric\n"
        (self.evidence_root / "fixed/environment.json").write_bytes(environment_payload)
        (self.evidence_root / "fixed/quality-rubric.md").write_bytes(rubric_payload)
        self.environment_artifact = {
            "ref": "fixed/environment.json",
            "digest": bytes_digest(environment_payload),
        }
        self.quality_rubric_artifact = {
            "ref": "fixed/quality-rubric.md",
            "digest": bytes_digest(rubric_payload),
        }
        self.protocol = {
            "schema_version": "1.0",
            "experiment_kind": "routing_ablation",
            "experiment_id": "exp-1",
            "product_repository": "example/product",
            "git_ref": "abc123",
            "minimum_repeats": 2,
            "execution_config_digest": fixed_digest("execution"),
            "environment_digest": self.environment_artifact["digest"],
            "environment_artifact": self.environment_artifact,
            "quality_rubric_digest": self.quality_rubric_artifact["digest"],
            "quality_rubric_artifact": self.quality_rubric_artifact,
            "order_policy": "interleaved_blocks",
            "randomization_seed_digest": fixed_digest("seed"),
            "required_gate_ids": ["tests", "security"],
            "gate_specs": [
                {"gate_id": "tests", "argv": ["python3", "-m", "unittest"], "cwd": "."},
                {"gate_id": "security", "argv": ["python3", "security.py"], "cwd": "."},
            ],
            "workloads": self.workloads,
            "arms": [
                {
                    "arm_id": "route_only",
                    "prompt_digest": fixed_digest("route-prompt"),
                    "treatment_digest": fixed_digest("route"),
                    "conformance": {
                        "minimum_route_calls": 1,
                        "maximum_route_calls": 1,
                        "required_skill_ids": [],
                        "allowed_skill_ids": [],
                        "maximum_active_runtime_calls": 0,
                        "maximum_other_engineering_assistant_calls": 0,
                        "delegation_policy": "forbidden",
                        "allowed_read_roots": ["frontend"],
                        "forbid_recursive_discovery": True,
                    },
                },
                {
                    "arm_id": "minimum_skills",
                    "prompt_digest": fixed_digest("minimum-prompt"),
                    "treatment_digest": fixed_digest("minimum"),
                    "conformance": {
                        "minimum_route_calls": 1,
                        "maximum_route_calls": 1,
                        "required_skill_ids": ["tdd", "code-review"],
                        "allowed_skill_ids": ["tdd", "code-review"],
                        "maximum_active_runtime_calls": 0,
                        "maximum_other_engineering_assistant_calls": 0,
                        "delegation_policy": "forbidden",
                        "allowed_read_roots": ["frontend"],
                        "forbid_recursive_discovery": True,
                    },
                },
                {
                    "arm_id": "full_local",
                    "prompt_digest": fixed_digest("full-prompt"),
                    "treatment_digest": fixed_digest("full"),
                    "conformance": {
                        "minimum_route_calls": 1,
                        "maximum_route_calls": 1,
                        "required_skill_ids": ["engineering-assistant", "tdd", "code-review"],
                        "allowed_skill_ids": ["engineering-assistant", "tdd", "code-review"],
                        "maximum_active_runtime_calls": 0,
                        "maximum_other_engineering_assistant_calls": 0,
                        "delegation_policy": "required",
                        "allowed_read_roots": ["frontend"],
                        "forbid_recursive_discovery": True,
                    },
                },
            ],
        }
        self.protocol["execution_config"] = {
            "model": "gpt-test",
            "reasoning_effort": "high",
            "sandbox_mode": "workspace-write",
            "approval_policy": "never",
            "network_policy": "disabled",
            "plugin_payload_digest": package_payload_digest,
            "package_manifest_artifact": self.package_manifest_artifact,
            "plugin_root": str(self.plugin_root),
            "plugin_skill_digests": self.plugin_skill_digests,
            "prompt_digest": fixed_digest("prompt"),
            "cli_argv": ["codex", "exec"],
        }
        self.protocol["execution_config_digest"] = digest(self.protocol["execution_config"])
        for arm in self.protocol["arms"]:
            arm["treatment_digest"] = digest(
                {
                    "arm_id": arm["arm_id"],
                    "prompt_digest": arm["prompt_digest"],
                    "conformance": arm["conformance"],
                }
            )
        self.protocol["run_plan"] = [
            {
                "run_id": f"{workload['workload_id']}-{arm['arm_id']}-{repeat}",
                "workload_id": workload["workload_id"],
                "arm_id": arm["arm_id"],
                "repeat_index": repeat,
                "planned_order": order,
                "plan_role": "primary",
            }
            for order, (workload, arm, repeat) in enumerate(
                (
                    (workload, arm, repeat)
                    for workload in self.workloads
                    for repeat in (1, 2)
                    for arm in self.protocol["arms"]
                ),
                1,
            )
        ]
        self.protocol_digest = digest(self.protocol)

    def record(
        self,
        workload: dict,
        arm: dict,
        repeat_index: int,
        *,
        billing_status: str = "not_collected",
        run_id_override: str | None = None,
        risk_hypotheses: tuple[str, ...] = (),
    ) -> dict:
        skills = list(arm["conformance"]["required_skill_ids"])
        run_id = run_id_override or f"{workload['workload_id']}-{arm['arm_id']}-{repeat_index}"
        artifact_dir = self.evidence_root / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        opaque_label = "opaque-" + hashlib.sha256(run_id.encode()).hexdigest()[:24]
        deliverable_ref = f"{run_id}/deliverable.json"
        deliverable_payload = json.dumps(
            {"delivery": f"verified asset for {opaque_label}"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        (self.evidence_root / deliverable_ref).write_bytes(deliverable_payload)
        platform_ref = f"{run_id}/platform.jsonl"
        platform_payload = (
            "\n".join(
                json.dumps(event)
                for event in [
                {"type": "thread.started", "thread_id": run_id + "-root"},
                {
                    "type": "item.completed",
                    "run_id": run_id,
                    "item": {
                        "id": "route-call-1",
                        "type": "mcp_tool_call",
                        "server": "engineering-assistant",
                        "tool": "engineering_assistant_route",
                    },
                },
                *(
                    [
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "command_execution",
                                "command": "; ".join(
                                    f"sed -n '1,260p' {self.plugin_root}/skills/{skill}/SKILL.md"
                                    for skill in skills
                                ),
                                "aggregated_output": "".join(
                                    (
                                        self.plugin_root
                                        / "skills"
                                        / skill
                                        / "SKILL.md"
                                    ).read_text()
                                    for skill in skills
                                ),
                                "exit_code": 0,
                                "status": "completed",
                            },
                        }
                    ]
                    if skills
                    else []
                ),
                {
                    "type": "item.completed",
                    "run_id": run_id,
                    "item": {
                        "type": "agent_message",
                        "content": deliverable_payload.decode("utf-8"),
                    },
                },
                {
                    "type": "turn.completed",
                    "run_id": run_id,
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 40,
                        "output_tokens": 20,
                    },
                },
                ]
            )
            + "\n"
        ).encode()
        (self.evidence_root / platform_ref).write_bytes(platform_payload)
        prompt_ref = f"prompts/{arm['arm_id']}.txt"
        prompt_payload = arm["arm_id"].replace("_only", "").replace(
            "minimum_skills", "minimum"
        ).replace("full_local", "full") + "-prompt"
        (self.evidence_root / "prompts").mkdir(exist_ok=True)
        (self.evidence_root / prompt_ref).write_text(prompt_payload)
        reviewer_ref = f"{run_id}/reviewer-1.jsonl"
        reviewer_payload = (
            "\n".join(
                json.dumps(event)
                for event in [
                {
                    "type": "thread.started",
                    "thread_id": run_id + "-reviewer-1",
                },
                {
                    "type": "turn.completed",
                    "run_id": run_id,
                    "usage": {
                        "input_tokens": 30,
                        "cached_input_tokens": 10,
                        "output_tokens": 5,
                    },
                },
                ]
            )
            + "\n"
        ).encode()
        (self.evidence_root / reviewer_ref).write_bytes(reviewer_payload)
        reviewer_native_ref = f"{run_id}/reviewer-1.native.jsonl"
        reviewer_native_payload = (
            "\n".join(
                json.dumps(event)
                for event in [
                {
                    "type": "session_meta",
                    "payload": {
                        "id": run_id + "-reviewer-1",
                        "parent_thread_id": run_id + "-root",
                    },
                },
                {
                    "type": "session_meta",
                    "payload": {
                        "id": run_id + "-root",
                        "parent_thread_id": None,
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 30,
                                "cached_input_tokens": 10,
                                "output_tokens": 5,
                            }
                        },
                    },
                },
                ]
            )
            + "\n"
        ).encode()
        (self.evidence_root / reviewer_native_ref).write_bytes(reviewer_native_payload)
        root_only_ref = f"{run_id}/root-notes.txt"
        root_only_payload = (run_id + " root notes\n").encode()
        (self.evidence_root / root_only_ref).write_bytes(root_only_payload)
        child_only_ref = f"{run_id}/child-findings.txt"
        child_only_payload = (run_id + " child findings\n").encode()
        (self.evidence_root / child_only_ref).write_bytes(child_only_payload)
        shared_evidence = {
            "ref": workload["input_artifact"]["ref"],
            "digest": workload["input_artifact"]["digest"],
            "evidence_kind": "fixed_workload_input",
        }
        fixed_evidence = [
            shared_evidence,
            {
                **self.protocol["quality_rubric_artifact"],
                "evidence_kind": "quality_rubric",
            },
            {
                **self.protocol["environment_artifact"],
                "evidence_kind": "fixed_environment_snapshot",
            },
        ]
        root_evidence_refs = [
            *fixed_evidence,
            {
                "ref": root_only_ref,
                "digest": bytes_digest(root_only_payload),
                "evidence_kind": "root_note",
            },
        ]
        child_evidence_refs = [
            *fixed_evidence,
            {
                "ref": child_only_ref,
                "digest": bytes_digest(child_only_payload),
                "evidence_kind": "review_finding",
            },
        ]
        for gate in self.protocol["gate_specs"]:
            (artifact_dir / f"{gate['gate_id']}.stdout.log").write_bytes(
                (run_id + gate["gate_id"] + " stdout\n").encode()
            )
            (artifact_dir / f"{gate['gate_id']}.stderr.log").write_bytes(
                (run_id + gate["gate_id"] + " stderr\n").encode()
            )
        threads = [
            {
                "thread_id": run_id + "-root",
                "parent_thread_id": None,
                "role": "root",
                "transcript_ref": platform_ref,
                "transcript_digest": bytes_digest(platform_payload),
                "evidence_refs": root_evidence_refs,
                "complete": True,
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 20,
            }
        ]
        if arm["conformance"]["delegation_policy"] == "required" or risk_hypotheses:
            threads.append({
                "thread_id": run_id + "-reviewer-1",
                "parent_thread_id": run_id + "-root",
                "role": "reviewer",
                "transcript_ref": reviewer_ref,
                "transcript_digest": bytes_digest(reviewer_payload),
                "native_transcript_ref": reviewer_native_ref,
                "native_transcript_digest": bytes_digest(reviewer_native_payload),
                "evidence_refs": child_evidence_refs,
                "complete": True,
                "input_tokens": 30,
                "cached_input_tokens": 10,
                "output_tokens": 5,
            })
        planned = next(
            (item for item in self.protocol["run_plan"] if item["run_id"] == run_id),
            {"planned_order": 4096},
        )
        delegation_count = len(threads) - 1
        unresolved_hypothesis_ids = list(risk_hypotheses)
        hypothesis_ref = f"{run_id}/hypotheses.json"
        hypothesis_payload = json.dumps(
            {
                "schema_version": "1.0",
                "run_id": run_id,
                "root_thread_id": run_id + "-root",
                "unresolved_hypothesis_ids": unresolved_hypothesis_ids,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        (self.evidence_root / hypothesis_ref).write_bytes(hypothesis_payload)
        root_user_messages = [prompt_payload, hypothesis_payload.decode("utf-8")]
        platform_payload = b"".join(
            (
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "user_message", "content": message},
                    }
                ).encode()
                + b"\n"
            )
            for message in root_user_messages
        ) + platform_payload
        (self.evidence_root / platform_ref).write_bytes(platform_payload)
        threads[0]["transcript_digest"] = bytes_digest(platform_payload)
        delegation_batches = []
        if delegation_count:
            delegation_prompt_ref = f"{run_id}/reviewer-1.prompt.json"
            delegation_prompt_payload = json.dumps(
                {
                    "schema_version": "1.0",
                    "run_id": run_id,
                    "child_thread_id": run_id + "-reviewer-1",
                    "delegation_scope": (
                        "targeted_hypotheses" if risk_hypotheses else "full_review"
                    ),
                    "hypothesis_ids": list(risk_hypotheses),
                    "evidence_refs": child_evidence_refs,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            (self.evidence_root / delegation_prompt_ref).write_bytes(
                delegation_prompt_payload
            )
            reviewer_native_payload = (
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": delegation_prompt_payload.decode("utf-8"),
                                }
                            ],
                        },
                    }
                ).encode()
                + b"\n"
                + reviewer_native_payload
            )
            (self.evidence_root / reviewer_native_ref).write_bytes(
                reviewer_native_payload
            )
            threads[1]["native_transcript_digest"] = bytes_digest(
                reviewer_native_payload
            )
            delegation_batches.append(
                {
                    "child_thread_id": run_id + "-reviewer-1",
                    "prompt_artifact": {
                        "ref": delegation_prompt_ref,
                        "digest": bytes_digest(delegation_prompt_payload),
                    },
                }
            )
        record = {
            "schema_version": "2.0",
            "evidence_status": "local_structural",
            "run_id": run_id,
            "experiment_id": self.protocol["experiment_id"],
            "protocol_digest": self.protocol_digest,
            "workload_id": workload["workload_id"],
            "workload_digest": workload["workload_digest"],
            "arm_id": arm["arm_id"],
            "repeat_index": repeat_index,
            "actual_start_order": planned["planned_order"],
            "started_at": "2026-07-15T00:00:00Z",
            "finished_at": "2026-07-15T00:00:01Z",
            "process_exit_code": 0,
            "product_repository": self.protocol["product_repository"],
            "git_ref": self.protocol["git_ref"],
            "treatment_digest": arm["treatment_digest"],
            "prompt_digest": arm["prompt_digest"],
            "prompt_artifact": {
                "ref": prompt_ref,
                "digest": bytes_digest(prompt_payload.encode()),
            },
            "execution_config_digest": self.protocol["execution_config_digest"],
            "environment_digest": self.protocol["environment_digest"],
            "quality_rubric_digest": self.protocol["quality_rubric_digest"],
            "root_thread_id": run_id + "-root",
            "platform_transcript": {
                "ref": platform_ref,
                "digest": bytes_digest(platform_payload),
                "complete": True,
            },
            "gate_receipts": [
                {
                    "gate_id": gate["gate_id"],
                    "argv": gate["argv"],
                    "cwd": gate["cwd"],
                    "command_digest": digest({"argv": gate["argv"], "cwd": gate["cwd"]}),
                    "started_at": "2026-07-15T01:00:00Z",
                    "finished_at": "2026-07-15T01:00:01Z",
                    "wall_time_milliseconds": 1000,
                    "exit_code": 0,
                    "timed_out": False,
                    "status": "passed",
                    "stdout_ref": f"{run_id}/{gate['gate_id']}.stdout.log",
                    "stdout_digest": bytes_digest(
                        (run_id + gate["gate_id"] + " stdout\n").encode()
                    ),
                    "stderr_ref": f"{run_id}/{gate['gate_id']}.stderr.log",
                    "stderr_digest": bytes_digest(
                        (run_id + gate["gate_id"] + " stderr\n").encode()
                    ),
                }
                for gate in self.protocol["gate_specs"]
            ],
            "usage": {
                "aggregation_semantics": "per_thread_exclusive",
                "coverage": "root_and_descendants",
                "complete": True,
                "delegation_event_count": delegation_count,
                "threads": threads,
                "aggregate": {
                    "input_tokens": sum(thread["input_tokens"] for thread in threads),
                    "cached_input_tokens": sum(thread["cached_input_tokens"] for thread in threads),
                    "output_tokens": sum(thread["output_tokens"] for thread in threads),
                },
                "wall_time_milliseconds": 1000,
            },
            "treatment_observation": {
                "route_call_count": 1,
                "loaded_skill_ids": skills,
                "active_runtime_call_count": 0,
                "other_engineering_assistant_call_count": 0,
                "delegation_event_count": delegation_count,
                "recursive_discovery_count": 0,
                "read_path_capture_status": "captured",
                "observed_read_paths": ["frontend/src/App.tsx"],
                "evidence_binding_version": "2.0",
                "hypothesis_artifact": {
                    "ref": hypothesis_ref,
                    "digest": bytes_digest(hypothesis_payload),
                },
                "unresolved_hypothesis_ids": unresolved_hypothesis_ids,
                "delegation_hypothesis_batches": delegation_batches,
                "duplicate_full_review_delegations": 0,
                "root_child_shared_evidence": (
                    [
                        {
                            "digest": evidence["digest"],
                            "evidence_kind": evidence["evidence_kind"],
                        }
                        for evidence in fixed_evidence
                    ]
                    if delegation_count
                    else []
                ),
            },
            "assurance": "local_unattested",
            "billing": (
                {
                    "status": "collected",
                    "source": "test-billing-receipt",
                    "cost_usd_micros": 100,
                }
                if billing_status == "collected"
                else {"status": billing_status}
            ),
        }
        attempt_fact = {
            "schema_version": "1.0",
            "run_id": run_id,
            "protocol_digest": self.protocol_digest,
            "workload_id": workload["workload_id"],
            "workload_digest": workload["workload_digest"],
            "arm_id": arm["arm_id"],
            "treatment_digest": arm["treatment_digest"],
            "attempt_status": "completed",
            "process_exit_code": 0,
            "gate_outcomes": [
                {
                    "gate_id": item["gate_id"],
                    "status": item["status"],
                    "exit_code": item["exit_code"],
                    "timed_out": item["timed_out"],
                }
                for item in record["gate_receipts"]
            ],
            "usage": {
                "status": "collected",
                **record["usage"]["aggregate"],
                "wall_time_milliseconds": record["usage"]["wall_time_milliseconds"],
            },
            "cost": record["billing"],
            "deliverable_capture": {
                "capture_kind": workload["deliverable_capture"]["capture_kind"],
                "artifact": {
                    "ref": deliverable_ref,
                    "digest": bytes_digest(deliverable_payload),
                },
            },
            "rework": {"status": "collected", "count": 0},
            "safety": {"status": "collected", "count": 0},
            "quality": {"status": "collected", "count": 0},
            "quality_blocker_count": {"status": "collected", "count": 0},
            "quality_major_count": {"status": "collected", "count": 0},
            "document_noise": {"status": "collected", "count": 0},
            "human_intervention_count": {"status": "collected", "count": 0},
            "human_rework_minutes": {"status": "collected", "count": 0},
            "applicable_matrix_cells": {"status": "collected", "count": 1},
            "closed_matrix_cells": {"status": "collected", "count": 1},
            "production_contract_failures": {"status": "collected", "count": 0},
        }
        blind_root = self.evidence_root / "blind" / opaque_label
        blind_root.mkdir(parents=True, exist_ok=True)
        asset_ref = f"blind/{opaque_label}/asset.json"
        asset_payload = deliverable_payload
        (self.evidence_root / asset_ref).write_bytes(asset_payload)
        assignment_transcript_ref = f"blind/{opaque_label}/assignment.jsonl"
        assignment_session_id = "assign-" + opaque_label.removeprefix("opaque-")
        assignment_transcript_payload = (
            json.dumps({
                "type": "session_meta", "at": "2026-07-15T00:01:00Z",
                "payload": {"id": assignment_session_id, "parent_thread_id": None},
            }) + "\n"
        ).encode()
        (self.evidence_root / assignment_transcript_ref).write_bytes(
            assignment_transcript_payload
        )
        assignment = {
            "schema_version": "1.0",
            "experiment_id": self.protocol["experiment_id"],
            "opaque_label": opaque_label,
            "asset_artifact": {"ref": asset_ref, "digest": bytes_digest(asset_payload)},
            "rubric_artifact": self.protocol["quality_rubric_artifact"],
            "assignment_session_id": assignment_session_id,
            "assigned_at": "2026-07-15T00:01:00Z",
            "assignment_transcript_artifact": {
                "ref": assignment_transcript_ref,
                "digest": bytes_digest(assignment_transcript_payload),
            },
        }
        assignment_ref = f"blind/{opaque_label}/assignment.json"
        assignment_payload = json.dumps(
            assignment, sort_keys=True, separators=(",", ":")
        ).encode()
        (self.evidence_root / assignment_ref).write_bytes(assignment_payload)
        evaluator_session_id = "evaluate-" + opaque_label.removeprefix("opaque-")
        evaluator_transcript_ref = f"blind/{opaque_label}/evaluator.jsonl"
        reviewer_prompt = (
            f"Review opaque label {opaque_label}.\n"
            f"Access asset digest {bytes_digest(asset_payload)}.\n"
            "Apply rubric digest "
            f"{self.protocol['quality_rubric_artifact']['digest']}."
        )
        evaluator_transcript_payload = (
            json.dumps({
                "type": "session_meta", "at": "2026-07-15T00:01:30Z",
                "payload": {"id": evaluator_session_id, "parent_thread_id": None},
            }) + "\n" + json.dumps({
                "type": "response_item", "at": "2026-07-15T00:01:31Z",
                "payload": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": reviewer_prompt}],
                },
            }) + "\n"
        ).encode()
        (self.evidence_root / evaluator_transcript_ref).write_bytes(
            evaluator_transcript_payload
        )
        score = {
            "schema_version": "1.0",
            "experiment_id": self.protocol["experiment_id"],
            "opaque_label": opaque_label,
            "asset_digest": bytes_digest(asset_payload),
            "rubric_digest": self.protocol["quality_rubric_artifact"]["digest"],
            "evaluator_session_id": evaluator_session_id,
            "quality_score": 92.5,
            "blind_blocker_count": 0,
            "blind_major_count": 0,
            "frozen_at": "2026-07-15T00:02:00Z",
            "evaluator_transcript_artifact": {
                "ref": evaluator_transcript_ref,
                "digest": bytes_digest(evaluator_transcript_payload),
            },
        }
        score_ref = f"blind/{opaque_label}/score.json"
        score_payload = json.dumps(score, sort_keys=True, separators=(",", ":")).encode()
        (self.evidence_root / score_ref).write_bytes(score_payload)
        reveal = {
            "schema_version": "1.0",
            "experiment_id": self.protocol["experiment_id"],
            "opaque_label": opaque_label,
            "run_id": run_id,
            "arm_id": arm["arm_id"],
            "treatment_digest": arm["treatment_digest"],
            "outcome_fact_digest": digest(attempt_fact),
            "assignment_raw_digest": bytes_digest(assignment_payload),
            "assignment_canonical_digest": digest(assignment),
            "score_raw_digest": bytes_digest(score_payload),
            "score_canonical_digest": digest(score),
            "reveal_session_id": "reveal-" + opaque_label.removeprefix("opaque-"),
            "revealed_at": "2026-07-15T00:03:00Z",
        }
        reveal_ref = f"blind/{opaque_label}/reveal.json"
        reveal_payload = json.dumps(
            reveal, sort_keys=True, separators=(",", ":")
        ).encode()
        (self.evidence_root / reveal_ref).write_bytes(reveal_payload)
        blind_review = {
            "assignment_artifact": {
                "ref": assignment_ref, "digest": bytes_digest(assignment_payload),
            },
            "score_artifact": {"ref": score_ref, "digest": bytes_digest(score_payload)},
            "reveal_artifact": {"ref": reveal_ref, "digest": bytes_digest(reveal_payload)},
        }
        attempt_fact["blind_review"] = blind_review
        record["blind_review"] = blind_review
        receipt_ref = f"{run_id}/attempt-fact.receipt.json"
        receipt_payload = json.dumps(
            {
                "schema_version": "1.0",
                "receipt_kind": "attempt_fact",
                "attempt_fact": attempt_fact,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        (self.evidence_root / receipt_ref).write_bytes(receipt_payload)
        outcome = {
            **attempt_fact,
            "raw_receipts": [{
                "receipt_kind": "attempt_fact",
                "ref": receipt_ref,
                "digest": bytes_digest(receipt_payload),
            }],
        }
        outcome_ref = f"{run_id}/attempt-outcome.json"
        outcome_payload = json.dumps(
            outcome, sort_keys=True, separators=(",", ":")
        ).encode()
        (self.evidence_root / outcome_ref).write_bytes(outcome_payload)
        record["outcome_artifact"] = {
            "ref": outcome_ref,
            "digest": bytes_digest(outcome_payload),
        }
        return record

    def complete_records(self) -> list[dict]:
        return [
            self.record(workload, arm, repeat)
            for workload in self.workloads
            for arm in self.protocol["arms"]
            for repeat in (1, 2)
        ]

    def manifest(self, records: list[dict]) -> dict:
        return {
            "schema_version": "2.0",
            "experiment_id": "exp-1",
            "protocol_digest": self.protocol_digest,
            "entries": [
                {
                    "run_id": record["run_id"],
                    "disposition": "included",
                    "reason_code": "protocol_conformant",
                    "run_record_digest": digest(record),
                    "decided_at": "2026-07-15T00:04:00Z",
                    **(
                        {"blind_review": record["blind_review"]}
                        if "blind_review" in record else {}
                    ),
                }
                for record in records
            ],
        }

    def rewrite_outcome(self, record: dict) -> None:
        """Keep the test receipt authoritative after changing attempt facts."""

        outcome_path = self.evidence_root / record["outcome_artifact"]["ref"]
        outcome = json.loads(outcome_path.read_text())
        outcome["process_exit_code"] = record["process_exit_code"]
        outcome["attempt_status"] = (
            "completed"
            if record["process_exit_code"] == 0
            and all(
                item["status"] == "passed"
                and item["exit_code"] == 0
                and not item["timed_out"]
                for item in record["gate_receipts"]
            )
            else "failed"
        )
        outcome["gate_outcomes"] = [
            {
                "gate_id": item["gate_id"],
                "status": item["status"],
                "exit_code": item["exit_code"],
                "timed_out": item["timed_out"],
            }
            for item in record["gate_receipts"]
        ]
        outcome["cost"] = record["billing"]
        receipt_ref = outcome["raw_receipts"][0]["ref"]
        receipt_payload = json.dumps(
            {
                "schema_version": "1.0",
                "receipt_kind": "attempt_fact",
                "attempt_fact": {
                    key: value for key, value in outcome.items() if key != "raw_receipts"
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        (self.evidence_root / receipt_ref).write_bytes(receipt_payload)
        outcome["raw_receipts"][0]["digest"] = bytes_digest(receipt_payload)
        outcome_payload = json.dumps(
            outcome, sort_keys=True, separators=(",", ":")
        ).encode()
        outcome_path.write_bytes(outcome_payload)
        record["outcome_artifact"]["digest"] = bytes_digest(outcome_payload)

    def rewrite_blind_chain(
        self,
        record: dict,
        *,
        mutate_assignment=None,
        mutate_score=None,
        mutate_reveal=None,
    ) -> None:
        chain = record["blind_review"]
        assignment_path = self.evidence_root / chain["assignment_artifact"]["ref"]
        score_path = self.evidence_root / chain["score_artifact"]["ref"]
        reveal_path = self.evidence_root / chain["reveal_artifact"]["ref"]
        assignment = json.loads(assignment_path.read_text())
        score = json.loads(score_path.read_text())
        reveal = json.loads(reveal_path.read_text())
        if mutate_assignment:
            mutate_assignment(assignment)
        if mutate_score:
            mutate_score(score)
        assignment_payload = json.dumps(
            assignment, sort_keys=True, separators=(",", ":")
        ).encode()
        score_payload = json.dumps(score, sort_keys=True, separators=(",", ":")).encode()
        assignment_path.write_bytes(assignment_payload)
        score_path.write_bytes(score_payload)
        reveal.update({
            "assignment_raw_digest": bytes_digest(assignment_payload),
            "assignment_canonical_digest": digest(assignment),
            "score_raw_digest": bytes_digest(score_payload),
            "score_canonical_digest": digest(score),
        })
        if mutate_reveal:
            mutate_reveal(reveal)
        reveal_payload = json.dumps(
            reveal, sort_keys=True, separators=(",", ":")
        ).encode()
        reveal_path.write_bytes(reveal_payload)
        chain = {
            "assignment_artifact": {
                "ref": chain["assignment_artifact"]["ref"],
                "digest": bytes_digest(assignment_payload),
            },
            "score_artifact": {
                "ref": chain["score_artifact"]["ref"],
                "digest": bytes_digest(score_payload),
            },
            "reveal_artifact": {
                "ref": chain["reveal_artifact"]["ref"],
                "digest": bytes_digest(reveal_payload),
            },
        }
        record["blind_review"] = chain
        outcome_path = self.evidence_root / record["outcome_artifact"]["ref"]
        outcome = json.loads(outcome_path.read_text())
        outcome["blind_review"] = chain
        receipt_ref = outcome["raw_receipts"][0]["ref"]
        receipt_payload = json.dumps({
            "schema_version": "1.0", "receipt_kind": "attempt_fact",
            "attempt_fact": {
                key: value for key, value in outcome.items() if key != "raw_receipts"
            },
        }, sort_keys=True, separators=(",", ":")).encode()
        (self.evidence_root / receipt_ref).write_bytes(receipt_payload)
        outcome["raw_receipts"][0]["digest"] = bytes_digest(receipt_payload)
        outcome_payload = json.dumps(
            outcome, sort_keys=True, separators=(",", ":")
        ).encode()
        outcome_path.write_bytes(outcome_payload)
        record["outcome_artifact"]["digest"] = bytes_digest(outcome_payload)

    def add_infrastructure_invalidation(
        self,
        manifest: dict,
        original: dict,
        replacement: dict,
        *,
        reason_code: str = "runner_crash",
        decided_at: str = "2026-07-15T00:02:00Z",
    ) -> dict:
        reviewer_session_id = original["run_id"] + "-invalidation-reviewer"
        reviewer_ref = f"{original['run_id']}/invalidation-reviewer.native.jsonl"
        reviewer_payload = (
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": reviewer_session_id,
                        "parent_thread_id": None,
                    },
                }
            )
            + "\n"
        ).encode()
        (self.evidence_root / reviewer_ref).write_bytes(reviewer_payload)
        diagnostic_ref = f"{original['run_id']}/{reason_code}.diagnostic.log"
        diagnostic_payload = f"independent diagnostic: {reason_code}\n".encode()
        (self.evidence_root / diagnostic_ref).write_bytes(diagnostic_payload)
        invalidation = {
            "schema_version": "1.0",
            "invalidation_kind": "infrastructure",
            "invalidated_run_id": original["run_id"],
            "invalidated_outcome_digest": original["outcome_artifact"]["digest"],
            "reason_code": reason_code,
            "reviewer_session_id": reviewer_session_id,
            "reviewer_session_artifact": {
                "ref": reviewer_ref,
                "digest": bytes_digest(reviewer_payload),
            },
            "executor_session_ids": sorted(
                item["thread_id"] for item in original["usage"]["threads"]
            ),
            "decided_at": decided_at,
            "diagnostic_artifacts": [
                {
                    "diagnostic_kind": reason_code,
                    "ref": diagnostic_ref,
                    "digest": bytes_digest(diagnostic_payload),
                }
            ],
        }
        invalidation_ref = f"{original['run_id']}/infrastructure-invalidation.json"
        invalidation_payload = json.dumps(
            invalidation, sort_keys=True, separators=(",", ":")
        ).encode()
        (self.evidence_root / invalidation_ref).write_bytes(invalidation_payload)
        entry = next(
            item for item in manifest["entries"] if item["run_id"] == original["run_id"]
        )
        entry.update(
            {
                "disposition": "replaced",
                "reason_code": "infrastructure_invalidated",
                "replacement_run_id": replacement["run_id"],
                "decided_at": decided_at,
                "invalidation_artifact": {
                    "ref": invalidation_ref,
                    "digest": bytes_digest(invalidation_payload),
                },
            }
        )
        return invalidation

    def audit(self, records: list[dict], manifest: dict | None = None) -> dict:
        return audit_canary_protocol(
            self.protocol,
            records,
            manifest or self.manifest(records),
            schema_root=ROOT / "evals/canary",
            evidence_root=self.evidence_root,
        )

    def test_skill_content_replay_root_does_not_replace_declared_command_root(self) -> None:
        records = self.complete_records()
        replay_content_root = self.evidence_root / "replay-plugin-content"
        shutil.copytree(self.plugin_root, replay_content_root)
        shutil.rmtree(self.plugin_root)

        report = audit_canary_protocol(
            self.protocol,
            records,
            self.manifest(records),
            schema_root=ROOT / "evals/canary",
            evidence_root=self.evidence_root,
            plugin_content_root=replay_content_root,
        )
        self.assertEqual("local_structural", report["status"], report)

        (replay_content_root / "skills" / "tdd" / "SKILL.md").write_text(
            "---\nname: tdd\ndescription: changed\n---\n",
            encoding="utf-8",
        )
        rejected = audit_canary_protocol(
            self.protocol,
            records,
            self.manifest(records),
            schema_root=ROOT / "evals/canary",
            evidence_root=self.evidence_root,
            plugin_content_root=replay_content_root,
        )
        self.assertEqual("failed", rejected["status"])
        self.assertTrue(
            any("transcript_skill_load_mismatch" in item for item in rejected["failures"]),
            rejected,
        )

    def test_protocol_fixed_evidence_bytes_and_thread_bindings_are_rehashed(self) -> None:
        records = self.complete_records()
        cases = (
            (
                self.workloads[0]["input_artifact"],
                "workload_input_digest_mismatch:w1",
            ),
            (self.protocol["quality_rubric_artifact"], "quality_rubric_artifact_digest_mismatch"),
            (self.protocol["environment_artifact"], "environment_artifact_digest_mismatch"),
        )
        for artifact, expected_failure in cases:
            with self.subTest(expected_failure=expected_failure):
                path = self.evidence_root / artifact["ref"]
                original = path.read_bytes()
                path.write_bytes(original + b"tampered")
                try:
                    report = self.audit(records)
                    self.assertIn(expected_failure, report["failures"])
                finally:
                    path.write_bytes(original)

        record = records[0]
        root = next(
            thread
            for thread in record["usage"]["threads"]
            if thread["parent_thread_id"] is None
        )
        root["evidence_refs"] = [
            item
            for item in root["evidence_refs"]
            if item["evidence_kind"] != "fixed_environment_snapshot"
        ]
        report = self.audit(records)
        self.assertIn(
            f"thread_fixed_evidence_missing:{record['run_id']}:{root['thread_id']}:fixed_environment_snapshot",
            report["failures"],
        )

    def test_declared_plugin_package_payload_is_verified_not_just_skill_files(self) -> None:
        records = self.complete_records()
        runtime = self.plugin_root / "engineering-assistant/runtime/engine.py"
        original = runtime.read_bytes()
        runtime.unlink()
        try:
            missing = self.audit(records)
            self.assertIn("plugin_package_verification_failed", missing["failures"])
        finally:
            runtime.write_bytes(original)

        runtime.write_bytes(b"TAMPERED = True\n")
        tampered = self.audit(records)
        self.assertIn("plugin_package_verification_failed", tampered["failures"])

    def test_three_arms_two_repeats_are_required(self) -> None:
        records = self.complete_records()
        omitted = records.pop()
        report = self.audit(records)
        self.assertEqual("failed", report["status"])
        self.assertIn(
            f"insufficient_repeats:{omitted['workload_id']}:{omitted['arm_id']}",
            report["failures"],
        )

    def test_delegation_ablation_three_arm_contract_is_auditable(self) -> None:
        source_arms = {arm["arm_id"]: arm for arm in self.protocol["arms"]}
        arm_sources = {
            "minimum_matrix_inline": "minimum_skills",
            "minimum_matrix_risk_delegation": "full_local",
            "full_local_control": "full_local",
        }
        arms = []
        for arm_id, source_id in arm_sources.items():
            source = json.loads(json.dumps(source_arms[source_id]))
            source["arm_id"] = arm_id
            if arm_id == "minimum_matrix_risk_delegation":
                source["conformance"]["delegation_policy"] = "allowed"
            prompt_payload = arm_id.replace("_only", "").replace(
                "minimum_skills", "minimum"
            ).replace("full_local", "full") + "-prompt"
            source["prompt_digest"] = fixed_digest(prompt_payload)
            source["treatment_digest"] = digest(
                {
                    "arm_id": arm_id,
                    "prompt_digest": source["prompt_digest"],
                    "conformance": source["conformance"],
                }
            )
            arms.append(source)
        self.protocol["experiment_kind"] = "delegation_ablation"
        self.protocol["arms"] = arms
        self.protocol["run_plan"] = [
            {
                "run_id": f"{workload['workload_id']}-{arm['arm_id']}-{repeat}",
                "workload_id": workload["workload_id"],
                "arm_id": arm["arm_id"],
                "repeat_index": repeat,
                "planned_order": order,
                "plan_role": "primary",
            }
            for order, (workload, arm, repeat) in enumerate(
                (
                    (workload, arm, repeat)
                    for workload in self.workloads
                    for repeat in (1, 2)
                    for arm in arms
                ),
                1,
            )
        ]
        self.protocol_digest = digest(self.protocol)
        records = self.complete_records()

        report = self.audit(records)
        self.assertEqual("local_structural", report["status"])
        self.assertEqual([], report["failures"])
        risk = next(
            record
            for record in records
            if record["arm_id"] == "minimum_matrix_risk_delegation"
        )
        self.assertEqual(0, risk["usage"]["delegation_event_count"])
        risk_index = records.index(risk)
        risk_arm = next(arm for arm in arms if arm["arm_id"] == risk["arm_id"])
        risk_workload = next(
            workload for workload in self.workloads
            if workload["workload_id"] == risk["workload_id"]
        )
        records[risk_index] = self.record(
            risk_workload,
            risk_arm,
            risk["repeat_index"],
            risk_hypotheses=("risk-1",),
        )
        report = self.audit(records)
        self.assertEqual("local_structural", report["status"])
        self.assertEqual([], report["failures"])

        risk = records[risk_index]
        risk["treatment_observation"]["unresolved_hypothesis_ids"] = ["forged"]
        risk["treatment_observation"]["duplicate_full_review_delegations"] = 1
        risk["treatment_observation"]["root_child_shared_evidence"] = []
        report = self.audit(records)
        self.assertIn(
            f"delegation_hypothesis_nonconformant:{risk['run_id']}",
            report["failures"],
        )

    def test_cycle_in_expected_native_session_chain_fails_closed(self) -> None:
        self.assertEqual(
            set(),
            canary_protocol._expected_session_links(
                "a",
                [
                    {"thread_id": "a", "parent_thread_id": "b"},
                    {"thread_id": "b", "parent_thread_id": "a"},
                ],
            ),
        )

    def test_shared_evidence_is_derived_by_content_digest_across_aliases(self) -> None:
        records = self.complete_records()
        record = next(item for item in records if item["arm_id"] == "full_local")
        child = next(
            thread for thread in record["usage"]["threads"]
            if thread["parent_thread_id"] is not None
        )
        shared = child["evidence_refs"][0]
        alias_ref = f"{record['run_id']}/child-fixed-input-alias.txt"
        (self.evidence_root / alias_ref).write_bytes(
            (self.evidence_root / shared["ref"]).read_bytes()
        )
        shared["ref"] = alias_ref

        batch = record["treatment_observation"]["delegation_hypothesis_batches"][0]
        prompt_path = self.evidence_root / batch["prompt_artifact"]["ref"]
        prompt = json.loads(prompt_path.read_text())
        prompt["evidence_refs"][0]["ref"] = alias_ref
        prompt_payload = json.dumps(
            prompt, sort_keys=True, separators=(",", ":")
        ).encode()
        prompt_path.write_bytes(prompt_payload)
        batch["prompt_artifact"]["digest"] = bytes_digest(prompt_payload)

        native_path = self.evidence_root / child["native_transcript_ref"]
        native_events = [json.loads(line) for line in native_path.read_text().splitlines()]
        user_message = next(
            event for event in native_events
            if event.get("type") == "response_item"
            and event.get("payload", {}).get("role") == "user"
        )
        user_message["payload"]["content"][0]["text"] = prompt_payload.decode()
        native_path.write_text(
            "\n".join(json.dumps(event) for event in native_events) + "\n"
        )
        child["native_transcript_digest"] = bytes_digest(native_path.read_bytes())

        report = self.audit(records)
        self.assertEqual("local_structural", report["status"])
        self.assertEqual([], report["failures"])

    def test_hypothesis_and_delegation_prompts_require_transcript_messages(self) -> None:
        records = self.complete_records()
        root_record = records[0]
        hypothesis = root_record["treatment_observation"]["hypothesis_artifact"]
        hypothesis_path = self.evidence_root / hypothesis["ref"]
        hypothesis_payload = hypothesis_path.read_bytes() + b" "
        hypothesis_path.write_bytes(hypothesis_payload)
        hypothesis["digest"] = bytes_digest(hypothesis_payload)

        delegated = next(item for item in records if item["arm_id"] == "full_local")
        batch = delegated["treatment_observation"]["delegation_hypothesis_batches"][0]
        prompt_path = self.evidence_root / batch["prompt_artifact"]["ref"]
        prompt_path.write_bytes(prompt_path.read_bytes() + b" ")
        batch["prompt_artifact"]["digest"] = bytes_digest(prompt_path.read_bytes())

        report = self.audit(records)
        self.assertIn(
            f"hypothesis_artifact_nonconformant:{root_record['run_id']}",
            report["failures"],
        )
        child_id = batch["child_thread_id"]
        self.assertIn(
            f"delegation_prompt_nonconformant:{delegated['run_id']}:{child_id}",
            report["failures"],
        )

    def test_root_prompt_artifact_bytes_must_be_a_platform_user_message(self) -> None:
        records = self.complete_records()
        record = records[0]
        prompt_text = (
            self.evidence_root / record["prompt_artifact"]["ref"]
        ).read_text()
        platform_path = self.evidence_root / record["platform_transcript"]["ref"]
        events = [json.loads(line) for line in platform_path.read_text().splitlines()]
        events = [
            event for event in events
            if not (
                event.get("type") == "item.completed"
                and event.get("item", {}).get("type") == "user_message"
                and event.get("item", {}).get("content") == prompt_text
            )
        ]
        platform_path.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n"
        )
        observed_digest = bytes_digest(platform_path.read_bytes())
        record["platform_transcript"]["digest"] = observed_digest
        root = next(
            thread for thread in record["usage"]["threads"]
            if thread["parent_thread_id"] is None
        )
        root["transcript_digest"] = observed_digest

        report = self.audit(records)
        self.assertIn(
            f"root_prompt_message_missing:{record['run_id']}", report["failures"]
        )

    def test_evidence_budget_does_not_retain_all_payload_bytes(self) -> None:
        reference = "bounded-evidence.bin"
        payload = b"x" * 4096
        (self.evidence_root / reference).write_bytes(payload)
        artifacts = canary_protocol.ArtifactIO(self.evidence_root, ".")
        self.addCleanup(artifacts.close)
        budget = canary_protocol._EvidenceBudget(artifacts)
        self.assertEqual(payload, budget.read_bytes_limited(8192, reference))
        self.assertEqual(payload, budget.read_bytes_limited(8192, reference))
        self.assertEqual(len(payload), budget.total_bytes)
        self.assertFalse(hasattr(budget, "_payloads"))

    def test_repeated_json_artifact_reference_is_parsed_once(self) -> None:
        reference = "repeated.json"
        payload = b'{"schema_version":"1.0"}'
        (self.evidence_root / reference).write_bytes(payload)
        artifacts = canary_protocol.ArtifactIO(self.evidence_root, ".")
        self.addCleanup(artifacts.close)
        budget = canary_protocol._EvidenceBudget(artifacts)
        failures: list[str] = []
        digest_cache: dict[str, str] = {}
        artifact = {"ref": reference, "digest": bytes_digest(payload)}
        with patch.object(
            artifacts,
            "read_bytes_limited",
            wraps=artifacts.read_bytes_limited,
        ) as reader:
            for _ in range(1024):
                self.assertEqual(
                    {"schema_version": "1.0"},
                    canary_protocol._read_bound_json_artifact(
                        budget,
                        artifact,
                        digest_cache,
                        failures,
                        "repeated",
                    ),
                )
        self.assertEqual(1, reader.call_count)
        self.assertEqual([], failures)

    def test_oversized_control_json_fails_before_its_first_parse(self) -> None:
        reference = "large-repeated.json"
        payload = json.dumps(
            {"value": "x" * (canary_protocol.MAX_DERIVED_CACHE_ENTRY_BYTES + 1)}
        ).encode()
        (self.evidence_root / reference).write_bytes(payload)
        artifacts = canary_protocol.ArtifactIO(self.evidence_root, ".")
        self.addCleanup(artifacts.close)
        budget = canary_protocol._EvidenceBudget(artifacts)
        failures: list[str] = []
        digest_cache: dict[str, str] = {}
        artifact = {"ref": reference, "digest": bytes_digest(payload)}
        with patch.object(
            artifacts,
            "read_bytes_limited",
            wraps=artifacts.read_bytes_limited,
        ) as reader:
            with self.assertRaisesRegex(ValidationFailure, "size limit"):
                canary_protocol._read_bound_json_artifact(
                    budget, artifact, digest_cache, failures, "large"
                )
        self.assertEqual(1, reader.call_count)
        self.assertEqual([], failures)

    def test_local_audit_reports_digest_bound_included_runs(self) -> None:
        records = self.complete_records()
        report = self.audit(records)
        self.assertEqual(len(records), len(report["included_run_bindings"]))
        self.assertEqual(len(records), len(report["audited_run_bindings"]))
        bindings = {item["run_id"]: item for item in report["included_run_bindings"]}
        audited = {item["run_id"]: item for item in report["audited_run_bindings"]}
        for record in records:
            self.assertEqual(digest(record), bindings[record["run_id"]]["run_record_digest"])
            self.assertEqual(digest(record), audited[record["run_id"]]["run_record_digest"])

    def test_quality_cohort_has_one_verified_opaque_blind_review_chain(self) -> None:
        records = self.complete_records()
        report = self.audit(records)
        self.assertEqual("local_structural", report["status"], report)
        self.assertEqual(len(records), len(report["blind_review_bindings"]))
        self.assertEqual(
            {record["run_id"] for record in records},
            {item["run_id"] for item in report["blind_review_bindings"]},
        )

    def test_blind_review_leak_session_timing_and_score_tamper_fail_closed(self) -> None:
        cases = (
            ("identity_leak", "blind_identity_leak_before_freeze"),
            ("session_overlap", "blind_reviewer_session_not_isolated"),
            ("timing", "blind_review_timing_invalid"),
            ("score_tamper", "blind_score_digest_mismatch"),
        )
        for case, failure_prefix in cases:
            with self.subTest(case=case):
                records = self.complete_records()
                record = records[0]
                if case == "identity_leak":
                    def leak(assignment):
                        path = self.evidence_root / assignment[
                            "assignment_transcript_artifact"
                        ]["ref"]
                        path.write_bytes(path.read_bytes() + (
                            json.dumps({
                                "type": "response_item",
                                "at": "2026-07-15T00:01:10Z",
                                "payload": {
                                    "type": "message", "role": "user",
                                    "content": [
                                        {"type": "input_text", "text": "candidate"}
                                    ],
                                },
                            }) + "\n"
                        ).encode())
                        assignment["assignment_transcript_artifact"]["digest"] = (
                            bytes_digest(path.read_bytes())
                        )
                    self.rewrite_blind_chain(record, mutate_assignment=leak)
                elif case == "session_overlap":
                    def overlap(score):
                        score["evaluator_session_id"] = record["root_thread_id"]
                        path = self.evidence_root / score[
                            "evaluator_transcript_artifact"
                        ]["ref"]
                        events = [
                            json.loads(line) for line in path.read_text().splitlines()
                        ]
                        events[0]["payload"]["id"] = record["root_thread_id"]
                        path.write_text(
                            "".join(json.dumps(event) + "\n" for event in events)
                        )
                        score["evaluator_transcript_artifact"]["digest"] = bytes_digest(
                            path.read_bytes()
                        )
                    self.rewrite_blind_chain(record, mutate_score=overlap)
                elif case == "timing":
                    self.rewrite_blind_chain(
                        record,
                        mutate_score=lambda score: score.update(
                            {"frozen_at": "2026-07-15T00:00:30Z"}
                        ),
                    )
                else:
                    score_path = self.evidence_root / record["blind_review"][
                        "score_artifact"
                    ]["ref"]
                    score_path.write_bytes(score_path.read_bytes() + b" ")
                report = self.audit(records)
                self.assertTrue(
                    any(
                        item.startswith(f"{failure_prefix}:{record['run_id']}")
                        for item in report["failures"]
                    ),
                    report,
                )

    def test_blind_review_leak_scan_decodes_bounded_common_encodings(self) -> None:
        candidate_base64 = base64.b64encode(b"candidate").decode().rstrip("=")
        combined = base64.b64encode(
            b"%63%61%6e%64%69%64%61%74%65"
        ).decode().rstrip("=")
        percent_encode = lambda value: "".join(
            f"%{byte:02X}" for byte in value.encode("utf-8")
        )
        four_layers = base64.b64encode(
            percent_encode(
                base64.b64encode(
                    percent_encode("candidate").encode("utf-8")
                ).decode().rstrip("=")
            ).encode("utf-8")
        ).decode().rstrip("=")
        five_layers = base64.b64encode(four_layers.encode("utf-8")).decode().rstrip("=")
        cases = {
            "json_unicode_escape": r"\u0063\u0061\u006e\u0064\u0069\u0064\u0061\u0074\u0065",
            "percent_and_form_plus": "%E5%80%99%E9%80%89+%E5%9F%BA%E7%BA%BF",
            "unpadded_base64": candidate_base64,
            "nfkc_fullwidth": "ｃａｎｄｉｄａｔｅ",
            "chinese_candidate": "候选",
            "chinese_baseline": "基线",
            "combined_base64_percent": combined,
            "four_layer_base64_percent": four_layers,
            "decode_depth_exceeded_fails_closed": five_layers,
            "risk_delegation_experiment_alias": "风险委派实验组",
            "full_local_control_alias": "全量本地控制组",
            "other_protocol_arm_id": self.protocol["arms"][1]["arm_id"],
            "other_protocol_treatment": self.protocol["arms"][1]["treatment_digest"],
            "other_protocol_run_id": self.protocol["run_plan"][1]["run_id"],
        }
        for case, encoded_leak in cases.items():
            with self.subTest(case=case):
                records = self.complete_records()
                record = records[0]

                def leak(score):
                    path = self.evidence_root / score[
                        "evaluator_transcript_artifact"
                    ]["ref"]
                    event = {
                        "type": "response_item",
                        "at": "2026-07-15T00:01:40Z",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": encoded_leak}
                            ],
                        },
                    }
                    if case == "json_unicode_escape":
                        line = json.dumps(event).replace(
                            r"\\u0063\\u0061\\u006e\\u0064\\u0069\\u0064\\u0061\\u0074\\u0065",
                            encoded_leak,
                        )
                    else:
                        line = json.dumps(event, ensure_ascii=False)
                    path.write_bytes(path.read_bytes() + line.encode() + b"\n")
                    score["evaluator_transcript_artifact"]["digest"] = bytes_digest(
                        path.read_bytes()
                    )

                self.rewrite_blind_chain(record, mutate_score=leak)
                report = self.audit(records)
                self.assertIn(
                    f"blind_identity_leak_before_freeze:{record['run_id']}",
                    report["failures"],
                    report,
                )

    def test_blind_evaluator_transcript_must_access_bound_review_material(self) -> None:
        for case in ("missing_prompt", "opaque_label", "asset_digest", "rubric_digest"):
            with self.subTest(case=case):
                records = self.complete_records()
                record = records[0]

                def break_access_binding(score):
                    path = self.evidence_root / score[
                        "evaluator_transcript_artifact"
                    ]["ref"]
                    events = [
                        json.loads(line) for line in path.read_text().splitlines()
                    ]
                    if case == "missing_prompt":
                        events = events[:1]
                    else:
                        prompt = events[1]["payload"]["content"][0]["text"]
                        expected = {
                            "opaque_label": record["blind_review"][
                                "assignment_artifact"
                            ]["ref"].split("/")[1],
                            "asset_digest": score["asset_digest"],
                            "rubric_digest": score["rubric_digest"],
                        }[case]
                        events[1]["payload"]["content"][0]["text"] = prompt.replace(
                            expected, "unbound-value"
                        )
                    path.write_text(
                        "".join(json.dumps(event) + "\n" for event in events)
                    )
                    score["evaluator_transcript_artifact"]["digest"] = bytes_digest(
                        path.read_bytes()
                    )

                self.rewrite_blind_chain(
                    record, mutate_score=break_access_binding
                )
                report = self.audit(records)
                self.assertIn(
                    f"blind_transcript_access_binding_invalid:{record['run_id']}",
                    report["failures"],
                    report,
                )

    def test_blind_asset_is_scanned_after_digest_binding(self) -> None:
        records = self.complete_records()
        record = records[0]
        assignment_path = self.evidence_root / record["blind_review"][
            "assignment_artifact"
        ]["ref"]
        original_assignment = json.loads(assignment_path.read_text())
        old_asset_digest = original_assignment["asset_artifact"]["digest"]
        encoded_leak = base64.b64encode(b"candidate").decode().rstrip("=")
        replacement_asset = json.dumps(
            {"delivery": encoded_leak}, separators=(",", ":")
        ).encode()
        new_asset_digest = bytes_digest(replacement_asset)

        def replace_asset(assignment):
            asset_path = self.evidence_root / assignment["asset_artifact"]["ref"]
            asset_path.write_bytes(replacement_asset)
            assignment["asset_artifact"]["digest"] = new_asset_digest

        def bind_replaced_asset(score):
            score["asset_digest"] = new_asset_digest
            transcript_path = self.evidence_root / score[
                "evaluator_transcript_artifact"
            ]["ref"]
            transcript = transcript_path.read_text().replace(
                old_asset_digest, new_asset_digest
            )
            transcript_path.write_text(transcript)
            score["evaluator_transcript_artifact"]["digest"] = bytes_digest(
                transcript_path.read_bytes()
            )

        self.rewrite_blind_chain(
            record,
            mutate_assignment=replace_asset,
            mutate_score=bind_replaced_asset,
        )
        report = self.audit(records)
        self.assertIn(
            f"blind_identity_leak_before_freeze:{record['run_id']}",
            report["failures"],
            report,
        )

    def test_blind_asset_cannot_be_replaced_by_an_unrelated_self_consistent_asset(self) -> None:
        records = self.complete_records()
        record = records[0]
        assignment_path = self.evidence_root / record["blind_review"][
            "assignment_artifact"
        ]["ref"]
        original_assignment = json.loads(assignment_path.read_text())
        old_asset_digest = original_assignment["asset_artifact"]["digest"]
        unrelated_asset = b'{"delivery":"unrelated opaque output"}'
        unrelated_digest = bytes_digest(unrelated_asset)

        def replace_asset(assignment):
            asset_path = self.evidence_root / assignment["asset_artifact"]["ref"]
            asset_path.write_bytes(unrelated_asset)
            assignment["asset_artifact"]["digest"] = unrelated_digest

        def synchronize_score_and_prompt(score):
            score["asset_digest"] = unrelated_digest
            transcript_path = self.evidence_root / score[
                "evaluator_transcript_artifact"
            ]["ref"]
            transcript_path.write_text(
                transcript_path.read_text().replace(
                    old_asset_digest, unrelated_digest
                )
            )
            score["evaluator_transcript_artifact"]["digest"] = bytes_digest(
                transcript_path.read_bytes()
            )

        self.rewrite_blind_chain(
            record,
            mutate_assignment=replace_asset,
            mutate_score=synchronize_score_and_prompt,
        )
        report = self.audit(records)
        self.assertIn(
            f"blind_asset_deliverable_binding_mismatch:{record['run_id']}",
            report["failures"],
            report,
        )

    def test_final_response_capture_requires_one_terminal_platform_event(self) -> None:
        for case in ("missing", "multiple", "nonterminal"):
            with self.subTest(case=case):
                records = self.complete_records()
                record = records[0]
                path = self.evidence_root / record["platform_transcript"]["ref"]
                events = [json.loads(line) for line in path.read_text().splitlines()]
                agent_index = next(
                    index
                    for index, event in enumerate(events)
                    if event.get("type") == "item.completed"
                    and event.get("item", {}).get("type") == "agent_message"
                )
                if case == "missing":
                    events.pop(agent_index)
                elif case == "multiple":
                    events.insert(agent_index, json.loads(json.dumps(events[agent_index])))
                else:
                    events.insert(
                        agent_index + 1,
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "command_execution",
                                "command": "true",
                                "aggregated_output": "",
                                "exit_code": 0,
                                "status": "completed",
                            },
                        },
                    )
                payload = ("\n".join(json.dumps(event) for event in events) + "\n").encode()
                path.write_bytes(payload)
                observed_digest = bytes_digest(payload)
                record["platform_transcript"]["digest"] = observed_digest
                root_thread = next(
                    item
                    for item in record["usage"]["threads"]
                    if item["parent_thread_id"] is None
                )
                root_thread["transcript_digest"] = observed_digest
                report = self.audit(records)
                self.assertIn(
                    f"deliverable_final_response_not_unique:{record['run_id']}",
                    report["failures"],
                    report,
                )

    def test_workspace_capture_without_runner_provenance_fails_closed(self) -> None:
        for capture_kind in ("workspace_patch", "workspace_tree"):
            with self.subTest(capture_kind=capture_kind):
                self.workloads[0]["deliverable_capture"] = {
                    "capture_kind": capture_kind,
                    "path_roots": ["frontend"],
                }
                self.protocol_digest = digest(self.protocol)
                records = self.complete_records()
                report = self.audit(records)
                affected = next(
                    record for record in records if record["workload_id"] == "w1"
                )
                self.assertIn(
                    f"deliverable_capture_provenance_unavailable:{affected['run_id']}",
                    report["failures"],
                    report,
                )

    def test_protocol_and_treatment_digests_are_bound(self) -> None:
        records = self.complete_records()
        records[0]["protocol_digest"] = fixed_digest("wrong-protocol")
        records[1]["treatment_digest"] = fixed_digest("wrong-treatment")
        records[2]["prompt_digest"] = fixed_digest("wrong-prompt")
        report = self.audit(records)
        self.assertIn(f"protocol_digest_mismatch:{records[0]['run_id']}", report["failures"])
        self.assertIn(f"treatment_digest_mismatch:{records[1]['run_id']}", report["failures"])
        self.assertIn(f"prompt_digest_mismatch:{records[2]['run_id']}", report["failures"])

    def test_process_exit_and_prompt_bytes_are_audited(self) -> None:
        records = self.complete_records()
        records[0]["process_exit_code"] = 1
        prompt_ref = records[1]["prompt_artifact"]["ref"]
        (self.evidence_root / prompt_ref).write_text("tampered-prompt")
        report = self.audit(records)
        self.assertIn(f"process_exit_nonzero:{records[0]['run_id']}", report["failures"])
        self.assertIn(f"prompt_artifact_digest_mismatch:{records[1]['run_id']}", report["failures"])

    def test_skill_loads_are_derived_from_command_transcript(self) -> None:
        records = self.complete_records()
        minimum = next(record for record in records if record["arm_id"] == "minimum_skills")
        minimum["treatment_observation"]["loaded_skill_ids"] = ["tdd"]
        report = self.audit(records)
        self.assertIn(
            f"transcript_skill_load_mismatch:{minimum['run_id']}",
            report["failures"],
        )

    def test_skill_read_accepts_bounded_wc_then_reader_sequence(self) -> None:
        records = self.complete_records()
        minimum = next(record for record in records if record["arm_id"] == "minimum_skills")
        transcript_path = self.evidence_root / minimum["platform_transcript"]["ref"]
        events = [json.loads(line) for line in transcript_path.read_text().splitlines()]
        command_item = next(
            event["item"]
            for event in events
            if event.get("type") == "item.completed"
            and event.get("item", {}).get("type") == "command_execution"
        )
        command_item["command"] = (
            f"wc -l {self.plugin_root}/skills/tdd/SKILL.md "
            f"{self.plugin_root}/skills/code-review/SKILL.md && "
            f"sed -n '1,260p' {self.plugin_root}/skills/tdd/SKILL.md && "
            f"sed -n '1,260p' {self.plugin_root}/skills/code-review/SKILL.md"
        )
        transcript_path.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )
        transcript_digest = bytes_digest(transcript_path.read_bytes())
        minimum["platform_transcript"]["digest"] = transcript_digest
        root = next(
            thread for thread in minimum["usage"]["threads"]
            if thread["parent_thread_id"] is None
        )
        root["transcript_digest"] = transcript_digest

        report = self.audit(records)
        self.assertEqual([], report["failures"])

    def test_descendant_usage_requires_native_provenance(self) -> None:
        records = self.complete_records()
        full = next(record for record in records if record["arm_id"] == "full_local")
        child = full["usage"]["threads"][1]
        child.pop("native_transcript_ref")
        child.pop("native_transcript_digest")
        report = self.audit(records)
        self.assertIn(
            f"descendant_native_usage_provenance_missing:{full['run_id']}:{child['thread_id']}",
            report["failures"],
        )

    def test_local_assurance_and_billing_status_are_fixed(self) -> None:
        records = self.complete_records()
        records[0]["assurance"] = "externally_attested"
        records[1]["billing"] = {"status": "unavailable"}
        with self.assertRaises(ValidationFailure):
            self.audit(records)

    def test_unexposed_read_capture_cannot_claim_paths(self) -> None:
        records = self.complete_records()
        record = records[0]
        record["treatment_observation"]["read_path_capture_status"] = "not_exposed"
        report = self.audit(records)
        self.assertIn(
            f"unexposed_read_paths_present:{record['run_id']}",
            report["failures"],
        )

    def test_arm_prompt_digest_is_bound_into_the_treatment_digest(self) -> None:
        arm = self.protocol["arms"][0]
        arm["prompt_digest"] = fixed_digest("changed-prompt")
        arm["treatment_digest"] = digest(
            {"arm_id": arm["arm_id"], "conformance": arm["conformance"]}
        )
        report = self.audit(self.complete_records())
        self.assertIn(
            "treatment_definition_digest_mismatch:route_only",
            report["failures"],
        )

    def test_replacement_must_be_explicit_and_match_the_same_cell(self) -> None:
        records = self.complete_records()
        original = records[0]
        replacement = self.record(self.workloads[1], self.protocol["arms"][0], 3)
        replacement["started_at"] = "2026-07-15T00:03:00Z"
        replacement["finished_at"] = "2026-07-15T00:03:01Z"
        records.append(replacement)
        manifest = self.manifest(records)
        self.add_infrastructure_invalidation(manifest, original, replacement)
        report = self.audit(records, manifest)
        self.assertIn(f"replacement_cell_mismatch:{original['run_id']}", report["failures"])
        self.assertIn(f"unplanned_run_record:{replacement['run_id']}", report["failures"])

    def test_standard_gate_failure_cannot_be_hidden_by_a_clean_spare(self) -> None:
        original_id = "w1-route_only-1"
        replacement_id = original_id + "-replacement"
        self.protocol["run_plan"].append(
            {
                "run_id": replacement_id,
                "workload_id": "w1",
                "arm_id": "route_only",
                "repeat_index": 1,
                "planned_order": 13,
                "plan_role": "replacement_spare",
                "replacement_for_run_id": original_id,
            }
        )
        self.protocol_digest = digest(self.protocol)
        records = self.complete_records()
        original = next(record for record in records if record["run_id"] == original_id)
        original["gate_receipts"][0]["status"] = "failed"
        self.rewrite_outcome(original)
        replacement = self.record(
            self.workloads[0],
            self.protocol["arms"][0],
            1,
            run_id_override=replacement_id,
        )
        records.append(replacement)
        manifest = self.manifest(records)
        original_entry = next(
            entry for entry in manifest["entries"] if entry["run_id"] == original_id
        )
        original_entry.update(
            {
                "disposition": "replaced",
                "reason_code": "infrastructure_invalidated",
                "replacement_run_id": replacement_id,
            }
        )
        with self.assertRaisesRegex(
            ValidationFailure,
            r"(?:missing required property invalidation_artifact|"
            r"'invalidation_artifact' is a required property)",
        ):
            self.audit(records, manifest)

    def test_independent_runner_crash_replacement_keeps_original_in_promotion_burden(self) -> None:
        original_id = "w1-route_only-1"
        replacement_id = original_id + "-replacement"
        self.protocol["run_plan"].append(
            {
                "run_id": replacement_id,
                "workload_id": "w1",
                "arm_id": "route_only",
                "repeat_index": 1,
                "planned_order": 13,
                "plan_role": "replacement_spare",
                "replacement_for_run_id": original_id,
            }
        )
        self.protocol_digest = digest(self.protocol)
        records = self.complete_records()
        original = next(record for record in records if record["run_id"] == original_id)
        original["process_exit_code"] = 70
        self.rewrite_outcome(original)
        replacement = self.record(
            self.workloads[0], self.protocol["arms"][0], 1,
            run_id_override=replacement_id,
        )
        replacement["started_at"] = "2026-07-15T00:03:00Z"
        replacement["finished_at"] = "2026-07-15T00:03:01Z"
        records.append(replacement)
        manifest = self.manifest(records)
        self.add_infrastructure_invalidation(manifest, original, replacement)

        report = self.audit(records, manifest)

        self.assertEqual("local_structural", report["status"], report)
        self.assertEqual([], report["failures"])
        burden_ids = {item["run_id"] for item in report["promotion_burden_bindings"]}
        quality_ids = {item["run_id"] for item in report["quality_cohort_bindings"]}
        invalidated_ids = {item["run_id"] for item in report["invalidated_attempt_bindings"]}
        self.assertIn(original_id, burden_ids)
        self.assertNotIn(original_id, quality_ids)
        self.assertEqual({original_id}, invalidated_ids)
        self.assertEqual(
            [{
                "invalidated_run_id": original_id,
                "replacement_run_id": replacement_id,
                "invalidation_artifact_digest": next(
                    item["invalidation_artifact"]["digest"]
                    for item in manifest["entries"] if item["run_id"] == original_id
                ),
            }],
            report["replacement_edges"],
        )
        self.assertEqual(
            digest({"attempt_bindings": report["promotion_burden_bindings"]}),
            report["promotion_attempt_set_digest"],
        )

    def test_invalidation_reviewer_timing_and_outcome_digest_are_fail_closed(self) -> None:
        original_id = "w1-route_only-1"
        replacement_id = original_id + "-replacement"
        self.protocol["run_plan"].append(
            {
                "run_id": replacement_id, "workload_id": "w1",
                "arm_id": "route_only", "repeat_index": 1,
                "planned_order": 13, "plan_role": "replacement_spare",
                "replacement_for_run_id": original_id,
            }
        )
        self.protocol_digest = digest(self.protocol)
        records = self.complete_records()
        original = next(record for record in records if record["run_id"] == original_id)
        original["process_exit_code"] = 70
        self.rewrite_outcome(original)
        replacement = self.record(
            self.workloads[0], self.protocol["arms"][0], 1,
            run_id_override=replacement_id,
        )
        replacement["started_at"] = "2026-07-15T00:03:00Z"
        replacement["finished_at"] = "2026-07-15T00:03:01Z"
        records.append(replacement)

        cases = (
            ("reviewer", f"invalidation_reviewer_not_isolated:{original_id}"),
            ("timing", f"invalidation_timing_invalid:{original_id}"),
            ("digest", f"invalidation_outcome_digest_mismatch:{original_id}"),
        )
        for case, expected in cases:
            with self.subTest(case=case):
                manifest = self.manifest(records)
                invalidation = self.add_infrastructure_invalidation(
                    manifest, original, replacement
                )
                entry = next(
                    item for item in manifest["entries"] if item["run_id"] == original_id
                )
                if case == "reviewer":
                    invalidation["reviewer_session_id"] = original["root_thread_id"]
                elif case == "timing":
                    invalidation["decided_at"] = "2026-07-14T23:59:59Z"
                    entry["decided_at"] = invalidation["decided_at"]
                else:
                    invalidation["invalidated_outcome_digest"] = fixed_digest("wrong")
                path = self.evidence_root / entry["invalidation_artifact"]["ref"]
                payload = json.dumps(
                    invalidation, sort_keys=True, separators=(",", ":")
                ).encode()
                path.write_bytes(payload)
                entry["invalidation_artifact"]["digest"] = bytes_digest(payload)
                report = self.audit(records, manifest)
                self.assertIn(expected, report["failures"])

    def test_evidence_files_are_safely_resolved_and_rehashed(self) -> None:
        records = self.complete_records()
        platform = self.evidence_root / records[0]["platform_transcript"]["ref"]
        platform.write_text("tampered\n", encoding="utf-8")
        stdout = self.evidence_root / records[1]["gate_receipts"][0]["stdout_ref"]
        stdout.write_text("tampered\n", encoding="utf-8")
        report = self.audit(records)
        self.assertIn(
            f"platform_transcript_digest_mismatch:{records[0]['run_id']}",
            report["failures"],
        )
        self.assertIn(
            f"gate_stdout_digest_mismatch:{records[1]['run_id']}:tests",
            report["failures"],
        )

        records[2]["platform_transcript"]["ref"] = "../outside.jsonl"
        with self.assertRaisesRegex(Exception, "escapes|outside|safe"):
            self.audit(records)

    def test_thread_order_is_irrelevant_and_delegated_transcript_is_rehashed(self) -> None:
        records = self.complete_records()
        records[4]["usage"]["threads"].reverse()
        reordered = self.audit(records)
        self.assertNotIn(
            f"root_thread_mismatch:{records[4]['run_id']}", reordered["failures"]
        )

        delegated_ref = records[4]["usage"]["threads"][0]["transcript_ref"]
        (self.evidence_root / delegated_ref).write_text("tampered\n", encoding="utf-8")
        report = self.audit(records)
        self.assertIn(
            f"thread_transcript_digest_mismatch:{records[4]['run_id']}:{records[4]['usage']['threads'][0]['thread_id']}",
            report["failures"],
        )

    def test_thread_transcript_reuse_is_rejected(self) -> None:
        records = self.complete_records()
        root, child = records[4]["usage"]["threads"]
        child["transcript_ref"] = root["transcript_ref"]
        child["transcript_digest"] = root["transcript_digest"]
        report = self.audit(records)
        self.assertIn(
            f"thread_transcript_reference_reused:{records[4]['run_id']}", report["failures"]
        )
        self.assertIn(
            f"thread_transcript_digest_reused:{records[4]['run_id']}", report["failures"]
        )

        records = self.complete_records()
        source = records[4]["usage"]["threads"][1]
        target = records[5]["usage"]["threads"][1]
        target["transcript_ref"] = source["transcript_ref"]
        target["transcript_digest"] = source["transcript_digest"]
        report = self.audit(records)
        self.assertIn(
            f"experiment_thread_transcript_reference_reused:{records[5]['run_id']}",
            report["failures"],
        )
        self.assertIn(
            f"experiment_thread_transcript_digest_reused:{records[5]['run_id']}",
            report["failures"],
        )

    def test_cross_record_reused_large_transcript_is_read_and_parsed_once(self) -> None:
        records = self.complete_records()
        source = records[4]["usage"]["threads"][1]
        target = records[5]["usage"]["threads"][1]
        transcript_path = self.evidence_root / source["transcript_ref"]
        events = [json.loads(line) for line in transcript_path.read_bytes().splitlines()]
        events[0]["padding"] = "x" * (canary_protocol.MAX_DERIVED_CACHE_ENTRY_BYTES + 1)
        large_line = json.dumps(events[0], separators=(",", ":")).encode()
        payload = large_line + b"\n" + b"\n".join(
            json.dumps(event, separators=(",", ":")).encode()
            for event in events[1:]
        ) + b"\n"
        transcript_path.write_bytes(payload)
        shared_digest = bytes_digest(payload)
        source["transcript_digest"] = shared_digest
        target["transcript_ref"] = source["transcript_ref"]
        target["transcript_digest"] = shared_digest

        original_reader = canary_protocol.ArtifactIO.read_bytes_limited
        original_loads = json.loads
        read_count = 0
        parse_count = 0

        def counting_reader(
            artifact_io: canary_protocol.ArtifactIO, limit: int, reference: str
        ) -> bytes:
            nonlocal read_count
            if reference == source["transcript_ref"]:
                read_count += 1
            return original_reader(artifact_io, limit, reference)

        def counting_loads(value: object, *args: object, **kwargs: object) -> object:
            nonlocal parse_count
            if isinstance(value, bytes) and value.strip() == large_line:
                parse_count += 1
            return original_loads(value, *args, **kwargs)

        with patch.object(
            canary_protocol.ArtifactIO,
            "read_bytes_limited",
            autospec=True,
            side_effect=counting_reader,
        ), patch.object(canary_protocol.json, "loads", side_effect=counting_loads):
            report = self.audit(records)

        self.assertEqual(1, read_count)
        self.assertEqual(1, parse_count)
        self.assertIn(
            f"experiment_thread_transcript_reference_reused:{records[5]['run_id']}",
            report["failures"],
        )
        self.assertIn(
            f"thread_identity_mismatch:{records[5]['run_id']}:{target['thread_id']}",
            report["failures"],
        )

    def test_gate_receipts_and_delegated_usage_must_be_complete(self) -> None:
        records = self.complete_records()
        records[0]["gate_receipts"][0]["status"] = "failed"
        records[4]["usage"]["delegation_event_count"] = 2
        records[2]["usage"]["aggregate"]["input_tokens"] += 1
        report = self.audit(records)
        self.assertIn(f"gate_not_passed:{records[0]['run_id']}:tests", report["failures"])
        self.assertIn(f"delegated_usage_incomplete:{records[4]['run_id']}", report["failures"])
        self.assertIn(f"usage_total_mismatch:{records[2]['run_id']}:input_tokens", report["failures"])

    def test_delegation_requires_descendant_coverage_and_complete_usage(self) -> None:
        records = self.complete_records()
        records[4]["usage"]["coverage"] = "root_only"
        records[5]["usage"]["complete"] = False
        records[10]["usage"]["threads"][1]["complete"] = False
        report = self.audit(records)
        for record in (records[4], records[5], records[10]):
            self.assertIn(
                f"usage_attribution_incomplete:{record['run_id']}",
                report["failures"],
            )

    def test_gate_pass_cannot_contradict_exit_code_or_timeout(self) -> None:
        records = self.complete_records()
        records[0]["gate_receipts"][0]["exit_code"] = 1
        records[1]["gate_receipts"][0]["timed_out"] = True
        report = self.audit(records)
        self.assertIn(f"gate_outcome_mismatch:{records[0]['run_id']}:tests", report["failures"])
        self.assertIn(f"gate_outcome_mismatch:{records[1]['run_id']}:tests", report["failures"])

    def test_treatment_conformance_is_a_hard_failure(self) -> None:
        records = self.complete_records()
        records[0]["treatment_observation"]["route_call_count"] = 2
        records[1]["treatment_observation"]["loaded_skill_ids"] = ["tdd"]
        records[2]["treatment_observation"]["active_runtime_call_count"] = 1
        report = self.audit(records)
        self.assertIn(f"route_call_count_nonconformant:{records[0]['run_id']}", report["failures"])
        self.assertIn(f"skills_nonconformant:{records[1]['run_id']}", report["failures"])
        self.assertIn(f"active_runtime_calls_nonconformant:{records[2]['run_id']}", report["failures"])

    def test_delegation_discovery_and_read_scope_are_treatment_constraints(self) -> None:
        records = self.complete_records()
        records[4]["treatment_observation"]["delegation_event_count"] = 0
        records[1]["treatment_observation"]["recursive_discovery_count"] = 1
        records[2]["treatment_observation"]["observed_read_paths"] = ["backend/pom.xml"]
        report = self.audit(records)
        self.assertIn(
            f"delegation_observation_mismatch:{records[4]['run_id']}", report["failures"]
        )
        self.assertIn(
            f"recursive_discovery_nonconformant:{records[1]['run_id']}", report["failures"]
        )
        self.assertIn(
            f"read_scope_nonconformant:{records[2]['run_id']}:backend/pom.xml",
            report["failures"],
        )

    def test_inclusion_reason_and_plan_are_strict(self) -> None:
        records = self.complete_records()
        manifest = self.manifest(records)
        manifest["entries"][0]["reason_code"] = "protocol_nonconformant"
        report = self.audit(records, manifest)
        self.assertIn(
            f"included_reason_mismatch:{records[0]['run_id']}", report["failures"]
        )

    def test_exclusion_is_derived_from_audited_record_failures(self) -> None:
        records = self.complete_records()
        records[1]["gate_receipts"][0]["status"] = "failed"
        manifest = self.manifest(records)
        manifest["entries"][0]["disposition"] = "excluded"
        manifest["entries"][0]["reason_code"] = "protocol_nonconformant"
        manifest["entries"][1]["disposition"] = "excluded"
        manifest["entries"][1]["reason_code"] = "treatment_nonconformance"
        report = self.audit(records, manifest)
        self.assertIn(f"unjustified_exclusion:{records[0]['run_id']}", report["failures"])
        excluded = {
            item["run_id"]: item["failures"] for item in report["excluded_run_failures"]
        }
        self.assertIn(f"gate_not_passed:{records[1]['run_id']}:tests", excluded[records[1]["run_id"]])
        self.assertIn(f"exclusion_reason_mismatch:{records[1]['run_id']}", report["failures"])

    def test_fixed_arm_contract_and_interleaved_start_order_are_enforced(self) -> None:
        records = self.complete_records()
        protocol = json.loads(json.dumps(self.protocol))
        protocol["arms"][1]["conformance"] = json.loads(
            json.dumps(protocol["arms"][0]["conformance"])
        )
        protocol["arms"][1]["treatment_digest"] = digest(
            {
                "arm_id": "minimum_skills",
                "prompt_digest": protocol["arms"][1]["prompt_digest"],
                "conformance": protocol["arms"][1]["conformance"],
            }
        )
        protocol["run_plan"][2]["planned_order"], protocol["run_plan"][3]["planned_order"] = (
            protocol["run_plan"][3]["planned_order"],
            protocol["run_plan"][2]["planned_order"],
        )
        manifest = self.manifest(records)
        manifest["protocol_digest"] = digest(protocol)
        report = audit_canary_protocol(
            protocol,
            records,
            manifest,
            schema_root=ROOT / "evals/canary",
            evidence_root=self.evidence_root,
        )
        self.assertIn("fixed_arm_contract_mismatch:minimum_skills", report["failures"])
        self.assertIn("interleaved_block_invalid:1", report["failures"])
        self.assertTrue(any(item.startswith("actual_start_order_mismatch:") for item in report["failures"]))

        records = self.complete_records()
        records[0]["finished_at"] = records[0]["started_at"]
        report = self.audit(records)
        self.assertIn(f"run_time_nonpositive:{records[0]['run_id']}", report["failures"])

    def test_codex_jsonl_counts_are_derived_not_trusted_from_observation(self) -> None:
        records = self.complete_records()
        record = records[0]
        transcript_path = self.evidence_root / record["platform_transcript"]["ref"]
        events = [
            {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "engineering-assistant", "tool": "engineering_assistant_start"}},
            {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "engineering-assistant", "tool": "engineering_assistant_artifact_validate"}},
            {"type": "item.completed", "item": {"type": "command_execution", "command": "rg --files backend"}},
        ]
        with transcript_path.open("ab") as stream:
            for event in events:
                stream.write((json.dumps(event) + "\n").encode())
        payload = transcript_path.read_bytes()
        new_digest = bytes_digest(payload)
        record["platform_transcript"]["digest"] = new_digest
        root_thread = next(
            thread for thread in record["usage"]["threads"] if thread["parent_thread_id"] is None
        )
        root_thread["transcript_digest"] = new_digest
        report = self.audit(records)
        self.assertIn(
            f"derived_active_runtime_calls_nonconformant:{record['run_id']}", report["failures"]
        )
        self.assertIn(
            f"derived_other_engineering_assistant_calls_nonconformant:{record['run_id']}",
            report["failures"],
        )
        self.assertIn(
            f"derived_recursive_discovery_nonconformant:{record['run_id']}", report["failures"]
        )

    def test_skill_load_cannot_be_forged_by_an_arbitrary_command_string(self) -> None:
        records = self.complete_records()
        record = next(item for item in records if item["arm_id"] == "minimum_skills")
        transcript_path = self.evidence_root / record["platform_transcript"]["ref"]
        events = [json.loads(line) for line in transcript_path.read_text().splitlines()]
        command_item = next(
            event["item"]
            for event in events
            if event.get("type") == "item.completed"
            and event.get("item", {}).get("type") == "command_execution"
        )
        command_item["command"] = (
            "printf '/plugin/skills/tdd/SKILL.md "
            "/plugin/skills/code-review/SKILL.md'"
        )
        transcript_path.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )
        payload = transcript_path.read_bytes()
        observed_digest = bytes_digest(payload)
        record["platform_transcript"]["digest"] = observed_digest
        root = next(
            thread for thread in record["usage"]["threads"]
            if thread["parent_thread_id"] is None
        )
        root["transcript_digest"] = observed_digest

        report = self.audit(records)
        self.assertIn(
            f"transcript_skill_load_mismatch:{record['run_id']}", report["failures"]
        )

    def test_skill_load_is_bound_to_frozen_root_digest_and_full_content(self) -> None:
        for attack in ("fake-root", "frontmatter-only"):
            records = self.complete_records()
            record = next(item for item in records if item["arm_id"] == "minimum_skills")
            transcript_path = self.evidence_root / record["platform_transcript"]["ref"]
            events = [json.loads(line) for line in transcript_path.read_text().splitlines()]
            command_item = next(
                event["item"]
                for event in events
                if event.get("type") == "item.completed"
                and event.get("item", {}).get("type") == "command_execution"
            )
            if attack == "fake-root":
                fake_root = self.evidence_root / "fake-plugin"
                for skill_id in ("tdd", "code-review"):
                    path = fake_root / "skills" / skill_id / "SKILL.md"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"---\nname: {skill_id}\n---\n", encoding="utf-8")
                command_item["command"] = "; ".join(
                    f"cat {fake_root}/skills/{skill_id}/SKILL.md"
                    for skill_id in ("tdd", "code-review")
                )
                command_item["aggregated_output"] = "---\nname: tdd\n---\n---\nname: code-review\n---\n"
            else:
                command_item["command"] = "; ".join(
                    f"sed -n '/^name:/p' {self.plugin_root}/skills/{skill_id}/SKILL.md"
                    for skill_id in ("tdd", "code-review")
                )
                command_item["aggregated_output"] = "name: tdd\nname: code-review\n"
            transcript_path.write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )
            transcript_digest = bytes_digest(transcript_path.read_bytes())
            record["platform_transcript"]["digest"] = transcript_digest
            root = next(
                thread for thread in record["usage"]["threads"]
                if thread["parent_thread_id"] is None
            )
            root["transcript_digest"] = transcript_digest
            report = self.audit(records)
            self.assertIn(
                f"transcript_skill_load_mismatch:{record['run_id']}", report["failures"]
            )

    def test_codex_started_and_completed_tool_is_counted_once_and_root_usage_is_bound(self) -> None:
        records = self.complete_records()
        record = records[0]
        transcript_path = self.evidence_root / record["platform_transcript"]["ref"]
        started = {
            "type": "item.started",
            "item": {
                "id": "route-call-1",
                "type": "mcp_tool_call",
                "server": "engineering-assistant",
                "tool": "engineering_assistant_route",
            },
        }
        original = transcript_path.read_text(encoding="utf-8")
        transcript_path.write_text(json.dumps(started) + "\n" + original, encoding="utf-8")
        payload = transcript_path.read_bytes()
        new_digest = bytes_digest(payload)
        record["platform_transcript"]["digest"] = new_digest
        root_thread = next(
            thread for thread in record["usage"]["threads"] if thread["parent_thread_id"] is None
        )
        root_thread["transcript_digest"] = new_digest
        report = self.audit(records)
        self.assertEqual("local_structural", report["status"])
        self.assertNotIn(
            f"transcript_count_mismatch:{record['run_id']}:route_call_count",
            report["failures"],
        )

        records = self.complete_records()
        record = records[0]
        root_thread = next(
            thread for thread in record["usage"]["threads"] if thread["parent_thread_id"] is None
        )
        root_thread["input_tokens"] += 1
        record["usage"]["aggregate"]["input_tokens"] += 1
        report = self.audit(records)
        self.assertIn(
            f"root_usage_mismatch:{record['run_id']}:input_tokens", report["failures"]
        )

    def test_descendant_usage_is_derived_and_maps_to_usage_exclusion_reason(self) -> None:
        records = self.complete_records()
        record = records[4]
        child = next(
            thread for thread in record["usage"]["threads"] if thread["parent_thread_id"] is not None
        )
        child["input_tokens"] += 1
        record["usage"]["aggregate"]["input_tokens"] += 1
        report = self.audit(records)
        mismatch = f"thread_usage_mismatch:{record['run_id']}:{child['thread_id']}:input_tokens"
        self.assertIn(mismatch, report["failures"])

        manifest = self.manifest(records)
        entry = next(item for item in manifest["entries"] if item["run_id"] == record["run_id"])
        entry["disposition"] = "excluded"
        entry["reason_code"] = "usage_attribution_incomplete"
        report = self.audit(records, manifest)
        self.assertNotIn(
            f"exclusion_reason_mismatch:{record['run_id']}", report["failures"]
        )
        diagnostics = {
            item["run_id"]: item["failures"] for item in report["excluded_run_failures"]
        }
        self.assertIn(mismatch, diagnostics[record["run_id"]])

        records = self.complete_records()
        record = records[4]
        child = next(
            thread for thread in record["usage"]["threads"] if thread["parent_thread_id"] is not None
        )
        child_path = self.evidence_root / child["transcript_ref"]
        child_path.write_text(
            json.dumps({"type": "item.completed", "item": {"type": "agent_message"}}) + "\n",
            encoding="utf-8",
        )
        child["transcript_digest"] = bytes_digest(child_path.read_bytes())
        report = self.audit(records)
        self.assertIn(
            f"thread_usage_missing:{record['run_id']}:{child['thread_id']}", report["failures"]
        )
        self.assertIn(f"usage_attribution_incomplete:{record['run_id']}", report["failures"])

    def test_descendant_export_and_native_identity_are_bound_and_not_reused(self) -> None:
        records = self.complete_records()
        full_records = [item for item in records if item["arm_id"] == "full_local"]
        record = full_records[0]
        child = next(
            thread for thread in record["usage"]["threads"]
            if thread["parent_thread_id"] is not None
        )
        native_path = self.evidence_root / child["native_transcript_ref"]
        native_events = [json.loads(line) for line in native_path.read_text().splitlines()]
        session_meta = next(
            event for event in native_events if event.get("type") == "session_meta"
        )
        session_meta["payload"]["id"] = "foreign-thread"
        session_meta["payload"]["parent_thread_id"] = "foreign-parent"
        native_path.write_text(
            "\n".join(json.dumps(event) for event in native_events) + "\n",
            encoding="utf-8",
        )
        child["native_transcript_digest"] = bytes_digest(native_path.read_bytes())

        other_child = next(
            thread for thread in full_records[1]["usage"]["threads"]
            if thread["parent_thread_id"] is not None
        )
        other_child["native_transcript_ref"] = child["native_transcript_ref"]
        other_child["native_transcript_digest"] = child["native_transcript_digest"]

        report = self.audit(records)
        self.assertIn(
            f"descendant_native_thread_mismatch:{record['run_id']}:{child['thread_id']}",
            report["failures"],
        )
        self.assertIn(
            f"descendant_native_parent_mismatch:{record['run_id']}:{child['thread_id']}",
            report["failures"],
        )
        self.assertTrue(
            any(
                item.startswith("experiment_native_transcript_reference_reused:")
                for item in report["failures"]
            )
        )

        records = self.complete_records()
        record = next(item for item in records if item["arm_id"] == "full_local")
        child = next(
            thread for thread in record["usage"]["threads"]
            if thread["parent_thread_id"] is not None
        )
        native_path = self.evidence_root / child["native_transcript_ref"]
        native_path.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {"id": "foreign-thread", "parent_thread_id": None},
                }
            )
            + "\n"
            + native_path.read_text(),
            encoding="utf-8",
        )
        child["native_transcript_digest"] = bytes_digest(native_path.read_bytes())
        report = self.audit(records)
        self.assertIn(
            f"descendant_native_session_chain_mismatch:{record['run_id']}:{child['thread_id']}",
            report["failures"],
        )

        records = self.complete_records()
        record = next(item for item in records if item["arm_id"] == "full_local")
        child = next(
            thread for thread in record["usage"]["threads"]
            if thread["parent_thread_id"] is not None
        )
        child["native_transcript_ref"] = child["transcript_ref"]
        child["native_transcript_digest"] = child["transcript_digest"]
        report = self.audit(records)
        self.assertIn(
            f"thread_export_native_reference_reused:{record['run_id']}", report["failures"]
        )
        self.assertIn(
            f"thread_export_native_digest_reused:{record['run_id']}", report["failures"]
        )

    def test_experiment_evidence_and_event_budgets_are_hard_bounds(self) -> None:
        records = self.complete_records()
        with patch.object(canary_protocol, "MAX_EVIDENCE_FILES", 1):
            with self.assertRaisesRegex(ValidationFailure, "file count exceeds limit"):
                self.audit(records)
        with patch.object(canary_protocol, "MAX_TRANSCRIPT_EVENTS", 1):
            with self.assertRaisesRegex(ValidationFailure, "event count exceeds limit"):
                self.audit(records)

    def test_descendant_conformance_events_are_included_in_run_counts(self) -> None:
        records = self.complete_records()
        record = next(item for item in records if item["arm_id"] == "full_local")
        child = next(
            thread for thread in record["usage"]["threads"]
            if thread["parent_thread_id"] is not None
        )
        native_path = self.evidence_root / child["native_transcript_ref"]
        events = [json.loads(line) for line in native_path.read_text().splitlines()]
        events.insert(
            1,
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "namespace": "engineering-assistant",
                    "name": "engineering_assistant_start",
                },
            },
        )
        native_path.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )
        child["native_transcript_digest"] = bytes_digest(native_path.read_bytes())

        report = self.audit(records)
        self.assertIn(
            f"derived_active_runtime_calls_nonconformant:{record['run_id']}",
            report["failures"],
        )

    def test_actual_pre_hardening_local_record_is_downgraded_to_legacy(self) -> None:
        records = self.complete_records()
        legacy = records[0]
        legacy["schema_version"] = "1.0"
        legacy.pop("process_exit_code")
        legacy.pop("prompt_artifact")
        legacy["treatment_observation"].pop("read_path_capture_status")
        manifest = self.manifest(records)

        report = self.audit(records, manifest)
        self.assertEqual("legacy_unverifiable", report["status"])
        self.assertFalse(report["promotion_eligible"])
        self.assertEqual(11, report["included_structural_runs"])
        self.assertTrue(
            any("legacy manifest inclusion ignored" in item for item in report["warnings"])
        )

    def test_descendant_native_failures_map_to_usage_exclusion(self) -> None:
        records = self.complete_records()
        record = next(item for item in records if item["arm_id"] == "full_local")
        child = next(
            thread for thread in record["usage"]["threads"]
            if thread["parent_thread_id"] is not None
        )
        child.pop("native_transcript_ref")
        child.pop("native_transcript_digest")
        manifest = self.manifest(records)
        entry = next(item for item in manifest["entries"] if item["run_id"] == record["run_id"])
        entry["disposition"] = "excluded"
        entry["reason_code"] = "usage_attribution_incomplete"

        report = self.audit(records, manifest)
        self.assertNotIn(
            f"exclusion_reason_mismatch:{record['run_id']}", report["failures"]
        )

    def test_local_assurance_and_collected_billing_require_valid_fields(self) -> None:
        records = self.complete_records()
        records[0]["assurance"] = "externally_attested"
        with self.assertRaises(ValidationFailure):
            self.audit(records)
        records = self.complete_records()
        records[0]["billing"] = {"status": "collected"}
        with self.assertRaises(ValidationFailure):
            self.audit(records)

    def test_legacy_records_are_preserved_but_never_count_as_verified(self) -> None:
        records = self.complete_records()
        records[0] = {
            "schema_version": "1.0",
            "evidence_status": "legacy_unverifiable",
            "run_id": records[0]["run_id"],
            "experiment_id": "exp-1",
            "workload_id": records[0]["workload_id"],
            "arm_id": records[0]["arm_id"],
            "repeat_index": records[0]["repeat_index"],
            "legacy_reason": "delegated usage was not captured",
        }
        manifest = self.manifest(records)
        manifest["entries"][0]["disposition"] = "excluded"
        manifest["entries"][0]["reason_code"] = "legacy_unverifiable"
        report = self.audit(records, manifest)
        self.assertEqual("legacy_unverifiable", report["status"])
        self.assertFalse(report["promotion_eligible"])
        excluded = {
            item["run_id"]: item["failures"] for item in report["excluded_run_failures"]
        }
        self.assertIn(f"legacy_unverifiable:{records[0]['run_id']}", excluded[records[0]["run_id"]])

    def test_local_without_billing_has_explicit_nonpromotion_status(self) -> None:
        records = self.complete_records()
        report = self.audit(records)
        self.assertEqual("local_structural", report["status"])
        self.assertEqual("local_unattested", report["assurance"])
        self.assertEqual("not_collected", report["billing_status"])
        self.assertFalse(report["promotion_eligible"])
        self.assertEqual([], report["failures"])

    def test_current_started_attempt_cannot_omit_outcome_or_required_statuses(self) -> None:
        records = self.complete_records()
        records[0].pop("outcome_artifact")
        with self.assertRaises(ValidationFailure):
            self.audit(records)

        for field in (
            "usage", "cost", "rework", "safety", "quality", "document_noise"
        ):
            with self.subTest(field=field):
                records = self.complete_records()
                record = records[0]
                path = self.evidence_root / record["outcome_artifact"]["ref"]
                outcome = json.loads(path.read_text())
                outcome[field].pop("status")
                payload = json.dumps(
                    outcome, sort_keys=True, separators=(",", ":")
                ).encode()
                path.write_bytes(payload)
                record["outcome_artifact"]["digest"] = bytes_digest(payload)
                report = self.audit(records)
                self.assertIn(
                    f"outcome_artifact_nonconformant:{record['run_id']}",
                    report["failures"],
                )

    def test_attempt_outcome_is_replayed_from_receipt_and_existing_run_facts(self) -> None:
        records = self.complete_records()
        record = records[0]
        path = self.evidence_root / record["outcome_artifact"]["ref"]
        outcome = json.loads(path.read_text())
        outcome["rework"]["count"] = 1
        payload = json.dumps(outcome, sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(payload)
        record["outcome_artifact"]["digest"] = bytes_digest(payload)
        report = self.audit(records)
        self.assertIn(f"outcome_receipt_mismatch:{record['run_id']}", report["failures"])

        records = self.complete_records()
        record = records[0]
        outcome_path = self.evidence_root / record["outcome_artifact"]["ref"]
        outcome = json.loads(outcome_path.read_text())
        outcome["usage"]["input_tokens"] += 1
        receipt_path = self.evidence_root / outcome["raw_receipts"][0]["ref"]
        receipt = json.loads(receipt_path.read_text())
        receipt["attempt_fact"] = {
            key: value for key, value in outcome.items() if key != "raw_receipts"
        }
        receipt_payload = json.dumps(
            receipt, sort_keys=True, separators=(",", ":")
        ).encode()
        receipt_path.write_bytes(receipt_payload)
        outcome["raw_receipts"][0]["digest"] = bytes_digest(receipt_payload)
        outcome_payload = json.dumps(
            outcome, sort_keys=True, separators=(",", ":")
        ).encode()
        outcome_path.write_bytes(outcome_payload)
        record["outcome_artifact"]["digest"] = bytes_digest(outcome_payload)
        report = self.audit(records)
        self.assertIn(f"outcome_usage_mismatch:{record['run_id']}", report["failures"])

    def test_cli_exit_codes_distinguish_failure_and_local_unverifiable(self) -> None:
        records = self.complete_records()
        manifest = self.manifest(records)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, payload in [
                ("protocol.json", self.protocol),
                ("manifest.json", manifest),
            ]:
                (root / name).write_text(json.dumps(payload), encoding="utf-8")
            record_paths = []
            for index, record in enumerate(records):
                path = root / f"run-{index}.json"
                path.write_text(json.dumps(record), encoding="utf-8")
                record_paths.append(path)
            args = build_parser().parse_args(
                [
                    "--repository-root",
                    str(ROOT),
                    "canary-audit",
                    "--protocol",
                    str(root / "protocol.json"),
                    "--evidence-root",
                    str(self.evidence_root),
                    "--inclusion-manifest",
                    str(root / "manifest.json"),
                    *sum((["--run-record", str(path)] for path in record_paths), []),
                ]
            )
            with redirect_stdout(StringIO()) as output:
                self.assertEqual(3, command_canary_audit(args))
            self.assertEqual(
                "local_structural",
                json.loads(output.getvalue())["status"],
            )
            with patch("engineering_assistant.cli.MAX_AUDIT_INPUT_FILE_BYTES", 1):
                with self.assertRaisesRegex(ValidationFailure, "exceeds.*limit|size limit"):
                    command_canary_audit(args)

            records[0]["treatment_observation"]["route_call_count"] = 2
            record_paths[0].write_text(json.dumps(records[0]), encoding="utf-8")
            manifest = self.manifest(records)
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with redirect_stdout(StringIO()):
                self.assertEqual(2, command_canary_audit(args))

            for record, path in zip(records, record_paths):
                record["treatment_observation"]["route_call_count"] = 1
                record["billing"] = {
                    "status": "collected",
                    "source": "provider-ledger",
                    "cost_usd_micros": 100,
                }
                path.write_text(json.dumps(record), encoding="utf-8")
            (root / "manifest.json").write_text(
                json.dumps(self.manifest(records)), encoding="utf-8"
            )
            with redirect_stdout(StringIO()) as output:
                self.assertEqual(2, command_canary_audit(args))
            final_report = json.loads(output.getvalue())
            self.assertEqual(
                "failed", final_report["status"]
            )
            self.assertFalse(final_report["promotion_eligible"])


if __name__ == "__main__":
    unittest.main()
