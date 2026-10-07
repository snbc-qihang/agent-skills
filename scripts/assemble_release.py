"""Combine four native CI artifact roots and one existing setup wheel."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.installation import TARGETS
from engineering_assistant.release_assets import assemble_release


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读核验原生 CI 输入并组装候选发行包，不执行远程发布。")
    for target in TARGETS:
        parser.add_argument("--" + target, type=Path, required=True, dest=target.replace("-", "_"))
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        result = assemble_release({target: getattr(arguments, target.replace("-", "_")) for target in TARGETS},
                                  arguments.wheel, arguments.output)
        print(json.dumps({"status": result["status"], "canonical_version": result["canonical_version"],
                          "support_qualification": result["support_qualification"]["status"],
                          "index": str(arguments.output / "release-index.json")}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
