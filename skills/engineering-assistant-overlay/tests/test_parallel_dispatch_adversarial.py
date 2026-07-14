#!/usr/bin/env python3
"""Adversarial regressions for fake parallelism, conflicts, and fake completion."""

import copy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("parallel_validator", ROOT / "scripts/validate_parallel_dispatch.py")
validator = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(validator)

plan = json.loads((ROOT / "templates/window-plan.template.json").read_text(encoding="utf-8"))
ledger = json.loads((ROOT / "templates/dispatch-ledger.template.json").read_text(encoding="utf-8"))
expected = validator.validate_plan(plan)
validator.validate_ledger(ledger, expected)


def must_reject(label, callback):
    try:
        callback()
    except ValueError:
        return
    raise SystemExit(f"ADVERSARIAL_PARALLEL_CASE_ACCEPTED {label}")


false_zero = copy.deepcopy(plan)
false_zero["parallel_dispatch_batches"] = []
false_zero["parallel_dispatch_decision"] = {"parallel_opportunity_count": 0, "serial_reason": "dependency_not_satisfied"}
must_reject("false_zero_parallel_opportunity", lambda: validator.validate_plan(false_zero))

overlap = copy.deepcopy(plan)
for task in overlap["planned_windows"]:
    if task["task_id"] in {"api-contract-test", "flow-test"}:
        task["write_scope"] = ["same.py"]
must_reject("overlapping_write_scope", lambda: validator.validate_plan(overlap))

dependency_in_batch = copy.deepcopy(plan)
for task in dependency_in_batch["planned_windows"]:
    if task["task_id"] == "flow-test":
        task["depends_on"] = ["api-contract-test"]
must_reject("dependency_inside_parallel_batch", lambda: validator.validate_plan(dependency_in_batch))

recursive_worker = copy.deepcopy(plan)
recursive_worker["planned_windows"][0]["may_spawn_workers"] = True
must_reject("recursive_worker", lambda: validator.validate_plan(recursive_worker))

unconsumed = copy.deepcopy(ledger)
unconsumed["batches"][0]["consumed_outputs"] = unconsumed["batches"][0]["consumed_outputs"][:-1]
must_reject("unconsumed_output", lambda: validator.validate_ledger(unconsumed, expected))

print("VALID_PARALLEL_DISPATCH_ADVERSARIAL cases=5")
