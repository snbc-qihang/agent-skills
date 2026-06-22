#!/usr/bin/env python3
"""Regression checks for team detailed-design document rules."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def write_inline_string_cell(sheet_xml: Path, cell_ref: str, value: str) -> None:
    ET.register_namespace("", XLSX_NS)
    root = ET.fromstring(sheet_xml.read_bytes())
    row_number = "".join(ch for ch in cell_ref if ch.isdigit())
    row = root.find(f".//{{{XLSX_NS}}}row[@r='{row_number}']")
    if row is None:
        sheet_data = root.find(f".//{{{XLSX_NS}}}sheetData")
        row = ET.SubElement(sheet_data, f"{{{XLSX_NS}}}row", {"r": row_number})
    cell = root.find(f".//{{{XLSX_NS}}}c[@r='{cell_ref}']")
    if cell is None:
        cell = ET.SubElement(row, f"{{{XLSX_NS}}}c", {"r": cell_ref})
    cell.set("t", "inlineStr")
    for child in list(cell):
        cell.remove(child)
    inline = ET.SubElement(cell, f"{{{XLSX_NS}}}is")
    text = ET.SubElement(inline, f"{{{XLSX_NS}}}t")
    text.text = value
    sheet_xml.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def _sheet_name_to_path(temp: Path) -> dict[str, Path]:
    ns = {
        "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    rels_root = ET.fromstring((temp / "xl" / "_rels" / "workbook.xml.rels").read_bytes())
    rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_root.findall("pkg:Relationship", ns)}
    workbook_root = ET.fromstring((temp / "xl" / "workbook.xml").read_bytes())
    mapping = {}
    for sheet in workbook_root.findall(".//a:sheet", ns):
        name = sheet.attrib.get("name", "")
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
        target = rels.get(rel_id, "").lstrip("/")
        if target.startswith("xl/"):
            mapping[name] = temp / target
        else:
            mapping[name] = temp / "xl" / target
    return mapping


def _write_xlsx_row_by_headers(target: Path, sheet_name: str, row_number: int, values: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        with zipfile.ZipFile(target) as src:
            src.extractall(temp)
        sheet_paths = _sheet_name_to_path(temp)
        sheet_xml = sheet_paths[sheet_name]
        root = ET.fromstring(sheet_xml.read_bytes())
        row = root.find(f".//{{{XLSX_NS}}}row[@r='1']")
        if row is None:
            raise AssertionError(f"sheet {sheet_name} missing header row")
        header_to_col = {}
        for cell in row.findall(f"{{{XLSX_NS}}}c"):
            ref = cell.attrib.get("r", "")
            col_letters = "".join(ch for ch in ref if ch.isalpha())
            text = ""
            if cell.attrib.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in cell.findall(f".//{{{XLSX_NS}}}t"))
            else:
                node = cell.find(f"{{{XLSX_NS}}}v")
                if node is not None and node.text:
                    # The template headers are stored as shared strings, but we only need stable refs used in the template.
                    # The current team template keeps header order fixed, so the known column letters are sufficient.
                    pass
            if text:
                header_to_col[text] = col_letters
        if not header_to_col:
            known_headers = {
                "消费者": {
                    "队列名称": "A",
                    "业务用途": "B",
                    "场景应用": "C",
                    "单消费节点消费": "D",
                    "队列类型": "E",
                    "优先队列": "F",
                    "是否持久化": "G",
                    "自动删除": "H",
                    "TTL": "I",
                    "消息大小": "J",
                    "绑定的Exchange/routingKey(多个）": "K",
                    "死信队列exchange/routeKey": "M",
                    "消费服务": "N",
                    "消息key": "O",
                    "运维监控": "P",
                    "软件需求号/bug号": "Q",
                    "设计日期": "R",
                    "设计者": "S",
                    "备注": "T",
                },
                "生产者": {
                    "业务用途": "A",
                    "场景应用": "B",
                    "业务消息key": "C",
                    "消息类型": "D",
                    "消息体内容": "E",
                    "优先等级": "F",
                    "消息TTL（毫秒）": "G",
                    "持久化": "H",
                    "目的交换机": "I",
                    "路由key": "J",
                    "消息预估大小": "K",
                    "生产服务/模块名称": "L",
                    "软件需求号/bug号": "M",
                    "设计日期": "N",
                    "设计者": "O",
                    "备注": "P",
                },
            }
            header_to_col = known_headers[sheet_name]
        for header, value in values.items():
            cell_ref = f"{header_to_col[header]}{row_number}"
            write_inline_string_cell(sheet_xml, cell_ref, value)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
            for file in temp.rglob("*"):
                if file.is_file():
                    dst.write(file, file.relative_to(temp).as_posix())


def rewrite_workbook_targets_absolute(target: Path) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        with zipfile.ZipFile(target) as src:
            src.extractall(temp)
        rels = temp / "xl" / "_rels" / "workbook.xml.rels"
        text = rels.read_text(encoding="utf-8")
        text = text.replace('Target="worksheets/', 'Target="/xl/worksheets/')
        rels.write_text(text, encoding="utf-8")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
            for file in temp.rglob("*"):
                if file.is_file():
                    dst.write(file, file.relative_to(temp).as_posix())


def make_mq_xlsx(target: Path, producer_values: dict[str, str] | None = None, consumer_values: dict[str, str] | None = None) -> None:
    shutil.copyfile(ROOT / "inputs" / "xxxMQ设计.xlsx", target)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        with zipfile.ZipFile(target) as src:
            src.extractall(temp)
        for cell_ref, value in (producer_values or {}).items():
            write_inline_string_cell(temp / "xl" / "worksheets" / "sheet2.xml", cell_ref, value)
        for cell_ref, value in (consumer_values or {}).items():
            write_inline_string_cell(temp / "xl" / "worksheets" / "sheet1.xml", cell_ref, value)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
            for file in temp.rglob("*"):
                if file.is_file():
                    dst.write(file, file.relative_to(temp).as_posix())


def run_validator(skill_id: str, payload_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(ROOT / "skills" / skill_id / "scripts" / "validate_output.py"), str(payload_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def payload(skill_id: str, artifacts: list[dict[str, str]], status: str = "succeeded", document_status: str = "draft") -> dict:
    preflight_state = {
        "succeeded": "ready",
        "waiting_for_input": "waiting_for_input",
        "waiting_for_human_review": "waiting_for_human_review",
        "blocked": "blocked",
        "failed": "blocked",
        "skipped": "blocked",
    }.get(status, "ready")
    return {
        "run_id": "run-team-doc-001",
        "skill_id": skill_id,
        "status": status,
        "preflight_input_state": preflight_state,
        "language": "zh-CN",
        "trace_id": "trace-team-doc-001",
        "document_metadata": {
            "document_number": "DDD-TEAM-20260526-001",
            "document_status": document_status,
            "retention_policy": "keep_until_run_end",
            "owner": "后端开发",
            "source_artifacts": [],
        },
        "artifacts": [
            {
                "name": item["name"],
                "path": item["path"],
                "artifact_type": item.get("artifact_type", "markdown"),
                "producer_skill": skill_id,
            }
            for item in artifacts
        ],
        "quality_gates": [],
        "findings": [],
        "required_human_reviews": [],
        "required_information_requests": [],
        "repair_summary": {"attempts": 0, "max_attempts": 0, "status": "not_needed"},
        "next_action": "complete",
    }


def write_mq_contract_artifacts(
    root: Path,
    *,
    config_type: str = "pendingOrderExportTask",
    body_fields: dict[str, str] | None = None,
    include_required: bool = True,
) -> list[dict[str, str]]:
    schema_path = root / "message-schema.json"
    topic_contract_path = root / "mq-topic-contract.yaml"
    required_fields = list((body_fields or {}).keys()) if body_fields else ["taskId", "taskType", "businessType", "eventTime"]
    properties = {field: {"type": "string"} for field in required_fields}
    body_node: dict[str, object] = {"type": "object", "properties": properties}
    if include_required:
        body_node["required"] = required_fields
    schema = {
        "type": "object",
        "required": ["issueId", "configType", config_type],
        "properties": {
            "issueId": {"type": "string"},
            "configType": {"type": "string", "const": config_type},
            config_type: body_node,
        },
    }
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    topic_contract_path.write_text(
        "\n".join(
            [
                "producer:",
                "  messageKey: pending.pay.order.created",
                f"  configType: {config_type}",
                "consumer:",
                "  queue: pending.pay.order.created.queue",
                "  messageKey: pending.pay.order.created",
                f"  configType: {config_type}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return [
        {"name": "message-schema.json", "path": str(schema_path), "artifact_type": "json"},
        {"name": "mq-topic-contract.yaml", "path": str(topic_contract_path), "artifact_type": "yaml"},
    ]


class TeamDocumentDesignRulesTest(unittest.TestCase):
    def test_high_level_design_contract_exposes_team_template_policy(self) -> None:
        contract = json.loads((ROOT / "skills" / "high-level-design" / "contract.yaml").read_text(encoding="utf-8"))
        policy = contract["team_document_policy"]

        self.assertEqual("skills/high-level-design/assets/high-level-design-template.md", policy["canonical_template"])
        template_policy = policy["template_usage_policy"]
        self.assertTrue(template_policy["must_read_template_before_generation"])
        self.assertIn("skills/high-level-design/assets/high-level-design-template.md", json.dumps(template_policy, ensure_ascii=False))
        self.assertIn("不得凭记忆", "\n".join(template_policy["generation_protocol"]))
        self.assertIn("flowchart", policy["forbidden_mermaid"])
        for section in ["1. 版本变更记录", "2. 平台概述", "3. 系统设计", "4.1.2 关键协作摘要", "5.中间件设计", "6.数据视图"]:
            self.assertIn(section, policy["required_sections"])

        skill_md = (ROOT / "skills" / "high-level-design" / "SKILL.md").read_text(encoding="utf-8")
        for text in ["模板执行协议", "团队概要设计模板规则", "high-level-design-template.md", "先读取", "不得删除", "系统逻辑视图", "数据视图"]:
            self.assertIn(text, skill_md)

    def test_detailed_design_contract_exposes_team_document_policy(self) -> None:
        contract = json.loads((ROOT / "skills" / "detailed-design" / "contract.yaml").read_text(encoding="utf-8"))
        policy = contract["team_document_policy"]
        template_policy = policy["main_document"]["template_usage_policy"]

        self.assertTrue(template_policy["must_read_template_before_generation"])
        self.assertIn("skills/detailed-design/assets/detailed-design-template.md", json.dumps(template_policy, ensure_ascii=False))
        self.assertIn("不得把团队 template 压缩成摘要", json.dumps(template_policy, ensure_ascii=False))
        self.assertIn("来源证据", policy["main_document"]["forbidden_headings"])
        self.assertIn("sequenceDiagram", policy["main_document"]["forbidden_mermaid"])
        self.assertIn("flowchart", policy["main_document"]["required_mermaid"])
        self.assertIn("classDiagram", json.dumps(policy, ensure_ascii=False))
        self.assertIn("1. 修订历史", policy["main_document"]["allowed_sections"])
        self.assertIn("5.2. 中间件设计", policy["main_document"]["allowed_sections"])
        self.assertIn("database-design.md", policy["stage_result"]["must_register_specialty_artifacts"])
        self.assertIn("Redis 新 Key", policy["stage_result"]["waiting_for_human_review_when"])

        skill_md = (ROOT / "skills" / "detailed-design" / "SKILL.md").read_text(encoding="utf-8")
        for text in ["模板执行协议", "detailed-design-template.md", "先读取", "章节顺序", "sequenceDiagram", "流程设计说明", "classDiagram", "waiting_for_human_review"]:
            self.assertIn(text, skill_md)

    def test_template_execution_policy_is_exposed_by_all_template_skills(self) -> None:
        expected_templates = {
            "high-level-design": ["assets/high-level-design-template.md"],
            "detailed-design": ["assets/detailed-design-template.md"],
            "database-design": ["assets/database-oltp-template.md", "assets/database-olap-template.md"],
            "redis-design": ["assets/redis-design-template.md"],
            "mq-design": ["assets/mq-design-template.xlsx"],
        }

        for skill_id, template_paths in expected_templates.items():
            contract = json.loads((ROOT / "skills" / skill_id / "contract.yaml").read_text(encoding="utf-8"))
            policy = contract["team_document_policy"]
            template_policy = policy.get("template_usage_policy") or policy["main_document"]["template_usage_policy"]
            self.assertTrue(template_policy["required"], skill_id)
            self.assertTrue(template_policy["must_read_template_before_generation"], skill_id)
            protocol_text = "\n".join(template_policy["generation_protocol"])
            self.assertIn("先读取", protocol_text, skill_id)
            self.assertIn("不得删除", protocol_text, skill_id)
            self.assertIn("waiting_for_input", protocol_text, skill_id)

            skill_md = (ROOT / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8")
            agent_meta = (ROOT / "skills" / skill_id / "agents" / "openai.yaml").read_text(encoding="utf-8")
            self.assertIn("模板执行协议", skill_md, skill_id)
            if skill_id == "mq-design":
                self.assertIn("先读取对应 xlsx template", agent_meta, skill_id)
            else:
                self.assertIn("先读取对应 assets template", agent_meta, skill_id)
            for template_path in template_paths:
                self.assertIn(template_path, json.dumps(template_policy, ensure_ascii=False), skill_id)
                self.assertIn(template_path, skill_md, skill_id)

    def test_team_templates_are_generated(self) -> None:
        expected = [
            ROOT / "skills" / "high-level-design" / "assets" / "high-level-design-template.md",
            ROOT / "skills" / "detailed-design" / "assets" / "detailed-design-template.md",
            ROOT / "skills" / "database-design" / "assets" / "database-oltp-template.md",
            ROOT / "skills" / "database-design" / "assets" / "database-olap-template.md",
            ROOT / "skills" / "redis-design" / "assets" / "redis-design-template.md",
            ROOT / "skills" / "mq-design" / "assets" / "mq-design-template.xlsx",
        ]
        for path in expected:
            self.assertTrue(path.exists(), f"missing template: {path}")

        hld_template = expected[0].read_text(encoding="utf-8")
        for text in ["0. 原始需求与原型追溯", "source_id", "1. 版本变更记录", "2. 平台概述", "3.1 系统逻辑视图", "4.1.2 关键协作摘要", "4.1.3 跨服务服务间时序图", "sequenceDiagram", "5.中间件设计", "6.数据视图"]:
            self.assertIn(text, hld_template)
        self.assertNotIn("flowchart TD", hld_template)
        self.assertNotIn("## 证据", hld_template)
        self.assertNotIn("## Findings", hld_template)

        detailed_template = expected[1].read_text(encoding="utf-8")
        for text in ["1. 修订历史", "2. 设计背景与目标摘要", "2.1 原始需求与原型引用矩阵", "source_id", "3.1. 业务流程图", "3.2. UML类图", "4. 数据库设计", "5.2. 中间件设计", "6. 单元测试"]:
            self.assertIn(text, detailed_template)
        self.assertIn("flowchart TD", detailed_template)
        self.assertIn("classDiagram", detailed_template)
        self.assertNotIn("## 来源证据", detailed_template)
        self.assertNotIn("## 发布", detailed_template)

        oltp_template = (ROOT / "skills" / "database-design" / "assets" / "database-oltp-template.md").read_text(encoding="utf-8")
        required_order = [
            "## 1. 文档信息",
            "### 1.1 变更记录",
            "### 1.2 术语定义",
            "### 1.3 参考文档",
            "## 2. 文档定位",
            "## 3. 业务语义与生命周期",
            "## 4. 物理结构设计",
            "## 5. 数据量与性能设计",
            "## 6. CRUD 契约设计",
            "## 7. 事务、一致性与并发控制",
            "## 8. 分区、分片与归档设计",
            "## 9. 安全与审计设计",
            "## 10. 测试与验收",
            "## 11. 附录",
        ]
        positions = [oltp_template.index(item) for item in required_order]
        self.assertEqual(sorted(positions), positions)
        for table_header in [
            "| 项目 | 内容 |",
            "| 成员表 | 角色 | 与主表关系 | 同事务要求 | 备注 |",
            "| 字段 | 类型 | 必填 | 默认值 | 索引 | 敏感级别 | 说明 |",
            "| 表 | 索引名 | 类型 | 字段（顺序敏感） | 唯一 | 服务场景 | 备注 |",
            "| 操作 | 典型入口 | 参与表 | 定位键/幂等键 | 一致性边界 | 必备前置条件 | 允许字段/投影 | 明确禁止 | 并发控制 | 审计 |",
            "| 场景 ID | 参与表 | 一致性要求 | 提交/回滚策略 | 补偿/核对策略 |",
            "| 编号 | 禁止行为 | 适用范围 | 例外（须工单+审批） |",
            "| 检查项 | 结果 | 备注 |",
        ]:
            self.assertIn(table_header, oltp_template)
        self.assertIn("### 4.2 字段定义（按表展开）", oltp_template)
        self.assertIn("#### 4.2.1 `{table}`", oltp_template)
        for text in [
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
            "文档结束",
        ]:
            self.assertIn(text, oltp_template)
        source_template = (ROOT / "inputs" / "关系型(OLTP)详细设计模板.md").read_text(encoding="utf-8")
        for text in [
            "## 1. 文档信息",
            "### 3.2 核心业务场景",
            "### 5.5 性能保障措施",
            "### 8.5 冷热分离与只读副本",
            "### 10.3 样例 SQL（MySQL 风格，可按项目替换）",
        ]:
            self.assertIn(text, source_template)
            self.assertIn(text, oltp_template)

    def test_extra_team_eval_cases_are_generated_and_checked_by_runner(self) -> None:
        hld_case = ROOT / "skills" / "high-level-design" / "evals" / "team_high_level_template_required.yaml"
        self.assertTrue(hld_case.exists())
        hld_data = json.loads(hld_case.read_text(encoding="utf-8"))
        self.assertEqual("team_high_level_template_required", hld_data["case_type"])
        self.assertIn("high-level-design.md", "\n".join(hld_data["pass_criteria"]))
        hld_sequence_case = ROOT / "skills" / "high-level-design" / "evals" / "team_high_level_service_sequence_traceability.yaml"
        self.assertTrue(hld_sequence_case.exists())
        hld_sequence_data = json.loads(hld_sequence_case.read_text(encoding="utf-8"))
        self.assertIn("sequenceDiagram", "\n".join(hld_sequence_data["pass_criteria"]))
        self.assertIn("source_id", "\n".join(hld_sequence_data["pass_criteria"]))
        hld_boundary_case = ROOT / "skills" / "high-level-design" / "evals" / "team_high_level_no_detailed_implementation_content.yaml"
        self.assertTrue(hld_boundary_case.exists())
        hld_boundary_data = json.loads(hld_boundary_case.read_text(encoding="utf-8"))
        self.assertEqual("team_high_level_no_detailed_implementation_content", hld_boundary_data["case_type"])
        self.assertIn("SQL/DDL", "\n".join(hld_boundary_data["pass_criteria"]))

        expected_cases = [
            "team_db_reference_only",
            "team_mq_template_reference_only",
            "team_redis_template_reference_only",
            "team_flowchart_not_sequence",
            "team_flowchart_exception_branches_required",
            "team_rules_under_flow",
            "team_ddd_requires_uml",
            "team_no_release_gray_sections",
        ]
        for case in expected_cases:
            path = ROOT / "skills" / "detailed-design" / "evals" / f"{case}.yaml"
            self.assertTrue(path.exists(), f"missing eval case: {case}")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(case, data["case_type"])
            self.assertIn("detailed-design.md", "\n".join(data["pass_criteria"]))

        runner = (ROOT / "engineering-assistant" / "scripts" / "run_skill_evals.py").read_text(encoding="utf-8")
        self.assertIn('glob("*.yaml")', runner)
        self.assertIn("StageRunResult.artifacts", runner)

        for case in ["team_database_open_door_event_table_group", "team_database_member_private_domain_table_group"]:
            path = ROOT / "skills" / "database-design" / "evals" / f"{case}.yaml"
            self.assertTrue(path.exists(), f"missing eval case: {case}")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(case, data["case_type"])
            criteria = "\n".join(data["pass_criteria"])
            self.assertIn("强耦合表组模式", criteria)
            self.assertIn("schema-change-plan.sql", criteria)

        code_case = ROOT / "skills" / "code-development" / "evals" / "team_code_source_design_traceability.yaml"
        self.assertTrue(code_case.exists())
        code_data = json.loads(code_case.read_text(encoding="utf-8"))
        self.assertIn("source_id", "\n".join(code_data["pass_criteria"]))
        self.assertIn("traceability-matrix.json", "\n".join(code_data["pass_criteria"]))

    def test_specialty_validators_only_contain_current_skill_rules(self) -> None:
        scripts = {
            "database-design": (ROOT / "skills" / "database-design" / "scripts" / "validate_output.py").read_text(encoding="utf-8"),
            "redis-design": (ROOT / "skills" / "redis-design" / "scripts" / "validate_output.py").read_text(encoding="utf-8"),
            "mq-design": (ROOT / "skills" / "mq-design" / "scripts" / "validate_output.py").read_text(encoding="utf-8"),
        }

        self.assertIn('SKILL_ID = "database-design"', scripts["database-design"])
        self.assertIn('SKILL_ID = "redis-design"', scripts["redis-design"])
        self.assertIn('SKILL_ID = "mq-design"', scripts["mq-design"])

        forbidden_by_skill = {
            "database-design": ["redis-design.md", "mq-design.xlsx", "detailed-design.md", "validate_redis", "validate_mq", "validate_detailed"],
            "redis-design": ["database-design.md", "mq-design.xlsx", "detailed-design.md", "validate_database", "validate_mq", "validate_detailed"],
            "mq-design": ["database-design.md", "redis-design.md", "detailed-design.md", "validate_database", "validate_redis", "validate_detailed"],
        }
        for skill_id, forbidden_items in forbidden_by_skill.items():
            for forbidden in forbidden_items:
                self.assertNotIn(forbidden, scripts[skill_id], f"{skill_id} validator leaked {forbidden}")
            self.assertIn("def validate_output", scripts[skill_id])
            self.assertIn("should_validate_formal_outputs(payload)", scripts[skill_id])
            self.assertIn("errors.extend(validate_output(payload_path, payload))", scripts[skill_id])

    def test_workflow_orchestrator_contract_requires_validator_summary(self) -> None:
        contract = json.loads((ROOT / "skills" / "workflow-orchestrator" / "contract.yaml").read_text(encoding="utf-8"))
        outputs = {item["name"] for item in contract["outputs"]}
        self.assertIn("validator-summary.json", outputs)
        skill_md = (ROOT / "skills" / "workflow-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("defect-analysis", skill_md)
        self.assertIn("validator-summary.json", skill_md)

    def test_workflow_orchestrator_validator_blocks_when_specialty_validator_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            validator_summary = root / "validator-summary.json"
            validator_summary.write_text(
                json.dumps(
                    {
                        "validators": [
                            {"skill_id": "high-level-design", "status": "passed", "exit_code": 0},
                            {"skill_id": "database-design", "status": "failed", "exit_code": 1, "errors": ["缺少模板章节"]},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result_payload = payload(
                "workflow-orchestrator",
                [
                    {"name": "workflow-trace.json", "path": str(root / "workflow-trace.json"), "artifact_type": "json"},
                    {"name": "workflow-summary.md", "path": str(root / "workflow-summary.md")},
                    {"name": "approval-requests.json", "path": str(root / "approval-requests.json"), "artifact_type": "json"},
                    {"name": "artifact-index.json", "path": str(root / "artifact-index.json"), "artifact_type": "json"},
                    {"name": "validator-summary.json", "path": str(validator_summary), "artifact_type": "json"},
                ],
                status="succeeded",
            )
            payload_path = root / "workflow-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("workflow-orchestrator", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("专项 validator 失败", output)
        self.assertIn("database-design", output)
        self.assertIn("blocked", output)

    def test_workflow_orchestrator_validator_requires_defect_analysis_for_quality_defects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary = root / "workflow-summary.md"
            summary.write_text("用户指出概要设计脱离代码实际，数据库模板裁剪。", encoding="utf-8")
            result_payload = payload(
                "workflow-orchestrator",
                [
                    {"name": "workflow-summary.md", "path": str(summary)},
                    {"name": "workflow-trace.json", "path": str(root / "workflow-trace.json"), "artifact_type": "json"},
                    {"name": "approval-requests.json", "path": str(root / "approval-requests.json"), "artifact_type": "json"},
                    {"name": "artifact-index.json", "path": str(root / "artifact-index.json"), "artifact_type": "json"},
                ],
                status="succeeded",
            )
            result_payload["findings"] = [{"summary": "用户指出产物质量问题：脱离代码实际、模板裁剪"}]
            payload_path = root / "workflow-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("workflow-orchestrator", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("defect-analysis", output)
        self.assertIn("root_cause", output)

    def test_waiting_for_input_skips_formal_output_validation_until_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result_payload = payload("detailed-design", [], status="waiting_for_input")
            result_payload["required_information_requests"] = [
                {
                    "id": "REQ-INFO-001",
                    "blocking": True,
                    "questions": [
                        {
                            "id": "Q1",
                            "question": "请补充业务边界。",
                            "reason": "缺少边界不能生成正式详细设计。",
                            "required": True,
                            "priority": "critical",
                            "expected_format": "JSON",
                        }
                    ],
                }
            ]
            payload_path = root / "stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("detailed-design", payload_path)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_waiting_for_input_blocks_formal_file_written_before_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            leaked = root / "artifacts" / "detailed-design" / "detailed-design.md"
            leaked.parent.mkdir(parents=True)
            leaked.write_text("# 不应提前生成的详细设计\n", encoding="utf-8")
            result_payload = payload("detailed-design", [], status="waiting_for_input")
            result_payload["required_information_requests"] = [
                {
                    "id": "REQ-INFO-001",
                    "blocking": True,
                    "questions": [
                        {
                            "id": "Q1",
                            "question": "请补充业务边界。",
                            "reason": "缺少边界不能生成正式详细设计。",
                            "required": True,
                            "priority": "critical",
                            "expected_format": "JSON",
                        }
                    ],
                }
            ]
            payload_path = root / "stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("detailed-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("waiting_for_input 不得先落盘正式阶段产物", output)
        self.assertIn("detailed-design.md", output)

    def test_detailed_design_validator_blocks_manual_review_confirmation_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "detailed-design.md"
            template = (ROOT / "skills" / "detailed-design" / "assets" / "detailed-design-template.md").read_text(encoding="utf-8")
            design.write_text(
                template.replace("matched / pending_confirmation / conflict", "人工评审确认"),
                encoding="utf-8",
            )
            result_payload = payload(
                "detailed-design",
                [
                    {"name": "detailed-design.md", "path": str(design)},
                    {"name": "database-design.md", "path": str(root / "database-design.md")},
                    {"name": "mq-design.xlsx", "path": str(root / "mq-design.xlsx"), "artifact_type": "xlsx"},
                    {"name": "redis-design.md", "path": str(root / "redis-design.md")},
                    {"name": "interface-contracts.yaml", "path": str(root / "interface-contracts.yaml"), "artifact_type": "yaml"},
                    {"name": "test-strategy.md", "path": str(root / "test-strategy.md")},
                ],
            )
            payload_path = root / "stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("detailed-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("人工评审确认", output)
        self.assertIn("waiting_for_input", output)
        self.assertIn("human-review HTML", output)

    def test_detailed_design_validator_blocks_forbidden_sections_and_sequence_diagram(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "detailed-design.md"
            design.write_text(
                """# 详细设计

