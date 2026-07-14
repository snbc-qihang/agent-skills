#!/usr/bin/env python3
"""Print the canonical identity-stripped proposal-audit synthesis input."""

import json
import sys
from pathlib import Path

from validate_council_run import anonymous_projection, canonical_json, validate_identity_projection


def main():
    if len(sys.argv) != 2:
        print("usage: project_anonymous_review.py council-member-outputs.json", file=sys.stderr)
        return 1
    try:
        outputs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"INVALID_COUNCIL_MEMBER_OUTPUTS: {error}", file=sys.stderr)
        return 1
    projection = anonymous_projection(outputs)
    try:
        validate_identity_projection(outputs, projection)
    except ValueError as error:
        print(f"INVALID_COUNCIL_ANONYMITY: {error}", file=sys.stderr)
        return 1
    print(canonical_json(projection))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
