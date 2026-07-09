"""Evaluation asset generation surface."""

from __future__ import annotations

from . import legacy_generator as _legacy


def skill_effectiveness_eval_spec():
    if hasattr(_legacy, "skill_effectiveness_eval_spec"):
        return _legacy.skill_effectiveness_eval_spec()
    return {
        "skill_name": _legacy.PLUGIN_NAME,
        "version": _legacy.PLUGIN_VERSION,
        "evaluation_goal": "验证 teamwork 工程助手插件在团队规则和控制面约束下的交付稳定性。",
        "cases": [],
    }


def generate_skill_effectiveness_eval_assets():
    if hasattr(_legacy, "generate_skill_effectiveness_eval_assets"):
        return _legacy.generate_skill_effectiveness_eval_assets()
    return skill_effectiveness_eval_spec()