## 来源证据

```mermaid
sequenceDiagram
    A->>B: 调用
```
""",
                encoding="utf-8",
            )
            result_payload = payload(
                "detailed-design",
                [
                    {"name": "detailed-design.md", "path": str(design)},
                    {"name": "database-design.md", "path": str(root / "database-design.md")},
                    {"name": "mq-design.xlsx", "path": str(root / "mq-design.xlsx"), "artifact_type": "xlsx"},
                    {"name": "redis-design.md", "path": str(root / "redis-design.md")},
                    {"name": "interface-contracts.yaml", "path": str(root / "interface-contracts.yaml"), "artifact_type": "yaml"},
                    {"name": "test-strategy.md", "path": str(root / "test-strategy.md")},
                ],
            )
            payload_path = root / "stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("detailed-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("禁止标题", output)
        self.assertIn("sequenceDiagram", output)
        self.assertIn("必须包含 flowchart", output)
        self.assertIn("缺少团队详细设计模板章节", output)

    def test_high_level_design_validator_blocks_generic_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "high-level-design.md"
            design.write_text(
                """# High Level Design 产物模板

## 证据

## Findings

## 必须补充信息

## 门禁决策
""",
                encoding="utf-8",
            )
            result_payload = payload(
                "high-level-design",
                [
                    {"name": "high-level-design.md", "path": str(design)},
                    {"name": "architecture-decision-record.md", "path": str(root / "architecture-decision-record.md")},
                    {"name": "module-boundary.yaml", "path": str(root / "module-boundary.yaml"), "artifact_type": "yaml"},
                    {"name": "risk-list.json", "path": str(root / "risk-list.json"), "artifact_type": "json"},
                ],
            )
            payload_path = root / "hld-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("high-level-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("缺少团队概要设计模板章节", output)
        self.assertIn("通用产物模板标题", output)

    def test_high_level_design_validator_blocks_flowchart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "high-level-design.md"
            design.write_text(
                """# 概要设计

