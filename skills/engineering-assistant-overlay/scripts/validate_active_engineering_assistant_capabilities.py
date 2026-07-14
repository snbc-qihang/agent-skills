#!/usr/bin/env python3
"""Validate active Engineering Assistant capability sources.

The check accepts capabilities provided by either the cached marketplace plugin
or this durable overlay. It fails only when neither source provides a required
capability marker.
"""

from pathlib import Path
import sys

ACTIVE = Path("/Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1")
OVERLAY = Path("/Users/fengtianyangyang/.codex/skills/engineering-assistant-overlay")
COUNCIL = Path("/Users/fengtianyangyang/.codex/skills/engineering-assistant-council-integration")

REQUIRED = {
    "assistant-run-feedback": ["assistant-run-feedback", "assistant_run_feedback", "validate_assistant_run_feedback.py"],
    "ASSISTANT_FEEDBACK_NOT_GENERATED": ["ASSISTANT_FEEDBACK_NOT_GENERATED"],
    "ASSISTANT_FEEDBACK_NOT_CONSUMED_BY_AGENT": ["ASSISTANT_FEEDBACK_NOT_CONSUMED_BY_AGENT"],
    "CLOSED_LOOP_OUTCOME_NOT_RECORDED": ["CLOSED_LOOP_OUTCOME_NOT_RECORDED", "closed_loop_outcome", "closed-loop-outcome"],
    "NEXT_RUN_FEEDBACK_NOT_CONSUMED": ["NEXT_RUN_FEEDBACK_NOT_CONSUMED", "next_run_feedback_consumed"],
    "ASSISTANT_RUN_ARTIFACT_INTAKE_SKIPPED": ["ASSISTANT_RUN_ARTIFACT_INTAKE_SKIPPED", "Run artifact feedback intake"],
    "TRAJECTORY_DISTILLATION_CANDIDATE_MISSING": ["TRAJECTORY_DISTILLATION_CANDIDATE_MISSING", "trajectory_distillation_candidate"],
    "SKILL_GATE_COMPRESSION_NOT_EVALUATED": ["SKILL_GATE_COMPRESSION_NOT_EVALUATED", "skill_gate_compression_review"],
    "REWARD_SIGNAL_NOT_RECORDED": ["REWARD_SIGNAL_NOT_RECORDED", "reward_signal_record"],
    "EXTERNAL_EVIDENCE_STATUS_UNCLASSIFIED": ["EXTERNAL_EVIDENCE_STATUS_UNCLASSIFIED", "external_evidence_status"],
    "INDEPENDENT_REVIEW_ENFORCEMENT_MISSING": ["INDEPENDENT_REVIEW_ENFORCEMENT_MISSING", "independent_review_enforcement"],
    "PROJECT_LONG_MEMORY_NOT_UPDATED": ["PROJECT_LONG_MEMORY_NOT_UPDATED", "project_long_memory_candidate"],
    "CONTEXT_SCOPE_UNCLASSIFIED": ["CONTEXT_SCOPE_UNCLASSIFIED", "context_scope_map", "context-scope-routing.md"],
    "CONTEXT_LOAD_PLAN_MISSING": ["CONTEXT_LOAD_PLAN_MISSING", "context_load_plan"],
    "CROSS_MODULE_CONTEXT_POLLUTION": ["CROSS_MODULE_CONTEXT_POLLUTION", "cross_module_contamination_guard"],
    "SCOPED_FACT_PACKET_MISSING": ["SCOPED_FACT_PACKET_MISSING", "scoped_fact_packet"],
    "CONTEXT_UNDERSTANDING_BEFORE_CHANGE_MISSING": ["CONTEXT_UNDERSTANDING_BEFORE_CHANGE_MISSING", "Before-edit operating protocol"],
    "CHANGE_CONTEXT_LEVEL_UNCLASSIFIED": ["CHANGE_CONTEXT_LEVEL_UNCLASSIFIED", "context_level"],
    "CHANGED_FACT_UNIDENTIFIED": ["CHANGED_FACT_UNIDENTIFIED", "changed_fact"],
    "PRODUCER_CONSUMER_MAP_MISSING": ["PRODUCER_CONSUMER_MAP_MISSING", "nearest_consumers"],
    "PROTECTED_INVARIANT_MISSING": ["PROTECTED_INVARIANT_MISSING", "protected_behavior"],
    "VERIFICATION_PLAN_TOO_LOCAL": ["VERIFICATION_PLAN_TOO_LOCAL", "smallest_verification"],
    "ROLLBACK_OR_DISABLE_PATH_MISSING": ["ROLLBACK_OR_DISABLE_PATH_MISSING", "rollback_or_disable_path"],
    "INTERNAL_GATE_LEAKED_TO_USER": ["INTERNAL_GATE_LEAKED_TO_USER", "internal_gate_leak_check"],
    "USER_BURDENED_WITH_AGENT_CHECKLIST": ["USER_BURDENED_WITH_AGENT_CHECKLIST", "USER_BURDENED_WITH_AGENT_CHECKLIST"],
    "UNNECESSARY_USER_QUESTION": ["UNNECESSARY_USER_QUESTION", "user_question_minimized"],
    "SELF_IMPROVEMENT_ADDED_CONCEPT_WITHOUT_EXECUTION_PATH": ["SELF_IMPROVEMENT_ADDED_CONCEPT_WITHOUT_EXECUTION_PATH", "execution_path_added"],
    "RULE_COMPRESSION_SKIPPED": ["RULE_COMPRESSION_SKIPPED", "rule_compression_review"],
    "FAST_PATH_OR_STOP_CONDITION_MISSING": ["FAST_PATH_OR_STOP_CONDITION_MISSING", "FAST_PATH_OR_STOP_CONDITION_MISSING"],
    "OVERLAY_LAYER_UNCLASSIFIED": ["OVERLAY_LAYER_UNCLASSIFIED", "overlay_layer", "overlay-scope-hierarchy.md"],
    "PROJECT_MODULE_OVERLAY_ROUTE_MISSING": ["PROJECT_MODULE_OVERLAY_ROUTE_MISSING", "project_overlay_route"],
    "PROJECT_SPECIFIC_RULE_IN_GLOBAL_OVERLAY": ["PROJECT_SPECIFIC_RULE_IN_GLOBAL_OVERLAY", "project-specific content is added to global overlay"],
    "multi_window_coordination": ["multi_window_coordination", "multi-window-coordination.md", "validate_window_registry.py", "validate_parallel_dispatch.py"],
    "EXPLICIT_WINDOW_CREATION_REQUIRED": ["EXPLICIT_WINDOW_CREATION_REQUIRED", "explicit user authorization"],
    "REQUIRED_INFORMATION_REQUESTS_MISSING": ["REQUIRED_INFORMATION_REQUESTS_MISSING", "required-information-requests.json"],
    "WINDOW_REGISTRY_MISSING": ["WINDOW_REGISTRY_MISSING", "window-registry.json"],
    "WINDOW_SCOPE_UNCLASSIFIED": ["WINDOW_SCOPE_UNCLASSIFIED", "module_scope"],
    "WINDOW_NAME_MISSING": ["WINDOW_NAME_MISSING", "name"],
    "BUSINESS_REVIEW_PENDING": ["BUSINESS_REVIEW_PENDING", "business_reviewer"],
    "DESIGN_REVIEW_REQUIRED": ["DESIGN_REVIEW_REQUIRED", "design_reviewer"],
    "REQUIREMENT_FREEZE_REQUIRED": ["REQUIREMENT_FREEZE_REQUIRED", "draft -> reviewing -> approved"],
    "API_CONTRACT_REQUIRED": ["API_CONTRACT_REQUIRED", "api-contract.md"],
    "TRACEABILITY_MATRIX_REQUIRED": ["TRACEABILITY_MATRIX_REQUIRED", "traceability-matrix.json"],
    "DEVELOPER_CONFIRMATION_REQUIRED": ["DEVELOPER_CONFIRMATION_REQUIRED", "Developer windows must confirm scope"],
    "INDEPENDENT_TEST_REQUIRED": ["INDEPENDENT_TEST_REQUIRED", "api_tester", "module_flow_tester", "page_acceptance_tester"],
    "SELF_REVIEW_FORBIDDEN": ["SELF_REVIEW_FORBIDDEN", "cannot review itself"],
    "MULTI_WINDOW_FILE_CONFLICT_UNCHECKED": ["MULTI_WINDOW_FILE_CONFLICT_UNCHECKED", "single writer per file"],
    "MULTI_WINDOW_PARALLEL_DISPATCH_SKIPPED": ["MULTI_WINDOW_PARALLEL_DISPATCH_SKIPPED", "dispatch_all_ready_before_wait", "concurrent_tool_batch"],
    "WORKER_WINDOW_OUTPUT_NOT_CONSUMED": ["WORKER_WINDOW_OUTPUT_NOT_CONSUMED", "Worker outputs must be read and consumed"],
    "WINDOW_REGISTRY_REUSE_SKIPPED": ["WINDOW_REGISTRY_REUSE_SKIPPED", "reuse_registered_window_first"],
    "WINDOW_REPLACEMENT_NOT_RECORDED": ["WINDOW_REPLACEMENT_NOT_RECORDED", "replacement"],
    "STALE_WINDOW_CONTEXT_USED_AS_FACT": ["STALE_WINDOW_CONTEXT_USED_AS_FACT", "historical_only"],
    "debate_mode": ["debate-mode.md", "correction_reviewer", "two debate rounds"],
    "DEBATE_MODE_UNBOUNDED": ["DEBATE_MODE_UNBOUNDED", "two debate rounds"],
    "DEBATE_CORRECTION_REVIEWER_MISSING": ["DEBATE_CORRECTION_REVIEWER_MISSING", "correction_reviewer"],
    "DEBATE_BLOCKING_OBJECTION_UNCLASSIFIED": ["DEBATE_BLOCKING_OBJECTION_UNCLASSIFIED", "blocking objections"],
    "council_mode": ["engineering-assistant-council-integration", "anonymous_proposal_audit_synthesis", "validate_council_run.py"],
    "COUNCIL_PARALLEL_DISPATCH_SKIPPED": ["COUNCIL_PARALLEL_DISPATCH_SKIPPED", "all_spawned_before_wait"],
    "bounded_multi_agent_deliberation": ["controller_relayed_proposal_audit", "single_baseline_proposal", "user_review_required_before_development"],
    "COUNCIL_DELIBERATION_MISSING": ["COUNCIL_DELIBERATION_MISSING", "competing plans", "final proposal"],
    "COUNCIL_UNRESOLVED_BLOCKERS": ["COUNCIL_UNRESOLVED_BLOCKERS", "unresolved_blocking_finding_ids"],
    "COUNCIL_DETERMINISTIC_GATE_OVERRIDE_ATTEMPT": ["COUNCIL_DETERMINISTIC_GATE_OVERRIDE_ATTEMPT", "deterministic_gate_override"],
    "OVERLAY_COMPACTION_REVIEW_MISSING": ["OVERLAY_COMPACTION_REVIEW_MISSING", "overlay_compaction_review", "overlay-retention-boundary.md"],
    "OVERLAY_SIZE_BUDGET_EXCEEDED": ["OVERLAY_SIZE_BUDGET_EXCEEDED", "overlay_size_budget", "validate_overlay_growth.py"],
    "RUN_ARTIFACT_RETENTION_UNREVIEWED": ["RUN_ARTIFACT_RETENTION_UNREVIEWED", "run_artifact_retention_review"],
    "RECORD_FILE_ROTATION_MISSING": ["RECORD_FILE_ROTATION_MISSING", "record_file_rotation"],
    "ACTIVE_ENGINEERING_ASSISTANT_CAPABILITY_MISSING": ["ACTIVE_ENGINEERING_ASSISTANT_CAPABILITY_MISSING"],
    "CAPABILITY_OUTPUT_NOT_CONSUMED": ["CAPABILITY_OUTPUT_NOT_CONSUMED", "capability_output_consumption"],
    "CAPABILITY_OUTPUT_NOT_RECORDED": ["CAPABILITY_OUTPUT_NOT_RECORDED"],
    "CAPABILITY_HEALTH_NOT_CHECKED": ["CAPABILITY_HEALTH_NOT_CHECKED", "capability_health"],
    "CHANGE_VERIFICATION_EVIDENCE_MISSING": ["CHANGE_VERIFICATION_EVIDENCE_MISSING"],
    "PROCESS_DOCUMENTATION_POLLUTION": ["PROCESS_DOCUMENTATION_POLLUTION"],
    "TARGET_REPO_ARTIFACT_POLLUTION": ["TARGET_REPO_ARTIFACT_POLLUTION"],
    "TARGET_REPO_DOC_PURPOSE_UNCLASSIFIED": ["TARGET_REPO_DOC_PURPOSE_UNCLASSIFIED", "target-repo-doc-retention-index.json"],
    "TARGET_REPO_DOC_CLEANUP_WITHOUT_APPROVAL": ["TARGET_REPO_DOC_CLEANUP_WITHOUT_APPROVAL", "explicit user approval"],
    "PROCESS_MD_WRITTEN_TO_PROJECT_DOCS": ["PROCESS_MD_WRITTEN_TO_PROJECT_DOCS", "process Markdown"],
    "ephemeral_artifact_default": ["run-artifacts/engineering-assistant", "ephemeral"],
    "RUNTIME_ROUTE_NOT_SELECTED": ["RUNTIME_ROUTE_NOT_SELECTED"],
    "NON_STANDARD_RUNTIME_ROUTE": ["NON_STANDARD_RUNTIME_ROUTE"],
    "ASSISTANT_AUDIT_TARGET_REPO_EDIT_FORBIDDEN": ["ASSISTANT_AUDIT_TARGET_REPO_EDIT_FORBIDDEN", "assistant_rule_or_capability_audit", "explicit_project_code_change_requested"],
    "WINDOW_CONTEXT_NOT_CONSUMED": ["WINDOW_CONTEXT_NOT_CONSUMED", "window_context_summary"],
    "BRANCH_RUNTIME_EVIDENCE_MISSING": ["BRANCH_RUNTIME_EVIDENCE_MISSING", "rev-parse", "served source"],
    "ACTIVE_RUNTIME_PROJECT_UNVERIFIED": ["ACTIVE_RUNTIME_PROJECT_UNVERIFIED", "active runtime project"],
    "DECLARED_WORKSPACE_MISSING": ["DECLARED_WORKSPACE_MISSING"],
    "WORKSPACE_RECOVERY_NOT_ATTEMPTED": ["WORKSPACE_RECOVERY_NOT_ATTEMPTED", "workspace-recovery"],
    "WORKSPACE_RECOVERY_NO_CANDIDATE": ["WORKSPACE_RECOVERY_NO_CANDIDATE", "workspace_candidate"],
    "WORKSPACE_RECOVERY_SELECTED_WITHOUT_EVIDENCE": ["WORKSPACE_RECOVERY_SELECTED_WITHOUT_EVIDENCE", "selected_workspace"],
    "VALIDATION_OUTPUT_NOT_CLASSIFIED": ["VALIDATION_OUTPUT_NOT_CLASSIFIED", "blocking_errors", "final_status"],
    "ABK_ENVIRONMENT_GUARD_MISSING": ["ABK_ENVIRONMENT_GUARD_MISSING", "ABK test environment"],
    "DATA_SOURCE_LAYER_UNLABELED": ["DATA_SOURCE_LAYER_UNLABELED", "abk_real_db", "abk_mapping_db"],
    "MUTATION_TARGET_NOT_CONFIRMED": ["MUTATION_TARGET_NOT_CONFIRMED", "exact target identity"],
    "CUSTOMER_VISIBLE_SOURCE_RESTRICTION_UNJUSTIFIED": ["CUSTOMER_VISIBLE_SOURCE_RESTRICTION_UNJUSTIFIED", "materialized_to_business_tables", "customer_visible_source_restrictions"],
    "SKILLOPT_SLEEP_GATE_NOT_RECORDED": ["SKILLOPT_SLEEP_GATE_NOT_RECORDED", "SkillOpt-Sleep gate record"],
    "SKILLOPT_SLEEP_ADOPT_WITHOUT_APPROVAL": ["SKILLOPT_SLEEP_ADOPT_WITHOUT_APPROVAL", "explicit user approval before `adopt`"],
    "SKILLOPT_SLEEP_CONTEXT_FALLBACK_NOT_RUN": ["SKILLOPT_SLEEP_CONTEXT_FALLBACK_NOT_RUN", "--source codex --scope all"],
    "SCOPE_GUARD_LEGACY_DEBT_UNLABELED": ["SCOPE_GUARD_LEGACY_DEBT_UNLABELED", "touched_scope_gate", "full_scope_gate", "legacy_debt"],
    "REPEATED_FIX_SURFACE_ONLY": ["REPEATED_FIX_SURFACE_ONLY", "surface_map", "symptom_history"],
    "REGRESSION_PRESERVATION_GATE_MISSING": ["REGRESSION_PRESERVATION_GATE_MISSING", "known_good_preservation", "regression_gate"],
    "REPEATED_FIX_RUNTIME_STATE_UNCLASSIFIED": ["REPEATED_FIX_RUNTIME_STATE_UNCLASSIFIED", "stale runtime", "cache"],
    "FIX_CHAIN_REGRESSION_UNCHECKED": ["FIX_CHAIN_REGRESSION_UNCHECKED", "protected_fix_set", "regression_survival_gate"],
    "UNIVERSAL_E2E_TEST_WORKFLOW_MISSING": ["UNIVERSAL_E2E_TEST_WORKFLOW_MISSING", "e2e-test-workflow.md"],
    "E2E_TEST_CLASSIFIER_SKIPPED": ["E2E_TEST_CLASSIFIER_SKIPPED", "NO_E2E", "LIGHT_FLOW", "FULL_E2E"],
    "E2E_SCENARIO_CONTRACT_UNCONFIRMED": ["E2E_SCENARIO_CONTRACT_UNCONFIRMED", "scenario-contract"],
    "E2E_RUNTIME_CONTINUATION_GATE_MISSING": ["E2E_RUNTIME_CONTINUATION_GATE_MISSING", "pending-flow-continuation", "pending-final-full-e2e-retest"],
    "PROJECT_FLOW_MEMORY_NOT_RECORDED": ["PROJECT_FLOW_MEMORY_NOT_RECORDED", "Project Flow Memory"],
    "JAVA_COMPILE_FIX_SCOPE_UNCLASSIFIED": ["JAVA_COMPILE_FIX_SCOPE_UNCLASSIFIED", "compile_error_clusters", "Java compile-fix discipline"],
    "JAVA_BRANCH_SYNC_VALIDATION_MISSING": ["JAVA_BRANCH_SYNC_VALIDATION_MISSING", "branch_sync_map", "branch_touched_scope_gate"],
    "JAVA_BRANCH_SYNC_FEATURE_LOSS_UNCHECKED": ["JAVA_BRANCH_SYNC_FEATURE_LOSS_UNCHECKED", "feature_preservation_gate", "destination_before_sha"],
    "DESIGN_BEFORE_CODE_GATE_MISSING": ["DESIGN_BEFORE_CODE_GATE_MISSING", "design_intake"],
    "CODE_DESIGN_GATE_MISSING": ["CODE_DESIGN_GATE_MISSING", "code_design_plan"],
    "BUSINESS_CODE_PILEUP_UNCHECKED": ["BUSINESS_CODE_PILEUP_UNCHECKED", "business_code_pileup_check"],
    "engineering_quality_constitution": ["Engineering Code Quality Constitution", "quality_rule_hierarchy", "spec_verdict", "quality_verdict"],
    "ENGINEERING_QUALITY_FLOOR_BYPASSED": ["ENGINEERING_QUALITY_FLOOR_BYPASSED", "quality_rule_hierarchy"],
    "DESIGN_PATTERN_DECISION_MISSING": ["DESIGN_PATTERN_DECISION_MISSING", "design_pattern_decision"],
    "OVER_DESIGN_BOUNDARY_UNCHECKED": ["OVER_DESIGN_BOUNDARY_UNCHECKED", "over_design_boundary"],
    "JAVA_VERSION_FEATURE_DECISION_MISSING": ["JAVA_VERSION_FEATURE_DECISION_MISSING", "java_version_feature_decision"],
    "FRAMEWORK_REUSE_NOT_EVALUATED": ["FRAMEWORK_REUSE_NOT_EVALUATED", "framework_reuse_decision"],
    "FRAMEWORK_INTEGRATION_NOT_EVALUATED": ["FRAMEWORK_INTEGRATION_NOT_EVALUATED", "framework_integration_decision"],
    "API_PERFORMANCE_BUDGET_MISSING": ["API_PERFORMANCE_BUDGET_MISSING", "performance_budget"],
    "FLOW_PERFORMANCE_REGRESSION_UNCHECKED": ["FLOW_PERFORMANCE_REGRESSION_UNCHECKED", "flow_performance_budget"],
    "BUSINESS_REDUNDANCY_BOUNDARY_UNCHECKED": ["BUSINESS_REDUNDANCY_BOUNDARY_UNCHECKED", "business_redundancy_boundary"],
    "PRODUCTION_PERFORMANCE_INCIDENT_UNTRIAGED": ["PRODUCTION_PERFORMANCE_INCIDENT_UNTRIAGED", "production rollback"],
    "DOMAIN_BOUNDARY_UNCLASSIFIED": ["DOMAIN_BOUNDARY_UNCLASSIFIED", "domain_boundary"],
    "FRONTEND_BACKEND_RESPONSIBILITY_UNCLASSIFIED": ["FRONTEND_BACKEND_RESPONSIBILITY_UNCLASSIFIED", "frontend_backend_responsibility"],
    "SYNC_DATA_USABILITY_NOT_VERIFIED": ["SYNC_DATA_USABILITY_NOT_VERIFIED", "sync_usability_evidence", "sync-written-but-not-usable"],
    "DEVELOPER_REVIEWER_NOT_SEPARATED": ["DEVELOPER_REVIEWER_NOT_SEPARATED", "developer_review_separation", "independent_reviewed"],
    "REPEATED_FIX_DIAGNOSTIC_RESET_REQUIRED": ["REPEATED_FIX_DIAGNOSTIC_RESET_REQUIRED", "diagnostic_reset"],
    "GIT_CONFLICT_FEATURE_PRESERVATION_UNCHECKED": ["GIT_CONFLICT_FEATURE_PRESERVATION_UNCHECKED", "conflict_feature_preservation"],
    "CONFIG_NECESSITY_UNREVIEWED": ["CONFIG_NECESSITY_UNREVIEWED", "config_necessity_review", "business-config-boundary.md"],
    "POSITIVE_SKILL_INSTRUCTION_SHAPE_MISSING": ["POSITIVE_SKILL_INSTRUCTION_SHAPE_MISSING", "positive_target_behavior_present", "completion_checks_present"],
    "external_capability_assimilation": ["External Capability Assimilation", "absorbed-capabilities.json", "validate_capability_assimilation.py"],
    "EXTERNAL_CAPABILITY_GAP_NOT_PROVEN": ["EXTERNAL_CAPABILITY_GAP_NOT_PROVEN"],
    "EXTERNAL_CAPABILITY_ROUTER_CONFLICT": ["EXTERNAL_CAPABILITY_ROUTER_CONFLICT", "sole_entrypoint", "sole_gate_owner"],
    "EXTERNAL_CAPABILITY_OVERLAP_UNCLASSIFIED": ["EXTERNAL_CAPABILITY_OVERLAP_UNCLASSIFIED", "capability-overlap-matrix.json"],
    "EXTERNAL_CAPABILITY_GATE_LEVEL_MISSING": ["EXTERNAL_CAPABILITY_GATE_LEVEL_MISSING", "G0", "G1", "G2"],
    "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED": ["EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED", "capability_acceptance"],
    "EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED": ["EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED", "explicit_local_version_upgrade_after_audit"],
}

