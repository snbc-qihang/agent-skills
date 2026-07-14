#!/usr/bin/env python3
"""Summarize L4 evidence classifications into cleanup buckets."""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import classify_l4_evidence


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reason_key(reason):
    if reason.startswith("missing files:"):
        return "missing_required_files"
    if reason.startswith("overall_status="):
        return "failed_or_blocked_status"
    if "non-standard route" in reason or "legacy route type" in reason:
        return "non_standard_or_legacy_route"
    if "capability" in reason:
        return "capability_evidence_gap"
    if "change run missing" in reason:
        return "change_evidence_gap"
    return "other"


def classify_all(root):
    results = []
    for feedback in sorted(root.rglob("assistant-run-feedback.json")):
        run_root = feedback.parent
        label, reasons = classify_l4_evidence.classify(run_root)
        results.append({
            "root": str(run_root),
            "classification": label,
            "reasons": reasons,
            "reason_keys": sorted({reason_key(reason) for reason in reasons}),
        })
    return results


def markdown_summary(summary, samples_by_classification):
    lines = [
        "# L4 Evidence Cleanup Summary",
        "",
        f"Generated at: `{summary['generated_at']}`",
        f"Root: `{summary['root']}`",
        "",
        "## Counts",
        "",
    ]
    for label, count in summary["counts"].items():
        lines.append(f"- `{label}`: {count}")
    lines.extend([
        "",
        "## Cleanup Buckets",
        "",
    ])
    for key, count in summary["reason_key_counts"].items():
        lines.append(f"- `{key}`: {count}")
    lines.extend([
        "",
        "## Policy",
        "",
        "- Only `strict_l4` may count as strict L4 maturity evidence.",
        "- `weak` items need missing artifact recovery or exclusion as historical incomplete runs.",
        "- `failed_or_blocked` items may be useful failure samples but must not count as maturity evidence.",
        "- `partial` items need route normalization, capability evidence, or change evidence repair before promotion.",
        "",
        "## Sample Index",
        "",
    ])
    for label, samples in samples_by_classification.items():
        lines.append(f"### {label}")
        if not samples:
            lines.append("")
            lines.append("No samples.")
            lines.append("")
            continue
        for item in samples[:10]:
            reason_text = "; ".join(item["reasons"]) if item["reasons"] else "no reason"
            lines.append(f"- `{item['root']}`: {reason_text}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Summarize L4 evidence cleanup work.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sample-limit", type=int, default=25)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    results = classify_all(root)
    counts = Counter(item["classification"] for item in results)
    reason_counts = Counter()
    samples_by_classification = defaultdict(list)
    for item in results:
        samples_by_classification[item["classification"]].append(item)
        for key in item["reason_keys"]:
            reason_counts[key] += 1

    ordered_labels = ["strict_l4", "partial", "weak", "failed_or_blocked", "not_evidence"]
    summary = {
        "generated_at": now_iso(),
        "root": str(root),
        "total": len(results),
        "counts": {label: counts.get(label, 0) for label in ordered_labels},
        "reason_key_counts": dict(sorted(reason_counts.items())),
        "strict_l4_maturity_claim_allowed": counts.get("strict_l4", 0) == len(results) and bool(results),
    }
    sample_index = {
        label: samples_by_classification.get(label, [])[:args.sample_limit]
        for label in ordered_labels
    }

    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "l4-evidence-summary.json", summary)
    write_json(out / "l4-evidence-sample-index.json", sample_index)
    (out / "l4-evidence-cleanup-plan.md").write_text(
        markdown_summary(summary, sample_index),
        encoding="utf-8",
    )
    print(json.dumps({"status": "generated", "out": str(out), "total": len(results), "counts": summary["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
