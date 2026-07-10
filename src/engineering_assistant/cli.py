"""Command-line contract for the engineering-assistant kernel."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .catalog import DEFAULT_REPOSITORY_ROOT, load_catalog
from .codec import evidence_ref_from_dict, route_decision_from_dict, route_intent_from_dict, step_result_from_dict
from .compiler import build_package, verify_package
from .engine import RuntimeEngine
from .evidence import EvidenceStore
from .eval_runner import run_canary_result, run_evals
from .router import route_intent
from .state_store import StateStore
from .validation import load_json, validate_instance


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
    return state_store, EvidenceStore(state_store)


def command_route(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    payload = _json_input(args.intent)
    validate_instance(payload, load_json(catalog.root / "schemas/route-intent.schema.json"), "route-intent")
    _emit(route_intent(route_intent_from_dict(payload), catalog, profile_id=args.profile).to_dict())
    return 0


def command_start(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    payload = _json_input(args.decision)
    validate_instance(payload, load_json(catalog.root / "schemas/route-decision.schema.json"), "route-decision")
    state = RuntimeEngine(catalog).start(
        args.task_id,
        route_decision_from_dict(payload),
        run_id=args.run_id,
        context_refs=args.context_ref,
        approvals=args.approval,
    )
    state_store, _ = _stores(args, catalog)
    path = state_store.create(state)
    _emit({"state": state.to_dict(), "state_path": str(path)})
    return 0


def command_next(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, _ = _stores(args, catalog)
    state = state_store.load(args.run_id)
    previous_revision = state.revision
    engine = RuntimeEngine(catalog)
    gate = engine.next(state)
    if state.revision != previous_revision:
        state_store.save(state, expected_revision=previous_revision)
    _emit({"gate": gate.to_dict(), "node": engine.node_payload(state), "state": state.to_dict()})
    return 0


def command_complete(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, evidence_store = _stores(args, catalog)
    state = state_store.load(args.run_id)
    previous_revision = state.revision
    for evidence_path in args.evidence:
        evidence_store.save(args.run_id, evidence_ref_from_dict(_json_input(evidence_path)))
    result = step_result_from_dict(_json_input(args.result))
    engine = RuntimeEngine(catalog)
    gate = engine.complete_step(
        state,
        result,
        available_evidence=evidence_store.ids(
            args.run_id,
            max_age_seconds=args.evidence_max_age_seconds,
        ),
    )
    state_store.save(state, expected_revision=previous_revision)
    _emit({"gate": gate.to_dict(), "node": engine.node_payload(state), "state": state.to_dict()})
    return 0


def command_approve(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.repository_root)
    state_store, _ = _stores(args, catalog)
    state = state_store.load(args.run_id)
    previous_revision = state.revision
    gate = RuntimeEngine(catalog).grant_approval(state, args.approval_id, ttl_seconds=args.ttl_seconds)
    state_store.save(state, expected_revision=previous_revision)
    _emit({"gate": gate.to_dict(), "state": state.to_dict()})
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
            "sources_required": args.require_sources,
        }
    )
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
    _emit(run_canary_result(args.result))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ea")
    parser.add_argument("--repository-root", default=str(DEFAULT_REPOSITORY_ROOT))
    parser.add_argument("--profile", default="default")
    subparsers = parser.add_subparsers(dest="command", required=True)

    route = subparsers.add_parser("route")
    route.add_argument("--intent", required=True, help="RouteIntent JSON path or - for stdin")
    route.set_defaults(handler=command_route)

    start = subparsers.add_parser("start")
    start.add_argument("--decision", required=True)
    start.add_argument("--task-id", required=True)
    start.add_argument("--run-id")
    start.add_argument("--project-root", default=".")
    start.add_argument("--context-ref", action="append", default=[])
    start.add_argument("--approval", action="append", default=[])
    start.set_defaults(handler=command_start)

    next_command = subparsers.add_parser("next")
    next_command.add_argument("--run-id", required=True)
    next_command.add_argument("--project-root", default=".")
    next_command.set_defaults(handler=command_next)

    complete = subparsers.add_parser("complete")
    complete.add_argument("--run-id", required=True)
    complete.add_argument("--result", required=True)
    complete.add_argument("--evidence", action="append", default=[])
    complete.add_argument("--evidence-max-age-seconds", type=int)
    complete.add_argument("--project-root", default=".")
    complete.set_defaults(handler=command_complete)

    approve = subparsers.add_parser("approve")
    approve.add_argument("--run-id", required=True)
    approve.add_argument("--approval-id", required=True)
    approve.add_argument("--ttl-seconds", type=int, default=3600)
    approve.add_argument("--project-root", default=".")
    approve.set_defaults(handler=command_approve)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--require-sources", action="store_true")
    validate.set_defaults(handler=command_validate)

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except Exception as exc:  # CLI boundary: errors are structured and non-zero
        _emit({"status": "failed", "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