## 0. 原始需求与原型追溯
| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | requirement_spec | specs/req.md |  | 开通流程 | 4.1 | matched |

## 1. 版本变更记录
## 2. 平台概述
## 3. 系统设计
### 3.1 系统逻辑视图
### 3.1.1 系统设计原则
### 3.3 研发视图
### 3.4 研发结构定义
## 4. 核心功能
### 4.1 开通
#### 4.1.1 参与系统与职责设计
| 系统 | 职责 |
| --- | --- |
| 订单服务 | 负责订单事实 |
#### 4.1.2 关键协作摘要

```mermaid
flowchart TD
    A["触发"] --> B["处理"]
```

#### 4.1.3 跨服务服务间时序图
```mermaid
sequenceDiagram
    participant OrderService as 订单服务
    participant MemberService as 会员服务
    OrderService->>MemberService: 服务间协作
```
## 5.中间件设计
## 6.数据视图
""",
                encoding="utf-8",
            )
            result_payload = payload(
                "high-level-design",
                [
                    {"name": "high-level-design.md", "path": str(design)},
                    {"name": "architecture-decision-record.md", "path": str(root / "architecture-decision-record.md")},
                    {"name": "module-boundary.yaml", "path": str(root / "module-boundary.yaml"), "artifact_type": "yaml"},
                    {"name": "risk-list.json", "path": str(root / "risk-list.json"), "artifact_type": "json"},
                ],
            )
            payload_path = root / "hld-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("high-level-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("不得包含 flowchart", output)

    def test_high_level_design_validator_blocks_non_service_sequence_participants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "high-level-design.md"
            design.write_text(
                """# 概要设计

## 0. 原始需求与原型追溯
| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | requirement_spec | specs/req.md |  | 开通流程 | 4.1 | matched |

