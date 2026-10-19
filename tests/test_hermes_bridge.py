from __future__ import annotations

import importlib.util
import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.platforms.adapters.hermes import HermesAdapter
from engineering_assistant.runtime.catalog import load_catalog
from engineering_assistant.runtime.mcp_server import RuntimeTools
from engineering_assistant.platforms.hermes_bridge import HermesBridge, TOOL_FAILURE

ROUTE_ARGS = {
    "intent": {
        "task_kind": "review", "requested_outcome": "评审当前变更。", "scope": ["diff"],
        "risk_signals": [], "requested_external_actions": [], "confirmed_actions": [],
        "confidence": 0.99, "evidence": ["用户请求"],
    }
}


def load_host(package):
    HermesAdapter().write_platform_files(package, load_catalog(ROOT))
    spec = importlib.util.spec_from_file_location("hermes_stdlib_host", package / "__init__.py")
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    return host


class Context:
    def __init__(self):
        self.tools = {}
        self.hooks = {}

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs

    def register_hook(self, name, handler):
        self.hooks[name] = handler

    def register_skill(self, name, path):
        pass


class HermesHostTests(unittest.TestCase):
    def test_registration_uses_only_materialized_definitions_without_host_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            host = load_host(package)
            context = Context()
            host.register(context)
            expected = {item["name"]: item for item in RuntimeTools(ROOT).definitions()}
            self.assertEqual(set(expected), set(context.tools))
            for name, binding in context.tools.items():
                self.assertEqual(expected[name]["inputSchema"], binding["schema"]["parameters"])
            self.assertEqual({"post_llm_call"}, set(context.hooks))
            self.assertEqual(
                {"error": "ToolExecutionError", "status": "failed"},
                json.loads(context.tools["engineering_assistant_route"]["handler"]({})),
            )
            self.assertIsNone(context.hooks["post_llm_call"]("session", "普通请求", "完成", [], "test", "hermes"))

    def test_generated_host_imports_only_stdlib_and_uses_target_launcher(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            HermesAdapter(target="windows-x64").write_platform_files(package, load_catalog(ROOT))
            source = (package / "__init__.py").read_text(encoding="utf-8")
            imported = {
                alias.name.split(".")[0]
                for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import)
                for alias in node.names
            }
            imported |= {
                node.module.split(".")[0]
                for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
            }
            self.assertEqual({"json", "os", "signal", "subprocess", "threading", "time", "pathlib"}, imported)
            self.assertIn("'ea.exe'", source)
            self.assertNotIn("importlib", source)
            self.assertNotIn("jsonschema", source)

    def test_transport_bounds_output_and_times_out_without_exposing_stderr(self):
        real_popen = subprocess.Popen
        scripts = (
            "import sys; sys.stdin.buffer.read(); sys.stdout.write('x' * 8192)",
            "import sys,time; sys.stdin.buffer.read(); time.sleep(10)",
            "import sys; sys.stdin.buffer.read(); sys.stderr.write('secret'); print('broken-json')",
        )
        with tempfile.TemporaryDirectory() as temporary:
            host = load_host(Path(temporary))
            host._MAX_RPC_BYTES = 4096
            host._RPC_TIMEOUT_SECONDS = 0.5
            for script in scripts:
                def spawn(command, **kwargs):
                    self.assertEqual([str(host._LAUNCHER), "hermes-rpc"], command)
                    self.assertEqual(subprocess.DEVNULL, kwargs["stderr"])
                    return real_popen([sys.executable, "-u", "-c", script], **kwargs)
                with mock.patch.object(host.subprocess, "Popen", side_effect=spawn):
                    response = host._handler("engineering_assistant_route")({})
                self.assertEqual(TOOL_FAILURE, json.loads(response))
                self.assertNotIn("secret", response)

    def test_pipe_round_trip_handles_large_request_and_never_transfers_history(self):
        real_popen = subprocess.Popen
        script = "import json,sys; request=json.load(sys.stdin); json.dump({'length':len(request['args']['value'])},sys.stdout)"
        with tempfile.TemporaryDirectory() as temporary:
            host = load_host(Path(temporary))
            def spawn(command, **kwargs):
                return real_popen([sys.executable, "-u", "-c", script], **kwargs)
            with mock.patch.object(host.subprocess, "Popen", side_effect=spawn):
                response = host._handler("fixture")({"value": "x" * 200_000})
            self.assertEqual(200_000, json.loads(response)["length"])
            requests = []
            with mock.patch.object(host, "_rpc", side_effect=lambda request: requests.append(request) or {"complete": True}):
                self.assertIsNone(host._capture_feedback("s", "使用 engineering-assistant 插件", "response", ["private-history"], "model", "hermes", turn_id="t"))
            self.assertEqual(1, requests[0]["args"][3])
            self.assertNotIn("private-history", json.dumps(requests))

    def test_failed_hook_retains_scoped_activity_for_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            host = load_host(Path(temporary))
            context = Context()
            host.register(context)
            seen = []
            def rpc(request):
                seen.append(request)
                return {"decision": {"flow_id": "review"}} if request["operation"] == "call" else {"complete": len(seen) > 3}
            kwargs = {"session_id": "s", "task_id": "task", "cwd": temporary}
            with mock.patch.object(host, "_rpc", side_effect=rpc):
                context.tools["engineering_assistant_route"]["handler"](ROUTE_ARGS, **kwargs)
                hook_args = ("s", "普通要求", "完成", [], "model", "hermes")
                context.hooks["post_llm_call"]("s", "使用 engineering-assistant 插件", "完成", [], "model", "hermes", task_id="task", cwd=temporary + "-other")
                context.hooks["post_llm_call"]("s", "使用 engineering-assistant 插件", "完成", [], "model", "hermes", task_id="task", cwd=temporary)
                context.hooks["post_llm_call"](*hook_args, task_id="task", cwd=temporary)
                context.hooks["post_llm_call"](*hook_args, task_id="task", cwd=temporary)
                self.assertEqual(4, len(seen))
                context.hooks["post_llm_call"]("s", "使用 engineering-assistant 插件", "完成", [], "model", "hermes", task_id="task", cwd=temporary)
            self.assertFalse(seen[1]["kwargs"]["tool_active"])
            self.assertTrue(seen[2]["kwargs"]["tool_active"])
            self.assertTrue(seen[3]["kwargs"]["tool_active"])
            self.assertFalse(seen[4]["kwargs"]["tool_active"])

    def test_unrelated_hook_does_not_start_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            host = load_host(Path(temporary))
            with mock.patch.object(host, "_rpc", side_effect=AssertionError("unrelated turn started Runtime")) as rpc:
                self.assertIsNone(host._capture_feedback("s", "普通请求", "完成", [], "test", "hermes", turn_id="t"))
                rpc.assert_not_called()


class HermesWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.worker = HermesBridge(ROOT)
        self.kwargs = {"session_id": "session", "task_id": "task", "turn_id": "turn", "cwd": str(self.project)}
        self.hook_args = ["session", "继续评审。", "当前被测试失败阻断。", 0, "test", "hermes"]

    def tearDown(self):
        self.temporary.cleanup()

    def hook(self, **kwargs):
        return self.worker.dispatch({"operation": "post_llm_call", "name": "post_llm_call", "args": self.hook_args,
                                     "kwargs": {**self.kwargs, "tool_active": True, **kwargs}})

    def test_new_workers_share_ledger_and_generate_anonymous_efficiency(self):
        for _ in range(2):
            result = HermesBridge(ROOT).call("engineering_assistant_route", ROUTE_ARGS, self.kwargs)
            self.assertEqual("review", result["decision"]["flow_id"])
        self.assertEqual({"complete": True}, self.hook())
        root = self.project / ".run-artifacts/engineering-assistant"
        candidates = list((root / "feedback/efficiency-candidates").glob("*.json"))
        self.assertEqual(1, len(candidates))
        candidate = json.loads(candidates[0].read_text())
        self.assertEqual(2, candidate["tool_calls"])
        self.assertEqual(["hermes_plugin_tool"], candidate["coverage"])
        self.assertIn("duplicate_call", candidate["signals"])
        self.assertEqual([], list((root / "usage-observations").rglob("*.json")))
        for path in (root / "feedback").rglob("*.json"):
            self.assertNotIn("继续评审。", path.read_text())
            self.assertNotIn("当前被测试失败阻断。", path.read_text())

    def test_observer_and_efficiency_failures_do_not_block_tools_or_text_feedback(self):
        with mock.patch.object(self.worker.observer, "handle", side_effect=OSError("observer unavailable")):
            result = self.worker.call("engineering_assistant_route", ROUTE_ARGS, self.kwargs)
        self.assertEqual("review", result["decision"]["flow_id"])
        self.worker.call("engineering_assistant_route", ROUTE_ARGS, self.kwargs)
        with mock.patch.object(self.worker.feedback, "collect_usage_efficiency", side_effect=OSError("store unavailable")), \
                mock.patch.object(self.worker.feedback, "collect_hermes_turn", wraps=self.worker.feedback.collect_hermes_turn) as collect:
            self.assertEqual({"complete": False}, self.hook())
            self.assertEqual(1, collect.call_count)
        self.assertTrue(self.hook()["complete"])

    def test_text_failure_retains_ledger_and_retry_completes(self):
        self.worker.call("engineering_assistant_route", ROUTE_ARGS, self.kwargs)
        with mock.patch.object(self.worker.feedback, "collect_hermes_turn", side_effect=OSError("unavailable")):
            self.assertFalse(self.hook()["complete"])
        ledgers = self.project / ".run-artifacts/engineering-assistant/usage-observations"
        self.assertEqual(1, len(list(ledgers.rglob("*.json"))))
        self.assertTrue(self.hook()["complete"])
        self.assertEqual([], list(ledgers.rglob("*.json")))

    def test_business_failure_is_controlled_and_feedback_modes_remain_scoped(self):
        secret = "private-exception-must-not-leak"
        with mock.patch.object(self.worker.tools, "call", side_effect=RuntimeError(secret)):
            result = self.worker.call("engineering_assistant_route", ROUTE_ARGS, self.kwargs)
        self.assertEqual(TOOL_FAILURE, result)
        self.assertTrue(self.hook()["complete"])
        for path in self.project.rglob("*.json"):
            self.assertNotIn(secret, path.read_text())
        for mode, captures in (("disabled", 0), ("metadata", 2)):
            project = self.project / mode
            project.mkdir()
            kwargs = {**self.kwargs, "cwd": str(project), "feedback_mode": mode}
            self.worker.call("engineering_assistant_route", ROUTE_ARGS, kwargs)
            self.worker.post_llm_call(self.hook_args, {**kwargs, "tool_active": True})
            artifact_root = project / ".run-artifacts/engineering-assistant"
            self.assertEqual(captures, len(list((artifact_root / "feedback/captures").glob("*.json"))))
            self.assertEqual([], list((artifact_root / "usage-observations").rglob("*.json")))

    def test_protocol_rejects_oversized_and_invalid_requests_without_echo(self):
        script = "from engineering_assistant.platforms.hermes_bridge import main; from pathlib import Path; raise SystemExit(main(Path.cwd()))"
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        for raw in (b"secret-invalid-json", b"x" * 1_048_577, b"[]"):
            result = subprocess.run([sys.executable, "-c", script], input=raw, capture_output=True,
                                    cwd=ROOT, env=environment, check=False)
            self.assertEqual(0, result.returncode)
            self.assertEqual(TOOL_FAILURE, json.loads(result.stdout))
            self.assertEqual(b"", result.stderr)

    def test_protocol_subprocess_executes_real_runtime_and_returns_only_json(self):
        script = "from engineering_assistant.platforms.hermes_bridge import main; from pathlib import Path; raise SystemExit(main(Path.cwd()))"
        request = {"operation": "call", "name": "engineering_assistant_route", "args": ROUTE_ARGS, "kwargs": self.kwargs}
        result = subprocess.run(
            [sys.executable, "-c", script], input=json.dumps(request).encode(), capture_output=True, cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}, check=False,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("review", json.loads(result.stdout)["decision"]["flow_id"])
        self.assertEqual(b"", result.stderr)


if __name__ == "__main__":
    unittest.main()
