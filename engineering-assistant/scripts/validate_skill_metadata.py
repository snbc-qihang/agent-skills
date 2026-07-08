#!/usr/bin/env python3
import sys
from pathlib import Path

errors = []
for skill_md in sorted(Path("skills").glob("*/SKILL.md")):
    text = skill_md.read_text(encoding="utf-8")
    skill_dir = skill_md.parent
    meta = skill_dir / "agents" / "openai.yaml"
    if "description: Use when" not in text:
        errors.append(f"{skill_md}: description 必须以 Use when 描述触发条件")
    if not meta.exists():
        errors.append(f"{meta}: 缺少 agents/openai.yaml")
        continue
    meta_text = meta.read_text(encoding="utf-8")
    for required in ["display_name:", "short_description:", "default_prompt:", "language_policy:", "when_unspecified: \"ask_user\"", "policy:", "allow_implicit_invocation:", "risk_level:", "metadata:"]:
        if required not in meta_text:
            errors.append(f"{meta}: 缺少 {required}")
    if skill_dir.name in {"workflow-orchestrator", "code-development", "code-quality-governor", "release-readiness", "release-verification", "engineering-knowledge-miner", "skill-evolution-review", "implementation-controller"} and "allow_implicit_invocation: false" not in meta_text:
        errors.append(f"{meta}: 高风险 skill 必须 explicit-only")
if errors:
    raise SystemExit("\n".join(errors))
print("ok")
