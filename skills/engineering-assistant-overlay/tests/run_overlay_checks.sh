#!/bin/sh
set -eu

ROOT="/Users/fengtianyangyang/.codex/skills/engineering-assistant-overlay"
WRAPPER="/Users/fengtianyangyang/.codex/skills/engineering-assistant/SKILL.md"
PLUGIN="/Users/fengtianyangyang/.codex/plugins/cache/codex-marketplace-global/engineering-assistant/1.0.0.1"
COUNCIL="/Users/fengtianyangyang/.codex/skills/engineering-assistant-council-integration"
SKILL_CREATOR="/Users/fengtianyangyang/.codex/skills/.system/skill-creator"

python3 "$ROOT/scripts/validate_active_engineering_assistant_capabilities.py"
python3 "$ROOT/scripts/validate_overlay_growth.py"
python3 "$ROOT/scripts/validate_overlay_hierarchy.py"
python3 - "$ROOT" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
script = (root / "scripts/validate_active_engineering_assistant_capabilities.py").read_text()
config = (root / "config.yaml").read_text()
required = re.findall(r'^\s+"([^"]+)": \[', script, re.M)
missing = [item for item in required if f"  - {item}\n" not in config]
if missing:
    print("CONFIG_REQUIRED_CAPABILITIES_OUT_OF_SYNC")
    print("\n".join(missing))
    raise SystemExit(1)
