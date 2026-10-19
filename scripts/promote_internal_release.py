"""Controlled internal release promotion; generated Git trees stay outside author branches."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from engineering_assistant.tools.internal_promotion import promote
from engineering_assistant.runtime.validation import ValidationFailure


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="先 prepare 两个不可变 tag，再凭固定命令及 BUILD 验收发布团队试用 Release 和公开验收摘要，并激活 installer alias。")
    parser.add_argument("--phase", choices=("prepare", "activate"), default="prepare")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--activation", type=Path, help="activate 专用的固定命令与 BUILD 更新验收。")
    parser.add_argument("--release-notes", type=Path, help="activate 专用的已验收 UTF-8 安装教程。")
    parser.add_argument("--expected-alias", help="activate 预期旧源码 commit；首次使用 absent。")
    confirmation = parser.add_mutually_exclusive_group()
    confirmation.add_argument("--dry-run", action="store_true", help="默认模式；不修改远程 ref。")
    confirmation.add_argument("--yes", action="store_true", help="明确授权执行当前 phase 的远程写入。")
    args = parser.parse_args(argv)
    try:
        result = promote(args.candidate, args.acceptance, phase=args.phase, activation=args.activation,
                         release_notes=args.release_notes, expected_alias=args.expected_alias, execute=args.yes)
    except ValidationFailure as error:
        result = {"status": "failed", "reason": str(error)}
    except Exception:
        result = {"status": "failed", "reason": "内部发行输入或执行状态无效；推广未能完成"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"ready_for_prepare", "ready_for_activate", "prepared", "promoted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
