"""Combine native local or CI records and a verified setup wheel."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.installation import TARGETS
from engineering_assistant.release_assets import INTERNAL_AGENTS, INTERNAL_TARGETS, INTERNAL_REPOSITORY, assemble_release
from engineering_assistant.artifact_io import ArtifactIO
from engineering_assistant.validation import ValidationFailure


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核验本地或 CI 原生输入并组装候选发行包，不执行远程发布。")
    for target in TARGETS:
        parser.add_argument("--" + target, type=Path, dest=target.replace("-", "_"))
    parser.add_argument("--agent", action="append", choices=("codex", "hermes", "claude-code"))
    parser.add_argument("--target", action="append", choices=TARGETS)
    parser.add_argument("--source-commit", help="CI 输入的源码 commit；本地输入从批次文件读取。")
    parser.add_argument("--ci-run-id")
    parser.add_argument("--ci-run-attempt", type=int)
    parser.add_argument("--validation-origin", type=Path, help="validate_local.py init 生成的本地批次文件。")
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.validation_origin is not None:
            if any(value is not None for value in (arguments.source_commit, arguments.ci_run_id, arguments.ci_run_attempt)):
                raise ValidationFailure("本地批次不能混用 CI 参数")
            path = arguments.validation_origin.absolute()
            storage = ArtifactIO(path.parent, ".")
            try:
                provenance, _ = storage.read_json_limited(1_048_576, path.name)
            finally:
                storage.close()
            if not isinstance(provenance, dict) or set(provenance) != {"source_commit", "validation_origin"}:
                raise ValidationFailure("本地验证批次格式无效")
        else:
            provenance = {"source_commit": arguments.source_commit, "ci_identity": {
                "repository": INTERNAL_REPOSITORY, "run_id": arguments.ci_run_id, "run_attempt": arguments.ci_run_attempt}}
        result = assemble_release({target: getattr(arguments, target.replace("-", "_")) for target in TARGETS
                                   if getattr(arguments, target.replace("-", "_")) is not None},
                                  arguments.wheel, arguments.output,
                                  agents=tuple(arguments.agent or INTERNAL_AGENTS), targets=tuple(arguments.target or INTERNAL_TARGETS),
                                  **provenance)
        print(json.dumps({"status": result["status"], "canonical_version": result["canonical_version"],
                          "support_qualification": result["support_qualification"]["status"],
                          "index": str(arguments.output / "release-index.json")}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