PY
grep -q "validate_active_engineering_assistant_capabilities.py" "$ROOT/SKILL.md"
grep -q "config.yaml" "$ROOT/SKILL.md"
test -f "$ROOT/references/context-scope-routing.md"
test -f "$ROOT/references/overlay-scope-hierarchy.md"
test -f "$ROOT/references/multi-window-coordination.md"
test -f "$ROOT/references/debate-mode.md"
test -f "$ROOT/references/external-capability-assimilation.md"
test -f "$ROOT/references/absorbed-agent-skills.md"
test -f "$ROOT/references/engineering-code-quality-constitution.md"
grep -q 'quality_rule_hierarchy' "$ROOT/references/engineering-code-quality-constitution.md"
grep -q 'spec_verdict' "$ROOT/references/engineering-code-quality-constitution.md"
grep -q 'quality_verdict' "$ROOT/references/engineering-code-quality-constitution.md"
grep -q 'Repository precedent is compatibility evidence, not proof of quality' "$ROOT/references/engineering-code-quality-constitution.md"
grep -q 'Do not use method length' "$ROOT/references/engineering-code-quality-constitution.md"
grep -q 'ENGINEERING_QUALITY_FLOOR_BYPASSED' "$ROOT/references/engineering-code-quality-constitution.md"
test -f "$ROOT/THIRD_PARTY_NOTICES.md"
test -f "$ROOT/registry/absorbed-capabilities.json"
test -f "$ROOT/registry/capability-upgrade-history.json"
test -f "$ROOT/schemas/absorbed_capabilities.schema.json"
test -f "$ROOT/schemas/capability_acceptance_results.schema.json"
test -f "$ROOT/scripts/validate_feedback_pair.py"
test -f "$ROOT/scripts/audit_feedback_corpus.py"
test -f "$COUNCIL/SKILL.md"
test -f "$COUNCIL/config.yaml"
test -f "$COUNCIL/references/council-contract.md"
test -f "$COUNCIL/scripts/validate_council_run.py"
test -f "$COUNCIL/scripts/project_anonymous_review.py"
test -f "$COUNCIL/tests/test_validate_council_run.py"
test -f "$ROOT/schemas/window_registry.schema.json"
test -f "$ROOT/templates/project-overlay.template.json"
test -f "$ROOT/templates/module-overlay.template.json"
test -f "$ROOT/templates/window-plan.template.json"
test -f "$ROOT/templates/window-registry.template.json"
test -f "$ROOT/templates/dispatch-ledger.template.json"
test -f "$PLUGIN/engineering-assistant/standards/plugin-capability-routing-standard.md"
test -f "$PLUGIN/engineering-assistant/registry/plugin-capabilities.json"
test -f "$PLUGIN/engineering-assistant/registry/runtime-compile-policy.json"
test -f "$PLUGIN/engineering-assistant/scripts/validate_runtime_compile_policy.py"
test -f "$PLUGIN/engineering-assistant/scripts/generate_plugin_manifest_review_packet.py"
test -f "$ROOT/scripts/validate_overlay_hierarchy.py"
test -f "$ROOT/scripts/validate_window_registry.py"
test -f "$ROOT/scripts/validate_parallel_dispatch.py"
test -f "$ROOT/project-overlays/projects/bc-lilishop-retail/project-overlay.json"
test -f "$ROOT/project-overlays/projects/bc-lilishop-retail/modules/abk-external-sync.json"
test -f "$ROOT/project-overlays/projects/bc-lilishop-retail/modules/order-promotion-fulfillment.json"
test -f "$ROOT/project-overlays/projects/bc-lilishop-retail/references/l4-entry-real-run-samples.md"
grep -q "Context Scope Routing" "$ROOT/references/context-scope-routing.md"
grep -q "context_scope" "$ROOT/references/context-scope-routing.md"
grep -q "cross-module samples only as labeled hypotheses" "$ROOT/references/context-scope-routing.md"
grep -q "Overlay Scope Hierarchy" "$ROOT/references/overlay-scope-hierarchy.md"
grep -q "project-overlays/projects/<project_slug>/modules/<module_slug>.json" "$ROOT/references/overlay-scope-hierarchy.md"
grep -q "project_overlay_route" "$ROOT/references/overlay-scope-hierarchy.md"
grep -q "Multi-window Coordination" "$ROOT/references/multi-window-coordination.md"
grep -q "threadId" "$ROOT/references/multi-window-coordination.md"
grep -q "not as a subthread" "$ROOT/references/multi-window-coordination.md"
grep -q "required-information-requests.json" "$ROOT/references/multi-window-coordination.md"
grep -q "api_tester" "$ROOT/references/multi-window-coordination.md"
grep -q "module_flow_tester" "$ROOT/references/multi-window-coordination.md"
grep -q "page_acceptance_tester" "$ROOT/references/multi-window-coordination.md"
grep -q "REPEATED_FIX_DIAGNOSTIC_RESET_REQUIRED" "$ROOT/references/multi-window-coordination.md"
grep -q "reuse_registered_window_first" "$ROOT/references/multi-window-coordination.md"
grep -q "window-reconciliation-ledger.json" "$ROOT/references/multi-window-coordination.md"
grep -q "old_window_context_policy=historical_only" "$ROOT/references/multi-window-coordination.md"
grep -q "dispatch_all_ready_before_wait" "$ROOT/references/multi-window-coordination.md"
grep -q "MULTI_WINDOW_PARALLEL_DISPATCH_SKIPPED" "$ROOT/references/multi-window-coordination.md"
grep -q "correction_reviewer" "$ROOT/references/debate-mode.md"
grep -q "two debate rounds" "$ROOT/references/debate-mode.md"
grep -q "DEBATE_MODE_UNBOUNDED" "$ROOT/references/debate-mode.md"
grep -q "engineering-assistant-council-integration" "$ROOT/references/debate-mode.md"
grep -q "Council Boundary" "$ROOT/references/multi-window-coordination.md"
grep -q "COUNCIL_PARALLEL_DISPATCH_SKIPPED" "$ROOT/SKILL.md"
grep -q "COUNCIL_DETERMINISTIC_GATE_OVERRIDE_ATTEMPT" "$ROOT/SKILL.md"
grep -q "external_model_api_enabled=false" "$ROOT/SKILL.md"
grep -q "anonymous_proposal_audit_synthesis" "$COUNCIL/SKILL.md"
grep -q "project_anonymous_review.py" "$COUNCIL/SKILL.md"
grep -q 'recommend' "$COUNCIL/references/council-contract.md"
grep -q "all_spawned_before_wait" "$COUNCIL/references/council-contract.md"
grep -q "single_baseline_proposal" "$COUNCIL/references/council-contract.md"
grep -q "audit_only_no_competing_proposal" "$COUNCIL/references/council-contract.md"
grep -q "all_members_must_cross_review" "$COUNCIL/references/council-contract.md"
grep -q "unresolved_blocking_finding_ids" "$COUNCIL/references/council-contract.md"
grep -q "user_review_required_before_development" "$COUNCIL/references/council-contract.md"
grep -q "development_gate_status" "$COUNCIL/references/council-contract.md"
python3 "$SKILL_CREATOR/scripts/quick_validate.py" "$COUNCIL"
python3 "$COUNCIL/tests/test_validate_council_run.py"
grep -q "required-information-requests.json" "$ROOT/config.yaml"
grep -q "window-reconciliation-ledger.json" "$ROOT/config.yaml"
grep -q "INDEPENDENT_TEST_REQUIRED" "$ROOT/templates/window-registry.template.json"
grep -q "WINDOW_REGISTRY_REUSE_SKIPPED" "$ROOT/templates/window-registry.template.json"
grep -q "STALE_WINDOW_CONTEXT_USED_AS_FACT" "$ROOT/templates/window-registry.template.json"
grep -q "window-registry.json" "$ROOT/config.yaml"
grep -q "multi_window_coordination" "$PLUGIN/engineering-assistant/registry/plugin-capabilities.json"
grep -q "source_layer" "$PLUGIN/engineering-assistant/registry/skills.yaml"
grep -q "runtime_compile" "$PLUGIN/engineering-assistant/registry/skills.yaml"
if grep -q "multi_window_coordination" "$PLUGIN/engineering-assistant/registry/workflows.yaml"; then
  echo "OVERLAY_CONTROL_CAPABILITY_UNEXPECTED_IN_WORKFLOWS"
  exit 1
