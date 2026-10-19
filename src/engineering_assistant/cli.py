"""Stable CLI entrypoint: runtime by default, author tools only on demand."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .runtime import cli as runtime_cli

AUTHOR_COMMANDS = frozenset(('build', 'canary-assemble', 'canary-audit', 'canary-prepare', 'canary-validate', 'eval', 'validate', 'verify-package', 'verify-sources'))


def build_parser():
    if (Path(__file__).parent / "tools/cli.py").is_file():
        from .tools.cli import build_parser as author_parser
        return author_parser()
    return runtime_cli.build_parser()


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    prefix = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    prefix.add_argument("--repository-root")
    prefix.add_argument("--profile")
    prefix.add_argument("--allow-author-repository", action="store_true")
    _, remaining = prefix.parse_known_args(arguments)
    command = remaining[0] if remaining else None
    if command in AUTHOR_COMMANDS:
        if not (Path(__file__).parent / "tools/cli.py").is_file():
            runtime_cli._emit({"status": "failed", "error": "author_environment_required",
                               "message": "此命令属于作者工具，请在仓库开发环境执行。"})
            return 2
        from .tools.cli import main as author_main
        return author_main(arguments)
    if command in {"--help", "-h"}:
        build_parser().parse_args(arguments)
    return runtime_cli.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
