#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

SKILL_ID = "high-level-design"
POLICY = {
  "required_sections": [
    "0. 原始需求与原型追溯",
    "1. 版本变更记录",
    "2. 平台概述",
    "3. 系统设计",
    "3.1 系统逻辑视图",
    "3.1.1 系统设计原则",
    "3.3 研发视图",
    "3.4 研发结构定义",
    "4. 核心功能",
    "4.1.3 跨服务服务间时序图",
    "5.中间件设计",
    "6.数据视图"
  ],
  "forbidden_headings": [
    "证据",
    "Findings",
    "必须补充信息",
    "门禁决策"
  ],
  "detailed_implementation_forbidden_terms": [
    "请求字段",
    "返回字段",
    "CREATE TABLE",
    "ALTER TABLE",
    "DROP TABLE",
    "字段类型",
    "索引名",
    "Controller",
    "Mapper",
    "Repository",
    "方法签名",
    "伪代码",
    "单元测试步骤"
  ],
  "source_traceability_header": "| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |",
  "service_sequence_forbidden_participants": [
    "用户",
    "页面",
    "前端",
    "客户端",
    "Controller",
    "API",
    "接口",
    "数据库",
    "DB",
    "Redis",
    "MQ",
    "Topic",
    "Queue",
    "表",
    "Mapper",
    "Repository"
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


def validate_output(payload_path, payload):
    errors = []
    text = read_artifact(payload_path, payload, "high-level-design.md")
    if not text:
        return ["缺少 high-level-design.md artifact 或文件不可读"]
    for section in POLICY["required_sections"]:
        if section not in text:
            errors.append("high-level-design.md 缺少团队概要设计模板章节: " + section)
    section_positions = []
    for section in POLICY["required_sections"]:
        index = text.find(section)
        if index >= 0:
            section_positions.append(index)
    if section_positions != sorted(section_positions):
        errors.append("high-level-design.md 章节顺序必须与团队概要设计模板一致")
    normalized_headings = [re.sub(r"\s+", " ", heading).strip(" ：:") for heading in markdown_headings(text)]
    for forbidden in POLICY["forbidden_headings"]:
        if any(heading == forbidden or heading.startswith(forbidden + " ") for heading in normalized_headings):
            errors.append("high-level-design.md 不得使用通用产物模板标题: " + forbidden)
    for required in ["系统逻辑视图", "系统设计原则", "研发视图", "研发结构定义", "中间件设计", "数据视图"]:
        if required not in text:
            errors.append("high-level-design.md 缺少概要设计核心内容: " + required)
    for term in POLICY["detailed_implementation_forbidden_terms"]:
        if term in text:
            errors.append("概要设计不得展开详细设计内容: " + term)
    if POLICY["source_traceability_header"] not in text:
        errors.append("high-level-design.md 缺少原始需求与原型追溯矩阵列头: " + POLICY["source_traceability_header"])
    sequence_blocks = mermaid_blocks(text, "sequenceDiagram")
    if not sequence_blocks:
        errors.append("high-level-design.md 跨服务核心场景必须包含 Mermaid sequenceDiagram 服务间时序图")
    for block_index, block in enumerate(sequence_blocks, start=1):
        participants = service_sequence_participants(block)
        if not participants:
            errors.append(f"第 {block_index} 个 sequenceDiagram 必须显式声明 participant，且 participant 只能是服务")
        for alias, label in participants.items():
            if not is_service_label(label, POLICY["service_sequence_forbidden_participants"]):
                errors.append(f"第 {block_index} 个 sequenceDiagram participant 不是服务: {label}")
        for endpoint in service_sequence_endpoints(block):
            label = participants.get(endpoint, endpoint)
            if not is_service_label(label, POLICY["service_sequence_forbidden_participants"]):
                errors.append(f"第 {block_index} 个 sequenceDiagram 消息端点不是服务: {label}")
    return errors


payload_path = Path(sys.argv[1])
payload = load_payload(payload_path)
fail(validate_output(payload_path, payload))
