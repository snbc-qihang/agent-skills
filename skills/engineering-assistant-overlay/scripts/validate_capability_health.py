#!/usr/bin/env python3
"""Validate capability-health.json."""

import json
import sys
from pathlib import Path

VALID_AVAILABILITY = {"available", "unavailable", "partial", "unknown"}
VALID_INDEX_STATUS = {"current", "stale", "missing", "unknown", "not_applicable"}
VALID_CONFIDENCE = {"high", "medium", "low", "pending"}


def fail(message):
    print(f"INVALID_CAPABILITY_HEALTH: {message}", file=sys.stderr)
    return 1


def main():
    if len(sys.argv) != 2:
        return fail("usage: validate_capability_health.py capability-health.json")
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not data.get("run_id"):
        return fail("run_id required")
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        return fail("capabilities must be non-empty")
    for index, item in enumerate(capabilities):
        for key in ["capability", "availability", "confidence", "fallback"]:
            if key not in item:
                return fail(f"capability {index} missing {key}")
        if item["availability"] not in VALID_AVAILABILITY:
            return fail(f"capability {index} invalid availability")
        if item.get("index_status", "not_applicable") not in VALID_INDEX_STATUS:
            return fail(f"capability {index} invalid index_status")
        if item["confidence"] not in VALID_CONFIDENCE:
            return fail(f"capability {index} invalid confidence")
        if item["availability"] in {"unavailable", "partial"} and not item.get("allowed_skip_reason"):
            return fail(f"capability {index} unavailable/partial requires allowed_skip_reason")
    print("VALID_CAPABILITY_HEALTH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
