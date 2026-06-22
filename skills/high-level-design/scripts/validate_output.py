#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

SKILL_ID = "high-level-design"
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
    "4.1.2 关键协作摘要",
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
  "forbidden_mermaid": [
    "flowchart"
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
  ],
  "abstract_participant_label_terms": [
    "权限组织服务",
    "数据权限服务",
    "支付通知服务",
    "查询服务",
    "组织服务",
    "风控服务"
  ],
  "event_driven_terms": [
    "MQ",
    "消息",
    "事件",
    "异步"
  ],
  "create_event_terms": [
    "创建类消息",
    "新增类消息",
    "产生类消息",
    "创建消息",
    "新增消息",
    "产生消息"
  ],
  "state_event_terms": [
    "状态变更消息",
    "删除消息",
    "失效消息",
    "状态变更类消息",
    "删除类消息",
    "失效类消息"
  ],
  "internal_sequence_terms": [
    "校验",
    "幂等",
    "处理记录"
  ],
  "internal_sequence_outcome_terms": [
    "查询",
    "事实详情",
    "保存",
    "写入",
    "删除",
    "移除",
    "本地读模型",
    "重试",
    "死信"
  ],
  "formal_outputs": [
    "high-level-design.md",
    "architecture-decision-record.md",
    "module-boundary.yaml",
    "risk-list.json"
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
    markers = []
    for marker in POLICY.get("unresolved_markers", []):
        if marker in ('{', '}'):
            if re.search(r"\{[^{}\n]{1,80}\}", text):
                markers.append(marker)
            continue
        if marker in text:
            markers.append(marker)
    return markers


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


def requires_database_er_diagram(text, trigger_terms):
    if any(term in text for term in ["CREATE TABLE", "ALTER TABLE", "DROP TABLE", "本地读模型", "表结构"]):
        return True
    if re.search(r"\bt_[a-zA-Z0-9_]+\b", text):
        return True
    if "主表" in text and any(term in text for term in ["明细", "关联表", "从表"]):
        return True
    has_database_noun = any(term in text for term in ["数据库", "DB"])
    has_database_action = any(term in text for term in ["查询", "写入", "更新", "删除", "upsert", "事务", "回滚", "提交"])
    if has_database_noun and has_database_action:
        return True
    return any(term in text for term in trigger_terms)


def er_diagram_entities(block):
    names = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        relation = re.match(r"^`?([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff\.]*)`?\s+[|}{oO-]+\s+`?([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff\.]*)`?\s*:", line)
        if relation:
            names.extend([normalize_table_name(relation.group(1)), normalize_table_name(relation.group(2))])
            continue
        entity = re.match(r"^`?([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff\.]*)`?\s*\{$", line)
        if entity:
            names.append(normalize_table_name(entity.group(1)))
    deduped = []
    for name in names:
        if name and name not in deduped:
            deduped.append(name)
    return deduped


def er_diagram_has_relationship(block):
    return bool(re.search(r"(?m)^[^\n]+[|}{oO-]+[^\n]+:", block))


def confirmed_database_tables(text):
    names = []
    names.extend(table_group_members(text))
    for match in re.finditer(r"(?m)^####\s+4\.2\.\d+\s+(.+)$", text):
        names.extend(extract_table_names(match.group(1)))
    for match in re.finditer(r"(?m)^\|\s*设计对象\s*\|\s*(.+?)\|", text):
        names.extend(extract_table_names(match.group(1)))
    names.extend(create_table_names(text))
    deduped = []
    for name in names:
        normalized = normalize_table_name(name)
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def normalized_nonempty_lines(text):
    return {re.sub(r"\s+", " ", line.strip()) for line in text.splitlines() if line.strip()}


def protected_template_lines(text):
    protected = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "{" in line or "YYYY-MM-DD" in line:
            continue
        if line.startswith((">", "##", "###", "####", "**", "- ")) or line in {"强耦合表组模式标题规则：", "文档结束"}:
            protected.append(re.sub(r"\s+", " ", line))
    return protected


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
    if status in {"unknown", "proposed", "assumed", "todo", "pending", "pending_confirmation", "unconfirmed", "missing"}:
        return False
    evidence_fields = [
        "repo_context", "repo_context_ref", "code_path", "source_path", "module_path", "service_registry_ref",
        "evidence", "evidence_refs", "source_artifacts", "owner_module", "pom", "build_file",
    ]
    if any(item.get(field) for field in evidence_fields):
        return True
    return status in {"confirmed", "matched", "verified", "existing"}


def message_schema_entries(data):
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    if any(field in data for field in ["issueId", "configType", "properties"]):
        return [data]
    for key in POLICY.get("message_schema_entry_collection_keys", []):
        raw = data.get(key)
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, dict):
            entries = []
            for config_type, value in raw.items():
                if isinstance(value, dict):
                    entry = dict(value)
                    entry.setdefault("configType", config_type)
                    entries.append(entry)
            if entries:
                return entries
    return []