fi
python3 "$PLUGIN/engineering-assistant/scripts/validate_runtime_compile_policy.py" "$PLUGIN"
tmp_manifest_review="$(mktemp -d)"
python3 "$PLUGIN/engineering-assistant/scripts/generate_plugin_manifest_review_packet.py" --plugin-root "$PLUGIN" --out "$tmp_manifest_review"
test -f "$tmp_manifest_review/manifest-human-review-packet.md"
test -f "$tmp_manifest_review/missing-manifest-metadata.json"
grep -q "waiting_for_human_review" "$tmp_manifest_review/manifest-review-index.json"
python3 "$ROOT/scripts/validate_window_registry.py" "$ROOT/templates/window-registry.template.json"
python3 "$ROOT/scripts/validate_parallel_dispatch.py" "$ROOT/templates/window-plan.template.json" "$ROOT/templates/dispatch-ledger.template.json"
python3 "$ROOT/tests/test_parallel_dispatch_adversarial.py"
if sed 's/"dispatch_method": "concurrent_tool_batch"/"dispatch_method": "sequential_wait_between_workers"/g' "$ROOT/templates/dispatch-ledger.template.json" | python3 "$ROOT/scripts/validate_parallel_dispatch.py" "$ROOT/templates/window-plan.template.json" /dev/stdin; then
  echo "SERIAL_WINDOW_DISPATCH_UNEXPECTEDLY_ACCEPTED"
  exit 1
