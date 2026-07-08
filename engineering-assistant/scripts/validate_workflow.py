#!/usr/bin/env python3
import json, sys
from pathlib import Path
VALID_ENTRY_MODES = {"auto_flow", "from_node", "single_node"}
for arg in sys.argv[1:]:
    data = json.loads(Path(arg).read_text(encoding="utf-8"))
    if not data.get("nodes"):
        raise SystemExit(f"{arg}: nodes 为空")
    node_ids = [node.get("node_id") for node in data["nodes"]]
    node_id_set = set(node_ids)
    if set(data.get("supported_entry_modes", [])) != VALID_ENTRY_MODES:
        raise SystemExit(f"{arg}: supported_entry_modes 必须支持 auto_flow/from_node/single_node")
    if data.get("default_entry_mode") != "auto_flow":
        raise SystemExit(f"{arg}: default_entry_mode 必须为 auto_flow")
    if data.get("start_node") not in node_id_set:
        raise SystemExit(f"{arg}: start_node 不在 nodes 中")
    if not data.get("terminal_nodes") or any(node not in node_id_set for node in data["terminal_nodes"]):
        raise SystemExit(f"{arg}: terminal_nodes 不合法")
    for mode in VALID_ENTRY_MODES:
        if mode not in data.get("composition_policy", {}):
            raise SystemExit(f"{arg}: composition_policy 缺少 {mode}")
    for node in data["nodes"]:
        for field in ["node_id", "skill_id", "entry_modes", "depends_on", "inputs", "outputs", "approval_policy", "failure_policy", "next_nodes"]:
            if field not in node:
                raise SystemExit(f"{arg}: node 缺少字段 {field}")
        if set(node.get("entry_modes", [])) != VALID_ENTRY_MODES:
            raise SystemExit(f"{arg}: {node.get('node_id')} entry_modes 不合法")
        for next_node in node.get("next_nodes", []):
            if next_node not in node_id_set:
                raise SystemExit(f"{arg}: {node.get('node_id')} next_nodes 指向未知节点 {next_node}")
        for previous_node in node.get("depends_on", []):
            if previous_node not in node_id_set:
                raise SystemExit(f"{arg}: {node.get('node_id')} depends_on 指向未知节点 {previous_node}")
    if data.get("workflow_id") in {"full-feature-development", "frontend-only", "design-only"}:
        for required in ["product-prototype-design", "prototype-review-loop"]:
            if required not in node_id_set:
                raise SystemExit(f"{arg}: web/app workflow 缺少原型硬门禁节点 {required}")
        review_index = node_ids.index("prototype-review-loop")
        for downstream in ["frontend-design", "implementation-controller", "code-development", "frontend-development"]:
            if downstream in node_id_set and review_index > node_ids.index(downstream):
                raise SystemExit(f"{arg}: prototype-review-loop 必须位于 {downstream} 之前")
        policy = data.get("prototype_review_policy") or {}
        if policy.get("minimum_review_rounds") != 3:
            raise SystemExit(f"{arg}: prototype_review_policy.minimum_review_rounds 必须为 3")
    if data.get("workflow_id") == "knowledge-review":
        expected_order = ["assistant-feedback-capture", "engineering-knowledge-miner", "skill-evolution-review", "skill-quality-auditor"]
        if node_ids != expected_order:
            raise SystemExit(f"{arg}: knowledge-review 必须按 feedback capture -> knowledge miner -> evolution review -> quality auditor 执行")
    if "feedback_evolution_policy" not in data:
        raise SystemExit(f"{arg}: 缺少 feedback_evolution_policy")
print("ok")
