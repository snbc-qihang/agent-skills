#!/usr/bin/env python3
import json, re, sys
from pathlib import Path

VALID_LANGUAGE = {"zh-CN", "en"}
VALID_STATUSES = {"succeeded", "failed", "blocked", "waiting_for_input", "waiting_for_human_review", "skipped"}
VALID_PREFLIGHT_STATES = {"ready", "waiting_for_input", "waiting_for_human_review", "blocked"}
FORMAL_DESIGN_ARTIFACTS = {"high-level-design.md", "detailed-design.md", "database-design.md", "redis-design.md", "mq-design.xlsx", "interface-contracts.yaml", "test-strategy.md"}
DOC_NUMBER = re.compile(r"^(REQ|CTX|HLD|DDD|DBD|RDS|MQD|DRR|CQR|CRR|RLP|RVF|RTR|KNO|RPT)-[A-Z0-9][A-Z0-9-]{1,40}-[0-9]{8}-[0-9]{3}$")
DOC_REQUIRED = ["document_number", "document_status", "retention_policy", "title", "owner", "source_artifacts"]
PERSIST_ALLOWED_CLASSES = {"formal_design", "formal_decision", "formal_index"}
TRANSIENT_ONLY_CLASSES = {"run_evidence", "agent_workspace", "process_trace", "human_review_packet", "human_readable_render", "rule_governance"}
FINAL_PROJECT_ROOTS = ("docs/00-index/", "docs/architecture/", "docs/design/", "docs/decisions/", "docs/release/")
NON_FINAL_ROOTS = ("artifacts/", "artifacts/_control/", "docs/human-review/", "docs/human-readable/")
WAITING_STATUSES = {"waiting_for_input", "waiting_for_human_review"}
BLOCKING_FINDING_SEVERITIES = {"blocker", "major"}
BLOCKING_GATE_RESULTS = {"block", "blocked", "block_for_completion", "blocked_for_product_completion", "fail", "failed", "error"}


def artifact_path(artifact):
    return artifact.get("path") or artifact.get("file") or artifact.get("uri") or ""


