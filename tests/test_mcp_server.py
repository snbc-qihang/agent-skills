from __future__ import annotations

import io
import json
import sys
import unittest
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


class MCPServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MCPServer(RuntimeTools(ROOT))

    def request(self, method: str, params: dict | None = None) -> dict:
        message = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            message["params"] = params
        response = self.server.handle(message)
        self.assertIsNotNone(response)
        return response

    def test_initialize_and_tools_list_expose_local_runtime_contract(self) -> None:
        initialized = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        self.assertEqual("2025-06-18", initialized["result"]["protocolVersion"])
        listed = self.request("tools/list", {})
        names = {tool["name"] for tool in listed["result"]["tools"]}
        required = {
            "engineering_assistant_route",
            "engineering_assistant_start",
            "engineering_assistant_next",
            "engineering_assistant_complete",
            "engineering_assistant_runs_list",
            "engineering_assistant_run_status",
            "engineering_assistant_evidence_register",
            "engineering_assistant_approval_record",
            "engineering_assistant_investigation_decide",
            "engineering_assistant_feedback_summary",
        }
        self.assertTrue(required.issubset(names))
        self.assertFalse(any("import" in name or "trust" in name for name in names))

    def test_stdio_rejects_oversized_line_and_recovers(self) -> None:
        oversized = "x" * (MAX_MCP_REQUEST_CHARS + 1) + "\n"
        ping = json.dumps(
            {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}}
        )
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
        deep = "[" * 10_000 + "0" + "]" * 10_000
        ping = json.dumps(
            {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}}
        )
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

    def test_tool_validation_rejects_unknown_evidence_provenance_input(self) -> None:
        definition = next(
            tool
            for tool in RuntimeTools(ROOT).definitions()
            if tool["name"] == "engineering_assistant_evidence_register"
        )
        self.assertNotIn("provenance", definition["inputSchema"]["properties"])
        self.assertNotIn("digest", definition["inputSchema"]["properties"])


if __name__ == "__main__":
    unittest.main()
