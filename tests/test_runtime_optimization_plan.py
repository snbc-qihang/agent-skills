#!/usr/bin/env python3
"""Regression checks for runtime IR, routing, scored eval, context packs, and root CI."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def publish_to_temp(test_case: unittest.TestCase) -> Path:
    temp_dir = tempfile.TemporaryDirectory()
    test_case.addCleanup(temp_dir.cleanup)
    publish_root = Path(temp_dir.name) / "publish"
    result = run_script(
        "publish_plugin.py",
        "--publish-root",
        str(publish_root),
        "--marketplace-path",
        str(publish_root / ".agents" / "plugins" / "marketplace.json"),
    )
    test_case.assertEqual(0, result.returncode, result.stderr + result.stdout)
    return publish_root / "plugins" / "teamwork-engineering-assistant"


def run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(ROOT / "engineering-assistant" / "scripts" / script), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class RuntimeOptimizationPlanTests(unittest.TestCase):
    def test_root_ci_is_generated_with_required_gates(self) -> None:
        for workflow in ["codex-code-quality.yml", "codex-skill-eval.yml", "codex-knowledge-mining.yml"]:
            path = ROOT / ".github" / "workflows" / workflow
            self.assertTrue(path.exists(), f"missing root workflow {workflow}")
            text = path.read_text(encoding="utf-8")
            self.assertIn("run_skill_evals.py", text)

        quality = (ROOT / ".github" / "workflows" / "codex-code-quality.yml").read_text(encoding="utf-8")
        for required in [
            "python3 -m unittest discover -s tests -v",
            "validate_skill_contract.py",
            "validate_workflow.py",
            "run_skill_evals.py --mode scored",
            "validate_skill_metadata.py",
            "publish_plugin.py",
            "diff -qr skills /tmp/teamwork-engineering-assistant-plugin/plugins/teamwork-engineering-assistant/skills",
            "diff -qr engineering-assistant /tmp/teamwork-engineering-assistant-plugin/plugins/teamwork-engineering-assistant/engineering-assistant",
        ]:
            self.assertIn(required, quality)

    def test_readme_documents_generator_first_and_canary(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("generate_engineering_assistant_assets.py", text)
        self.assertIn("publish_plugin.py", text)
        self.assertIn(".agent/plugins/publish-config.json", text)
        self.assertIn("--layout personal", text)
        self.assertIn("~/.agents/plugins/marketplace.json", text)
        self.assertIn("/Users/sunliming/work/project/personal/ai-platform-v1", text)
        self.assertIn("run_skill_evals.py --mode scored", text)
        self.assertIn("upstream-main-capability-matrix.md", text)

    def test_repository_does_not_keep_temporary_plugin_publish_dir(self) -> None:
        self.assertFalse((ROOT / "plugins").exists())
        self.assertTrue((ROOT / ".agent" / "plugins" / "publish-config.json").exists())
        self.assertFalse((ROOT / ".agent" / "plugins" / "marketplace.json").exists())
        self.assertIn("/plugins/", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    def test_skill_runtime_ir_is_generated_and_can_be_recompiled(self) -> None:
        index = json.loads((ROOT / "engineering-assistant" / "runtime" / "compiled" / "skill-runtime-index.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(index["skills"]), 20)
        repo_context = ROOT / "engineering-assistant" / "runtime" / "compiled" / "skills" / "repo-context-miner.ir.json"
        ir = json.loads(repo_context.read_text(encoding="utf-8"))
        for field in ["skill_id", "prompt_pack", "inputs", "outputs", "routing", "risk", "quality_gates", "source_files"]:
            self.assertIn(field, ir)
        self.assertEqual("repo-context-miner", ir["skill_id"])

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_script("compile_skill_runtime.py", "--out", temp_dir)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            compiled_index = json.loads((Path(temp_dir) / "skill-runtime-index.json").read_text(encoding="utf-8"))
            self.assertEqual(len(index["skills"]), len(compiled_index["skills"]))

    def test_router_handles_explicit_negative_and_high_risk_implicit(self) -> None:
        explicit = run_script("route_skill.py", "--prompt", "使用 repo-context-miner，根据当前仓库产物恢复上下文。")
        self.assertEqual(0, explicit.returncode, explicit.stderr + explicit.stdout)
        self.assertEqual("repo-context-miner", json.loads(explicit.stdout)["decision"])

        negative = run_script("route_skill.py", "--prompt", "只解释 Code Development 的用途，不执行任务、不生成产物。")
        self.assertEqual(0, negative.returncode, negative.stderr + negative.stdout)
        self.assertEqual("rejected", json.loads(negative.stdout)["status"])

        canary = run_script("route_skill.py", "--prompt", "继续推进任务 complete_identity_access_rbac_and_model_usage_policy_projection_before_rag_runtime")
        self.assertEqual(0, canary.returncode, canary.stderr + canary.stdout)
        payload = json.loads(canary.stdout)
        self.assertEqual("waiting_for_input", payload["status"])
        self.assertIn("explicit-only", payload["reason"])
        self.assertTrue(payload["candidates"])

        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as context_file:
            context_file.write("runtime fact source: engineering-assistant/workflow-orchestrator")
            context_file.flush()
            context_route = run_script(
                "route_skill.py",
                "--prompt",
                "继续推进任务 complete_identity_access_rbac_and_model_usage_policy_projection_before_rag_runtime",
                "--context",
                context_file.name,
            )
        self.assertEqual(0, context_route.returncode, context_route.stderr + context_route.stdout)
        context_payload = json.loads(context_route.stdout)
        self.assertEqual("waiting_for_input", context_payload["status"])
        self.assertIn("explicit-only", context_payload["reason"])

    def test_context_pack_uses_only_allowed_ai_platform_sources(self) -> None:
        fixture = json.loads((ROOT / "engineering-assistant" / "evals" / "fixtures" / "ai-platform-v1.json").read_text(encoding="utf-8"))
        canary_root = Path(fixture["root"])
        if not canary_root.exists():
            self.skipTest(f"external canary root is unavailable: {canary_root}")
        result = run_script(
            "recommend_context.py",
            "--root",
            fixture["root"],
            "--skill-id",
            "workflow-orchestrator",
            "--task-id",
            fixture["task_id"],
        )
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        source_paths = {item["path"] for item in payload["sources"]}
        self.assertIn("artifacts/workflow-orchestrator/artifact-index.json", source_paths)
        self.assertIn("artifacts/workflow-orchestrator/workflow-summary.md", source_paths)
        self.assertIn("artifacts/_control/architecture-baseline.json", source_paths)
        self.assertIn("Makefile", source_paths)
        self.assertTrue(all(not path.endswith((".html", ".png", ".jpg", ".jpeg")) for path in source_paths))
        self.assertTrue(any(path.endswith(".html") for path in payload["forbidden_sources"]))
        self.assertEqual([], payload["missing_required_sources"])

    def test_context_pack_blocks_missing_required_and_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "artifacts" / "workflow-orchestrator").mkdir(parents=True)
            (root / "artifacts" / "workflow-orchestrator" / "artifact-index.json").write_text(
                json.dumps({"stage_results": ["../outside.json"], "document_control_artifacts": [], "human_review_packets": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            (Path(temp_dir).parent / "outside.json").write_text("{}", encoding="utf-8")
            result = run_script("recommend_context.py", "--root", str(root), "--skill-id", "workflow-orchestrator", "--task-id", "missing")

        self.assertNotEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("block", payload["status"])
        self.assertIn("artifacts/workflow-orchestrator/workflow-summary.md", payload["missing_required_sources"])
        self.assertIn("../outside.json", payload["forbidden_sources"])

    def test_scored_eval_outputs_report_and_keeps_plugin_sync(self) -> None:
        result = run_script("run_skill_evals.py", "--mode", "scored")
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        report = json.loads((ROOT / "engineering-assistant" / "evals" / "reports" / "eval-report.json").read_text(encoding="utf-8"))
        self.assertEqual("pass", report["status"])
        for metric in ["route_accuracy", "distribution_surface_status", "control_plane_pass", "context_source_validity", "plugin_sync_status"]:
            self.assertEqual(1.0, report["metrics"][metric])
        self.assertIn("plugin-manifest-metadata", {check["id"] for check in report["checks"]})
        plugin_sync_checks = [check for check in report["checks"] if check["id"].startswith("plugin-sync-")]
        self.assertTrue(plugin_sync_checks)
        for check in plugin_sync_checks:
            self.assertIn("$EVAL_TEMP", check["right"])
            self.assertNotIn("/tmp/", check["right"])

        before = (ROOT / "engineering-assistant" / "evals" / "reports" / "eval-report.json").read_text(encoding="utf-8")
        readonly = run_script("run_skill_evals.py", "--mode", "scored", "--no-write-report")
        self.assertEqual(0, readonly.returncode, readonly.stderr + readonly.stdout)
        after = (ROOT / "engineering-assistant" / "evals" / "reports" / "eval-report.json").read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_policy_as_code_blocks_existing_risks(self) -> None:
        policy = ROOT / "engineering-assistant" / "runtime" / "codex" / "policies" / "tool-policy.yaml"
        self.assertTrue(policy.exists())
        data = json.loads(policy.read_text(encoding="utf-8"))
        self.assertIn("policies", data)

        hook = ROOT / "engineering-assistant" / "runtime" / "codex" / "hooks" / "pre_tool_use_policy.py"
        for command in [
            "rm -rf /tmp/bad",
            "git push origin main",
            "python3 - <<'PY'\nopen('plugins/teamwork-engineering-assistant/skills/x','w').write('bad')\nPY",
            "cp source plugins/teamwork-engineering-assistant/skills/x",
            "touch plugins/teamwork-engineering-assistant/skills/x",
        ]:
            result = subprocess.run(
                ["python3", str(hook)],
                input=json.dumps({"tool_input": {"command": command}}, ensure_ascii=False),
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("deny", json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"])

    def test_generated_runtime_assets_are_mirrored_to_plugin(self) -> None:
        plugin_root = publish_to_temp(self)
        for rel in [
            "engineering-assistant/runtime/compiled/skill-runtime-index.json",
            "engineering-assistant/evals/fixtures/ai-platform-v1.json",
            "engineering-assistant/schemas/skill-routing.schema.json",
            "engineering-assistant/schemas/context-pack.schema.json",
            "engineering-assistant/runtime/codex/policies/tool-policy.yaml",
        ]:
            self.assertTrue((ROOT / rel).exists(), f"missing source {rel}")
            self.assertTrue((plugin_root / rel).exists(), f"missing published plugin asset {rel}")
        self.assertTrue((plugin_root / ".codex-plugin" / "plugin.json").exists())

    def test_publish_plugin_supports_canonical_personal_marketplace_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            personal_root = Path(temp_dir) / "home"
            result = run_script("publish_plugin.py", "--layout", "personal", "--publish-root", str(personal_root))
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)

            plugin_root = personal_root / "plugins" / "teamwork-engineering-assistant"
            marketplace_path = personal_root / ".agents" / "plugins" / "marketplace.json"
            self.assertTrue((plugin_root / ".codex-plugin" / "plugin.json").exists())
            self.assertTrue((plugin_root / "skills").exists())
            self.assertTrue((plugin_root / "engineering-assistant").exists())
            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
            self.assertEqual("personal", marketplace["name"])
            self.assertEqual("Personal", marketplace["interface"]["displayName"])
            self.assertEqual("./plugins/teamwork-engineering-assistant", marketplace["plugins"][0]["source"]["path"])
            payload = json.loads(result.stdout)
            self.assertEqual("personal", payload["layout"])
            self.assertEqual(str(marketplace_path.resolve()), payload["marketplace_path"])


if __name__ == "__main__":
    unittest.main()
