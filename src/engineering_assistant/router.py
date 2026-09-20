# GPT-6 适配变更说明：只读意图显式内联执行，保留原始风险证据；矛盾的写入请求仍阻断，旧调用默认行为保持兼容。
"""Semantic intent router for the public skill surface."""

from __future__ import annotations

from typing import Sequence

from .catalog import Catalog
from .model import RouteDecision, RouteIntent
from .policy import resolve_policies
from .validation import ValidationFailure, load_json, validate_instance


ROUTES = {
    "explain": (None, ()),
    "context": (None, ("repo-context",)),
    "research": (None, ("research",)),
    "decide": (None, ("decision-interview",)),
    "model": (None, ("domain-modeling",)),
    "domain-design": (
        "domain-design",
        ("repo-context", "domain-modeling", "decision-interview", "codebase-design", "code-review"),
    ),
    "shape": ("shape", ("repo-context", "domain-modeling", "decision-interview")),
    "prototype": (None, ("prototype",)),
    "design": ("design", ("repo-context", "domain-modeling", "codebase-design")),
    "implement": ("implement", ("tdd", "code-review")),
    "diagnose": (None, ("diagnosing-bugs",)),
    "review": ("review", ("code-review",)),
    "release": ("release", ("engineering-assistant",)),
    "evolve": ("evolve", ("engineering-assistant",)),
    "wayfind": (None, ("wayfinder",)),
}

HIGH_RISK_SIGNALS = {
    "production",
    "destructive",
    "history-rewrite",
    "credential",
    "security",
    "irreversible",
    "cross-repository",
}
TEAM_DELIVERY_TASKS = {"shape", "design", "implement", "release", "evolve"}


def _ordered_unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def route_intent(intent: RouteIntent, catalog: Catalog, *, profile_id: str | None = None) -> RouteDecision:
    profile_id = profile_id or "default"
    validate_instance(
        intent.to_dict(),
        load_json(catalog.root / "schemas/route-intent.schema.json"),
        "route-intent",
    )
    if intent.task_kind not in ROUTES:
        raise ValidationFailure(f"unsupported task kind {intent.task_kind}")

    if intent.read_only and (
        intent.task_kind not in {"explain", "context", "research", "decide", "model", "domain-design", "shape", "design", "diagnose", "review", "wayfind"}
        or intent.requested_external_actions
        or {"forbidden", "authorization-denied"} & set(intent.risk_signals)
    ):
        decision = RouteDecision(
            decision="block", flow_id=None, skill_ids=[],
            policy_refs=list(catalog.profiles[profile_id].policy_refs),
            evidence_level="inline", persistence_mode="blocked", approval_required=[],
            reason="只读意图与请求的执行动作或明确拒绝授权相矛盾；先澄清冲突，不执行写入。",
        )
        _validate_decision(decision, catalog)
        return decision

    flow_id, skill_ids = ROUTES[intent.task_kind]
    if (
        profile_id == "rrq-yq-team"
        and intent.task_kind in TEAM_DELIVERY_TASKS
    ):
        flow_id = "team-delivery"
    if intent.read_only:
        flow_id = None
    if intent.confidence < 0.55:
        decision = RouteDecision(
            decision="ask",
            flow_id=None,
            skill_ids=["engineering-assistant"],
            policy_refs=list(catalog.profiles[profile_id].policy_refs),
            evidence_level="inline",
            persistence_mode="inline",
            approval_required=[],
            reason="意图置信度低于 0.55；加载 flow 前先询问一个会改变决策的问题。",
        )
        _validate_decision(decision, catalog)
        return decision

    unknown_skills = set(skill_ids) - set(catalog.skills)
    if unknown_skills:
        raise ValidationFailure(f"route references missing skills: {sorted(unknown_skills)}")

    risk_signals = set(intent.risk_signals)
    approval_required = list(intent.requested_external_actions)
    if not intent.read_only:
        approval_required.extend(sorted(risk_signals & HIGH_RISK_SIGNALS))
    if intent.task_kind == "release":
        approval_required.append("release-execution")
    approval_required = _ordered_unique(approval_required)
    missing_confirmations = [
        action for action in approval_required if action not in intent.confirmed_actions
    ]

    if "forbidden" in risk_signals or "authorization-denied" in risk_signals:
        decision_name = "block"
        persistence = "blocked"
        reason = "请求路由包含明确的禁止或授权拒绝信号。"
    elif missing_confirmations:
        decision_name = "confirm"
        persistence = "target_repo" if flow_id else "ephemeral"
        reason = "路由已经明确，但高风险或外部动作需要范围独立的审批。"
    else:
        decision_name = "proceed"
        persistence = "target_repo" if flow_id or (intent.task_kind == "wayfind" and not intent.read_only) else "inline"
        reason = (
            "请求只需要解释；直接回答，不调用 skill。"
            if intent.task_kind == "explain"
            else "已从结构化意图中选择最小充分的原语或受治理 flow。"
        )

    effective = resolve_policies(catalog, profile_id=profile_id, flow_id=flow_id, skill_ids=skill_ids)
    evidence_level = "formal" if intent.task_kind in {"release", "evolve"} else (
        "standard" if flow_id or intent.task_kind in {"diagnose", "review"} else "lite"
    )
    decision = RouteDecision(
        decision=decision_name,
        flow_id=flow_id,
        skill_ids=list(skill_ids),
        policy_refs=list(effective.policy_ids),
        evidence_level=evidence_level,
        persistence_mode=persistence,
        approval_required=missing_confirmations,
        reason=reason,
    )
    _validate_decision(decision, catalog)
    return decision


def _validate_decision(decision: RouteDecision, catalog: Catalog) -> None:
    validate_instance(
        decision.to_dict(),
        load_json(catalog.root / "schemas/route-decision.schema.json"),
        "route-decision",
    )
