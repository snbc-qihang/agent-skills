#!/usr/bin/env python3
"""Validate Engineering Assistant overlay and record-file growth budgets."""

from pathlib import Path
import sys

ROOT = Path("/Users/fengtianyangyang/.codex/skills/engineering-assistant-overlay")
UPGRADE_SUMMARY = Path(
    "/Users/fengtianyangyang/.codex/run-artifacts/engineering-assistant/"
    "assistant-problem-intake/20260703-overlay-upgrade/upgrade-summary.md"
)

BUDGETS = {
    "SKILL.md": (500, 650),
    "upgrade-summary.md": (220, 400),
}


def line_count(path):
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())


def main():
    checks = [
        ("SKILL.md", ROOT / "SKILL.md"),
        ("upgrade-summary.md", UPGRADE_SUMMARY),
    ]
    failed = []
    for label, path in checks:
        soft, hard = BUDGETS[label]
        count = line_count(path)
        if count > hard:
            failed.append(f"{label} lines={count} hard={hard}")
        elif count > soft:
            print(f"OVERLAY_GROWTH_SOFT_BUDGET_WARN {label} lines={count} soft={soft}")
        else:
            print(f"OVERLAY_GROWTH_BUDGET_OK {label} lines={count} soft={soft} hard={hard}")

    if failed:
        print("OVERLAY_SIZE_BUDGET_EXCEEDED", file=sys.stderr)
        for item in failed:
            print(item, file=sys.stderr)
        return 1
    print("VALID_OVERLAY_GROWTH_BUDGET")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
