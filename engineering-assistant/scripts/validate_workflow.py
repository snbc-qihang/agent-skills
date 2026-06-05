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
    preflight_policy = data.get("preflight_runtime_policy", {})
    if preflight_policy.get("formal_generation_entry_condition") != "preflight_input_state == ready":
        raise SystemExit(f"{arg}: preflight_runtime_policy.formal_generation_entry_condition 必须为 preflight_input_state == ready")
    if preflight_policy.get("block_current_node_formal_generation") is not True:
        raise SystemExit(f"{arg}: preflight_runtime_policy.block_current_node_formal_generation 必须为 true")
    if preflight_policy.get("block_next_nodes") is not True:
        raise SystemExit(f"{arg}: preflight_runtime_policy.block_next_nodes 必须为 true")
    for node in data["nodes"]:
        for field in ["node_id", "skill_id", "entry_modes", "depends_on", "inputs", "outputs", "preflight_gate", "approval_policy", "failure_policy", "next_nodes"]:
            if field not in node:
                raise SystemExit(f"{arg}: node 缺少字段 {field}")
        gate = node.get("preflight_gate", {})
        if gate.get("formal_generation_entry_condition") != "preflight_input_state == ready":
            raise SystemExit(f"{arg}: {node.get('node_id')} preflight_gate.formal_generation_entry_condition 必须为 preflight_input_state == ready")
        if gate.get("block_formal_generation_when_not_ready") is not True:
            raise SystemExit(f"{arg}: {node.get('node_id')} preflight_gate.block_formal_generation_when_not_ready 必须为 true")
        if gate.get("block_next_nodes_when_not_ready") is not True:
            raise SystemExit(f"{arg}: {node.get('node_id')} preflight_gate.block_next_nodes_when_not_ready 必须为 true")
        if set(node.get("entry_modes", [])) != VALID_ENTRY_MODES:
            raise SystemExit(f"{arg}: {node.get('node_id')} entry_modes 不合法")
        for next_node in node.get("next_nodes", []):
            if next_node not in node_id_set:
                raise SystemExit(f"{arg}: {node.get('node_id')} next_nodes 指向未知节点 {next_node}")
        for previous_node in node.get("depends_on", []):
            if previous_node not in node_id_set:
                raise SystemExit(f"{arg}: {node.get('node_id')} depends_on 指向未知节点 {previous_node}")
print("ok")
