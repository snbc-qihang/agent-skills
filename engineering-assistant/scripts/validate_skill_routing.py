#!/usr/bin/env python3
"""Validate every registered Skill's trigger, exclusion, prerequisites, and consumption contract."""

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
REGISTRY = ROOT / "engineering-assistant/registry/skill-routing-signals.json"
SKILL_REGISTRY = ROOT / "engineering-assistant/registry/skills.yaml"
ROUTER = ROOT / "engineering-assistant/scripts/route_skill.py"


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("engineering_assistant_route_skill", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def fail(message: str) -> None:
    print(f"INVALID_SKILL_ROUTING: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    config = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registered = json.loads(SKILL_REGISTRY.read_text(encoding="utf-8"))["skills"]
    route_module = load_module(ROUTER)
    by_id = {item["skill_id"]: item for item in config["skills"]}
    registered_ids = {item["skill_id"] for item in registered}
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    if manifest.get("skills") != "./entrypoint-skills/":
        fail("plugin manifest must expose only the Engineering Assistant entrypoint")
    exposed = list((ROOT / "entrypoint-skills").glob("*/SKILL.md"))
    if len(exposed) != 1 or "name: engineering-assistant" not in exposed[0].read_text(encoding="utf-8"):
        fail("exactly one Engineering Assistant Skill entrypoint must be exposed")
    if set(by_id) != registered_ids:
        fail(f"registry mismatch missing={sorted(registered_ids-set(by_id))} extra={sorted(set(by_id)-registered_ids)}")

    checks = 0
    for skill_id, skill in by_id.items():
        for field in ("primary_phrases", "secondary_phrases", "prerequisites", "output_consumers"):
            if field not in skill or not isinstance(skill[field], list):
                fail(f"{skill_id} missing list field {field}")
        if not skill["primary_phrases"]:
            fail(f"{skill_id} has no positive trigger")
        if not skill["output_consumers"]:
            fail(f"{skill_id} has no output consumer")
        for prerequisite in skill["prerequisites"]:
            if prerequisite not in by_id:
                fail(f"{skill_id} references unknown prerequisite {prerequisite}")

        positive = route_module.route(skill["primary_phrases"][0], ROOT)
        if skill.get("controller_only"):
            if positive.get("controller") != skill_id:
                fail(f"{skill_id} controller trigger failed: {positive}")
        elif skill_id not in positive.get("selected_skills", []):
            fail(f"{skill_id} positive trigger failed: {positive}")
        checks += 1

        negative = route_module.route(f"只解释 {skill['primary_phrases'][0]} 的用途，不执行任务、不生成产物", ROOT)
        if negative.get("status") != "rejected":
            fail(f"{skill_id} negative trigger failed: {negative}")
        checks += 1

        if not skill.get("controller_only"):
            missing = set(skill["prerequisites"]) - set(positive.get("selected_skills", []))
            if missing:
                fail(f"{skill_id} prerequisite completion failed: {sorted(missing)}")
        checks += 1

        if not skill["output_consumers"]:
            fail(f"{skill_id} output consumption contract missing")
        checks += 1

    probes = [
        ("修复后端订单服务的空指针 bug", "code-development"),
        ("对这次代码变更做代码评审", "code-review"),
        ("设计订单 Redis 缓存方案", "redis-design"),
        ("设计订单异步消息和重试机制", "mq-design"),
        ("只修改前端优惠券页面", "frontend-development"),
        ("准备生产发布并验证回滚方案", "release-readiness"),
        ("审计研发助手并修复重复犯错问题", "self-evolution-controller"),
    ]
    for prompt, expected in probes:
        result = route_module.route(prompt, ROOT)
        if result.get("decision") != expected:
            fail(f"probe expected {expected}: {prompt}: {result}")
        if result.get("routing_confirmation_required") is not False:
            fail(f"route unexpectedly requires confirmation: {prompt}")
        checks += 1

    complex_result = route_module.route("实现跨模块订单与支付共享状态机改造", ROOT)
    protocol = complex_result.get("complex_requirement_protocol", {})
    if complex_result.get("risk_level") not in {"L2_SHARED", "L3_CRITICAL"} or not protocol.get("required") or protocol.get("max_questions") != 6:
        fail(f"complex requirement protocol missing: {complex_result}")
    checks += 1

    no_write = route_module.route("审计当前实现，不修改任何文件", ROOT)
    if {"code-development", "frontend-development", "implementation-controller"} & set(no_write.get("selected_skills", [])):
        fail(f"read-only request selected write capability: {no_write}")
    checks += 1

    forbidden = route_module.route("不要使用 code-development，只做代码评审", ROOT)
    if "code-development" in forbidden.get("selected_skills", []) or "code-review" not in forbidden.get("selected_skills", []):
        fail(f"explicit forbidden capability was selected: {forbidden}")
    checks += 1

    positions = {
        skill: index
        for index, batch in enumerate(complex_result.get("parallel_batches", []))
        for skill in batch["skills"]
    }
    chain = ["detailed-design", "design-review", "implementation-controller", "code-development"]
    if not all(positions.get(left, -1) < positions.get(right, -1) for left, right in zip(chain, chain[1:])):
        fail(f"conditional implementation dependency order invalid: {complex_result}")
    checks += 1

    parallel = route_module.route("详细设计订单数据库、Redis 缓存和 MQ 消息方案", ROOT)
    if not any({"database-design", "redis-design", "mq-design"} <= set(batch["skills"]) for batch in parallel.get("parallel_batches", [])):
        fail(f"specialty design parallel batch missing: {parallel}")
    checks += 1

    if len(parallel.get("skipped_candidates", [])) > config["policy"]["max_skipped_candidates"]:
        fail("skipped candidate budget exceeded")
    checks += 1

    print(f"VALID_SKILL_ROUTING skills={len(by_id)} checks={checks} probes={len(probes)}")


if __name__ == "__main__":
    main()
