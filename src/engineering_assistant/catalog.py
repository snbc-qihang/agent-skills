"""Load and verify the authoring catalog.

The catalog is the authoring source of truth.  Platform packages are compiled
from this data; they must not grow their own copies of skills, flows or policy
rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from .model import (
    CapabilityProviderSpec,
    CompletionCriterion,
    ContextPointer,
    FlowNode,
    FlowSpec,
    PolicyRule,
    PolicySpec,
    ProviderSource,
    SkillSpec,
)
from .validation import ValidationFailure, load_json, validate_many


DEFAULT_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Capability:
    id: str
    kind: str
    owner: str


@dataclass(frozen=True)
class ProjectProfile:
    id: str
    version: str
    policy_refs: tuple[str, ...]
    store: Mapping[str, Any]
    evidence_broker: Mapping[str, Any]
    approval_broker: Mapping[str, Any]
    investigation_policy: Mapping[str, Any]
    evidence_policy: Mapping[str, Any]
    adapter_preferences: tuple[str, ...]


@dataclass(frozen=True)
class Pack:
    id: str
    version: str
    activation: tuple[str, ...]
    capabilities: tuple[str, ...]
    policy_refs: tuple[str, ...]
    source_path: str


@dataclass(frozen=True)
class Catalog:
    root: Path
    version: str
    skills: Mapping[str, SkillSpec]
    flows: Mapping[str, FlowSpec]
    policies: Mapping[str, PolicySpec]
    capabilities: Mapping[str, Capability]
    packs: Mapping[str, Pack]
    profiles: Mapping[str, ProjectProfile]
    providers: Mapping[str, CapabilityProviderSpec]

    def skill_for_capability(self, capability_id: str) -> SkillSpec | None:
        capability = self.capabilities.get(capability_id)
        if capability is None or capability.kind != "primitive":
            return None
        return self.skills.get(capability.owner)

    def provider_for_capability(self, capability_id: str) -> CapabilityProviderSpec | None:
        candidates = [
            provider for provider in self.providers.values()
            if capability_id in provider.capability_ids
        ]
        return max(candidates, key=lambda item: item.priority) if candidates else None


def _unique_by_id(items: Iterable[Mapping[str, Any]], label: str) -> Dict[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    for item in items:
        item_id = str(item.get("id", ""))
        if not item_id:
            raise ValidationFailure(f"{label}: item has no id")
        if item_id in result:
            raise ValidationFailure(f"{label}: duplicate id {item_id}")
        result[item_id] = item
    return result


def _assert_refs(refs: Iterable[str], available: Mapping[str, Any], label: str) -> None:
    missing = sorted(set(refs) - set(available))
    if missing:
        raise ValidationFailure(f"{label}: unknown references: {', '.join(missing)}")


def _assert_acyclic(flow: FlowSpec) -> None:
    nodes = {node.id: node for node in flow.nodes}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            raise ValidationFailure(f"flow {flow.id}: dependency cycle at {node_id}")
        visiting.add(node_id)
        for dependency in nodes[node_id].depends_on:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in nodes:
        visit(node_id)


def _skill_spec(data: Mapping[str, Any]) -> SkillSpec:
    return SkillSpec(
        id=data["id"],
        version=data["version"],
        invocation_mode=data["invocation_mode"],
        description=data.get("description"),
        leading_words=list(data["leading_words"]),
        capabilities=list(data["capabilities"]),
        inputs=list(data["inputs"]),
        completion_criteria=[CompletionCriterion(**criterion) for criterion in data["completion_criteria"]],
        context_pointers=[ContextPointer(**pointer) for pointer in data["context_pointers"]],
        policy_refs=list(data["policy_refs"]),
        risk_class=data["risk_class"],
        source_path=data["source_path"],
    )


def _flow_spec(data: Mapping[str, Any]) -> FlowSpec:
    return FlowSpec(
        id=data["id"],
        version=data["version"],
        entry_conditions=list(data["entry_conditions"]),
        nodes=[FlowNode(**node) for node in data["nodes"]],
        terminal_conditions=list(data["terminal_conditions"]),
        policy_refs=list(data["policy_refs"]),
    )


def _policy_spec(data: Mapping[str, Any]) -> PolicySpec:
    return PolicySpec(
        id=data["id"],
        version=data["version"],
        policy_class=data["policy_class"],
        immutable=bool(data["immutable"]),
        applies_when=list(data["applies_when"]),
        rules=[PolicyRule(**rule) for rule in data["rules"]],
        required_evidence=list(data["required_evidence"]),
        on_violation=data["on_violation"],
    )


def _provider_spec(data: Mapping[str, Any]) -> CapabilityProviderSpec:
    source = data.get("source")
    return CapabilityProviderSpec(
        id=data["id"],
        version=data["version"],
        mode=data["mode"],
        capability_ids=list(data["capability_ids"]),
        input_schema_ref=data["input_schema_ref"],
        output_schema_ref=data["output_schema_ref"],
        risk_class=data["risk_class"],
        network_policy=data["network_policy"],
        timeout_seconds=data["timeout_seconds"],
        evidence_contract=list(data["evidence_contract"]),
        failure_action=data["failure_action"],
        fallback_provider_id=data.get("fallback_provider_id"),
        source=ProviderSource(**source) if source is not None else None,
        priority=data.get("priority", 0),
    )


def _validate_skill_source(root: Path, skill: SkillSpec) -> None:
    source_root = (root / skill.source_path).resolve()
    if not (source_root / "SKILL.md").is_file():
        compiled_source = (root.parent / "skills" / skill.id).resolve()
        if (compiled_source / "SKILL.md").is_file():
            source_root = compiled_source
    if root not in source_root.parents and root.parent not in source_root.parents:
        raise ValidationFailure(f"skill {skill.id}: source path escapes repository")
    source = source_root / "SKILL.md"
    if not source.is_file():
        raise ValidationFailure(f"skill {skill.id}: missing source {skill.source_path}/SKILL.md")
    lines = source.read_text(encoding="utf-8").splitlines()
    if len(lines) < 4 or lines[0] != "---" or "---" not in lines[1:]:
        raise ValidationFailure(f"skill {skill.id}: invalid SKILL.md frontmatter")
    closing = lines[1:].index("---") + 1
    metadata: dict[str, str] = {}
    for line in lines[1:closing]:
        key, separator, value = line.partition(":")
        if not separator:
            raise ValidationFailure(f"skill {skill.id}: invalid frontmatter line {line!r}")
        metadata[key.strip()] = value.strip()
    if set(metadata) != {"name", "description"}:
        raise ValidationFailure(f"skill {skill.id}: frontmatter must contain only name and description")
    if metadata["name"] != skill.id or metadata["description"] != skill.description:
        raise ValidationFailure(f"skill {skill.id}: catalog and SKILL.md metadata disagree")
    if len(lines) > 500:
        raise ValidationFailure(f"skill {skill.id}: SKILL.md exceeds 500 lines")
    for pointer in skill.context_pointers:
        relative = Path(pointer.path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValidationFailure(f"skill {skill.id}: unsafe context pointer {pointer.path}")
        if not (source_root / relative).is_file():
            raise ValidationFailure(f"skill {skill.id}: missing context pointer {pointer.path}")


def load_catalog(root: Path | str = DEFAULT_REPOSITORY_ROOT, *, require_sources: bool = False) -> Catalog:
    root = Path(root).resolve()
    schemas = root / "schemas"
    skill_doc = load_json(root / "catalog/skills/public.json")
    flow_doc = load_json(root / "catalog/flows/core.json")
    policy_doc = load_json(root / "catalog/policies/core.json")
    capability_doc = load_json(root / "catalog/capabilities/registry.json")
    pack_doc = load_json(root / "catalog/packs/core.json")
    profile_doc = load_json(root / "catalog/profiles/default.json")
    provider_doc = load_json(root / "catalog/providers/core.json")

    skill_data = _unique_by_id(skill_doc.get("skills", []), "skills")
    flow_data = _unique_by_id(flow_doc.get("flows", []), "flows")
    policy_data = _unique_by_id(policy_doc.get("policies", []), "policies")
    capability_data = _unique_by_id(capability_doc.get("capabilities", []), "capabilities")
    pack_data = _unique_by_id(pack_doc.get("packs", []), "packs")
    provider_data = _unique_by_id(provider_doc.get("providers", []), "providers")

    validate_many(skill_data.values(), load_json(schemas / "skill-spec.schema.json"), "skills")
    validate_many(flow_data.values(), load_json(schemas / "flow-spec.schema.json"), "flows")
    validate_many(policy_data.values(), load_json(schemas / "policy-spec.schema.json"), "policies")
    validate_many(pack_data.values(), load_json(schemas / "pack-spec.schema.json"), "packs")
    validate_many(
        provider_data.values(),
        load_json(schemas / "capability-provider-spec.schema.json"),
        "providers",
    )

    versions = {
        skill_doc.get("version"),
        flow_doc.get("version"),
        policy_doc.get("version"),
        capability_doc.get("version"),
        pack_doc.get("version"),
        profile_doc.get("version"),
        provider_doc.get("version"),
    }
    if len(versions) != 1 or None in versions:
        raise ValidationFailure(f"catalog component versions do not agree: {sorted(str(item) for item in versions)}")
    version = next(iter(versions))

    skills = {item_id: _skill_spec(item) for item_id, item in skill_data.items()}
    flows = {item_id: _flow_spec(item) for item_id, item in flow_data.items()}
    policies = {item_id: _policy_spec(item) for item_id, item in policy_data.items()}
    capabilities = {
        item_id: Capability(id=item_id, kind=item["kind"], owner=item["owner"])
        for item_id, item in capability_data.items()
    }
    packs = {
        item_id: Pack(
            id=item_id,
            version=item["version"],
            activation=tuple(item["activation"]),
            capabilities=tuple(item["capabilities"]),
            policy_refs=tuple(item["policy_refs"]),
            source_path=item["source_path"],
        )
        for item_id, item in pack_data.items()
    }
    profile = ProjectProfile(
        id=profile_doc["id"],
        version=profile_doc["version"],
        policy_refs=tuple(profile_doc["policy_refs"]),
        store=profile_doc["store"],
        evidence_broker=profile_doc["evidence_broker"],
        approval_broker=profile_doc["approval_broker"],
        investigation_policy=profile_doc["investigation_policy"],
        evidence_policy=profile_doc["evidence_policy"],
        adapter_preferences=tuple(profile_doc["adapter_preferences"]),
    )
    for broker_name, broker in (
        ("evidence_broker", profile.evidence_broker),
        ("approval_broker", profile.approval_broker),
    ):
        required = ("enabled", "id", "introspection_url", "timeout_seconds")
        if not isinstance(broker.get("enabled"), bool) or any(key not in broker for key in required):
            raise ValidationFailure(f"profile {broker_name} is incomplete")
        if broker["enabled"] and not str(broker["introspection_url"]).startswith("https://"):
            raise ValidationFailure(f"profile {broker_name} requires an HTTPS introspection URL")
    if not isinstance(profile.approval_broker.get("audience"), str) or not profile.approval_broker[
        "audience"
    ].strip():
        raise ValidationFailure("profile approval_broker requires a non-empty audience")
    investigation_mode = profile.investigation_policy.get("default_mode")
    if investigation_mode not in {"auto_readonly", "suggest_then_run", "guided", "disabled"}:
        raise ValidationFailure("profile investigation_policy has an invalid default_mode")
    auto_readonly = profile.investigation_policy.get("auto_readonly", {})
    if not isinstance(auto_readonly.get("enabled"), bool):
        raise ValidationFailure("profile auto_readonly policy requires enabled")
    max_evidence_age = profile.evidence_policy.get("max_age_seconds")
    max_future_skew = profile.evidence_policy.get("max_future_skew_seconds")
    if not isinstance(max_evidence_age, int) or max_evidence_age <= 0:
        raise ValidationFailure("profile evidence_policy requires positive max_age_seconds")
    if not isinstance(max_future_skew, int) or max_future_skew < 0:
        raise ValidationFailure(
            "profile evidence_policy requires non-negative max_future_skew_seconds"
        )
    providers = {
        item_id: _provider_spec(item) for item_id, item in provider_data.items()
    }

    versioned = [
        *skills.values(), *flows.values(), *policies.values(), *packs.values(),
        *providers.values(), profile,
    ]
    mismatched = sorted(item.id for item in versioned if item.version != version)
    if mismatched:
        raise ValidationFailure(f"catalog entries have mismatched versions: {', '.join(mismatched)}")

    for skill in skills.values():
        _assert_refs(skill.capabilities, capabilities, f"skill {skill.id} capabilities")
        _assert_refs(skill.policy_refs, policies, f"skill {skill.id} policies")
        for capability_id in skill.capabilities:
            capability = capabilities[capability_id]
            if capability.kind != "primitive" or capability.owner != skill.id:
                raise ValidationFailure(
                    f"skill {skill.id}: capability {capability_id} must be its owned primitive"
                )
        if require_sources:
            _validate_skill_source(root, skill)

    for flow in flows.values():
        node_ids = {node.id for node in flow.nodes}
        if len(node_ids) != len(flow.nodes):
            raise ValidationFailure(f"flow {flow.id}: duplicate node id")
        _assert_refs(flow.policy_refs, policies, f"flow {flow.id} policies")
        for node in flow.nodes:
            _assert_refs(node.depends_on, {item: True for item in node_ids}, f"flow {flow.id} node {node.id} dependencies")
            if node.id in node.depends_on:
                raise ValidationFailure(f"flow {flow.id} node {node.id}: self dependency")
            _assert_refs([node.capability], capabilities, f"flow {flow.id} node {node.id} capability")
            _assert_refs(node.policy_refs, policies, f"flow {flow.id} node {node.id} policies")
        _assert_acyclic(flow)

    _assert_refs(profile.policy_refs, policies, f"profile {profile.id} policies")
    for provider in providers.values():
        _assert_refs(
            provider.capability_ids,
            capabilities,
            f"provider {provider.id} capabilities",
        )
        if provider.fallback_provider_id is not None:
            _assert_refs(
                [provider.fallback_provider_id],
                providers,
                f"provider {provider.id} fallback",
            )
            if provider.fallback_provider_id == provider.id:
                raise ValidationFailure(f"provider {provider.id}: fallback cannot reference itself")
        for contract_ref in (provider.input_schema_ref, provider.output_schema_ref):
            relative = Path(contract_ref)
            if relative.is_absolute() or ".." in relative.parts or not (root / relative).is_file():
                raise ValidationFailure(
                    f"provider {provider.id}: invalid schema reference {contract_ref}"
                )
    for capability_id in capabilities:
        candidates = [
            provider for provider in providers.values()
            if capability_id in provider.capability_ids
        ]
        if not candidates:
            continue
        highest = max(provider.priority for provider in candidates)
        selected = sorted(provider.id for provider in candidates if provider.priority == highest)
        if len(selected) != 1:
            raise ValidationFailure(
                f"capability {capability_id}: ambiguous highest priority providers: "
                + ", ".join(selected)
            )
    for pack in packs.values():
        _assert_refs(pack.capabilities, capabilities, f"pack {pack.id} capabilities")
        _assert_refs(pack.policy_refs, policies, f"pack {pack.id} policies")
        for capability_id in pack.capabilities:
            capability = capabilities[capability_id]
            if capability.kind != "pack" or capability.owner != f"pack:{pack.id}":
                raise ValidationFailure(
                    f"pack {pack.id}: capability {capability_id} ownership is {capability.owner}"
                )
        if require_sources:
            authored_source = root / pack.source_path
            compiled_source = root / "packs" / Path(pack.source_path).name
            if not authored_source.is_file() and not compiled_source.is_file():
                raise ValidationFailure(f"pack {pack.id}: missing source {pack.source_path}")
    declared_pack_capabilities = {
        capability_id for pack in packs.values() for capability_id in pack.capabilities
    }
    registered_pack_capabilities = {
        capability.id for capability in capabilities.values() if capability.kind == "pack"
    }
    if declared_pack_capabilities != registered_pack_capabilities:
        raise ValidationFailure(
            "pack capability registry mismatch: "
            f"missing={sorted(registered_pack_capabilities - declared_pack_capabilities)}, "
            f"extra={sorted(declared_pack_capabilities - registered_pack_capabilities)}"
        )
    return Catalog(
        root=root,
        version=version,
        skills=skills,
        flows=flows,
        policies=policies,
        capabilities=capabilities,
        packs=packs,
        profiles={profile.id: profile},
        providers=providers,
    )
