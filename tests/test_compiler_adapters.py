from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.compiler import build_package, verify_package  # noqa: E402


class CompilerAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_codex_and_hermes_packages_have_the_same_core(self) -> None:
        codex = self.root / "codex"
        hermes = self.root / "hermes"
        codex_report = build_package(ROOT, "codex", codex)
        build_package(ROOT, "hermes", hermes)
        self.assertEqual(11, codex_report["skill_count"])
        self.assertTrue((codex / ".codex-plugin/plugin.json").is_file())
        self.assertTrue((codex / ".mcp.json").is_file())
        self.assertTrue((codex / "hooks/hooks.json").is_file())
        self.assertTrue((codex / "hooks/feedback_capture.py").is_file())
        self.assertTrue((hermes / "plugin.yaml").is_file())
        self.assertTrue((hermes / "__init__.py").is_file())
        self.assertEqual(11, len(list((codex / "skills").glob("*/SKILL.md"))))
        self.assertEqual(11, len(list((hermes / "skills").glob("*/SKILL.md"))))
        self.assertFalse((codex / "engineering-assistant/generator").exists())
        self.assertFalse(any(path.name == ".DS_Store" for path in codex.rglob("*")))
        self.assertFalse(any(path.name == ".DS_Store" for path in hermes.rglob("*")))
        verify_package(codex)
        verify_package(hermes)

        codex_manifest = json.loads((codex / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual("./.mcp.json", codex_manifest["mcpServers"])
        mcp_config = json.loads((codex / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(
            ["mcp-serve"],
            mcp_config["mcpServers"]["engineering-assistant"]["args"][-1:],
        )
        self.assertEqual(
            "./engineering-assistant/bin/ea",
            mcp_config["mcpServers"]["engineering-assistant"]["command"],
        )
        self.assertEqual(".", mcp_config["mcpServers"]["engineering-assistant"]["cwd"])

        hermes_manifest = (hermes / "plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("provides_tools:", hermes_manifest)
        self.assertIn("engineering_assistant_route", hermes_manifest)
        self.assertIn("provides_hooks:", hermes_manifest)
        hooks = json.loads((codex / "hooks/hooks.json").read_text(encoding="utf-8"))
        self.assertEqual({"Stop", "UserPromptSubmit"}, set(hooks["hooks"]))
        for groups in hooks["hooks"].values():
            command = groups[0]["hooks"][0]["command"]
            self.assertIn("${PLUGIN_ROOT}/hooks/feedback_capture.py", command)

        hook_project = self.root / "codex-hook-project"
        hook_project.mkdir()
        hook_payload = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "transcript_path": None,
            "cwd": str(hook_project),
            "hook_event_name": "Stop",
            "model": "test",
            "permission_mode": "default",
            "stop_hook_active": False,
            "last_assistant_message": "当前被测试失败阻断。",
        }
        hook_run = subprocess.run(
            [sys.executable, str(codex / "hooks/feedback_capture.py")],
            input=json.dumps(hook_payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, hook_run.returncode, hook_run.stdout + hook_run.stderr)
        self.assertEqual({}, json.loads(hook_run.stdout))
        self.assertEqual(
            1,
            len(
                list(
                    (
                        hook_project
                        / ".run-artifacts/engineering-assistant/feedback/events"
                    ).glob("*.json")
                )
            ),
        )

        for source in sorted((ROOT / "skills").glob("*/SKILL.md")):
            relative = source.relative_to(ROOT / "skills")
            self.assertEqual(source.read_bytes(), (codex / "skills" / relative).read_bytes())
            self.assertEqual(source.read_bytes(), (hermes / "skills" / relative).read_bytes())

    def test_repeated_build_is_byte_deterministic(self) -> None:
        first = build_package(ROOT, "codex", self.root / "first")
        second = build_package(ROOT, "codex", self.root / "second")
        self.assertEqual(first["payload_digest"], second["payload_digest"])
        self.assertEqual(first["payload_files"], second["payload_files"])

    def test_manifest_uses_supported_platform_fields_and_build_manifest_preserves_canonical_version(self) -> None:
        output = self.root / "codex-version"
        build_package(ROOT, "codex", output)
        manifest = json.loads((output / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual("1.0.0-rc.1+build.0", manifest["version"])
        self.assertEqual(
            {"name": "sunliming625@gmail.com", "email": "sunliming625@gmail.com"},
            manifest["author"],
        )
        self.assertNotIn("canonical_version", manifest)
        self.assertNotIn("skill_versions", manifest)
        self.assertTrue(manifest["interface"]["longDescription"])
        self.assertEqual("sunliming625@gmail.com", manifest["interface"]["developerName"])
        self.assertEqual(3, len(manifest["interface"]["defaultPrompt"]))

        build_manifest = json.loads((output / "package-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("1.0.0.0-rc.1", build_manifest["canonical_version"])
        self.assertEqual(11, len(build_manifest["skill_versions"]))
        self.assertEqual({"1.0.0.0-rc.1"}, set(build_manifest["skill_versions"].values()))

    def test_compiled_runtime_validates_and_runs_real_evals(self) -> None:
        output = self.root / "runtime-smoke"
        build_package(ROOT, "codex", output)
        launcher = output / "engineering-assistant/bin/ea"
        validate = subprocess.run(
            [str(launcher), "validate", "--require-sources"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, validate.returncode, validate.stdout + validate.stderr)
        evaluate = subprocess.run(
            [str(launcher), "eval"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, evaluate.returncode, evaluate.stdout + evaluate.stderr)
        report = json.loads(evaluate.stdout)
        self.assertFalse(report["simulation"])
        self.assertGreaterEqual(report["routing"]["case_count"], 100)

        messages = "\n".join(
            json.dumps(message)
            for message in [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ]
        ) + "\n"
        mcp = subprocess.run(
            [str(launcher), "mcp-serve"],
            input=messages,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, mcp.returncode, mcp.stdout + mcp.stderr)
        responses = [json.loads(line) for line in mcp.stdout.splitlines()]
        self.assertEqual([1, 2], [response["id"] for response in responses])
        tool_names = {item["name"] for item in responses[1]["result"]["tools"]}
        self.assertEqual(10, len(tool_names))
        self.assertNotIn("engineering_assistant_investigation_decide", tool_names)

    def test_hermes_adapter_registers_runtime_tools_from_the_same_kernel(self) -> None:
        output = self.root / "hermes-runtime"
        build_package(ROOT, "hermes", output)

        class Context:
            def __init__(self) -> None:
                self.tools = {}
                self.skills = {}
                self.hooks = {}

            def register_tool(self, **kwargs) -> None:
                self.tools[kwargs["name"]] = kwargs

            def register_skill(self, name, path) -> None:
                self.skills[name] = path

            def register_hook(self, name, handler) -> None:
                self.hooks[name] = handler

        spec = importlib.util.spec_from_file_location(
            "compiled_engineering_assistant", output / "__init__.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        context = Context()
        module.register(context)
        self.assertEqual(10, len(context.tools))
        self.assertNotIn("engineering_assistant_investigation_decide", context.tools)
        plugin_lines = (output / "plugin.yaml").read_text(encoding="utf-8").splitlines()
        start = plugin_lines.index("provides_tools:") + 1
        end = plugin_lines.index("provides_hooks:")
        declared_tools = {line.removeprefix("  - ") for line in plugin_lines[start:end]}
        self.assertEqual(set(context.tools), declared_tools)
        self.assertEqual(11, len(context.skills))
        self.assertEqual({"post_llm_call"}, set(context.hooks))
        payload = context.tools["engineering_assistant_route"]["handler"](
            {
                "intent": {
                    "task_kind": "review",
                    "requested_outcome": "评审变更。",
                    "scope": ["diff"],
                    "risk_signals": [],
                    "requested_external_actions": [],
                    "confidence": 0.95,
                    "evidence": ["用户请求"],
                }
            }
        )
        self.assertEqual("review", json.loads(payload)["decision"]["flow_id"])

        project = self.root / "hermes-project"
        project.mkdir()
        context.hooks["post_llm_call"](
            "session-1",
            "补充要求：不要增加新依赖。",
            "当前被测试失败阻断。",
            [],
            "test",
            "cli",
            cwd=str(project),
        )
        self.assertEqual(
            2,
            len(
                list(
                    (
                        project
                        / ".run-artifacts/engineering-assistant/feedback/events"
                    ).glob("*.json")
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()
