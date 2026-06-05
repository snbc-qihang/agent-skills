#!/usr/bin/env python3
"""Compare two design run roots for normalized structural stability."""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


XLSX_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def normalize_xlsx_target(target: str) -> str:
    normalized = (target or "").replace("\\", "/").lstrip("/")
    if normalized.startswith("xl/"):
        return normalized
    return "xl/" + normalized


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def markdown_headings(text: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"(?m)^#{1,6}\s*(.+?)\s*$", text)]


def mermaid_flow_blocks(text: str) -> list[str]:
    blocks = []
    for match in re.finditer(r"```mermaid\s*\n\s*flowchart\b([\s\S]*?)```", text):
        block = re.sub(r"\s+", " ", match.group(1)).strip()
        blocks.append(block)
    return blocks


def normalize_table_name(value: str) -> str:
    value = value.strip().strip("`")
    if "." in value:
        value = value.split(".")[-1].strip("`")
    return value


def extract_table_names(text: str) -> list[str]:
    names = [normalize_table_name(item) for item in re.findall(r"`?([a-zA-Z][a-zA-Z0-9_]*\.[a-zA-Z][a-zA-Z0-9_]*|t_[a-zA-Z0-9_]+)`?", text)]
    deduped: list[str] = []
    for name in names:
        if name and name not in deduped:
            deduped.append(name)
    return deduped


def hld_signal(root: Path) -> dict:
    text = read_text(root / "artifacts" / "high-level-design" / "high-level-design.md")
    return {
        "headings": markdown_headings(text),
        "has_flowchart": "flowchart" in text,
        "sequence_count": len(re.findall(r"```mermaid\s*\n\s*sequenceDiagram\b", text)),
    }


def ddd_signal(root: Path) -> dict:
    text = read_text(root / "artifacts" / "detailed-design" / "detailed-design.md")
    return {
        "headings": markdown_headings(text),
        "flow_blocks": mermaid_flow_blocks(text),
        "exception_table_count": len(re.findall(r"(?m)^\|\s*场景\s*\|\s*触发条件\s*\|", text)),
    }


def db_signal(root: Path) -> dict:
    text = read_text(root / "artifacts" / "database-design" / "database-design.md")
    return {
        "headings": markdown_headings(text),
        "member_tables": extract_table_names(text),
        "template_markers": {marker: (marker in text) for marker in ["应写明：", "不应重复：", "编写要点：", "样例 SQL（MySQL 风格，可按项目替换）", "文档结束"]},
    }


def _shared_text(si: ET.Element) -> str:
    return "".join(t.text or "" for t in si.findall(".//a:t", XLSX_NS))


def _cell_ref_to_col(ref: str) -> int:
    letters = re.match(r"([A-Z]+)", ref or "")
    if not letters:
        return 0
    index = 0
    for char in letters.group(1):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def mq_signal(root: Path) -> dict:
    path = root / "artifacts" / "mq-design" / "mq-design.xlsx"
    if not path.exists():
        return {}
    with zipfile.ZipFile(path) as workbook:
        shared = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared = [_shared_text(si) for si in shared_root.findall("a:si", XLSX_NS)]
        rels_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_root}
        workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
        sheet_order = []
        sheets = {}
        for sheet in workbook_root.findall(".//a:sheet", XLSX_NS):
            sheet_name = sheet.attrib.get("name", "")
            sheet_order.append(sheet_name)
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
            target = normalize_xlsx_target(rels.get(rel_id, ""))
            sheet_root = ET.fromstring(workbook.read(target))
            rows = {}
            for row in sheet_root.findall(".//a:sheetData/a:row", XLSX_NS):
                row_number = int(row.attrib.get("r", "0") or 0)
                values: list[str] = []
                for cell in row.findall("a:c", XLSX_NS):
                    col_index = _cell_ref_to_col(cell.attrib.get("r", ""))
                    while len(values) <= col_index:
                        values.append("")
                    value = ""
                    if cell.attrib.get("t") == "inlineStr":
                        value = "".join(t.text or "" for t in cell.findall(".//a:t", XLSX_NS))
                    else:
                        node = cell.find("a:v", XLSX_NS)
                        if node is not None and node.text is not None:
                            value = shared[int(node.text)] if cell.attrib.get("t") == "s" and shared else node.text
                    values[col_index] = value
                rows[row_number] = values
            header = rows.get(1, [])
            occupancy = []
            for row_number, values in sorted(rows.items()):
                if row_number <= 1 or not any(str(value).strip() for value in values):
                    continue
                occupied_headers = []
                for index, value in enumerate(values):
                    if str(value).strip() and index < len(header) and str(header[index]).strip():
                        occupied_headers.append(header[index])
                occupancy.append({"row": row_number, "headers": occupied_headers})
            sheets[sheet_name] = {"header": header, "occupancy": occupancy}
    return {"sheet_order": sheet_order, "sheets": sheets}


def artifact_inventory(root: Path) -> list[str]:
    result = []
    for path in (root / "artifacts").rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            rel = re.sub(r"docs/human-review/[^/]+\.html$", "docs/human-review/*.html", rel)
            result.append(rel)
    return sorted(result)


def stage_signal(root: Path) -> dict:
    stage_path = root / "stage-run-result.json"
    if not stage_path.exists():
        return {}
    payload = json.loads(stage_path.read_text(encoding="utf-8"))
    findings = [
        {"id": item.get("id"), "severity": item.get("severity")}
        for item in payload.get("findings", []) or []
    ]
    artifacts = sorted(item.get("name", "") for item in payload.get("artifacts", []) or [])
    return {
        "status": payload.get("status"),
        "preflight_input_state": payload.get("preflight_input_state"),
        "artifact_names": artifacts,
        "findings": findings,
    }


def load_signal(root: Path) -> dict:
    return {
        "hld": hld_signal(root),
        "ddd": ddd_signal(root),
        "db": db_signal(root),
        "mq": mq_signal(root),
        "artifact_inventory": artifact_inventory(root),
        "stage": stage_signal(root),
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check_design_run_stability.py <run-root-a> <run-root-b>", file=sys.stderr)
        return 2
    left = Path(sys.argv[1]).resolve()
    right = Path(sys.argv[2]).resolve()
    left_signal = load_signal(left)
    right_signal = load_signal(right)
    if left_signal != right_signal:
        print(json.dumps({"left": left_signal, "right": right_signal}, ensure_ascii=False, indent=2))
        return 1
    print("stable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
