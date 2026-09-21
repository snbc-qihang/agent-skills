"""Exercise generated Codex metadata and hooks at the process boundary."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from engineering_assistant.compiler import build_package


class CodexProductBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.package = Path(cls.tmp.name) / "codex"
        build_package(ROOT, "codex", cls.package)
        cls.product = json.loads((cls.package / ".codex-plugin/plugin.json").read_text())["name"]
        cls.other = ("engineering-assistant" if cls.product == "teamwork-engineering-assistant"
                     else "teamwork-engineering-assistant")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def hook(self, project, event, **extra):
        payload = dict(cwd=str(project), session_id="boundary", turn_id="one",
                       hook_event_name=event, **extra)
        result = subprocess.run([sys.executable, str(self.package / "hooks/feedback_capture.py")],
            input=json.dumps(payload), text=True, capture_output=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_all_skill_prompts_and_tool_matchers_are_product_qualified(self):
        qualified = set()
        for metadata in (self.package / "skills").glob("*/agents/openai.yaml"):
            skill = metadata.parent.parent.name
            line = next(x for x in metadata.read_text().splitlines() if "default_prompt:" in x)
            prompt = json.loads(line.split(":", 1)[1].strip())
            self.assertIn(f"${self.product}:{skill}", prompt)
            qualified.add(f"{self.product}:{skill}")
        self.assertEqual(11, len(qualified))
        servers = json.loads((self.package / ".mcp.json").read_text())["mcpServers"]
        self.assertEqual([self.product], list(servers))
        hooks = json.loads((self.package / "hooks/hooks.json").read_text())["hooks"]
        for event in ["PreToolUse", "PostToolUse"]:
            matcher = hooks[event][0]["matcher"]
            self.assertIsNotNone(re.fullmatch(matcher, f"mcp__{self.product.replace('-', '_')}__engineering_assistant_route"))
            self.assertIsNone(re.fullmatch(matcher, f"mcp__{self.other.replace('-', '_')}__engineering_assistant_route"))

    def test_other_product_prompt_and_tool_do_not_activate_this_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.assertEqual({}, self.hook(project, "UserPromptSubmit", prompt=f"使用 ${self.other}:tdd 修复问题。"))
            self.assertEqual({}, self.hook(project, "PreToolUse",
                tool_name=f"mcp__{self.other.replace('-', '_')}__engineering_assistant_route", tool_input={}))
            self.assertEqual([], list(project.iterdir()))

    def test_repeated_stop_never_requests_continuation_or_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.hook(project, "UserPromptSubmit", prompt=f"使用 ${self.product}:tdd 修复问题。")
            for active in [False, False, True, True]:
                response = self.hook(project, "Stop", stop_hook_active=active,
                    last_assistant_message="相关回归已通过，本次修改完成。")
                self.assertEqual({}, response)
