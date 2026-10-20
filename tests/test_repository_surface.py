from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.runtime.catalog import load_catalog  # noqa: E402
from engineering_assistant.tools.compiler import build_package  # noqa: E402


HAN = re.compile(r"[\u4e00-\u9fff]")


class RepositorySurfaceTests(unittest.TestCase):
    def test_public_ci_keeps_readonly_permissions_and_does_not_persist_credentials(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("pull_request_target:", workflow)
        self.assertNotRegex(workflow, r"(?:contents|permissions):\s*(?:write|write-all)")
        self.assertEqual(workflow.count("uses: actions/checkout@"), workflow.count("persist-credentials: false"))

    def test_ci_job_environment_uses_only_available_github_contexts(self) -> None:
        # GitHub's Context availability contract excludes runner at job env:
        # https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability
        allowed = {"github", "needs", "strategy", "matrix", "vars", "secrets", "inputs"}
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        environments = re.findall(r"^    env:\n((?:      [^\n]*\n)+)", workflow, flags=re.MULTILINE)
        self.assertTrue(environments)
        for environment in environments:
            used = set(re.findall(r"\$\{\{\s*([a-zA-Z_][\w]*)\.", environment))
            self.assertLessEqual(used, allowed, "job env is evaluated before a Runner is available")

    def test_ci_initializes_isolated_directories_on_runner_before_tools(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        step = re.search(r"      - name: 初始化隔离运行目录\n        run: \|\n(.*?)\n      - name:",
                         workflow, flags=re.DOTALL)
        self.assertIsNotNone(step, "Runner-dependent directories need an execution step")
        source = re.search(r"python - <<'PY'\n(.*?)\n          PY", step.group(1), flags=re.DOTALL)
        self.assertIsNotNone(source)
        self.assertLess(step.start(), workflow.index("      - name: 准备固定开发工具"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            command_file = root / "github-env"
            for target in ("macos-arm64", "linux-x64", "windows-x64"):
                with mock.patch.dict(os.environ, {"RUNNER_TEMP": str(root), "GITHUB_ENV": str(command_file),
                                                   "EA_CI_TARGET": target}, clear=True):
                    exec(compile(textwrap.dedent(source.group(1)), "<CI directory initialization>", "exec"), {})
                values = dict(line.split("=", 1) for line in command_file.read_text(encoding="utf-8").splitlines())
                self.assertEqual(values, {
                    "ENGINEERING_ASSISTANT_VALIDATOR_CACHE_DIR": str(root / "ea-official-validators"),
                    "UV_CACHE_DIR": str(root / "ea-uv-cache"),
                    "CLAUDE_CONFIG_DIR": str(root / "ea-claude-config"),
                    "EA_CI_ROOT": str(root / "ea-ci" / target),
                })
                self.assertTrue(all(Path(value).is_dir() for value in values.values()))
                command_file.unlink()

    def test_ci_bootstraps_pinned_official_validators_for_clean_runner(self) -> None:
        from engineering_assistant.tools.official_validation import OFFICIAL_VALIDATORS

        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main, teamwork]", workflow)
        self.assertIn("validate_with_official_tools", workflow)
        self.assertIn("uv==0.11.7", workflow)
        self.assertNotIn("$HOME/.codex", workflow)
        self.assertNotIn("sha256sum", workflow)
        self.assertEqual(
            "6cc9dc3199c935916cf6f73fcbbbb0e3bb1b58c8f5109fefa499978908164f51",
            OFFICIAL_VALIDATORS["quick_validate"]["sha256"],
        )
        self.assertEqual(
            "ebda00d55d7518b127f675f062fb5c6e7a1ffdc0a99df1a55ac594400d7d3228",
            OFFICIAL_VALIDATORS["plugin_validate"]["sha256"],
        )

    def test_ci_runs_each_native_target_with_fixed_tools_and_runtime_qualification(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for runner, target in {
            "macos-14": "macos-arm64",
            "windows-2025": "windows-x64",
        }.items():
            self.assertRegex(workflow, rf"- runner: {re.escape(runner)}\n\s+target: {target}\n")
        for contract in (
            'python-version: "3.13.13"', 'RUSTUP_TOOLCHAIN: "1.90.0"',
            'ENGINEERING_ASSISTANT_REQUIRE_PROVIDER_SANDBOX: "1"',
            'fail-fast: false', 'scripts/qualify_installation.py',
            'Windows Server', 'agent_host_qualification', 'not_run',
        ):
            self.assertIn(contract, workflow)
        self.assertNotIn("continue-on-error", workflow)

    def test_windows_ci_uses_the_consumer_download_contract_before_developer_install(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        step = re.search(r"      - name: 使用消费者相同的固定 Windows Python\n.*?python - <<'PY'\n(.*?)\n          PY",
                         workflow, flags=re.DOTALL)
        self.assertIsNotNone(step)
        self.assertLess(step.start(), workflow.index("      - name: 安装开发包"))
        key = "cpython-3.13.13-windows-x86_64-none"
        entry = json.loads((ROOT / "config/runtime-python-downloads.json").read_text())[key]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            base = root / "consumer-python" / key
            base.mkdir(parents=True)
            (base / "BUILD").write_text(entry["build"])
            (base / "python.exe").write_bytes(b"fixture; never executed")
            command_file = root / "github-path"
            with mock.patch.dict(os.environ, {"EA_CI_ROOT": str(root), "GITHUB_PATH": str(command_file),
                    "UV_CACHE_DIR": str(root / "cache"), "UV_INDEX_URL": "untrusted-fixture"}, clear=True), \
                 mock.patch("subprocess.run") as run:
                exec(compile(textwrap.dedent(step.group(1)), "<CI consumer Python>", "exec"), {})
            command = run.call_args.args[0]
            self.assertEqual([sys.executable, "-m", "uv", "--no-config", "python", "install", key], command)
            environment = run.call_args.kwargs["env"]
            self.assertNotIn("UV_INDEX_URL", environment)
            self.assertEqual(entry["build"], environment["UV_PYTHON_CPYTHON_BUILD"])
            self.assertEqual("0", environment["UV_PYTHON_INSTALL_REGISTRY"])
            self.assertEqual([str(base), str(base / "Scripts")], command_file.read_text().splitlines())

    def test_ci_native_gate_rejects_skips_missing_tests_and_failures(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        functions = []
        for block in re.findall(r"python - <<'PY'\n(.*?)\n          PY", workflow, flags=re.DOTALL):
            module = ast.parse(textwrap.dedent(block))
            functions.extend(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "require_native_test_results")
        self.assertEqual(1, len(functions), "CI must mechanically reject unexecuted native safety tests")
        namespace = {}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROOT / ".github/workflows/ci.yml"), "exec"), namespace)
        gate = namespace["require_native_test_results"]
        required = {"test.native.contract"}
        native = SimpleNamespace(id=lambda: "test.native.contract")
        foreign = SimpleNamespace(id=lambda: "test.other_os.contract")
        for result, observed in (
            (SimpleNamespace(skipped=[(native, "unsupported")], wasSuccessful=lambda: True), required),
            (SimpleNamespace(skipped=[], wasSuccessful=lambda: True), set()),
            (SimpleNamespace(skipped=[], wasSuccessful=lambda: False), required),
        ):
            with self.assertRaises(SystemExit):
                gate(result, required, observed)
        self.assertIsNone(gate(SimpleNamespace(skipped=[(foreign, "other OS")], wasSuccessful=lambda: True), required, required))

    def test_repository_contains_only_current_product_surfaces(self) -> None:
        catalog = load_catalog(ROOT, require_sources=True)
        absent = [
            "generator",
            "engineering-assistant",
            "effectiveness-evals",
            "artifacts",
            ".agent",
            "v4",
            "docs/migration",
            "docs/decisions",
            "docs/research",
            "src/engineering_assistant/migration.py",
            "src/engineering_assistant/publisher.py",
        ]
        for relative in absent:
            self.assertFalse((ROOT / relative).exists(), relative)

        self.assertEqual(
            set(catalog.skills),
            {path.name for path in (ROOT / "skills").iterdir() if path.is_dir()},
        )
        self.assertEqual(
            {pack.source_path for pack in catalog.packs.values()},
            {path.relative_to(ROOT).as_posix() for path in (ROOT / "packs").glob("*.md")},
        )
        self.assertEqual([ROOT / ".github/workflows/ci.yml"], list((ROOT / ".github/workflows").glob("*.yml")))

    def test_active_sources_have_no_upgrade_process_dependencies(self) -> None:
        active_files = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "VERSIONING.md"]
        for base in [ROOT / "catalog", ROOT / "config", ROOT / "src", ROOT / "scripts", ROOT / ".github"]:
            active_files.extend(
                path
                for path in base.rglob("*")
                if path.is_file() and path.suffix in {".md", ".json", ".py", ".yml", ".yaml", ".toml"}
            )
        corpus = "\n".join(path.read_text(encoding="utf-8") for path in active_files)
        forbidden = [
            "docs/migration",
            "legacy-skills.json",
            "validate_legacy_migration",
            "HISTORICAL_V3_MAPPING",
            "402fe0625e449eff5080e0af20eb8caf77fe82be",
            "implementation-backlog",
            "decision-matrix",
        ]
        for marker in forbidden:
            self.assertNotIn(marker, corpus, marker)

    def test_public_skills_and_packs_are_simplified_chinese(self) -> None:
        catalog = load_catalog(ROOT, require_sources=True)
        for skill in catalog.skills.values():
            self.assertRegex(skill.description or "", HAN, skill.id)
            source = ROOT / skill.source_path / "SKILL.md"
            text = source.read_text(encoding="utf-8")
            self.assertRegex(text, HAN, source)
            self.assertIn(f"description: {skill.description}", text)
        for pack in catalog.packs.values():
            self.assertRegex((ROOT / pack.source_path).read_text(encoding="utf-8"), HAN, pack.id)

    def test_platform_metadata_uses_the_configured_developer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            hermes = root / "hermes"
            build_package(ROOT, "codex", codex)
            build_package(ROOT, "hermes", hermes)
            manifest = json.loads((codex / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
            self.assertEqual("sunliming625@gmail.com", manifest["author"]["email"])
            self.assertEqual("sunliming625@gmail.com", manifest["interface"]["developerName"])
            self.assertIn('author: "sunliming625@gmail.com"', (hermes / "plugin.yaml").read_text(encoding="utf-8"))

        cases = json.loads((ROOT / "evals/routing/cases.json").read_text(encoding="utf-8"))
        languages = {item["language"] for group in cases["groups"] for item in group["requests"]}
        self.assertEqual({"zh-CN", "en"}, languages)


if __name__ == "__main__":
    unittest.main()
