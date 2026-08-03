from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.mcp_server import RuntimeTools  # noqa: E402
from engineering_assistant.state_store import StateStore  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


def intent(task_kind: str, *, actions: list[str] | None = None) -> dict:
    return {
        "task_kind": task_kind,
        "requested_outcome": f"complete {task_kind}",
        "scope": ["repository"],
        "risk_signals": [],
        "requested_external_actions": list(actions or []),
        "confirmed_actions": [],
        "confidence": 0.95,
        "evidence": ["explicit user request"],
    }


class LocalRuntimeV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.tools = RuntimeTools(ROOT)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_flow_routes_persist_without_host_trust_and_primitive_stays_inline(self) -> None:
        routed = self.tools.call(
            "engineering_assistant_route", {"intent": intent("implement")}
        )
        self.assertTrue(routed["execution"]["persisted_flow_ready"])
        self.assertEqual("persisted_flow", routed["execution"]["recommended_execution"])

        primitive = self.tools.call(
            "engineering_assistant_route", {"intent": intent("model")}
        )
        self.assertFalse(primitive["execution"]["persisted_flow_ready"])
        self.assertEqual("inline", primitive["execution"]["recommended_execution"])

    def test_start_selects_first_node_and_writes_manifest_and_state(self) -> None:
        started = self.tools.call(
            "engineering_assistant_start",
            {
                "intent": intent("implement"),
                "task_id": "task-local-v2",
                "run_id": "run-local-v2",
                "project_root": str(self.project),
                "profile": "default",
            },
        )

        self.assertEqual("2", started["state"]["schema_version"])
        self.assertEqual("continue", started["gate"]["decision"])
        self.assertEqual("select-slice", started["node"]["id"])
        self.assertEqual("work-slicing", started["guidance"]["capability"])
        self.assertEqual("tdd", started["guidance"]["skill"])
        run_dir = self.project / ".run-artifacts/engineering-assistant/run-local-v2"
        self.assertTrue((run_dir / "run-manifest.json").is_file())
        self.assertTrue((run_dir / "run-state.json").is_file())
        manifest = json.loads((run_dir / "run-manifest.json").read_text())
        self.assertEqual("2", manifest["schema_version"])
        self.assertNotIn("prompt", manifest)

    def test_evidence_register_controls_provenance_and_local_digest(self) -> None:
        source = self.project / "src.txt"
        source.write_text("domain fact\n")
        self.tools.call(
            "engineering_assistant_start",
            {
                "intent": intent("implement"),
                "task_id": "task-evidence",
                "run_id": "run-evidence",
                "project_root": str(self.project),
                "profile": "default",
            },
        )

        local = self.tools.call(
            "engineering_assistant_evidence_register",
            {
                "run_id": "run-evidence",
                "project_root": str(self.project),
                "profile": "default",
                "evidence_id": "source-1",
                "kind": "source",
                "uri": "src.txt",
                "producer": "agent",
                "scope": "repository",
                "scope_tags": ["implementation-contract"],
                "contract_refs": [],
            },
        )["evidence"]
        self.assertEqual("runtime_observed", local["provenance"])
        self.assertEqual(
            "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
            local["digest"],
        )

        remote = self.tools.call(
            "engineering_assistant_evidence_register",
            {
                "run_id": "run-evidence",
                "project_root": str(self.project),
                "profile": "default",
                "evidence_id": "remote-1",
                "kind": "external_state",
                "uri": "https://example.invalid/build/1",
                "producer": "agent",
                "scope": "remote-build",
                "scope_tags": [],
                "contract_refs": [],
            },
        )["evidence"]
        self.assertEqual("agent_reported", remote["provenance"])

        outside = Path(self.temporary.name).parent / "outside-evidence.txt"
        outside.write_text("outside")
        try:
            with self.assertRaisesRegex(ValidationFailure, "project_root"):
                self.tools.call(
                    "engineering_assistant_evidence_register",
                    {
                        "run_id": "run-evidence",
                        "project_root": str(self.project),
                "profile": "default",
                        "evidence_id": "outside-1",
                        "kind": "source",
                        "uri": str(outside),
                        "producer": "agent",
                        "scope": "outside",
                        "scope_tags": [],
                        "contract_refs": [],
                    },
                )
        finally:
            outside.unlink(missing_ok=True)

    def test_complete_persists_step_and_returns_next_guidance(self) -> None:
        source = self.project / "slice.md"
        source.write_text("bounded vertical slice\n")
        self.tools.call(
            "engineering_assistant_start",
            {
                "intent": intent("implement"),
                "task_id": "task-complete",
                "run_id": "run-complete",
                "project_root": str(self.project),
                "profile": "default",
            },
        )
        self.tools.call(
            "engineering_assistant_evidence_register",
            {
                "run_id": "run-complete",
                "project_root": str(self.project),
                "profile": "default",
                "evidence_id": "slice-1",
                "kind": "source",
                "uri": "slice.md",
                "producer": "agent",
                "scope": "approved-slice",
                "scope_tags": [],
                "contract_refs": [],
            },
        )
        completed = self.tools.call(
            "engineering_assistant_complete",
            {
                "run_id": "run-complete",
                "project_root": str(self.project),
                "profile": "default",
                "result": {
                    "run_id": "run-complete",
                    "node_id": "select-slice",
                    "status": "completed",
                    "criteria_results": [
                        {
                            "criterion_id": "select-slice:1",
                            "passed": True,
                            "evidence_ids": ["slice-1"],
                            "detail": "The vertical slice and allowed file are explicit.",
                        }
                    ],
                    "outputs": ["slice.md"],
                    "findings": [],
                    "open_questions": [],
                    "requested_transition": "continue",
                },
            },
        )

        self.assertEqual("red-green", completed["node"]["id"])
        self.assertEqual("tdd", completed["guidance"]["capability"])
        steps = list(
            (
                self.project
                / ".run-artifacts/engineering-assistant/run-complete/steps"
            ).glob("*.json")
        )
        self.assertEqual(1, len(steps))
        record = json.loads(steps[0].read_text())
        self.assertEqual(1, record["input_revision"])
        self.assertEqual(completed["state"]["revision"], record["output_revision"])
        self.assertEqual(completed["state"], record["state_after"])

        listed = self.tools.call(
            "engineering_assistant_runs_list",
            {"project_root": str(self.project)},
        )
        self.assertEqual(["run-complete"], [run["run_id"] for run in listed["runs"]])
        status = self.tools.call(
            "engineering_assistant_run_status",
            {"project_root": str(self.project),
                "profile": "default", "run_id": "run-complete"},
        )
        self.assertEqual("red-green", status["node"]["id"])
        self.assertEqual("tdd", status["guidance"]["capability"])

    def test_load_recovers_a_step_written_before_state_cas(self) -> None:
        started = self.tools.call(
            "engineering_assistant_start",
            {
                "intent": intent("implement"),
                "task_id": "task-recovery",
                "run_id": "run-recovery",
                "project_root": str(self.project),
                "profile": "default",
            },
        )
        before = started["state"]
        after = copy.deepcopy(before)
        after["revision"] = before["revision"] + 1
        store = StateStore(self.project, ROOT / "schemas")
        store.record_step(
            result={
                "run_id": "run-recovery",
                "node_id": before["current_node"],
            },
            gate={"decision": "continue"},
            node_output=None,
            input_revision=before["revision"],
            output_revision=after["revision"],
            state_after=after,
        )

        recovered = store.load("run-recovery")

        self.assertEqual(after, recovered.to_dict())
        persisted = json.loads(store.path("run-recovery").read_text())
        self.assertEqual(after, persisted)

    def test_old_run_state_is_rejected_with_stable_message(self) -> None:
        run_dir = self.project / ".run-artifacts/engineering-assistant/old-run"
        run_dir.mkdir(parents=True)
        (run_dir / "run-state.json").write_text(json.dumps({"run_id": "old-run"}))

        store = StateStore(self.project, ROOT / "schemas")
        with self.assertRaisesRegex(ValidationFailure, "旧 RC 协议不受支持"):
            store.load("old-run")

    def test_author_mode_never_allows_an_installed_plugin_target(self) -> None:
        author = self.project / "author"
        for relative in ("catalog", "skills", "schemas", "src/engineering_assistant"):
            (author / relative).mkdir(parents=True, exist_ok=True)
        StateStore(
            author,
            author / "schemas",
            allow_author_repository=True,
        )

        installed = self.project / "installed"
        for relative in ("catalog", "schemas", "runtime/engineering_assistant"):
            (installed / relative).mkdir(parents=True, exist_ok=True)
        with self.assertRaisesRegex(ValidationFailure, "installed plugin tree"):
            StateStore(
                installed,
                installed / "schemas",
                allow_author_repository=True,
            )


if __name__ == "__main__":
    unittest.main()
