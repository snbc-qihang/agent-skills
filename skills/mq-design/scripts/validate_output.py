#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

SKILL_ID = "mq-design"
POLICY = {
  "unresolved_markers": [
    "{",
    "}",
    "待补充",
    "待确认",
    "未知",
    "未确认",
    "人工评审确认",
    "待人工补充",
    "待用户补充",
    "pending_confirmation",
    "TBD",
    "TODO",
    "<填写",
    "请替换"
  ],
  "producer_fields": [
    "业务用途",
    "场景应用",
    "业务消息key",
    "消息类型",
    "消息体内容",
    "优先等级",
    "消息TTL（毫秒）",
    "持久化",
    "目的交换机",
    "路由key",
    "消息预估大小",
    "生产服务/模块名称",
    "软件需求号/bug号",
    "设计日期",
    "设计者",
    "备注"
  ],
  "consumer_fields": [
    "队列名称",
    "业务用途",
    "场景应用",
    "单消费节点消费",
    "队列类型",
    "优先队列",
    "是否持久化",
    "自动删除",
    "TTL",
    "消息大小",
    "绑定的Exchange/routingKey(多个）",
    "死信队列exchange/routeKey",
    "消费服务",
    "消息key",
    "运维监控",
    "软件需求号/bug号",
    "设计日期",
    "设计者",
    "备注"
  ],
  "producer_required_value_fields": [
    "业务用途",
    "场景应用",
    "业务消息key",
    "消息类型",
    "消息体内容",
    "目的交换机",
    "路由key",
    "生产服务/模块名称"
  ],
  "consumer_required_value_fields": [
    "队列名称",
    "业务用途",
    "场景应用",
    "绑定的Exchange/routingKey(多个）",
    "死信队列exchange/routeKey",
    "消费服务",
    "消息key",
    "运维监控"
  ],
  "formal_outputs": [
    "mq-design.xlsx",
    "mq-topic-contract.yaml",
    "message-schema.json",
    "mq-risk-report.json"
  ]
}


def load_payload(path):
    schema = json.loads(Path(__file__).parents[1].joinpath("output.schema.json").read_text(encoding="utf-8"))
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [field for field in schema.get("required", []) if field not in payload]
    if missing:
        raise SystemExit(f"缺少必填字段: {missing}")
    if payload.get("skill_id") != schema["properties"]["skill_id"]["const"]:
        raise SystemExit("skill_id 不匹配")
    if payload.get("status") not in schema["properties"]["status"]["enum"]:
        raise SystemExit("status 不合法")
    return payload


def artifact_map(payload):
    return {item.get("name"): item for item in payload.get("artifacts", [])}


def resolve_artifact(payload_path, item):
    raw = item.get("path") if item else ""
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path
    return Path(payload_path).parent / path


def read_artifact(payload_path, payload, name):
    item = artifact_map(payload).get(name)
    path = resolve_artifact(payload_path, item)
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def artifact_path(item):
    return (item or {}).get("path") or (item or {}).get("file") or (item or {}).get("uri") or ""


def artifact_kind(item):
    return " ".join(str(value).lower() for value in [
        (item or {}).get("name", ""),
        (item or {}).get("artifact_type", ""),
        artifact_path(item),
    ])


def is_waiting_support_artifact(item):
    text = artifact_kind(item)
    allowed = [
        "required-information",
        "missing-information",
        "human-review",
        "approval",
        "workflow-trace",
        "resume",
        "open-questions",
        "artifact-index",
    ]
    return any(token in text for token in allowed)


def is_formal_artifact(item):
    if is_waiting_support_artifact(item):
        return False
    path = artifact_path(item).lower()
    kind = artifact_kind(item)
    return path.endswith((".md", ".xlsx", ".xls", ".json", ".yaml", ".yml")) or any(token in kind for token in ["markdown", "xlsx", "json", "yaml"])


def blocking_information_requests(payload):
    for request in payload.get("required_information_requests", []) or []:
        if request.get("blocking") is True:
            return True
        for question in request.get("questions", []) or []:
            if isinstance(question, dict) and question.get("required") is True:
                return True
    return False


def artifact_texts(payload_path, payload):
    for item in payload.get("artifacts", []) or []:
        name = item.get("name", "")
        path = artifact_path(item).lower()
        if not (name.endswith(".md") or path.endswith(".md")):
            continue
        resolved = resolve_artifact(payload_path, item)
        if resolved and resolved.exists():
            yield name or path, resolved.read_text(encoding="utf-8")


