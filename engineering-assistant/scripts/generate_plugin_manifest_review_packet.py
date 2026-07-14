#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

PLACEHOLDER_PATHS = [
    "author.email",
    "author.url",
    "homepage",
    "repository",
    "interface.websiteURL",
    "interface.privacyPolicyURL",
    "interface.termsOfServiceURL",
]


def get_path(data, dotted):
    current = data
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a human review packet for Engineering Assistant plugin manifest metadata.")
    parser.add_argument("--plugin-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    plugin_root = Path(args.plugin_root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = plugin_root / "engineering-assistant/plugin/plugin.json"
    validator = plugin_root / "engineering-assistant/scripts/validate_plugin_manifest.py"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = []
    for dotted in PLACEHOLDER_PATHS:
        value = get_path(manifest, dotted)
        if value is None or "example." in str(value) or str(value).endswith("@example.com"):
            missing.append({"path": dotted, "value": value, "action": "replace_before_external_distribution"})

    proc = subprocess.run([sys.executable, str(validator)], cwd=str(plugin_root), text=True, capture_output=True)
    validator_payload = {}
    try:
        validator_payload = json.loads(proc.stdout or proc.stderr or "{}")
    except json.JSONDecodeError:
        validator_payload = {"status": "unknown", "stdout": proc.stdout, "stderr": proc.stderr}

    status = "waiting_for_human_review" if missing or validator_payload.get("status") == "waiting_for_human_review" else "pass"
    (out / "missing-manifest-metadata.json").write_text(json.dumps({"status": status, "missing": missing}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "manifest-review-index.json").write_text(json.dumps({
        "status": status,
        "manifest": str(manifest_path),
        "validator_status": validator_payload.get("status"),
        "missing_metadata_path": "missing-manifest-metadata.json",
        "human_review_packet": "manifest-human-review-packet.md"
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Plugin Manifest Human Review Packet",
        "",
        f"Status: `{status}`",
        "",
        "## Manifest",
        "",
        f"- Path: `{manifest_path}`",
        f"- Name: `{manifest.get('name')}`",
        f"- Version: `{manifest.get('version')}`",
        "",
        "## Metadata requiring review",
        "",
    ]
    if missing:
        for item in missing:
            lines.append(f"- `{item['path']}`: `{item['value']}` -> {item['action']}")
    else:
        lines.append("- None")
    lines.extend(["", "## Validator result", "", "```json", json.dumps(validator_payload, ensure_ascii=False, indent=2), "```", ""])
    (out / "manifest-human-review-packet.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": status, "out": str(out), "missing": len(missing)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
