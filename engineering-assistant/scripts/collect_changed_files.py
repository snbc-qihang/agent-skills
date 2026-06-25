#!/usr/bin/env python3
import argparse
import hashlib
import subprocess
from pathlib import Path
from control_runtime import ensure_control_dir, now_iso, update_artifact_index, validate_target_project_root, write_json

def git_lines(args, cwd: Path):
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode not in (0, 1):
        if "ambiguous argument" in result.stderr or "bad revision" in result.stderr or "unknown revision" in result.stderr:
            return []
        raise SystemExit(result.stderr.strip())
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]

def fingerprint(items: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(items)).encode("utf-8")).hexdigest()

def main():
    parser = argparse.ArgumentParser(description="Collect changed files for contract validation.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--output", default="artifacts/_control/changed-files-report.json")
    args = parser.parse_args()
    root = validate_target_project_root(Path(args.root))
    output = root / args.output
    unstaged = git_lines(["git", "diff", "--name-only", args.base], root)
    staged = git_lines(["git", "diff", "--cached", "--name-only", args.base], root)
    untracked = git_lines(["git", "ls-files", "--others", "--exclude-standard"], root)
    changed = sorted(set(unstaged + staged + untracked))
    rel_output = str(output.relative_to(root))
    artifact_index = "artifacts/_control/artifact-index.json"
    changed = sorted(set(changed + [rel_output, artifact_index]))
    report = {"base": args.base, "changed_files": changed, "workspace_fingerprint": fingerprint(changed), "unstaged_files": unstaged, "staged_files": staged, "untracked_files": untracked, "generated_at": now_iso()}
    write_json(output, report)
    ensure_control_dir(root)
    update_artifact_index(root, output.name, output, "json", "collect_changed_files")
    print(output)

if __name__ == "__main__":
    main()