## 1. 版本变更记录
## 2. 平台概述
## 3. 系统设计
### 3.1 系统逻辑视图
### 3.1.1 系统设计原则
### 3.3 研发视图
### 3.4 研发结构定义
## 4. 核心功能
### 4.1 开通
#### 4.1.3 跨服务服务间时序图
```mermaid
sequenceDiagram
    participant User as 用户
    participant OrderService as 订单服务
    participant DB as 数据库
    User->>OrderService: 提交
    OrderService->>DB: 写入
```
## 5.中间件设计
## 6.数据视图
""",
                encoding="utf-8",
            )
            result_payload = payload(
                "high-level-design",
                [
                    {"name": "high-level-design.md", "path": str(design)},
                    {"name": "architecture-decision-record.md", "path": str(root / "architecture-decision-record.md")},
                    {"name": "module-boundary.yaml", "path": str(root / "module-boundary.yaml"), "artifact_type": "yaml"},
                    {"name": "risk-list.json", "path": str(root / "risk-list.json"), "artifact_type": "json"},
                ],
            )
            payload_path = root / "hld-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("high-level-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("participant 不是服务", output)
        self.assertIn("消息端点不是服务", output)

    def test_high_level_design_validator_requires_participant_evidence_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "high-level-design.md"
            design.write_text(
                """# 概要设计

## 0. 原始需求与原型追溯
| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | requirement_spec | specs/req.md |  | 开通流程 | 4.1 | matched |

## 1. 版本变更记录
## 2. 平台概述
## 3. 系统设计
### 3.1 系统逻辑视图
### 3.1.1 系统设计原则
### 3.3 研发视图
### 3.4 研发结构定义
## 4. 核心功能
### 4.1 开通
#### 4.1.1 参与系统与职责设计
#### 4.1.2 关键协作摘要
服务间协作摘要。
#### 4.1.3 跨服务服务间时序图
```mermaid
sequenceDiagram
    participant OrderService as 订单服务
    participant PaymentNotifyService as 支付通知服务
    OrderService->>PaymentNotifyService: 支付成功通知
```
## 5.中间件设计
## 6.数据视图
""",
                encoding="utf-8",
            )
            result_payload = payload(
                "high-level-design",
                [
                    {"name": "high-level-design.md", "path": str(design)},
                    {"name": "architecture-decision-record.md", "path": str(root / "architecture-decision-record.md")},
                    {"name": "module-boundary.yaml", "path": str(root / "module-boundary.yaml"), "artifact_type": "yaml"},
                    {"name": "risk-list.json", "path": str(root / "risk-list.json"), "artifact_type": "json"},
                ],
            )
            payload_path = root / "hld-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("high-level-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("participant-evidence-map.json", output)
        self.assertIn("PaymentNotifyService", output)

    def test_high_level_design_validator_blocks_unknown_participant_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "high-level-design.md"
            design.write_text(
                """# 概要设计

## 0. 原始需求与原型追溯
| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | requirement_spec | specs/req.md |  | 开通流程 | 4.1 | matched |

## 1. 版本变更记录
## 2. 平台概述
## 3. 系统设计
### 3.1 系统逻辑视图
### 3.1.1 系统设计原则
### 3.3 研发视图
### 3.4 研发结构定义
## 4. 核心功能
### 4.1 开通
#### 4.1.1 参与系统与职责设计
#### 4.1.2 关键协作摘要
服务间协作摘要。
#### 4.1.3 跨服务服务间时序图
```mermaid
sequenceDiagram
    participant OrderService as 订单服务
    participant PaymentNotifyService as 支付通知服务
    OrderService->>PaymentNotifyService: 支付成功通知
```
## 5.中间件设计
## 6.数据视图
""",
                encoding="utf-8",
            )
            evidence = root / "participant-evidence-map.json"
            evidence.write_text(
                json.dumps(
                    {
                        "participants": [
                            {"participant": "OrderService", "status": "confirmed", "code_path": "src/OrderService.java"},
                            {"participant": "PaymentNotifyService", "status": "unknown"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result_payload = payload(
                "high-level-design",
                [
                    {"name": "high-level-design.md", "path": str(design)},
                    {"name": "participant-evidence-map.json", "path": str(evidence), "artifact_type": "json"},
                    {"name": "architecture-decision-record.md", "path": str(root / "architecture-decision-record.md")},
                    {"name": "module-boundary.yaml", "path": str(root / "module-boundary.yaml"), "artifact_type": "yaml"},
                    {"name": "risk-list.json", "path": str(root / "risk-list.json"), "artifact_type": "json"},
                ],
            )
            payload_path = root / "hld-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("high-level-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("unknown/proposed", output)
        self.assertIn("PaymentNotifyService", output)

    def test_high_level_design_validator_blocks_detailed_implementation_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "high-level-design.md"
            design.write_text(
                """# 概要设计

## 0. 原始需求与原型追溯
| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | requirement_spec | specs/req.md |  | 开通流程 | 4.1 | matched |

## 1. 版本变更记录
## 2. 平台概述
## 3. 系统设计
### 3.1 系统逻辑视图
### 3.1.1 系统设计原则
### 3.3 研发视图
### 3.4 研发结构定义
## 4. 核心功能
### 4.1 开通
#### 4.1.3 跨服务服务间时序图
```mermaid
sequenceDiagram
    participant OrderService as 订单服务
    participant MemberService as 会员服务
    OrderService->>MemberService: 服务间协作
```

### 接口字段明细
| 请求字段 | 返回字段 | 类型 |
| --- | --- | --- |
| userId | status | String |

```sql
CREATE TABLE t_order_ext(id bigint);
```

Controller 调用 Mapper，并补充单元测试步骤。

## 5.中间件设计
## 6.数据视图
""",
                encoding="utf-8",
            )
            result_payload = payload(
                "high-level-design",
                [
                    {"name": "high-level-design.md", "path": str(design)},
                    {"name": "architecture-decision-record.md", "path": str(root / "architecture-decision-record.md")},
                    {"name": "module-boundary.yaml", "path": str(root / "module-boundary.yaml"), "artifact_type": "yaml"},
                    {"name": "risk-list.json", "path": str(root / "risk-list.json"), "artifact_type": "json"},
                ],
            )
            payload_path = root / "hld-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("high-level-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("概要设计不得展开详细设计内容", output)
        self.assertIn("请求字段", output)
        self.assertIn("CREATE TABLE", output)
        self.assertIn("Controller", output)

    def test_code_development_validator_requires_source_design_code_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary = root / "implementation-summary.md"
            summary.write_text("# summary\n", encoding="utf-8")
            mapping = root / "design-to-code-mapping.yaml"
            mapping.write_text("- requirement: REQ-001\n  design: detailed-design.md#开通\n  code: src/OrderService.java\n", encoding="utf-8")
            changed = root / "changed-files-report.json"
            changed.write_text(json.dumps({"changed_files": ["src/OrderService.java"]}, ensure_ascii=False), encoding="utf-8")
            matrix = root / "traceability-matrix.json"
            matrix.write_text(json.dumps({"rows": [{"design_section": "detailed-design.md#开通"}]}, ensure_ascii=False), encoding="utf-8")
            result_payload = payload(
                "code-development",
                [
                    {"name": "implementation-summary.md", "path": str(summary)},
                    {"name": "design-to-code-mapping.yaml", "path": str(mapping), "artifact_type": "yaml"},
                    {"name": "changed-files-report.json", "path": str(changed), "artifact_type": "json"},
                    {"name": "traceability-matrix.json", "path": str(matrix), "artifact_type": "json"},
                ],
            )
            payload_path = root / "code-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("code-development", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("design-to-code-mapping.yaml 缺少追踪字段: source_id", output)
        self.assertIn("traceability-matrix.json 第 1 行缺少追踪字段: code_path", output)

    def test_detailed_design_validator_blocks_missing_flow_notes_uml_and_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "detailed-design.md"
            design.write_text(
                """# 详细设计

## 6. 流程图与流程设计

```mermaid
flowchart TD
    A["提交"] --> B["保存"]
```

本方案采用 DDD、ApplicationService、Repository、Handler Template 扩展点。
包含 DDL 和 Redis 新 Key。
""",
                encoding="utf-8",
            )
            result_payload = payload(
                "detailed-design",
                [
                    {"name": "detailed-design.md", "path": str(design)},
                    {"name": "database-design.md", "path": str(root / "database-design.md")},
                    {"name": "mq-design.xlsx", "path": str(root / "mq-design.xlsx"), "artifact_type": "xlsx"},
                    {"name": "redis-design.md", "path": str(root / "redis-design.md")},
                    {"name": "interface-contracts.yaml", "path": str(root / "interface-contracts.yaml"), "artifact_type": "yaml"},
                    {"name": "test-strategy.md", "path": str(root / "test-strategy.md")},
                ],
            )
            payload_path = root / "stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("detailed-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("流程设计说明", output)
        self.assertIn("classDiagram", output)
        self.assertIn("waiting_for_human_review", output)

    def test_detailed_design_validator_blocks_flowchart_without_exception_branches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "detailed-design.md"
            design.write_text(
                """# 详细设计

## 1. 修订历史
## 2. 设计背景与目标摘要
### 2.1 原始需求与原型引用矩阵
| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | requirement_spec | specs/req.md |  | 开通流程 | 3.1 | matched |
## 3. 模块/功能详细设计
### 3.1. 业务流程图

```mermaid
flowchart TD
    A["开始"] --> B["保存"]
    B --> C["成功结束"]
```

流程设计说明：

- 业务规则：保存开通记录
- 校验规则：校验入参
- 事务边界：单事务提交
- 幂等与一致性：按业务单号幂等
- 异常场景：
- 日志要求：记录开始和结束

| 场景 | 触发条件 | 返回编码 | 描述 |
| --- | --- | --- | --- |
| 参数错误 | 参数为空 | 1001 | 参数错误 |

### 3.2. UML类图
## 4. 数据库设计
## 5. 接口定义
### 5.1. API接口列表
### 5.2. 中间件设计
## 6. 单元测试
## 7. 性能与扩展性设计
## 8. 人工评审项
""",
                encoding="utf-8",
            )
            result_payload = payload(
                "detailed-design",
                [
                    {"name": "detailed-design.md", "path": str(design)},
                    {"name": "database-design.md", "path": str(root / "database-design.md")},
                    {"name": "mq-design.xlsx", "path": str(root / "mq-design.xlsx"), "artifact_type": "xlsx"},
                    {"name": "redis-design.md", "path": str(root / "redis-design.md")},
                    {"name": "interface-contracts.yaml", "path": str(root / "interface-contracts.yaml"), "artifact_type": "yaml"},
                    {"name": "test-strategy.md", "path": str(root / "test-strategy.md")},
                ],
            )
            payload_path = root / "stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("detailed-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("缺少异常分支", output)
        self.assertIn("缺少失败终态", output)
        self.assertIn("异常场景表缺少字段", output)
        self.assertIn("补偿/重试/人工处理", output)

    def test_detailed_design_validator_requires_er_diagram_for_database_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "detailed-design.md"
            design.write_text(
                """# 详细设计

