"""Skill and governance catalog source for the generator."""

from __future__ import annotations

from . import legacy_generator as _legacy

SKILLS = _legacy.SKILLS
TEAM_RULE_CATALOG = _legacy.TEAM_RULE_CATALOG
CAPABILITY_FAMILIES = getattr(_legacy, "CAPABILITY_FAMILIES", {})
CAPABILITY_ROUTING_PROTOCOL = getattr(_legacy, "CAPABILITY_ROUTING_PROTOCOL", {})
DOCUMENTATION_OUTPUT_MODE_POLICY = getattr(_legacy, "DOCUMENTATION_OUTPUT_MODE_POLICY", {})
ENGINEERING_GOVERNANCE_STATE_MACHINE = getattr(_legacy, "ENGINEERING_GOVERNANCE_STATE_MACHINE", {})
