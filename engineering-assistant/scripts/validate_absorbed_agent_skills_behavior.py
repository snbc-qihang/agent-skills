#!/usr/bin/env python3
"""Behavior acceptance for the absorbed clarification, argumentation, and scheduling capabilities."""

import importlib.util
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EA = ROOT / "engineering-assistant"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"ABSORBED_BEHAVIOR_FAILED {message}")


route_module = load_module("ea_route_skill", EA / "scripts/route_skill.py")
argumentation_module = load_module("ea_argumentation", EA / "scripts/validate_requirement_argumentation.py")

ambiguous = route_module.route("帮我做一个系统", ROOT)
check(ambiguous["status"] == "waiting_for_input", "ambiguous request must pause")

clear_review = route_module.route("帮我做代码评审，检查安全和回归风险", ROOT)
check(clear_review["status"] == "selected", "clear review must route without interview")
check("code-review" in clear_review["selected_skills"], "code-review not selected")
check("requirement-intake" not in clear_review["selected_skills"], "clear L1 review must not force requirement intake")

parallel = route_module.route("设计一个跨模块功能，需要数据库、Redis 和 MQ 方案", ROOT)
check(parallel["complex_requirement_protocol"]["required"], "complex protocol missing")
specialties = {"database-design", "redis-design", "mq-design"}
check(any(specialties <= set(batch["skills"]) for batch in parallel["parallel_batches"]), "specialty Skills are not a parallel ready set")

for fixture in (
    "requirement-argumentation-executable.json",
    "requirement-argumentation-conditional.json",
    "requirement-argumentation-not-executable.json",
):
    argumentation_module.validate(EA / "evals" / fixture)

multi_window = (Path.home() / ".codex/skills/engineering-assistant-overlay/references/multi-window-coordination.md").read_text(encoding="utf-8")
for phrase in ("sole owner of the global dependency DAG", "cannot create or command other workers", "completion barrier", "ARTIFACT + CONTRACT"):
    check(phrase in multi_window, f"multi-window contract missing: {phrase}")

signals = json.loads((EA / "registry/skill-routing-signals.json").read_text(encoding="utf-8"))
check(len(signals["skills"]) == 22, "routing registry must retain exactly 22 existing Skills")
evidence = {
    "schema_version": "1.0",
    "case_count": 7,
    "passed_count": 7,
    "passed": True,
    "checks": [
        "ambiguous_request_pauses",
        "clear_review_skips_interview",
        "complex_protocol_routes",
        "specialty_ready_set_parallel",
        "three_argumentation_verdicts_validate",
        "multi_window_controller_contract",
        "twenty_two_skill_registry_preserved",
    ],
    "source_sha256": {
        "route_skill.py": hashlib.sha256((EA / "scripts/route_skill.py").read_bytes()).hexdigest(),
        "multi-window-coordination.md": hashlib.sha256((Path.home() / ".codex/skills/engineering-assistant-overlay/references/multi-window-coordination.md").read_bytes()).hexdigest(),
    },
}
if len(sys.argv) == 3 and sys.argv[1] == "--out":
    output = Path(sys.argv[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
elif len(sys.argv) != 1:
    raise SystemExit("usage: validate_absorbed_agent_skills_behavior.py [--out evidence.json]")
print("VALID_ABSORBED_AGENT_SKILLS_BEHAVIOR cases=7 skills=22")
