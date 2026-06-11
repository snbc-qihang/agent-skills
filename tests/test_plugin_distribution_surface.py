#!/usr/bin/env python3
"""Regression checks for plugin distribution metadata and runtime template scope."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HIGH_RISK_SKILLS = {
    "workflow-orchestrator",
    "code-development",
    "code-quality-governor",
    "release-readiness",
    "release-verification",
    "engineering-knowledge-miner",
    "implementation-controller",
}


def run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(ROOT / "engineering-assistant" / "scripts" / script), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class PluginDistributionSurfaceTests(unittest.TestCase):
    def test_manifest_records_placeholder_metadata_as_waiting_for_human_review(self) -> None:
        manifest = json.loads((ROOT / "engineering-assistant" / "plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual("waiting_for_human_review", manifest["metadata_status"])
        self.assertTrue(manifest["distribution_notes"]["placeholder_metadata_allowed_for_local_template"])
        self.assertEqual("waiting_for_human_review", manifest["distribution_notes"]["external_distribution_gate"])
        self.assertIn("homepage", " ".join(manifest["distribution_notes"]["todo"]))
        self.assertIn("websiteURL", manifest["interface"])
        self.assertIn("privacyPolicyURL", manifest["interface"])
        self.assertIn("termsOfServiceURL", manifest["interface"])

        result = run_script("validate_plugin_manifest.py")
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual("waiting_for_human_review", payload["status"])
        self.assertTrue(any("example" in warning for warning in payload["warnings"]))

    def test_runtime_policy_pack_is_documented_as_target_project_template(self) -> None:
        readme = (ROOT / "engineering-assistant" / "runtime" / "codex" / "README.md").read_text(encoding="utf-8")
        self.assertIn("目标业务项目复制启用", readme)
        self.assertIn("安装插件不等于自动启用", readme)
        self.assertIn("不作为插件内置 hooks 自动生效", readme)
        self.assertIn("trust review", readme)

        manifest = json.loads((ROOT / "engineering-assistant" / "plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertNotIn("hooks", manifest)
        self.assertEqual("target-project-template", manifest["distribution_notes"]["runtime_policy_pack"])

    def test_profile_compatibility_examples_exist(self) -> None:
        profiles = ROOT / "engineering-assistant" / "runtime" / "codex" / "profiles"
        readonly = profiles / "readonly_review.toml"
        controlled = profiles / "controlled_fix.toml"
        self.assertTrue(readonly.exists())
        self.assertTrue(controlled.exists())
        self.assertIn('sandbox_mode = "read-only"', readonly.read_text(encoding="utf-8"))
        self.assertIn('approval_policy = "untrusted"', controlled.read_text(encoding="utf-8"))

        readme = (ROOT / "engineering-assistant" / "runtime" / "codex" / "README.md").read_text(encoding="utf-8")
        self.assertIn("profiles/readonly_review.toml", readme)
        self.assertIn("profiles/controlled_fix.toml", readme)

    def test_skill_discovery_metadata_is_short_and_drift_free(self) -> None:
        registry = json.loads((ROOT / "engineering-assistant" / "registry" / "skills.yaml").read_text(encoding="utf-8"))
        runtime_index = json.loads((ROOT / "engineering-assistant" / "runtime" / "compiled" / "skill-runtime-index.json").read_text(encoding="utf-8"))
        registry_ids = {item["skill_id"] for item in registry["skills"]}
        runtime_ids = {Path(item["path"]).stem.replace(".ir", "") for item in runtime_index["skills"]}
        self.assertEqual(registry_ids, runtime_ids)

        for skill_dir in sorted((ROOT / "skills").iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            description_line = next(line for line in skill_md.splitlines() if line.startswith("description: "))
            self.assertLessEqual(len(description_line), 180, f"{skill_dir.name} description too long")
            self.assertIn("Use when", description_line)
            self.assertIn("Do not use", description_line)

            agent_meta = (skill_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")
            expected = "allow_implicit_invocation: false" if skill_dir.name in HIGH_RISK_SKILLS else "allow_implicit_invocation: true"
            self.assertIn(expected, agent_meta)

    def test_personal_publish_package_keeps_distribution_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            personal_root = Path(temp_dir) / "home"
            result = run_script("publish_plugin.py", "--layout", "personal", "--publish-root", str(personal_root))
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)

            plugin_root = personal_root / "plugins" / "engineering-assistant"
            manifest = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
            self.assertEqual("waiting_for_human_review", manifest["metadata_status"])
            self.assertTrue((plugin_root / "engineering-assistant" / "runtime" / "codex" / "profiles" / "readonly_review.toml").exists())
            self.assertTrue((plugin_root / "engineering-assistant" / "runtime" / "codex" / "README.md").exists())

    def test_publish_plugin_upserts_marketplace_entry_without_clobbering_others(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            publish_root = Path(temp_dir) / "publish"
            marketplace = publish_root / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True, exist_ok=True)
            marketplace.write_text(
                json.dumps(
                    {
                        "name": "personal",
                        "interface": {"displayName": "Personal"},
                        "plugins": [
                            {
                                "name": "other-plugin",
                                "source": {"source": "local", "path": "./plugins/other-plugin"},
                                "policy": {"installation": "AVAILABLE", "authentication": "NONE"},
                                "category": "Utility",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )

            result = run_script("publish_plugin.py", "--publish-root", str(publish_root), "--marketplace-path", str(marketplace))
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)

            payload = json.loads(marketplace.read_text(encoding="utf-8"))
            plugins = {item["name"]: item for item in payload["plugins"]}
            self.assertEqual("personal", payload["name"])
            self.assertEqual("Personal", payload["interface"]["displayName"])
            self.assertIn("other-plugin", plugins)
            self.assertIn("engineering-assistant", plugins)
            self.assertEqual("./plugins/engineering-assistant", plugins["engineering-assistant"]["source"]["path"])


if __name__ == "__main__":
    unittest.main()