fi
tmp_serial_plan="$(mktemp -d)"
python3 - "$ROOT/templates/window-plan.template.json" "$tmp_serial_plan" <<'PY'
import json
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text())
plan["planned_windows"] = plan["planned_windows"][:2]
plan["parallel_dispatch_batches"] = []
plan["parallel_dispatch_decision"] = {
    "parallel_opportunity_count": 0,
    "serial_reason": "dependency_not_satisfied",
}
out = Path(sys.argv[2])
(out / "window-plan.json").write_text(json.dumps(plan))
(out / "dispatch-ledger.json").write_text(json.dumps({
    "run_id": plan["run_id"],
    "scheduling_mode": "dependency_aware_parallel",
    "batches": [],
}))
PY
python3 "$ROOT/scripts/validate_parallel_dispatch.py" "$tmp_serial_plan/window-plan.json" "$tmp_serial_plan/dispatch-ledger.json"
python3 "$ROOT/scripts/classify_l4_evidence.py" "$ROOT/tests/minimal/l4_legacy_route" | grep -q '"partial": 1'
tmp_l4_cleanup="$(mktemp -d)"
python3 "$ROOT/scripts/summarize_l4_evidence_cleanup.py" --root "$ROOT/tests/minimal/l4_legacy_route" --out "$tmp_l4_cleanup"
test -f "$tmp_l4_cleanup/l4-evidence-summary.json"
grep -q '"partial": 1' "$tmp_l4_cleanup/l4-evidence-summary.json"
grep -q "BC_RETAIL_DOMAIN_BOUNDARY" "$ROOT/project-overlays/projects/bc-lilishop-retail/project-overlay.json"
grep -q "ABK_ENVIRONMENT_AND_LAYER_GUARD" "$ROOT/project-overlays/projects/bc-lilishop-retail/modules/abk-external-sync.json"
grep -q "ORDER_PROMOTION_SHARED_INVARIANT" "$ROOT/project-overlays/projects/bc-lilishop-retail/modules/order-promotion-fulfillment.json"
test -f "$ROOT/references/overlay-retention-boundary.md"
test -f "$ROOT/references/target-repo-doc-governance.md"
test -f "$ROOT/scripts/validate_overlay_growth.py"
grep -q "Overlay Retention Boundary" "$ROOT/references/overlay-retention-boundary.md"
grep -q "Target Repo Doc Governance" "$ROOT/references/target-repo-doc-governance.md"
grep -q "target-repo-doc-retention-index.json" "$ROOT/references/target-repo-doc-governance.md"
test -f "$ROOT/references/closed-loop-evolution.md"
test -f "$ROOT/references/runtime-and-regression-guards.md"
test -f "$ROOT/references/java-validation-and-branch-sync.md"
test -f "$ROOT/references/self-improvement-evidence.md"
test -f "$ROOT/references/run-evidence-governance.md"
grep -q "Closed-loop Evolution Protocol" "$ROOT/references/closed-loop-evolution.md"
grep -q "runtime-and-regression-guards.md" "$ROOT/SKILL.md"
grep -q "java-validation-and-branch-sync.md" "$ROOT/SKILL.md"
grep -q "self-improvement-evidence.md" "$ROOT/SKILL.md"
grep -q "run-evidence-governance.md" "$ROOT/SKILL.md"
grep -q "FIX_CHAIN_REGRESSION_UNCHECKED" "$ROOT/references/runtime-and-regression-guards.md"
grep -q "JAVA_BRANCH_SYNC_FEATURE_LOSS_UNCHECKED" "$ROOT/references/java-validation-and-branch-sync.md"
grep -q "SKILLOPT_SLEEP_ADOPT_WITHOUT_APPROVAL" "$ROOT/references/self-improvement-evidence.md"
grep -q "CAPABILITY_OUTPUT_NOT_CONSUMED" "$ROOT/references/run-evidence-governance.md"
grep -q "FIX_CHAIN_REGRESSION_UNCHECKED" "$ROOT/SKILL.md"
grep -q "protected_fix_set" "$ROOT/SKILL.md"
grep -q "FIX_CHAIN_REGRESSION_UNCHECKED" "$ROOT/config.yaml"
grep -q "FIX_CHAIN_REGRESSION_UNCHECKED" "$ROOT/scripts/validate_active_engineering_assistant_capabilities.py"
test -f "$ROOT/references/business-config-boundary.md"
grep -q "Business Configuration Boundary" "$ROOT/references/business-config-boundary.md"
grep -q "replace_by_design" "$ROOT/references/business-config-boundary.md"
test -f "$ROOT/references/e2e-test-workflow.md"
grep -q "E2E Test Classifier" "$ROOT/references/e2e-test-workflow.md"
grep -q "pending-flow-continuation" "$ROOT/references/e2e-test-workflow.md"
grep -q "Project Flow Memory" "$ROOT/references/e2e-test-workflow.md"
grep -q "^description: Use when" "$WRAPPER"
python3 "$ROOT/scripts/validate_assistant_run_feedback.py" "$ROOT/tests/minimal/assistant_feedback_must_be_agent_consumed/assistant-run-feedback.json"
tmpdir="$(mktemp -d)"
cp "$ROOT/tests/minimal/assistant_audit_target_repo_edit_forbidden/"*.json "$tmpdir"/
python3 "$ROOT/scripts/generate_assistant_run_feedback.py" "$tmpdir"
grep -q "ASSISTANT_AUDIT_TARGET_REPO_EDIT_FORBIDDEN" "$tmpdir/assistant-run-feedback.json"
python3 "$ROOT/scripts/validate_assistant_run_feedback.py" "$tmpdir/assistant-run-feedback.json"
test -f "$tmpdir/closed-loop-outcome.json"
python3 "$ROOT/scripts/validate_closed_loop_outcome.py" "$tmpdir/closed-loop-outcome.json"
tmpdir="$(mktemp -d)"
cat > "$tmpdir/run_state.json" <<'JSON'
{
  "run_id": "overlay-test-fix-chain-regression",
  "task_summary": "修复 B 时把已修复的 A 改回去了。",
  "gates": [
    {
      "code": "FIX_CHAIN_REGRESSION_UNCHECKED"
    }
  ]
}
JSON
cat > "$tmpdir/runtime-route-decision.json" <<'JSON'
{
  "run_id": "overlay-test-fix-chain-regression",
  "task_kind": "change",
  "evidence_level": "standard",
  "persistence_mode": "ephemeral"
}
JSON
cat > "$tmpdir/artifact-persistence-policy.json" <<'JSON'
{
  "run_id": "overlay-test-fix-chain-regression",
  "target_repo_write_allowed": false,
  "persistence_mode": "ephemeral"
}
JSON
python3 "$ROOT/scripts/generate_assistant_run_feedback.py" "$tmpdir"
grep -q "FIX_CHAIN_REGRESSION_UNCHECKED" "$tmpdir/assistant-run-feedback.json"
grep -q '"overall_status": "blocked"' "$tmpdir/assistant-run-feedback.json"
python3 "$ROOT/scripts/validate_assistant_run_feedback.py" "$tmpdir/assistant-run-feedback.json"
tmpdir="$(mktemp -d)"
cp "$ROOT/tests/minimal/materialized_business_data_source_restriction_forbidden/"*.json "$tmpdir"/
python3 "$ROOT/scripts/generate_assistant_run_feedback.py" "$tmpdir"
grep -q "CUSTOMER_VISIBLE_SOURCE_RESTRICTION_UNJUSTIFIED" "$tmpdir/assistant-run-feedback.json"
python3 "$ROOT/scripts/validate_assistant_run_feedback.py" "$tmpdir/assistant-run-feedback.json"
python3 "$ROOT/scripts/validate_closed_loop_outcome.py" "$tmpdir/closed-loop-outcome.json"
tmpdir="$(mktemp -d)"
cp "$ROOT/tests/minimal/materialized_business_data_source_metadata_internal_allowed/"*.json "$tmpdir"/
python3 "$ROOT/scripts/generate_assistant_run_feedback.py" "$tmpdir"
if grep -q "CUSTOMER_VISIBLE_SOURCE_RESTRICTION_UNJUSTIFIED" "$tmpdir/assistant-run-feedback.json"; then
  echo "UNEXPECTED_CUSTOMER_VISIBLE_SOURCE_RESTRICTION_GATE"
  exit 1