PREFER_OVERLAY_SOURCE = {
    "engineering_quality_constitution",
    "ENGINEERING_QUALITY_FLOOR_BYPASSED",
    "multi_window_coordination",
    "external_capability_assimilation",
    "EXTERNAL_CAPABILITY_GAP_NOT_PROVEN",
    "EXTERNAL_CAPABILITY_ROUTER_CONFLICT",
    "EXTERNAL_CAPABILITY_OVERLAP_UNCLASSIFIED",
    "EXTERNAL_CAPABILITY_GATE_LEVEL_MISSING",
    "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED",
    "EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED",
}

PREFER_LOCAL_SKILL_SOURCE = {
    "council_mode",
    "COUNCIL_PARALLEL_DISPATCH_SKIPPED",
    "COUNCIL_DETERMINISTIC_GATE_OVERRIDE_ATTEMPT",
}

STRUCTURED_SOURCE = {
    "assistant-run-feedback": "overlay",
    "ASSISTANT_FEEDBACK_NOT_GENERATED": "overlay",
    "ASSISTANT_FEEDBACK_NOT_CONSUMED_BY_AGENT": "overlay",
    "CLOSED_LOOP_OUTCOME_NOT_RECORDED": "overlay",
    "NEXT_RUN_FEEDBACK_NOT_CONSUMED": "overlay",
    "ASSISTANT_RUN_ARTIFACT_INTAKE_SKIPPED": "overlay",
    "TRAJECTORY_DISTILLATION_CANDIDATE_MISSING": "overlay",
    "SKILL_GATE_COMPRESSION_NOT_EVALUATED": "overlay",
    "REWARD_SIGNAL_NOT_RECORDED": "overlay",
    "EXTERNAL_EVIDENCE_STATUS_UNCLASSIFIED": "overlay",
    "INDEPENDENT_REVIEW_ENFORCEMENT_MISSING": "overlay",
    "PROJECT_LONG_MEMORY_NOT_UPDATED": "overlay",
    "engineering_quality_constitution": "overlay",
    "ENGINEERING_QUALITY_FLOOR_BYPASSED": "overlay",
    "multi_window_coordination": "overlay",
    "debate_mode": "overlay",
    "council_mode": "local_skill",
    "COUNCIL_PARALLEL_DISPATCH_SKIPPED": "local_skill",
    "bounded_multi_agent_deliberation": "local_skill",
    "COUNCIL_DELIBERATION_MISSING": "local_skill",
    "COUNCIL_UNRESOLVED_BLOCKERS": "local_skill",
    "COUNCIL_DETERMINISTIC_GATE_OVERRIDE_ATTEMPT": "local_skill",
    "external_capability_assimilation": "overlay",
    "EXTERNAL_CAPABILITY_GAP_NOT_PROVEN": "overlay",
    "EXTERNAL_CAPABILITY_ROUTER_CONFLICT": "overlay",
    "EXTERNAL_CAPABILITY_OVERLAP_UNCLASSIFIED": "overlay",
    "EXTERNAL_CAPABILITY_GATE_LEVEL_MISSING": "overlay",
    "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED": "overlay",
    "EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED": "overlay",
}


