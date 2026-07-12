"""Hermes packaging adapter."""

from __future__ import annotations

from pathlib import Path

from ..catalog import Catalog
from ..mcp_server import RuntimeTools
from ..version import platform_version


class HermesAdapter:
    id = "hermes"

    def write_platform_files(self, package_root: Path, catalog: Catalog) -> list[Path]:
        plugin_yaml = package_root / "plugin.yaml"
        version = platform_version(catalog.version, supports_four_part=False)
        provides_tools = "".join(
            f"  - {tool['name']}\n" for tool in RuntimeTools(catalog.root).definitions()
        )
        plugin_yaml.write_text(
            "name: engineering-assistant\n"
            f'version: "{version}"\n'
            f'canonical_version: "{catalog.version}"\n'
            'skill_versions_source: "engineering-assistant/catalog/skills/public.json"\n'
            'description: "基于证据的工程原语、受治理流程、状态恢复和人工审批门禁。"\n'
            'author: "sunliming625@gmail.com"\n'
            "kind: standalone\n"
            "provides_tools:\n"
            + provides_tools
            + "provides_hooks:\n"
            "  - post_llm_call\n"
            "platforms:\n"
            "  - linux\n"
            "  - macos\n"
            "  - windows\n",
            encoding="utf-8",
        )
        entrypoint = package_root / "__init__.py"
        entrypoint.write_text(
            '"""Generated Hermes adapter for engineering-assistant."""\n\n'
            "import json\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n\n"
            "_ROOT = Path(__file__).resolve().parent\n"
            "sys.path.insert(0, str(_ROOT / 'engineering-assistant/runtime'))\n"
            "from engineering_assistant.feedback import FeedbackCollector\n"
            "from engineering_assistant.mcp_server import RuntimeTools\n\n"
            "_TOOLS = RuntimeTools(_ROOT / 'engineering-assistant')\n\n\n"
            "_FEEDBACK = FeedbackCollector(_ROOT / 'engineering-assistant/schemas')\n\n\n"
            "def _handler(name):\n"
            "    def invoke(args, **kwargs):\n"
            "        try:\n"
            "            return json.dumps(_TOOLS.call(name, args), ensure_ascii=False)\n"
            "        except Exception as exc:\n"
            "            return json.dumps({'error': type(exc).__name__, 'message': str(exc)}, ensure_ascii=False)\n"
            "    return invoke\n\n\n"
            "def _capture_feedback(session_id, user_message, assistant_response, conversation_history, model, platform, **kwargs):\n"
            "    try:\n"
            "        _FEEDBACK.collect_hermes_turn(\n"
            "            project_root=kwargs.get('cwd') or Path.cwd(),\n"
            "            session_id=session_id, turn_id=str(kwargs.get('turn_id') or f'{session_id}:{len(conversation_history)}'),\n"
            "            user_message=user_message, assistant_response=assistant_response,\n"
            "            model=model, platform=platform,\n"
            "            mode=kwargs.get('feedback_mode') or os.environ.get('ENGINEERING_ASSISTANT_FEEDBACK_MODE', 'candidates'),\n"
            "        )\n"
            "    except Exception:\n"
            "        return None\n"
            "    return None\n\n\n"
            "def register(ctx) -> None:\n"
            "    for tool in _TOOLS.definitions():\n"
            "        schema = {\n"
            "            'name': tool['name'],\n"
            "            'description': tool['description'],\n"
            "            'parameters': tool['inputSchema'],\n"
            "        }\n"
            "        ctx.register_tool(\n"
            "            name=tool['name'], toolset='engineering-assistant',\n"
            "            schema=schema, handler=_handler(tool['name']),\n"
            "        )\n"
            "    ctx.register_hook('post_llm_call', _capture_feedback)\n"
            "    skills_root = Path(__file__).resolve().parent / 'skills'\n"
            "    for skill_md in sorted(skills_root.glob('*/SKILL.md')):\n"
            "        ctx.register_skill(skill_md.parent.name, skill_md)\n",
            encoding="utf-8",
        )
        return [plugin_yaml, entrypoint]
