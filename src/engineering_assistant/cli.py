"""Command-line contract for the engineering-assistant kernel."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
from .engine import RuntimeEngine
from .evidence import EvidenceStore
from .governance import InvestigationStore, QualityGate, QualityStore
from .eval_runner import run_canary_result, run_evals
from .mcp_server import MCPServer, RuntimeTools, serve_stdio
from .router import route_intent
from .state_store import StateStore
from .trust import verifier_from_profile
from .validation import load_json, validate_instance


ARTIFACT_SCHEMAS = {
    "feedback-event": "feedback-event.schema.json",
    "provider-result": "provider-result.schema.json",
    "quality-snapshot": "quality-snapshot.schema.json",
    "run-state": "run-state.schema.json",
    "step-result": "step-result.schema.json",
}


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
    verifier = getattr(args, "trust_verifier", None) or verifier_from_profile(profile)
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
    broker = catalog.profiles[args.profile].approval_broker
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
    _emit({"record": record.to_dict(), "approval_required": record.request.status == "proposed"})
    return 0


def command_investigation_list(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, _ = _stores(args, catalog)
    _load_state(state_store, args.run_id, args.profile)
    records = InvestigationStore(state_store).list(args.run_id)
    _emit({"records": [item.to_dict() for item in records]})
    return 0


def command_investigation_approval_import(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, evidence_store = _stores(args, catalog)
    grant = investigation_decision_grant_from_dict(_json_input(args.grant))
    state = _load_state(state_store, grant.run_id, args.profile)
    broker = catalog.profiles[args.profile].approval_broker
    if not broker.get("enabled"):
        raise ValueError("external approval broker is not enabled for this profile")
    record = InvestigationStore(state_store).apply_grant(
        grant,
        verifier=evidence_store.trust_verifier,
        current_run_revision=state.revision,
        expected_broker_id=str(broker["id"]),
        expected_audience=str(broker["audience"]),
    )
    _emit({"record": record.to_dict()})
    return 0


def command_investigation_start(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, _ = _stores(args, catalog)
    _load_state(state_store, args.run_id, args.profile)
    record = InvestigationStore(state_store).start(args.run_id, args.investigation_id)
    _emit({"record": record.to_dict()})
    return 0


def command_investigation_finish(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, evidence_store = _stores(args, catalog)
    _load_state(state_store, args.run_id, args.profile)
    record = InvestigationStore(state_store).finish(
        args.run_id,
        args.investigation_id,
        outcome=args.outcome,
        evidence_refs=args.evidence_ref,
        available_evidence=evidence_store.ids(args.run_id, minimum_trust_level="observed"),
    )
    _emit({"record": record.to_dict()})
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
            "providers": len(catalog.providers),
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
    _emit(run_canary_result(args.result, trust_verifier=args.trust_verifier))
    return 0


def command_mcp_serve(args: argparse.Namespace) -> int:
    return serve_stdio(
        MCPServer(RuntimeTools(args.repository_root, trust_verifier=args.trust_verifier))
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ea")
    parser.add_argument("--repository-root", default=str(DEFAULT_REPOSITORY_ROOT))
    parser.add_argument("--profile", default="default")
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

    artifact_validate = subparsers.add_parser(
        "artifact-validate",
        help="按当前 Runtime schema 校验 step result、quality snapshot 等结构化 artifact。",
    )
    artifact_validate.add_argument("--kind", choices=sorted(ARTIFACT_SCHEMAS), required=True)
    artifact_validate.add_argument("--input", required=True)
    artifact_validate.set_defaults(handler=command_artifact_validate)

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

    canary = subparsers.add_parser("canary-validate")
    canary.add_argument("--result", required=True)
    canary.set_defaults(handler=command_canary_validate)

    mcp = subparsers.add_parser("mcp-serve")
    mcp.set_defaults(handler=command_mcp_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        catalog = load_catalog(args.repository_root)
        args.trust_verifier = verifier_from_profile(catalog.profiles[args.profile])
        return args.handler(args)
    except Exception as exc:  # CLI boundary: errors are structured and non-zero
        _emit({"status": "failed", "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
