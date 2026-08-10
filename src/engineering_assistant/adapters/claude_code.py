"""Claude Code packaging adapter."""

from __future__ import annotations

import json
from pathlib import Path

from ..catalog import Catalog
from ..version import platform_version


class ClaudeCodeAdapter:
    id = "claude-code"

    PLUGIN_NAME = "engineering-assistant"
    MCP_SERVER_NAME = "engineering-assistant"
    MCP_TOOL_MATCHER = (
        r"^mcp__plugin_engineering-assistant_engineering-assistant__"
        r"engineering_assistant_.*$"
    )

    def write_platform_files(self, package_root: Path, catalog: Catalog) -> list[Path]:
        manifest_dir = package_root / ".claude-plugin"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "plugin.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "name": self.PLUGIN_NAME,
                    "version": platform_version(catalog.version, supports_four_part=False),
                    "description": "基于证据的工程原语、受治理流程、状态恢复和人工审批门禁。",
                    "author": {"name": "sunliming625@gmail.com"},
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        mcp_path = package_root / ".mcp.json"
        mcp_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        self.MCP_SERVER_NAME: {
                            "command": "${CLAUDE_PLUGIN_ROOT}/engineering-assistant/bin/ea",
                            "args": ["mcp-serve"],
                            "cwd": "${CLAUDE_PLUGIN_ROOT}",
                        }
                    }
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        hooks_dir = package_root / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_path = hooks_dir / "hooks.json"
        hook_handler = {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/feedback_capture.py",
            "timeout": 10,
        }
        hook_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [{"hooks": [hook_handler]}],
                        "PreToolUse": [
                            {"matcher": self.MCP_TOOL_MATCHER, "hooks": [hook_handler]}
                        ],
                        "PostToolUse": [
                            {"matcher": self.MCP_TOOL_MATCHER, "hooks": [hook_handler]}
                        ],
                        "Stop": [{"hooks": [hook_handler]}],
                    }
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        hook_script = hooks_dir / "feedback_capture.py"
        hook_script.write_text(
            "#!/usr/bin/env python3\n"
            "import io\n"
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            "def emit_empty():\n"
            "    json.dump({}, sys.stdout); sys.stdout.write('\\n'); return 0\n"
            "try:\n"
            "    root = Path(__file__).resolve().parents[1]\n"
            "    sys.path.insert(0, str(root / 'engineering-assistant/runtime'))\n"
            "    from engineering_assistant.claude_hook import run_claude_hook\n"
            "    output = io.StringIO()\n"
            "    exit_code = run_claude_hook(\n"
            "        input_stream=sys.stdin, output_stream=output,\n"
            "        schema_root=root / 'engineering-assistant/schemas',\n"
            "    )\n"
            "    sys.stdout.write(output.getvalue())\n"
            "except Exception:\n"
            "    exit_code = emit_empty()\n"
            "raise SystemExit(exit_code)\n",
            encoding="utf-8",
        )
        hook_script.chmod(0o755)
        return [manifest_path, mcp_path, hook_path, hook_script]
