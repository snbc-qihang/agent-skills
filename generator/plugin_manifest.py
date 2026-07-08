"""Plugin manifest and publish-config generation."""

from __future__ import annotations

from pathlib import Path

from .io_utils import write_json


PLUGIN_NAME = "engineering-assistant"
PLUGIN_VERSION = "3.1.0"


def plugin_manifest() -> dict:
    return {
        "name": PLUGIN_NAME,
        "version": PLUGIN_VERSION,
        "metadata_status": "waiting_for_human_review",
        "description": "团队研发助手插件，提供需求准入、主动信息补全、技术/框架选型评审、前端设计研发、代码上下文分析、概要/详细设计、DB/Redis/MQ 设计、设计评审、实现控制、文档治理、代码质量治理和经验沉淀能力。",
        "author": {
            "name": "Engineering Team",
            "email": "engineering@example.com",
            "url": "https://example.internal/engineering-assistant",
        },
        "homepage": "https://example.internal/engineering-assistant",
        "repository": "https://example.internal/engineering-assistant/repo",
        "license": "UNLICENSED",
        "distribution_notes": {
            "placeholder_metadata_allowed_for_local_template": True,
            "external_distribution_gate": "waiting_for_human_review",
            "runtime_policy_pack": "target-project-template",
            "hooks_packaging": "not-bundled",
            "todo": [
                "Replace author.email with an approved team contact before external distribution.",
                "Replace homepage and repository with real internal or public URLs before external distribution.",
                "Set interface.websiteURL, privacyPolicyURL and termsOfServiceURL to approved URLs before external distribution.",
                "Add approved logo, composerIcon and screenshots before listing in a shared marketplace.",
            ],
        },
        "keywords": [
            "engineering",
            "design",
            "framework-selection",
            "frontend",
            "required-information",
            "implementation-control",
            "document-governance",
            "code-quality",
            "workflow",
            "skills",
        ],
        "skills": "./skills/",
        "interface": {
            "displayName": "研发助手",
            "shortDescription": "按团队规范完成设计、研发、评审和质量治理。",
            "longDescription": "面向个人和团队的研发流程插件，内置阶段化 skills、团队规范、语言确认、主动信息补全、技术/框架选型评审、前端设计研发流程、HTML 已审设计到 machine contract 的实现控制、文档编号与生命周期治理、工作流、eval、CI 校验和 profile 注入机制。",
            "developerName": "Engineering Team",
            "category": "Productivity",
            "capabilities": ["Interactive", "Write"],
            "websiteURL": "https://example.internal/engineering-assistant",
            "privacyPolicyURL": "https://example.internal/engineering-assistant/privacy",
            "termsOfServiceURL": "https://example.internal/engineering-assistant/terms",
            "defaultPrompt": [
                "使用研发助手走 design-only 流程",
                "基于当前仓库生成详细设计",
                "检查技术/框架选型，覆盖后端、持久化、前端、测试和构建工具",
                "使用 frontend-only 流程完成前端设计和研发",
                "基于已审 HTML 设计自动推进实现和质量门禁",
                "先确认输出语言是简体中文还是 English",
                "先列出完成本阶段必须由我补充的信息",
                "按文档治理规范生成正式设计文档",
                "评审这份设计是否可进入研发",
            ],
            "brandColor": "#2563EB",
        },
    }


def generate_plugin_publish_config(root: Path) -> None:
    write_json(root / ".agent" / "plugins" / "publish-config.json", {
        "name": "local-engineering",
        "interface": {
            "displayName": "Local Engineering Plugins",
        },
        "plugin_name": PLUGIN_NAME,
        "publish_root": "~/.codex/local-plugins/local-engineering",
        "marketplace_path": "~/.codex/local-plugins/local-engineering/.agents/plugins/marketplace.json",
        "plugin_relative_path": f"plugins/{PLUGIN_NAME}",
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    })
