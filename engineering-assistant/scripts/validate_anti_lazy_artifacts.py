#!/usr/bin/env python3
"""Validate anti-lazy artifacts for engineering-assistant code changes.

Checks are intentionally lightweight and dependency-free so they can run in local
agent sessions and CI before a full schema validator is available.
"""
import argparse, json, sys
from pathlib import Path

REQUIRED_JSON = {
    "business-context-map.json": ["task_id", "source_evidence", "entry_points", "core_services", "data_layer", "assumptions", "unknowns"],
    "change-impact-matrix.json": ["task_id", "changed_points", "upstream_callers", "downstream_consumers", "shared_data", "verification_plan", "residual_risks"],
}

def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"{path}: invalid json: {exc}")

def require_fields(path: Path, data: dict, fields: list[str], errors: list[str]):
    for field in fields:
        if field not in data:
            errors.append(f"{path}: missing field {field}")

def nonempty(value):
    return value is not None and value != "" and value != [] and value != {}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", help="Directory containing anti-lazy artifacts")
    parser.add_argument("--merge", action="store_true", help="Require merge-safety-checklist.json")
    args = parser.parse_args()
    root = Path(args.artifact_dir)
    errors=[]
    if not root.exists():
        raise SystemExit(f"artifact dir not found: {root}")
    loaded={}
    for name, fields in REQUIRED_JSON.items():
        path=root/name
        if not path.exists():
            errors.append(f"{path}: required artifact missing")
            continue
        data=load_json(path); loaded[name]=data
        require_fields(path, data, fields, errors)
    bcm=loaded.get("business-context-map.json") or {}
    if bcm:
        if not nonempty(bcm.get("source_evidence")):
            errors.append("business-context-map.json: source_evidence must not be empty")
        for key in ["entry_points", "core_services", "data_layer"]:
            if key in bcm and not isinstance(bcm[key], list):
                errors.append(f"business-context-map.json: {key} must be array")
    cim=loaded.get("change-impact-matrix.json") or {}
    if cim:
        if not nonempty(cim.get("changed_points")):
            errors.append("change-impact-matrix.json: changed_points must not be empty")
        if not nonempty(cim.get("verification_plan")):
            errors.append("change-impact-matrix.json: verification_plan must not be empty")
        vp_text=json.dumps(cim.get("verification_plan", []), ensure_ascii=False).lower()
        if not any(token in vp_text for token in ["test", "mvn", "pytest", "验证", "check", "lint", "compile"]):
            errors.append("change-impact-matrix.json: verification_plan must include a concrete test/check/compile/lint command or check")
    if args.merge:
        path=root/"merge-safety-checklist.json"
        if not path.exists():
            errors.append(f"{path}: required for merge tasks")
        else:
            data=load_json(path)
            for field in ["base_evidence","ours_evidence","theirs_evidence","final_evidence","verification_plan","gate_decision"]:
                if not nonempty(data.get(field)):
                    errors.append(f"{path}: {field} must not be empty")
    if errors:
        raise SystemExit("\n".join(errors))
    print(json.dumps({"status":"pass","artifact_dir":str(root)}, ensure_ascii=False))
if __name__ == "__main__":
    main()
