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
class ProductSpec:
    id: str
    display_name: str
    description: str
    developer: str
    root_skill_id: str
    default_profile_id: str


@dataclass(frozen=True)
class ProjectProfile:
    id: str
    version: str
    policy_refs: tuple[str, ...]
    store: Mapping[str, Any]
    local_approval: Mapping[str, tuple[str, ...]]
    investigation_policy: Mapping[str, Any]
    evidence_policy: Mapping[str, Any]
    adapter_preferences: tuple[str, ...]
    pack_refs: tuple[str, ...]
    rule_catalog_ref: str | None


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
class TeamRuleSource:
    id: str
    title: str
    url: str
    digest: str
    topics: tuple[str, ...]


@dataclass(frozen=True)
class TeamRule:
    id: str
    category: str
    guidance: str
    source_refs: tuple[str, ...]
    target_refs: tuple[str, ...]
    capability_refs: tuple[str, ...]


@dataclass(frozen=True)
class TeamRuleCatalog:
    id: str
    version: str
    profile_id: str
    sources: Mapping[str, TeamRuleSource]
    rules: Mapping[str, TeamRule]


@dataclass(frozen=True)
class Catalog:
    root: Path
    version: str
    product: ProductSpec
    skills: Mapping[str, SkillSpec]
    flows: Mapping[str, FlowSpec]
    policies: Mapping[str, PolicySpec]
    capabilities: Mapping[str, Capability]
    packs: Mapping[str, Pack]
    profiles: Mapping[str, ProjectProfile]
    providers: Mapping[str, CapabilityProviderSpec]
    sources: Mapping[str, SourceDecision]
    rule_catalogs: Mapping[str, TeamRuleCatalog]

    @property
    def default_profile(self) -> ProjectProfile:
        return self.profiles[self.product.default_profile_id]

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

    def rules_for_capability(self, profile_id: str, capability_id: str) -> tuple[TeamRule, ...]:
        profile = self.profiles[profile_id]
        if not profile.rule_catalog_ref:
            return ()
        rules = self.rule_catalogs[profile.rule_catalog_ref].rules.values()
        return tuple(rule for rule in rules if capability_id in rule.capability_refs
                     and set(rule.target_refs).intersection(profile.pack_refs))


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


