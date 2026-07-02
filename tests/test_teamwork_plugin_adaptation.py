#!/usr/bin/env python3
"""Regression checks for the team-adapted Codex plugin package."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "teamwork-engineering-assistant"
PLUGIN_VERSION = "1.0.0.5"


class TeamworkPluginAdaptationTests(unittest.TestCase):
    def test_manifest_and_publish_config_use_distinct_team_plugin_name(self) -> None:
        manifest = json.loads((ROOT / "engineering-assistant" / "plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(PLUGIN_NAME, manifest["name"])
        self.assertEqual(PLUGIN_VERSION, manifest["version"])
        self.assertEqual("团队研发助手", manifest["interface"]["displayName"])
        self.assertIn("人人取/萤启", manifest["description"])
        self.assertIn("teamwork", manifest["keywords"])

        config = json.loads((ROOT / ".agent" / "plugins" / "publish-config.json").read_text(encoding="utf-8"))
        self.assertEqual(PLUGIN_NAME, config["plugin_name"])
        self.assertEqual(f"plugins/{PLUGIN_NAME}", config["plugin_relative_path"])
        self.assertIn("local-teamwork-engineering", config["publish_root"])

    def test_team_profile_sources_and_rules_are_packaged(self) -> None:
        profile = json.loads((ROOT / "engineering-assistant" / "profiles" / "rrq-yq-team.yaml").read_text(encoding="utf-8"))
        self.assertEqual("rrq-yq-team", profile["profile_id"])
        self.assertEqual("YApi", profile["interface_doc_tool"])
        self.assertIn("萤启服务商系统", profile["system_scope"])
        self.assertFalse((ROOT / "engineering-assistant" / "profiles" / "generic-platform.yaml").exists())

        sources = json.loads((ROOT / "engineering-assistant" / "registry" / "team-standard-sources.yaml").read_text(encoding="utf-8"))
        titles = {item["title"] for item in sources["documents"]}
        self.assertIn("人人取----Yapi使用规范", titles)
        self.assertIn("人人取----缓存Redis设计规范", titles)
        self.assertIn("萤启运营系统概要设计", titles)
        for item in sources["documents"]:
            self.assertIn(str(ROOT / "inputs"), item["source_path"])

        rules = json.loads((ROOT / "engineering-assistant" / "registry" / "team-rule-catalog.yaml").read_text(encoding="utf-8"))
        rule_ids = {item["id"] for item in rules["rules"]}
        for rule_id in ["H7", "RRQ-LOG1", "RRQ-IDEMP1", "YAPI5", "YQ3"]:
            self.assertIn(rule_id, rule_ids)
        self.assertIn("YAPI", rules["eval_rule_prefixes"]["detailed-design"])
        self.assertIn("YQ", rules["eval_rule_prefixes"]["code-review"])

    def test_skill_contracts_load_team_adaptation_policy(self) -> None:
        contract = json.loads((ROOT / "skills" / "detailed-design" / "contract.yaml").read_text(encoding="utf-8"))
        policy = contract["team_adaptation_policy"]
        self.assertEqual("rrq-yq-team", policy["profile_id"])
        self.assertEqual("engineering-assistant/registry/team-standard-sources.yaml", policy["source_catalog"])
        self.assertIn("RRQ", policy["rule_prefixes"])

        skill_md = (ROOT / "skills" / "detailed-design" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("rrq-yq-team.yaml", skill_md)
        self.assertIn("team-rule-catalog.yaml", skill_md)

    def test_personal_layout_publishes_teamwork_plugin_for_codex_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            personal_root = Path(temp_dir) / "home"
            result = subprocess.run(
                [
                    "python3",
                    str(ROOT / "engineering-assistant" / "scripts" / "publish_plugin.py"),
                    "--layout",
                    "personal",
                    "--publish-root",
                    str(personal_root),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)

            plugin_root = personal_root / "plugins" / PLUGIN_NAME
            marketplace_path = personal_root / ".agents" / "plugins" / "marketplace.json"
            self.assertTrue((plugin_root / ".codex-plugin" / "plugin.json").exists())
            published_manifest = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
            self.assertEqual(PLUGIN_VERSION, published_manifest["version"])
            self.assertTrue((plugin_root / "skills").exists())
            self.assertTrue((plugin_root / "engineering-assistant").exists())

            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
            self.assertEqual(PLUGIN_NAME, marketplace["plugins"][0]["name"])
            self.assertEqual(f"./plugins/{PLUGIN_NAME}", marketplace["plugins"][0]["source"]["path"])

    def test_personal_layout_preserves_existing_marketplace_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            personal_root = Path(temp_dir) / "home"
            marketplace_path = personal_root / ".agents" / "plugins" / "marketplace.json"
            marketplace_path.parent.mkdir(parents=True)
            marketplace_path.write_text(
                json.dumps(
                    {
                        "name": "personal",
                        "interface": {"displayName": "Personal"},
                        "plugins": [
                            {
                                "name": "engineering-assistant",
                                "source": {"source": "local", "path": "./plugins/engineering-assistant"},
                                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                                "category": "Productivity",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(ROOT / "engineering-assistant" / "scripts" / "publish_plugin.py"),
                    "--layout",
                    "personal",
                    "--publish-root",
                    str(personal_root),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)

            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
            plugin_names = [item["name"] for item in marketplace["plugins"]]
            self.assertEqual(["engineering-assistant", PLUGIN_NAME], plugin_names)
            self.assertEqual("./plugins/engineering-assistant", marketplace["plugins"][0]["source"]["path"])
            self.assertEqual(f"./plugins/{PLUGIN_NAME}", marketplace["plugins"][1]["source"]["path"])


if __name__ == "__main__":
    unittest.main()
