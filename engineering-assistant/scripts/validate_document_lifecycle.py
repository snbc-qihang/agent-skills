#!/usr/bin/env python3
import json, re, sys
from pathlib import Path

DOC_NUMBER = re.compile(r"^(REQ|CTX|HLD|DDD|DBD|RDS|MQD|DRR|CQR|CRR|RLP|RVF|RTR|KNO|RPT)-[A-Z0-9][A-Z0-9-]{1,40}-[0-9]{8}-[0-9]{3}$")
REQUIRED = ["document_number", "document_status", "retention_policy", "title", "owner", "source_artifacts"]
FORMAL_STATUSES = {"approved", "final"}
INTERMEDIATE_STATUSES = {"draft", "reviewing", "blocked", "waiting_for_input"}
PERSIST_ALLOWED_CLASSES = {"formal_design", "formal_decision", "formal_index"}
TRANSIENT_ONLY_CLASSES = {"run_evidence", "agent_workspace", "process_trace", "human_review_packet", "human_readable_render", "rule_governance"}
FINAL_PROJECT_ROOTS = ("docs/00-index/", "docs/architecture/", "docs/design/", "docs/decisions/", "docs/release/")
NON_FINAL_ROOTS = ("artifacts/", "artifacts/_control/", "docs/human-review/", "docs/human-readable/")


def normalized_path(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("/")


def validate_persisted_document(path: Path, data: dict) -> None:
    if data.get("retention_policy") != "persist":
        return
    document_class = data.get("document_class")
    canonical_path = normalized_path(data.get("canonical_path") or (data.get("source_artifacts") or [""])[0])
    if document_class not in PERSIST_ALLOWED_CLASSES:
        errors.append(f"{path}: persist 文档必须声明 document_class=formal_design|formal_decision|formal_index")
    if document_class in TRANSIENT_ONLY_CLASSES:
        errors.append(f"{path}: {document_class} 只能作为运行期或 agent 工作产物，不得 persist")
    if data.get("retention_scope") != "final_project_record":
        errors.append(f"{path}: persist 文档必须声明 retention_scope=final_project_record")
    if not canonical_path.startswith(FINAL_PROJECT_ROOTS):
        errors.append(f"{path}: persist 文档 canonical_path 必须位于正式 docs 目录")
    if canonical_path.startswith(NON_FINAL_ROOTS):
        errors.append(f"{path}: artifacts/_control 或 HTML 目录不得作为正式留存源")

errors = []
for arg in sys.argv[1:]:
    path = Path(arg)
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in REQUIRED:
        if field not in data:
            errors.append(f"{path}: 缺少字段 {field}")
    if errors:
        continue
    if not DOC_NUMBER.match(str(data["document_number"])):
        errors.append(f"{path}: document_number 不符合编号规范")
    if data["document_status"] in INTERMEDIATE_STATUSES and data["retention_policy"] == "persist":
        errors.append(f"{path}: 中间过程文档不得 persist")
    if data["retention_policy"] == "persist" and data["document_status"] not in FORMAL_STATUSES:
        errors.append(f"{path}: 只有 approved/final 文档可以 persist")
    validate_persisted_document(path, data)
if errors:
    raise SystemExit("\n".join(errors))
print("ok")
