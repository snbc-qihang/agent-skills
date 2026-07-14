#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fail(message: str) -> int:
    print(f"INVALID_RUNTIME_COMPILE_POLICY: {message}")
    return 1


def main() -> int:
    plugin_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    policy_path = plugin_root / "engineering-assistant/registry/runtime-compile-policy.json"
    if not policy_path.exists():
        return fail(f"missing policy {policy_path}")
    policy = load_json(policy_path)

    index_path = plugin_root / policy.get("compiled_index", "")
    registry_path = plugin_root / policy.get("skill_registry", "")
    if not index_path.exists():
        return fail(f"missing compiled index {index_path}")
    if not registry_path.exists():
        return fail(f"missing skill registry {registry_path}")

    index = load_json(index_path)
    registry = load_json(registry_path)
    compiled_by_id = {item["skill_id"]: item for item in index.get("skills", [])}
    errors = []

    for skill in registry.get("skills", []):
        skill_id = skill.get("skill_id")
        compiled = compiled_by_id.get(skill_id)
        if not compiled:
            errors.append(f"missing compiled skill {skill_id}")
            continue
        compiled_path = plugin_root / compiled.get("path", "")
        if not compiled_path.exists():
            errors.append(f"missing compiled IR for {skill_id}: {compiled_path}")
        if compiled.get("risk_level") != skill.get("risk_level"):
            errors.append(f"risk mismatch for {skill_id}: registry={skill.get('risk_level')} compiled={compiled.get('risk_level')}")
        if compiled.get("allow_implicit_invocation") != skill.get("allow_implicit_invocation"):
            errors.append(
                f"implicit invocation mismatch for {skill_id}: registry={skill.get('allow_implicit_invocation')} compiled={compiled.get('allow_implicit_invocation')}"
            )

    if errors:
        for error in errors:
            print(error)
        return fail(f"{len(errors)} error(s)")
    print(f"VALID_RUNTIME_COMPILE_POLICY skills={len(registry.get('skills', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
