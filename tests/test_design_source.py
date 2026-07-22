from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.design_source import (  # noqa: E402
    check_design_source,
    read_design_document,
    resolve_design_source,
    validate_database_design,
    validate_review_package,
)
from engineering_assistant.model import DesignSourceRef  # noqa: E402
from engineering_assistant.mcp_server import RuntimeTools  # noqa: E402
from engineering_assistant.validation import (  # noqa: E402
    ValidationFailure,
    load_json,
    validate_instance,
)


class DesignSourceTests(unittest.TestCase):
    def _completed_database_design(self) -> str:
        template = (
            ROOT
            / "skills/codebase-design/references/relational-oltp-detailed-design-template.md"
        ).read_text(encoding="utf-8")
        completed = re.sub(r"\{[^{}\n]+\}", "实际值", template)
        return completed.replace("YYYY-MM-DD", "2026-07-22")

    def _source(self, root: Path) -> DesignSourceRef:
        governance = root / "90-design-basis/30-document-governance"
        hld = root / "10-high-level-design"
        details = root / "20-context-detailed-design/10-context-designs"
        templates = root / "40-templates"
        governance.mkdir(parents=True)
        hld.mkdir(parents=True)
        details.mkdir(parents=True)
        templates.mkdir(parents=True)
        (hld / "01-high-level-design.md").write_text(
            "---\ndocument_number: HLD-YQ-001\ndocument_status: reviewing\n"
            "version: V1.0-reviewing\nowner: architect\n---\n# HLD\n",
            encoding="utf-8",
        )
        (details / "01-trade-context.md").write_text(
            "---\ndocument_number: DDD-YQ-TRADE-001\ndocument_status: reviewing\n"
            "version: V1.0-reviewing\nowner: trade-owner\n---\n# Trade\n",
            encoding="utf-8",
        )
        (templates / "01-high-level-design-template.md").write_text(
            "# HLD template\n", encoding="utf-8"
        )
        (templates / "02-detailed-design-template.md").write_text(
            "# DDD template\n", encoding="utf-8"
        )
        (governance / "07-architecture-impact-rules.yaml").write_text(
            "rules: []\n", encoding="utf-8"
        )
        (governance / "04-document-registry.yaml").write_text(
            "registry_version: 1.0.0\n"
            "documents:\n"
            "  - document_number: HLD-YQ-001\n"
            "    type: high_level_design\n"
            "    path: ../../10-high-level-design/01-high-level-design.md\n"
            "    status: reviewing\n"
            "    owner: architect\n"
            "  - document_number: DDD-YQ-TRADE-001\n"
            "    type: context_detailed_design\n"
            "    path: ../../20-context-detailed-design/10-context-designs/01-trade-context.md\n"
            "    status: reviewing\n"
            "    owner: trade-owner\n",
            encoding="utf-8",
        )
        return DesignSourceRef(
            root=str(root),
            registry="90-design-basis/30-document-governance/04-document-registry.yaml",
        )

    def test_resolve_read_and_detect_stale_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._source(Path(temporary))
            snapshot = resolve_design_source(source)
            validate_instance(
                snapshot,
                load_json(ROOT / "schemas/design-source-snapshot.schema.json"),
                "design-source-snapshot",
            )

            self.assertRegex(snapshot["digest"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual("HLD-YQ-001", snapshot["high_level_design"]["document_number"])
            self.assertEqual(1, len(snapshot["context_detailed_designs"]))
            self.assertEqual(2, len(snapshot["templates"]))
            self.assertEqual(1, len(snapshot["governance_inputs"]))
            document = read_design_document(source, "DDD-YQ-TRADE-001")
            self.assertIn("# Trade", document["content"])
            self.assertEqual("current", check_design_source(source, snapshot["digest"])["status"])

            trade_digest = snapshot["context_detailed_designs"][0]["digest"]
            self.assertEqual(
                "current",
                check_design_source(source, trade_digest, "DDD-YQ-TRADE-001")["status"],
            )

            governance = Path(source.root) / "90-design-basis/30-document-governance/07-architecture-impact-rules.yaml"
            governance.write_text("rules:\n  - changed\n", encoding="utf-8")
            self.assertEqual("stale", check_design_source(source, snapshot["digest"])["status"])
            self.assertEqual(
                "current",
                check_design_source(source, trade_digest, "DDD-YQ-TRADE-001")["status"],
            )

            target = Path(source.root) / "20-context-detailed-design/10-context-designs/01-trade-context.md"
            target.write_text(target.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
            self.assertEqual("stale", check_design_source(source, snapshot["digest"])["status"])
            self.assertEqual(
                "stale",
                check_design_source(source, trade_digest, "DDD-YQ-TRADE-001")["status"],
            )

    def test_registry_path_cannot_escape_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = DesignSourceRef(root=temporary, registry="../outside.yaml")
            with self.assertRaisesRegex(ValidationFailure, "within design source root"):
                resolve_design_source(source)

    def test_review_package_requires_reviewing_documents_and_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = (
                Path(temporary)
                / ".run-artifacts/engineering-assistant/review-packages/REQ-1"
            )
            package.mkdir(parents=True)
            for name in (
                "01-impact-assessment.md",
                "04-interface-and-specialty-delta.yaml",
                "05-implementation-and-test-plan.md",
                "08-review-checklist.md",
            ):
                (package / name).write_text("complete\n", encoding="utf-8")
            (package / "06-design-change-summary.md").write_text(
                "新增 修改 删除 明确不变\n聚合 不变量 流程 状态 接口 资源\n"
                "冲突 合并顺序 共同回归\n",
                encoding="utf-8",
            )
            (package / "03-trade-detailed-design.review.md").write_text(
                "---\ndocument_number: DDD-YQ-TRADE-001\ndocument_status: reviewing\n"
                "requirement_id: REQ-1\nbase_document_number: DDD-YQ-TRADE-001\n"
                "base_version: V1.0-reviewing\nbase_digest: sha256:" + "a" * 64 + "\n---\n# Trade\n",
                encoding="utf-8",
            )
            (package / "07-requirement-design-traceability.yaml").write_text(
                "requirement_id: REQ-1\ndesign_source_digest: sha256:" + "b" * 64 + "\n"
                "mappings:\n"
                "  - requirement_item: REQ-1-AC-01\n"
                "    design_document: DDD-YQ-TRADE-001\n"
                "    design_section: '4.2'\n"
                "    design_change: modified\n"
                "    code_targets: []\n"
                "    test_cases: []\n"
                "    status: designed\n",
                encoding="utf-8",
            )

            report = validate_review_package(package, "REQ-1")
            self.assertEqual("passed", report["status"])

            (package / "01-impact-assessment.md").write_text(
                "database_impact: true\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ValidationFailure, "database impact requires database designs"
            ):
                validate_review_package(package, "REQ-1")

            database_designs = package / "09-database-designs"
            database_designs.mkdir()
            database_design = database_designs / "trade.review.md"
            database_design.write_text(
                self._completed_database_design(), encoding="utf-8"
            )
            self.assertEqual(
                ["09-database-designs/trade.review.md"],
                validate_review_package(package, "REQ-1")["database_designs"],
            )

            (package / "02-high-level-design.review.md").write_text(
                (package / "03-trade-detailed-design.review.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValidationFailure, "system-level impact"):
                validate_review_package(package, "REQ-1")
            (package / "01-impact-assessment.md").write_text(
                "system_level_impact: true\ndatabase_impact: true\n",
                encoding="utf-8",
            )
            self.assertEqual("passed", validate_review_package(package, "REQ-1")["status"])

            review = package / "03-trade-detailed-design.review.md"
            review.write_text(review.read_text(encoding="utf-8").replace("reviewing", "final", 1), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "must stay reviewing"):
                validate_review_package(package, "REQ-1")

    def test_database_design_requires_exact_template_structure_and_resolved_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            document = Path(temporary) / "trade.md"
            document.write_text(
                self._completed_database_design(), encoding="utf-8"
            )

            report = validate_database_design(document)
            self.assertEqual("passed", report["status"])
            self.assertEqual(63, report["heading_count"])
            self.assertGreater(report["table_count"], 30)

            document.write_text(
                self._completed_database_design().replace(
                    "### 6.8 幂等键与重复请求\n", "", 1
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValidationFailure, "heading structure differs"
            ):
                validate_database_design(document)

            document.write_text(
                self._completed_database_design().replace(
                    "| 索引名 | 类型 | 字段（顺序敏感） | 唯一 | 服务场景 | 备注 |",
                    "| 索引名 | 类型 | 字段 | 唯一 | 场景 |",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValidationFailure, "table structure differs"
            ):
                validate_database_design(document)

            template = (
                ROOT
                / "skills/codebase-design/references/relational-oltp-detailed-design-template.md"
            ).read_text(encoding="utf-8")
            document.write_text(template, encoding="utf-8")
            with self.assertRaisesRegex(
                ValidationFailure, "unresolved placeholder"
            ):
                validate_database_design(document)

    def test_read_only_mcp_tools_expose_snapshot_and_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._source(Path(temporary))
            tools = RuntimeTools(ROOT)
            arguments = {"source_root": source.root, "registry": source.registry}

            snapshot = tools.call(
                "engineering_assistant_design_source_resolve", arguments
            )
            document = tools.call(
                "engineering_assistant_design_source_read",
                {**arguments, "document": "HLD-YQ-001"},
            )
            current = tools.call(
                "engineering_assistant_design_source_check",
                {**arguments, "expected_digest": snapshot["digest"]},
            )

            self.assertIn("# HLD", document["content"])
            self.assertEqual("current", current["status"])
            definitions = {item["name"]: item for item in tools.definitions()}
            for name in (
                "engineering_assistant_design_source_resolve",
                "engineering_assistant_design_source_read",
                "engineering_assistant_design_source_check",
                "engineering_assistant_review_package_validate",
                "engineering_assistant_database_design_validate",
            ):
                self.assertTrue(definitions[name]["annotations"]["readOnlyHint"])

            database_document = Path(temporary) / "database-design.md"
            database_document.write_text(
                self._completed_database_design(), encoding="utf-8"
            )
            database_report = tools.call(
                "engineering_assistant_database_design_validate",
                {"document_path": str(database_document)},
            )
            self.assertEqual("passed", database_report["status"])


if __name__ == "__main__":
    unittest.main()