## 1. 修订历史
## 2. 设计背景与目标摘要
### 2.1 原始需求与原型引用矩阵
| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | requirement_spec | specs/req.md |  | 导出任务落库 | 3.1 | matched |
## 3. 模块/功能详细设计
### 3.1. 业务流程图

```mermaid
flowchart TD
    A["触发"] --> B{"参数/权限/状态校验通过?"}
    B -- 否 --> E1["返回校验失败"]
    B -- 是 --> C["数据库查询导出任务"]
    C --> D["写入数据库并提交事务"]
    D --> T{"事务处理成功?"}
    T -- 是 --> S["成功终态"]
    T -- 否 --> R{"可重试或可补偿?"}
    R -- 可重试 --> RT["记录日志告警并重试"]
    R -- 可补偿 --> CP["执行补偿/回滚"]
    R -- 不可自动处理 --> H["进入人工处理"]
    E1 --> F["失败结束"]
    RT --> D
    CP --> F
    H --> F
```

流程设计说明：

- 业务规则：导出任务进入处理中后，写入任务表并更新状态。
- 校验规则：参数、权限、状态不合法直接失败。
- 事务边界：数据库写入与状态变更在同一事务提交，失败时回滚。
- 幂等与一致性：按 taskId 幂等，重复请求不重复创建任务。
- 异常场景：见下表。
- 日志要求：记录 traceId、taskId、异常编码和告警维度。

| 场景 | 触发条件 | 异常编码 | 异常信息 | 系统处理动作 | 数据状态 | 日志/告警 | 补偿/重试/人工处理 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 参数/权限/状态校验失败 | 参数为空或状态非法 | EXPORT-001 | 参数非法 | 返回失败 | 不落库 | 记录 traceId 和 taskId | 无需补偿 |
| 外部依赖失败 | 数据库查询超时 | EXPORT-002 | 查询失败 | 记录失败并重试 | 保持处理中 | 告警数据库耗时 | 自动重试 |
| 事务/一致性失败 | 提交失败 | EXPORT-003 | 提交失败 | 回滚事务 | 回滚到提交前状态 | 告警事务失败 | 补偿或人工处理 |

## 4. 数据库设计
| 设计项 | 关联文档 | 说明 |
| --- | --- | --- |
| 数据库专项设计 | `database-design.md` | 使用真实表名 |
## 5. 接口定义
### 5.1. API接口列表
### 5.2. 中间件设计
## 6. 单元测试
## 7. 性能与扩展性设计
## 8. 人工评审项
""",
                encoding="utf-8",
            )
            db_doc = root / "database-design.md"
            db_doc.write_text(
                """## 4. 物理结构设计
### 4.2 字段定义（按表展开）
#### 4.2.1 t_export_task
#### 4.2.2 t_export_task_item
""",
                encoding="utf-8",
            )
            result_payload = payload(
                "detailed-design",
                [
                    {"name": "detailed-design.md", "path": str(design)},
                    {"name": "database-design.md", "path": str(db_doc)},
                    {"name": "mq-design.xlsx", "path": str(root / "mq-design.xlsx"), "artifact_type": "xlsx"},
                    {"name": "redis-design.md", "path": str(root / "redis-design.md")},
                    {"name": "interface-contracts.yaml", "path": str(root / "interface-contracts.yaml"), "artifact_type": "yaml"},
                    {"name": "test-strategy.md", "path": str(root / "test-strategy.md")},
                ],
            )
            payload_path = root / "stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("detailed-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("必须包含 erDiagram", result.stdout + result.stderr)

    def test_detailed_design_validator_blocks_abstract_er_diagram_table_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "detailed-design.md"
            design.write_text(
                """# 详细设计

## 1. 修订历史
## 2. 设计背景与目标摘要
### 2.1 原始需求与原型引用矩阵
| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | requirement_spec | specs/req.md |  | 导出任务落库 | 3.1 | matched |
## 3. 模块/功能详细设计
### 3.1. 业务流程图

```mermaid
flowchart TD
    A["触发"] --> B{"参数/权限/状态校验通过?"}
    B -- 否 --> E1["返回校验失败"]
    B -- 是 --> C["数据库查询导出任务"]
    C --> D["写入数据库并提交事务"]
    D --> T{"事务处理成功?"}
    T -- 是 --> S["成功终态"]
    T -- 否 --> R{"可重试或可补偿?"}
    R -- 可重试 --> RT["记录日志告警并重试"]
    R -- 可补偿 --> CP["执行补偿/回滚"]
    R -- 不可自动处理 --> H["进入人工处理"]
    E1 --> F["失败结束"]
    RT --> D
    CP --> F
    H --> F
```

流程设计说明：

- 业务规则：导出任务进入处理中后，写入任务表并更新状态。
- 校验规则：参数、权限、状态不合法直接失败。
- 事务边界：数据库写入与状态变更在同一事务提交，失败时回滚。
- 幂等与一致性：按 taskId 幂等，重复请求不重复创建任务。
- 异常场景：见下表。
- 日志要求：记录 traceId、taskId、异常编码和告警维度。

| 场景 | 触发条件 | 异常编码 | 异常信息 | 系统处理动作 | 数据状态 | 日志/告警 | 补偿/重试/人工处理 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 参数/权限/状态校验失败 | 参数为空或状态非法 | EXPORT-001 | 参数非法 | 返回失败 | 不落库 | 记录 traceId 和 taskId | 无需补偿 |
| 外部依赖失败 | 数据库查询超时 | EXPORT-002 | 查询失败 | 记录失败并重试 | 保持处理中 | 告警数据库耗时 | 自动重试 |
| 事务/一致性失败 | 提交失败 | EXPORT-003 | 提交失败 | 回滚事务 | 回滚到提交前状态 | 告警事务失败 | 补偿或人工处理 |

### 3.2. 数据库图
```mermaid
erDiagram
    订单表 ||--o{ 明细表 : contains
```

## 4. 数据库设计
| 设计项 | 关联文档 | 说明 |
| --- | --- | --- |
| 数据库专项设计 | `database-design.md` | 使用真实表名 |
## 5. 接口定义
### 5.1. API接口列表
### 5.2. 中间件设计
## 6. 单元测试
## 7. 性能与扩展性设计
## 8. 人工评审项
""",
                encoding="utf-8",
            )
            db_doc = root / "database-design.md"
            db_doc.write_text(
                """## 4. 物理结构设计
