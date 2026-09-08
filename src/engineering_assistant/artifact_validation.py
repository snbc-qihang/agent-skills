"""Bounded in-memory artifact validation for model-facing runtimes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .validation import ValidationFailure, load_json, validate_instance
from .codec import quality_snapshot_from_dict
from .governance import validate_quality_contract


ARTIFACT_SCHEMAS = {
    "database-design": "database-design.schema.json",
    "review-package": "review-package.schema.json",
    "capability-provider-spec": "capability-provider-spec.schema.json",
    "design-source-registry": "design-source-registry.schema.json",
    "feedback-capture": "feedback-capture.schema.json",
    "feedback-disposition": "feedback-disposition.schema.json",
    "feedback-evolution-export": "feedback-evolution-export.schema.json",
    "feedback-event": "feedback-event.schema.json",
    "investigation-record": "investigation-record.schema.json",
    "investigation-request": "investigation-request.schema.json",
    "provider-invocation": "provider-invocation.schema.json",
    "provider-result": "provider-result.schema.json",
    "quality-snapshot": "quality-snapshot.schema.json",
    "run-state": "run-state.schema.json",
    "step-result": "step-result.schema.json",
    "usage-efficiency-feedback": "usage-efficiency-feedback.schema.json",
    "usage-observation-ledger": "usage-observation-ledger.schema.json",
    "usage-observation-plan": "usage-observation-plan.schema.json",
}
MAX_MODEL_ARTIFACT_BYTES = 262_144
MAX_MODEL_ARTIFACT_DEPTH = 32
MAX_MODEL_ARTIFACT_NODES = 10_000


def validate_artifact_payload(
    *,
    schema_root: Path | str,
    kind: str,
    artifact: Mapping[str, Any],
) -> dict:
    if kind not in ARTIFACT_SCHEMAS:
        raise ValidationFailure("unsupported artifact kind")
    _validate_shape(artifact)
    encoded = json.dumps(
        artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > MAX_MODEL_ARTIFACT_BYTES:
        raise ValidationFailure("artifact payload is too large")
    try:
        validate_instance(
            artifact,
            load_json(Path(schema_root) / ARTIFACT_SCHEMAS[kind]),
            kind,
        )
    except ValidationFailure as exc:
        raise ValidationFailure(
            f"artifact does not conform to the {kind} schema"
        ) from exc
    if kind in {"database-design", "review-package"}:
        from .design_documents import validate_design_document
        return validate_design_document(kind, artifact, Path(schema_root))
    if kind == "quality-snapshot":
        validate_quality_contract(quality_snapshot_from_dict(artifact))
    return {"status": "passed", "kind": kind}


def _validate_shape(root: object) -> None:
    nodes = 0
    stack = [(root, 0)]
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_MODEL_ARTIFACT_NODES:
            raise ValidationFailure("artifact payload has too many values")
        if depth > MAX_MODEL_ARTIFACT_DEPTH:
            raise ValidationFailure("artifact payload is nested too deeply")
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