fi
grep -q '"overall_status": "pass"' "$tmpdir/assistant-run-feedback.json"
python3 "$ROOT/scripts/validate_assistant_run_feedback.py" "$tmpdir/assistant-run-feedback.json"
tmpdir="$(mktemp -d)"
cp "$ROOT/tests/minimal/positive_skill_instruction_shape_missing/"*.json "$tmpdir"/
python3 "$ROOT/scripts/generate_assistant_run_feedback.py" "$tmpdir"
grep -q "POSITIVE_SKILL_INSTRUCTION_SHAPE_MISSING" "$tmpdir/assistant-run-feedback.json"
python3 "$ROOT/scripts/validate_assistant_run_feedback.py" "$tmpdir/assistant-run-feedback.json"
tmpdir="$(mktemp -d)"
cp "$ROOT/tests/minimal/positive_skill_instruction_shape_present/"*.json "$tmpdir"/
python3 "$ROOT/scripts/generate_assistant_run_feedback.py" "$tmpdir"
if grep -q "POSITIVE_SKILL_INSTRUCTION_SHAPE_MISSING" "$tmpdir/assistant-run-feedback.json"; then
  echo "UNEXPECTED_POSITIVE_SKILL_INSTRUCTION_SHAPE_GATE"
  exit 1
fi
grep -q '"overall_status": "pass"' "$tmpdir/assistant-run-feedback.json"
python3 "$ROOT/scripts/validate_assistant_run_feedback.py" "$tmpdir/assistant-run-feedback.json"
python3 "$ROOT/scripts/validate_capability_health.py" "$ROOT/tests/minimal/capability-health.json"
python3 "$ROOT/scripts/validate_capability_output_consumption.py" "$ROOT/tests/minimal/capability-invocation-ledger.json" "$ROOT/tests/minimal/capability-output-consumption.json"
assimilation_tmp="$(mktemp -d)"
python3 "$ROOT/scripts/evaluate_absorbed_capabilities.py" \
  "$ROOT/tests/capability-assimilation/historical-regressions.json" \
  --registry "$ROOT/registry/absorbed-capabilities.json" \
  --out "$assimilation_tmp/acceptance-results.json" >/dev/null
