#!/usr/bin/env python3
"""Validate called capability outputs are consumed by downstream stages."""

import json
import sys
from pathlib import Path


def fail(message):
    print(f"INVALID_CAPABILITY_OUTPUT_CONSUMPTION: {message}", file=sys.stderr)
    return 1


def main():
    if len(sys.argv) != 3:
        return fail("usage: validate_capability_output_consumption.py capability-invocation-ledger.json capability-output-consumption.json")
    ledger = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    consumption = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    invocations = ledger.get("invocations", ledger if isinstance(ledger, list) else [])
    consumptions = consumption.get("consumptions", [])
    if not isinstance(consumptions, list):
        return fail("consumptions must be list")
    consumed = {(item.get("capability"), item.get("source_artifact")) for item in consumptions}
    for index, item in enumerate(consumptions):
        for key in ["capability", "source_artifact", "consumed_by_phase", "consumed_by_artifact", "consumption_effect"]:
            if not item.get(key):
                return fail(f"consumption {index} missing {key}")
    for item in invocations:
        if item.get("invocation_status") != "called":
            continue
        capability = item.get("capability")
        artifacts = item.get("output_artifacts", [])
        if not artifacts and not item.get("no_artifact_rationale"):
            return fail(f"called capability has no recorded output: {capability}")
        for artifact in artifacts:
            if (capability, artifact) not in consumed:
                return fail(f"called output not consumed: {capability} -> {artifact}")
    print("VALID_CAPABILITY_OUTPUT_CONSUMPTION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