def _load_component_documents(
    directory: Path,
    collection_key: str,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    paths = sorted(path for path in directory.glob("*.json") if path.is_file())
    if not paths:
        raise ValidationFailure(f"catalog component directory is empty: {directory}")
    documents = [load_json(path) for path in paths]
    items: list[Mapping[str, Any]] = []
    for path, document in zip(paths, documents):
        if set(document) != {"version", collection_key}:
            raise ValidationFailure(
                f"catalog component {path.name} must contain only version and {collection_key}"
            )
        collection = document.get(collection_key)
        if not isinstance(collection, list):
            raise ValidationFailure(f"catalog component {path.name} has invalid {collection_key}")
        items.extend(collection)
    return documents, items


def _load_profile_documents(directory: Path) -> list[Mapping[str, Any]]:
    paths = sorted(path for path in directory.glob("*.json") if path.is_file())
    if not paths:
        raise ValidationFailure(f"catalog profile directory is empty: {directory}")
    return [load_json(path) for path in paths]


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
    product_doc = load_json(root / "catalog/product.json")
    skill_doc = load_json(root / "catalog/skills/public.json")
    flow_docs, flow_items = _load_component_documents(root / "catalog/flows", "flows")
    policy_docs, policy_items = _load_component_documents(
        root / "catalog/policies", "policies"
    )
    capability_doc = load_json(root / "catalog/capabilities/registry.json")
    pack_docs, pack_items = _load_component_documents(root / "catalog/packs", "packs")
    profile_docs = _load_profile_documents(root / "catalog/profiles")
    rule_catalog_docs = _load_profile_documents(root / "catalog/rules")
    provider_doc = load_json(root / "catalog/providers/core.json")
    source_doc = load_json(root / "catalog/sources/open-source.json")

    skill_data = _unique_by_id(skill_doc.get("skills", []), "skills")
    flow_data = _unique_by_id(flow_items, "flows")
    policy_data = _unique_by_id(policy_items, "policies")
    capability_data = _unique_by_id(capability_doc.get("capabilities", []), "capabilities")
    pack_data = _unique_by_id(pack_items, "packs")
    profile_data = _unique_by_id(profile_docs, "profiles")
    rule_catalog_data = _unique_by_id(rule_catalog_docs, "rule catalogs")
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
        profile_data.values(),
        load_json(schemas / "project-profile.schema.json"),
        "profiles",
    )
    validate_many(
        rule_catalog_data.values(),
        load_json(schemas / "team-rule-catalog.schema.json"),
        "rule catalogs",
    )
    validate_many(
        [product_doc],
        load_json(schemas / "product-spec.schema.json"),
        "product",
    )
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
        *(document.get("version") for document in flow_docs),
        *(document.get("version") for document in policy_docs),
        capability_doc.get("version"),
        *(document.get("version") for document in pack_docs),
        *(document.get("version") for document in profile_docs),
        *(document.get("version") for document in rule_catalog_docs),
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
    profiles = {
        item_id: ProjectProfile(
            id=item["id"],
            version=item["version"],
            policy_refs=tuple(item["policy_refs"]),
            store=item["store"],
            local_approval={
                approval_id: tuple(actor_refs)
                for approval_id, actor_refs in item["local_approval"].items()
            },
            investigation_policy=item["investigation_policy"],
            evidence_policy=item["evidence_policy"],
            adapter_preferences=tuple(item["adapter_preferences"]),
            pack_refs=tuple(item["pack_refs"]),
            rule_catalog_ref=item.get("rule_catalog_ref"),
        )
        for item_id, item in profile_data.items()
    }
    for profile in profiles.values():
        if not profile.local_approval or any(
            not actors or any(not actor.strip() for actor in actors)
            for actors in profile.local_approval.values()
        ):
            raise ValidationFailure(f"profile {profile.id} local_approval is incomplete")
        investigation_mode = profile.investigation_policy.get("default_mode")
        if investigation_mode not in {"auto_readonly", "suggest_then_run", "guided", "disabled"}:
            raise ValidationFailure(
                f"profile {profile.id} investigation_policy has an invalid default_mode"
            )
        auto_readonly = profile.investigation_policy.get("auto_readonly", {})
        if not isinstance(auto_readonly.get("enabled"), bool):
            raise ValidationFailure(
                f"profile {profile.id} auto_readonly policy requires enabled"
            )
        max_evidence_age = profile.evidence_policy.get("max_age_seconds")
        max_future_skew = profile.evidence_policy.get("max_future_skew_seconds")
        if not isinstance(max_evidence_age, int) or max_evidence_age <= 0:
            raise ValidationFailure(
                f"profile {profile.id} evidence_policy requires positive max_age_seconds"
            )
        if not isinstance(max_future_skew, int) or max_future_skew < 0:
            raise ValidationFailure(
                f"profile {profile.id} evidence_policy requires non-negative max_future_skew_seconds"
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
    product = ProductSpec(
        id=product_doc["id"],
        display_name=product_doc["display_name"],
        description=product_doc["description"],
        developer=product_doc["developer"],
        root_skill_id=product_doc["root_skill_id"],
        default_profile_id=product_doc["default_profile_id"],
    )
    rule_catalogs: dict[str, TeamRuleCatalog] = {}
    for item_id, item in rule_catalog_data.items():
        source_items = _unique_by_id(item["sources"], f"rule catalog {item_id} sources")
        rule_items = _unique_by_id(item["rules"], f"rule catalog {item_id} rules")
        rule_catalogs[item_id] = TeamRuleCatalog(
            id=item_id,
            version=item["version"],
            profile_id=item["profile_id"],
            sources={
                source_id: TeamRuleSource(
                    id=source_id,
                    title=source["title"],
                    url=source["url"],
                    digest=source["digest"],
                    topics=tuple(source["topics"]),
                )
                for source_id, source in source_items.items()
            },
            rules={
                rule_id: TeamRule(
                    id=rule_id,
                    category=rule["category"],
                    guidance=rule["guidance"],
                    source_refs=tuple(rule["source_refs"]),
                    target_refs=tuple(rule["target_refs"]),
                    capability_refs=tuple(rule["capability_refs"]),
                )
                for rule_id, rule in rule_items.items()
            },
        )

    versioned = [
        *skills.values(), *flows.values(), *policies.values(), *packs.values(),
        *providers.values(), *profiles.values(), *rule_catalogs.values(),
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
            undeclared_required_kinds = sorted(
                set(node.required_evidence_kinds) - set(node.evidence_kinds)
            )
            if undeclared_required_kinds:
                raise ValidationFailure(
                    f"flow {flow.id} node {node.id}: required evidence kinds are not allowed: "
                    + ", ".join(undeclared_required_kinds)
                )
        _assert_acyclic(flow)

    if product.root_skill_id not in skills:
        raise ValidationFailure(
            f"product root skill is unknown: {product.root_skill_id}"
        )
    if product.default_profile_id not in profiles:
        raise ValidationFailure(
            f"product default profile is unknown: {product.default_profile_id}"
        )
    for profile in profiles.values():
        _assert_refs(profile.policy_refs, policies, f"profile {profile.id} policies")
        _assert_refs(profile.pack_refs, packs, f"profile {profile.id} packs")
        if profile.rule_catalog_ref is not None:
            if profile.rule_catalog_ref not in rule_catalogs:
                raise ValidationFailure(
                    f"profile {profile.id} rule catalog is unknown: {profile.rule_catalog_ref}"
                )
            if rule_catalogs[profile.rule_catalog_ref].profile_id != profile.id:
                raise ValidationFailure(
                    f"profile {profile.id} rule catalog targets another profile"
                )
    for rule_catalog in rule_catalogs.values():
        if rule_catalog.profile_id not in profiles:
            raise ValidationFailure(
                f"rule catalog {rule_catalog.id} profile is unknown: {rule_catalog.profile_id}"
            )
        for source in rule_catalog.sources.values():
            if (
                Path(source.url).is_absolute()
                or source.url.casefold().startswith("file:")
                or "\\" in source.url
            ):
                raise ValidationFailure(
                    f"rule catalog {rule_catalog.id} source {source.id} uses a local path"
                )
        for rule in rule_catalog.rules.values():
            _assert_refs(
                rule.source_refs,
                rule_catalog.sources,
                f"rule catalog {rule_catalog.id} rule {rule.id} sources",
            )
            _assert_refs(
                rule.target_refs,
                packs,
                f"rule catalog {rule_catalog.id} rule {rule.id} targets",
            )
            _assert_refs(
                rule.capability_refs,
                capabilities,
                f"rule catalog {rule_catalog.id} rule {rule.id} capabilities",
            )
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
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not any(candidate.exists() for candidate in candidates)
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
        product=product,
        skills=skills,
        flows=flows,
        policies=policies,
        capabilities=capabilities,
        packs=packs,
        profiles=profiles,
        providers=providers,
        sources=sources,
        rule_catalogs=rule_catalogs,
    )
