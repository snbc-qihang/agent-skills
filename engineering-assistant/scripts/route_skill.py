#!/usr/bin/env python3
"""Route natural-language engineering intent to a minimal capability DAG."""

import argparse
import json
import re
from pathlib import Path


ACTION_MARKERS = (
    "修复", "实现", "修改", "执行", "生成", "开发", "评审", "审查", "测试",
    "发布", "上线", "设计", "审计", "吞噬", "合并", "复盘", "分析", "验证",
)
EXPLAIN_MARKERS = ("只解释", "仅解释", "用途", "不执行", "不生成产物", "explain only")
L3_MARKERS = ("生产", "线上", "支付", "退款", "资金", "库存", "权限", "迁移", "回填", "删除数据", "核心链路")
L2_MARKERS = ("跨模块", "跨服务", "共享", "公共接口", "数据库", "redis", "mq", "消息队列", "状态机", "多窗口")
GENERIC_IMPLEMENT_MARKERS = ("修复", "开发", "实现", "修改代码", "写代码", "bug")
READ_ONLY_MARKERS = ("只读", "不修改", "不要修改", "不改文件", "不写代码", "仅审计", "只做代码评审", "只评审")
WRITE_SKILLS = {"code-development", "frontend-development", "implementation-controller"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def contains_any(text: str, phrases) -> list[str]:
    return [phrase for phrase in phrases if normalize(phrase) in text]


def is_explain_only(text: str) -> bool:
    if text.startswith(("只解释", "仅解释", "explain only")):
        return True
    action_text = text.replace("不执行", "").replace("不生成产物", "")
    return bool(contains_any(text, EXPLAIN_MARKERS)) and not bool(contains_any(action_text, ACTION_MARKERS))


def request_constraints(text: str, skill_ids) -> tuple[bool, set[str]]:
    read_only = bool(contains_any(text, READ_ONLY_MARKERS))
    forbidden = set()
    for skill_id in skill_ids:
        patterns = (
            rf"(?:不要|禁止|不再|勿)\s*(?:使用|调用|执行|选择)?\s*{re.escape(skill_id)}",
            rf"{re.escape(skill_id)}\s*(?:不要|禁止|不执行|不使用)",
        )
        if any(re.search(pattern, text) for pattern in patterns):
            forbidden.add(skill_id)
    if read_only:
        forbidden.update(WRITE_SKILLS)
    return read_only, forbidden


def risk_level(text: str) -> str:
    if contains_any(text, L3_MARKERS):
        return "L3_CRITICAL"
    if contains_any(text, L2_MARKERS):
        return "L2_SHARED"
    if contains_any(text, ACTION_MARKERS):
        return "L1_DIRECT"
    return "L0_FAST"


def score_skill(text: str, skill: dict) -> tuple[int, list[str]]:
    evidence = []
    score = 0
    skill_id = skill["skill_id"]
    if skill_id in text:
        score += 100
        evidence.append(f"explicit:{skill_id}")
    primary = contains_any(text, skill.get("primary_phrases", []))
    secondary = contains_any(text, skill.get("secondary_phrases", []))
    for phrase in primary:
        score += 40 + min(len(phrase), 20)
        evidence.append(f"primary:{phrase}")
    for phrase in secondary:
        score += 10 + min(len(phrase), 10)
        evidence.append(f"secondary:{phrase}")
    return score, evidence


def expand_prerequisites(selected: set[str], by_id: dict[str, dict], risk: str) -> set[str]:
    expanded = set(selected)
    stack = list(selected)
    while stack:
        skill_id = stack.pop()
        for prerequisite in by_id[skill_id].get("prerequisites", []):
            if prerequisite not in expanded:
                expanded.add(prerequisite)
                stack.append(prerequisite)

    implementation = {"code-development", "frontend-development"} & expanded
    if implementation and risk in {"L2_SHARED", "L3_CRITICAL"}:
        for prerequisite in ("requirement-intake", "repo-context-miner", "high-level-design", "detailed-design", "design-review", "implementation-controller"):
            if prerequisite not in expanded:
                expanded.add(prerequisite)
                stack.append(prerequisite)
        while stack:
            skill_id = stack.pop()
            for prerequisite in by_id[skill_id].get("prerequisites", []):
                if prerequisite not in expanded:
                    expanded.add(prerequisite)
                    stack.append(prerequisite)
    return expanded


def effective_prerequisites(skill_id: str, selected: set[str], by_id: dict[str, dict], risk: str) -> set[str]:
    prerequisites = set(by_id[skill_id].get("prerequisites", [])) & selected
    if risk in {"L2_SHARED", "L3_CRITICAL"} and ({"code-development", "frontend-development"} & selected):
        conditional_edges = {
            "detailed-design": {"high-level-design"},
            "design-review": {"detailed-design"},
            "implementation-controller": {"design-review"},
            "code-development": {"implementation-controller"},
            "frontend-development": {"implementation-controller"},
        }
        prerequisites.update(conditional_edges.get(skill_id, set()) & selected)
    return prerequisites


def dependency_batches(selected: set[str], by_id: dict[str, dict], risk: str) -> list[list[str]]:
    remaining = set(selected)
    completed = set()
    batches = []
    while remaining:
        ready = sorted(
            skill_id for skill_id in remaining
            if effective_prerequisites(skill_id, selected, by_id, risk) <= completed
        )
        if not ready:
            raise ValueError(f"routing dependency cycle: {sorted(remaining)}")
        batches.append(ready)
        completed.update(ready)
        remaining.difference_update(ready)
    return batches


def infer_fallback(text: str) -> list[str]:
    if contains_any(text, GENERIC_IMPLEMENT_MARKERS):
        return ["code-development"]
    return []


def compact_record(result: dict) -> dict:
    """Persist only the considered set, never a dump of every installed Skill."""
    selected = set(result.get("selected_skills", []))
    candidates = []
    for item in result.get("candidates", []):
        skill_id = item.get("skill_id")
        if skill_id in selected or len(candidates) < 3:
            candidates.append({
                "skill_id": skill_id,
                "score": item.get("score", 0),
                "selected": skill_id in selected,
                "evidence": item.get("evidence", []),
            })
    return {
        "status": result.get("status"),
        "decision": result.get("decision"),
        "risk_level": result.get("risk_level"),
        "selected_skills": result.get("selected_skills", []),
        "parallel_batches": result.get("parallel_batches", []),
        "candidates": candidates,
        "skipped_candidates": result.get("skipped_candidates", [])[:3],
    }


def route(prompt: str, root: Path, context_text: str = "") -> dict:
    registry_path = root / "engineering-assistant/registry/skill-routing-signals.json"
    registry = load_json(registry_path)
    policy = registry["policy"]
    by_id = {item["skill_id"]: item for item in registry["skills"]}
    explicit_text = normalize(prompt)
    text = normalize(prompt + "\n" + context_text)

    if is_explain_only(explicit_text):
        return {
            "status": "rejected",
            "decision": None,
            "confidence": 1.0,
            "reason": "咨询说明类请求不执行 Skill",
            "controller": policy["controller"],
            "selected_skills": [],
            "candidates": [],
        }

    read_only, forbidden = request_constraints(explicit_text, by_id)
    scored = []
    for skill in registry["skills"]:
        score, evidence = score_skill(text, skill)
        if score and skill["skill_id"] not in forbidden:
            scored.append({"skill_id": skill["skill_id"], "score": score, "evidence": evidence})
    scored.sort(key=lambda item: (-item["score"], item["skill_id"]))

    selected_primary = [item["skill_id"] for item in scored if item["score"] >= max(30, (scored[0]["score"] - 25) if scored else 30)]
    if not selected_primary:
        selected_primary = [item for item in infer_fallback(text) if item not in forbidden]
    if not selected_primary and read_only and contains_any(text, ("代码", "实现", "变更", "审计", "评审")):
        selected_primary = ["code-review"]

    if "self-evolution-controller" in selected_primary:
        selected_primary = [item for item in selected_primary if item in {"self-evolution-controller", "skill-quality-auditor"}]
    if "code-review" in selected_primary and "code-development" in selected_primary and not contains_any(text, ("修复", "修改", "实现")):
        selected_primary.remove("code-development")
    if "design-review" in selected_primary and "code-review" in selected_primary and "设计" not in text:
        selected_primary.remove("design-review")
    if "frontend-development" in selected_primary and "code-development" in selected_primary and not contains_any(text, ("后端", "接口", "java", "spring", "服务")):
        selected_primary.remove("code-development")
    if "release-verification" in selected_primary and "release-readiness" in selected_primary:
        selected_primary.remove("release-readiness")

    if not selected_primary:
        continuation = contains_any(text, ("继续", "恢复", "接着做", "继续推进"))
        return {
            "status": "waiting_for_input",
            "decision": None,
            "confidence": 0.0,
            "reason": "无法从用户意图或可用上下文确定最小能力集合",
            "controller": policy["controller"],
            "selected_skills": [],
            "candidates": scored[:5] or ([{
                "skill_id": policy["controller"],
                "score": 1,
                "evidence": ["continuation_requires_frozen_task_context"],
            }] if continuation else []),
        }

    risk = risk_level(text)
    selected = expand_prerequisites(set(selected_primary), by_id, risk)
    selected.discard(policy["controller"])
    batches = dependency_batches(selected, by_id, risk)
    selected_order = [skill_id for batch in batches for skill_id in batch]
    primary = selected_primary[0]
    top_score = next((item["score"] for item in scored if item["skill_id"] == primary), 30)
    skipped = [
        {"skill_id": item["skill_id"], "reason": "lower_intent_score", "score": item["score"]}
        for item in scored if item["skill_id"] not in selected
    ][: policy["max_skipped_candidates"]]

    return {
        "status": "selected",
        "decision": primary,
        "confidence": min(top_score / 100, 1.0),
        "reason": "natural_language_capability_routing",
        "controller": policy["controller"],
        "risk_level": risk,
        "routing_confirmation_required": policy["routing_requires_user_confirmation"],
        "read_only": read_only,
        "forbidden_capabilities": sorted(forbidden),
        "selected_primary_skills": selected_primary,
        "selected_skills": selected_order,
        "parallel_batches": [
            {"batch_id": f"batch-{index}", "skills": batch, "dispatch": "parallel" if len(batch) > 1 else "serial_dependency"}
            for index, batch in enumerate(batches, start=1)
        ],
        "complex_requirement_protocol": {
            "required": risk in policy["complex_risk_levels"],
            "clarification_owner": "requirement-intake",
            "argumentation_required": risk in policy["complex_risk_levels"],
            "max_questions": 6,
        },
        "high_risk_action_approval_preserved": policy["high_risk_action_approval_preserved"],
        "skipped_candidates": skipped,
        "candidates": scored[:5],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Route natural-language intent to the minimum sufficient Engineering Assistant capability DAG.")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--context")
    parser.add_argument("--record-dir", help="Optional run-artifact directory for a compact routing decision.")
    args = parser.parse_args()
    context = ""
    if args.context and Path(args.context).exists():
        context = Path(args.context).read_text(encoding="utf-8", errors="ignore")[:8000]
    result = route(args.prompt, Path(args.root), context)
    if args.record_dir:
        record_dir = Path(args.record_dir)
        record_dir.mkdir(parents=True, exist_ok=True)
        (record_dir / "skill-route-decision.json").write_text(
            json.dumps(compact_record(result), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
