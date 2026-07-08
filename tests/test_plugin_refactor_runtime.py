#!/usr/bin/env python3
"""Regression checks for the engineering-assistant runtime refactor."""

from __future__ import annotations

import json
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def publish_to_temp(test_case: unittest.TestCase) -> Path:
    temp_dir = tempfile.TemporaryDirectory()
    test_case.addCleanup(temp_dir.cleanup)
    publish_root = Path(temp_dir.name) / "publish"
    result = subprocess.run(
        [
            "python3",
            str(ROOT / "engineering-assistant" / "scripts" / "publish_plugin.py"),
            "--publish-root",
            str(publish_root),
            "--marketplace-path",
            str(publish_root / ".agents" / "plugins" / "marketplace.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    test_case.assertEqual(0, result.returncode, result.stderr + result.stdout)
    return publish_root / "plugins" / "engineering-assistant"


def run_publish(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            str(ROOT / "engineering-assistant" / "scripts" / "publish_plugin.py"),
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class PluginRuntimeRefactorTests(unittest.TestCase):
    def test_implementation_controller_is_source_generated_and_mirrored(self) -> None:
        generator = (ROOT / "generator" / "legacy_generator.py").read_text(encoding="utf-8")
        self.assertIn('"id": "implementation-controller"', generator)
        self.assertIn('"contract-driven-development"', generator)
        self.assertIn('"init_task.py"', generator)
        self.assertIn('"run_quality_commands.py"', generator)

        plugin_root = publish_to_temp(self)
        for root in [ROOT, plugin_root]:
            skill = root / "skills" / "implementation-controller"
            self.assertTrue((skill / "SKILL.md").exists(), f"{skill} missing SKILL.md")
            self.assertTrue((skill / "contract.yaml").exists(), f"{skill} missing contract")
            contract = json.loads((skill / "contract.yaml").read_text(encoding="utf-8"))
            self.assertEqual("implementation-controller", contract["skill_id"])
            self.assertIn("quality-contract.json", json.dumps(contract, ensure_ascii=False))

    def test_contract_driven_workflow_places_controller_after_design_review(self) -> None:
        full = json.loads((ROOT / "engineering-assistant" / "workflows" / "full-feature-development.yaml").read_text(encoding="utf-8"))
        node_ids = [node["node_id"] for node in full["nodes"]]
        self.assertLess(node_ids.index("design-review"), node_ids.index("implementation-controller"))
        self.assertLess(node_ids.index("implementation-controller"), node_ids.index("code-development"))

        dedicated = ROOT / "engineering-assistant" / "workflows" / "contract-driven-development.yaml"
        self.assertTrue(dedicated.exists(), "missing contract-driven-development workflow")
        workflow = json.loads(dedicated.read_text(encoding="utf-8"))
        self.assertEqual("contract-driven-development", workflow["workflow_id"])
        self.assertIn("implementation-controller", [node["node_id"] for node in workflow["nodes"]])

    def test_runtime_policy_pack_exists_and_is_packaged(self) -> None:
        required = [
            "AGENTS.md",
            "engineering-assistant/runtime/codex/README.md",
            "engineering-assistant/runtime/codex/config.toml",
            "engineering-assistant/runtime/codex/rules/default.rules",
            "engineering-assistant/runtime/codex/hooks/pre_tool_use_policy.py",
        ]
        for rel in required:
            self.assertTrue((ROOT / rel).exists(), f"missing source runtime policy file {rel}")
            if rel != "AGENTS.md":
                plugin_root = publish_to_temp(self)
                self.assertTrue((plugin_root / rel).exists(), f"missing packaged runtime policy file {rel}")

        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertLess(len(agents.splitlines()), 90, "AGENTS.md should stay concise")
        self.assertIn("artifacts/_control", agents)

    def test_source_and_plugin_trees_are_synchronized(self) -> None:
        plugin_root = publish_to_temp(self)
        for left, right in [
            (ROOT / "skills", plugin_root / "skills"),
            (ROOT / "engineering-assistant", plugin_root / "engineering-assistant"),
        ]:
            result = subprocess.run(
                ["diff", "-qr", str(left), str(right)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_hermes_layout_registers_all_skills_with_qualified_plugin_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            hermes_root = Path(temp_dir) / "hermes"
            result = run_publish("--layout", "hermes", "--publish-root", str(hermes_root))
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)

            plugin_root = hermes_root / "plugins" / "engineering-assistant"
            self.assertTrue((plugin_root / "plugin.yaml").exists())
            self.assertTrue((plugin_root / "__init__.py").exists())
            self.assertTrue((plugin_root / "skills").exists())
            self.assertTrue((plugin_root / "engineering-assistant").exists())
            payload = json.loads(result.stdout)
            self.assertEqual("hermes", payload["layout"])
            self.assertEqual(str((plugin_root / "plugin.yaml").resolve()), payload["hermes_plugin_manifest"])
            self.assertEqual(str((plugin_root / "__init__.py").resolve()), payload["hermes_plugin_entrypoint"])
            self.assertFalse(payload["hermes_enabled"])

            registered: list[tuple[str, Path, str]] = []

            class FakeHermesContext:
                def register_skill(self, name, path, description=""):
                    registered.append((name, Path(path), description))

            spec = importlib.util.spec_from_file_location("engineering_assistant_hermes_plugin_test", plugin_root / "__init__.py")
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.register(FakeHermesContext())

            expected = sorted(path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md"))
            self.assertEqual(expected, sorted(name for name, _, _ in registered))
            self.assertEqual(len(expected), len(registered))
            self.assertTrue(all(path.exists() for _, path, _ in registered))
            self.assertTrue(all(description for _, _, description in registered))

    def test_hermes_enable_updates_config_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            hermes_root = Path(temp_dir) / "hermes"
            first = run_publish("--layout", "hermes", "--publish-root", str(hermes_root), "--enable")
            self.assertEqual(0, first.returncode, first.stderr + first.stdout)
            second = run_publish("--layout", "hermes", "--publish-root", str(hermes_root), "--enable")
            self.assertEqual(0, second.returncode, second.stderr + second.stdout)

            config_text = (hermes_root / "config.yaml").read_text(encoding="utf-8")
            self.assertEqual(1, config_text.count("engineering-assistant"))
            self.assertTrue(json.loads(first.stdout)["hermes_enabled"])
            self.assertTrue(json.loads(second.stdout)["hermes_enabled"])


if __name__ == "__main__":
    unittest.main()