python3 "$PLUGIN/engineering-assistant/scripts/validate_absorbed_agent_skills_behavior.py" \
  --out "$assimilation_tmp/behavior-evidence.json" >/dev/null
python3 "$ROOT/scripts/validate_capability_assimilation.py" \
  "$ROOT/registry/absorbed-capabilities.json" \
  "$ROOT/tests/capability-assimilation/capability-overlap-matrix.json" \
  "$assimilation_tmp/acceptance-results.json" \
  --routing-registry "$PLUGIN/engineering-assistant/registry/skill-routing-signals.json" \
  --behavior-evidence "$assimilation_tmp/behavior-evidence.json"
grep -q '"case_count": 28' "$assimilation_tmp/acceptance-results.json"
grep -q '"g0_pass_rate": 1.0' "$assimilation_tmp/acceptance-results.json"
grep -q '"existing_gate_regressions": 0' "$assimilation_tmp/acceptance-results.json"
python3 - "$ROOT/registry/absorbed-capabilities.json" "$assimilation_tmp/router-conflict.json" <<'PY'
import json
import sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
data["router_policy"]["upstream_router_imported"] = True
Path(sys.argv[2]).write_text(json.dumps(data))
PY
if python3 "$ROOT/scripts/validate_capability_assimilation.py" "$assimilation_tmp/router-conflict.json" "$ROOT/tests/capability-assimilation/capability-overlap-matrix.json" "$assimilation_tmp/acceptance-results.json" --routing-registry "$PLUGIN/engineering-assistant/registry/skill-routing-signals.json" --behavior-evidence "$assimilation_tmp/behavior-evidence.json" >"$assimilation_tmp/router-conflict.log"; then
  echo "UPSTREAM_ROUTER_CONFLICT_UNEXPECTEDLY_ACCEPTED"
  exit 1
fi
grep -q "EXTERNAL_CAPABILITY_ROUTER_CONFLICT" "$assimilation_tmp/router-conflict.log"
python3 - "$ROOT/tests/capability-assimilation/capability-overlap-matrix.json" "$assimilation_tmp/incomplete-overlap.json" <<'PY'
import json
import sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
data["decisions"].pop()
Path(sys.argv[2]).write_text(json.dumps(data))
PY
if python3 "$ROOT/scripts/validate_capability_assimilation.py" "$ROOT/registry/absorbed-capabilities.json" "$assimilation_tmp/incomplete-overlap.json" "$assimilation_tmp/acceptance-results.json" --routing-registry "$PLUGIN/engineering-assistant/registry/skill-routing-signals.json" --behavior-evidence "$assimilation_tmp/behavior-evidence.json" >"$assimilation_tmp/incomplete-overlap.log"; then
  echo "INCOMPLETE_CAPABILITY_OVERLAP_UNEXPECTEDLY_ACCEPTED"
  exit 1
