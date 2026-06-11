#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

SKILL_ID = "redis-design"
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
    "历史版本信息",
    "1. 前言",
    "1.1. 目的",
    "1.2. 适用范围",
    "1.3. 参考资料",
    "2. 公共配置",
    "2.1. Redis版本",
    "2.2. 集群配置",
    "2.3. 持久化策略",
    "2.4. 过期淘汰策略",
    "3. 设计项",
    "3.1. <设计项名称>",
    "3.1.1. 特性用途",
    "3.1.2. 业务说明",
    "3.1.3. 存储设计",
    "3.1.4. 预估数据",
    "3.1.5. 多团队协同",
    "4. 安全与运维",
    "4.1. 资源申请",
    "4.2. 运维监控"
  ],
  "item_fields": [
    "特性用途",
    "业务说明",
    "存储设计",
    "预估数据",
    "多团队协同"
  ],
  "storage_fields": [
    "库",
    "数据结构",
    "ttl",
    "key",
    "数据格式"
  ],
  "forbidden_formal_terms": [
    "终态水位",
    "水位"
  ],
  "business_terms": [
    "状态处理记录",
    "已处理状态记录",
    "消息幂等记录",
    "短期处理记录",
    "乱序保护记录"
  ],
  "formal_outputs": [
    "redis-design.md",
    "redis-key-registry.yaml",
    "cache-consistency-plan.md",
    "redis-risk-report.json"
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
    text = read_artifact(payload_path, payload, "redis-design.md")
    if not text:
        return ["缺少 redis-design.md artifact 或文件不可读"]
    for section in POLICY["required_sections"] + POLICY["item_fields"]:
        if section not in text:
            errors.append("redis-design.md 缺少模板章节或字段: " + section)
    for field in POLICY["storage_fields"]:
        if field not in text:
            errors.append("redis-design.md 存储设计缺少字段: " + field)
    for term in POLICY["forbidden_formal_terms"]:
        if term in text:
            errors.append("Redis 设计不得使用“" + term + "”作为正式术语，应改为状态处理记录 / 消息幂等记录 / 乱序保护记录等业务可理解术语")
    if any(term in text for term in ["乱序", "幂等", "状态处理", "过程信息"]):
        if not any(term in text for term in POLICY["business_terms"]):
            errors.append("Redis 设计涉及乱序/幂等/状态处理时必须使用状态处理记录、消息幂等记录或乱序保护记录等显式业务术语")
    if re.search(r"Redis\s*(作为|做|充当).{0,18}(事实库|事实源|共享事实源|长期审计库|审计库)", text):
        errors.append("Redis 不得作为事实库、跨服务共享事实源或长期审计库")
    if re.search(r"Redis\s*(作为|做|充当).{0,12}消息队列", text):
        errors.append("Redis 不得作为消息队列")
    if not re.search(r"TTL[^\n]*(秒|分钟|小时|天|ms|s|min|hour|day)", text, re.IGNORECASE):
        errors.append("TTL 必须带单位")
    if "降级" not in text and "不可用" not in text:
        errors.append("Redis 不可用必须有降级策略")
    if "不可用" in text or "降级" in text:
        if re.search(r"Redis.{0,10}不可用[\s\S]{0,80}(继续|直接|绕过)[\s\S]{0,40}(写库|写 DB|落库|删除|删 DB)", text):
            errors.append("Redis 不可用时不得绕过幂等 / 状态处理记录直接写 DB 或删除 DB")
        for required in ["重试", "死信", "告警", "人工回放"]:
            if required not in text:
                errors.append("Redis 不可用策略缺少: " + required)
    if payload.get("status") == "succeeded" and any(term in text for term in ["版本待确认", "拓扑待确认", "持久化待确认", "淘汰策略待确认"]):
        errors.append("Redis 版本、拓扑、持久化或淘汰策略无法确认时不得 succeeded")
    if payload.get("status") == "succeeded" and any(term in text for term in ["Redis 新 Key", "新增 Key", "新 Key"]):
        errors.append("Redis 新 Key 必须 waiting_for_human_review")
    return errors


payload_path = Path(sys.argv[1])
payload = load_payload(payload_path)
errors = validate_preflight_order(payload_path, payload)
if should_validate_formal_outputs(payload):
    errors.extend(validate_output(payload_path, payload))
fail(errors)
