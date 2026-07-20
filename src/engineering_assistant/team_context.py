"""Task-scoped teamwork pack and rule context for model-facing adapters."""

from __future__ import annotations

from typing import Iterable

from .catalog import Catalog, TeamRule
from .model import RouteIntent


TEAM_PACK_ORDER = (
    "rrq-yq-delivery",
    "rrq-yq-architecture",
    "rrq-yq-api",
    "rrq-yq-code-quality",
    "rrq-yq-frontend",
    "rrq-yq-database",
    "rrq-yq-redis",
    "rrq-yq-mq",
)

TASK_PACKS = {
    "context": ("rrq-yq-delivery",),
    "decide": ("rrq-yq-delivery",),
    "model": ("rrq-yq-architecture",),
    "shape": ("rrq-yq-delivery",),
    "design": ("rrq-yq-delivery", "rrq-yq-architecture"),
    "implement": ("rrq-yq-delivery", "rrq-yq-code-quality"),
    "diagnose": ("rrq-yq-code-quality",),
    "review": (
        "rrq-yq-delivery",
        "rrq-yq-architecture",
        "rrq-yq-code-quality",
    ),
    "release": ("rrq-yq-delivery", "rrq-yq-code-quality"),
    "evolve": ("rrq-yq-delivery",),
    "wayfind": ("rrq-yq-delivery",),
}

TASK_CAPABILITIES = {
    "context": ("repo-context", "design-source-read"),
    "decide": ("decision-interview",),
    "model": ("architecture-design",),
    "shape": ("repo-context", "design-source-read", "decision-interview", "shape-contract"),
    "design": (
        "repo-context",
        "design-source-read",
        "decision-interview",
        "shape-contract",
        "architecture-design",
        "implementation-contract",
        "review-package-validation",
        "design-review",
    ),
    "implement": (
        "design-source-read", "review-package-validation", "work-slicing", "tdd", "implementation", "quality-evidence", "code-review",
    ),
    "diagnose": ("implementation", "quality-evidence", "code-review"),
    "review": ("design-source-read", "review-package-validation", "design-review", "quality-evidence", "code-review"),
    "release": (
        "design-source-read", "review-package-validation", "release-readiness", "release-verification", "release-retrospective",
    ),
    "evolve": (
        "release-retrospective",
        "feedback-ingest",
        "knowledge-mining",
        "skill-quality",
        "skill-evolution",
    ),
    "wayfind": ("repo-context", "design-source-read", "decision-interview", "shape-contract"),
}

PACK_CAPABILITIES = {
    "rrq-yq-architecture": (
        "architecture-design", "implementation-contract", "design-review",
    ),
    "rrq-yq-api": ("architecture-design", "implementation-contract", "code-review"),
    "rrq-yq-code-quality": (
        "tdd", "implementation", "quality-evidence", "code-review",
    ),
    "rrq-yq-frontend": ("frontend-design", "frontend-implementation"),
    "rrq-yq-database": ("database-design",),
    "rrq-yq-redis": ("redis-design",),
    "rrq-yq-mq": ("mq-design",),
}

PACK_KEYWORDS = {
    "rrq-yq-architecture": (
        "架构", "ddd", "jdk", "框架", "设计模式", "architecture", "framework",
    ),
    "rrq-yq-api": ("接口", "api", "yapi", "endpoint", "异常契约"),
    "rrq-yq-code-quality": (
        "研发", "实现", "代码", "tdd", "测试", "质量", "安全", "日志", "监控",
        "幂等", "并发", "implementation", "test", "quality", "security",
    ),
    "rrq-yq-frontend": (
        "前端", "frontend", "浏览器", "browser", "页面", "ui", "ux",
    ),
    "rrq-yq-database": (
        "数据库", "database", "schema", "sql", "索引", "分库", "分表",
    ),
    "rrq-yq-redis": ("redis", "缓存", "cache"),
    "rrq-yq-mq": (
        "mq", "消息", "topic", "rocketmq", "kafka", "rabbitmq",
    ),
}


