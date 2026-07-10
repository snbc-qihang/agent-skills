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
        manifest_dir = package_root / ".codex-plugin"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        version = platform_version(catalog.version, supports_four_part=False)
        if self.cachebuster:
            version = f"{version.partition('+')[0]}+codex.{self.cachebuster}"
        manifest = {
            "name": "engineering-assistant",
            "version": version,
            "description": "基于证据的工程原语、受治理流程、状态恢复和人工审批门禁。",
            "author": {
                "name": "sunliming625@gmail.com",
                "email": "sunliming625@gmail.com",
            },
            "skills": "./skills/",
            "interface": {
                "displayName": "工程助手",
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
        for skill in catalog.skills.values():
            metadata_dir = package_root / "skills" / skill.id / "agents"
            metadata_dir.mkdir(parents=True, exist_ok=True)
            display = self.DISPLAY_NAMES[skill.id]
            short = f"按明确范围、证据和完成条件执行“{display}”工作流。"
            if len(short) < 25:
                short = f"按明确范围、可验证证据和完成条件执行“{display}”工程工作流。"
            short = short[:64].rstrip()
            default_prompt = f"使用 ${skill.id} 基于证据完成这项工程任务。"
            content = (
                "interface:\n"
                f"  display_name: {json.dumps(display, ensure_ascii=False)}\n"
                f"  short_description: {json.dumps(short, ensure_ascii=False)}\n"
                f"  default_prompt: {json.dumps(default_prompt, ensure_ascii=False)}\n"
            )
            (metadata_dir / "openai.yaml").write_text(content, encoding="utf-8")
        return [manifest_path]
