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


def _default_repository_root(module_path: Path) -> Path:
    package = module_path.resolve().parents[1]
    assets = package / "_assets"
    return assets if (assets / "catalog").is_dir() else package.parents[1]


DEFAULT_REPOSITORY_ROOT = _default_repository_root(Path(__file__))
REQUIRED_OPEN_SOURCE_IDS = frozenset(
    {
        "anthropic-skills",
        "obra-superpowers",
        "addyosmani-agent-skills",
        "taste-skill",
        "ui-ux-pro-max-skill",
        "ux-ui-agent-skills",
    }
)


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
class SourceDecision:
    id: str
    version: str
    repository_url: str
    revision: str
    license: str
    license_evidence: tuple[str, ...]
    evidence_digests: Mapping[str, str]
    integrity: str | None
    decision: str
    rationale: str
    evidence_paths: tuple[str, ...]
    target_refs: tuple[str, ...]
    provider_id: str | None


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
    sources: Mapping[str, SourceDecision]

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
    source_doc = load_json(root / "catalog/sources/open-source.json")

    skill_data = _unique_by_id(skill_doc.get("skills", []), "skills")
    flow_data = _unique_by_id(flow_doc.get("flows", []), "flows")
    policy_data = _unique_by_id(policy_doc.get("policies", []), "policies")
    capability_data = _unique_by_id(capability_doc.get("capabilities", []), "capabilities")
    pack_data = _unique_by_id(pack_doc.get("packs", []), "packs")
    provider_data = _unique_by_id(provider_doc.get("providers", []), "providers")
    source_data = _unique_by_id(source_doc.get("sources", []), "sources")
    if set(source_doc) != {"version", "review_scope", "sources"}:
        raise ValidationFailure(
            "source registry must contain only version, review_scope and sources"
        )
    review_scope = source_doc.get("review_scope")
    if (
        not isinstance(review_scope, list)
        or not review_scope
        or any(not isinstance(item, str) or not item for item in review_scope)
        or len(review_scope) != len(set(review_scope))
        or set(review_scope) != REQUIRED_OPEN_SOURCE_IDS
        or set(source_data) != REQUIRED_OPEN_SOURCE_IDS
    ):
        raise ValidationFailure(
            "source registry review scope must match source decisions exactly"
        )

    validate_many(skill_data.values(), load_json(schemas / "skill-spec.schema.json"), "skills")
    validate_many(flow_data.values(), load_json(schemas / "flow-spec.schema.json"), "flows")
    validate_many(policy_data.values(), load_json(schemas / "policy-spec.schema.json"), "policies")
    validate_many(pack_data.values(), load_json(schemas / "pack-spec.schema.json"), "packs")
    validate_many(
        provider_data.values(),
        load_json(schemas / "capability-provider-spec.schema.json"),
        "providers",
    )
    validate_many(
        source_data.values(),
        load_json(schemas / "source-decision.schema.json"),
        "sources",
    )

    versions = {
        skill_doc.get("version"),
        flow_doc.get("version"),
        policy_doc.get("version"),
        capability_doc.get("version"),
        pack_doc.get("version"),
        profile_doc.get("version"),
        provider_doc.get("version"),
        source_doc.get("version"),
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
        investigation_policy=profile_doc["investigation_policy"],
        evidence_policy=profile_doc["evidence_policy"],
        adapter_preferences=tuple(profile_doc["adapter_preferences"]),
    )
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
    sources = {
        item_id: SourceDecision(
            id=item["id"],
            version=item["version"],
            repository_url=item["repository_url"],
            revision=item["revision"],
            license=item["license"],
            license_evidence=tuple(item["license_evidence"]),
            evidence_digests=dict(item["evidence_digests"]),
            integrity=item.get("integrity"),
            decision=item["decision"],
            rationale=item["rationale"],
            evidence_paths=tuple(item["evidence_paths"]),
            target_refs=tuple(item["target_refs"]),
            provider_id=item.get("provider_id"),
        )
        for item_id, item in source_data.items()
    }

    versioned = [
        *skills.values(), *flows.values(), *policies.values(), *packs.values(),
        *providers.values(), profile,
        *sources.values(),
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
    for source in sources.values():
        expected_evidence_paths = set(source.license_evidence) | set(source.evidence_paths)
        if set(source.evidence_digests) != expected_evidence_paths:
            raise ValidationFailure(
                f"source {source.id}: evidence digests must exactly cover license and review evidence paths"
            )
        for upstream_path in (*source.license_evidence, *source.evidence_paths):
            segments = upstream_path.split("/")
            if (
                upstream_path.startswith("/")
                or upstream_path.endswith("/")
                or "\\" in upstream_path
                or ":" in upstream_path
                or any(segment in {"", ".", ".."} for segment in segments)
            ):
                raise ValidationFailure(
                    f"source {source.id}: unsafe upstream evidence path {upstream_path}"
                )
        if source.provider_id is not None:
            _assert_refs(
                [source.provider_id],
                providers,
                f"source {source.id} provider",
            )
            provider_source = providers[source.provider_id].source
            normalized_source_url = source.repository_url.rstrip("/").removesuffix(".git")
            normalized_provider_url = (
                provider_source.url.rstrip("/").removesuffix(".git")
                if provider_source is not None
                else None
            )
            if (
                provider_source is None
                or provider_source.revision != source.revision
                or normalized_provider_url != normalized_source_url
                or provider_source.license != source.license
                or provider_source.integrity != source.integrity
            ):
                raise ValidationFailure(
                    f"source {source.id}: URL, revision, license and integrity must match provider {source.provider_id}"
                )
        if require_sources:
            consumer_assets = (root.name == "_assets"
                               and (root.parent / "runtime/catalog.py").is_file()
                               and not (root / "src").exists())
            for target_ref in source.target_refs:
                relative = Path(target_ref)
                candidates = [root / relative]
                if relative.parts and relative.parts[0] == "skills":
                    candidates.append(root.parent / relative)
                if relative.parts[:2] == ("src", "engineering_assistant"):
                    candidates.append(
                        root
                        / "runtime/engineering_assistant"
                        / Path(*relative.parts[2:])
                    )
                    if root.name == "_assets":
                        candidates.append(root.parent / Path(*relative.parts[2:]))
                # The wheel retains provenance for author integrations, while
                # its distribution contract deliberately excludes author tools.
                # Author checkouts and all consumer Runtime references stay strict.
                author_only = (consumer_assets
                               and relative.parts[:3] == ("src", "engineering_assistant", "tools"))
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or (not author_only and not any(candidate.exists() for candidate in candidates))
                ):
                    raise ValidationFailure(
                        f"source {source.id}: invalid target reference {target_ref}"
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
        sources=sources,
    )