def unresolved_markers(text):
    return [marker for marker in POLICY.get("unresolved_markers", []) if marker in text]


def candidate_project_roots(payload_path):
    path = Path(payload_path).resolve()
    roots = []
    for candidate in [path.parent, *path.parents]:
        if candidate not in roots:
            roots.append(candidate)
        if (candidate / "artifacts").exists():
            break
    cwd = Path.cwd().resolve()
    if cwd not in roots:
        roots.append(cwd)
    return roots


def leaked_formal_output_files(payload_path):
    leaks = []
    for output in POLICY.get("formal_outputs", []):
        for root in candidate_project_roots(payload_path):
            for candidate in [root / "artifacts" / SKILL_ID / output, root / output]:
                if candidate.exists():
                    leaks.append(str(candidate))
    return sorted(set(leaks))


def should_validate_formal_outputs(payload):
    status = payload.get("status")
    state = payload.get("preflight_input_state")
    if status == "waiting_for_input":
        return False
    return state in ('ready', 'waiting_for_human_review', 'blocked') or status in ('succeeded', 'failed', 'blocked', 'waiting_for_human_review')


def validate_preflight_order(payload_path, payload):
    errors = []
    status = payload.get("status")
    state = payload.get("preflight_input_state")
    if state not in ('ready', 'waiting_for_input', 'waiting_for_human_review', 'blocked'):
        errors.append("preflight_input_state 必须是 ready/waiting_for_input/waiting_for_human_review/blocked")
    if status == "waiting_for_input":
        if state != "waiting_for_input":
            errors.append("status=waiting_for_input 时 preflight_input_state 必须为 waiting_for_input")
        if not payload.get("required_information_requests"):
            errors.append("waiting_for_input 必须输出 required_information_requests 主动询问用户")
        for item in payload.get("artifacts", []) or []:
            if is_formal_artifact(item):
                errors.append("waiting_for_input 不得登记正式阶段产物，必须先等待补充信息写回: " + (artifact_path(item) or item.get("name", "")))
        leaks = leaked_formal_output_files(payload_path)
        if leaks:
            errors.append("waiting_for_input 不得先落盘正式阶段产物，必须先等待补充信息写回: " + ", ".join(leaks))
    if status == "waiting_for_human_review" and state not in ('waiting_for_human_review', 'blocked'):
        errors.append("status=waiting_for_human_review 时 preflight_input_state 必须为 waiting_for_human_review 或 blocked")
    if status == "succeeded":
        if state != "ready":
            errors.append("succeeded 必须满足 preflight_input_state == ready")
        if blocking_information_requests(payload):
            errors.append("succeeded 不允许存在未解决的 blocking required_information_requests")
        for name, text in artifact_texts(payload_path, payload):
            unresolved = unresolved_markers(text)
            if unresolved:
                errors.append(name + " 包含未决信息标记，必须先 waiting_for_input 并生成 human-review HTML: " + ", ".join(sorted(set(unresolved))))
    return errors


def markdown_headings(text):
    return [match.group(1).strip() for match in re.finditer(r"(?m)^#{1,6}\s*(?:\d+(?:\.\d+)*\s*)?(.+?)\s*$", text)]


def table_cells(line):
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def is_separator_row(line):
    cells = table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell.replace(" ", "")) for cell in cells)


def section_text(text, heading, next_heading_pattern=r"^#{1,3}\s*\d+(?:\.\d+)*\s+"):
    start = text.find(heading)
    if start < 0:
        return ""
    tail = text[start:]
    match = re.search(r"(?m)" + next_heading_pattern, tail[len(heading):])
    return tail if not match else tail[: len(heading) + match.start()]


def normalize_table_name(value):
    value = value.strip().strip("`").strip()
    if "." in value:
        value = value.split(".")[-1].strip("`")
    return value


def extract_table_names(value):
    return [normalize_table_name(item) for item in re.findall(r"`?([a-zA-Z][a-zA-Z0-9_]*\.[a-zA-Z][a-zA-Z0-9_]*|t_[a-zA-Z0-9_]+)`?", value)]