fi
grep -q "EXTERNAL_CAPABILITY_OVERLAP_UNCLASSIFIED" "$assimilation_tmp/incomplete-overlap.log"
python3 - "$assimilation_tmp/acceptance-results.json" "$assimilation_tmp/g0-failure.json" <<'PY'
import json
import sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
data["g0_passed_count"] -= 1
data["g0_pass_rate"] = data["g0_passed_count"] / data["g0_case_count"]
Path(sys.argv[2]).write_text(json.dumps(data))
PY
if python3 "$ROOT/scripts/validate_capability_assimilation.py" "$ROOT/registry/absorbed-capabilities.json" "$ROOT/tests/capability-assimilation/capability-overlap-matrix.json" "$assimilation_tmp/g0-failure.json" --routing-registry "$PLUGIN/engineering-assistant/registry/skill-routing-signals.json" --behavior-evidence "$assimilation_tmp/behavior-evidence.json" >"$assimilation_tmp/g0-failure.log"; then
  echo "G0_FAILURE_UNEXPECTEDLY_ACCEPTED"
  exit 1
fi
grep -q "EXTERNAL_CAPABILITY_ACCEPTANCE_FAILED" "$assimilation_tmp/g0-failure.log"
python3 - "$ROOT/registry/absorbed-capabilities.json" "$assimilation_tmp/version-mismatch.json" <<'PY'
import json
import sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
data["local_version"] = "1.0.1"
Path(sys.argv[2]).write_text(json.dumps(data))
PY
if python3 "$ROOT/scripts/validate_capability_assimilation.py" "$assimilation_tmp/version-mismatch.json" "$ROOT/tests/capability-assimilation/capability-overlap-matrix.json" "$assimilation_tmp/acceptance-results.json" --routing-registry "$PLUGIN/engineering-assistant/registry/skill-routing-signals.json" --behavior-evidence "$assimilation_tmp/behavior-evidence.json" >"$assimilation_tmp/version-mismatch.log"; then
  echo "VERSION_MISMATCH_UNEXPECTEDLY_ACCEPTED"
  exit 1
fi
grep -q "EXTERNAL_CAPABILITY_VERSION_UPGRADE_UNVERIFIED" "$assimilation_tmp/version-mismatch.log"
feedback_pair_tmp="$(mktemp -d)"
cp "$ROOT/tests/minimal/positive_skill_instruction_shape_present/"*.json "$feedback_pair_tmp/"
python3 "$ROOT/scripts/generate_assistant_run_feedback.py" "$feedback_pair_tmp" >/dev/null
python3 "$ROOT/scripts/validate_feedback_pair.py" "$feedback_pair_tmp"
feedback_corpus_tmp="$(mktemp -d)"
mkdir -p "$feedback_corpus_tmp/complete" "$feedback_corpus_tmp/feedback-only"
cp "$feedback_pair_tmp/assistant-run-feedback.json" "$feedback_corpus_tmp/complete/"
cp "$feedback_pair_tmp/closed-loop-outcome.json" "$feedback_corpus_tmp/complete/"
cp "$feedback_pair_tmp/assistant-run-feedback.json" "$feedback_corpus_tmp/feedback-only/"
python3 "$ROOT/scripts/audit_feedback_corpus.py" "$feedback_corpus_tmp" --out "$feedback_corpus_tmp/audit.json" >/dev/null
grep -q '"paired_with_closed_loop": 1' "$feedback_corpus_tmp/audit.json"
grep -q '"status": "warn"' "$feedback_corpus_tmp/audit.json"
rm "$feedback_pair_tmp/closed-loop-outcome.json"
if python3 "$ROOT/scripts/validate_feedback_pair.py" "$feedback_pair_tmp" >"$feedback_pair_tmp/missing-pair.log" 2>&1; then
  echo "MISSING_CLOSED_LOOP_PAIR_UNEXPECTEDLY_ACCEPTED"
  exit 1
fi
grep -q "CLOSED_LOOP_OUTCOME_NOT_RECORDED" "$feedback_pair_tmp/missing-pair.log"

echo "VALID_ENGINEERING_ASSISTANT_OVERLAY"
