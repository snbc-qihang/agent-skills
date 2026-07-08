#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

HIGH_RISK = {"workflow-orchestrator", "code-development", "code-quality-governor", "release-readiness", "release-verification", "engineering-knowledge-miner", "skill-evolution-review", "implementation-controller"}
EXPLAIN_ONLY = ["只解释", "用途", "不执行", "不生成产物", "explain"]


def load_registry(root: Path) -> list[dict]:
    index = root / "engineering-assistant" / "runtime" / "compiled" / "skill-runtime-index.json"
    if index.exists():
        data = json.loads(index.read_text(encoding="utf-8"))
        skills = []
        for item in data.get("skills", []):
            ir_path = root / item["path"]
            ir = json.loads(ir_path.read_text(encoding="utf-8")) if ir_path.exists() else {}
            skills.append({
                "skill_id": item["skill_id"],
                "risk_level": item.get("risk_level", ir.get("risk", {}).get("risk_level", "medium")),
                "allow_implicit_invocation": item.get("allow_implicit_invocation", ir.get("risk", {}).get("allow_implicit_invocation", True)),
                "stage": ir.get("stage", ""),
                "type": ir.get("type", ""),
                "triggers": " ".join(ir.get("routing", {}).get("positive_triggers", []) + ir.get("routing", {}).get("intent_tags", [])),
            })
        return skills
    registry = root / "engineering-assistant" / "registry" / "skills.yaml"
    return json.loads(registry.read_text(encoding="utf-8")).get("skills", [])


def explicit_skill_mention(prompt: str, skill_id: str) -> bool:
    return re.search(rf"(^|\s|使用|use\s+){re.escape(skill_id)}($|\s|，|,)", prompt.lower()) is not None


def score_skill(prompt: str, skill: dict, explicit_prompt: str) -> int:
    text = prompt.lower()
    skill_id = skill["skill_id"]
    score = 0
    if explicit_skill_mention(explicit_prompt, skill_id):
        score += 100
    for token in skill_id.split("-"):
        if token and token in text:
            score += 5
    if "设计" in prompt and "design" in skill_id:
        score += 8
    if ("评审" in prompt or "review" in text) and "review" in skill_id:
        score += 8
    if ("测试" in prompt or "test" in text) and skill_id == "self-test":
        score += 8
    if any(token in text for token in ["实现", "编码", "代码", "complete", "修复"]) and skill_id == "code-development":
        score += 12
    if any(token in text for token in ["继续", "恢复", "next_action", "workflow"]) and skill_id == "workflow-orchestrator":
        score += 10
    if "frontend" in text or "前端" in prompt:
        if "frontend" in skill_id:
            score += 10
        elif skill_id == "code-development":
            score -= 4
    return score


def route(prompt: str, root: Path, explicit_prompt=None) -> dict:
    explicit_prompt = explicit_prompt if explicit_prompt is not None else prompt
    if any(token in explicit_prompt for token in EXPLAIN_ONLY):
        return {"status": "rejected", "decision": None, "confidence": 1.0, "reason": "咨询说明类请求不执行 skill", "candidates": []}
    skills = load_registry(root)
    scored = sorted(({"skill_id": skill["skill_id"], "score": score_skill(prompt, skill, explicit_prompt), "risk_level": skill.get("risk_level", "medium"), "allow_implicit_invocation": skill.get("allow_implicit_invocation", True)} for skill in skills), key=lambda item: item["score"], reverse=True)
    candidates = [item for item in scored if item["score"] > 0][:5]
    if not candidates:
        return {"status": "waiting_for_input", "decision": None, "confidence": 0.0, "reason": "无法确定最小足够 skill", "candidates": []}
    top = candidates[0]
    explicit = explicit_skill_mention(explicit_prompt, top["skill_id"])
    if top["skill_id"] in HIGH_RISK and not explicit:
        return {"status": "waiting_for_input", "decision": None, "confidence": min(top["score"] / 100, 0.89), "reason": "高风险 skill 必须 explicit-only", "candidates": candidates}
    second_score = candidates[1]["score"] if len(candidates) > 1 else 0
    if top["score"] < 8 or (second_score and top["score"] - second_score < 3):
        return {"status": "waiting_for_input", "decision": None, "confidence": min(top["score"] / 100, 0.7), "reason": "路由置信度不足或存在相邻 skill 冲突", "candidates": candidates}
    return {"status": "selected", "decision": top["skill_id"], "confidence": min(top["score"] / 100, 1.0), "reason": "命中确定性路由规则", "candidates": candidates}


def main():
    parser = argparse.ArgumentParser(description="Route a request to the minimum sufficient engineering-assistant skill.")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--context")
    args = parser.parse_args()
    explicit_prompt = args.prompt
    prompt = explicit_prompt
    if args.context and Path(args.context).exists():
        prompt += "\n" + Path(args.context).read_text(encoding="utf-8")[:4000]
    print(json.dumps(route(prompt, Path(args.root), explicit_prompt=explicit_prompt), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
