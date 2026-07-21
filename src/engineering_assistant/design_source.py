"""Read-only deterministic design-source and review-package contracts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .model import DesignSourceRef
from .validation import ValidationFailure


MAX_REGISTRY_BYTES = 1_048_576
MAX_DOCUMENT_BYTES = 8_388_608
MAX_DOCUMENTS = 512
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIREMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PLACEHOLDER = re.compile(
    r"<[A-Z][A-Z0-9_-]*>|\{\{[^{}]+\}\}|\b(?:TBD|TODO)\b|待填写",
    re.IGNORECASE,
)


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_root(reference: DesignSourceRef) -> Path:
    raw = Path(reference.root)
    if not raw.is_absolute():
        raise ValidationFailure("design source root must be absolute")
    try:
        root = raw.resolve(strict=True)
    except OSError as exc:
        raise ValidationFailure("design source root is unavailable") from exc
    if not root.is_dir():
        raise ValidationFailure("design source root must be a directory")
    return root


def _resolve_member(root: Path, base: Path, relative: str, label: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise ValidationFailure(f"{label} must stay within design source root")
    unresolved = (base / path).resolve(strict=False)
    if not _within(root, unresolved):
        raise ValidationFailure(f"{label} must stay within design source root")
    try:
        resolved = unresolved.resolve(strict=True)
    except OSError as exc:
        raise ValidationFailure(f"{label} is unavailable: {relative}") from exc
    if not _within(root, resolved):
        raise ValidationFailure(f"{label} must stay within design source root")
    if not resolved.is_file():
        raise ValidationFailure(f"{label} must be a file: {relative}")
    return resolved


def _scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value in {"null", "~"}:
        return None
    if value in {"true", "false"}:
        return value == "true"
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    return value


def _parse_registry(content: str) -> dict[str, Any]:
    stripped = content.lstrip()
    if stripped.startswith("{"):
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValidationFailure("design source registry is invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValidationFailure("design source registry must be an object")
        return value

    result: dict[str, Any] = {}
    documents: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_documents = False
    for line_number, raw in enumerate(content.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw == "documents:":
            in_documents = True
            result["documents"] = documents
            continue
        if in_documents and raw.startswith("  - "):
            current = {}
            documents.append(current)
            key, separator, value = raw[4:].partition(":")
            if not separator or not key:
                raise ValidationFailure(f"invalid registry line {line_number}")
            current[key.strip()] = _scalar(value)
            continue
        if in_documents and raw.startswith("    "):
            if current is None:
                raise ValidationFailure(f"invalid registry line {line_number}")
            key, separator, value = raw.strip().partition(":")
            if not separator or not key:
                raise ValidationFailure(f"invalid registry line {line_number}")
            current[key.strip()] = _scalar(value)
            continue
        if raw.startswith(" "):
            raise ValidationFailure(f"unsupported registry nesting at line {line_number}")
        in_documents = False
        key, separator, value = raw.partition(":")
        if not separator or not key:
            raise ValidationFailure(f"invalid registry line {line_number}")
        result[key.strip()] = _scalar(value)
    return result


def _frontmatter(content: str) -> dict[str, Any]:
    if not content.startswith("---\n"):
        return {}
    end = content.find("\n---\n", 4)
    if end < 0:
        raise ValidationFailure("design document has unterminated frontmatter")
    metadata: dict[str, Any] = {}
    for raw in content[4:end].splitlines():
        if not raw or raw.startswith(" ") or ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        metadata[key.strip()] = _scalar(value)
    return metadata


def _read_bounded(path: Path, limit: int, label: str) -> bytes:
    size = path.stat().st_size
    if size > limit:
        raise ValidationFailure(f"{label} exceeds size limit")
    return path.read_bytes()


def resolve_design_source(reference: DesignSourceRef) -> dict[str, Any]:
    root = _resolve_root(reference)
    registry_path = _resolve_member(root, root, reference.registry, "design source registry")
    registry_bytes = _read_bounded(registry_path, MAX_REGISTRY_BYTES, "design source registry")
    registry = _parse_registry(registry_bytes.decode("utf-8"))
    raw_documents = registry.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise ValidationFailure("design source registry must contain documents")
    if len(raw_documents) > MAX_DOCUMENTS:
        raise ValidationFailure("design source registry contains too many documents")

    documents: list[dict[str, Any]] = []
    numbers: set[str] = set()
    paths: set[str] = set()
    for raw in raw_documents:
        if not isinstance(raw, dict):
            raise ValidationFailure("design source document entry must be an object")
        required = ("document_number", "type", "path", "status", "owner")
        if any(not isinstance(raw.get(key), str) or not raw.get(key) for key in required):
            raise ValidationFailure("design source document entry is incomplete")
        number = str(raw["document_number"])
        relative = str(raw["path"])
        if number in numbers or relative in paths:
            raise ValidationFailure("design source document identifiers and paths must be unique")
        numbers.add(number)
        paths.add(relative)
        path = _resolve_member(root, registry_path.parent, relative, "design document")
        content = _read_bounded(path, MAX_DOCUMENT_BYTES, "design document")
        text = content.decode("utf-8")
        metadata = _frontmatter(text)
        if metadata.get("document_number") not in {None, number}:
            raise ValidationFailure(f"registry document number differs from frontmatter: {number}")
        status = str(raw["status"])
        if metadata.get("document_status") not in {None, status}:
            raise ValidationFailure(f"registry status differs from frontmatter: {number}")
        documents.append(
            {
                "document_number": number,
                "type": str(raw["type"]),
                "path": path.relative_to(root).as_posix(),
                "status": status,
                "owner": str(raw.get("owner", "")),
                "version": metadata.get("version"),
                "digest": _sha256(content),
                "size": len(content),
            }
        )

    high_levels = [item for item in documents if item["type"] == "high_level_design"]
    contexts = [item for item in documents if item["type"] == "context_detailed_design"]

    templates: list[dict[str, Any]] = []
    template_patterns = (
        (root / "40-templates", "[0-9][0-9]-*template.*"),
        (root / "30-requirement-maintenance/10-template", "[0-9][0-9]-*"),
    )
    for template_root, pattern in template_patterns:
        if not template_root.is_dir():
            continue
        for path in sorted(template_root.glob(pattern)):
            if path.name.startswith("00-"):
                continue
            resolved = path.resolve(strict=True)
            if not _within(root, resolved) or not resolved.is_file():
                raise ValidationFailure("design template must stay within design source root")
            content = _read_bounded(resolved, MAX_DOCUMENT_BYTES, "design template")
            templates.append(
                {
                    "path": resolved.relative_to(root).as_posix(),
                    "digest": _sha256(content),
                    "size": len(content),
                }
            )

    governance_inputs: list[dict[str, Any]] = []
    governance_root = root / "90-design-basis/30-document-governance"
    for name in (
        "03-review-gates.md",
        "05-service-capability-catalog.yaml",
        "07-architecture-impact-rules.yaml",
        "08-traceability-matrix.yaml",
    ):
        path = governance_root / name
        if not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        if not _within(root, resolved):
            raise ValidationFailure("design governance input must stay within design source root")
        content = _read_bounded(resolved, MAX_DOCUMENT_BYTES, "design governance input")
        governance_inputs.append(
            {
                "path": resolved.relative_to(root).as_posix(),
                "digest": _sha256(content),
                "size": len(content),
            }
        )

    digest_payload = {
        "registry_digest": _sha256(registry_bytes),
        "documents": [
            {key: item[key] for key in ("document_number", "type", "path", "status", "version", "digest")}
            for item in documents
        ],
        "templates": templates,
        "governance_inputs": governance_inputs,
    }
    snapshot_digest = _sha256(
        json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return {
        "status": "resolved",
        "digest": snapshot_digest,
        "registry": registry_path.relative_to(root).as_posix(),
        "registry_digest": _sha256(registry_bytes),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "high_level_designs": high_levels,
        "architecture_decisions": [item for item in documents if item["type"] == "architecture_decision_record"],
        "domain_designs": [item for item in documents if item["type"] == "domain_design"],
        "context_detailed_designs": contexts,
        "governance_documents": [item for item in documents if item["type"] == "governance"],
        "governance_inputs": governance_inputs,
        "templates": templates,
        "documents": documents,
    }


def _snapshot_members(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *snapshot["documents"],
        *snapshot["templates"],
        *snapshot["governance_inputs"],
    ]


def _snapshot_member(snapshot: dict[str, Any], document_ref: str) -> dict[str, Any]:
    candidates = [
        item
        for item in _snapshot_members(snapshot)
        if item.get("document_number") == document_ref or item["path"] == document_ref
    ]
    if len(candidates) != 1:
        raise ValidationFailure("design document reference is not uniquely registered")
    return candidates[0]


def read_design_document(reference: DesignSourceRef, document_ref: str) -> dict[str, Any]:
    snapshot = resolve_design_source(reference)
    member = _snapshot_member(snapshot, document_ref)
    root = _resolve_root(reference)
    path = _resolve_member(root, root, member["path"], "design document")
    content = _read_bounded(path, MAX_DOCUMENT_BYTES, "design document")
    return {**member, "content": content.decode("utf-8"), "snapshot_digest": snapshot["digest"]}


def check_design_source(
    reference: DesignSourceRef, expected_digest: str, document_ref: str | None = None
) -> dict[str, Any]:
    if not _DIGEST.fullmatch(expected_digest):
        raise ValidationFailure("expected design source digest is invalid")
    snapshot = resolve_design_source(reference)
    observed_digest = (
        _snapshot_member(snapshot, document_ref)["digest"]
        if document_ref is not None
        else snapshot["digest"]
    )
    return {
        "status": "current" if observed_digest == expected_digest else "stale",
        "document": document_ref,
        "expected_digest": expected_digest,
        "observed_digest": observed_digest,
        "snapshot_digest": snapshot["digest"],
        "observed_at": snapshot["observed_at"],
    }


def validate_review_package(package_root: Path | str, requirement_id: str) -> dict[str, Any]:
    if not _REQUIREMENT_ID.fullmatch(requirement_id):
        raise ValidationFailure("review package requirement id is invalid")
    root = Path(package_root).resolve(strict=True)
    if not root.is_dir():
        raise ValidationFailure("review package must be a directory")
    expected_tail = (
        ".run-artifacts",
        "engineering-assistant",
        "review-packages",
        requirement_id,
    )
    if root.parts[-4:] != expected_tail:
        raise ValidationFailure(
            "review package must be under .run-artifacts/engineering-assistant/"
            "review-packages/<REQUIREMENT-ID>"
        )
    required = (
        "01-impact-assessment.md",
        "04-interface-and-specialty-delta.yaml",
        "05-implementation-and-test-plan.md",
        "06-design-change-summary.md",
        "07-requirement-design-traceability.yaml",
        "08-review-checklist.md",
    )
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise ValidationFailure("review package is missing required files: " + ", ".join(missing))
    high_level_reviews = sorted(root.glob("02-high-level-design.review.md")) + sorted(
        root.glob("02-*-high-level-design.review.md")
    )
    detailed_reviews = sorted(root.glob("03-*-detailed-design.review.md"))
    reviews = high_level_reviews + detailed_reviews
    if not reviews:
        raise ValidationFailure("review package must contain at least one review design")
    for path in reviews:
        content = _read_bounded(path, MAX_DOCUMENT_BYTES, "review design").decode("utf-8")
        metadata = _frontmatter(content)
        if metadata.get("document_status") != "reviewing":
            raise ValidationFailure(f"review design must stay reviewing: {path.name}")
        if metadata.get("requirement_id") != requirement_id:
            raise ValidationFailure(f"review design requirement differs from package: {path.name}")
        for field in ("base_document_number", "base_version", "base_digest"):
            if not metadata.get(field):
                raise ValidationFailure(f"review design missing {field}: {path.name}")
        if not _DIGEST.fullmatch(str(metadata["base_digest"])):
            raise ValidationFailure(f"review design base digest is invalid: {path.name}")
        if _PLACEHOLDER.search(content):
            raise ValidationFailure(f"review design contains unresolved placeholder: {path.name}")

    if high_level_reviews:
        impact = (root / "01-impact-assessment.md").read_text(encoding="utf-8")
        if not re.search(r"^system_level_impact:\s*true\s*$", impact, re.MULTILINE):
            raise ValidationFailure("high-level design requires confirmed system-level impact")

    summary = (root / "06-design-change-summary.md").read_text(encoding="utf-8")
    for item in (
        "新增", "修改", "删除", "明确不变", "聚合", "不变量", "流程", "状态",
        "接口", "资源", "冲突", "合并顺序", "共同回归",
    ):
        if item not in summary:
            raise ValidationFailure(f"design change summary missing {item}")

    trace = (root / "07-requirement-design-traceability.yaml").read_text(encoding="utf-8")
    if not re.search(rf"^requirement_id:\s*['\"]?{re.escape(requirement_id)}['\"]?\s*$", trace, re.MULTILINE):
        raise ValidationFailure("traceability requirement differs from package")
    digest_match = re.search(r"^design_source_digest:\s*(sha256:[0-9a-f]{64})\s*$", trace, re.MULTILINE)
    if not digest_match or not re.search(r"^\s*-\s+requirement_item:\s*\S+", trace, re.MULTILINE):
        raise ValidationFailure("traceability must contain a source digest and mappings")
    mapping_blocks = re.split(r"(?=^\s*-\s+requirement_item:\s*)", trace, flags=re.MULTILINE)[1:]
    for block in mapping_blocks:
        for field in ("design_document", "design_section", "design_change", "code_targets", "test_cases", "status"):
            if not re.search(rf"^\s+{field}:\s*", block, re.MULTILINE):
                raise ValidationFailure(f"traceability mapping missing {field}")
    return {
        "status": "passed",
        "requirement_id": requirement_id,
        "design_source_digest": digest_match.group(1),
        "review_documents": [path.name for path in reviews],
        "files": sorted(path.name for path in root.iterdir() if path.is_file()),
    }
