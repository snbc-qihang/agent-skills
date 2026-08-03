"""Deterministic policy composition with immutable safety floors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .catalog import Catalog
from .model import PolicyRule, PolicySpec
from .validation import ValidationFailure


VIOLATION_RANK = {"ask": 0, "confirm": 1, "block": 2, "fail": 3}


@dataclass(frozen=True)
class PolicyOverride:
    policy_id: str
    action: str
    reason: str
    approval_id: str | None = None


@dataclass(frozen=True)
class RuleProvenance:
    rule_id: str
    policy_id: str
    source: str


@dataclass(frozen=True)
class EffectivePolicySet:
    policy_ids: tuple[str, ...]
    policies: Mapping[str, PolicySpec]
    rules: Mapping[str, PolicyRule]
    provenance: tuple[RuleProvenance, ...]
    required_evidence: tuple[str, ...]
    strongest_violation: str
    applied_overrides: tuple[PolicyOverride, ...]


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def resolve_policies(
    catalog: Catalog,
    *,
    profile_id: str = "default",
    global_refs: Sequence[str] = ("safety-core",),
    flow_id: str | None = None,
    skill_ids: Sequence[str] = (),
    task_policy_refs: Sequence[str] = (),
    overrides: Sequence[PolicyOverride] = (),
) -> EffectivePolicySet:
    """Resolve policies in safety -> profile -> flow -> skill -> task order.

    A task may add policies.  Disabling any policy is a lowering operation and
    therefore requires an approval; immutable policies can never be disabled.
    """

    if profile_id not in catalog.profiles:
        raise ValidationFailure(f"unknown profile {profile_id}")
    if flow_id is not None and flow_id not in catalog.flows:
        raise ValidationFailure(f"unknown flow {flow_id}")
    unknown_skills = sorted(set(skill_ids) - set(catalog.skills))
    if unknown_skills:
        raise ValidationFailure(f"unknown skills: {', '.join(unknown_skills)}")

    ordered: list[tuple[str, str]] = []
    ordered.extend((item, "global") for item in global_refs)
    ordered.extend((item, f"profile:{profile_id}") for item in catalog.profiles[profile_id].policy_refs)
    if flow_id is not None:
        ordered.extend((item, f"flow:{flow_id}") for item in catalog.flows[flow_id].policy_refs)
    for skill_id in skill_ids:
        ordered.extend((item, f"skill:{skill_id}") for item in catalog.skills[skill_id].policy_refs)
    ordered.extend((item, "task") for item in task_policy_refs)

    refs = _ordered_unique(item for item, _ in ordered)
    unknown_policies = sorted(set(refs) - set(catalog.policies))
    if unknown_policies:
        raise ValidationFailure(f"unknown policies: {', '.join(unknown_policies)}")

    override_by_policy: dict[str, PolicyOverride] = {}
    for override in overrides:
        if override.policy_id not in catalog.policies:
            raise ValidationFailure(f"override references unknown policy {override.policy_id}")
        if override.action not in {"disable"}:
            raise ValidationFailure(f"unsupported override action {override.action}")
        if override.policy_id in override_by_policy:
            raise ValidationFailure(f"duplicate override for policy {override.policy_id}")
        policy = catalog.policies[override.policy_id]
        if policy.immutable:
            raise ValidationFailure(f"immutable policy {policy.id} cannot be disabled")
        if not override.approval_id:
            raise ValidationFailure(f"disabling policy {policy.id} requires approval_id")
        override_by_policy[override.policy_id] = override

    active_refs = [item for item in refs if item not in override_by_policy]
    policies = {item: catalog.policies[item] for item in active_refs}
    source_by_policy: dict[str, str] = {}
    for policy_id, source in ordered:
        source_by_policy.setdefault(policy_id, source)

    rules: dict[str, PolicyRule] = {}
    provenance: list[RuleProvenance] = []
    for policy_id in active_refs:
        for rule in policies[policy_id].rules:
            existing = rules.get(rule.id)
            if existing is not None and existing != rule:
                raise ValidationFailure(
                    f"rule {rule.id} is defined inconsistently by more than one policy; rule ids are global"
                )
            rules[rule.id] = rule
            provenance.append(RuleProvenance(rule.id, policy_id, source_by_policy[policy_id]))

    required_evidence = tuple(
        _ordered_unique(evidence for policy in policies.values() for evidence in policy.required_evidence)
    )
    strongest_violation = max(
        (policy.on_violation for policy in policies.values()),
        key=lambda item: VIOLATION_RANK[item],
        default="ask",
    )
    return EffectivePolicySet(
        policy_ids=tuple(active_refs),
        policies=policies,
        rules=rules,
        provenance=tuple(provenance),
        required_evidence=required_evidence,
        strongest_violation=strongest_violation,
        applied_overrides=tuple(overrides),
    )
