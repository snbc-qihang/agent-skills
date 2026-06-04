#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

SKILL_ID = "detailed-design"
POLICY = {
  "required_sections": [
    "1. 修订历史",
    "2. 设计背景与目标摘要",
    "2.1 原始需求与原型引用矩阵",
    "3. 模块/功能详细设计",
    "3.1. 业务流程图",
    "3.2. UML类图",
    "4. 数据库设计",
    "5. 接口定义",
    "5.1. API接口列表",
    "5.2. 中间件设计",
    "6. 单元测试",
    "7. 性能与扩展性设计",
    "8. 人工评审项"
  ],
  "forbidden_headings": [
    "来源证据",
    "技术选型",
    "业务规则与校验",
    "幂等与一致性",
    "异常与日志",
    "发布",
    "灰度",
    "上线"
  ],
  "flow_note_fields": [
    "业务规则",
    "校验规则",
    "事务边界",
    "幂等与一致性",
    "异常场景",
    "日志要求"
  ],
  "flow_required_branch_terms": {
    "异常分支": [
      "异常",
      "失败",
      "校验失败",
      "权限失败",
      "状态失败",
      "调用失败",
      "超时"
    ],
    "失败终态": [
      "失败结束",
      "异常结束",
      "终止",
      "人工处理",
      "补偿完成",
      "回滚"
    ],
    "补偿/重试/人工处理": [
      "补偿",
      "重试",
      "人工处理",
      "回滚",
      "告警"
    ]
  },
  "exception_table_required_fields": [
    "场景",
    "触发条件",
    "异常编码",
    "异常信息",
    "系统处理动作",
    "数据状态",
    "日志/告警",
    "补偿/重试/人工处理"
  ],
  "ddd_terms": [
    "DDD",
    "聚合根",
    "领域服务",
    "ApplicationService",
    "Repository",
    "Handler",
    "Strategy",
    "Template",
    "port",
    "adapter"
  ],
  "specialty_docs": {
    "database-design.md": "数据库设计",
    "mq-design.xlsx": "MQ 设计",
    "redis-design.md": "Redis 设计",
    "interface-contracts.yaml": "接口契约",
    "test-strategy.md": "测试策略"
  },
  "source_traceability_header": "| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |"
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
    text = read_artifact(payload_path, payload, "detailed-design.md")
    if not text:
        return ["缺少 detailed-design.md artifact 或文件不可读"]
    for section in POLICY["required_sections"]:
        if section not in text:
            errors.append("detailed-design.md 缺少团队详细设计模板章节: " + section)
    section_positions = []
    for section in POLICY["required_sections"]:
        index = text.find(section)
        if index >= 0:
            section_positions.append(index)
    if section_positions != sorted(section_positions):
        errors.append("detailed-design.md 章节顺序必须与团队详细设计模板一致")
    normalized_headings = [re.sub(r"\s+", " ", heading).strip(" ：:") for heading in markdown_headings(text)]
    for forbidden in POLICY["forbidden_headings"]:
        if any(heading == forbidden or heading.startswith(forbidden + " ") for heading in normalized_headings):
            errors.append("detailed-design.md 包含禁止标题: " + forbidden)
    if "sequenceDiagram" in text:
        errors.append("detailed-design.md 不得包含 sequenceDiagram")
    if "flowchart" not in text:
        errors.append("detailed-design.md 必须包含 flowchart")
    flow_blocks = list(re.finditer(r"```mermaid\s*\n\s*flowchart[\s\S]*?```", text))
    for index, block in enumerate(flow_blocks, start=1):
        tail = text[block.end(): block.end() + 700]
        flow_context = block.group(0)
        if "流程设计说明" not in tail:
            errors.append(f"第 {index} 个 flowchart 后缺少流程设计说明")
            continue
        for label, terms in POLICY["flow_required_branch_terms"].items():
            if not any(term in flow_context for term in terms):
                errors.append(f"第 {index} 个 flowchart 缺少{label}: " + "、".join(terms))
        for field in POLICY["flow_note_fields"]:
            if field not in tail:
                errors.append(f"第 {index} 个 flowchart 的流程设计说明缺少 {field}")
    exception_headers = []
    for line in text.splitlines():
        cells = table_cells(line)
        if cells and not is_separator_row(line) and "场景" in cells and "触发条件" in cells:
            exception_headers.append(cells)
    field_aliases = {
        "异常编码": ["异常编码", "返回编码"],
        "日志/告警": ["日志/告警", "日志要求", "告警"],
        "补偿/重试/人工处理": ["补偿/重试/人工处理", "补偿", "重试", "人工处理"],
    }
    if not exception_headers:
        errors.append("异常场景表缺少字段: " + "、".join(POLICY["exception_table_required_fields"]))
    else:
        best_header = max(exception_headers, key=len)
        missing_fields = []
        for field in POLICY["exception_table_required_fields"]:
            aliases = field_aliases.get(field, [field])
            if not any(any(alias in cell for cell in best_header) for alias in aliases):
                missing_fields.append(field)
        if missing_fields:
            errors.append("异常场景表缺少字段: " + "、".join(missing_fields))
    if any(term in text for term in POLICY["ddd_terms"]) and "classDiagram" not in text:
        errors.append("出现 DDD/分层/扩展点关键词时必须包含 classDiagram")
    if POLICY["source_traceability_header"] not in text:
        errors.append("detailed-design.md 缺少原始需求与原型引用矩阵列头: " + POLICY["source_traceability_header"])
    artifacts = artifact_map(payload)
    for doc_name in POLICY["specialty_docs"]:
        if doc_name not in artifacts:
            errors.append("StageRunResult.artifacts 未登记专项文档: " + doc_name)
    status = payload.get("status")
    high_risk_terms = ["DDL", "CREATE TABLE", "ALTER TABLE", "新队列", "新 topic", "新Topic", "Redis 新 Key", "新增 Key"]
    if status == "succeeded" and any(term in text for term in high_risk_terms):
        errors.append("存在 DDL、MQ 新队列/topic 或 Redis 新 Key 时状态必须为 waiting_for_human_review")
    return errors


payload_path = Path(sys.argv[1])
payload = load_payload(payload_path)
fail(validate_output(payload_path, payload))