### 4.2 字段定义（按表展开）
#### 4.2.1 t_export_task
#### 4.2.2 t_export_task_item
""",
                encoding="utf-8",
            )
            result_payload = payload(
                "detailed-design",
                [
                    {"name": "detailed-design.md", "path": str(design)},
                    {"name": "database-design.md", "path": str(db_doc)},
                    {"name": "mq-design.xlsx", "path": str(root / "mq-design.xlsx"), "artifact_type": "xlsx"},
                    {"name": "redis-design.md", "path": str(root / "redis-design.md")},
                    {"name": "interface-contracts.yaml", "path": str(root / "interface-contracts.yaml"), "artifact_type": "yaml"},
                    {"name": "test-strategy.md", "path": str(root / "test-strategy.md")},
                ],
            )
            payload_path = root / "stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("detailed-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("抽象表名", output)
        self.assertIn("未体现 database-design.md 中已确认的真实表名", output)

    def test_specialty_validators_block_template_and_policy_violations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            db_doc = root / "database-design.md"
            db_doc.write_text("```sql\nUPDATE t_order SET status = 1;\nCREATE TABLE t_order_ext(id bigint);\n```\n", encoding="utf-8")
            db_payload = root / "db-stage-run-result.json"
            db_payload.write_text(json.dumps(payload("database-design", [{"name": "database-design.md", "path": str(db_doc)}]), ensure_ascii=False), encoding="utf-8")
            db_result = run_validator("database-design", db_payload)
            self.assertNotEqual(0, db_result.returncode)
            self.assertIn("没有 WHERE", db_result.stdout + db_result.stderr)

            redis_doc = root / "redis-design.md"
            redis_doc.write_text("Redis 作为事实库。\nTTL：30\n", encoding="utf-8")
            redis_payload = root / "redis-stage-run-result.json"
            redis_payload.write_text(json.dumps(payload("redis-design", [{"name": "redis-design.md", "path": str(redis_doc)}]), ensure_ascii=False), encoding="utf-8")
            redis_result = run_validator("redis-design", redis_payload)
            self.assertNotEqual(0, redis_result.returncode)
            redis_output = redis_result.stdout + redis_result.stderr
            self.assertIn("事实库", redis_output)
            self.assertIn("TTL 必须带单位", redis_output)

            mq_doc = root / "mq-design.xlsx"
            make_mq_xlsx(
                mq_doc,
                producer_values={"K2": "28KB", "P2": "生产消息回放；未说明处理策略"},
                consumer_values={"M2": "死信队列exchange/routeKey"},
            )
            mq_payload = root / "mq-stage-run-result.json"
            mq_payload.write_text(
                json.dumps(
                    payload("mq-design", [{"name": "mq-design.xlsx", "path": str(mq_doc), "artifact_type": "xlsx"}, *write_mq_contract_artifacts(root)]),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            mq_result = run_validator("mq-design", mq_payload)
            self.assertNotEqual(0, mq_result.returncode)
            mq_output = mq_result.stdout + mq_result.stderr
            self.assertIn("幂等", mq_output)
            self.assertIn("超过 10KB", mq_output)

    def test_mq_validator_blocks_template_text_and_range_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mq_doc = root / "mq-design.xlsx"
            make_mq_xlsx(
                mq_doc,
                producer_values={"A1": "修改后的表头", "A3": "新增模板外数据"},
            )
            mq_payload = root / "mq-stage-run-result.json"
            mq_payload.write_text(
                json.dumps(
                    payload("mq-design", [{"name": "mq-design.xlsx", "path": str(mq_doc), "artifact_type": "xlsx"}, *write_mq_contract_artifacts(root)]),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_validator("mq-design", mq_payload)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("固定模板文本不得修改", output)
        self.assertIn("不得新增非模板单元格", output)

    def test_mq_validator_accepts_absolute_relationship_targets_and_header_aligned_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mq_doc = root / "mq-design.xlsx"
            make_mq_xlsx(mq_doc)
            _write_xlsx_row_by_headers(
                mq_doc,
                "生产者",
                2,
                {
                    "业务用途": "待支付订单创建快照",
                    "场景应用": "待支付订单列表",
                    "业务消息key": "pending.pay.order.created",
                    "消息类型": "订单创建事件",
                    "消息体内容": "统一 envelope：issueId、configType=pendingOrderExportTask、pendingOrderExportTask{taskId,taskType,businessType,eventTime}，定义幂等、重试、回放策略",
                    "目的交换机": "pending.pay.exchange",
                    "路由key": "pending.pay.created",
                    "生产服务/模块名称": "facilitator-statistic-service",
                },
            )
            _write_xlsx_row_by_headers(
                mq_doc,
                "消费者",
                2,
                {
                    "队列名称": "pending.pay.order.created.queue",
                    "业务用途": "落待支付快照",
                    "场景应用": "待支付订单列表",
                    "绑定的Exchange/routingKey(多个）": "pending.pay.exchange/pending.pay.created",
                    "死信队列exchange/routeKey": "pending.pay.dlx/pending.pay.created.dlq",
                    "消费服务": "facilitator-statistic-service",
                    "消息key": "pending.pay.order.created",
                    "运维监控": "幂等、死信、重试、回放告警",
                },
            )
            rewrite_workbook_targets_absolute(mq_doc)
            mq_payload = root / "mq-stage-run-result.json"
            mq_payload.write_text(
                json.dumps(
                    payload(
                        "mq-design",
                        [{"name": "mq-design.xlsx", "path": str(mq_doc), "artifact_type": "xlsx"}, *write_mq_contract_artifacts(root)],
                        status="waiting_for_human_review",
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_validator("mq-design", mq_payload)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_mq_validator_blocks_header_misaligned_business_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mq_doc = root / "mq-design.xlsx"
            make_mq_xlsx(mq_doc)
            with tempfile.TemporaryDirectory() as unzip_dir:
                temp = Path(unzip_dir)
                with zipfile.ZipFile(mq_doc) as src:
                    src.extractall(temp)
                write_inline_string_cell(temp / "xl" / "worksheets" / "sheet2.xml", "I2", "误放到交换机列的业务消息key")
                write_inline_string_cell(temp / "xl" / "worksheets" / "sheet2.xml", "J2", "误放到路由列的业务用途")
                with zipfile.ZipFile(mq_doc, "w", zipfile.ZIP_DEFLATED) as dst:
                    for file in temp.rglob("*"):
                        if file.is_file():
                            dst.write(file, file.relative_to(temp).as_posix())
            mq_payload = root / "mq-stage-run-result.json"
            mq_payload.write_text(
                json.dumps(
                    payload(
                        "mq-design",
                        [{"name": "mq-design.xlsx", "path": str(mq_doc), "artifact_type": "xlsx"}, *write_mq_contract_artifacts(root)],
                        status="waiting_for_human_review",
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_validator("mq-design", mq_payload)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("生产者 sheet 第 2 行缺少必填业务值", output)
        self.assertIn("业务消息key", output)

    def test_mq_validator_requires_message_schema_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mq_doc = root / "mq-design.xlsx"
            make_mq_xlsx(mq_doc)
            _write_xlsx_row_by_headers(
                mq_doc,
                "生产者",
                2,
                {
                    "业务用途": "待支付订单创建快照",
                    "场景应用": "待支付订单列表",
                    "业务消息key": "pending.pay.order.created",
                    "消息类型": "订单创建事件",
                    "消息体内容": "统一 envelope：issueId、configType=pendingOrderExportTask、pendingOrderExportTask{taskId,taskType,businessType,eventTime}，定义幂等、重试、回放策略",
                    "目的交换机": "pending.pay.exchange",
                    "路由key": "pending.pay.created",
                    "生产服务/模块名称": "facilitator-statistic-service",
                },
            )
            _write_xlsx_row_by_headers(
                mq_doc,
                "消费者",
                2,
                {
                    "队列名称": "pending.pay.order.created.queue",
                    "业务用途": "落待支付快照",
                    "场景应用": "待支付订单列表",
                    "绑定的Exchange/routingKey(多个）": "pending.pay.exchange/pending.pay.created",
                    "死信队列exchange/routeKey": "pending.pay.dlx/pending.pay.created.dlq",
                    "消费服务": "facilitator-statistic-service",
                    "消息key": "pending.pay.order.created",
                    "运维监控": "幂等、死信、重试、回放告警",
                },
            )
            topic_contract = root / "mq-topic-contract.yaml"
            topic_contract.write_text(
                "producer:\n  messageKey: pending.pay.order.created\n  configType: pendingOrderExportTask\n",
                encoding="utf-8",
            )
            mq_payload = root / "mq-stage-run-result.json"
            mq_payload.write_text(
                json.dumps(
                    payload(
                        "mq-design",
                        [
                            {"name": "mq-design.xlsx", "path": str(mq_doc), "artifact_type": "xlsx"},
                            {"name": "mq-topic-contract.yaml", "path": str(topic_contract), "artifact_type": "yaml"},
                        ],
                        status="waiting_for_human_review",
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_validator("mq-design", mq_payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("message-schema.json", result.stdout + result.stderr)

    def test_mq_validator_blocks_pending_order_export_task_schema_without_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mq_doc = root / "mq-design.xlsx"
            make_mq_xlsx(mq_doc)
            _write_xlsx_row_by_headers(
                mq_doc,
                "生产者",
                2,
                {
                    "业务用途": "待支付订单创建快照",
                    "场景应用": "待支付订单列表",
                    "业务消息key": "pending.pay.order.created",
                    "消息类型": "订单创建事件",
                    "消息体内容": "统一 envelope：issueId、configType=pendingOrderExportTask、pendingOrderExportTask{taskId,taskType,businessType}，定义幂等、重试、回放策略",
                    "目的交换机": "pending.pay.exchange",
                    "路由key": "pending.pay.created",
                    "生产服务/模块名称": "facilitator-statistic-service",
                },
            )
            _write_xlsx_row_by_headers(
                mq_doc,
                "消费者",
                2,
                {
                    "队列名称": "pending.pay.order.created.queue",
                    "业务用途": "落待支付快照",
                    "场景应用": "待支付订单列表",
                    "绑定的Exchange/routingKey(多个）": "pending.pay.exchange/pending.pay.created",
                    "死信队列exchange/routeKey": "pending.pay.dlx/pending.pay.created.dlq",
                    "消费服务": "facilitator-statistic-service",
                    "消息key": "pending.pay.order.created",
                    "运维监控": "幂等、死信、重试、回放告警",
                },
            )
            artifacts = write_mq_contract_artifacts(
                root,
                body_fields={"taskId": "string", "taskType": "string", "businessType": "string"},
                include_required=True,
            )
            mq_payload = root / "mq-stage-run-result.json"
            mq_payload.write_text(
                json.dumps(
                    payload(
                        "mq-design",
                        [{"name": "mq-design.xlsx", "path": str(mq_doc), "artifact_type": "xlsx"}, *artifacts],
                        status="waiting_for_human_review",
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_validator("mq-design", mq_payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("eventTime", result.stdout + result.stderr)

    def test_database_validator_blocks_unresolved_info_and_requires_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_doc = root / "database-design.md"
            template = (ROOT / "skills" / "database-design" / "assets" / "database-oltp-template.md").read_text(encoding="utf-8")
            db_doc.write_text(template.replace("安全/合规接口人 |  |", "安全/合规接口人 | 待补充 |"), encoding="utf-8")

            succeeded_payload = root / "db-succeeded-stage-run-result.json"
            succeeded_payload.write_text(
                json.dumps(payload("database-design", [{"name": "database-design.md", "path": str(db_doc)}]), ensure_ascii=False),
                encoding="utf-8",
            )
            succeeded_result = run_validator("database-design", succeeded_payload)
            self.assertNotEqual(0, succeeded_result.returncode)
            self.assertIn("waiting_for_input", succeeded_result.stdout + succeeded_result.stderr)

            waiting_payload = payload("database-design", [{"name": "database-design.md", "path": str(db_doc)}], status="waiting_for_input")
            waiting_path = root / "db-waiting-stage-run-result.json"
            waiting_path.write_text(json.dumps(waiting_payload, ensure_ascii=False), encoding="utf-8")
            waiting_result = run_validator("database-design", waiting_path)
            self.assertNotEqual(0, waiting_result.returncode)
            self.assertIn("required_information_requests", waiting_result.stdout + waiting_result.stderr)

    def test_database_validator_blocks_compressed_oltp_template_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_doc = root / "database-design.md"
            template = (ROOT / "skills" / "database-design" / "assets" / "database-oltp-template.md").read_text(encoding="utf-8")
            compressed = template.replace("**应写明：**", "").replace("**不应重复：**", "").replace("**编写要点：**", "")
            db_doc.write_text(compressed, encoding="utf-8")
            db_payload = root / "db-stage-run-result.json"
            db_payload.write_text(
                json.dumps(payload("database-design", [{"name": "database-design.md", "path": str(db_doc)}]), ensure_ascii=False),
                encoding="utf-8",
            )

            result = run_validator("database-design", db_payload)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("缺少 OLTP 模板固定内容: 应写明：", output)
        self.assertIn("缺少 OLTP 模板固定内容: 不应重复：", output)
        self.assertIn("缺少 OLTP 模板固定内容: 编写要点：", output)

    def test_design_run_stability_script_normalizes_noise_and_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            left = root / "run-a"
            right = root / "run-b"
            for run_root in [left, right]:
                (run_root / "artifacts" / "high-level-design").mkdir(parents=True)
                (run_root / "artifacts" / "detailed-design").mkdir(parents=True)
                (run_root / "artifacts" / "database-design").mkdir(parents=True)
                (run_root / "artifacts" / "mq-design").mkdir(parents=True)

                (run_root / "artifacts" / "high-level-design" / "high-level-design.md").write_text(
                    """# 概要设计
## 0. 原始需求与原型追溯
## 1. 版本变更记录
## 2. 平台概述
## 3. 系统设计
### 3.1 系统逻辑视图
### 3.1.1 系统设计原则
### 3.3 研发视图
### 3.4 研发结构定义
## 4. 核心功能
### 4.1 待支付订单
#### 4.1.2 关键协作摘要
#### 4.1.3 跨服务服务间时序图
```mermaid
sequenceDiagram
    participant OrderService as 订单服务
    participant StatisticService as 统计服务
    OrderService->>StatisticService: 服务间协作
```
## 5.中间件设计
## 6.数据视图
""",
                    encoding="utf-8",
                )
                (run_root / "artifacts" / "detailed-design" / "detailed-design.md").write_text(
                    """# 详细设计
