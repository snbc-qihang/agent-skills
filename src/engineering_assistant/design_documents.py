"""Structural checks for design drafts; approval remains a separate gate."""
from __future__ import annotations
import re
from pathlib import Path
from .validation import ValidationFailure


PLACEHOLDERS = re.compile(r"TODO|TBD|待填写|待补充|待确认|待核实|\[(?:填写|待|姓名|日期)[^\]]*\]", re.I)


def _structure(markdown: str) -> tuple[list[str], list[tuple[str, str]]]:
    headings, tables = [], []
    fenced = False
    section = ""
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
        if fenced:
            continue
        if re.match(r"^#{2,3} ", line):
            section = line.strip()
            headings.append(section)
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.fullmatch(r"[ |:−-]+", lines[i + 1]) and "-" in lines[i + 1]:
            tables.append((section, "|".join(cell.strip() for cell in line.strip().strip("|").split("|"))))
    return headings, tables


def validate_template(document: str, template: str) -> None:
    expected = _structure(template)
    if not expected[0]:
        raise ValidationFailure("template has no section contract")
    if _structure(document) != expected:
        raise ValidationFailure("design headings, order or table headers differ from the template")
    if PLACEHOLDERS.search(document):
        raise ValidationFailure("design draft has unresolved placeholders")
    markers = set(re.findall(r"\{[^{}\n]+\}", template))
    if any(marker in document for marker in markers):
        raise ValidationFailure("design draft retains template field markers")
    headings = list(re.finditer(r"^(#{2,3}) .*$", document, re.M))
    for i, heading in enumerate(headings):
        following = next((h for h in headings[i + 1:] if len(h.group(1)) <= len(heading.group(1))), None)
        body = document[heading.end():following.start() if following else len(document)].strip()
        if not body:
            raise ValidationFailure("design draft has an empty section")


def validate_design_document(kind: str, artifact: dict, schema_root: Path) -> dict:
    if kind == "database-design":
        relative = Path("skills/codebase-design/references/relational-oltp-detailed-design-template.md")
        template_path = schema_root.parent / relative
        if not template_path.is_file():
            template_path = schema_root.parent.parent / relative
        validate_template(artifact["document"], template_path.read_text(encoding="utf-8"))
    else:
        documents = {item["id"]: item for item in artifact["documents"]}
        if len(documents) != len(artifact["documents"]):
            raise ValidationFailure("duplicate review document id")
        required_roles = {"impact", "specialist-diff", "implementation-test-plan", "change-summary", "checklist", "context-design"}
        if not required_roles.issubset({item["role"] for item in documents.values()}):
            raise ValidationFailure("review package is missing a required document role")
        for document in documents.values():
            if PLACEHOLDERS.search(document["content"]):
                raise ValidationFailure("review document has unresolved placeholders")
            if document["role"] in {"context-design", "hld"}:
                for field in ("base_document_number", "base_version", "base_digest", "template"):
                    if not document.get(field):
                        raise ValidationFailure("design draft is missing baseline or template metadata")
                validate_template(document["content"], document["template"])
            if document["role"] == "database-design":
                validate_design_document("database-design", {"document": document["content"]}, schema_root)
        covered = set()
        design_roles = {"context-design", "hld", "database-design", "specialist-diff"}
        for row in artifact["traceability"]:
            if row["requirement_item"] not in artifact["requirement_items"]:
                raise ValidationFailure("traceability references an undeclared requirement")
            values = [row["design_change"], row["status"], *row["code_targets"], *row["test_cases"]]
            if any(not value.strip() or PLACEHOLDERS.search(value) for value in values):
                raise ValidationFailure("traceability has unresolved fields")
            doc = documents.get(row["design_document"])
            if not doc or doc["role"] not in design_roles or row["design_section"] not in _structure(doc["content"])[0]:
                raise ValidationFailure("traceability references a missing design section")
            covered.add(row["requirement_item"])
        if covered != set(artifact["requirement_items"]):
            raise ValidationFailure("traceability does not cover every requirement item")
    return {"status": "passed", "kind": kind, "validation_scope": "structure",
            "source_freshness": "not_verified", "human_review_status": "not_verified"}
