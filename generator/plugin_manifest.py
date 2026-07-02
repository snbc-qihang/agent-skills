"""Plugin manifest and publish-config generation."""

from __future__ import annotations

from pathlib import Path

from . import legacy_generator as _legacy
from .io_utils import write_json


PLUGIN_NAME = _legacy.PLUGIN_NAME
PLUGIN_VERSION = _legacy.PLUGIN_VERSION


def plugin_manifest() -> dict:
    return _legacy.plugin_manifest()


def generate_plugin_publish_config(root: Path) -> None:
    write_json(root / ".agent" / "plugins" / "publish-config.json", {
        "name": _legacy.PLUGIN_MARKETPLACE_NAME,
        "interface": {
            "displayName": _legacy.PLUGIN_MARKETPLACE_DISPLAY_NAME,
        },
        "plugin_name": _legacy.PLUGIN_NAME,
        "compatibility_alias": _legacy.PLUGIN_COMPATIBILITY_ALIAS,
        "publish_root": f"~/.codex/local-plugins/{_legacy.PLUGIN_MARKETPLACE_NAME}",
        "hermes_publish_root": "~/.hermes",
        "marketplace_path": f"~/.codex/local-plugins/{_legacy.PLUGIN_MARKETPLACE_NAME}/.agents/plugins/marketplace.json",
        "plugin_relative_path": f"plugins/{_legacy.PLUGIN_NAME}",
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    })
