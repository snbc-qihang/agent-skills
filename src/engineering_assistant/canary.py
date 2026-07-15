"""Prepare unsigned, reproducible canary evidence bundles for external attestation."""

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path
from typing import Any

from .artifact_io import (
    ArtifactConflict,
    ArtifactIO,
)
from . import canary_limits
from .trust import TrustVerifier, canary_observation_claims, parse_time
from .validation import ValidationFailure, load_json, validate_instance


MEASUREMENT_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cost_usd_micros",
    "quality_score",
    "document_noise_units",
    "safety_violations",
)
MEASUREMENT_EVIDENCE_KINDS = {
    "input_tokens": "usage",
    "output_tokens": "usage",
    "cost_usd_micros": "billing",
    "quality_score": "quality_evaluation",
    "document_noise_units": "document_noise",
    "safety_violations": "safety_audit",
}


def validate_measurement_evidence_coverage(
    payload: dict[str, Any],
    measurement_groups,
) -> None:
    covered = {kind for group in measurement_groups for kind in group}
    required = {
        MEASUREMENT_EVIDENCE_KINDS[field]
        for field in MEASUREMENT_FIELDS
        if field in payload
    }
    if not required.issubset(covered):
        missing = sorted(required - covered)
        raise ValidationFailure(
            "canary measurement artifact coverage is missing: "
            + ", ".join(missing)
        )
OBSERVATION_FIELDS = (
    "task_id",
    "workload_digest",
    "variant",
    "git_ref",
    "treatment_digest",
    "execution_config_digest",
    "environment_digest",
    "quality_rubric_digest",
    "evaluator_id",
    "started_at",
    "finished_at",
    *MEASUREMENT_FIELDS,
)


def _sha256_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _outside_repository(output: Path, repository_root: Path) -> None:
    try:
        output.relative_to(repository_root)
    except ValueError:
        return
    raise ValidationFailure("canary bundle output must stay outside the author repository")


def _source_artifact(reference: str, manifest_io: ArtifactIO) -> tuple[Path, bytes]:
    candidate = Path(reference)
    if candidate.is_absolute():
        raise ValidationFailure("canary source artifact paths must be relative to the manifest")
    try:
        payload = manifest_io.read_bytes_limited(
            canary_limits.MAX_ARTIFACT_BYTES,
            *candidate.parts,
        )
    except FileNotFoundError as exc:
        raise ValidationFailure("canary source artifact is missing") from exc
    return candidate, payload


