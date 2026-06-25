#!/usr/bin/env python3
from pathlib import Path
required = [
    "engineering-assistant/scripts/init_task.py",
    "engineering-assistant/scripts/ensure_agent_entrypoint.py",
    "engineering-assistant/scripts/compile_design_contract.py",
    "engineering-assistant/scripts/validate_contract_control.py",
    "engineering-assistant/scripts/validate_control_plane_readonly.py",
    "engineering-assistant/scripts/validate_design_to_code.py",
    "engineering-assistant/scripts/build_traceability_report.py",
    "engineering-assistant/scripts/run_quality_contract.py",
    "engineering-assistant/scripts/run_quality_commands.py",
    "engineering-assistant/scripts/validate_control_health.py",
    "engineering-assistant/scripts/validate_technology_adoption.py",
    "engineering-assistant/scripts/validate_spring_boot_quality.py",
    "engineering-assistant/scripts/validate_rule_consumption.py",
    "engineering-assistant/scripts/run_controlled_task.py",
]
missing = [item for item in required if not Path(item).exists()]
if missing:
    raise SystemExit("missing control scripts: " + ", ".join(missing))
print("ok")
