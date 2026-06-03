#!/usr/bin/env python3
"""Regression checks for team detailed-design document rules."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_validator(skill_id: str, payload_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(ROOT / "skills" / skill_id / "scripts" / "validate_output.py"), str(payload_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def payload(skill_id: str, artifacts: list[dict[str, str]], status: str = "succeeded", document_status: str = "draft") -> dict:
    return {
        "run_id": "run-team-doc-001",
        "skill_id": skill_id,
        "status": status,
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


class TeamDocumentDesignRulesTest(unittest.TestCase):
    def test_high_level_design_contract_exposes_team_template_policy(self) -> None:
        contract = json.loads((ROOT / "skills" / "high-level-design" / "contract.yaml").read_text(encoding="utf-8"))
        policy = contract["team_document_policy"]

        self.assertEqual("skills/high-level-design/assets/high-level-design-template.md", policy["canonical_template"])
        template_policy = policy["template_usage_policy"]
        self.assertTrue(template_policy["must_read_template_before_generation"])
        self.assertIn("skills/high-level-design/assets/high-level-design-template.md", json.dumps(template_policy, ensure_ascii=False))
        self.assertIn("不得凭记忆", "\n".join(template_policy["generation_protocol"]))
        for section in ["1. 版本变更记录", "2. 平台概述", "3. 系统设计", "5.中间件设计", "6.数据视图"]:
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
            "mq-design": ["assets/mq-design-template.md"],
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
            ROOT / "skills" / "mq-design" / "assets" / "mq-design-template.md",
        ]
        for path in expected:
            self.assertTrue(path.exists(), f"missing template: {path}")

        hld_template = expected[0].read_text(encoding="utf-8")
        for text in ["0. 原始需求与原型追溯", "source_id", "1. 版本变更记录", "2. 平台概述", "3.1 系统逻辑视图", "4.1.3 跨服务服务间时序图", "sequenceDiagram", "5.中间件设计", "6.数据视图"]:
            self.assertIn(text, hld_template)
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

        expected_cases = [
            "team_db_reference_only",
            "team_mq_template_reference_only",
            "team_redis_template_reference_only",
            "team_flowchart_not_sequence",
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
            "database-design": ["redis-design.md", "mq-design.md", "detailed-design.md", "validate_redis", "validate_mq", "validate_detailed"],
            "redis-design": ["database-design.md", "mq-design.md", "detailed-design.md", "validate_database", "validate_mq", "validate_detailed"],
            "mq-design": ["database-design.md", "redis-design.md", "detailed-design.md", "validate_database", "validate_redis", "validate_detailed"],
        }
        for skill_id, forbidden_items in forbidden_by_skill.items():
            for forbidden in forbidden_items:
                self.assertNotIn(forbidden, scripts[skill_id], f"{skill_id} validator leaked {forbidden}")
            self.assertIn("def validate_output", scripts[skill_id])
            self.assertIn("fail(validate_output(payload_path, payload))", scripts[skill_id])

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
                    {"name": "mq-design.md", "path": str(root / "mq-design.md")},
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
                    {"name": "mq-design.md", "path": str(root / "mq-design.md")},
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

            mq_doc = root / "mq-design.md"
            mq_doc.write_text("消息预估大小：28KB\n生产消息回放。\n", encoding="utf-8")
            mq_payload = root / "mq-stage-run-result.json"
            mq_payload.write_text(json.dumps(payload("mq-design", [{"name": "mq-design.md", "path": str(mq_doc)}]), ensure_ascii=False), encoding="utf-8")
            mq_result = run_validator("mq-design", mq_payload)
            self.assertNotEqual(0, mq_result.returncode)
            mq_output = mq_result.stdout + mq_result.stderr
            self.assertIn("生产者表缺少字段", mq_output)
            self.assertIn("超过 10KB", mq_output)

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


if __name__ == "__main__":
    unittest.main()
