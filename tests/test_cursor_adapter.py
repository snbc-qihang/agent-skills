from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class CursorAdapterTests(unittest.TestCase):
    def payload(self, event, root, **extra):
        return {"hook_event_name": event, "conversation_id": "conversation", "generation_id": "generation",
                "workspace_roots": [str(root)], "user_email": "private@example.com", "transcript_path": "/do/not/read", **extra}

    def test_cursor_hook_keeps_native_response_and_ignores_other_servers(self):
        from engineering_assistant.platforms.cursor_hook import run_cursor_hook
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for event, response in (("beforeSubmitPrompt", {"continue": True}), ("beforeMCPExecution", {"permission": "allow"}), ("stop", {})):
                output = io.StringIO()
                payload = self.payload(event, root, prompt="普通任务", mcp_server_name="other", tool_name="engineering_assistant_route")
                self.assertEqual(0, run_cursor_hook(input_stream=io.StringIO(json.dumps(payload)), output_stream=output, schema_root=ROOT / "schemas"))
                self.assertEqual(response, json.loads(output.getvalue()))
            self.assertFalse((root / ".run-artifacts").exists())

    def test_cursor_uses_its_own_platform_and_drops_private_host_metadata(self):
        from engineering_assistant.platforms.cursor_hook import run_cursor_hook
        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "engineering_assistant.platforms.cursor_hook.run_lifecycle_hook", return_value=0
        ) as collect:
            payload = self.payload("afterMCPExecution", Path(temporary).resolve(),
                mcp_server_name="engineering-assistant", tool_name="engineering_assistant_route",
                tool_input='{"intent":{}}', result_json='{"result":{"decision":"proceed"}}', tool_use_id="native-call-id")
            output = io.StringIO()
            self.assertEqual(0, run_cursor_hook(input_stream=io.StringIO(json.dumps(payload)), output_stream=output))
            normalized = json.loads(collect.call_args.kwargs["input_stream"].getvalue())
            self.assertEqual("cursor", collect.call_args.kwargs["platform"])
            self.assertEqual("PostToolUse", normalized["hook_event_name"])
            self.assertEqual("mcp__engineering-assistant__engineering_assistant_route", normalized["tool_name"])
            self.assertNotIn("private@example.com", json.dumps(normalized))
            self.assertNotIn("/do/not/read", json.dumps(normalized))

    def test_cursor_without_native_call_id_does_not_invent_usage_counts(self):
        from engineering_assistant.platforms.cursor_hook import run_cursor_hook
        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "engineering_assistant.platforms.cursor_hook.run_lifecycle_hook"
        ) as usage, mock.patch("engineering_assistant.platforms.cursor_hook.FeedbackCollector") as collector:
            payload = self.payload("afterMCPExecution", Path(temporary).resolve(),
                mcp_server_name="engineering-assistant", tool_name="engineering_assistant_route",
                tool_input="{}", result_json='{"isError":true}')
            self.assertEqual(0, run_cursor_hook(input_stream=io.StringIO(json.dumps(payload)), output_stream=io.StringIO()))
            usage.assert_not_called()
            self.assertEqual("cursor", collector.return_value.collect_lifecycle.call_args.kwargs["platform"])

    def test_malformed_or_ambiguous_cursor_input_fails_open_without_false_success(self):
        from engineering_assistant.platforms.cursor_hook import run_cursor_hook
        for payload in ("{", json.dumps({"hook_event_name": "beforeMCPExecution"}), json.dumps({
            "hook_event_name": "beforeMCPExecution", "conversation_id": "c", "generation_id": "g",
            "workspace_roots": ["/first", "/second"], "mcp_server_name": "engineering-assistant",
            "tool_name": "engineering_assistant_route"})):
            output = io.StringIO()
            self.assertEqual(1, run_cursor_hook(input_stream=io.StringIO(payload), output_stream=output))
            self.assertEqual("", output.getvalue())

    def test_cursor_manifest_uses_native_paths_and_full_hook_surface(self):
        from engineering_assistant.tools.compiler import build_package, verify_package
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary).resolve() / "cursor"
            build_package(ROOT, "cursor", package)
            self.assertEqual("cursor", verify_package(package)["platform"])
            manifest = json.loads((package / ".cursor-plugin/plugin.json").read_text())
            self.assertEqual("engineering-assistant", manifest["name"])
            mcp = json.loads((package / "mcp.json").read_text())["mcpServers"]["engineering-assistant"]
            self.assertIn("${CURSOR_PLUGIN_ROOT}", mcp["command"])
            hooks = json.loads((package / "hooks/hooks.json").read_text())["hooks"]
            self.assertEqual({"beforeSubmitPrompt", "beforeMCPExecution", "afterMCPExecution", "postToolUseFailure", "stop"}, set(hooks))
            commands = [entry["command"] for entries in hooks.values() for entry in entries]
            if os.name == "nt":
                import base64
                commands = [base64.b64decode(command.split()[-1]).decode("utf-16le") for command in commands]
            self.assertTrue(all("cursor-hook" in command for command in commands))

    def test_unprepared_cursor_permission_hook_uses_documented_fail_open_exit(self):
        from engineering_assistant.tools.compiler import build_package
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = root / "cursor"
            build_package(ROOT, "cursor", package)
            executable = package / "engineering-assistant/bin" / ("ea.exe" if os.name == "nt" else "ea")
            result = subprocess.run([str(executable), "cursor-hook"], input="{}", capture_output=True, text=True,
                env={**os.environ, "ENGINEERING_ASSISTANT_DATA_HOME": str(root / "not-prepared")}, timeout=15)
            self.assertEqual(1, result.returncode)
            self.assertEqual("", result.stdout)


if __name__ == "__main__":
    unittest.main()
