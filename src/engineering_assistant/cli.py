"""Command-line contract for the engineering-assistant kernel."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import canary_limits
from .artifact_validation import ARTIFACT_SCHEMAS
from .artifact_io import ArtifactConflict, ArtifactIO
from .canary import import_canary_attestation, prepare_canary_bundle
from .canary_protocol import (
    MAX_AUDIT_INPUT_FILE_BYTES,
    MAX_AUDIT_INPUT_FILES,
    MAX_AUDIT_INPUT_TOTAL_BYTES,
    audit_canary_protocol,
)
from .catalog import DEFAULT_REPOSITORY_ROOT, load_catalog
from .codec import (
    evidence_ref_from_dict,
    investigation_decision_grant_from_dict,
    investigation_request_from_dict,
    quality_snapshot_from_dict,
    run_approval_grant_from_dict,
    route_intent_from_dict,
    step_result_from_dict,
)
from .compiler import build_package, verify_package
from .design_source import (
    check_design_source,
    read_design_document,
    resolve_design_source,
    validate_database_design,
    validate_review_package,
)
from .engine import RuntimeEngine
from .evidence import EvidenceStore
from .governance import (
    InvestigationStore,
    QualityGate,
    QualityStore,
    investigation_evidence_contract,
)
from .feedback import (
    FeedbackStore,
    export_feedback_evolution,
    summarize_usage_efficiency,
)
from .model import DesignSourceRef, FeedbackDisposition
from .eval_runner import assemble_canary_result, run_canary_result, run_evals
from .mcp_server import MCPServer, RuntimeTools, serve_stdio
from .router import route_intent
from .state_store import StateStore
from .source_verification import verify_source_checkouts
from .trust import trust_bindings_from_host
from .validation import ValidationFailure, load_json, validate_instance


def _json_input(value: str) -> dict:
    if value == "-":
        return json.load(sys.stdin)
    return load_json(Path(value))


def _emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _stores(args: argparse.Namespace, catalog):
    profile = catalog.profiles[args.profile]
    state_store = StateStore(args.project_root, catalog.root / "schemas", profile.store["run_root"])
    verifier = getattr(args, "trust_verifier", None)
    return state_store, EvidenceStore(state_store, verifier)


def _load_state(state_store: StateStore, run_id: str, profile_id: str):
    state = state_store.load(run_id)
    if state.profile_id != profile_id:
        raise ValueError(
            f"run {run_id} is bound to profile {state.profile_id}, not {profile_id}"
        )
    return state


def command_route(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    payload = _json_input(args.intent)
    validate_instance(payload, load_json(catalog.root / "schemas/route-intent.schema.json"), "route-intent")
    _emit(route_intent(route_intent_from_dict(payload), catalog, profile_id=args.profile).to_dict())
    return 0


def command_start(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    payload = _json_input(args.intent)
    validate_instance(payload, load_json(catalog.root / "schemas/route-intent.schema.json"), "route-intent")
    state = RuntimeEngine(catalog).start(
        args.task_id,
        route_intent_from_dict(payload),
        profile_id=args.profile,
        run_id=args.run_id,
        context_refs=args.context_ref,
    )
    state_store, _ = _stores(args, catalog)
    path = state_store.create(state)
    _emit({"state": state.to_dict(), "state_path": str(path)})
    return 0


def command_next(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, _ = _stores(args, catalog)
    state = _load_state(state_store, args.run_id, args.profile)
    previous_revision = state.revision
    engine = RuntimeEngine(catalog)
    gate = engine.next(state)
    if state.revision != previous_revision:
        state_store.save(state, expected_revision=previous_revision)
    _emit({"gate": gate.to_dict(), "node": engine.node_payload(state), "state": state.to_dict()})
    return 0


def command_approval_import(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, evidence_store = _stores(args, catalog)
    grant = run_approval_grant_from_dict(_json_input(args.grant))
    state = _load_state(state_store, grant.run_id, args.profile)
    previous_revision = state.revision
    broker = args.approval_broker
    if not broker.get("enabled"):
        raise ValueError("external approval broker is not enabled for this profile")
    gate = RuntimeEngine(catalog).apply_approval(
        state,
        grant,
        verifier=evidence_store.trust_verifier,
        expected_broker_id=str(broker["id"]),
        expected_audience=str(broker["audience"]),
    )
    state_store.save(state, expected_revision=previous_revision)
    _emit({"gate": gate.to_dict(), "state": state.to_dict()})
    return 0


def command_complete(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, evidence_store = _stores(args, catalog)
    state = _load_state(state_store, args.run_id, args.profile)
    previous_revision = state.revision
    result = step_result_from_dict(_json_input(args.result))
    engine = RuntimeEngine(catalog)
    gate = engine.complete_step(
        state,
        result,
        evidence_store=evidence_store,
        evidence_max_age_seconds=args.evidence_max_age_seconds,
    )
    state_store.save(state, expected_revision=previous_revision)
    _emit({"gate": gate.to_dict(), "node": engine.node_payload(state), "state": state.to_dict()})
    return 0


def command_quality_submit(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, evidence_store = _stores(args, catalog)
    snapshot = quality_snapshot_from_dict(_json_input(args.snapshot))
    state = _load_state(state_store, snapshot.run_id, args.profile)
    if state.current_node != snapshot.node_id:
        raise ValueError("quality snapshot does not match the active run and node")
    saved = QualityStore(state_store, evidence_store).save(
        snapshot,
        current_state_revision=state.revision,
    )
    _emit({"snapshot": saved.to_dict(), "gate": QualityGate.evaluate(saved).to_dict()})
    return 0


def command_investigation_propose(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, _ = _stores(args, catalog)
    request = investigation_request_from_dict(_json_input(args.request))
    _load_state(state_store, request.run_id, args.profile)
    profile = catalog.profiles[args.profile]
    record = InvestigationStore(state_store).propose(
        request, investigation_policy=dict(profile.investigation_policy)
    )
    _emit(
        {
            "record": record.to_dict(),
            "evidence_contract": investigation_evidence_contract(record),
            "approval_required": record.request.status == "proposed",
        }
    )
    return 0


def command_investigation_list(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, _ = _stores(args, catalog)
    _load_state(state_store, args.run_id, args.profile)
    records, next_after_id = InvestigationStore(state_store).list(
        args.run_id,
        limit=args.limit,
        after_id=args.after_id,
    )
    _emit(
        {
            "records": [item.to_dict() for item in records],
            "evidence_contracts": {
                item.request.id: investigation_evidence_contract(item)
                for item in records
            },
            "next_after_id": next_after_id,
        }
    )
    return 0


def command_investigation_approval_import(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, evidence_store = _stores(args, catalog)
    grant = investigation_decision_grant_from_dict(_json_input(args.grant))
    state = _load_state(state_store, grant.run_id, args.profile)
    broker = args.approval_broker
    if not broker.get("enabled"):
        raise ValueError("external approval broker is not enabled for this profile")
    record = InvestigationStore(state_store).apply_grant(
        grant,
        verifier=evidence_store.trust_verifier,
        current_run_revision=state.revision,
        expected_broker_id=str(broker["id"]),
        expected_audience=str(broker["audience"]),
    )
    _emit(
        {
            "record": record.to_dict(),
            "evidence_contract": investigation_evidence_contract(record),
        }
    )
    return 0


def command_investigation_start(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, _ = _stores(args, catalog)
    _load_state(state_store, args.run_id, args.profile)
    record = InvestigationStore(state_store).start(args.run_id, args.investigation_id)
    _emit(
        {
            "record": record.to_dict(),
            "evidence_contract": investigation_evidence_contract(record),
        }
    )
    return 0


def command_investigation_finish(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, evidence_store = _stores(args, catalog)
    _load_state(state_store, args.run_id, args.profile)
    record = InvestigationStore(state_store, evidence_store).finish(
        args.run_id,
        args.investigation_id,
        outcome=args.outcome,
        evidence_refs=args.evidence_ref,
    )
    _emit(
        {
            "record": record.to_dict(),
            "evidence_contract": investigation_evidence_contract(record),
        }
    )
    return 0


def command_evidence_import(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, evidence_store = _stores(args, catalog)
    _load_state(state_store, args.run_id, args.profile)
    saved = evidence_store.save(args.run_id, evidence_ref_from_dict(_json_input(args.evidence)))
    _emit({"evidence": saved.to_dict()})
    return 0


def command_validate(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root, require_sources=args.require_sources)
    _emit(
        {
            "status": "passed",
            "version": catalog.version,
            "skills": len(catalog.skills),
            "flows": len(catalog.flows),
            "policies": len(catalog.policies),
            "packs": len(catalog.packs),
            "profiles": len(catalog.profiles),
            "rule_catalogs": len(catalog.rule_catalogs),
            "team_rules": sum(
                len(rule_catalog.rules)
                for rule_catalog in catalog.rule_catalogs.values()
            ),
            "team_rule_sources": sum(
                len(rule_catalog.sources)
                for rule_catalog in catalog.rule_catalogs.values()
            ),
            "providers": len(catalog.providers),
            "sources": len(catalog.sources),
            "sources_required": args.require_sources,
        }
    )
    return 0


def command_artifact_validate(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    payload = _json_input(args.input)
    validate_instance(
        payload,
        load_json(catalog.root / "schemas" / ARTIFACT_SCHEMAS[args.kind]),
        args.kind,
    )
    _emit({"status": "passed", "kind": args.kind, "input": str(args.input)})
    return 0


def _design_source_ref(args: argparse.Namespace) -> DesignSourceRef:
    return DesignSourceRef(root=args.source_root, registry=args.registry)


def command_design_source_resolve(args: argparse.Namespace) -> int:
    _emit(resolve_design_source(_design_source_ref(args)))
    return 0


def command_design_source_read(args: argparse.Namespace) -> int:
    _emit(read_design_document(_design_source_ref(args), args.document))
    return 0


def command_design_source_check(args: argparse.Namespace) -> int:
    report = check_design_source(
        _design_source_ref(args), args.expected_digest, args.document
    )
    _emit(report)
    return 0 if report["status"] == "current" else 3


def command_review_package_validate(args: argparse.Namespace) -> int:
    _emit(validate_review_package(args.package, args.requirement_id))
    return 0


def command_database_design_validate(args: argparse.Namespace) -> int:
    _emit(validate_database_design(args.document))
    return 0


def command_verify_sources(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root, require_sources=True)
    roots: dict[str, Path] = {}
    for value in args.source:
        source_id, separator, path = value.partition("=")
        if not separator or not source_id or not path:
            raise ValidationFailure("source checkout must use SOURCE_ID=/absolute/path")
        if source_id in roots:
            raise ValidationFailure(f"duplicate source checkout: {source_id}")
        roots[source_id] = Path(path)
    _emit(verify_source_checkouts(catalog, roots))
    return 0


def command_build(args: argparse.Namespace) -> int:
    report = build_package(
        args.repository_root,
        args.platform,
        args.output,
        replace=args.replace,
    )
    _emit(report)
    return 0


def command_verify_package(args: argparse.Namespace) -> int:
    _emit({"status": "passed", "manifest": verify_package(args.package)})
    return 0


def command_eval(args: argparse.Namespace) -> int:
    report = run_evals(args.repository_root)
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _emit(report)
    return 0


def command_canary_validate(args: argparse.Namespace) -> int:
    broker_id, config_digest = _canary_trust_provenance(args)
    report = run_canary_result(
        args.result,
        trust_verifier=args.trust_verifier,
        expected_evidence_broker_id=broker_id,
        expected_host_trust_config_digest=config_digest,
    )
    _emit(report)
    return 0 if report["status"] == "passed" else 2


def command_canary_audit(args: argparse.Namespace) -> int:
    repository_root = Path(args.repository_root).resolve()
    input_paths = [
        Path(args.protocol),
        *(Path(path) for path in args.run_record),
        Path(args.inclusion_manifest),
    ]
    if len(input_paths) > MAX_AUDIT_INPUT_FILES:
        raise ValidationFailure("canary audit input file count exceeds limit")
    inputs = []
    total_bytes = 0
    for path in input_paths:
        if path.is_symlink():
            raise ValidationFailure("canary audit input cannot be a symlink")
        resolved = path.resolve()
        source = ArtifactIO(resolved.parent, ".")
        try:
            payload, raw = source.read_json_limited(
                MAX_AUDIT_INPUT_FILE_BYTES,
                resolved.name,
            )
        finally:
            source.close()
        total_bytes += len(raw)
        if total_bytes > MAX_AUDIT_INPUT_TOTAL_BYTES:
            raise ValidationFailure("canary audit input bytes exceed limit")
        inputs.append(payload)
    report = audit_canary_protocol(
        inputs[0],
        inputs[1:-1],
        inputs[-1],
        schema_root=repository_root / "evals/canary",
        evidence_root=args.evidence_root,
    )
    _emit(report)
    if report["status"] in {
        "local_structural",
        "legacy_unverifiable",
    }:
        return 3
    return 2


def command_canary_prepare(args: argparse.Namespace) -> int:
    broker_id, config_digest = _canary_trust_provenance(args)
    _emit(
        prepare_canary_bundle(
            args.manifest,
            args.output,
            repository_root=args.repository_root,
            evidence_broker_id=broker_id,
            host_trust_config_digest=config_digest,
        )
    )
    return 0


def command_canary_assemble(args: argparse.Namespace) -> int:
    broker_id, config_digest = _canary_trust_provenance(args)
    evidence_root = Path(args.evidence_root).resolve()
    artifacts = ArtifactIO(evidence_root, ".")
    artifacts.assert_runtime_target(
        Path(args.repository_root).resolve() / "schemas"
    )
    output_reference = Path(args.output)
    result = assemble_canary_result(
        evidence_root,
        args.evidence_ref,
        trust_verifier=args.trust_verifier,
        expected_evidence_broker_id=broker_id,
        expected_host_trust_config_digest=config_digest,
        artifact_io=artifacts,
    )
    try:
        output, created = artifacts.create_immutable_json_with_status(
            result,
            *output_reference.parts,
            existing_max_bytes=canary_limits.MAX_OBSERVATION_BYTES,
        )
    except ArtifactConflict as exc:
        raise ValidationFailure("canary assembly output already exists with different content") from exc
    _emit(
        {
            "status": "assembled" if created else "already_assembled",
            "result_path": str(output),
            "result": result,
        }
    )
    return 0


def command_canary_attestation_import(args: argparse.Namespace) -> int:
    broker_id, config_digest = _canary_trust_provenance(args)
    _emit(
        import_canary_attestation(
            args.evidence_root,
            args.draft_ref,
            args.response_ref,
            args.output,
            trust_verifier=args.trust_verifier,
            evidence_broker_id=broker_id,
            host_trust_config_digest=config_digest,
            repository_root=args.repository_root,
        )
    )
    return 0


def _canary_trust_provenance(args: argparse.Namespace) -> tuple[str, str]:
    broker = args.evidence_broker
    digest = args.host_trust_config_digest
    if args.trust_verifier is None or not broker.get("enabled") or not digest:
        raise ValidationFailure(
            "canary commands require an administrator-bound external evidence broker"
        )
    return str(broker["id"]), str(digest)


def command_feedback_summary(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    _emit(
        summarize_usage_efficiency(
            args.project_root,
            catalog.root / "schemas",
        )
    )
    return 0


def command_feedback_disposition(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    payload = load_json(Path(args.input))
    disposition = FeedbackDisposition(**payload)
    created = FeedbackStore(
        args.project_root,
        catalog.root / "schemas",
    ).save_disposition(disposition)
    _emit({"status": "created" if created else "already_exists", "disposition_id": disposition.disposition_id})
    return 0


def command_feedback_evolution_export(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    _emit(
        export_feedback_evolution(
            args.project_root,
            catalog.root / "schemas",
            limit=args.limit,
            after_event_ref=args.after_event_ref,
            snapshot_revision=args.snapshot_revision,
        )
    )
    return 0


def command_mcp_serve(args: argparse.Namespace) -> int:
    return serve_stdio(
        MCPServer(
            RuntimeTools(
                args.repository_root,
                trust_verifier=args.trust_verifier,
                evidence_broker_enabled=bool(args.evidence_broker.get("enabled")),
                approval_broker_enabled=bool(args.approval_broker.get("enabled")),
            )
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ea")
    parser.add_argument("--repository-root", default=str(DEFAULT_REPOSITORY_ROOT))
    parser.add_argument("--profile")
    subparsers = parser.add_subparsers(dest="command", required=True)

    route = subparsers.add_parser("route")
    route.add_argument("--intent", required=True, help="RouteIntent JSON path or - for stdin")
    route.set_defaults(handler=command_route)

    start = subparsers.add_parser("start")
    start.add_argument("--intent", required=True)
    start.add_argument("--task-id", required=True)
    start.add_argument("--run-id")
    start.add_argument("--project-root", default=".")
    start.add_argument("--context-ref", action="append", default=[])
    start.set_defaults(handler=command_start)

    next_command = subparsers.add_parser("next")
    next_command.add_argument("--run-id", required=True)
    next_command.add_argument("--project-root", default=".")
    next_command.set_defaults(handler=command_next)

    approval = subparsers.add_parser("approval-import")
    approval.add_argument("--grant", required=True)
    approval.add_argument("--project-root", default=".")
    approval.set_defaults(handler=command_approval_import)

    complete = subparsers.add_parser("complete")
    complete.add_argument("--run-id", required=True)
    complete.add_argument("--result", required=True)
    complete.add_argument("--evidence-max-age-seconds", type=int)
    complete.add_argument("--project-root", default=".")
    complete.set_defaults(handler=command_complete)

    quality = subparsers.add_parser("quality-submit")
    quality.add_argument("--snapshot", required=True)
    quality.add_argument("--project-root", default=".")
    quality.set_defaults(handler=command_quality_submit)

    investigation_propose = subparsers.add_parser("investigation-propose")
    investigation_propose.add_argument("--request", required=True)
    investigation_propose.add_argument("--project-root", default=".")
    investigation_propose.set_defaults(handler=command_investigation_propose)

    investigation_list = subparsers.add_parser("investigation-list")
    investigation_list.add_argument("--run-id", required=True)
    investigation_list.add_argument("--project-root", default=".")
    investigation_list.add_argument("--limit", type=int, default=50)
    investigation_list.add_argument("--after-id")
    investigation_list.set_defaults(handler=command_investigation_list)

    investigation_approval = subparsers.add_parser("investigation-approval-import")
    investigation_approval.add_argument("--grant", required=True)
    investigation_approval.add_argument("--project-root", default=".")
    investigation_approval.set_defaults(handler=command_investigation_approval_import)

    investigation_start = subparsers.add_parser("investigation-start")
    investigation_start.add_argument("--run-id", required=True)
    investigation_start.add_argument("--investigation-id", required=True)
    investigation_start.add_argument("--project-root", default=".")
    investigation_start.set_defaults(handler=command_investigation_start)

    investigation_finish = subparsers.add_parser("investigation-finish")
    investigation_finish.add_argument("--run-id", required=True)
    investigation_finish.add_argument("--investigation-id", required=True)
    investigation_finish.add_argument("--outcome", choices=("completed", "blocked"), required=True)
    investigation_finish.add_argument("--evidence-ref", action="append", default=[])
    investigation_finish.add_argument("--project-root", default=".")
    investigation_finish.set_defaults(handler=command_investigation_finish)

    evidence_import = subparsers.add_parser("evidence-import")
    evidence_import.add_argument("--run-id", required=True)
    evidence_import.add_argument("--evidence", required=True)
    evidence_import.add_argument("--project-root", default=".")
    evidence_import.set_defaults(handler=command_evidence_import)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--require-sources", action="store_true")
    validate.set_defaults(handler=command_validate)

    verify_sources = subparsers.add_parser(
        "verify-sources",
        help="离线核验六个固定 revision checkout 中的许可证与评审证据摘要。",
    )
    verify_sources.add_argument(
        "--source",
        action="append",
        required=True,
        metavar="SOURCE_ID=/absolute/path",
    )
    verify_sources.set_defaults(handler=command_verify_sources)

    artifact_validate = subparsers.add_parser(
        "artifact-validate",
        help="按当前 Runtime schema 校验 step result、quality snapshot 等结构化 artifact。",
    )
    artifact_validate.add_argument("--kind", choices=sorted(ARTIFACT_SCHEMAS), required=True)
    artifact_validate.add_argument("--input", required=True)
    artifact_validate.set_defaults(handler=command_artifact_validate)

    for command, handler in (
        ("design-source-resolve", command_design_source_resolve),
        ("design-source-read", command_design_source_read),
        ("design-source-check", command_design_source_check),
    ):
        design_source = subparsers.add_parser(command)
        design_source.add_argument("--source-root", required=True)
        design_source.add_argument("--registry", required=True)
        if command == "design-source-read":
            design_source.add_argument("--document", required=True)
        if command == "design-source-check":
            design_source.add_argument("--expected-digest", required=True)
            design_source.add_argument("--document")
        design_source.set_defaults(handler=handler)

    review_package = subparsers.add_parser("review-package-validate")
    review_package.add_argument("--package", required=True)
    review_package.add_argument("--requirement-id", required=True)
    review_package.set_defaults(handler=command_review_package_validate)

    database_design = subparsers.add_parser("database-design-validate")
    database_design.add_argument("--document", required=True)
    database_design.set_defaults(handler=command_database_design_validate)

    build = subparsers.add_parser("build")
    build.add_argument("--platform", choices=sorted(("codex", "hermes")), required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--replace", action="store_true")
    build.set_defaults(handler=command_build)

    verify = subparsers.add_parser("verify-package")
    verify.add_argument("--package", required=True)
    verify.set_defaults(handler=command_verify_package)

    evaluate = subparsers.add_parser("eval")
    evaluate.add_argument("--output")
    evaluate.set_defaults(handler=command_eval)

    canary_prepare = subparsers.add_parser(
        "canary-prepare",
        help="复制真实运行 artifact 并生成待外部验签的 observation draft。",
    )
    canary_prepare.add_argument("--manifest", required=True)
    canary_prepare.add_argument("--output", required=True)
    canary_prepare.set_defaults(handler=command_canary_prepare)

    canary_import = subparsers.add_parser(
        "canary-attestation-import",
        help="校验外部 broker 回执并生成不可变 run evidence。",
    )
    canary_import.add_argument("--evidence-root", required=True)
    canary_import.add_argument("--draft-ref", required=True)
    canary_import.add_argument("--response-ref", required=True)
    canary_import.add_argument("--output", required=True)
    canary_import.set_defaults(handler=command_canary_attestation_import)

    canary_assemble = subparsers.add_parser(
        "canary-assemble",
        help="验签 observation 并从真实测量确定性组装 canary result。",
    )
    canary_assemble.add_argument("--evidence-root", required=True)
    canary_assemble.add_argument("--evidence-ref", action="append", required=True)
    canary_assemble.add_argument("--output", required=True)
    canary_assemble.set_defaults(handler=command_canary_assemble)

    canary = subparsers.add_parser("canary-validate")
    canary.add_argument("--result", required=True)
    canary.set_defaults(handler=command_canary_validate)

    canary_audit = subparsers.add_parser(
        "canary-audit",
        help="只读审计三臂 canary 运行、纳入替换和本地证据完整性。",
    )
    canary_audit.add_argument("--protocol", required=True)
    canary_audit.add_argument("--evidence-root", required=True)
    canary_audit.add_argument("--run-record", action="append", required=True)
    canary_audit.add_argument("--inclusion-manifest", required=True)
    canary_audit.set_defaults(handler=command_canary_audit)

    feedback_summary = subparsers.add_parser(
        "feedback-summary",
        help="只读汇总去标识化效率候选，不修改 skill、规则或门禁。",
    )
    feedback_summary.add_argument("--project-root", required=True)
    feedback_summary.set_defaults(handler=command_feedback_summary)

    feedback_disposition = subparsers.add_parser(
        "feedback-disposition",
        help="导入人工或 CI 明确给出的反馈处置，不修改原始反馈事件。",
    )
    feedback_disposition.add_argument("--project-root", required=True)
    feedback_disposition.add_argument("--input", required=True)
    feedback_disposition.set_defaults(handler=command_feedback_disposition)

    feedback_evolution = subparsers.add_parser(
        "feedback-evolution-export",
        help="只读导出已接受反馈的去敏回归提案，不修改正式资产。",
    )
    feedback_evolution.add_argument("--project-root", required=True)
    feedback_evolution.add_argument("--limit", type=int, default=100)
    feedback_evolution.add_argument("--after-event-ref")
    feedback_evolution.add_argument("--snapshot-revision", type=int)
    feedback_evolution.set_defaults(handler=command_feedback_evolution_export)

    mcp = subparsers.add_parser("mcp-serve")
    mcp.set_defaults(handler=command_mcp_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        catalog = load_catalog(args.repository_root)
        args.profile = args.profile or catalog.product.default_profile_id
        bindings = trust_bindings_from_host(
            catalog.profiles[args.profile],
            catalog.root / "schemas",
        )
        args.trust_verifier = bindings.verifier
        args.evidence_broker = bindings.evidence_broker
        args.approval_broker = bindings.approval_broker
        args.host_trust_config_digest = bindings.config_digest
        return args.handler(args)
    except Exception as exc:  # CLI boundary: errors are structured and non-zero
        _emit({"status": "failed", "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
