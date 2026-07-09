"""Schema generation helpers."""

from __future__ import annotations

from . import legacy_generator as _legacy

STRICT_CONTROL_SCHEMA_VERSION = _legacy.STRICT_CONTROL_SCHEMA_VERSION


def string_array_schema(description: str = "") -> dict:
    if hasattr(_legacy, "string_array_schema"):
        return _legacy.string_array_schema(description)
    schema = {"type": "array", "items": {"type": "string"}}
    if description:
        schema["description"] = description
    return schema


def strict_object_schema(properties: dict, required: list[str] | None = None, title: str | None = None) -> dict:
    if hasattr(_legacy, "strict_object_schema"):
        return _legacy.strict_object_schema(properties, required=required, title=title)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required or list(properties),
    }
    if title:
        schema["title"] = title
    return schema


def control_document_metadata_schema() -> dict:
    if hasattr(_legacy, "control_document_metadata_schema"):
        return _legacy.control_document_metadata_schema()
    return strict_object_schema({
        "schema_version": {"const": STRICT_CONTROL_SCHEMA_VERSION},
        "task_id": {"type": "string"},
        "generated_at": {"type": "string"},
    }, required=["schema_version", "task_id"])