def _matches(text: str, keywords: Iterable[str]) -> bool:
    folded = text.casefold()
    return any(keyword.casefold() in folded for keyword in keywords)


def _rule_payload(rule: TeamRule) -> dict:
    return {
        "id": rule.id,
        "category": rule.category,
        "guidance": rule.guidance,
        "source_refs": list(rule.source_refs),
        "target_refs": list(rule.target_refs),
        "capability_refs": list(rule.capability_refs),
        "evidence_contract_ref": f"rule:{rule.id}",
    }


def team_context_for_intent(
    catalog: Catalog,
    profile_id: str,
    intent: RouteIntent,
) -> dict | None:
    """Return applicable team author sources without changing RouteDecision."""

    profile = catalog.profiles[profile_id]
    if profile.rule_catalog_ref is None:
        return None
    rule_catalog = catalog.rule_catalogs[profile.rule_catalog_ref]
    searchable = " ".join((intent.requested_outcome, *intent.scope))
    selected = set(TASK_PACKS.get(intent.task_kind, ()))
    active_capabilities = set(TASK_CAPABILITIES.get(intent.task_kind, ()))
    for pack_id, keywords in PACK_KEYWORDS.items():
        if _matches(searchable, keywords):
            selected.add(pack_id)
            active_capabilities.update(PACK_CAPABILITIES[pack_id])
    pack_refs = [
        pack_id
        for pack_id in TEAM_PACK_ORDER
        if pack_id in selected and pack_id in profile.pack_refs
    ]
    rules = [
        _rule_payload(rule)
        for rule in rule_catalog.rules.values()
        if set(rule.target_refs).intersection(pack_refs)
        and set(rule.capability_refs).intersection(active_capabilities)
    ]
    referenced_source_ids = {
        source_ref for rule in rules for source_ref in rule["source_refs"]
    }
    missing_design_inputs = []
    if not intent.requirement_id:
        missing_design_inputs.append("requirement_id")
    if intent.design_source is None:
        missing_design_inputs.append("design_source")
    return {
        "profile_id": profile.id,
        "rule_catalog_id": rule_catalog.id,
        "pack_refs": pack_refs,
        "capability_refs": [
            capability_id
            for capability_id in catalog.capabilities
            if capability_id in active_capabilities
        ],
        "packs": [
            {
                "id": pack_id,
                "activation": list(catalog.packs[pack_id].activation),
                "source_path": catalog.packs[pack_id].source_path,
            }
            for pack_id in pack_refs
        ],
        "sources": [
            {
                "id": source.id,
                "title": source.title,
                "url": source.url,
                "digest": source.digest,
            }
            for source in rule_catalog.sources.values()
            if source.id in referenced_source_ids
        ],
        "rules": rules,
        "evidence_requirement": (
            "适用规则必须通过现有 EvidenceRef.contract_refs 登记 rule:<rule-id>。"
        ),
        "deterministic_design_input": (
            {
                "requirement_id": intent.requirement_id,
                "design_source": {
                    "root": intent.design_source.root,
                    "registry": intent.design_source.registry,
                },
            }
            if intent.requirement_id and intent.design_source
            else None
        ),
        "design_input_status": "missing" if missing_design_inputs else "ready",
        "missing_required_inputs": missing_design_inputs,
    }


def team_rules_for_capability(
    catalog: Catalog,
    profile_id: str,
    capability_id: str,
) -> list[dict]:
    """Return only rules declared applicable to one persisted flow capability."""

    profile = catalog.profiles[profile_id]
    if profile.rule_catalog_ref is None:
        return []
    rule_catalog = catalog.rule_catalogs[profile.rule_catalog_ref]
    return [
        _rule_payload(rule)
        for rule in rule_catalog.rules.values()
        if capability_id in rule.capability_refs
    ]