def prepare_canary_bundle(
    manifest_path: Path | str,
    output_root: Path | str,
    *,
    repository_root: Path | str,
    evidence_broker_id: str,
    host_trust_config_digest: str,
) -> dict[str, Any]:
    """Copy raw artifacts and emit unsigned claims; never emits an attestation."""

    manifest_path = Path(manifest_path)
    if manifest_path.is_symlink():
        raise ValidationFailure("canary preparation manifest cannot be a symlink")
    manifest_path = manifest_path.resolve()
    manifest_io = ArtifactIO(manifest_path.parent, ".")
    manifest, _manifest_raw = manifest_io.read_json_limited(
        canary_limits.MAX_MANIFEST_BYTES,
        manifest_path.name,
    )

    repository_root = Path(repository_root).resolve()
    output_root = Path(output_root).resolve()
    _outside_repository(output_root, repository_root)
    if not output_root.parent.is_dir():
        raise ValidationFailure("canary bundle output parent must already exist")
    output_io = ArtifactIO(output_root.parent, ".")
    output_io.assert_runtime_target(repository_root / "schemas")
    if output_io.entry_exists(output_root.name):
        raise ValidationFailure("canary bundle output already exists")

    schema_root = repository_root / "evals/canary"
    validate_instance(
        manifest,
        load_json(schema_root / "preparation-manifest.schema.json"),
        "canary-preparation-manifest",
    )
    artifact_count = sum(len(run["artifact_paths"]) for run in manifest["runs"])
    if artifact_count > canary_limits.MAX_TOTAL_ARTIFACTS:
        raise ValidationFailure(
            "canary preparation has too many artifacts; maximum is "
            f"{canary_limits.MAX_TOTAL_ARTIFACTS}"
        )
    trust_provenance = {
        "evidence_broker_id": evidence_broker_id,
        "host_trust_config_digest": host_trust_config_digest,
    }

    staging_name = f".{output_root.name}.staging-{secrets.token_hex(6)}"
    _staging_path, staging_fd, staging_metadata = (
        output_io.create_directory_exclusive_open(staging_name)
    )
    staging_io = ArtifactIO.from_open_directory_fd(
        output_root.parent / staging_name,
        staging_fd,
    )
    os.close(staging_fd)
    draft_refs: list[str] = []
    incomplete_runs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    total_artifact_bytes = 0
    try:
        for run in manifest["runs"]:
            key = (run["task_id"], run["variant"])
            if key in seen:
                raise ValidationFailure(
                    f"duplicate canary preparation run for {key[0]} {key[1]}"
                )
            seen.add(key)
            if parse_time(run["finished_at"]) < parse_time(run["started_at"]):
                raise ValidationFailure("canary run finishes before it starts")
            if set(run["artifact_paths"]) != set(run["artifact_measurements"]):
                raise ValidationFailure(
                    "canary artifact measurement mapping must match artifact paths"
                )
            validate_measurement_evidence_coverage(
                run,
                run["artifact_measurements"].values(),
            )

            task_ref = hashlib.sha256(run["task_id"].encode("utf-8")).hexdigest()[:16]
            artifact_refs = []
            for index, reference in enumerate(run["artifact_paths"]):
                source, payload = _source_artifact(reference, manifest_io)
                total_artifact_bytes += len(payload)
                if total_artifact_bytes > canary_limits.MAX_TOTAL_ARTIFACT_BYTES:
                    raise ValidationFailure(
                        "canary preparation exceeds the total artifact bytes limit"
                    )
                suffix = source.suffix[:16] if source.suffix else ".bin"
                relative = Path("artifacts") / task_ref / run["variant"] / (
                    f"artifact-{index + 1}{suffix}"
                )
                staging_io.write_bytes_exclusive(
                    payload,
                    *relative.parts,
                )
                artifact_refs.append(
                    {
                        "path": relative.as_posix(),
                        "digest": _sha256_bytes(payload),
                        "measurement_kinds": sorted(
                            run["artifact_measurements"][reference]
                        ),
                    }
                )

            observation = {
                "simulation": False,
                "product_repository": manifest["product_repository"],
                **{field: run[field] for field in OBSERVATION_FIELDS if field in run},
                "artifact_refs": artifact_refs,
                "trust_provenance": trust_provenance,
            }
            missing_fields = sorted(
                field for field in MEASUREMENT_FIELDS if field not in observation
            )
            status = "incomplete" if missing_fields else "awaiting_attestation"
            draft = {
                "schema_version": "1.0",
                "status": status,
                "observation": observation,
                "missing_fields": missing_fields,
                "claims": canary_observation_claims(observation),
            }
            validate_instance(
                draft,
                load_json(schema_root / "observation-draft.schema.json"),
                "canary-observation-draft",
            )
            relative_draft = Path("observations") / (
                f"observation-{task_ref}-{run['variant']}.draft.json"
            )
            staging_io.write_bytes_exclusive(
                ArtifactIO.canonical_json_bytes(draft),
                *relative_draft.parts,
            )
            draft_refs.append(relative_draft.as_posix())
            if missing_fields:
                incomplete_runs.append(
                    {
                        "task_id": run["task_id"],
                        "variant": run["variant"],
                        "missing_fields": missing_fields,
                    }
                )

        report = {
            "schema_version": "1.0",
            "status": "incomplete" if incomplete_runs else "awaiting_attestation",
            "draft_count": len(draft_refs),
            "draft_refs": draft_refs,
            "incomplete_runs": incomplete_runs,
            "attestation_source": "external_evidence_broker_only",
            "canary_result_generated": False,
        }
        staging_io.write_bytes_exclusive(
            ArtifactIO.canonical_json_bytes(report),
            "preparation-report.json",
        )
        _output_path, output_fd, output_metadata = (
            output_io.create_directory_exclusive_open(output_root.name)
        )
        final_io = ArtifactIO.from_open_directory_fd(output_root, output_fd)
        os.close(output_fd)
        try:
            staging_io.copy_contents_to(
                final_io,
                max_file_bytes=canary_limits.MAX_ARTIFACT_BYTES,
            )
            if not output_io.child_directory_matches(
                output_root.name,
                output_metadata,
            ):
                raise ValidationFailure("canary output directory identity changed")
        except Exception:
            try:
                final_io.remove_all_contents()
                output_io.remove_child_directory_if_matches(
                    output_root.name,
                    output_metadata,
                )
            except Exception:
                pass
            raise
        staging_io.remove_all_contents()
        output_io.remove_child_directory_if_matches(
            staging_name,
            staging_metadata,
        )
        return report
    except Exception:
        try:
            staging_io.remove_all_contents()
            output_io.remove_child_directory_if_matches(
                staging_name,
                staging_metadata,
            )
        except Exception:
            pass
        raise


