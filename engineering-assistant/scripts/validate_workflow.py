#!/usr/bin/env python3
import json
import sys
from pathlib import Path

VALID_ENTRY_MODES = {"auto_flow", "from_node", "single_node"}
REQUIRED_ROUTING_POLICY = {
    "mode": "capability_conditioned_dag",
    "execute_selected_subgraph_only": True,
    "non_selected_node_status": "skipped",
    "skip_reason_required": True,
    "parallelize_independent_ready_nodes": True,
    "completion_barrier_required": True,
    "legacy_next_nodes": "dependency_hints_only",
}

for arg in sys.argv[1:]:
    workflow_path = Path(arg).resolve()
    data = json.loads(workflow_path.read_text(encoding="utf-8"))
    if not data.get("nodes"):
        raise SystemExit(f"{arg}: nodes 为空")
    node_ids = [node.get("node_id") for node in data["nodes"]]
    node_id_set = set(node_ids)
    if set(data.get("supported_entry_modes", [])) != VALID_ENTRY_MODES:
        raise SystemExit(f"{arg}: supported_entry_modes 必须支持 auto_flow/from_node/single_node")
    if data.get("default_entry_mode") != "auto_flow":
        raise SystemExit(f"{arg}: default_entry_mode 必须为 auto_flow")
    routing_policy = data.get("routing_policy", {})
    for field, expected in REQUIRED_ROUTING_POLICY.items():
        if routing_policy.get(field) != expected:
            raise SystemExit(f"{arg}: routing_policy.{field} 必须为 {expected!r}")
    plugin_root = workflow_path.parents[2]
    for field in ("router", "signals_registry"):
        target = plugin_root / routing_policy.get(field, "")
        if not target.is_file():
            raise SystemExit(f"{arg}: routing_policy.{field} 不存在: {target}")
    signals = json.loads((plugin_root / routing_policy["signals_registry"]).read_text(encoding="utf-8"))
    registered_skills = {item["skill_id"] for item in signals.get("skills", [])}
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
        if node.get("skill_id") not in registered_skills:
            raise SystemExit(f"{arg}: {node.get('node_id')} skill_id 未注册自然语言路由")
        for next_node in node.get("next_nodes", []):
            if next_node not in node_id_set:
                raise SystemExit(f"{arg}: {node.get('node_id')} next_nodes 指向未知节点 {next_node}")
        for previous_node in node.get("depends_on", []):
            if previous_node not in node_id_set:
                raise SystemExit(f"{arg}: {node.get('node_id')} depends_on 指向未知节点 {previous_node}")
    next_graph = {node["node_id"]: node.get("next_nodes", []) for node in data["nodes"]}
    dependency_graph = {node["node_id"]: node.get("depends_on", []) for node in data["nodes"]}

    def assert_acyclic(graph, label):
        visiting = set()
        visited = set()

        def visit(node_id):
            if node_id in visiting:
                raise SystemExit(f"{arg}: {label} 存在循环，涉及 {node_id}")
            if node_id in visited:
                return
            visiting.add(node_id)
            for linked in graph[node_id]:
                visit(linked)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in graph:
            visit(node_id)

    assert_acyclic(next_graph, "next_nodes")
    assert_acyclic(dependency_graph, "depends_on")

    reachable = set()
    stack = [data["start_node"]]
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        stack.extend(next_graph[node_id])
    unreachable = node_id_set - reachable
    if unreachable:
        raise SystemExit(f"{arg}: start_node 无法到达节点 {sorted(unreachable)}")
print("ok")