def normalized_path(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("/")


def validate_persisted_metadata(result_path: Path, metadata: dict) -> None:
    if metadata.get("retention_policy") != "persist":
        return
    document_class = metadata.get("document_class")
    canonical_path = normalized_path(metadata.get("canonical_path") or (metadata.get("source_artifacts") or [""])[0])
    if document_class not in PERSIST_ALLOWED_CLASSES:
        errors.append(f"{result_path}: persist 文档必须声明 document_class=formal_design|formal_decision|formal_index")
    if document_class in TRANSIENT_ONLY_CLASSES:
        errors.append(f"{result_path}: {document_class} 只能作为运行期或 agent 工作产物，不得 persist")
    if metadata.get("retention_scope") != "final_project_record":
        errors.append(f"{result_path}: persist 文档必须声明 retention_scope=final_project_record")
    if not canonical_path.startswith(FINAL_PROJECT_ROOTS):
        errors.append(f"{result_path}: persist 文档 canonical_path 必须位于正式 docs 目录")
    if canonical_path.startswith(NON_FINAL_ROOTS):
        errors.append(f"{result_path}: artifacts/_control 或 HTML 目录不得作为正式留存源")


def artifact_kind(artifact):
    fields = [
        artifact.get("type", ""),
        artifact.get("artifact_type", ""),
        artifact.get("name", ""),
        artifact_path(artifact),
    ]
    return " ".join(str(item).lower() for item in fields)


def is_human_html_artifact(artifact):
    path_text = artifact_path(artifact).lower()
    kind = artifact_kind(artifact)
    return path_text.endswith((".html", ".htm")) and any(token in kind for token in ["human", "review", "confirmation", "approval"])


def is_blocking_gate(gate: dict) -> bool:
    raw = str(gate.get("result") or gate.get("status") or "").strip().lower()
    if raw in BLOCKING_GATE_RESULTS:
        return True
    return raw.startswith("block") or raw.startswith("fail")


def resolve_artifact_file(result_path: Path, artifact):
    raw = artifact_path(artifact)
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    candidates = [Path.cwd() / candidate, result_path.parent / candidate]
    candidates.extend(parent / candidate for parent in result_path.resolve().parents)
    for item in candidates:
        if item.exists():
            return item
    return candidates[0]


def validate_human_html(path: Path, owner: Path):
    if not path.exists():
        errors.append(f"{owner}: 人工审阅 HTML 不存在: {path}")
        return
    normalized_path = str(path).replace("\\", "/")
    if "/docs/human-review/" not in normalized_path:
        errors.append(f"{owner}: 人工审阅 HTML 必须放在 docs/human-review/ 目录: {path}")
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    if not any(token in lowered for token in ["<textarea", "<input", "<select", "contenteditable"]):
        errors.append(f"{owner}: 人工审阅 HTML 必须包含可编辑输入控件: {path}")
    if "data-human-review-packet" not in lowered:
        errors.append(f"{owner}: 人工审阅 HTML 必须标记 data-human-review-packet: {path}")
    if "answer-json" not in lowered:
        errors.append(f"{owner}: 人工审阅 HTML 必须包含答案 JSON 导出区域: {path}")
    if not any(token in lowered for token in ["download", "clipboard", "复制 json", "下载 json"]):
        errors.append(f"{owner}: 人工审阅 HTML 必须支持复制或下载结构化答案: {path}")

errors = []
for arg in sys.argv[1:]:
    path = Path(arg)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") not in VALID_STATUSES:
        errors.append(f"{path}: status 不合法")
    if data.get("preflight_input_state") not in VALID_PREFLIGHT_STATES:
        errors.append(f"{path}: preflight_input_state 不合法")
    if data.get("language") not in VALID_LANGUAGE:
        errors.append(f"{path}: language 不能为空，且必须为 zh-CN 或 en")
    info_requests = data.get("required_information_requests", [])
    artifact_names = {artifact.get("name") for artifact in data.get("artifacts", []) if artifact.get("name")}
    if data.get("status") == "waiting_for_input" and data.get("preflight_input_state") != "waiting_for_input":
        errors.append(f"{path}: waiting_for_input 时 preflight_input_state 必须为 waiting_for_input")
    if data.get("status") == "waiting_for_human_review" and data.get("preflight_input_state") != "waiting_for_human_review":
        errors.append(f"{path}: waiting_for_human_review 时 preflight_input_state 必须为 waiting_for_human_review")
    if data.get("preflight_input_state") != "ready":
        leaked = sorted(name for name in artifact_names if name in FORMAL_DESIGN_ARTIFACTS)
        if leaked:
            errors.append(f"{path}: preflight_input_state={data.get('preflight_input_state')} 时不得产出正式设计工件: {', '.join(leaked)}")
    if data.get("status") == "waiting_for_input":
        if not info_requests:
            errors.append(f"{path}: waiting_for_input 必须包含 required_information_requests")
        for index, request in enumerate(info_requests):
            if request.get("blocking") and not request.get("questions"):
                errors.append(f"{path}: required_information_requests[{index}].questions 不能为空")
    if data.get("status") in WAITING_STATUSES:
        html_artifacts = [artifact for artifact in data.get("artifacts", []) if is_human_html_artifact(artifact)]
        if not html_artifacts:
            errors.append(f"{path}: {data.get('status')} 必须在 artifacts 登记可填写的人工审阅 HTML")
        for artifact in html_artifacts:
            html_path = resolve_artifact_file(path, artifact)
            if html_path is not None:
                validate_human_html(html_path, path)
    if data.get("status") == "succeeded":
        if data.get("preflight_input_state") != "ready":
            errors.append(f"{path}: succeeded 时 preflight_input_state 必须为 ready")
        metadata = data.get("document_metadata") or {}
        for field in DOC_REQUIRED:
            if field not in metadata or metadata.get(field) in ("", [], None):
                errors.append(f"{path}: document_metadata 缺少 {field}")
        number = str(metadata.get("document_number", ""))
        if number and not DOC_NUMBER.match(number):
            errors.append(f"{path}: document_metadata.document_number 不符合编号规范")
        validate_persisted_metadata(path, metadata)
        for finding in data.get("findings", []):
            if str(finding.get("severity", "")).lower() in BLOCKING_FINDING_SEVERITIES:
                errors.append(f"{path}: succeeded 不允许包含 blocker/major finding: {finding.get('id') or finding.get('summary')}")
        for gate in data.get("quality_gates", []):
            if is_blocking_gate(gate):
                errors.append(f"{path}: succeeded 不允许包含阻断质量门禁: {gate.get('name') or gate.get('gate_id')}")
if errors:
    raise SystemExit("\n".join(errors))
print("ok")
