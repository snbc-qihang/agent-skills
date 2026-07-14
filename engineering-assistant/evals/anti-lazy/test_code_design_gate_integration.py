#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ENGINEERING_ASSISTANT = Path(__file__).resolve().parents[2]
SCRIPTS = ENGINEERING_ASSISTANT / "scripts"
DATASET = Path(__file__).with_name("code-design-gates.json")


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def main() -> int:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    l1_case = next(item for item in dataset["cases"] if item["id"] == "l1_local_fix_uses_compact_design")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        control = root / "artifacts/_control"
        write_json(control / "current-task.json", {"task_id": "design-gate-l1", "project_profile": {}})
        write_json(control / "artifact-index.json", {"artifacts": {}})
        write_json(control / "open-questions.json", {"questions": []})
        write_json(control / "coding-eligibility.json", l1_case["eligibility"])
        write_json(control / "code-design-decision.json", l1_case["code_design_decision"])
        compile_result = run([
            sys.executable,
            str(SCRIPTS / "compile_design_contract.py"),
            "--root",
            str(root),
            "--eligibility",
            "artifacts/_control/coding-eligibility.json",
            "--code-design-decision",
            "artifacts/_control/code-design-decision.json",
        ])
        if compile_result.returncode != 0:
            print(compile_result.stdout + compile_result.stderr)
            return 1
        design_contract = json.loads((control / "design-contract.json").read_text(encoding="utf-8"))
        implementation_contract = json.loads((control / "implementation-contract.json").read_text(encoding="utf-8"))
        quality_contract = json.loads((control / "quality-contract.json").read_text(encoding="utf-8"))
        failures = []
        if design_contract.get("design_evidence_mode") != "compact":
            failures.append("L1 design contract is not compact")
        if design_contract.get("risk_level") != "L1_DIRECT":
            failures.append("L1 risk level was not preserved")
        if "src/Formatter.java" not in implementation_contract.get("allowed_modules", []):
            failures.append("compact placement was not compiled into allowed_modules")
        if "business_code_pileup_check" not in quality_contract.get("required_evidence", []):
            failures.append("pileup evidence is not required by quality contract")
        if not any("controllers and adapters" in item for item in implementation_contract.get("architecture_rules", [])):
            failures.append("domain placement rule was not compiled")

        formal_root = root / "formal-case"
        formal_control = formal_root / "artifacts/_control"
        formal_design = formal_root / "approved/order-capability-design.md"
        formal_design.parent.mkdir(parents=True, exist_ok=True)
        formal_design.write_text(
            "document_status: approved\n# Order capability\nChange order pricing ownership.\n"
            "Keep membership decisions behind the membership contract.\n"
            "Implement in `src/OrderApplicationService.java`.\n"
            "Protect existing order creation behavior.\n",
            encoding="utf-8",
        )
        write_json(formal_control / "current-task.json", {"task_id": "design-gate-l2", "project_profile": {}})
        write_json(formal_control / "artifact-index.json", {"artifacts": {}})
        write_json(formal_control / "open-questions.json", {"questions": []})
        write_json(formal_control / "coding-eligibility.json", {
            "risk_level": "L2_SHARED",
            "change_kind": "business_capability",
            "business_capability_change": True,
            "selected_path": "formal_design",
            "decision": "allow_code",
            "source_evidence": ["src/OrderApplicationService.java", "approved/order-capability-design.md"],
            "design_evidence": {"status": "approved", "formal_design_path": "approved/order-capability-design.md"},
        })
        formal_compile = run([
            sys.executable,
            str(SCRIPTS / "compile_design_contract.py"),
            "--root",
            str(formal_root),
            "--eligibility",
            "artifacts/_control/coding-eligibility.json",
            "--design",
            "approved/order-capability-design.md",
        ])
        if formal_compile.returncode != 0:
            failures.append("approved L2 design failed to compile: " + formal_compile.stdout + formal_compile.stderr)
        else:
            formal_contract = json.loads((formal_control / "design-contract.json").read_text(encoding="utf-8"))
            if formal_contract.get("design_evidence_mode") != "formal" or formal_contract.get("risk_level") != "L2_SHARED":
                failures.append("L2 formal design evidence was not preserved")
        result = {"status": "pass" if not failures else "block", "failures": failures}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
