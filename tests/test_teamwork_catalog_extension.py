from __future__ import annotations

import json
import hashlib
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.catalog import load_catalog  # noqa: E402
from engineering_assistant.compiler import build_package  # noqa: E402
from engineering_assistant.engine import RuntimeEngine  # noqa: E402
from engineering_assistant.evidence import EvidenceStore  # noqa: E402
from engineering_assistant.mcp_server import MCPServer, RuntimeTools  # noqa: E402
from engineering_assistant.model import (  # noqa: E402
    CriterionResult,
    DesignSourceRef,
    EvidenceRef,
    RouteIntent,
    StepResult,
)
from engineering_assistant.router import route_intent  # noqa: E402
from engineering_assistant.state_store import StateStore  # noqa: E402
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class _EvidenceVerifier:
    def verify_evidence(self, run_id: str, evidence: EvidenceRef) -> bool:
        return evidence.attestation == f"team-test:{run_id}:{evidence.id}"


class TeamworkCatalogExtensionTests(unittest.TestCase):
    def _copy_author_sources(self, root: Path) -> None:
        shutil.copytree(ROOT / "catalog", root / "catalog")
        shutil.copytree(ROOT / "schemas", root / "schemas")

    def _empty_evidence_store(self) -> EvidenceStore:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return EvidenceStore(
            StateStore(Path(temporary.name), ROOT / "schemas"), _EvidenceVerifier()
        )

    @staticmethod
    def _intent(kind: str = "design") -> RouteIntent:
        return RouteIntent(
            task_kind=kind,
            requested_outcome="完成团队交付",
            scope=["rrq-yq"],
            risk_signals=[],
            requested_external_actions=[],
            confidence=1.0,
            evidence=["user-request"],
        )

    @staticmethod
    def _attested_evidence(
        project: Path,
        run_id: str,
        evidence_id: str,
        *,
        kind: str,
        scope_tags: list[str],
        contract_refs: list[str],
    ) -> EvidenceRef:
        target = project / f"{evidence_id}.txt"
        target.write_text(evidence_id + "\n", encoding="utf-8")
        return EvidenceRef(
            id=evidence_id,
            kind=kind,
            uri=str(target),
            producer="team-test",
            observed_at=datetime.now(timezone.utc).isoformat(),
            trust_level="observed",
            scope="team delivery test",
            scope_tags=scope_tags,
            contract_refs=contract_refs,
            digest="sha256:" + hashlib.sha256(target.read_bytes()).hexdigest(),
            attestation=f"team-test:{run_id}:{evidence_id}",
        )

    def test_product_identity_and_default_profile_are_author_sources(self) -> None:
        catalog = load_catalog(ROOT)

        self.assertEqual("teamwork-engineering-assistant", catalog.product.id)
        self.assertEqual("团队研发助手", catalog.product.display_name)
        self.assertEqual("engineering-assistant", catalog.product.root_skill_id)
        self.assertEqual("rrq-yq-team", catalog.product.default_profile_id)
        self.assertEqual("rrq-yq-team", catalog.default_profile.id)

    def test_multiple_component_files_are_aggregated_deterministically(self) -> None:
        catalog = load_catalog(ROOT)

        self.assertEqual(7, len(catalog.flows))
        self.assertEqual(11, len(catalog.policies))
        self.assertEqual(17, len(catalog.packs))
        self.assertEqual(["default", "rrq-yq-team"], sorted(catalog.profiles))
        self.assertEqual("team-delivery", list(catalog.flows)[-1])

    def test_duplicate_ids_across_component_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_author_sources(root)
            core = json.loads((root / "catalog/flows/core.json").read_text(encoding="utf-8"))
            duplicate = {
                "version": core["version"],
                "flows": [core["flows"][0]],
            }
            (root / "catalog/flows/duplicate.json").write_text(
                json.dumps(duplicate), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValidationFailure, "duplicate id"):
                load_catalog(root)

    def test_component_file_version_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_author_sources(root)
            teamwork = root / "catalog/packs/teamwork.json"
            data = json.loads(teamwork.read_text(encoding="utf-8"))
            data["version"] = "2.0.0.1-rc.1"
            teamwork.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ValidationFailure, "component versions do not agree"):
                load_catalog(root)

    def test_unknown_product_default_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_author_sources(root)
            product = root / "catalog/product.json"
            data = json.loads(product.read_text(encoding="utf-8"))
            data["default_profile_id"] = "missing-profile"
            product.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ValidationFailure, "default profile"):
                load_catalog(root)

    def test_profile_pack_and_rule_references_are_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_author_sources(root)
            profile = root / "catalog/profiles/rrq-yq-team.json"
            data = json.loads(profile.read_text(encoding="utf-8"))
            data["pack_refs"].append("missing-pack")
            profile.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ValidationFailure, "unknown references"):
                load_catalog(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_author_sources(root)
            profile = root / "catalog/profiles/rrq-yq-team.json"
            data = json.loads(profile.read_text(encoding="utf-8"))
            data["rule_catalog_ref"] = "missing-rules"
            profile.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ValidationFailure, "rule catalog"):
                load_catalog(root)

    def test_rule_catalog_has_exact_counts_and_no_local_source_paths(self) -> None:
        catalog = load_catalog(ROOT)
        rules = catalog.rule_catalogs["rrq-yq-team-rules"]

        self.assertEqual(110, len(rules.rules))
        self.assertEqual(8, len(rules.sources))
        counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        for rule in rules.rules.values():
            target = rule.target_refs[0]
            counts[target] = counts.get(target, 0) + 1
            category_counts[rule.category] = category_counts.get(rule.category, 0) + 1
            self.assertTrue(rule.source_refs)
            self.assertTrue(rule.capability_refs)
        self.assertEqual(
            {
                "rrq-yq-delivery": 54,
                "rrq-yq-architecture": 22,
                "rrq-yq-api": 10,
                "rrq-yq-code-quality": 12,
                "rrq-yq-frontend": 4,
                "rrq-yq-database": 3,
                "rrq-yq-redis": 2,
                "rrq-yq-mq": 3,
            },
            counts,
        )
        self.assertEqual(
            {
                "架构": 6, "概要设计": 11, "详细设计": 11, "接口": 2,
                "异常": 2, "幂等并发": 2, "Redis": 2, "MQ": 3,
                "数据库": 3, "框架选型": 4, "前端": 4, "文档治理": 22,
                "信息补全": 8, "代码研发": 1, "代码质量": 2, "JDK21": 1,
                "DDD": 2, "TDD": 1, "框架高级特性": 1, "设计模式": 1,
                "人人取架构": 1, "人人取通用技术": 2, "人人取日志": 1,
                "人人取安全": 1, "人人取监控": 1, "人人取幂等": 3,
                "YApi": 6, "萤启服务商系统": 4, "知识沉淀": 2,
            },
            category_counts,
        )
        for source in rules.sources.values():
            self.assertFalse(Path(source.url).is_absolute())
            self.assertRegex(source.digest, r"^git-blob:[0-9a-f]{40}$")
            self.assertNotIn(".html", source.url.casefold())
        author_text = (ROOT / "catalog/rules/rrq-yq-team.json").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("/Users/", author_text)
        self.assertNotIn(".html", author_text.casefold())
        for legacy_protocol in (
            "StageRunRequest",
            "StageRunResult",
            "preflight_input_state",
            "formal_generation",
            "artifacts/rule-governance",
        ):
            self.assertNotIn(legacy_protocol, author_text)
        self.assertFalse((ROOT / "inputs").exists())
        self.assertFalse((ROOT / "generator").exists())
        self.assertFalse((ROOT / "runtime/compiled").exists())

    def test_broken_rule_source_and_target_references_are_rejected(self) -> None:
        for field, value, message in (
            ("source_refs", ["missing-source"], "unknown references"),
            ("target_refs", ["missing-pack"], "unknown references"),
            ("capability_refs", ["missing-capability"], "unknown references"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._copy_author_sources(root)
                rule_catalog = root / "catalog/rules/rrq-yq-team.json"
                data = json.loads(rule_catalog.read_text(encoding="utf-8"))
                data["rules"][0][field] = value
                rule_catalog.write_text(json.dumps(data), encoding="utf-8")

                with self.assertRaisesRegex(ValidationFailure, message):
                    load_catalog(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_author_sources(root)
            rule_catalog = root / "catalog/rules/rrq-yq-team.json"
            data = json.loads(rule_catalog.read_text(encoding="utf-8"))
            data["sources"][0]["url"] = "/Users/example/raw-standard.html"
            rule_catalog.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ValidationFailure, "local path"):
                load_catalog(root)

    def test_default_route_uses_the_product_default_profile(self) -> None:
        catalog = load_catalog(ROOT)
        decision = route_intent(
            RouteIntent(
                task_kind="design",
                requested_outcome="设计团队交付方案",
                scope=["rrq-yq"],
                risk_signals=[],
                requested_external_actions=[],
                confidence=1.0,
                evidence=["user-request"],
            ),
            catalog,
        )

        self.assertIn("teamwork-delivery-gates", decision.policy_refs)
        self.assertIn("teamwork-rule-consumption", decision.policy_refs)

        with self.assertRaisesRegex(ValidationFailure, "unknown profile"):
            route_intent(self._intent(), catalog, profile_id="missing-profile")

    def test_build_changes_product_identity_but_preserves_runtime_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "codex"
            build_package(ROOT, "codex", output)
            manifest = json.loads(
                (output / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
            )
            mcp = json.loads((output / ".mcp.json").read_text(encoding="utf-8"))

            self.assertEqual("teamwork-engineering-assistant", manifest["name"])
            self.assertEqual("团队研发助手", manifest["interface"]["displayName"])
            self.assertEqual(
                ["teamwork-engineering-assistant"], list(mcp["mcpServers"])
            )
            self.assertEqual(
                "./engineering-assistant/bin/ea",
                mcp["mcpServers"]["teamwork-engineering-assistant"]["command"],
            )
            self.assertEqual(
                set(load_catalog(ROOT).skills),
                {path.parent.name for path in (output / "skills").glob("*/SKILL.md")},
            )
            self.assertTrue((output / "engineering-assistant/bin/ea").is_file())

        tools = RuntimeTools(ROOT)
        self.assertEqual(
            "rrq-yq-team",
            tools.definitions()[0]["inputSchema"]["properties"]["profile"]["default"],
        )
        self.assertTrue(
            all(item["name"].startswith("engineering_assistant_") for item in tools.definitions())
        )
        initialize = MCPServer(tools).handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        self.assertEqual(
            "teamwork-engineering-assistant",
            initialize["result"]["serverInfo"]["name"],
        )
        route = tools.call(
            "engineering_assistant_route",
            {"intent": self._intent().to_dict()},
        )
        self.assertEqual("team-delivery", route["decision"]["flow_id"])
        self.assertFalse(route["execution"]["persisted_flow_ready"])
        self.assertEqual("skills_only", route["execution"]["recommended_execution"])

    def test_skills_only_route_exposes_task_scoped_team_rules(self) -> None:
        tools = RuntimeTools(ROOT)
        intent = replace(
            self._intent(),
            requested_outcome="设计包含 Redis 缓存与接口契约的团队方案",
            scope=["rrq-yq", "Redis", "API"],
            requirement_id="REQ-TEAM-001",
            design_source=DesignSourceRef(
                root="/project/project-inspection",
                registry="90-design-basis/30-document-governance/04-document-registry.yaml",
            ),
        )

        routed = tools.call(
            "engineering_assistant_route",
            {"intent": intent.to_dict()},
        )

        self.assertEqual("skills_only", routed["execution"]["recommended_execution"])
        context = routed["team_context"]
        self.assertEqual("ready", context["design_input_status"])
        self.assertEqual([], context["missing_required_inputs"])
        self.assertEqual(
            {
                "requirement_id": "REQ-TEAM-001",
                "design_source": {
                    "root": "/project/project-inspection",
                    "registry": "90-design-basis/30-document-governance/04-document-registry.yaml",
                },
            },
            context["deterministic_design_input"],
        )
        self.assertEqual("rrq-yq-team", context["profile_id"])
        self.assertEqual("rrq-yq-team-rules", context["rule_catalog_id"])
        self.assertEqual(
            [
                "rrq-yq-delivery",
                "rrq-yq-architecture",
                "rrq-yq-api",
                "rrq-yq-redis",
            ],
            context["pack_refs"],
        )
        self.assertNotIn("rrq-yq-frontend", context["pack_refs"])
        self.assertNotIn("rrq-yq-database", context["pack_refs"])
        self.assertNotIn("rrq-yq-mq", context["pack_refs"])
        rule_ids = {rule["id"] for rule in context["rules"]}
        self.assertIn("R1", rule_ids)
        self.assertIn("YAPI1", rule_ids)
        for rule in context["rules"]:
            self.assertEqual(f"rule:{rule['id']}", rule["evidence_contract_ref"])
            self.assertTrue(set(rule["target_refs"]) & set(context["pack_refs"]))
        source_ids = {source["id"] for source in context["sources"]}
        self.assertEqual(
            source_ids,
            {source_ref for rule in context["rules"] for source_ref in rule["source_refs"]},
        )

        generic = tools.call(
            "engineering_assistant_route",
            {"intent": intent.to_dict(), "profile": "default"},
        )
        self.assertNotIn("team_context", generic)

        missing = tools.call(
            "engineering_assistant_route", {"intent": self._intent().to_dict()}
        )["team_context"]
        self.assertEqual("missing", missing["design_input_status"])
        self.assertEqual(
            ["requirement_id", "design_source"], missing["missing_required_inputs"]
        )

    def test_ordinary_code_review_does_not_require_design_inputs(self) -> None:
        tools = RuntimeTools(ROOT)
        ordinary = tools.call(
            "engineering_assistant_route",
            {
                "intent": replace(
                    self._intent("review"),
                    requested_outcome="对固定分支进行普通代码走查",
                    scope=["rrq-yq", "code diff"],
                ).to_dict()
            },
        )

        self.assertEqual("review", ordinary["decision"]["flow_id"])
        context = ordinary["team_context"]
        self.assertEqual("not_applicable", context["design_input_status"])
        self.assertEqual([], context["missing_required_inputs"])
        self.assertIn("code-review", context["capability_refs"])
        self.assertNotIn("design-source-read", context["capability_refs"])
        self.assertNotIn("review-package-validation", context["capability_refs"])
        self.assertNotIn("design-review", context["capability_refs"])

        requested = tools.call(
            "engineering_assistant_route",
            {
                "intent": replace(
                    self._intent("review"),
                    requested_outcome="执行设计到实现追踪代码走查",
                ).to_dict()
            },
        )["team_context"]
        self.assertEqual("missing", requested["design_input_status"])
        self.assertEqual(
            ["requirement_id", "design_source"],
            requested["missing_required_inputs"],
        )
        self.assertIn("design-source-read", requested["capability_refs"])

        ready = tools.call(
            "engineering_assistant_route",
            {
                "intent": replace(
                    self._intent("review"),
                    requested_outcome="执行设计到实现追踪代码走查",
                    requirement_id="REQ-REVIEW-001",
                    design_source=DesignSourceRef(
                        root="/project/project-inspection",
                        registry="90-design-basis/30-document-governance/04-document-registry.yaml",
                    ),
                ).to_dict()
            },
        )["team_context"]
        self.assertEqual("ready", ready["design_input_status"])
        self.assertEqual([], ready["missing_required_inputs"])
        self.assertIn("review-package-validation", ready["capability_refs"])
        self.assertIn("design-review", ready["capability_refs"])

    def test_database_design_route_activates_team_template_capability(self) -> None:
        tools = RuntimeTools(ROOT)
        context = tools.call(
            "engineering_assistant_route",
            {
                "intent": replace(
                    self._intent(),
                    requested_outcome="为 MySQL OLTP 表设计字段、索引和事务",
                    scope=["rrq-yq", "database", "schema"],
                ).to_dict()
            },
        )["team_context"]

        self.assertIn("rrq-yq-database", context["pack_refs"])
        self.assertIn("database-design", context["capability_refs"])
        database_pack = next(
            pack for pack in context["packs"] if pack["id"] == "rrq-yq-database"
        )
        self.assertEqual("packs/rrq-yq-database.md", database_pack["source_path"])

    def test_persisted_node_payload_exposes_only_applicable_rule_contracts(self) -> None:
        catalog = load_catalog(ROOT)
        engine = RuntimeEngine(catalog)
        state = engine.start("team-context", self._intent(), run_id="team-context-run")
        engine.next(state)

        payload = engine.node_payload(state)

        self.assertIsNotNone(payload)
        rules = payload["team_rules"]
        self.assertEqual(
            {"QIN1", "QIN2", "QIN3", "QIN4", "QIN5", "QIN6", "QIN7", "QIN8", "DG23"},
            {rule["id"] for rule in rules},
        )
        self.assertEqual(
            [*[f"rule:QIN{index}" for index in range(1, 9)], "rule:DG23"],
            payload["rule_contract_refs"],
        )
        self.assertTrue(all("repo-context" in rule["capability_refs"] for rule in rules))

    def test_rule_contract_policy_accepts_test_evidence_for_tdd(self) -> None:
        catalog = load_catalog(ROOT)
        engine = RuntimeEngine(catalog)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            state_store = StateStore(project, ROOT / "schemas")
            evidence_store = EvidenceStore(state_store, _EvidenceVerifier())
            state = engine.start("team-tdd", self._intent(), run_id="team-tdd-run")
            state.current_node = "tdd"
            state.status = "running"
            evidence_store.save(
                state.run_id,
                self._attested_evidence(
                    project,
                    state.run_id,
                    "tdd-test",
                    kind="test",
                    scope_tags=["flow:team-delivery", "stage:implementation"],
                    contract_refs=["rule:TDD1"],
                ),
            )

            gate = engine.complete_step(
                state,
                StepResult(
                    run_id=state.run_id,
                    node_id="tdd",
                    status="completed",
                    criteria_results=[CriterionResult("tdd:1", True, ["tdd-test"])],
                    outputs=["red-green evidence"],
                    findings=[],
                    open_questions=[],
                    requested_transition="continue",
                ),
                evidence_store=evidence_store,
            )

            self.assertNotEqual("retry", gate.decision)
            self.assertNotIn(
                "teamwork-rule-consumption:one-of(approval,review,source)",
                gate.missing_evidence,
            )

    def test_team_flow_requires_an_applicable_rule_contract_reference(self) -> None:
        catalog = load_catalog(ROOT)
        engine = RuntimeEngine(catalog)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            state_store = StateStore(project, ROOT / "schemas")
            evidence_store = EvidenceStore(state_store, _EvidenceVerifier())
            state = engine.start("team-task", self._intent(), run_id="team-rule-run")
            gate = engine.next(state)
            self.assertEqual("requirements-facts", gate.next_node)
            evidence_store.save(
                state.run_id,
                self._attested_evidence(
                    project,
                    state.run_id,
                    "facts-without-rule",
                    kind="source",
                    scope_tags=["flow:team-delivery", "stage:requirements"],
                    contract_refs=[],
                ),
            )
            result = StepResult(
                run_id=state.run_id,
                node_id="requirements-facts",
                status="completed",
                criteria_results=[
                    CriterionResult(
                        "requirements-facts:1", True, ["facts-without-rule"]
                    )
                ],
                outputs=["facts"],
                findings=[],
                open_questions=[],
                requested_transition="continue",
            )

            missing = engine.complete_step(state, result, evidence_store=evidence_store)
            self.assertEqual("retry", missing.decision)
            self.assertIn("requirements-facts:rule-contract", missing.missing_evidence)

            evidence_store.save(
                state.run_id,
                self._attested_evidence(
                    project,
                    state.run_id,
                    "facts-with-rule",
                    kind="source",
                    scope_tags=["flow:team-delivery", "stage:requirements"],
                    contract_refs=["rule:QIN1"],
                ),
            )
            accepted = engine.complete_step(
                state,
                replace(
                    result,
                    criteria_results=[
                        CriterionResult(
                            "requirements-facts:1", True, ["facts-with-rule"]
                        )
                    ],
                ),
                evidence_store=evidence_store,
            )
            self.assertEqual("design-source-snapshot", accepted.next_node)

    def test_incomplete_requirements_retry_without_advancing(self) -> None:
        catalog = load_catalog(ROOT)
        engine = RuntimeEngine(catalog)
        state = engine.start(
            "team-incomplete", self._intent(), run_id="team-incomplete-run"
        )
        engine.next(state)
        gate = engine.complete_step(
            state,
            StepResult(
                run_id=state.run_id,
                node_id="requirements-facts",
                status="completed",
                criteria_results=[],
                outputs=["仍缺少验收事实"],
                findings=[],
                open_questions=["谁确认验收范围？"],
                requested_transition="continue",
            ),
            evidence_store=self._empty_evidence_store(),
        )
        self.assertEqual("retry", gate.decision)
        self.assertEqual("requirements-facts", state.current_node)
        self.assertNotIn("requirements-facts", state.completed_nodes)

    def test_team_quality_gate_requires_the_main_quality_snapshot(self) -> None:
        catalog = load_catalog(ROOT)
        engine = RuntimeEngine(catalog)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            state_store = StateStore(project, ROOT / "schemas")
            evidence_store = EvidenceStore(state_store, _EvidenceVerifier())
            state = engine.start("team-quality", self._intent(), run_id="team-quality-run")
            state.current_node = "quality-gate"
            state.status = "running"
            evidence_store.save(
                state.run_id,
                self._attested_evidence(
                    project,
                    state.run_id,
                    "quality-test",
                    kind="test",
                    scope_tags=["flow:team-delivery", "gate:quality"],
                    contract_refs=["rule:CQ1"],
                ),
            )
            result = StepResult(
                run_id=state.run_id,
                node_id="quality-gate",
                status="completed",
                criteria_results=[
                    CriterionResult("quality-gate:1", True, ["quality-test"])
                ],
                outputs=["quality"],
                findings=[],
                open_questions=[],
                requested_transition="continue",
            )

            gate = engine.complete_step(state, result, evidence_store=evidence_store)
            self.assertEqual("retry", gate.decision)
            self.assertIn("quality-snapshot", gate.missing_evidence)

    def test_trusted_approval_and_external_state_are_required_evidence_kinds(self) -> None:
        catalog = load_catalog(ROOT)
        flow = catalog.flows["team-delivery"]
        nodes = {node.id: node for node in flow.nodes}
        self.assertEqual(
            ["requirements-facts"], nodes["design-source-snapshot"].depends_on
        )
        self.assertEqual(
            ["decision-convergence"], nodes["domain-model"].depends_on
        )
        self.assertEqual(
            ["domain-model"], nodes["requirements-contract"].depends_on
        )
        self.assertIn("外部设计源保持只读", " ".join(nodes["domain-model"].completion_criteria))
        self.assertEqual(
            ["review-package-validation"], nodes["design-source-recheck"].depends_on
        )
        self.assertEqual(
            ["design-source-recheck"], nodes["design-approval"].depends_on
        )
        self.assertTrue(
            any("仅当服务边界" in criterion for criterion in nodes["architecture-design"].completion_criteria)
        )
        self.assertEqual(
            ["review", "approval"], nodes["design-approval"].required_evidence_kinds
        )
        self.assertEqual(
            ["review", "approval"], nodes["code-confirmation"].required_evidence_kinds
        )
        self.assertTrue(
            any(
                "正式 Markdown 走查报告" in criterion
                for criterion in nodes["code-confirmation"].completion_criteria
            )
        )
        self.assertTrue(
            any(
                "代码异味专项" in criterion
                for criterion in nodes["code-confirmation"].completion_criteria
            )
        )
        self.assertEqual(
            ["source", "review", "ci", "approval"],
            nodes["release-readiness"].required_evidence_kinds,
        )
        self.assertEqual(
            ["ci", "external_state"],
            nodes["release-verification"].required_evidence_kinds,
        )
        self.assertEqual(
            ["review", "approval"], nodes["tl-disposition"].required_evidence_kinds
        )

        engine = RuntimeEngine(catalog)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            state_store = StateStore(project, ROOT / "schemas")
            evidence_store = EvidenceStore(state_store, _EvidenceVerifier())
            state = engine.start("team-approval", self._intent(), run_id="team-approval-run")
            state.current_node = "design-approval"
            state.status = "running"
            evidence_store.save(
                state.run_id,
                self._attested_evidence(
                    project,
                    state.run_id,
                    "design-review-only",
                    kind="review",
                    scope_tags=["flow:team-delivery", "gate:design-approval"],
                    contract_refs=["rule:A1"],
                ),
            )
            gate = engine.complete_step(
                state,
                StepResult(
                    run_id=state.run_id,
                    node_id="design-approval",
                    status="completed",
                    criteria_results=[
                        CriterionResult(
                            f"design-approval:{index}", True, ["design-review-only"]
                        )
                        for index in range(1, 4)
                    ],
                    outputs=["reviewed"],
                    findings=[],
                    open_questions=[],
                    requested_transition="continue",
                ),
                evidence_store=evidence_store,
            )
            self.assertEqual("pause_for_approval", gate.decision)
            self.assertEqual("waiting_for_approval", state.status)
            self.assertIn(
                "design-approval:required-kind:approval", gate.missing_evidence
            )

            external_state = engine.start(
                "team-external", self._intent(), run_id="team-external-run"
            )
            external_state.current_node = "release-verification"
            external_state.status = "running"
            evidence_store.save(
                external_state.run_id,
                self._attested_evidence(
                    project,
                    external_state.run_id,
                    "release-ci-only",
                    kind="ci",
                    scope_tags=["flow:team-delivery", "stage:release"],
                    contract_refs=["rule:DG1"],
                ),
            )
            external_gate = engine.complete_step(
                external_state,
                StepResult(
                    run_id=external_state.run_id,
                    node_id="release-verification",
                    status="completed",
                    criteria_results=[
                        CriterionResult(
                            "release-verification:1", True, ["release-ci-only"]
                        )
                    ],
                    outputs=["CI complete"],
                    findings=[],
                    open_questions=[],
                    requested_transition="continue",
                ),
                evidence_store=evidence_store,
            )
            self.assertEqual("pause_for_input", external_gate.decision)
            self.assertEqual("waiting_for_input", external_state.status)
            self.assertIn(
                "release-verification:required-kind:external_state",
                external_gate.missing_evidence,
            )

    def test_code_confirmation_and_release_readiness_pause_for_human_approval(self) -> None:
        catalog = load_catalog(ROOT)
        engine = RuntimeEngine(catalog)
        cases = (
            (
                "code-confirmation",
                ["review"],
                ["flow:team-delivery", "gate:code-confirmation"],
                "rule:A1",
            ),
            (
                "release-readiness",
                ["source", "review", "ci"],
                ["flow:team-delivery", "gate:release-approval"],
                "rule:DG1",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            state_store = StateStore(project, ROOT / "schemas")
            evidence_store = EvidenceStore(state_store, _EvidenceVerifier())
            for node_id, kinds, scope_tags, rule_ref in cases:
                with self.subTest(node_id=node_id):
                    state = engine.start(
                        f"task-{node_id}",
                        self._intent(),
                        run_id=f"run-{node_id}",
                    )
                    state.current_node = node_id
                    state.status = "running"
                    evidence_ids = []
                    for kind in kinds:
                        evidence_id = f"{node_id}-{kind}"
                        evidence_ids.append(evidence_id)
                        evidence_store.save(
                            state.run_id,
                            self._attested_evidence(
                                project,
                                state.run_id,
                                evidence_id,
                                kind=kind,
                                scope_tags=scope_tags,
                                contract_refs=[rule_ref],
                            ),
                        )
                    gate = engine.complete_step(
                        state,
                        StepResult(
                            run_id=state.run_id,
                            node_id=node_id,
                            status="completed",
                            criteria_results=[
                                CriterionResult(
                                    f"{node_id}:{index}", True, evidence_ids
                                )
                                for index in range(
                                    1,
                                    len(
                                        next(
                                            node
                                            for node in catalog.flows["team-delivery"].nodes
                                            if node.id == node_id
                                        ).completion_criteria
                                    )
                                    + 1,
                                )
                            ],
                            outputs=["ready for approval"],
                            findings=[],
                            open_questions=[],
                            requested_transition="continue",
                        ),
                        evidence_store=evidence_store,
                    )
                    self.assertEqual("pause_for_approval", gate.decision)
                    self.assertEqual("waiting_for_approval", state.status)

    def test_optional_specialties_and_rule_candidate_paths_resolve_explicitly(self) -> None:
        catalog = load_catalog(ROOT)
        engine = RuntimeEngine(catalog)
        flow = catalog.flows["team-delivery"]
        node_ids = [node.id for node in flow.nodes]

        state = engine.start("team-optional", self._intent(), run_id="team-optional-run")
        state.current_node = "frontend-design"
        state.status = "running"
        state.completed_nodes = node_ids[: node_ids.index("frontend-design")]
        skipped = engine.complete_step(
            state,
            StepResult(
                run_id=state.run_id,
                node_id="frontend-design",
                status="skipped",
                criteria_results=[],
                outputs=["影响范围不包含前端"],
                findings=[],
                open_questions=[],
                requested_transition="continue",
            ),
            evidence_store=self._empty_evidence_store(),
        )
        self.assertIn("frontend-design", state.skipped_nodes)
        self.assertEqual("database-design", skipped.next_node)

        no_candidate = engine.start(
            "team-no-candidate", self._intent(), run_id="team-no-candidate-run"
        )
        candidate_index = node_ids.index("rule-candidate-quality")
        no_candidate.completed_nodes = node_ids[:candidate_index]
        no_candidate.current_node = "rule-candidate-quality"
        no_candidate.status = "running"
        gate = engine.complete_step(
            no_candidate,
            StepResult(
                run_id=no_candidate.run_id,
                node_id="rule-candidate-quality",
                status="skipped",
                criteria_results=[],
                outputs=["复盘没有产生规范候选"],
                findings=[],
                open_questions=[],
                requested_transition="continue",
            ),
            evidence_store=self._empty_evidence_store(),
        )
        self.assertEqual("tl-disposition", gate.next_node)
        completed = engine.complete_step(
            no_candidate,
            StepResult(
                run_id=no_candidate.run_id,
                node_id="tl-disposition",
                status="skipped",
                criteria_results=[],
                outputs=["没有候选，无需 TL 处置"],
                findings=[],
                open_questions=[],
                requested_transition="continue",
            ),
            evidence_store=self._empty_evidence_store(),
        )
        self.assertEqual("complete", completed.decision)
        self.assertEqual("completed", no_candidate.status)

        candidate = engine.start(
            "team-candidate", self._intent(), run_id="team-candidate-run"
        )
        candidate.completed_nodes = node_ids[:-1]
        candidate.current_node = "tl-disposition"
        candidate.status = "running"
        waiting = engine.complete_step(
            candidate,
            StepResult(
                run_id=candidate.run_id,
                node_id="tl-disposition",
                status="waiting",
                criteria_results=[],
                outputs=["规范候选质量审计已通过"],
                findings=[],
                open_questions=["waiting_for_human_review: TL 接受或拒绝规范候选"],
                requested_transition="pause_for_approval",
            ),
            evidence_store=self._empty_evidence_store(),
        )
        self.assertEqual("pause_for_approval", waiting.decision)
        self.assertEqual("waiting_for_approval", candidate.status)
        self.assertIn("waiting_for_human_review", candidate.next_actions[0])


if __name__ == "__main__":
    unittest.main()
