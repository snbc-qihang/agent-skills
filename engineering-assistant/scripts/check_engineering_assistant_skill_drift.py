#!/usr/bin/env python3
import argparse, filecmp, json, sys
from pathlib import Path

def collect(root: Path):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source", default="/Users/fengtianyangyang/plugins/engineering-assistant/skills")
    p.add_argument("--target", default="/Users/fengtianyangyang/.hermes/skills/engineering-assistant")
    args=p.parse_args()
    source=Path(args.source); target=Path(args.target)
    errors=[]
    if not source.exists(): errors.append(f"source missing: {source}")
    if not target.exists(): errors.append(f"target missing: {target}")
    if errors: raise SystemExit("\n".join(errors))
    sfiles=set(collect(source)); tfiles=set(collect(target))
    missing=sorted(sfiles-tfiles); extra=sorted(tfiles-sfiles)
    changed=[]
    for rel in sorted(sfiles & tfiles):
        sp=source/rel; tp=target/rel
        if sp.read_bytes()!=tp.read_bytes(): changed.append(rel)
    status="pass" if not missing and not extra and not changed else "block"
    report={"status":status,"source":str(source),"target":str(target),"missing_in_target":missing,"extra_in_target":extra,"changed":changed}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if status!="pass": raise SystemExit(1)
if __name__ == "__main__": main()
