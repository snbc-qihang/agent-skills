#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

SKILL_ID = "database-design"
POLICY = {
  "oltp_sections": [
    "1. 文档信息",
    "1.1 变更记录",
    "1.2 术语定义",
    "1.3 参考文档",
    "2. 文档定位",
    "2.1 编写目的",
    "2.2 设计对象类型",
    "2.3 与其他文档的关系",
    "2.4 强耦合表组说明（若适用）",
    "3. 业务语义与生命周期",
    "3.1 表的业务职责（业务角色）",
    "3.2 核心业务场景",
    "3.3 数据生命周期阶段",
    "3.4 状态机（若存在状态字段）",
    "4. 物理结构设计",
    "4.1 建表级环境与约定",
    "4.2 字段定义（按表展开）",
    "4.3 索引设计",
    "4.4 约束与数据库对象",
    "4.5 字段可变性矩阵",
    "4.6 技术实现依赖",
    "5. 数据量与性能设计",
    "5.1 数据量估算",
    "5.2 读写 QPS 与延迟 SLA",
    "5.3 热点与数据倾斜分析",
    "5.4 容量规划",
    "5.5 性能保障措施",
    "6. CRUD 契约设计（OLTP 核心）",
    "6.1 CRUD 总览矩阵",
    "6.2 强制前置条件（Mandatory Conditions）",
    "6.3 禁止操作清单（Prohibited Operations）",
    "6.4 Create",
    "6.5 Read",
    "6.6 Update",
    "6.7 Delete",
    "6.8 幂等键与重复请求",
    "6.9 批量操作与数据修复规则",
    "7. 事务、一致性与并发控制",
    "7.1 本地事务边界（单库）",
    "7.2 跨表一致性（表组内/跨库）",
    "7.3 并发控制",
    "7.4 数据质量校验",
    "7.5 隔离级别、死锁与重试约定",
    "7.6 跨表最终一致",
    "8. 分区、分片与归档设计",
    "8.1 路由与分片规则",
    "8.2 分区策略",
    "8.3 查询策略",
    "8.4 归档与保留",
    "8.5 冷热分离与只读副本",
    "9. 安全与审计设计",
    "9.1 敏感字段清单",
    "9.2 脱敏与掩码规则",
    "9.3 访问控制",
    "9.4 审计要求",
    "10. 测试与验收",
    "10.1 验收检查表",
    "10.2 测试用例类型",
    "10.3 样例 SQL",
    "11. 附录",
    "11.1 DDL SQL",
    "11.2 兼容性说明"
  ],
  "olap_sections": [
    "数据分层",
    "字段级血缘",
    "MergeTree 引擎选型",
    "ORDER BY",
    "PARTITION BY",
    "TTL",
    "物化视图关系",
    "刷新策略",
    "上下游影响"
  ],
  "oltp_table_headers": [
    "| 项目 | 内容 |",
    "| 版本 | 日期 | 变更原因/依据 | 变更摘要 | 变更人 | 评审/批准 |",
    "| 术语 | 说明 |",
    "| 文档名 | 关联类型 | 参考说明 |",
    "| 成员表 | 角色 | 与主表关系 | 同事务要求 | 备注 |",
    "| 场景 ID | 场景名称 | 触发入口 | 主要 SQL 形态 | 优先级 | 频率/峰值 |",
    "| 阶段 | 进入条件 | 允许的操作类型 | 对外可见性 | 数据留存策略 |",
    "| 当前状态",
    "| 字段 | 类型 | 必填 | 默认值 | 索引 | 敏感级别 | 说明 |",
    "| 表 | 索引名 | 类型 | 字段（顺序敏感） | 唯一 | 服务场景 | 备注 |",
    "| 类别 | 规则 | 实现方式 | 备注 |",
    "| 字段 | 创建时赋值 | 运行中可改 | 结束态可改 | 修改主体 | 约束/备注 |",
    "| 依赖项 | 版本/规格 | 本文档是否依赖 | 说明 |",
    "| 维度 | 估算值 | 说明 |",
    "| 场景 ID | 场景名称 | 操作类型 | QPS/TPS 目标 | P99 延迟目标 | 优先级 | 说明 |",
    "| 热点类型 | 表现 | 发生条件 | 缓解措施 |",
    "| 资源 | 估算方法 | 目标值 | 说明 |",
    "| 措施 | 适用场景 | 实施状态 | 说明 |",
    "| 操作 | 典型入口 | 参与表 | 定位键/幂等键 | 一致性边界 | 必备前置条件 | 允许字段/投影 | 明确禁止 | 并发控制 | 审计 |",
    "| 操作 | 编号 | 强制条件",
    "| 编号 | 禁止行为 | 适用范围 | 例外",
    "| 规则项 | 要求 |",
    "| 查询类型 | 必带条件 | 推荐索引 | 主库/只读 | 备注 |",
    "| 场景 | 前置条件 | 允许 SET 字段 | 禁止 SET 字段 | 并发 |",
    "| 操作 | 策略 | 前置条件 | 审批 |",
    "| 层级 | 机制 | 说明 |",
    "| 类型 | 允许条件 | 事务与批次 | 记录要求 |",
    "| 场景 ID | 参与表 | 一致性要求 | 提交/回滚策略 | 补偿/核对策略 |",
    "| 关系 | 参与表 | 策略 | 补偿/核对 |",
    "| 场景 | 策略 | 说明 |",
    "| 校验项 | 规则 | 频率 | 失败处理 |",
    "| 主题 | 约定 |",
    "| 步骤 | 动作 | 失败补偿 |",
    "| 分片键 |",
    "| 维度 | MySQL | PostgreSQL |",
    "| 场景 | 是否带路由/分区键 | 预期计划 | 禁止 |",
    "| 阶段 | 条件 | 目标存储 | 在线库策略 |",
    "| 数据类别 | 放置 | 查询入口 | 说明 |",
    "| 字段 | 级别 | 存储 | 应用展示 | 导出 |",
    "| 场景 | 规则 | 示例 |",
    "| 角色 | 读 | 写 | 说明 |",
    "| 事件 | 记录内容 | 保留期 |",
    "| 检查项 | 结果 | 备注 |",
    "| 类型 | 目的 | 示例 |",
    "| 主题 | 注意点 |"
  ],
  "oltp_template_markers": [
    "应写明：",
    "不应重复：",
    "编写要点：",
    "示例（请替换为真实业务）：",
    "方言差异提示：",
    "编写要求：",
    "契约含义：",
    "原则说明（可粘贴到评审）：",
    "读写分离：",
    "样例 SQL（MySQL 风格，可按项目替换）",
    "强耦合表组模式标题规则",
    "强耦合表组模式要求",
    "文档结束"
  ],
  "oltp_fact_fields": [
    "文档名称",
    "逻辑库/Schema",
    "物理库标识",
    "所属集群/实例",
    "设计对象",
    "数据库产品",
    "数据库版本",
    "编写日期",
    "编写人",
    "业务负责人",
    "DBA 负责人",
    "安全/合规接口人"
  ],
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
  "formal_outputs": [
    "database-design.md",
    "schema-change-plan.sql",
    "migration-plan.md",
    "rollback-plan.md",
    "database-risk-report.json"
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
    text = read_artifact(payload_path, payload, "database-design.md")
    if not text:
        return ["缺少 database-design.md artifact 或文件不可读"]
    sections = POLICY["olap_sections"] if any(term in text for term in ["ClickHouse", "MergeTree", "物化视图", "分析宽表"]) else POLICY["oltp_sections"]
    template_path = Path(__file__).parents[1] / "assets" / ("database-olap-template.md" if sections == POLICY["olap_sections"] else "database-oltp-template.md")
    template_text = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
    for section in sections:
        if section not in text:
            errors.append("database-design.md 缺少模板章节或字段: " + section)
    if sections == POLICY.get("oltp_sections"):
        normalized_lines = normalized_nonempty_lines(text)
        for protected in protected_template_lines(template_text):
            if protected not in normalized_lines:
                errors.append("database-design.md 不得改写模板固定说明: " + protected)
        section_positions = []
        for section in POLICY["oltp_sections"]:
            index = text.find(section)
            if index >= 0:
                section_positions.append(index)
        if section_positions != sorted(section_positions):
            errors.append("database-design.md OLTP 章节顺序必须与模板一致")
        for header in POLICY["oltp_table_headers"]:
            if header not in text:
                errors.append("database-design.md 缺少 OLTP 模板表格列头: " + header)
        for marker in POLICY["oltp_template_markers"]:
            if marker not in text:
                errors.append("database-design.md 缺少 OLTP 模板固定内容: " + marker)
        for field in POLICY["oltp_fact_fields"]:
            if field not in text:
                errors.append("database-design.md 文档信息缺少必填事实字段: " + field)
        for required_text in ["MC-", "PO-", "QPS", "P99", "DDL SQL", "兼容性说明", "敏感级别", "幂等"]:
            if required_text not in text:
                errors.append("database-design.md 缺少 OLTP 强制内容: " + required_text)
        design_value = design_object_value(text)
        member_tables = table_group_members(text)
        object_type = object_type_value(text)
        strong_group = "强耦合表组：" in design_value or "强耦合表组:" in design_value or len(member_tables) >= 2 or "表组 关系型（OLTP）详细设计" in "\n".join(text.splitlines()[:3])
        if "强耦合表组" in text and "2.4 强耦合表组说明" not in text:
            errors.append("database-design.md 包含强耦合表组但缺少 2.4 强耦合表组说明")
        if strong_group:
            if "表组 关系型（OLTP）详细设计" not in "\n".join(text.splitlines()[:5]):
                errors.append("强耦合表组模式下文档标题必须使用 <业务对象>表组 关系型（OLTP）详细设计")
            if not re.search(r"设计对象\s*\|\s*强耦合表组[：:]", text):
                errors.append("强耦合表组模式下 1. 文档信息的设计对象必须写成 强耦合表组：表1、表2、表3...")
            if len(member_tables) < 2:
                errors.append("强耦合表组模式下设计对象或 2.4 表组说明至少要列出两张成员表")
            if not any(term in object_type for term in ["主表", "明细", "规则", "参数", "大字段", "领取", "配置", "+"]):
                errors.append("强耦合表组模式下 2. 文档定位必须明确对象类型，例如 主表 + 明细表 + 规则表")
            required_group_header = "| 成员表 | 角色 | 与主表关系 | 同事务要求 | 备注 |"
            if required_group_header not in text:
                errors.append("2.4 强耦合表组说明列头必须固定为: " + required_group_header)
            responsibility = section_text(text, "3.1 表的业务职责")
            if "唯一事实来源" not in responsibility:
                errors.append("3.1 表的业务职责必须按表列出唯一事实来源")
            for table in member_tables:
                if table not in responsibility:
                    errors.append("3.1 表的业务职责缺少成员表: " + table)
            if "4.2 字段定义（按表展开）" not in text:
                errors.append("强耦合表组模式下 4.2 必须命名为 字段定义（按表展开）")
            field_section = section_text(text, "4.2 字段定义（按表展开）")
            if not re.search(r"(?m)^####\s+4\.2\.\d+\s+", field_section):
                errors.append("多表场景下 4.2 字段定义必须逐表建立 #### 4.2.x 表名 子章节")
            required_field_header = "| 字段 | 类型 | 必填 | 默认值 | 索引 | 敏感级别 | 说明 |"
            if required_field_header not in field_section:
                errors.append("每张表字段表列头必须包含: " + required_field_header)
            for table in member_tables:
                if not re.search(r"(?m)^####\s+4\.2\.\d+\s+" + re.escape(table) + r"\b", field_section):
                    errors.append("4.2 字段定义缺少成员表子章节: " + table)
            required_index_header = "| 表 | 索引名 | 类型 | 字段（顺序敏感） | 唯一 | 服务场景 | 备注 |"
            if required_index_header not in text:
                errors.append("4.3 索引设计列头必须固定为: " + required_index_header)
            index_rows = markdown_index_rows(text)
            indexed_tables = {row["table"] for row in index_rows if row.get("table")}
            for table in member_tables:
                if table not in indexed_tables:
                    errors.append("4.3 索引设计缺少成员表索引归属: " + table)
            crud_section = section_text(text, "6.1 CRUD 总览矩阵")
            if "参与表" not in crud_section:
                errors.append("CRUD 总览矩阵必须包含 参与表")
            if not any(term in crud_section for term in ["同事务", "最终一致", "一致性边界"]):
                errors.append("CRUD 总览矩阵必须描述跨表同事务或最终一致性边界")
            transaction_section = section_text(text, "7. 事务、一致性与并发控制", r"^##\s+\d+\.\s+")
            for required in ["参与表", "提交/回滚", "补偿/核对"]:
                if required not in transaction_section:
                    errors.append("事务、一致性与并发控制缺少表组口径: " + required)
            for table in member_tables:
                if table not in transaction_section:
                    errors.append("事务、一致性与并发控制缺少成员表: " + table)
            schema_sql = read_artifact(payload_path, payload, "schema-change-plan.sql")
            if not schema_sql:
                errors.append("强耦合表组模式下缺少 schema-change-plan.sql artifact 或文件不可读")
            else:
                ddl_tables = create_table_names(schema_sql)
                if len(ddl_tables) < len(member_tables):
                    errors.append("设计对象列出多张表，但 schema-change-plan.sql 的 CREATE TABLE 数量少于设计对象表数量")
                for table in member_tables:
                    if table not in ddl_tables:
                        errors.append("schema-change-plan.sql 缺少成员表 CREATE TABLE: " + table)
                for row in index_rows:
                    table = row.get("table", "")
                    index_name = row.get("name", "")
                    if table in member_tables and index_name and index_name not in {"不适用", "无"}:
                        ddl_indexes = ddl_index_names(schema_sql, table)
                        if index_name not in ddl_indexes:
                            errors.append(f"schema-change-plan.sql 中 {table} 缺少与索引设计一致的索引: {index_name}")
            migration = read_artifact(payload_path, payload, "migration-plan.md")
            for required in ["表组同批创建", "同批校验", "逐表索引 explain", "表组关系校验"]:
                if required not in migration:
                    errors.append("migration-plan.md 缺少表组口径: " + required)
            rollback = read_artifact(payload_path, payload, "rollback-plan.md")
            if not (("不得只删除" in rollback or "不得只回滚" in rollback) and "孤立" in rollback):
                errors.append("rollback-plan.md 必须说明应用发布后不得只删除或回滚表组中的单张事实表，避免孤立配置、孤立明细或主明细不一致")
            risk_report = read_artifact(payload_path, payload, "database-risk-report.json")
            for required in ["生产 DDL 审批", "表组同批创建审批", "容量", "QPS", "枚举口径", "幂等键口径"]:
                if required not in risk_report:
                    errors.append("database-risk-report.json 缺少表组风险: " + required)
    for block in re.findall(r"```sql\s*\n([\s\S]*?)```", text):
        for match in re.finditer(r"(?ims)^\s*(update|delete)\b([\s\S]*?);", block):
            if "where" not in match.group(2).lower():
                errors.append("禁止没有 WHERE 的 UPDATE/DELETE")
    unresolved = [marker for marker in POLICY.get("unresolved_markers", []) if marker in text]
    if unresolved and payload.get("status") not in {"waiting_for_input", "waiting_for_human_review", "blocked"}:
        errors.append("存在未确认信息时必须 waiting_for_input，禁止推测或以占位符输出 succeeded: " + ", ".join(sorted(set(unresolved))))
    if payload.get("status") == "waiting_for_input" and not payload.get("required_information_requests"):
        errors.append("waiting_for_input 必须输出 required_information_requests 主动询问用户")
    final_status = payload.get("document_metadata", {}).get("document_status")
    if final_status in {"approved", "final"}:
        for required in ["库名", "实例", "字符集", "索引名"]:
            if required + "：" not in text and required + ":" not in text:
                errors.append("approved/final 文档必须确认" + required)
    if payload.get("status") == "succeeded" and any(term in text for term in ["CREATE TABLE", "ALTER TABLE", "DROP TABLE", "DDL"]):
        errors.append("包含 DDL 时必须 waiting_for_human_review")
    return errors


payload_path = Path(sys.argv[1])
payload = load_payload(payload_path)
errors = validate_preflight_order(payload_path, payload)
if should_validate_formal_outputs(payload):
    errors.extend(validate_output(payload_path, payload))
fail(errors)
