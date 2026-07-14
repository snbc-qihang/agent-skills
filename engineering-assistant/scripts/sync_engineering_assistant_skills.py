#!/usr/bin/env python3
import argparse, shutil, json
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source", default="/Users/fengtianyangyang/plugins/engineering-assistant/skills")
    p.add_argument("--target", default="/Users/fengtianyangyang/.hermes/skills/engineering-assistant")
    p.add_argument("--backup", default="/Users/fengtianyangyang/.hermes/skills-backups")
    args=p.parse_args()
    source=Path(args.source); target=Path(args.target); backup=Path(args.backup)
    if not source.exists(): raise SystemExit(f"source missing: {source}")
    backup.mkdir(parents=True, exist_ok=True)
    backup_path=None
    if target.exists():
        import datetime
        backup_path=backup/("engineering-assistant-"+datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copytree(target, backup_path)
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_dir(): shutil.copytree(item, target/item.name)
    count=len(list(target.glob("*/SKILL.md")))
    print(json.dumps({"status":"pass","installed":count,"target":str(target),"backup":str(backup_path) if backup_path else None}, ensure_ascii=False))
if __name__ == "__main__": main()