def collect_text(root):
    chunks = []
    if not root.exists():
        return ""
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".yaml", ".yml", ".py"}:
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
            chunks.append(str(path))
        except Exception:
            pass
    return "\n".join(chunks)


def main():
    active_text = collect_text(ACTIVE)
    overlay_text = collect_text(OVERLAY)
    council_text = collect_text(COUNCIL)
    missing = []
    report = []
    structured_count = 0
    legacy_count = 0
    for capability, markers in REQUIRED.items():
        active_hit = any(marker in active_text for marker in markers)
        overlay_hit = any(marker in overlay_text for marker in markers)
        council_hit = any(marker in council_text for marker in markers)
        expected_source = STRUCTURED_SOURCE.get(capability)
        expected_hit = {
            "active_plugin": active_hit,
            "overlay": overlay_hit,
            "local_skill": council_hit,
        }.get(expected_source, False)
        if expected_source:
            structured_count += 1
            if expected_hit:
                report.append(f"{capability}: provided_by={expected_source} source_resolution=structured")
            else:
                missing.append(capability)
                report.append(f"{capability}: missing expected_source={expected_source} source_resolution=structured")
        elif capability in PREFER_LOCAL_SKILL_SOURCE and council_hit:
            legacy_count += 1
            report.append(f"{capability}: provided_by=local_skill source_resolution=legacy_marker_scan")
        elif capability in PREFER_OVERLAY_SOURCE and overlay_hit:
            legacy_count += 1
            report.append(f"{capability}: provided_by=overlay source_resolution=legacy_marker_scan")
        elif active_hit:
            legacy_count += 1
            report.append(f"{capability}: provided_by=active_plugin source_resolution=legacy_marker_scan")
        elif overlay_hit:
            legacy_count += 1
            report.append(f"{capability}: provided_by=overlay source_resolution=legacy_marker_scan")
        else:
            missing.append(capability)
            report.append(f"{capability}: missing source_resolution=legacy_marker_scan")
    if missing:
        print("INVALID_ACTIVE_ENGINEERING_ASSISTANT_CAPABILITIES")
        for line in report:
            print(line)
        print("missing=" + ",".join(missing), file=sys.stderr)
        return 1
    print("VALID_ACTIVE_ENGINEERING_ASSISTANT_CAPABILITIES")
    for line in report:
        print(line)
    print(f"structured_sources={structured_count}")
    print(f"legacy_marker_sources={legacy_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
