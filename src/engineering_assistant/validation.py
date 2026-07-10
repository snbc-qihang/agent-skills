"""Draft 2020-12 schema validation helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:  # pragma: no cover - exercised by packaging smoke tests
    Draft202012Validator = None
    FormatChecker = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class ValidationFailure(ValueError):
    pass


VALIDATION_BACKEND = "jsonschema-draft-2020-12" if Draft202012Validator is not None else "builtin-supported-keywords"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationFailure(f"{path}: invalid JSON: {exc}") from exc


def validate_instance(instance: Any, schema: Dict[str, Any], label: str = "instance") -> None:
    if Draft202012Validator is not None:
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path))
        if errors:
            rendered = []
            for error in errors:
                location = ".".join(str(item) for item in error.absolute_path) or "$"
                rendered.append(f"{label}:{location}: {error.message}")
            raise ValidationFailure("\n".join(rendered))
        return
    errors: List[str] = []
    _validate_supported(instance, schema, "$", errors)
    if errors:
        raise ValidationFailure("\n".join(f"{label}:{item}" for item in errors))


def _matches_type(value: Any, expected: str) -> bool:
    mapping = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    return expected in mapping and mapping[expected](value)


def _is_valid(value: Any, schema: Dict[str, Any]) -> bool:
    nested: List[str] = []
    _validate_supported(value, schema, "$", nested)
    return not nested


def _validate_supported(value: Any, schema: Dict[str, Any], path: str, errors: List[str]) -> None:
    expected = schema.get("type")
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, item) for item in allowed):
            errors.append(f"{path}: expected type {allowed}, got {type(value).__name__}")
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is not in enum")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: value {value!r} does not equal const {schema['const']!r}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: string is shorter than minLength")
        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            errors.append(f"{path}: string does not match pattern {pattern}")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("timezone is required")
            except ValueError:
                errors.append(f"{path}: string is not an RFC 3339 date-time")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: value is above maximum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: array is shorter than minItems")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{path}: array items are not unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_supported(item, item_schema, f"{path}[{index}]", errors)
    if isinstance(value, dict):
        for required in schema.get("required", []):
            if required not in value:
                errors.append(f"{path}: missing required property {required}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _validate_supported(item, properties[key], f"{path}.{key}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: additional property {key} is not allowed")
            elif isinstance(schema.get("additionalProperties"), dict):
                _validate_supported(item, schema["additionalProperties"], f"{path}.{key}", errors)
    for subschema in schema.get("allOf", []):
        _validate_supported(value, subschema, path, errors)
    if "if" in schema and _is_valid(value, schema["if"]):
        _validate_supported(value, schema.get("then", {}), path, errors)


def validate_file(instance_path: Path, schema_path: Path) -> None:
    validate_instance(load_json(instance_path), load_json(schema_path), str(instance_path))


def validate_many(instances: Iterable[Dict[str, Any]], schema: Dict[str, Any], label: str) -> List[str]:
    validated: List[str] = []
    for index, instance in enumerate(instances):
        validate_instance(instance, schema, f"{label}[{index}]")
        validated.append(str(instance.get("id", index)))
    return validated
