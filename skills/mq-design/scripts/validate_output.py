#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

SKILL_ID = "mq-design"
POLICY = {
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


def read_json_artifact(payload_path, payload, name):
    text = read_artifact(payload_path, payload, name)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


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
                sheet_path = "xl/" + target.lstrip("/")
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


def validate_output(payload_path, payload):
    errors = []
    workbook, error = read_xlsx_artifact(payload_path, payload, "mq-design.xlsx")
    if error:
        return [error]
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
fail(validate_output(payload_path, payload))
