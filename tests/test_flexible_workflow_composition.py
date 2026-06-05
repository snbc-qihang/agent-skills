#!/usr/bin/env python3
"""Regression checks for flexible workflow composition and entry modes."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FlexibleWorkflowCompositionTests(unittest.TestCase):
    def load_workflow(self, workflow_id: str) -> dict:
        return json.loads((ROOT / "engineering-assistant" / "workflows" / f"{workflow_id}.yaml").read_text(encoding="utf-8"))

    def test_workflows_declare_supported_entry_modes(self) -> None:
        for workflow_id in ["full-feature-development", "design-only", "coding-only", "frontend-only"]:
            workflow = self.load_workflow(workflow_id)
            self.assertEqual(workflow["default_entry_mode"], "auto_flow")
            self.assertEqual(set(workflow["supported_entry_modes"]), {"auto_flow", "from_node", "single_node"})
            self.assertIn("start_node", workflow)
            self.assertIn("terminal_nodes", workflow)
            self.assertIn("composition_policy", workflow)
            self.assertIn("preflight_runtime_policy", workflow)
            self.assertEqual("preflight_input_state == ready", workflow["preflight_runtime_policy"]["formal_generation_entry_condition"])
            self.assertTrue(workflow["preflight_runtime_policy"]["block_current_node_formal_generation"])
            self.assertTrue(workflow["preflight_runtime_policy"]["block_next_nodes"])
            self.assertIn("from_node", workflow["composition_policy"])
            self.assertIn("single_node", workflow["composition_policy"])
            self.assertIn("auto_flow", workflow["composition_policy"])

    def test_sequential_workflows_wire_next_nodes_and_dependencies(self) -> None:
        workflow = self.load_workflow("coding-only")
        nodes = workflow["nodes"]
        node_ids = [node["node_id"] for node in nodes]
        self.assertEqual(workflow["start_node"], node_ids[0])
        self.assertEqual(workflow["terminal_nodes"], [node_ids[-1]])

        for index, node in enumerate(nodes):
            expected_next = [node_ids[index + 1]] if index + 1 < len(nodes) else []
            expected_previous = [node_ids[index - 1]] if index > 0 else []
            self.assertEqual(node["next_nodes"], expected_next)
            self.assertEqual(node["depends_on"], expected_previous)
            self.assertEqual(set(node["entry_modes"]), {"auto_flow", "from_node", "single_node"})
            self.assertEqual(node["preflight_gate"]["formal_generation_entry_condition"], "preflight_input_state == ready")
            self.assertTrue(node["preflight_gate"]["block_formal_generation_when_not_ready"])
            self.assertTrue(node["preflight_gate"]["block_next_nodes_when_not_ready"])

    def test_workflow_orchestrator_contract_names_runtime_modes(self) -> None:
        contract = json.loads((ROOT / "skills" / "workflow-orchestrator" / "contract.yaml").read_text(encoding="utf-8"))
        self.assertIn("workflow_runtime_policy", contract)
        runtime_policy = contract["workflow_runtime_policy"]
        self.assertEqual(set(runtime_policy["supported_entry_modes"]), {"auto_flow", "from_node", "single_node"})
        self.assertIn("start_node", runtime_policy["from_node_required_fields"])
        self.assertIn("target_node", runtime_policy["single_node_required_fields"])
        self.assertIn("pause_when", runtime_policy["auto_transition_policy"])
        self.assertEqual("preflight_input_state == ready", runtime_policy["auto_transition_policy"]["formal_generation_entry_condition"])
        self.assertTrue(runtime_policy["auto_transition_policy"]["preflight_blocks_current_node_formal_generation"])
        self.assertTrue(runtime_policy["auto_transition_policy"]["preflight_blocks_next_nodes"])
        policy_text = json.dumps(runtime_policy, ensure_ascii=False)
        self.assertIn("preflight_input_state != ready", policy_text)
        self.assertIn("blocking required_information_requests", policy_text)
        self.assertIn("human-review HTML 只作为人工填写入口", policy_text)

    def test_plugin_tree_receives_same_workflow_assets(self) -> None:
        source = self.load_workflow("full-feature-development")
        with tempfile.TemporaryDirectory() as temp_dir:
            publish_root = Path(temp_dir) / "publish"
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
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            plugin = json.loads(
                (
                    publish_root
                    / "plugins"
                    / "teamwork-engineering-assistant"
                    / "engineering-assistant"
                    / "workflows"
                    / "full-feature-development.yaml"
                ).read_text(encoding="utf-8")
            )
        self.assertEqual(source["supported_entry_modes"], plugin["supported_entry_modes"])
        self.assertEqual(source["nodes"][0]["next_nodes"], plugin["nodes"][0]["next_nodes"])


if __name__ == "__main__":
    unittest.main()