def design_object_value(text):
    for line in text.splitlines():
        cells = table_cells(line)
        if len(cells) >= 2 and cells[0] == "设计对象":
            return cells[1]
    return ""


def object_type_value(text):
    for line in text.splitlines():
        cells = table_cells(line)
        if len(cells) >= 2 and cells[0] == "对象类型":
            return cells[1]
    return ""


def table_group_members(text):
    names = []
    names.extend(extract_table_names(design_object_value(text)))
    group = section_text(text, "2.4 强耦合表组说明")
    for line in group.splitlines():
        cells = table_cells(line)
        if len(cells) >= 5 and cells[0] != "成员表" and not is_separator_row(line):
            names.extend(extract_table_names(cells[0]))
    deduped = []
    for name in names:
        if name and name not in deduped:
            deduped.append(name)
    return deduped


def create_table_names(sql):
    names = []
    pattern = r"(?is)\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?(?:`?[a-zA-Z][a-zA-Z0-9_]*`?\.)?`?([a-zA-Z][a-zA-Z0-9_]*)`?"
    for match in re.finditer(pattern, sql):
        names.append(normalize_table_name(match.group(1)))
    return names


def ddl_index_names(sql, table):
    names = set()
    table_pattern = re.escape(table)
    match = re.search(r"(?is)\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?(?:`?[a-zA-Z][a-zA-Z0-9_]*`?\.)?`?" + table_pattern + r"`?\s*\((.*?)\)\s*;", sql)
    if not match:
        return names
    body = match.group(1)
    if re.search(r"(?is)\bprimary\s+key\b", body):
        names.add("PRIMARY")
    for index_match in re.finditer(r"(?is)\b(?:unique\s+)?(?:key|index)\s+`?([a-zA-Z][a-zA-Z0-9_]*)`?", body):
        names.add(index_match.group(1))
    return names


def markdown_index_rows(text):
    rows = []
    in_index_table = False
    for line in section_text(text, "4.3 索引设计").splitlines():
        cells = table_cells(line)
        if cells == ["表", "索引名", "类型", "字段（顺序敏感）", "唯一", "服务场景", "备注"]:
            in_index_table = True
            continue
        if not in_index_table or is_separator_row(line):
            continue
        if len(cells) >= 7:
            rows.append({"table": normalize_table_name(cells[0]), "name": cells[1], "unique": cells[4]})
    return rows


def mermaid_blocks(text, diagram_type):
    pattern = r"```mermaid\s*\n\s*" + re.escape(diagram_type) + r"\b([\s\S]*?)```"
    return [match.group(1) for match in re.finditer(pattern, text)]


def service_sequence_participants(block):
    participants = {}
    for raw in block.splitlines():
        line = raw.strip()
        match = re.match(r"(?i)^(participant|actor)\s+([A-Za-z0-9_]+)(?:\s+as\s+(.+))?$", line)
        if match:
            participants[match.group(2)] = (match.group(3) or match.group(2)).strip()
    return participants


def service_sequence_endpoints(block):
    endpoints = []
    for raw in block.splitlines():
        line = raw.strip()
        match = re.match(r"([A-Za-z0-9_\u4e00-\u9fff]+)\s*(?:-+|=+|x-+|-->>|->>|->|-->)\s*([A-Za-z0-9_\u4e00-\u9fff]+)", line)
        if match:
            endpoints.extend([match.group(1), match.group(2)])
    return endpoints


def is_service_label(label, forbidden_terms):
    label = str(label).strip()
    if not label:
        return False
    if any(term and term in label for term in forbidden_terms):
        return False
    return "服务" in label or "Service" in label or label.endswith("Svc")


def has_abstract_participant_label(label, abstract_terms):
    label = str(label).strip()
    return any(term and term in label for term in abstract_terms)


def is_event_driven_design(text, event_terms):
    return any(term in text for term in event_terms)


def sequence_has_internal_processing(block, required_terms, outcome_terms):
    participants = service_sequence_participants(block)
    has_self_call = False
    for raw in block.splitlines():
        line = raw.strip()
        match = re.match(r"([A-Za-z0-9_一-鿿]+)\s*(?:-+|=+|-->>|->>|->|-->)\s*([A-Za-z0-9_一-鿿]+)\s*:\s*(.*)", line)
        if not match:
            continue
        left, right, message = match.group(1), match.group(2), match.group(3)
        if left == right:
            has_self_call = True
            if all(term in message for term in required_terms) and any(term in message for term in outcome_terms):
                return True
    if not has_self_call:
        return False
    # Allow split self-calls as long as the block as a whole shows the internal path.
    return all(term in block for term in required_terms) and any(term in block for term in outcome_terms)


