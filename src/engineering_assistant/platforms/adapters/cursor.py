"""Cursor native local-plugin layout; host acceptance remains a separate gate."""
from __future__ import annotations

import json
from pathlib import Path

from ...runtime.catalog import Catalog
from ...runtime.version import platform_version
from .codex import windows_hook_command


class CursorAdapter:
    id = "cursor"

    def __init__(self, target: str | None = None) -> None:
        self.target = target

    def write_platform_files(self, package_root: Path, catalog: Catalog) -> list[Path]:
        manifest = package_root / ".cursor-plugin/plugin.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"name": "engineering-assistant",
            "version": platform_version(catalog.version, supports_four_part=False),
            "description": "基于证据的工程原语、受治理流程、状态恢复和人工审批门禁。",
            "author": {"name": "sunliming625@gmail.com"}, "license": "MIT",
            "skills": "./skills/", "mcpServers": "./mcp.json", "hooks": "./hooks/hooks.json"},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        executable = "ea.exe" if self.target == "windows-x64" else "ea"
        mcp = package_root / "mcp.json"
        mcp.write_text(json.dumps({"mcpServers": {"engineering-assistant": {
            "command": "${CURSOR_PLUGIN_ROOT}/engineering-assistant/bin/" + executable,
            "args": ["mcp-serve"], "cwd": "${CURSOR_PLUGIN_ROOT}"}}}, indent=2) + "\n", encoding="utf-8")
        hook = (windows_hook_command(root_variable="CURSOR_PLUGIN_ROOT", mode="cursor-hook")
                if self.target == "windows-x64" else '"${CURSOR_PLUGIN_ROOT}/engineering-assistant/bin/ea" cursor-hook')
        hooks = package_root / "hooks/hooks.json"
        hooks.parent.mkdir(parents=True, exist_ok=True)
        hooks.write_text(json.dumps({"version": 1, "hooks": {event: [{"command": hook, "timeout": 10}]
            for event in ("beforeSubmitPrompt", "beforeMCPExecution", "afterMCPExecution", "postToolUseFailure", "stop")}},
            indent=2) + "\n", encoding="utf-8")
        return [manifest, mcp, hooks]
