#!/usr/bin/env python3
"""Validate dependency-aware parallel window planning and dispatch evidence."""

import json
import sys
from datetime import datetime
from pathlib import Path

SERIAL_REASONS = {
    "dependency_not_satisfied",
    "overlapping_write_scope_without_isolation",
    "shared_contract_single_owner",
    "runtime_concurrency_limit",
}


def fail(message):
    print(f"INVALID_PARALLEL_DISPATCH: {message}", file=sys.stderr)
    return 1


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_time(value, field):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    if parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone offset")
    return parsed


def validate_plan(plan):
    if plan.get("capability_id") != "multi_window_coordination":
        raise ValueError("plan capability_id must be multi_window_coordination")

    policy = plan.get("scheduling_policy", {})
    if policy.get("mode") != "dependency_aware_parallel":
        raise ValueError("scheduling_policy.mode must be dependency_aware_parallel")
    if policy.get("dispatch_method") != "concurrent_tool_batch":
        raise ValueError("scheduling_policy.dispatch_method must be concurrent_tool_batch")
    if policy.get("dispatch_barrier") != "dispatch_all_ready_before_wait":
        raise ValueError("scheduling_policy.dispatch_barrier must be dispatch_all_ready_before_wait")
    if policy.get("completion_barrier") != "wait_for_all_dispatched_workers":
        raise ValueError("scheduling_policy.completion_barrier must be wait_for_all_dispatched_workers")
    maximum = policy.get("max_parallel_windows")
    if not isinstance(maximum, int) or not 2 <= maximum <= 8:
        raise ValueError("max_parallel_windows must be an integer from 2 to 8")
    missing_reasons = SERIAL_REASONS - set(policy.get("serial_only_when", []))
    if missing_reasons:
        raise ValueError("serial_only_when missing: " + ",".join(sorted(missing_reasons)))

    tasks = plan.get("planned_windows", [])
    task_ids = {task.get("task_id") for task in tasks}
    if not tasks or None in task_ids or len(task_ids) != len(tasks):
        raise ValueError("planned_windows must have unique task_id values")
    dependencies = {}
    by_id = {}
    for task in tasks:
        deps = task.get("depends_on")
        if not isinstance(deps, list):
            raise ValueError(f"task {task['task_id']} depends_on must be a list")
        unknown = set(deps) - task_ids
        if unknown or task["task_id"] in deps:
            raise ValueError(f"task {task['task_id']} has invalid dependencies")
        dependencies[task["task_id"]] = deps
        by_id[task["task_id"]] = task
        if task.get("controller_owned") is not True or task.get("dispatch_depth") != 1:
            raise ValueError(f"task {task['task_id']} must be controller-owned at dispatch_depth=1")
        if task.get("may_spawn_workers") is not False:
            raise ValueError(f"task {task['task_id']} may_spawn_workers must be false")
        if not isinstance(task.get("write_scope"), list) or not isinstance(task.get("contract_scope"), list):
            raise ValueError(f"task {task['task_id']} must declare write_scope and contract_scope")

    visiting = set()
    visited = set()

    def visit(task_id):
        if task_id in visiting:
            raise ValueError("task dependency graph contains a cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependencies[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in task_ids:
        visit(task_id)

    computed_parallel_sets = []
    remaining = set(task_ids)
    completed = set()
    while remaining:
        ready = sorted(task_id for task_id in remaining if set(dependencies[task_id]) <= completed)
        if not ready:
            raise ValueError("task dependency graph has no computable ready set")
        if len(ready) >= 2:
            write_owners = {}
            contract_owners = {}
            for task_id in ready:
                for path in by_id[task_id]["write_scope"]:
                    if path in write_owners:
                        raise ValueError(f"ready tasks {write_owners[path]} and {task_id} overlap write scope {path}")
                    write_owners[path] = task_id
                for contract in by_id[task_id]["contract_scope"]:
                    if contract in contract_owners:
                        raise ValueError(f"ready tasks {contract_owners[contract]} and {task_id} overlap contract ownership {contract}")
                    contract_owners[contract] = task_id
            for start in range(0, len(ready), maximum):
                chunk = ready[start:start + maximum]
                if len(chunk) >= 2:
                    computed_parallel_sets.append(set(chunk))
        completed.update(ready)
        remaining.difference_update(ready)

    expected_batches = {}
    for batch in plan.get("parallel_dispatch_batches", []):
        batch_id = batch.get("batch_id")
        ready = batch.get("ready_task_ids", [])
        if not batch_id or len(ready) < 2 or len(set(ready)) != len(ready):
            raise ValueError("parallel_dispatch_batches require a unique batch_id and 2+ ready tasks")
        if batch_id in expected_batches:
            raise ValueError(f"duplicate parallel batch {batch_id}")
        if set(ready) - task_ids:
            raise ValueError(f"batch {batch_id} references unknown tasks")
        if batch.get("dispatch_method") != "concurrent_tool_batch":
            raise ValueError(f"batch {batch_id} must use concurrent_tool_batch")
        if batch.get("dispatch_barrier") != "dispatch_all_ready_before_wait":
            raise ValueError(f"batch {batch_id} must dispatch all ready tasks before waiting")
        expected_batches[batch_id] = set(ready)
    declared_sets = list(expected_batches.values())
    if sorted(map(sorted, declared_sets)) != sorted(map(sorted, computed_parallel_sets)):
        raise ValueError(f"declared parallel batches do not match computed ready sets: computed={sorted(map(sorted, computed_parallel_sets))}")
    if not expected_batches:
        decision = plan.get("parallel_dispatch_decision", {})
        if computed_parallel_sets or decision.get("parallel_opportunity_count") != 0:
            raise ValueError("parallel_opportunity_count must be zero when no parallel batch is planned")
        if decision.get("serial_reason") not in SERIAL_REASONS:
            raise ValueError("a valid serial_reason is required when no parallel batch is planned")
    return expected_batches


def validate_ledger(ledger, expected_batches):
    if ledger.get("scheduling_mode") != "dependency_aware_parallel":
        raise ValueError("ledger scheduling_mode must be dependency_aware_parallel")
    batches = ledger.get("batches", [])
    actual_batches = {batch.get("batch_id"): batch for batch in batches}
    if len(actual_batches) != len(batches):
        raise ValueError("ledger batch_id values must be unique")
    for batch_id, expected_ready in expected_batches.items():
        batch = actual_batches.get(batch_id)
        if not batch:
            raise ValueError(f"ledger missing batch {batch_id}")
        ready = set(batch.get("ready_task_ids", []))
        if ready != expected_ready or batch.get("parallel_required") is not True:
            raise ValueError(f"batch {batch_id} ready set or parallel_required is invalid")
        if batch.get("dispatch_method") != "concurrent_tool_batch":
            raise ValueError(f"batch {batch_id} used serial dispatch")
        if batch.get("all_dispatches_submitted_before_wait") is not True:
            raise ValueError(f"batch {batch_id} waited before all dispatches were submitted")
        dispatches = batch.get("dispatches", [])
        dispatched = {item.get("task_id") for item in dispatches}
        if dispatched != expected_ready or len(dispatches) != len(expected_ready):
            raise ValueError(f"batch {batch_id} dispatch set does not match ready set")
        first_wait = parse_time(batch.get("first_wait_or_read_at"), "first_wait_or_read_at")
        for item in dispatches:
            if item.get("tool") != "send_message_to_thread" or item.get("accepted") is not True:
                raise ValueError(f"batch {batch_id} has an unaccepted or invalid dispatch")
            if not item.get("tool_call_id") or item.get("controller_owned") is not True or item.get("dispatch_depth") != 1:
                raise ValueError(f"batch {batch_id} dispatch lacks controller provenance")
            if parse_time(item.get("sent_at"), "sent_at") > first_wait:
                raise ValueError(f"batch {batch_id} dispatched a worker after waiting began")
        if batch.get("completion_barrier") != "wait_for_all_dispatched_workers":
            raise ValueError(f"batch {batch_id} missing completion barrier")
        if set(batch.get("completed_task_ids", [])) != expected_ready or batch.get("status") != "completed":
            raise ValueError(f"batch {batch_id} did not complete and consume every worker")
        outputs = batch.get("consumed_outputs", [])
        output_tasks = {item.get("task_id") for item in outputs}
        if output_tasks != expected_ready or len(outputs) != len(expected_ready):
            raise ValueError(f"batch {batch_id} output consumption set does not match ready set")
        for item in outputs:
            if not item.get("output_summary") or not item.get("output_hash") or item.get("consumed_by_controller") is not True:
                raise ValueError(f"batch {batch_id} has unconsumed or unproven worker output")


def main():
    if len(sys.argv) != 3:
        return fail("usage: validate_parallel_dispatch.py window-plan.json dispatch-ledger.json")
    try:
        expected_batches = validate_plan(load(sys.argv[1]))
        validate_ledger(load(sys.argv[2]), expected_batches)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return fail(str(error))
    print("VALID_PARALLEL_DISPATCH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