def is_mq_db_redis_flow(text):
    has_mq = any(term in text for term in ["MQ", "消息", "消费", "队列", "死信"])
    has_db = any(term in text for term in ["DB", "数据库", "主表", "明细", "读模型"])
    has_redis = any(term in text for term in ["Redis", "缓存", "幂等记录", "状态处理记录", "乱序保护记录"])
    return has_mq and has_db and has_redis


def is_local_read_model_write(text):
    return "本地读模型" in text and any(term in text for term in ["写入", "保存", "upsert", "重建"])


def is_local_read_model_delete(text):
    return "本地读模型" in text and any(term in text for term in ["删除", "移除", "失效"])


def is_query_or_export_flow(text):
    return any(term in text for term in ["查询流程", "导出流程", "查询 / 导出", "列表查询", "分批导出"])


def read_json_artifact(payload_path, payload, name):
    text = read_artifact(payload_path, payload, name)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def participant_evidence_entries(payload_path, payload):
    data = read_json_artifact(payload_path, payload, "participant-evidence-map.json")
    if not isinstance(data, dict):
        return None
    raw_entries = data.get("participants") or data.get("services") or data.get("items") or []
    entries = {}
    if isinstance(raw_entries, dict):
        raw_entries = [{"participant": key, **(value if isinstance(value, dict) else {"evidence": value})} for key, value in raw_entries.items()]
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        keys = [
            item.get("participant"), item.get("alias"), item.get("service"), item.get("service_name"),
            item.get("name"), item.get("label"), item.get("display_name"), item.get("service_label"),
        ]
        for key in keys:
            if key:
                entries[str(key).strip()] = item
    return entries


def has_confirmed_participant_evidence(item):
    if not isinstance(item, dict):
        return False
    status = str(item.get("status") or item.get("evidence_status") or "").strip().lower()
    if status in ('unknown', 'proposed', 'assumed', 'todo', 'pending', 'pending_confirmation', 'unconfirmed', 'missing'):
        return False
    evidence_fields = [
        "repo_context", "repo_context_ref", "code_path", "source_path", "module_path", "service_registry_ref",
        "evidence", "evidence_refs", "source_artifacts", "owner_module", "pom", "build_file",
    ]
    if any(item.get(field) for field in evidence_fields):
        return True
    return status in ('confirmed', 'matched', 'verified', 'existing')


def fail(errors):
    if errors:
        raise SystemExit("\n".join(errors))
    print("ok")


XLSX_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def _shared_text(si):
    return "".join(t.text or "" for t in si.findall(".//a:t", XLSX_NS))


def _cell_ref_to_col(ref):
    letters = re.match(r"([A-Z]+)", ref or "")
    if not letters:
        return 0
    index = 0
    for char in letters.group(1):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def _normalize_xlsx_target(target):
    normalized = (target or "").replace("\\", "/").lstrip("/")
    if normalized.startswith("xl/"):
        return normalized
    return "xl/" + normalized


def read_xlsx_artifact(payload_path, payload, name):
    item = artifact_map(payload).get(name)
    path = resolve_artifact(payload_path, item)
    if not path or not path.exists():
        return None, "缺少 " + name + " artifact 或文件不可读"
    if path.suffix.lower() != ".xlsx":
        return None, name + " 必须是 .xlsx 文件"
    try:
        with zipfile.ZipFile(path) as workbook:
            shared = []
            if "xl/sharedStrings.xml" in workbook.namelist():
                shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
                shared = [_shared_text(si) for si in shared_root.findall("a:si", XLSX_NS)]
            rels_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
            rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_root}
            workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
            sheets = {}
            all_text = []
            for sheet in workbook_root.findall(".//a:sheet", XLSX_NS):
                name = sheet.attrib.get("name", "")
                rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
                target = rels.get(rel_id, "")
                if not target:
                    continue
                sheet_path = _normalize_xlsx_target(target)
                sheet_root = ET.fromstring(workbook.read(sheet_path))
                rows = {}
                for row in sheet_root.findall(".//a:sheetData/a:row", XLSX_NS):
                    row_number = int(row.attrib.get("r", "0") or 0)
                    values = []
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
                        if value:
                            all_text.append(value)
                    rows[row_number] = values
                sheets[name] = rows
            return {"sheets": sheets, "text": "\n".join(all_text)}, ""
    except Exception as exc:
        return None, "无法读取 mq-design.xlsx: " + str(exc)


