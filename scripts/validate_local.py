"""Collect native validation without a hosted CI identity or remote writes."""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.artifact_io import ArtifactIO, artifact_fs
from engineering_assistant.catalog import load_catalog
from engineering_assistant.compiler import build_package, verify_package
from engineering_assistant.eval_runner import run_evals
from engineering_assistant.installation import PYTHON_VERSION, _protocol_run, _uv
from engineering_assistant.native_launcher import host_target
from engineering_assistant.official_validation import validate_with_official_tools
from engineering_assistant.provider_runtime import ProviderExecutor
from engineering_assistant.release_assets import (
    INTERNAL_REPOSITORY, INTERNAL_TARGETS, _record, _safe_root,
    release_provenance, required_native_tests,
)
from engineering_assistant.validation import ValidationFailure
from qualify_installation import qualify
from verify_setup_wheel import _output_directory, _verify_wheel


def _git(*arguments: str) -> str:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1", GIT_OPTIONAL_LOCKS="0")
    try:
        return _protocol_run(["git", "-c", "core.fsmonitor=false", *arguments], cwd=ROOT,
                             environment=environment, timeout=60).decode("utf-8").strip()
    except Exception:
        raise ValidationFailure("本地源码 Git 检查失败：" + arguments[0]) from None


def _source_identity() -> str:
    source = _git("rev-parse", "HEAD")
    if _git("status", "--porcelain=v1", "--untracked-files=normal"):
        raise ValidationFailure("发行验证拒绝未提交或未跟踪源码；先完成源码评审与提交")
    if _git("remote", "get-url", "origin") not in {
        "https://github.com/" + INTERNAL_REPOSITORY + ".git",
        "https://github.com/" + INTERNAL_REPOSITORY,
        "git@github.com:" + INTERNAL_REPOSITORY + ".git",
    }:
        raise ValidationFailure("发行验证必须来自固定团队仓库")
    if Path(_git("rev-parse", "--show-toplevel")).resolve() != ROOT:
        raise ValidationFailure("发行验证必须从作者源 Git 根目录执行")
    return source


def initialize(output: Path) -> dict:
    source = _source_identity()
    origin = {"kind": "local", "repository": INTERNAL_REPOSITORY,
              "validation_id": str(uuid.uuid4()), "assurance": "local_unattested"}
    release_provenance(source, validation_origin=origin)
    report = {"source_commit": source, "validation_origin": origin}
    storage = _output_directory(output)
    try:
        storage.create_immutable_json(report, output.name)
    finally:
        storage.close()
    return report


def _native_tests(target: str) -> dict:
    sys.path.insert(0, str(ROOT / "tests"))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    def identifiers(test):
        if isinstance(test, unittest.TestSuite):
            return set().union(*(identifiers(child) for child in test))
        return {test.id()}
    discovered = identifiers(suite)
    required = required_native_tests(target)
    if not required <= discovered:
        raise ValidationFailure("原生必需测试未被发现")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or any(test.id() in required for test, _ in result.skipped):
        raise ValidationFailure("原生测试失败或必需用例被跳过")
    capability = ProviderExecutor.sandbox_capability()
    if capability.get("supported") is not True:
        raise ValidationFailure("当前宿主不支持完整 Provider 隔离")
    return {"target": target, "test_count": result.testsRun, "native_tests": sorted(required),
            "required_native_skips": 0, "provider_capability": capability, "agent_host_qualification": "not_run"}


