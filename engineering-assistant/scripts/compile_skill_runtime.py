#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


PLUGIN_VERSION = "1.0.0.4"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_agent_meta(path: Path) -> dict:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    meta = {}
    for key in ["display_name", "short_description", "default_prompt"]:
        match = re.search(rf"^{key}:\s*\"?(.*?)\"?$", text, re.MULTILINE)
        meta[key] = match.group(1) if match else ""
    meta["allow_implicit_invocation"] = "allow_implicit_invocation: true" in text
    risk_match = re.search(r"risk_level:\s*\"?([a-z]+)\"?", text)
    meta["risk_level"] = risk_match.group(1) if risk_match else "medium"
    return meta


def compile_skill(skill_dir: Path) -> dict:
    contract = load_json(skill_dir / "contract.yaml")
    workflow = load_json(skill_dir / "workflow" / "node.yaml")
    agent_meta = read_agent_meta(skill_dir / "agents" / "openai.yaml")
    skill_md = skill_dir / "SKILL.md"
    routing = contract.get("routing") or {
        "positive_triggers": [contract["skill_id"], contract.get("skill_name", ""), contract.get("purpose", "")],
        "negative_triggers": [f"只解释 {contract.get('skill_name', contract['skill_id'])} 的用途，不执行任务"],
        "allow_implicit_invocation": agent_meta["allow_implicit_invocation"],
        "risk_level": agent_meta["risk_level"],
    }
    return {
        "skill_id": contract["skill_id"],
        "version": contract.get("version", PLUGIN_VERSION),
        "stage": contract.get("stage"),
        "type": contract.get("type"),
        "prompt_pack": {
            "display_name": agent_meta["display_name"],
            "short_description": agent_meta["short_description"],
            "default_prompt": agent_meta["default_prompt"],
            "trigger_description": contract.get("trigger_description", ""),
            "language_policy": contract.get("language_policy", {}),
        },
        "inputs": contract.get("inputs", []),
        "outputs": contract.get("outputs", []),
        "routing": routing,
        "risk": {
            "risk_level": agent_meta["risk_level"],
            "allow_implicit_invocation": agent_meta["allow_implicit_invocation"],
            "human_approval_required": contract.get("human_approval_required", []),
        },
        "quality_gates": contract.get("quality_gates", []),
        "workflow": {
            "node_id": workflow.get("node_id"),
            "entry_modes": workflow.get("entry_modes", []),
            "next_nodes": workflow.get("next_nodes", []),
        },
        "source_files": [
            str(skill_md),
            str(skill_dir / "contract.yaml"),
            str(skill_dir / "workflow" / "node.yaml"),
            str(skill_dir / "agents" / "openai.yaml"),
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Compile skills into lightweight runtime IR.")
    parser.add_argument("--skills-root", default="skills")
    parser.add_argument("--out", default="engineering-assistant/runtime/compiled")
    args = parser.parse_args()
    out = Path(args.out)
    skills_out = out / "skills"
    skills_out.mkdir(parents=True, exist_ok=True)
    compiled = []
    for skill_dir in sorted(Path(args.skills_root).glob("*")):
        if not (skill_dir / "contract.yaml").exists():
            continue
        ir = compile_skill(skill_dir)
        target = skills_out / f"{ir['skill_id']}.ir.json"
        target.write_text(json.dumps(ir, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        compiled.append({"skill_id": ir["skill_id"], "path": str(target), "risk_level": ir["risk"]["risk_level"], "allow_implicit_invocation": ir["risk"]["allow_implicit_invocation"]})
    index = {"version": PLUGIN_VERSION, "skills": compiled}
    (out / "skill-runtime-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "compiled": len(compiled), "out": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