def _cell_value(cell, shared):
    value = ""
    if cell.attrib.get("t") == "inlineStr":
        value = "".join(t.text or "" for t in cell.findall(".//a:t", XLSX_NS))
    else:
        node = cell.find("a:v", XLSX_NS)
        if node is not None and node.text is not None:
            value = shared[int(node.text)] if cell.attrib.get("t") == "s" and shared else node.text
    return value


def read_xlsx_template_signature(path):
    with zipfile.ZipFile(path) as workbook:
        shared = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared = [_shared_text(si) for si in shared_root.findall("a:si", XLSX_NS)]
        rels_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_root}
        workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
        signature = {
            "style_bytes": workbook.read("xl/styles.xml") if "xl/styles.xml" in workbook.namelist() else b"",
            "sheet_order": [],
            "sheets": {},
        }
        for sheet in workbook_root.findall(".//a:sheet", XLSX_NS):
            sheet_name = sheet.attrib.get("name", "")
            signature["sheet_order"].append(sheet_name)
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
            target = rels.get(rel_id, "")
            sheet_path = _normalize_xlsx_target(target)
            sheet_root = ET.fromstring(workbook.read(sheet_path))
            dimension = sheet_root.find("a:dimension", XLSX_NS)
            merge_refs = [
                merge.attrib.get("ref", "")
                for merge in sheet_root.findall(".//a:mergeCells/a:mergeCell", XLSX_NS)
            ]
            cells = {}
            for cell in sheet_root.findall(".//a:sheetData/a:row/a:c", XLSX_NS):
                ref = cell.attrib.get("r", "")
                cells[ref] = {
                    "style": cell.attrib.get("s", ""),
                    "value": _cell_value(cell, shared),
                }
            signature["sheets"][sheet_name] = {
                "dimension": dimension.attrib.get("ref", "") if dimension is not None else "",
                "merge_refs": merge_refs,
                "cells": cells,
            }
        return signature


def validate_mq_template_integrity(payload_path, payload):
    errors = []
    item = artifact_map(payload).get("mq-design.xlsx")
    output_path = resolve_artifact(payload_path, item)
    if not output_path or not output_path.exists():
        return errors
    template_path = Path(__file__).parents[1] / "assets" / "mq-design-template.xlsx"
    try:
        template = read_xlsx_template_signature(template_path)
        output = read_xlsx_template_signature(output_path)
    except Exception as exc:
        return ["无法校验 mq-design.xlsx 模板一致性: " + str(exc)]
    if output["style_bytes"] != template["style_bytes"]:
        errors.append("mq-design.xlsx 不得修改模板样式定义 styles.xml")
    if output["sheet_order"] != template["sheet_order"]:
        errors.append("mq-design.xlsx 必须保留模板 sheet 名称和顺序: " + ", ".join(template["sheet_order"]))
    for sheet_name in template["sheet_order"]:
        expected = template["sheets"].get(sheet_name, {})
        actual = output["sheets"].get(sheet_name, {})
        if not actual:
            errors.append("mq-design.xlsx 缺少模板 sheet: " + sheet_name)
            continue
        if actual.get("dimension") != expected.get("dimension"):
            errors.append(f"mq-design.xlsx 的 {sheet_name} sheet 不得追加行列或改变模板范围: {expected.get('dimension')} -> {actual.get('dimension')}")
        if actual.get("merge_refs") != expected.get("merge_refs"):
            errors.append("mq-design.xlsx 的 " + sheet_name + " sheet 不得修改合并单元格")
        expected_cells = expected.get("cells", {})
        actual_cells = actual.get("cells", {})
        for ref, expected_cell in expected_cells.items():
            actual_cell = actual_cells.get(ref)
            if actual_cell is None:
                errors.append(f"mq-design.xlsx 的 {sheet_name}!{ref} 模板单元格不得删除")
                continue
            if actual_cell.get("style") != expected_cell.get("style"):
                errors.append(f"mq-design.xlsx 的 {sheet_name}!{ref} 不得修改模板样式")
            if expected_cell.get("value") and actual_cell.get("value") != expected_cell.get("value"):
                errors.append(f"mq-design.xlsx 的 {sheet_name}!{ref} 固定模板文本不得修改")
        for ref, actual_cell in actual_cells.items():
            if ref not in expected_cells and actual_cell.get("value"):
                errors.append(f"mq-design.xlsx 的 {sheet_name}!{ref} 不得新增非模板单元格")
    return errors


