"""Codex packaging adapter."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..catalog import Catalog
from ..version import platform_version


class CodexAdapter:
    id = "codex"

    def __init__(self, cachebuster: str | None = None) -> None:
        if cachebuster is not None and not re.fullmatch(r"[0-9A-Za-z-]+", cachebuster):
            raise ValueError("Codex cachebuster 只能包含字母、数字和连字符")
        self.cachebuster = cachebuster

    DISPLAY_NAMES = {
        "engineering-assistant": "工程助手",
        "research": "工程研究",
        "decision-interview": "决策访谈",
        "domain-modeling": "领域建模",
        "repo-context": "仓库上下文",
        "wayfinder": "长任务导航",
        "prototype": "原型验证",
        "codebase-design": "代码库设计",
        "tdd": "测试驱动开发",
        "diagnosing-bugs": "缺陷诊断",
        "code-review": "代码评审",
    }

    def write_platform_files(self, package_root: Path, catalog: Catalog) -> list[Path]:
        mcp_server_id = catalog.product.id.replace("-", "_")
        manifest_dir = package_root / ".codex-plugin"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        version = platform_version(catalog.version, supports_four_part=False)
        if self.cachebuster:
            version = f"{version.partition('+')[0]}+codex.{self.cachebuster}"
        manifest = {
            "name": catalog.product.id,
            "version": version,
            "description": "基于证据的工程原语、受治理流程、状态恢复和人工审批门禁。",
            "author": {
                "name": "sunliming625@gmail.com",
                "email": "sunliming625@gmail.com",
            },
            "skills": "./skills/",
            "mcpServers": "./.mcp.json",
            "interface": {
                "displayName": catalog.product.display_name,
                "shortDescription": "基于证据、状态和审批门禁执行工程任务。",
                "longDescription": "以可复用工程原语、受治理 flow、可恢复运行状态和人工审批门禁，协助完成研究、设计、实现、诊断、评审与发布准备。",
                "developerName": "sunliming625@gmail.com",
                "category": "Productivity",
                "capabilities": ["Interactive", "Write"],
                "defaultPrompt": [
                    "梳理当前仓库上下文并给出最小充分的工程路径。",
                    "基于证据诊断这个问题，并明确风险和验证结果。",
                    "评审当前变更是否符合仓库规范和原始需求。",
                ],
            },
        }
        manifest_path = manifest_dir / "plugin.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        mcp_path = package_root / ".mcp.json"
        mcp_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        catalog.product.id: {
                            "command": f"./{catalog.product.id}/bin/ea",
                            "args": ["mcp-serve"],
                            "cwd": ".",
                        }
                    }
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        hooks_dir = package_root / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_command = "python3 ${PLUGIN_ROOT}/hooks/feedback_capture.py"
        hook_command_windows = 'py -3 "%PLUGIN_ROOT%\\hooks\\feedback_capture.py"'
        hook_handler = {
            "type": "command",
            "command": hook_command,
            "commandWindows": hook_command_windows,
            "timeout": 10,
        }
        hooks_path = hooks_dir / "hooks.json"
        hooks_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {"hooks": [hook_handler]}
                        ],
                        "PreToolUse": [
                            {
                                "matcher": f"^mcp__{mcp_server_id}__engineering_assistant_.*$",
                                "hooks": [hook_handler],
                            }
                        ],
                        "PostToolUse": [
                            {
                                "matcher": f"^mcp__{mcp_server_id}__engineering_assistant_.*$",
                                "hooks": [hook_handler],
                            }
                        ],
                        "Stop": [
                            {"hooks": [hook_handler]}
                        ],
                    }
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        hook_script = hooks_dir / "feedback_capture.py"
        hook_script.write_text(
            "#!/usr/bin/env python3\n"
            "import importlib.util\n"
            "import json\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "def emit_empty():\n"
            "    json.dump({}, sys.stdout); sys.stdout.write('\\n'); return 0\n"
            "try:\n"
            "    root = Path(__file__).resolve().parents[1]\n"
            f"    os.environ.setdefault('ENGINEERING_ASSISTANT_PLUGIN_ID', '{catalog.product.id}')\n"
            f"    os.environ.setdefault('ENGINEERING_ASSISTANT_MCP_SERVER_ID', '{mcp_server_id}')\n"
            f"    gate_path = root / '{catalog.product.id}/runtime/engineering_assistant/hook_gate.py'\n"
            "    spec = importlib.util.spec_from_file_location('_engineering_assistant_hook_gate', gate_path)\n"
            "    if spec is None or spec.loader is None:\n"
            "        raise ImportError('hook gate loader is unavailable')\n"
            "    gate = importlib.util.module_from_spec(spec)\n"
            "    spec.loader.exec_module(gate)\n"
            "    should_load, raw = gate.read_gate_input(sys.stdin)\n"
            "    if should_load:\n"
            "        import io\n"
            f"        sys.path.insert(0, str(root / '{catalog.product.id}/runtime'))\n"
            "        from engineering_assistant.feedback import run_codex_hook\n"
            "        output = io.StringIO()\n"
            f"        exit_code = run_codex_hook(input_stream=io.StringIO(raw), output_stream=output, schema_root=root / '{catalog.product.id}/schemas')\n"
            "        sys.stdout.write(output.getvalue())\n"
            "    else:\n"
            "        exit_code = emit_empty()\n"
            "except Exception:\n"
            "    exit_code = emit_empty()\n"
            "raise SystemExit(exit_code)\n",
            encoding="utf-8",
        )
        hook_script.chmod(0o755)
        for skill in catalog.skills.values():
            metadata_dir = package_root / "skills" / skill.id / "agents"
            metadata_dir.mkdir(parents=True, exist_ok=True)
            display = self.DISPLAY_NAMES[skill.id]
            short = f"按明确范围、证据和完成条件执行“{display}”工作流。"
            if len(short) < 25:
                short = f"按明确范围、可验证证据和完成条件执行“{display}”工程工作流。"
            short = short[:64].rstrip()
            invocation = f"$teamwork-engineering-assistant:{skill.id}"
            default_prompt = f"使用 {invocation} 基于证据完成这项工程任务。"
            content = (
                "interface:\n"
                f"  display_name: {json.dumps(display, ensure_ascii=False)}\n"
                f"  short_description: {json.dumps(short, ensure_ascii=False)}\n"
                f"  default_prompt: {json.dumps(default_prompt, ensure_ascii=False)}\n"
            )
            (metadata_dir / "openai.yaml").write_text(content, encoding="utf-8")
        return [manifest_path, mcp_path, hooks_path, hook_script]