def schema_properties(entry):
    if isinstance(entry, dict) and isinstance(entry.get("properties"), dict):
        return entry.get("properties") or {}
    return {}


def schema_required_fields(node):
    if isinstance(node, dict) and isinstance(node.get("required"), list):
        return {str(item) for item in node.get("required", []) if isinstance(item, str)}
    return set()


def schema_config_type(entry, root_properties):
    config_value = entry.get("configType") if isinstance(entry, dict) else None
    if isinstance(config_value, str) and config_value.strip():
        return config_value.strip()
    config_node = root_properties.get("configType") if isinstance(root_properties, dict) else None
    if isinstance(config_node, dict):
        for key in ["const", "default", "example"]:
            value = config_node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        enum_value = config_node.get("enum")
        if isinstance(enum_value, list) and len(enum_value) == 1 and isinstance(enum_value[0], str) and enum_value[0].strip():
            return enum_value[0].strip()
    return ""


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
    for mermaid_type in POLICY.get("forbidden_mermaid", []):
        if mermaid_blocks(text, mermaid_type):
            errors.append("high-level-design.md 不得包含 " + mermaid_type + "；概要设计只允许关键协作摘要和服务间时序图")
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
    if is_event_driven_design(text, POLICY["event_driven_terms"]):
        create_present = any(term in text for term in POLICY["create_event_terms"])
        state_present = any(term in text for term in POLICY["state_event_terms"])
        if not sequence_blocks:
            errors.append("MQ / 事件 / 异步消息场景至少必须包含一个 sequenceDiagram")
        if create_present and state_present and len(sequence_blocks) < 2:
            errors.append("同时包含创建类消息和状态变更/删除/失效类消息时，概要设计必须至少包含两个核心 sequenceDiagram")
        for block_index, block in enumerate(sequence_blocks, start=1):
            if not sequence_has_internal_processing(block, POLICY["internal_sequence_terms"], POLICY["internal_sequence_outcome_terms"]):
                errors.append(f"第 {block_index} 个事件驱动 sequenceDiagram 只有消息收发或缺少服务内部关键处理 self-call")
    evidence_entries = participant_evidence_entries(payload_path, payload)
    for block_index, block in enumerate(sequence_blocks, start=1):
        participants = service_sequence_participants(block)
        if not participants:
            errors.append(f"第 {block_index} 个 sequenceDiagram 必须显式声明 participant，且 participant 只能是服务")
        if participants and evidence_entries is None:
            errors.append("high-level-design.md sequenceDiagram participant 必须提供 participant-evidence-map.json，追溯到 repo_context/代码/服务注册证据: " + ", ".join(participants.keys()))
        for alias, label in participants.items():
            if has_abstract_participant_label(label, POLICY["abstract_participant_label_terms"]):
                errors.append(f"第 {block_index} 个 sequenceDiagram participant 是无证据抽象能力名，不得进入正式时序图: {label}")
            if not is_service_label(label, POLICY["service_sequence_forbidden_participants"]):
                errors.append(f"第 {block_index} 个 sequenceDiagram participant 不是服务: {label}")
            if evidence_entries is not None:
                evidence = evidence_entries.get(alias) or evidence_entries.get(label)
                if not evidence:
                    errors.append(f"第 {block_index} 个 sequenceDiagram participant 缺少 participant-evidence-map.json 证据: {alias}/{label}")
                elif not has_confirmed_participant_evidence(evidence):
                    errors.append(f"第 {block_index} 个 sequenceDiagram participant 证据状态为 unknown/proposed 或缺少 repo_context 证据: {alias}/{label}")
        for endpoint in service_sequence_endpoints(block):
            label = participants.get(endpoint, endpoint)
            if not is_service_label(label, POLICY["service_sequence_forbidden_participants"]):
                errors.append(f"第 {block_index} 个 sequenceDiagram 消息端点不是服务: {label}")
            elif evidence_entries is not None:
                evidence = evidence_entries.get(endpoint) or evidence_entries.get(label)
                if not evidence:
                    errors.append(f"第 {block_index} 个 sequenceDiagram 消息端点缺少 participant-evidence-map.json 证据: {endpoint}/{label}")
                elif not has_confirmed_participant_evidence(evidence):
                    errors.append(f"第 {block_index} 个 sequenceDiagram 消息端点证据状态为 unknown/proposed 或缺少 repo_context 证据: {endpoint}/{label}")
    return errors


payload_path = Path(sys.argv[1])
payload = load_payload(payload_path)
errors = validate_preflight_order(payload_path, payload)
if should_validate_formal_outputs(payload):
    errors.extend(validate_output(payload_path, payload))
fail(errors)
