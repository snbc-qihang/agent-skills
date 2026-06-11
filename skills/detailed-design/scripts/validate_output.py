#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

SKILL_ID = "detailed-design"
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
      "失败终态",
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
  "source_traceability_header": "| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |",
  "mq_db_redis_required_terms": {
    "Redis / 缓存 / 状态处理记录 / 幂等记录": [
      "Redis",
      "缓存",
      "状态处理记录",
      "幂等记录"
    ],
    "幂等": [
      "幂等"
    ],
    "DB / 数据库 / 主表 / 明细": [
      "DB",
      "数据库",
      "主表",
      "明细"
    ],
    "事务": [
      "事务"
    ],
    "回滚": [
      "回滚"
    ],
    "重试": [
      "重试"
    ],
    "死信": [
      "死信"
    ],
    "人工处理": [
      "人工处理"
    ],
    "外部详情查询或事实服务查询": [
      "外部详情查询",
      "事实服务查询",
      "查询当前详情",
      "查询事实详情"
    ]
  },
  "formal_outputs": [
    "detailed-design.md",
    "implementation-plan.md",
    "interface-contracts.yaml",
    "test-strategy.md",
    "database-design.md",
    "mq-design.xlsx",
    "redis-design.md"
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
    field_aliases = {
        "异常编码": ["异常编码", "返回编码"],
        "日志/告警": ["日志/告警", "日志要求", "告警"],
        "补偿/重试/人工处理": ["补偿/重试/人工处理", "补偿", "重试", "人工处理"],
    }
    for index, block in enumerate(flow_blocks, start=1):
        tail = text[block.end(): block.end() + 1200]
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
        local_headers = []
        for line in tail.splitlines():
            cells = table_cells(line)
            if cells and not is_separator_row(line) and "场景" in cells and "触发条件" in cells:
                local_headers.append(cells)
        if not local_headers:
            errors.append(f"第 {index} 个 flowchart 后缺少异常场景表")
            continue
        best_header = max(local_headers, key=len)
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
    if is_mq_db_redis_flow(text):
        for label, terms in POLICY["mq_db_redis_required_terms"].items():
            if not any(term in text for term in terms):
                errors.append("MQ + DB + Redis 详细设计关键执行路径缺少: " + label)
    if is_local_read_model_write(text) and not all(any(term in text for term in group) for group in [["主表"], ["明细"], ["事务"]]):
        errors.append("本地读模型写入流程必须明确主表写入或更新、明细表写入/更新/重建和主明细事务关系")
    if is_local_read_model_delete(text) and not all(any(term in text for term in group) for group in [["状态处理记录"], ["先删明细", "明细删除"], ["再删主表", "主表删除"], ["删除失败", "回滚", "重试", "死信"]]):
        errors.append("本地读模型删除流程必须明确状态处理记录、明细删除、主表删除、删除顺序和失败处理")
    if is_query_or_export_flow(text) and not all(any(term in text for term in group) for group in [["登录态", "数据范围"], ["可见范围"], ["参数校验"], ["DB 查询", "数据库查询", "分批导出"], ["导出上限"], ["文件生成失败", "生成失败"]]):
        errors.append("查询 / 导出流程必须明确登录态或数据范围、可见范围合并、参数校验、DB 查询/分批导出、导出上限和文件生成失败处理")
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
errors = validate_preflight_order(payload_path, payload)
if should_validate_formal_outputs(payload):
    errors.extend(validate_output(payload_path, payload))
fail(errors)