def run(origin_path: Path, output: Path) -> dict:
    origin_path, output = origin_path.absolute(), output.absolute()
    origin_io = _safe_root(origin_path.parent)
    try:
        batch, _ = _record(origin_io, origin_path.name)
    finally:
        origin_io.close()
    if set(batch) != {"source_commit", "validation_origin"}:
        raise ValidationFailure("本地批次只能包含源码和 validation_origin")
    release_provenance(batch["source_commit"], validation_origin=batch["validation_origin"])
    source = _source_identity()
    if source != batch["source_commit"]:
        raise ValidationFailure("本地批次与当前源码 commit 不一致")
    target = host_target()
    if target not in INTERNAL_TARGETS or platform.python_version() != PYTHON_VERSION:
        raise ValidationFailure("请在三个原生目标之一使用固定 Python " + PYTHON_VERSION)
    parent = _output_directory(output)
    try:
        path, descriptor, identity = parent.create_directory_exclusive_open(output.name)
        try:
            storage = ArtifactIO.from_open_directory_fd(path, descriptor)
        finally:
            artifact_fs.close(descriptor)
        try:
            previous = os.environ.get("ENGINEERING_ASSISTANT_REQUIRE_PROVIDER_SANDBOX")
            os.environ["ENGINEERING_ASSISTANT_REQUIRE_PROVIDER_SANDBOX"] = "1"
            try:
                print("执行完整单元测试与原生必需测试：" + target, file=sys.stderr, flush=True)
                reports = {"native-tests.json": _native_tests(target)}
                print("校验作者源、eval、Codex/Hermes 构建及官方格式。", file=sys.stderr, flush=True)
                load_catalog(ROOT, require_sources=True)
                evaluation = run_evals(ROOT)
                storage.create_immutable_json(evaluation, "eval.json")
                for agent in ("codex", "hermes"):
                    build_package(ROOT, agent, output / agent, target=target)
                    verify_package(output / agent)
                reports["official-validation.json"] = validate_with_official_tools(ROOT, output / "codex")
                print("验证真实 Runtime、MCP、Hook、持久化与 Provider 隔离。", file=sys.stderr, flush=True)
                with tempfile.TemporaryDirectory(prefix="ea-local-runtime-") as temporary:
                    reports["runtime-qualification.json"] = qualify(Path(temporary).resolve(), ("codex",))
                storage.ensure_directory("setup")
                print("构建并隔离安装 setup wheel。", file=sys.stderr, flush=True)
                _protocol_run([str(_uv(None)), "build", "--wheel", "--out-dir", str(output / "setup"), str(ROOT)],
                              cwd=ROOT, environment=dict(os.environ), timeout=120)
                wheels = list((output / "setup").glob("*.whl"))
                if len(wheels) != 1:
                    raise ValidationFailure("必须构建唯一 setup wheel")
                reports["setup/wheel-verification.json"] = _verify_wheel(wheels[0])
                print("执行 Codex 无副作用发布预演。", file=sys.stderr, flush=True)
                _protocol_run([sys.executable, "scripts/publish_local.py", "--platform", "codex", "--dry-run"],
                              cwd=ROOT, environment=dict(os.environ), timeout=600)
            finally:
                if previous is None:
                    os.environ.pop("ENGINEERING_ASSISTANT_REQUIRE_PROVIDER_SANDBOX", None)
                else:
                    os.environ["ENGINEERING_ASSISTANT_REQUIRE_PROVIDER_SANDBOX"] = previous
            if _source_identity() != source or not parent.child_directory_matches(output.name, identity):
                raise ValidationFailure("验证期间源码或输出目录发生变化；本次记录不能用于发行")
            reports["host.json"] = {"target": target, "os": platform.platform(), "python": platform.python_version(),
                "agent_host_qualification": "not_run", "windows11_qualification": "not_run" if target == "windows-x64" else "not_applicable"}
            for name, report in reports.items():
                storage.create_immutable_json({**report, **batch}, *name.split("/"))
            return {"status": "passed", "target": target, **batch, "output": str(output),
                    "native_agent_sessions": "not_verified"}
        finally:
            storage.close()
    finally:
        parent.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地原生发行验证；不注册插件、不推送、不替代真实宿主验收。")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="为干净的已提交源码生成一次验证批次").add_argument("--output", type=Path, required=True)
    selected = commands.add_parser("run", help="在当前目标执行完整验证并生成绑定记录")
    selected.add_argument("--origin", type=Path, required=True)
    selected.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        result = initialize(arguments.output) if arguments.command == "init" else run(arguments.origin, arguments.output)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error": type(error).__name__, "message": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
