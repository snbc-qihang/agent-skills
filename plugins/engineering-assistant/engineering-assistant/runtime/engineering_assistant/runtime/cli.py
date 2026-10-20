"""Command-line contract for the engineering-assistant kernel."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .artifact_validation import ARTIFACT_SCHEMAS
from .artifact_io import ArtifactConflict, ArtifactIO
from .catalog import DEFAULT_REPOSITORY_ROOT, load_catalog
from .codec import (
    investigation_request_from_dict,
    quality_snapshot_from_dict,
)
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
from .model import FeedbackDisposition
from .mcp_server import MCPServer, RuntimeTools, serve_stdio
from .state_store import StateStore
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
    state_store = StateStore(
        args.project_root,
        catalog.root / "schemas",
        profile.store["run_root"],
        allow_author_repository=getattr(args, "allow_author_repository", False),
    )
    return state_store, EvidenceStore(state_store)


def _load_state(state_store: StateStore, run_id: str, profile_id: str):
    state = state_store.load(run_id)
    if state.profile_id != profile_id:
        raise ValueError(
            f"run {run_id} is bound to profile {state.profile_id}, not {profile_id}"
        )
    return state


def command_route(args: argparse.Namespace) -> int:
    payload = _json_input(args.intent)
    _emit(RuntimeTools(args.repository_root).call(
        "engineering_assistant_route",
        {"intent": payload, "profile": args.profile},
    ))
    return 0


def command_start(args: argparse.Namespace) -> int:
    payload = _json_input(args.intent)
    if args.allow_author_repository:
        os.environ["ENGINEERING_ASSISTANT_AUTHOR_MODE"] = "1"
    _emit(RuntimeTools(args.repository_root).call(
        "engineering_assistant_start",
        {
            "intent": payload,
            "task_id": args.task_id,
            "run_id": args.run_id,
            "project_root": args.project_root,
            "profile": args.profile,
            "context_refs": args.context_ref,
            **({"design_source_ref": args.design_source_ref} if args.design_source_ref else {}),
        },
    ))
    return 0


def command_next(args: argparse.Namespace) -> int:
    _emit(RuntimeTools(args.repository_root).call(
        "engineering_assistant_next",
        {"run_id": args.run_id, "project_root": args.project_root, "profile": args.profile},
    ))
    return 0


def command_runs_list(args: argparse.Namespace) -> int:
    _emit(RuntimeTools(args.repository_root).call(
        "engineering_assistant_runs_list",
        {
            "project_root": args.project_root,
            "profile": args.profile,
            "include_terminal": args.include_terminal,
            "limit": args.limit,
            **({"after_run_id": args.after_run_id} if args.after_run_id else {}),
        },
    ))
    return 0


def command_run_status(args: argparse.Namespace) -> int:
    _emit(RuntimeTools(args.repository_root).call(
        "engineering_assistant_run_status",
        {
            "run_id": args.run_id,
            "project_root": args.project_root,
            "profile": args.profile,
        },
    ))
    return 0


def command_approval_record(args: argparse.Namespace) -> int:
    payload = _json_input(args.record)
    _emit(RuntimeTools(args.repository_root).call(
        "engineering_assistant_approval_record",
        {**payload, "project_root": args.project_root, "profile": args.profile},
    ))
    return 0


def command_complete(args: argparse.Namespace) -> int:
    _emit(RuntimeTools(args.repository_root).call(
        "engineering_assistant_complete",
        {
            "run_id": args.run_id,
            "project_root": args.project_root,
            "profile": args.profile,
            "result": _json_input(args.result),
            **({"evidence_max_age_seconds": args.evidence_max_age_seconds} if args.evidence_max_age_seconds else {}),
        },
    ))
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


def command_investigation_decide(args: argparse.Namespace) -> int:
    _emit(RuntimeTools(args.repository_root).call(
        "engineering_assistant_investigation_decide",
        {**_json_input(args.decision), "project_root": args.project_root, "profile": args.profile},
    ))
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


def command_evidence_register(args: argparse.Namespace) -> int:
    _emit(RuntimeTools(args.repository_root).call(
        "engineering_assistant_evidence_register",
        {
            **_json_input(args.evidence),
            "run_id": args.run_id,
            "project_root": args.project_root,
            "profile": args.profile,
        },
    ))
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
    return serve_stdio(MCPServer(RuntimeTools(args.repository_root)))


def build_parser(configure=None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ea")
    parser.add_argument("--repository-root", default=str(DEFAULT_REPOSITORY_ROOT))
    parser.add_argument("--profile", default="default")
    parser.add_argument("--allow-author-repository", action="store_true")
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
    start.add_argument("--design-source-ref")
    start.set_defaults(handler=command_start)

    next_command = subparsers.add_parser("next")
    next_command.add_argument("--run-id", required=True)
    next_command.add_argument("--project-root", default=".")
    next_command.set_defaults(handler=command_next)

    runs_list = subparsers.add_parser("runs-list")
    runs_list.add_argument("--project-root", default=".")
    runs_list.add_argument("--include-terminal", action="store_true")
    runs_list.add_argument("--limit", type=int, default=50)
    runs_list.add_argument("--after-run-id")
    runs_list.set_defaults(handler=command_runs_list)

    run_status = subparsers.add_parser("run-status")
    run_status.add_argument("--run-id", required=True)
    run_status.add_argument("--project-root", default=".")
    run_status.set_defaults(handler=command_run_status)

    approval = subparsers.add_parser("approval-record")
    approval.add_argument("--record", required=True)
    approval.add_argument("--project-root", default=".")
    approval.set_defaults(handler=command_approval_record)

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

    investigation_approval = subparsers.add_parser("investigation-decide")
    investigation_approval.add_argument("--decision", required=True)
    investigation_approval.add_argument("--project-root", default=".")
    investigation_approval.set_defaults(handler=command_investigation_decide)

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

    evidence_import = subparsers.add_parser("evidence-register")
    evidence_import.add_argument("--run-id", required=True)
    evidence_import.add_argument("--evidence", required=True)
    evidence_import.add_argument("--project-root", default=".")
    evidence_import.set_defaults(handler=command_evidence_register)

    artifact_validate = subparsers.add_parser(
        "artifact-validate",
        help="按当前 Runtime schema 校验 step result、quality snapshot 等结构化 artifact。",
    )
    artifact_validate.add_argument("--kind", choices=sorted(ARTIFACT_SCHEMAS), required=True)
    artifact_validate.add_argument("--input", required=True)
    artifact_validate.set_defaults(handler=command_artifact_validate)

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
    if configure is not None:
        configure(subparsers)
    return parser


def main(argv: list[str] | None = None, *, configure=None) -> int:
    args = build_parser(configure).parse_args(argv)
    try:
        if args.allow_author_repository:
            os.environ["ENGINEERING_ASSISTANT_AUTHOR_MODE"] = "1"
        return args.handler(args)
    except Exception as exc:  # CLI boundary: errors are structured and non-zero
        _emit({"status": "failed", "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