def _header_index_map(header):
    mapping = {}
    for index, value in enumerate(header):
        if value:
            mapping[value] = index
    return mapping


def _non_empty_rows(rows):
    result = []
    for row_number, values in sorted(rows.items()):
        if row_number <= 1:
            continue
        if any(str(value).strip() for value in values):
            result.append((row_number, values))
    return result


def _validate_required_sheet_values(errors, rows, header, required_fields, sheet_name):
    header_map = _header_index_map(header)
    missing_headers = [field for field in required_fields if field not in header_map]
    if missing_headers:
        errors.append(f"mq-design.xlsx 的 {sheet_name} sheet 缺少必填业务列: " + "、".join(missing_headers))
        return
    for row_number, values in _non_empty_rows(rows):
        missing_values = []
        for field in required_fields:
            index = header_map[field]
            value = values[index].strip() if index < len(values) and isinstance(values[index], str) else (str(values[index]).strip() if index < len(values) else "")
            if not value:
                missing_values.append(field)
        if missing_values:
            errors.append(f"mq-design.xlsx 的 {sheet_name} sheet 第 {row_number} 行缺少必填业务值: " + "、".join(missing_values))


def validate_output(payload_path, payload):
    errors = []
    workbook, error = read_xlsx_artifact(payload_path, payload, "mq-design.xlsx")
    if error:
        return [error]
    errors.extend(validate_mq_template_integrity(payload_path, payload))
    sheets = workbook["sheets"]
    text = workbook["text"]
    if "mq-design.md" in artifact_map(payload):
        errors.append("正式 MQ 设计正文必须是 mq-design.xlsx，不得登记 mq-design.md")
    if "生产者" not in sheets:
        errors.append("mq-design.xlsx 缺少生产者 sheet")
    if "消费者" not in sheets:
        errors.append("mq-design.xlsx 缺少消费者 sheet")
    producer_header = sheets.get("生产者", {}).get(1, [])
    consumer_header = sheets.get("消费者", {}).get(1, [])
    for field in POLICY["producer_fields"]:
        if field not in producer_header:
            errors.append("mq-design.xlsx 生产者表缺少字段: " + field)
    for field in POLICY["consumer_fields"]:
        if field not in consumer_header:
            errors.append("mq-design.xlsx 消费者表缺少字段: " + field)
    _validate_required_sheet_values(errors, sheets.get("生产者", {}), producer_header, POLICY.get("producer_required_value_fields", []), "生产者")
    _validate_required_sheet_values(errors, sheets.get("消费者", {}), consumer_header, POLICY.get("consumer_required_value_fields", []), "消费者")
    if "死信" not in text:
        errors.append("MQ 必须设计死信队列")
    if "幂等" not in text:
        errors.append("MQ 必须定义幂等策略")
    if "重试" not in text:
        errors.append("MQ 必须定义重试策略")
    if "回放" not in text:
        errors.append("MQ 必须定义回放策略")
    for size in re.findall(r"(\d+)\s*KB", text, re.IGNORECASE):
        if int(size) > 10 and payload.get("status") == "succeeded":
            errors.append("消息体超过 10KB 必须 waiting_for_human_review")
    if payload.get("status") == "succeeded" and any(term in text for term in ["回放生产消息", "删除队列", "重命名队列", "删除 topic", "重命名 topic", "删除Topic", "重命名Topic"]):
        errors.append("生产消息回放或删除/重命名 topic/queue 必须 waiting_for_human_review")
    return errors


payload_path = Path(sys.argv[1])
payload = load_payload(payload_path)
errors = validate_preflight_order(payload_path, payload)
if should_validate_formal_outputs(payload):
    errors.extend(validate_output(payload_path, payload))
fail(errors)