def import_canary_attestation(
    evidence_root: Path | str,
    draft_ref: str,
    response_ref: str,
    output_ref: str,
    *,
    trust_verifier: TrustVerifier | None,
    evidence_broker_id: str,
    host_trust_config_digest: str,
    repository_root: Path | str,
) -> dict[str, Any]:
    """Verify an external receipt against an unchanged draft and persist evidence."""

    if trust_verifier is None:
        raise ValidationFailure("canary attestation import requires an external evidence broker")
    evidence_root = Path(evidence_root).resolve()
    repository_root = Path(repository_root).resolve()
    artifacts = ArtifactIO(evidence_root, ".")
    artifacts.assert_runtime_target(repository_root / "schemas")
    draft_parts = Path(draft_ref).parts
    response_parts = Path(response_ref).parts
    output_parts = Path(output_ref).parts
    draft, draft_raw = artifacts.read_json_limited(
        canary_limits.MAX_OBSERVATION_BYTES,
        *draft_parts,
    )
    response, _response_raw = artifacts.read_json_limited(
        canary_limits.MAX_ATTESTATION_RESPONSE_BYTES,
        *response_parts,
    )
    schema_root = repository_root / "evals/canary"
    validate_instance(
        draft,
        load_json(schema_root / "observation-draft.schema.json"),
        "canary-observation-draft",
    )
    validate_measurement_evidence_coverage(
        draft["observation"],
        (
            item["measurement_kinds"]
            for item in draft["observation"]["artifact_refs"]
        ),
    )
    validate_instance(
        response,
        load_json(schema_root / "attestation-response.schema.json"),
        "canary-attestation-response",
    )
    if _sha256_bytes(draft_raw) != response["draft_digest"]:
        raise ValidationFailure("canary attestation response targets a different draft")
    if draft["status"] != "awaiting_attestation" or draft["missing_fields"]:
        raise ValidationFailure("incomplete canary observation cannot be attested")
    expected_claims = canary_observation_claims(draft["observation"])
    if draft["claims"] != expected_claims:
        raise ValidationFailure("canary draft claims do not match its observation")
    expected_provenance = {
        "evidence_broker_id": evidence_broker_id,
        "host_trust_config_digest": host_trust_config_digest,
    }
    if draft["observation"].get("trust_provenance") != expected_provenance:
        raise ValidationFailure(
            "canary draft was prepared under a different host trust binding"
        )
    observation = {**draft["observation"], "attestation": response["attestation"]}
    validate_instance(
        observation,
        load_json(schema_root / "run-evidence.schema.json"),
        "canary-run-evidence",
    )
    if not trust_verifier.verify_canary_observation(observation):
        raise ValidationFailure("canary observation attestation is not trusted")
    try:
        path, created = artifacts.create_immutable_json_with_status(
            observation,
            *output_parts,
            existing_max_bytes=canary_limits.MAX_OBSERVATION_BYTES,
        )
    except ArtifactConflict as exc:
        raise ValidationFailure("canary run evidence already exists with different content") from exc
    return {
        "status": "imported" if created else "already_imported",
        "evidence_ref": path.relative_to(evidence_root).as_posix(),
        "draft_digest": response["draft_digest"],
    }