## 1. 修订历史
## 2. 设计背景与目标摘要
### 2.1 原始需求与原型引用矩阵
## 3. 模块/功能详细设计
### 3.1. 业务流程图
```mermaid
flowchart TD
    A[触发] --> B{参数/权限/状态校验通过?}
    B -- 否 --> F[失败结束]
    B -- 是 --> C[核心处理]
    C --> D[外部依赖/消息协作]
    D --> E{事务/一致性处理成功?}
    E -- 是 --> S[成功终态]
    E -- 否 --> R{可重试或可补偿?}
    R --> M[人工处理]
    M --> F
```
流程设计说明：
- 业务规则：主表快照
- 校验规则：必填校验
- 事务边界：主明细同事务
- 幂等与一致性：orderId 幂等
- 异常场景：见下表
- 日志要求：traceId
| 场景 | 触发条件 | 异常编码 | 异常信息 | 系统处理动作 | 数据状态 | 日志/告警 | 补偿/重试/人工处理 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 参数错误 | 空值 | 1001 | bad request | 拒绝 | 不落库 | 记录 | 无 |
## 4. 数据库设计
## 5. 接口定义
### 5.1. API接口列表
### 5.2. 中间件设计
## 6. 单元测试
## 7. 性能与扩展性设计
## 8. 人工评审项
""",
                    encoding="utf-8",
                )
                (run_root / "artifacts" / "database-design" / "database-design.md").write_text(
                    """# 待支付订单表组 关系型（OLTP）详细设计
## 1. 文档信息
| 项目 | 内容 |
| --- | --- |
| 设计对象 | 强耦合表组：t_pending_order、t_pending_order_item |
**应写明：**
**不应重复：**
**编写要点：**
样例 SQL（MySQL 风格，可按项目替换）
文档结束
""",
                    encoding="utf-8",
                )
                mq_doc = run_root / "artifacts" / "mq-design" / "mq-design.xlsx"
                make_mq_xlsx(mq_doc)
                _write_xlsx_row_by_headers(
                    mq_doc,
                    "生产者",
                    2,
                    {
                        "业务用途": "写待支付快照",
                        "场景应用": "待支付订单",
                        "业务消息key": "pending.pay.created",
                        "消息类型": "订单创建",
                        "消息体内容": "含幂等、重试、回放和死信处理",
                        "目的交换机": "pending.pay.exchange",
                        "路由key": "pending.pay.created",
                        "生产服务/模块名称": "order-service",
                    },
                )
                _write_xlsx_row_by_headers(
                    mq_doc,
                    "消费者",
                    2,
                    {
                        "队列名称": "pending.pay.created.queue",
                        "业务用途": "写快照",
                        "场景应用": "待支付订单",
                        "绑定的Exchange/routingKey(多个）": "pending.pay.exchange/pending.pay.created",
                        "死信队列exchange/routeKey": "pending.pay.dlx/pending.pay.created.dlq",
                        "消费服务": "statistic-service",
                        "消息key": "pending.pay.created",
                        "运维监控": "幂等、重试、回放、死信告警",
                    },
                )
            (left / "stage-run-result.json").write_text(
                json.dumps(
                    {
                        "status": "waiting_for_human_review",
                        "preflight_input_state": "waiting_for_human_review",
                        "artifacts": [{"name": "artifact-index"}, {"name": "human-review-html"}],
                        "findings": [{"id": "DR-001", "severity": "blocker"}],
                        "document_metadata": {"document_number": "DOC-A", "owner": "A"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (right / "stage-run-result.json").write_text(
                json.dumps(
                    {
                        "status": "waiting_for_human_review",
                        "preflight_input_state": "waiting_for_human_review",
                        "artifacts": [{"name": "artifact-index"}, {"name": "human-review-html"}],
                        "findings": [{"id": "DR-001", "severity": "blocker"}],
                        "document_metadata": {"document_number": "DOC-B", "owner": "B"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            stable = subprocess.run(
                ["python3", str(ROOT / "engineering-assistant" / "scripts" / "check_design_run_stability.py"), str(left), str(right)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, stable.returncode, stable.stdout + stable.stderr)

            (right / "artifacts" / "high-level-design" / "high-level-design.md").write_text(
                read_text := (left / "artifacts" / "high-level-design" / "high-level-design.md").read_text(encoding="utf-8").replace("#### 4.1.2 关键协作摘要", "#### 4.1.2 核心流程"),
                encoding="utf-8",
            )
            drift = subprocess.run(
                ["python3", str(ROOT / "engineering-assistant" / "scripts" / "check_design_run_stability.py"), str(left), str(right)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, drift.returncode)

    def test_database_validator_blocks_inconsistent_strong_table_group_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_doc = root / "database-design.md"
            db_doc.write_text(
                """# 配置领取表组 关系型（OLTP）详细设计

## 1. 文档信息
| 项目 | 内容 |
|------|------|
| 文档名称 | 配置领取表组 关系型（OLTP）详细设计 |
| 逻辑库/Schema | biz_schema |
| 物理库标识 | biz_schema |
| 所属集群/实例 | biz-mysql |
| 设计对象 | 强耦合表组：t_biz_config_main、t_biz_config_param |
| 数据库产品 | MySQL |
| 数据库版本 | 8.0 |
| 编写日期 | 2026-06-03 |
| 编写人 | DBA |
| 业务负责人 | 会员域 |
| DBA 负责人 | DBA |
| 安全/合规接口人 | security |

### 1.1 变更记录
| 版本 | 日期 | 变更原因/依据 | 变更摘要 | 变更人 | 评审/批准 |
|------|------|---------------|----------|--------|-----------|

### 1.2 术语定义
| 术语 | 说明 |
|------|------|

### 1.3 参考文档
| 文档名 | 关联类型 | 参考说明 |
|------|------|------|

## 2. 文档定位
### 2.1 编写目的
### 2.2 设计对象类型
| 项目 | 内容 |
|------|------|
| 对象类型 | 配置表 + 入口配置表 |
| 是否强耦合表组 | 是 |
### 2.3 与其他文档的关系
### 2.4 强耦合表组说明
| 成员表 | 角色 | 与主表关系 | 同事务要求 | 备注 |
|--------|------|------------|------------|------|
| t_biz_config_main | 主表 | 主表 | 是 | 配置主记录 |
| t_biz_config_param | 参数表 | main_id | 是 | 配置参数 |

## 3. 业务语义与生命周期
### 3.1 表的业务职责
| 表 | 业务职责 | 唯一事实来源 | 写入方 | 读取方 | 备注 |
|----|----------|--------------|--------|--------|------|
| t_biz_config_main | 配置主记录 | MySQL 本表 | MQ 消费 | 客户端 |  |
| t_biz_config_param | 配置参数 | MySQL 本表 | MQ 消费 | 客户端 |  |
### 3.2 核心业务场景
| 场景 ID | 场景名称 | 触发入口 | 主要 SQL 形态 | 优先级 | 频率/峰值 | 说明 |
|---------|----------|----------|---------------|--------|-----------|------|
### 3.3 数据生命周期阶段
| 阶段 | 进入条件 | 允许的操作类型 | 对外可见性 | 数据留存策略 |
|------|----------|----------------|------------|--------------|
### 3.4 状态机
| 当前状态（值/枚举名） | 允许迁移至 | 触发动作/事件 | 是否可回退 | 备注 |
|----------------------|------------|---------------|------------|------|

## 4. 物理结构设计
### 4.1 建表级环境与约定
### 4.2 字段定义（按表展开）
#### 4.2.1 t_biz_config_main
| 字段 | 类型 | 必填 | 默认值 | 索引 | 敏感级别 | 说明 |
|------|------|------|--------|------|----------|------|
| id | BIGINT | 是 | 无 | PRIMARY | 低 | 主键 |
#### 4.2.2 t_biz_config_param
| 字段 | 类型 | 必填 | 默认值 | 索引 | 敏感级别 | 说明 |
|------|------|------|--------|------|----------|------|
| id | BIGINT | 是 | 无 | PRIMARY | 低 | 主键 |
### 4.3 索引设计
| 表 | 索引名 | 类型 | 字段（顺序敏感） | 唯一 | 服务场景 | 备注 |
|----|--------|------|------------------|------|----------|------|
| t_biz_config_main | PRIMARY | 主键 | id | 是 | 内部关联 |  |
| t_biz_config_param | idx_main_id | 普通索引 | main_id | 否 | 按主记录查参数 |  |
### 4.4 约束与数据库对象
### 4.5 字段可变性矩阵
### 4.6 技术实现依赖
## 5. 数据量与性能设计
### 5.1 数据量估算
### 5.2 读写 QPS 与延迟 SLA
### 5.3 热点与数据倾斜分析
### 5.4 容量规划
### 5.5 性能保障措施
## 6. CRUD 契约设计
### 6.1 CRUD 总览矩阵
| 操作 | 典型入口 | 参与表 | 定位键/幂等键 | 一致性边界 | 必备前置条件 | 允许字段/投影 | 明确禁止 | 并发控制 | 审计 |
|------|----------|--------|---------------|------------|--------------|---------------|----------|----------|------|
| C | MQ 消费 | t_biz_config_main、t_biz_config_param | biz_code | 同事务 | MC-C1 | 配置字段 | 物理删除 | 幂等 | 记录 |
### 6.2 强制前置条件
| 操作 | 编号 | 强制条件（不满足则拒绝） | 错误码/HTTP 建议 |
|------|------|---------------------------|------------------|
| Create | MC-C1 | 幂等键存在 |  |
### 6.3 禁止操作清单
| 编号 | 禁止行为 | 适用范围 | 例外（须工单+审批） |
|------|----------|----------|---------------------|
| PO-01 | 无 WHERE 的 UPDATE/DELETE | 全部环境 | 不存在 |
### 6.4 Create
### 6.5 Read
### 6.6 Update
### 6.7 Delete
### 6.8 幂等键与重复请求
### 6.9 批量操作与数据修复规则
## 7. 事务、一致性与并发控制
### 7.1 本地事务边界
| 场景 ID | 参与表 | 一致性要求 | 提交/回滚策略 | 补偿/核对策略 |
|---------|--------|------------|----------------|----------------|
| T01 | t_biz_config_main、t_biz_config_param | 强一致 | 提交/回滚同事务 | 补偿/核对 |
### 7.2 跨表一致性
### 7.3 并发控制
### 7.4 数据质量校验
### 7.5 隔离级别、死锁与重试约定
### 7.6 跨表最终一致
## 8. 分区、分片与归档设计
### 8.1 路由与分片规则
### 8.2 分区策略
### 8.3 查询策略
### 8.4 归档与保留
### 8.5 冷热分离与只读副本
## 9. 安全与审计设计
### 9.1 敏感字段清单
### 9.2 脱敏与掩码规则
### 9.3 访问控制
### 9.4 审计要求
## 10. 测试与验收
### 10.1 验收检查表
| 检查项 | 结果 | 备注 |
|--------|------|------|
### 10.2 测试用例类型
### 10.3 样例 SQL
## 11. 附录
### 11.1 DDL SQL
### 11.2 兼容性说明
""",
                encoding="utf-8",
            )
            schema = root / "schema-change-plan.sql"
            schema.write_text("CREATE TABLE t_biz_config_main (id BIGINT PRIMARY KEY);", encoding="utf-8")
            migration = root / "migration-plan.md"
            migration.write_text("只建主表。", encoding="utf-8")
            rollback = root / "rollback-plan.md"
            rollback.write_text("允许单表回滚。", encoding="utf-8")
            risk = root / "database-risk-report.json"
            risk.write_text(json.dumps({"risks": ["生产 DDL 审批"]}, ensure_ascii=False), encoding="utf-8")
            result_payload = payload(
                "database-design",
                [
                    {"name": "database-design.md", "path": str(db_doc)},
                    {"name": "schema-change-plan.sql", "path": str(schema), "artifact_type": "sql"},
                    {"name": "migration-plan.md", "path": str(migration)},
                    {"name": "rollback-plan.md", "path": str(rollback)},
                    {"name": "database-risk-report.json", "path": str(risk), "artifact_type": "json"},
                ],
                status="waiting_for_human_review",
            )
            payload_path = root / "db-table-group-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("database-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("CREATE TABLE 数量少于设计对象表数量", output)
        self.assertIn("缺少成员表 CREATE TABLE: t_biz_config_param", output)
        self.assertIn("migration-plan.md 缺少表组口径", output)
        self.assertIn("rollback-plan.md 必须说明", output)
        self.assertIn("database-risk-report.json 缺少表组风险", output)


    def test_high_level_design_validator_blocks_abstract_participant_and_oversimplified_event_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "high-level-design.md"
            design.write_text(
                """# 概要设计

