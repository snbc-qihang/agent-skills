"""Author commands, loaded only for explicit development operations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..runtime import cli as runtime_cli
from ..runtime.cli import _emit, _json_input
from ..runtime.artifact_io import ArtifactIO, ArtifactConflict
from ..runtime.catalog import load_catalog
from ..runtime.validation import ValidationFailure, load_json
from . import canary_limits
from .canary import prepare_canary_bundle
from .canary_protocol import (
    MAX_AUDIT_INPUT_FILE_BYTES,
    MAX_AUDIT_INPUT_FILES,
    MAX_AUDIT_INPUT_TOTAL_BYTES,
    audit_canary_protocol,
)
from .compiler import build_package, verify_package
from .eval_runner import assemble_canary_result, run_canary_result, run_evals
from .source_verification import verify_source_checkouts

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
            "sources": len(catalog.sources),
            "sources_required": args.require_sources,
        }
    )
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
        target=args.target,
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
    report = run_canary_result(args.result)
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
    _emit(
        prepare_canary_bundle(
            args.manifest,
            args.output,
            repository_root=args.repository_root,
        )
    )
    return 0


def command_canary_assemble(args: argparse.Namespace) -> int:
    evidence_root = Path(args.evidence_root).resolve()
    artifacts = ArtifactIO(evidence_root, ".")
    artifacts.assert_runtime_target(
        Path(args.repository_root).resolve() / "schemas"
    )
    output_reference = Path(args.output)
    result = assemble_canary_result(
        evidence_root,
        args.evidence_ref,
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
            "assurance": "local_unattested",
            "result_path": str(output),
            "result": result,
        }
    )
    return 0


def _add_author_commands(subparsers):
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

    build = subparsers.add_parser("build")
    build.add_argument(
        "--platform",
        choices=sorted(("claude-code", "codex", "cursor", "hermes")),
        required=True,
    )
    build.add_argument("--output", required=True)
    build.add_argument("--replace", action="store_true")
    build.add_argument("--target", choices=("macos-arm64", "linux-x64", "windows-x64"))
    build.set_defaults(handler=command_build)

    verify = subparsers.add_parser("verify-package")
    verify.add_argument("--package", required=True)
    verify.set_defaults(handler=command_verify_package)

    evaluate = subparsers.add_parser("eval")
    evaluate.add_argument("--output")
    evaluate.set_defaults(handler=command_eval)

    canary_prepare = subparsers.add_parser(
        "canary-prepare",
        help="复制真实运行 artifact 并生成 local_unattested observation。",
    )
    canary_prepare.add_argument("--manifest", required=True)
    canary_prepare.add_argument("--output", required=True)
    canary_prepare.set_defaults(handler=command_canary_prepare)

    canary_assemble = subparsers.add_parser(
        "canary-assemble",
        help="从本地摘要校验后的真实测量确定性组装 canary result。",
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


def build_parser():
    return runtime_cli.build_parser(_add_author_commands)

def main(argv=None):
    return runtime_cli.main(argv, configure=_add_author_commands)
