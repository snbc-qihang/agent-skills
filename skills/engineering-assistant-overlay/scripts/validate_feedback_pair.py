#!/usr/bin/env python3
"""Validate that a run has a mutually consistent feedback/closed-loop pair."""

import json
import subprocess
import sys
from pathlib import Path


def fail(code, detail):
    print(f"{code}: {detail}", file=sys.stderr)
    return 1


def main():
    if len(sys.argv) != 2:
        return fail("INVALID_ASSISTANT_FEEDBACK_PAIR", "usage: validate_feedback_pair.py artifact-root")
    root = Path(sys.argv[1])
    feedback = root / "assistant-run-feedback.json"
    closed_loop = root / "closed-loop-outcome.json"
    if not feedback.exists():
        return fail("ASSISTANT_FEEDBACK_NOT_GENERATED", str(feedback))
    if not closed_loop.exists():
        return fail("CLOSED_LOOP_OUTCOME_NOT_RECORDED", str(closed_loop))

    scripts = Path(__file__).parent
    checks = [
        [sys.executable, str(scripts / "validate_assistant_run_feedback.py"), str(feedback)],
        [sys.executable, str(scripts / "validate_closed_loop_outcome.py"), str(closed_loop)],
    ]
    for command in checks:
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode:
            sys.stderr.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            return fail("INVALID_ASSISTANT_FEEDBACK_PAIR", "schema validation failed")

    feedback_data = json.loads(feedback.read_text())
    closed_data = json.loads(closed_loop.read_text())
    if feedback_data.get("run_id") != closed_data.get("run_id"):
        return fail("INVALID_ASSISTANT_FEEDBACK_PAIR", "run_id mismatch")
    if feedback_data.get("overall_status") != closed_data.get("execution_feedback", {}).get("overall_status"):
        return fail("INVALID_ASSISTANT_FEEDBACK_PAIR", "overall_status mismatch")
    required = set(closed_data.get("next_run_context", {}).get("must_consume_artifacts", []))
    if str(feedback) not in required or str(closed_loop) not in required:
        return fail("NEXT_RUN_FEEDBACK_NOT_CONSUMED", "next_run_context does not require both pair members")

    print("VALID_ASSISTANT_FEEDBACK_PAIR")
    print(f"run_id={feedback_data['run_id']}")
    print(f"overall_status={feedback_data['overall_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