## 0. 原始需求与原型追溯
| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | requirement_spec | specs/req.md |  | 创建类消息和状态变更消息维护本地读模型 | 4.1 | matched |

## 1. 版本变更记录
## 2. 平台概述
## 3. 系统设计
### 3.1 系统逻辑视图
### 3.1.1 系统设计原则
### 3.3 研发视图
### 3.4 研发结构定义
## 4. 核心功能
### 4.1 本地读模型同步
#### 4.1.1 参与系统与职责设计
沿用现有登录态和查询条件过滤流程，不新增外部权限服务。
#### 4.1.2 关键协作摘要
需求涉及 MQ 创建类消息和状态变更消息。
#### 4.1.3 跨服务服务间时序图
```mermaid
sequenceDiagram
    participant UpstreamService as 上游事实服务
    participant AuthScopeService as 权限组织服务
    participant BusinessService as 下游业务系统
    UpstreamService-->>BusinessService: 发送创建类消息
    BusinessService->>UpstreamService: 查询详情
```
## 5.中间件设计
涉及 MQ。
## 6.数据视图
本地读模型。
""",
                encoding="utf-8",
            )
            evidence = root / "participant-evidence-map.json"
            evidence.write_text(
                json.dumps(
                    {
                        "participants": [
                            {"participant": "UpstreamService", "display_name": "上游事实服务", "status": "confirmed", "code_path": "src/UpstreamService.java"},
                            {"participant": "AuthScopeService", "display_name": "权限组织服务", "status": "confirmed", "code_path": "src/AuthScopeService.java"},
                            {"participant": "BusinessService", "display_name": "下游业务系统", "status": "confirmed", "code_path": "src/BusinessService.java"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result_payload = payload(
                "high-level-design",
                [
                    {"name": "high-level-design.md", "path": str(design)},
                    {"name": "participant-evidence-map.json", "path": str(evidence), "artifact_type": "json"},
                    {"name": "architecture-decision-record.md", "path": str(root / "architecture-decision-record.md")},
                    {"name": "module-boundary.yaml", "path": str(root / "module-boundary.yaml"), "artifact_type": "yaml"},
                    {"name": "risk-list.json", "path": str(root / "risk-list.json"), "artifact_type": "json"},
                ],
            )
            payload_path = root / "hld-event-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("high-level-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("抽象能力名", output)
        self.assertIn("至少包含两个核心 sequenceDiagram", output)
        self.assertIn("缺少服务内部关键处理 self-call", output)

    def test_detailed_design_validator_requires_mq_db_redis_key_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "detailed-design.md"
            design.write_text(
                """# 详细设计
## 1. 修订历史
## 2. 设计背景与目标摘要
### 2.1 原始需求与原型引用矩阵
| source_id | source_type | source_path_or_url | prototype_page_or_section | requirement_item | design_section | consistency_status |
| --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | requirement_spec | specs/req.md |  | MQ 消费 Redis 幂等 DB 主明细读模型 | 3.1 | matched |
## 3. 模块/功能详细设计
### 3.1. 业务流程图
```mermaid
flowchart TD
    A["收到 MQ 消息"] --> B["处理消息"]
    B --> C["保存本地读模型到 DB 主表"]
    C -- 失败 --> F["失败终态，重试，人工处理"]
```
流程设计说明：
- 业务规则：维护本地读模型
- 校验规则：基础校验
- 事务边界：单事务
- 幂等与一致性：Redis 幂等记录
- 异常场景：见表
- 日志要求：traceId
| 场景 | 触发条件 | 异常编码 | 异常信息 | 系统处理动作 | 数据状态 | 日志/告警 | 补偿/重试/人工处理 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 失败 | DB异常 | 3001 | 失败 | 回滚 | 未完成 | 告警 | 重试/人工处理 |
## 4. 数据库设计
## 5. 接口定义
### 5.1. API接口列表
### 5.2. 中间件设计
## 6. 单元测试
## 7. 性能与扩展性设计
## 8. 人工评审项
""",
                encoding="utf-8",
            )
            result_payload = payload(
                "detailed-design",
                [
                    {"name": "detailed-design.md", "path": str(design)},
                    {"name": "database-design.md", "path": str(root / "database-design.md")},
                    {"name": "mq-design.xlsx", "path": str(root / "mq-design.xlsx"), "artifact_type": "xlsx"},
                    {"name": "redis-design.md", "path": str(root / "redis-design.md")},
                    {"name": "interface-contracts.yaml", "path": str(root / "interface-contracts.yaml"), "artifact_type": "yaml"},
                    {"name": "test-strategy.md", "path": str(root / "test-strategy.md")},
                ],
            )
            payload_path = root / "detailed-key-path-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("detailed-design", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("MQ + DB + Redis 详细设计关键执行路径缺少", output)
        self.assertIn("死信", output)
        self.assertIn("外部详情查询", output)

    def test_redis_validator_blocks_watermark_and_unsafe_unavailable_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            redis_doc = root / "redis-design.md"
            redis_doc.write_text(
                """# Redis 设计
历史版本信息
## 1. 前言
### 1.1. 目的
### 1.2. 适用范围
### 1.3. 参考资料
## 2. 公共配置
### 2.1. Redis版本
### 2.2. 集群配置
### 2.3. 持久化策略
### 2.4. 过期淘汰策略
## 3. 设计项
### 3.1. <设计项名称>
#### 3.1.1. 特性用途
#### 3.1.2. 业务说明
使用终态水位解决消息乱序。
#### 3.1.3. 存储设计
| 项/值 | 数值 | 说明 |
| --- | --- | --- |
| 库 | 0 |  |
| 数据结构 | String |  |
| ttl | 30分钟 | TTL 必须说明单位 |
| key | service:tenant:string:bizKey |  |
数据格式
Redis 不可用时直接写 DB 并删除本地读模型。
#### 3.1.4. 预估数据
#### 3.1.5. 多团队协同
## 4. 安全与运维
### 4.1. 资源申请
### 4.2. 运维监控
""",
                encoding="utf-8",
            )
            redis_payload = root / "redis-stage-run-result.json"
            redis_payload.write_text(json.dumps(payload("redis-design", [{"name": "redis-design.md", "path": str(redis_doc)}]), ensure_ascii=False), encoding="utf-8")

            result = run_validator("redis-design", redis_payload)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("终态水位", output)
        self.assertIn("不得绕过", output)
        self.assertIn("人工回放", output)

    def test_workflow_validator_requires_design_only_specialty_validator_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary = root / "validator-summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "validators": [
                            {"stage": "high-level-design", "validator": "validate_output.py", "status": "passed"},
                            {"stage": "detailed-design", "validator": "validate_output.py", "status": "failed", "error_message": "missing flow"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result_payload = payload(
                "workflow-orchestrator",
                [{"name": "validator-summary.json", "path": str(summary), "artifact_type": "json"}],
                status="succeeded",
            )
            payload_path = root / "workflow-stage-run-result.json"
            payload_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")

            result = run_validator("workflow-orchestrator", payload_path)

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("缺少: database-design, mq-design, redis-design", output)
        self.assertIn("专项 validator 失败必须向 workflow-orchestrator 冒泡", output)
        self.assertIn("failed_rule", output)
        self.assertIn("suggested_repair", output)



    def test_generic_team_plugin_does_not_embed_personal_or_project_architecture_notes(self) -> None:
        forbidden_terms = [
            "个人画像",
            "个人能力提升",
            "苏格拉底",
            "personal-operating-profile",
            "Socratic personal",
            "YQ / 萤启-人人取",
            "萤启-人人取总体架构",
            "yq-ddd-first-architecture",
            "yq-architecture-inspection",
            "/snbc/yq",
            "平台防腐层",
            "随单购卡",
            "SVIP",
        ]
        checked_roots = [ROOT / "skills", ROOT / "engineering-assistant"]
        offenders: list[str] = []
        for root in checked_roots:
            for file in root.rglob("*"):
                if not file.is_file() or file.suffix not in {".md", ".yaml", ".json", ".py"}:
                    continue
                if "evals" in file.parts or "reports" in file.parts:
                    continue
                text = file.read_text(encoding="utf-8", errors="ignore")
                for term in forbidden_terms:
                    if term in text:
                        offenders.append(f"{file.relative_to(ROOT)}: {term}")
        self.assertEqual([], offenders)

if __name__ == "__main__":
    unittest.main()
