from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.runtime.feedback import FeedbackCollector, run_codex_hook  # noqa: E402
from engineering_assistant.runtime.hook_gate import (  # noqa: E402
    is_explicit_plugin_request,
    should_load_runtime,
)
from engineering_assistant.runtime.usage_observation import (  # noqa: E402
    MAX_OBSERVATION_LEDGER_BYTES,
    MAX_RETAINED_TOOL_EVENTS,
    STALE_LEDGER_TTL_SECONDS,
)
from engineering_assistant.runtime.validation import (  # noqa: E402
    ValidationFailure,
    load_json,
    validate_instance,
)


class UsageObservationHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.common = {
            "session_id": "observation-session",
            "turn_id": "observation-turn",
            "transcript_path": None,
            "cwd": str(self.project),
            "model": "gpt-test",
            "permission_mode": "default",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_hook(
        self,
        payload: dict,
        *,
        output_reference: int = 1024,
        environment: dict[str, str] | None = None,
    ) -> dict:
        output = io.StringIO()
        code = run_codex_hook(
            input_stream=io.StringIO(json.dumps({**self.common, **payload})),
            output_stream=output,
            schema_root=ROOT / "schemas",
            environment={
                "ENGINEERING_ASSISTANT_FEEDBACK_MODE": "candidates",
                "ENGINEERING_ASSISTANT_OBSERVE_OUTPUT_BYTES": str(output_reference),
                **(environment or {}),
            },
        )
        self.assertEqual(0, code)
        return json.loads(output.getvalue())

    def activate(self) -> dict:
        return self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "使用 $engineering-assistant:code-review 完成代码评审。",
            }
        )

    def pre(self, tool_name: str, tool_input: dict, tool_use_id: str) -> dict:
        return self.run_hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_use_id": tool_use_id,
            }
        )

    def post(self, tool_name: str, tool_input: dict, tool_use_id: str, response) -> dict:
        return self.run_hook(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_use_id": tool_use_id,
                "tool_response": response,
            }
        )

    def ledger(self) -> dict:
        ledgers = list(
            (
                self.project
                / ".run-artifacts/engineering-assistant/usage-observations"
            ).rglob("turn-*.json")
        )
        self.assertEqual(1, len(ledgers))
        return json.loads(ledgers[0].read_text(encoding="utf-8"))

    def test_namespaced_plugin_request_activates_non_blocking_observation(self) -> None:
        response = self.activate()

        specific = response["hookSpecificOutput"]
        self.assertEqual("UserPromptSubmit", specific["hookEventName"])
        self.assertIn("只采集", specific["additionalContext"])
        payload = self.ledger()
        self.assertEqual("explicit_prompt", payload["plan"]["activation_source"])
        self.assertEqual(0, payload["tool_calls"])

    def test_ledger_schema_rejects_an_empty_plan_without_secondary_validation(
        self,
    ) -> None:
        payload = {
            "plan": {},
            "tool_calls": 0,
            "shell_calls": 0,
            "index_queries": 0,
            "output_bytes": 0,
            "tool_use_signatures": {},
            "completed_tool_use_ids": [],
            "signals": [],
            "signal_counts": {},
            "revision": 0,
        }

        with self.assertRaises(ValidationFailure):
            validate_instance(
                payload,
                load_json(ROOT / "schemas/usage-observation-ledger.schema.json"),
                "usage-observation-ledger",
            )

    def test_embedded_ledger_plan_contract_matches_the_standalone_schema(self) -> None:
        ledger_schema = load_json(
            ROOT / "schemas/usage-observation-ledger.schema.json"
        )
        plan_schema = load_json(ROOT / "schemas/usage-observation-plan.schema.json")
        standalone_contract = {
            key: value
            for key, value in plan_schema.items()
            if key not in {"$schema", "$id"}
        }

        self.assertEqual(
            standalone_contract,
            ledger_schema["properties"]["plan"],
        )

    def test_ledger_schema_rejects_oversized_retained_event_windows(self) -> None:
        self.activate()
        payload = self.ledger()
        schema = load_json(ROOT / "schemas/usage-observation-ledger.schema.json")

        payload["tool_use_signatures"] = {
            f"tool-{index:016x}": "sha256:" + "0" * 64
            for index in range(MAX_RETAINED_TOOL_EVENTS + 1)
        }
        with self.assertRaises(ValidationFailure):
            validate_instance(payload, schema, "usage-observation-ledger")

        payload = self.ledger()
        payload["completed_tool_use_ids"] = [
            f"tool-{index:016x}" for index in range(MAX_RETAINED_TOOL_EVENTS + 1)
        ]
        with self.assertRaises(ValidationFailure):
            validate_instance(payload, schema, "usage-observation-ledger")

    def test_builtin_schema_validator_enforces_collection_bounds(self) -> None:
        from engineering_assistant.runtime import validation

        with patch.object(validation, "Draft202012Validator", None):
            with self.assertRaises(ValidationFailure):
                validation.validate_instance(
                    ["first", "second"],
                    {"type": "array", "maxItems": 1},
                    "bounded-array",
                )
            with self.assertRaises(ValidationFailure):
                validation.validate_instance(
                    {"first": 1, "second": 2},
                    {"type": "object", "maxProperties": 1},
                    "bounded-object",
                )

    def test_plugin_tool_call_is_a_trusted_activation_signal(self) -> None:
        response = self.pre(
            "mcp__engineering_assistant__engineering_assistant_route",
            {"intent": {"task_kind": "review"}},
            "tool-1",
        )

        self.assertEqual({}, response)
        payload = self.ledger()
        self.assertEqual("plugin_tool", payload["plan"]["activation_source"])
        self.assertEqual(["mcp"], payload["plan"]["coverage"])
        self.assertEqual(1, payload["tool_calls"])

    def test_plugin_tool_completion_labels_efficiency_source_as_tool_hook(self) -> None:
        tool_name = "mcp__engineering_assistant__engineering_assistant_route"
        tool_input = {"intent": {"task_kind": "review"}}

        self.assertEqual({}, self.pre(tool_name, tool_input, "tool-1"))
        self.assertEqual(
            {},
            self.post(
                tool_name,
                tool_input,
                "tool-1",
                {"content": [{"type": "text", "text": "x" * 2_048}]},
            ),
        )

        candidate = json.loads(
            next(
                (
                    self.project
                    / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
                ).glob("*.json")
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("tool_hook", candidate["source"])

    def test_sequential_plugin_calls_publish_duplicate_signal_after_each_post(self) -> None:
        tool_name = "mcp__engineering_assistant__engineering_assistant_route"
        tool_input = {"intent": {"task_kind": "review"}}
        small_response = {"content": [{"type": "text", "text": "ok"}]}

        self.assertEqual({}, self.pre(tool_name, tool_input, "tool-1"))
        self.assertEqual(
            {}, self.post(tool_name, tool_input, "tool-1", small_response)
        )
        first = self.ledger()
        self.assertEqual(1, first["tool_calls"])
        self.assertEqual(1, len(first["completed_tool_use_ids"]))
        self.assertEqual([], first["signals"])

        self.assertEqual({}, self.pre(tool_name, tool_input, "tool-2"))
        self.assertEqual(
            {}, self.post(tool_name, tool_input, "tool-2", small_response)
        )

        candidate = json.loads(
            next(
                (
                    self.project
                    / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
                ).glob("*.json")
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("tool_hook", candidate["source"])
        self.assertEqual(2, candidate["tool_calls"])
        self.assertIn("duplicate_call", candidate["signals"])
        self.assertEqual(
            [],
            list(
                (
                    self.project
                    / ".run-artifacts/engineering-assistant/usage-observations"
                ).rglob("turn-*.json")
            ),
        )

    def test_concurrent_first_plugin_calls_are_both_observed_without_blocking(self) -> None:
        calls = [
            (
                "mcp__engineering_assistant__engineering_assistant_route",
                {"intent": {"task_kind": "review"}},
                "tool-route",
            ),
            (
                "mcp__engineering_assistant__engineering_assistant_artifact_validate",
                {"kind": "step-result", "artifact": {}},
                "tool-validate",
            ),
        ]

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda args: self.pre(*args), calls))

        self.assertEqual([{}, {}], responses)
        self.assertEqual(2, self.ledger()["tool_calls"])

    def test_interleaved_plugin_posts_wait_for_all_tracked_calls(self) -> None:
        tool_name = "mcp__engineering_assistant__engineering_assistant_route"
        first_input = {"intent": {"task_kind": "review"}}
        second_input = {"intent": {"task_kind": "implementation"}}
        small_response = {"content": [{"type": "text", "text": "ok"}]}
        candidates = (
            self.project
            / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
        )

        self.assertEqual({}, self.pre(tool_name, first_input, "tool-1"))
        self.assertEqual({}, self.pre(tool_name, second_input, "tool-2"))
        self.assertEqual(
            {}, self.post(tool_name, first_input, "tool-1", small_response)
        )

        after_first_post = self.ledger()
        self.assertEqual(2, after_first_post["tool_calls"])
        self.assertEqual(1, len(after_first_post["completed_tool_use_ids"]))
        self.assertEqual([], list(candidates.glob("*.json")))

        self.assertEqual(
            {}, self.post(tool_name, second_input, "tool-2", small_response)
        )
        after_second_post = self.ledger()
        self.assertEqual(2, len(after_second_post["completed_tool_use_ids"]))
        self.assertEqual([], list(candidates.glob("*.json")))

        self.assertEqual({}, self.pre(tool_name, first_input, "tool-3"))
        self.assertEqual(
            {}, self.post(tool_name, first_input, "tool-3", small_response)
        )
        candidate = json.loads(next(candidates.glob("*.json")).read_text("utf-8"))
        self.assertEqual(3, candidate["tool_calls"])
        self.assertIn("duplicate_call", candidate["signals"])
        self.assertNotIn("tool_without_post", candidate["signals"])

    def test_concurrent_pre_during_candidate_commit_is_rebased_not_deleted(
        self,
    ) -> None:
        tool_name = "mcp__engineering_assistant__engineering_assistant_route"
        first_input = {"intent": {"task_kind": "review"}}
        concurrent_input = {"intent": {"task_kind": "implementation"}}
        original_collect = FeedbackCollector.collect_usage_efficiency

        self.assertEqual({}, self.pre(tool_name, first_input, "tool-1"))
        first_observation_id = self.ledger()["plan"]["observation_id"]

        def collect_after_concurrent_pre(collector, **kwargs):
            self.assertEqual(
                {}, self.pre(tool_name, concurrent_input, "tool-concurrent")
            )
            return original_collect(collector, **kwargs)

        with patch.object(
            FeedbackCollector,
            "collect_usage_efficiency",
            autospec=True,
            side_effect=collect_after_concurrent_pre,
        ):
            self.assertEqual(
                {},
                self.post(
                    tool_name,
                    first_input,
                    "tool-1",
                    {"content": [{"type": "text", "text": "x" * 40_000}]},
                ),
            )

        rebased = self.ledger()
        self.assertNotEqual(first_observation_id, rebased["plan"]["observation_id"])
        self.assertEqual(1, rebased["tool_calls"])
        self.assertEqual(0, rebased["output_bytes"])
        self.assertEqual([], rebased["completed_tool_use_ids"])
        self.assertEqual([], rebased["signals"])

        small_response = {"content": [{"type": "text", "text": "ok"}]}
        self.assertEqual(
            {},
            self.post(
                tool_name,
                concurrent_input,
                "tool-concurrent",
                small_response,
            ),
        )
        self.assertEqual(
            {}, self.pre(tool_name, concurrent_input, "tool-concurrent-repeat")
        )
        self.assertEqual(
            {},
            self.post(
                tool_name,
                concurrent_input,
                "tool-concurrent-repeat",
                small_response,
            ),
        )

        candidates = [
            json.loads(path.read_text("utf-8"))
            for path in (
                self.project
                / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
            ).glob("*.json")
        ]
        self.assertEqual(2, len(candidates))
        self.assertEqual(
            [
                "duplicate_call",
                "large_single_output",
                "output_reference_exceeded",
            ],
            sorted(
                signal
                for candidate in candidates
                for signal in candidate["signals"]
            ),
        )
        self.assertEqual(
            [1, 2], sorted(candidate["tool_calls"] for candidate in candidates)
        )

    def test_rebase_preserves_a_repeated_signal_occurring_after_snapshot(
        self,
    ) -> None:
        tool_name = "mcp__engineering_assistant__engineering_assistant_route"
        tool_input = {"intent": {"task_kind": "review"}}
        small_response = {"content": [{"type": "text", "text": "ok"}]}
        original_collect = FeedbackCollector.collect_usage_efficiency

        self.assertEqual({}, self.pre(tool_name, tool_input, "tool-1"))
        self.assertEqual({}, self.pre(tool_name, tool_input, "tool-2"))
        self.assertEqual(
            {}, self.post(tool_name, tool_input, "tool-1", small_response)
        )

        def collect_after_same_signal(collector, **kwargs):
            self.assertEqual({}, self.pre(tool_name, tool_input, "tool-3"))
            return original_collect(collector, **kwargs)

        with patch.object(
            FeedbackCollector,
            "collect_usage_efficiency",
            autospec=True,
            side_effect=collect_after_same_signal,
        ):
            self.assertEqual(
                {}, self.post(tool_name, tool_input, "tool-2", small_response)
            )

        rebased = self.ledger()
        self.assertEqual(1, rebased["tool_calls"])
        self.assertEqual(["duplicate_call"], rebased["signals"])
        self.assertEqual({"duplicate_call": 1}, rebased["signal_counts"])

        self.assertEqual(
            {}, self.post(tool_name, tool_input, "tool-3", small_response)
        )
        candidates = [
            json.loads(path.read_text("utf-8"))
            for path in (
                self.project
                / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
            ).glob("*.json")
        ]
        self.assertEqual(2, len(candidates))
        self.assertEqual(
            [["duplicate_call"], ["duplicate_call"]],
            sorted(candidate["signals"] for candidate in candidates),
        )
        self.assertEqual(
            [1, 2], sorted(candidate["tool_calls"] for candidate in candidates)
        )

    def test_legacy_ledger_without_signal_counts_is_upgraded_on_mutation(
        self,
    ) -> None:
        tool_name = "mcp__engineering_assistant__engineering_assistant_route"
        tool_input = {"intent": {"task_kind": "review"}}
        self.assertEqual({}, self.pre(tool_name, tool_input, "tool-1"))
        self.assertEqual({}, self.pre(tool_name, tool_input, "tool-2"))

        ledger_path = next(
            (
                self.project
                / ".run-artifacts/engineering-assistant/usage-observations"
            ).rglob("turn-*.json")
        )
        legacy = json.loads(ledger_path.read_text("utf-8"))
        legacy.pop("signal_counts")
        ledger_path.write_text(json.dumps(legacy), encoding="utf-8")

        self.assertEqual({}, self.pre(tool_name, tool_input, "tool-3"))
        upgraded = self.ledger()
        self.assertEqual({"duplicate_call": 2}, upgraded["signal_counts"])

    def test_lookalike_mcp_server_cannot_activate_plugin_observation(self) -> None:
        response = self.pre(
            "mcp__unrelated-server__engineering_assistant_route",
            {"intent": {"task_kind": "review"}},
            "tool-1",
        )

        self.assertEqual({}, response)
        self.assertFalse((self.project / ".run-artifacts/engineering-assistant").exists())

    def test_second_index_query_is_recorded_but_never_denied(self) -> None:
        self.activate()
        first = self.pre("mcp__codegraph__codegraph_explore", {"query": "auth"}, "tool-1")
        second = self.pre("mcp__codegraph__codegraph_explore", {"query": "acl"}, "tool-2")

        self.assertEqual({}, first)
        self.assertEqual({}, second)
        payload = self.ledger()
        self.assertEqual(2, payload["index_queries"])
        self.assertIn("index_query_reference_exceeded", payload["signals"])

    def test_duplicate_tool_input_is_recorded_but_never_denied(self) -> None:
        self.activate()
        command = {"command": "git status --short"}
        self.assertEqual({}, self.pre("Bash", command, "tool-1"))
        self.assertEqual({}, self.pre("Bash", command, "tool-2"))

        payload = self.ledger()
        self.assertEqual(2, payload["tool_calls"])
        self.assertIn("duplicate_call", payload["signals"])

    def test_plugin_skill_self_read_is_recorded_but_never_denied(self) -> None:
        self.activate()
        skill_path = (
            "/tmp/plugins/engineering-assistant/1.0.0/skills/code-review/SKILL.md"
        )
        reference_only = self.pre(
            "Bash",
            {"command": f"test -f '{skill_path}'"},
            "tool-reference-only",
        )
        print_only = self.pre(
            "Bash",
            {"command": f"printf '%s\\n' '{skill_path}'"},
            "tool-print-only",
        )
        quoted_cat = self.pre(
            "Bash",
            {"command": f"echo cat '{skill_path}'"},
            "tool-quoted-cat",
        )
        quoted_sed = self.pre(
            "Bash",
            {"command": f"printf '%s' \"sed -n '1p' '{skill_path}'\""},
            "tool-quoted-sed",
        )
        search_text = self.pre(
            "Bash",
            {"command": f"rg \"sed .* {skill_path}\" tests"},
            "tool-search-text",
        )

        self.assertEqual({}, reference_only)
        self.assertEqual({}, print_only)
        self.assertEqual({}, quoted_cat)
        self.assertEqual({}, quoted_sed)
        self.assertEqual({}, search_text)
        self.assertNotIn("plugin_skill_self_read", self.ledger()["signals"])

        command = {
            "command": f"/bin/zsh -lc \"sed -n '1,240p' '{skill_path}'\""
        }
        response = self.pre("Bash", command, "tool-self-read")

        self.assertEqual({}, response)
        self.assertIn("plugin_skill_self_read", self.ledger()["signals"])

    def test_large_single_output_is_recorded_without_blocking_following_tools(self) -> None:
        self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "使用 $engineering-assistant:code-review 完成代码评审。",
            },
            output_reference=64_000,
        )
        command = {"command": "git diff --stat"}
        self.assertEqual({}, self.pre("Bash", command, "tool-large-output"))

        post = self.post(
            "Bash",
            command,
            "tool-large-output",
            {"output": "x" * 40_000},
        )
        following = self.pre("Bash", {"command": "git log -1"}, "tool-following")

        self.assertEqual({}, post)
        self.assertEqual({}, following)
        signals = self.ledger()["signals"]
        self.assertIn("large_single_output", signals)
        self.assertNotIn("output_reference_exceeded", signals)

    def test_output_reference_never_blocks_current_or_following_tools(self) -> None:
        self.activate()
        command = {"command": "git diff --stat"}
        self.assertEqual({}, self.pre("Bash", command, "tool-1"))

        post = self.post("Bash", command, "tool-1", {"output": "x" * 2048})
        following = self.pre("Bash", {"command": "git log -1"}, "tool-2")

        self.assertEqual({}, post)
        self.assertEqual({}, following)
        payload = self.ledger()
        self.assertGreater(payload["output_bytes"], 1024)
        self.assertIn("output_reference_exceeded", payload["signals"])

    def test_ordinary_task_and_stop_hook_are_complete_no_ops(self) -> None:
        prompt = self.run_hook(
            {"hook_event_name": "UserPromptSubmit", "prompt": "解释这个 Python 函数。"}
        )
        pre = self.pre("Bash", {"command": "git status --short"}, "tool-1")
        stop = self.run_hook(
            {
                "hook_event_name": "Stop",
                "last_assistant_message": "测试失败，需要返工。",
                "stop_hook_active": False,
            }
        )

        self.assertEqual({}, prompt)
        self.assertEqual({}, pre)
        self.assertEqual({}, stop)
        self.assertFalse((self.project / ".run-artifacts/engineering-assistant").exists())

    def test_feedback_summary_is_observation_exempt_in_an_active_turn(self) -> None:
        self.activate()
        before = self.ledger()
        tool_name = (
            "mcp__engineering_assistant__engineering_assistant_feedback_summary"
        )
        tool_input = {"project_root": str(self.project)}

        self.assertFalse(
            should_load_runtime(
                {
                    **self.common,
                    "hook_event_name": "PreToolUse",
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_use_id": "summary-tool",
                }
            )
        )
        self.assertEqual({}, self.pre(tool_name, tool_input, "summary-tool"))
        self.assertEqual(
            {},
            self.post(
                tool_name,
                tool_input,
                "summary-tool",
                {"candidate_count": 0},
            ),
        )
        self.assertEqual(before, self.ledger())
        self.assertEqual(
            {},
            self.run_hook(
                {
                    "hook_event_name": "Stop",
                    "last_assistant_message": "任务已完成。",
                    "stop_hook_active": False,
                }
            ),
        )
        self.assertFalse(
            (
                self.project
                / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
            ).exists()
        )

    def test_feedback_summary_does_not_activate_or_write_in_an_ordinary_turn(
        self,
    ) -> None:
        tool_name = (
            "mcp__engineering_assistant__engineering_assistant_feedback_summary"
        )
        tool_input = {"project_root": str(self.project)}

        self.assertEqual({}, self.pre(tool_name, tool_input, "summary-tool"))
        self.assertEqual(
            {},
            self.post(
                tool_name,
                tool_input,
                "summary-tool",
                {"candidate_count": 0},
            ),
        )
        self.assertFalse((self.project / ".run-artifacts/engineering-assistant").exists())

    def test_describing_the_plugin_without_invoking_it_does_not_activate(self) -> None:
        response = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "engineering-assistant 插件是什么？",
            }
        )

        self.assertEqual({}, response)
        self.assertFalse((self.project / ".run-artifacts/engineering-assistant").exists())

    def test_hypothetical_plugin_mention_does_not_activate(self) -> None:
        prompts = [
            "如果使用 engineering-assistant，会有什么变化？",
            "为什么使用 engineering-assistant？",
            "你不应该使用 engineering-assistant。",
            "不要推荐我使用 engineering-assistant。",
            "不要使用 $engineering-assistant:code-review。",
            "请解释 $engineering-assistant:code-review 是什么。",
            "如果使用 $engineering-assistant 会怎样？",
            "使用 engineering-assistant 插件：这句话是什么意思？",
            "使用 $engineering-assistant 会怎样？",
            "使用 $engineering-assistant 是否安全？",
            "$engineering-assistant:code-review 会做什么？",
            "Use the engineering-assistant plugin: what happens?",
            "do not ever use engineering-assistant",
            "请解释这句话：use engineering-assistant to review the diff",
            "Reference text: then use the engineering-assistant plugin "
            "to review the diff.",
            "For example: inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.",
            "Example: inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.",
            "Just an example: inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.",
            "> Inspect the repository, then use the engineering-assistant "
            "plugin to review the diff.",
            "‘Inspect the repository, then use the engineering-assistant "
            "plugin to review the diff.’",
            "He said 'Inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.'",
            "The quoted command is 'Inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.'",
            "The literal text is `Inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.`",
            "Copy this string: 'Inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.'",
            "例如：先检查仓库，然后使用 "
            "$engineering-assistant:code-review 评审当前 diff。",
            "比如：先检查仓库，然后使用 "
            "$engineering-assistant:code-review 评审 diff。",
            "示例：先检查仓库，然后使用 "
            "$engineering-assistant:code-review 评审 diff。",
            "样例：先检查仓库，然后使用 "
            "$engineering-assistant:code-review 评审 diff。",
            "e.g. inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.",
            "Only when tests fail, inspect the repo, then use the "
            "engineering-assistant plugin to diagnose it.",
            "When tests fail, inspect the repo, then use the "
            "engineering-assistant plugin to diagnose it.",
            "Unless explicitly requested, inspect the repository, then use "
            "the engineering-assistant plugin.",
            "Never inspect the repository and then use the "
            "engineering-assistant plugin automatically.",
            "Agents must not inspect the repository and then use the "
            "engineering-assistant plugin automatically.",
            "Agents should not inspect the repository and then use the "
            "engineering-assistant plugin automatically.",
            "Do not inspect the repository and then use the "
            "engineering-assistant plugin automatically.",
            "Don't inspect the repository and then use the "
            "engineering-assistant plugin automatically.",
            "当测试失败时，先检查仓库，然后使用 "
            "$engineering-assistant:diagnosing-bugs 定位问题。",
            "除非用户明确要求，否则先检查仓库，然后使用 "
            "$engineering-assistant:code-review。",
            "不可以先检查仓库然后使用 "
            "$engineering-assistant:code-review。",
            "Use the engineering-assistant plugin to review this diff; "
            "this is just an example.",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    {},
                    self.run_hook(
                        {"hook_event_name": "UserPromptSubmit", "prompt": prompt}
                    ),
                )
        self.assertFalse((self.project / ".run-artifacts/engineering-assistant").exists())

    def test_explicit_plugin_skill_syntax_activates_observation(self) -> None:
        response = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "请用 $engineering-assistant:code-review 评审当前 diff。",
            }
        )

        self.assertIn("hookSpecificOutput", response)
        self.assertEqual("explicit_prompt", self.ledger()["plan"]["activation_source"])

    def test_common_explicit_plugin_request_prefixes_are_recognized(self) -> None:
        prompts = [
            "明确使用 $engineering-assistant:diagnosing-bugs 完成 smoke。",
            "请在本任务中使用 engineering-assistant 插件完成评审。",
            "我明确要求使用 engineering-assistant 插件完成评审。",
            "请务必使用 engineering-assistant 插件完成评审。",
            "I want you to use the engineering-assistant plugin to review this diff.",
            "Please, use the engineering-assistant plugin to review this diff.",
        ]

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(is_explicit_plugin_request(prompt))

        self.assertTrue(
            is_explicit_plugin_request(
                "明确使用 engineering-assistant 插件完成评审，只有发现问题时才报告。"
            )
        )
        self.assertFalse(
            is_explicit_plugin_request(
                "明确使用 engineering-assistant 插件，作为本测试的输入字符串。"
            )
        )
        self.assertFalse(
            is_explicit_plugin_request(
                "明确使用 engineering-assistant 插件完成评审，"
                "这只是一个示例。"
            )
        )
        self.assertFalse(
            is_explicit_plugin_request(
                "示例输入：“先检查仓库，然后明确使用 "
                "$engineering-assistant:diagnosing-bugs 完成 smoke。”"
            )
        )
        self.assertFalse(
            is_explicit_plugin_request(
                "请记录这个示例：先检查仓库，然后使用 "
                "$engineering-assistant:code-review 评审 diff。"
            )
        )
        for prompt in (
            "Example input: inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.",
            "Reference text: then use the engineering-assistant plugin "
            "to review the diff.",
            "For example: inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.",
            "Example: inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.",
            "Just an example: inspect the repository, then use the "
            "engineering-assistant plugin to review the diff.",
            "> Inspect the repository, then use the engineering-assistant "
            "plugin to review the diff.",
            "‘Inspect the repository, then use the engineering-assistant "
            "plugin to review the diff.’",
            "“先检查仓库，然后使用 "
            "$engineering-assistant:code-review 评审当前 diff。”",
            "'Inspect the repository, then use the engineering-assistant "
            "plugin to review the diff.'",
            "`Inspect the repository, then use the engineering-assistant "
            "plugin to review the diff.`",
            "这是一个示例：先检查仓库，然后使用 "
            "$engineering-assistant:code-review 评审当前 diff。",
            "例如：先检查仓库，然后使用 "
            "$engineering-assistant:code-review 评审当前 diff。",
            "比如：先检查仓库，然后使用 "
            "$engineering-assistant:code-review 评审 diff。",
            "如果先检查仓库，然后使用 "
            "$engineering-assistant:code-review 评审当前 diff。",
            "仅当测试失败时，先检查仓库，然后使用 "
            "$engineering-assistant:diagnosing-bugs 定位问题。",
            "If we inspect the repo first, then use the "
            "engineering-assistant plugin to review the diff.",
            "Only when tests fail, inspect the repo, then use the "
            "engineering-assistant plugin to diagnose it.",
            "When tests fail, inspect the repo, then use the "
            "engineering-assistant plugin to diagnose it.",
            "Unless explicitly requested, inspect the repository, then use "
            "the engineering-assistant plugin.",
            "Never inspect the repository and then use the "
            "engineering-assistant plugin automatically.",
            "Agents must not inspect the repository and then use the "
            "engineering-assistant plugin automatically.",
            "Use the engineering-assistant plugin to review this diff; "
            "this is just an example.",
        ):
            with self.subTest(prompt=prompt):
                self.assertFalse(is_explicit_plugin_request(prompt))
        self.assertTrue(
            is_explicit_plugin_request(
                "明确使用 $engineering-assistant:diagnosing-bugs 完成 smoke，"
                "完成后告诉我是否通过？"
            )
        )
        self.assertTrue(
            is_explicit_plugin_request(
                "请使用 $engineering-assistant:code-review 评审当前 diff，可以吗？"
            )
        )
        self.assertTrue(
            is_explicit_plugin_request(
                "能否使用 $engineering-assistant:code-review 评审当前 diff？"
            )
        )
        self.assertTrue(
            is_explicit_plugin_request(
                "Could you use the engineering-assistant plugin to review this diff?"
            )
        )
        self.assertTrue(
            is_explicit_plugin_request(
                "Let's inspect the repository, then use the "
                "engineering-assistant plugin to review the diff."
            )
        )
        self.assertTrue(
            is_explicit_plugin_request(
                "We'll inspect the repository, then use the "
                "engineering-assistant plugin to review the diff."
            )
        )

    def test_explicit_clause_scope_controls_full_hook_activation(self) -> None:
        response = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": (
                    "明确使用 $engineering-assistant:diagnosing-bugs 完成 smoke，"
                    "只有失败时才报告。"
                ),
            }
        )
        self.assertIn("hookSpecificOutput", response)

        with tempfile.TemporaryDirectory() as temporary:
            other_project = Path(temporary)
            previous = self.common["cwd"]
            self.common["cwd"] = str(other_project)
            try:
                self.assertEqual(
                    {},
                    self.run_hook(
                        {
                            "hook_event_name": "UserPromptSubmit",
                            "prompt": (
                                "明确使用 engineering-assistant 插件，"
                                "作为本测试的输入字符串。"
                            ),
                        }
                    ),
                )
                self.assertFalse(
                    (other_project / ".run-artifacts/engineering-assistant").exists()
                )
            finally:
                self.common["cwd"] = previous

    def test_embedded_command_activates_but_policy_statement_does_not(self) -> None:
        self.assertTrue(
            is_explicit_plugin_request(
                "Please inspect the repository, then use the "
                "engineering-assistant plugin to review the diff."
            )
        )
        self.assertFalse(
            is_explicit_plugin_request(
                "Use the engineering-assistant plugin only if the user "
                "explicitly asks; this is a policy statement."
            )
        )
        self.assertTrue(
            is_explicit_plugin_request(
                "请先查看仓库，然后使用 $engineering-assistant:code-review "
                "评审当前 diff。"
            )
        )
        self.assertFalse(
            is_explicit_plugin_request(
                "使用 engineering-assistant 插件，不是本任务的要求。"
            )
        )
        self.assertFalse(
            is_explicit_plugin_request(
                "Use the engineering-assistant plugin is optional; "
                "do not enable it for this task."
            )
        )
        self.assertTrue(
            is_explicit_plugin_request(
                "Use the engineering-assistant plugin to review this diff; "
                "do not modify files."
            )
        )
        self.assertTrue(
            is_explicit_plugin_request(
                "Use the engineering-assistant plugin to review the security policy."
            )
        )
        self.assertTrue(
            is_explicit_plugin_request(
                "Use the engineering-assistant plugin to review this policy statement."
            )
        )

    def test_explicit_natural_language_plugin_request_activates_observation(self) -> None:
        response = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": (
                    "使用已安装的 engineering-assistant 插件，对当前仓库执行只读评审。"
                ),
            }
        )

        self.assertIn("hookSpecificOutput", response)
        self.assertEqual("explicit_prompt", self.ledger()["plan"]["activation_source"])

    def test_explicit_english_plugin_request_activates_observation(self) -> None:
        response = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": (
                    "Please use the engineering-assistant plugin to review "
                    "this diff."
                ),
            }
        )

        self.assertIn("hookSpecificOutput", response)
        self.assertEqual("explicit_prompt", self.ledger()["plan"]["activation_source"])

    def test_quoted_or_negated_english_plugin_command_does_not_activate(self) -> None:
        prompts = [
            'Explain the phrase "use the engineering-assistant plugin".',
            "Do not use the engineering-assistant plugin for this task.",
        ]

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    {},
                    self.run_hook(
                        {"hook_event_name": "UserPromptSubmit", "prompt": prompt}
                    ),
                )
        self.assertFalse((self.project / ".run-artifacts/engineering-assistant").exists())

    def test_unqualified_skill_name_does_not_claim_plugin_provenance(self) -> None:
        response = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "请用 $research 调研这个问题。",
            }
        )

        self.assertEqual({}, response)
        self.assertFalse((self.project / ".run-artifacts/engineering-assistant").exists())

    def test_unknown_namespaced_skill_does_not_activate_observation(self) -> None:
        response = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "请用 $engineering-assistant:unknown-skill 完成任务。",
            }
        )

        self.assertEqual({}, response)
        self.assertFalse((self.project / ".run-artifacts/engineering-assistant").exists())

    def test_negated_plugin_request_does_not_activate_observation(self) -> None:
        response = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "这个普通任务不要使用 engineering-assistant 插件。",
            }
        )

        self.assertEqual({}, response)
        self.assertFalse((self.project / ".run-artifacts/engineering-assistant").exists())

    def test_activation_is_scoped_to_one_turn(self) -> None:
        self.activate()

        response = self.run_hook(
            {
                "hook_event_name": "PreToolUse",
                "turn_id": "next-ordinary-turn",
                "tool_name": "Bash",
                "tool_input": {"command": "git status --short"},
                "tool_use_id": "tool-next",
            }
        )

        self.assertEqual({}, response)
        ledgers = list(
            (
                self.project
                / ".run-artifacts/engineering-assistant/usage-observations"
            ).rglob("turn-*.json")
        )
        self.assertEqual(1, len(ledgers))

    def test_new_activation_opportunistically_prunes_stale_orphan_ledgers(self) -> None:
        self.activate()
        ledger = next(
            (
                self.project
                / ".run-artifacts/engineering-assistant/usage-observations"
            ).rglob("turn-*.json")
        )
        stale = 1_700_000_000 - STALE_LEDGER_TTL_SECONDS - 1
        os.utime(ledger, (stale, stale))

        self.common["turn_id"] = "new-observation-turn"
        self.activate()

        ledgers = list(
            (
                self.project
                / ".run-artifacts/engineering-assistant/usage-observations"
            ).rglob("turn-*.json")
        )
        self.assertEqual(1, len(ledgers))
        self.assertNotEqual(ledger.name, ledgers[0].name)

    def test_successful_stop_removes_the_empty_session_directory(self) -> None:
        self.activate()
        root = (
            self.project
            / ".run-artifacts/engineering-assistant/usage-observations"
        )
        session_directory = next(path for path in root.iterdir() if path.is_dir())

        self.run_hook(
            {
                "hook_event_name": "Stop",
                "last_assistant_message": "任务已完成。",
                "stop_hook_active": False,
            }
        )

        self.assertFalse(session_directory.exists())

    def test_followup_phrase_without_plugin_provenance_does_not_activate(self) -> None:
        self.activate()

        response = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "turn_id": "followup-turn",
                "prompt": "刚才的实现不对，请改为复用现有接口。",
            }
        )

        self.assertEqual({}, response)
        ledgers = list(
            (
                self.project
                / ".run-artifacts/engineering-assistant/usage-observations"
            ).rglob("turn-*.json")
        )
        self.assertEqual(1, len(ledgers))
        events = list(
            (
                self.project / ".run-artifacts/engineering-assistant/feedback/events"
            ).glob("*.json")
        )
        self.assertEqual(0, len(events))

    def test_intervening_ordinary_turn_closes_plugin_followup_collection(self) -> None:
        self.activate()

        ordinary = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "turn_id": "ordinary-turn",
                "prompt": "请改为解释这个普通 Python 函数。",
            }
        )
        later_correction = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "turn_id": "later-turn",
                "prompt": "刚才的解释不对，请改为逐行说明。",
            }
        )

        self.assertEqual({}, ordinary)
        self.assertEqual({}, later_correction)
        ledgers = list(
            (
                self.project
                / ".run-artifacts/engineering-assistant/usage-observations"
            ).rglob("turn-*.json")
        )
        self.assertEqual(1, len(ledgers))
        self.assertFalse(
            (
                self.project / ".run-artifacts/engineering-assistant/feedback/events"
            ).exists()
        )

    def test_each_new_turn_requires_explicit_plugin_provenance(self) -> None:
        self.activate()

        response = self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "turn_id": "explicit-after-corruption",
                "prompt": "请使用 $engineering-assistant:code-review 继续评审。",
            }
        )

        self.assertIn("hookSpecificOutput", response)
        self.assertEqual(
            2,
            len(
                list(
                    (
                        self.project
                        / ".run-artifacts/engineering-assistant/usage-observations"
                    ).rglob("turn-*.json")
                )
            ),
        )

    def test_failed_tool_result_creates_structured_feedback_without_raw_output(
        self,
    ) -> None:
        self.activate()
        command = {"command": "run-sensitive-command"}
        self.pre("Bash", command, "tool-failed")

        response = self.post(
            "Bash",
            command,
            "tool-failed",
            {"exit_code": 7, "output": "sensitive failure details"},
        )

        self.assertEqual({}, response)
        events = list(
            (
                self.project / ".run-artifacts/engineering-assistant/feedback/events"
            ).glob("*.json")
        )
        self.assertEqual(1, len(events))
        event = json.loads(events[0].read_text(encoding="utf-8"))
        self.assertEqual("tool_failure", event["event_type"])
        self.assertEqual("tool_hook", event["source"])
        self.assertEqual("info", event["severity"])
        self.assertEqual("unknown", event["change_kind"])
        self.assertEqual("reported-tool-failure-shell-nonzero-exit", event["recurrence_key"])
        self.assertEqual(1, len(event["affected_asset_refs"]))
        artifact_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                self.project / ".run-artifacts/engineering-assistant/feedback"
            ).rglob("*.json")
        )
        self.assertNotIn("sensitive failure details", artifact_text)
        self.assertNotIn("run-sensitive-command", artifact_text)

    def test_codex_nested_command_failure_shape_creates_feedback(self) -> None:
        self.activate()
        command = {"command": "failing-command"}
        self.pre("Bash", command, "tool-nested-failure")

        self.assertEqual(
            {},
            self.post(
                "Bash",
                command,
                "tool-nested-failure",
                {
                    "item": {
                        "type": "command_execution",
                        "aggregated_output": "private failure output",
                        "exit_code": 1,
                        "status": "failed",
                    }
                },
            ),
        )

        event = json.loads(
            next(
                (
                    self.project
                    / ".run-artifacts/engineering-assistant/feedback/events"
                ).glob("*.json")
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            "reported-tool-failure-shell-nonzero-exit",
            event["recurrence_key"],
        )
        artifacts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                self.project / ".run-artifacts/engineering-assistant/feedback"
            ).rglob("*.json")
        )
        self.assertNotIn("private failure output", artifacts)

    def test_bash_transport_metadata_failure_shape_creates_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            previous = self.common["cwd"]
            self.common["cwd"] = temporary
            try:
                self.activate()
                command = {"command": "failing-command"}
                self.pre("Bash", command, "tool-transport")
                self.assertEqual(
                    {},
                    self.post(
                        "Bash",
                        command,
                        "tool-transport",
                        {
                            "output": "private metadata output",
                            "metadata": {"exit_code": 2},
                        },
                    ),
                )
                event = json.loads(
                    next(
                        (
                            Path(temporary)
                            / ".run-artifacts/engineering-assistant/feedback/events"
                        ).glob("*.json")
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    "reported-tool-failure-shell-nonzero-exit",
                    event["recurrence_key"],
                )
            finally:
                self.common["cwd"] = previous

    def test_business_failure_fields_are_not_transport_tool_failures(self) -> None:
        self.activate()
        command = {"command": "query-business-data"}
        for index, response in enumerate(
            (
                {"result": {"status": "failed", "records": 0}},
                {
                    "status": "completed",
                    "metadata": {"error": "domain validation message"},
                },
                {
                    "output": (
                        "Process exited with code 7 is the phrase being tested"
                    ),
                    "metadata": {"exit_code": 0},
                },
                "Process exited with code 3\nFinal output:\nordinary tool output",
            )
        ):
            tool_id = f"tool-business-{index}"
            self.pre("Bash", command, tool_id)
            self.assertEqual({}, self.post("Bash", command, tool_id, response))

        self.assertFalse(
            (
                self.project / ".run-artifacts/engineering-assistant/feedback/events"
            ).exists()
        )

    def test_root_transport_failed_status_is_a_tool_failure_signal(self) -> None:
        self.activate()
        command = {"command": "host-reported-failure"}
        self.pre("Bash", command, "tool-root-status")

        self.assertEqual(
            {},
            self.post(
                "Bash",
                command,
                "tool-root-status",
                {"status": "failed", "output": "private host output"},
            ),
        )

        event = json.loads(
            next(
                (
                    self.project
                    / ".run-artifacts/engineering-assistant/feedback/events"
                ).glob("*.json")
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            "reported-tool-failure-shell-tool-error",
            event["recurrence_key"],
        )

    def test_empty_error_container_is_not_a_tool_failure(self) -> None:
        self.activate()
        command = {"command": "successful-command"}
        self.pre("Bash", command, "tool-success")

        self.assertEqual(
            {},
            self.post(
                "Bash",
                command,
                "tool-success",
                {"exit_code": 0, "error": {}, "output": "ok"},
            ),
        )
        self.assertFalse(
            (
                self.project / ".run-artifacts/engineering-assistant/feedback/events"
            ).exists()
        )

    def test_collection_corruption_is_silent_and_never_affects_the_tool(self) -> None:
        self.activate()
        ledgers = list(
            (
                self.project
                / ".run-artifacts/engineering-assistant/usage-observations"
            ).rglob("turn-*.json")
        )
        ledgers[0].write_text("{}", encoding="utf-8")

        response = self.pre("Bash", {"command": "git status --short"}, "tool-1")

        self.assertEqual({}, response)

    def test_oversized_observation_ledger_is_skipped_without_blocking(self) -> None:
        self.activate()
        ledgers = list(
            (
                self.project
                / ".run-artifacts/engineering-assistant/usage-observations"
            ).rglob("turn-*.json")
        )
        ledgers[0].write_text(
            "x" * (MAX_OBSERVATION_LEDGER_BYTES + 1), encoding="utf-8"
        )

        response = self.pre("Bash", {"command": "git status --short"}, "tool-1")

        self.assertEqual({}, response)

    def test_inactive_malformed_hook_input_is_silently_ignored(self) -> None:
        output = io.StringIO()
        code = run_codex_hook(
            input_stream=io.StringIO("not-json"),
            output_stream=output,
            schema_root=ROOT / "schemas",
            environment={},
        )

        self.assertEqual(0, code)
        self.assertEqual({}, json.loads(output.getvalue()))
        self.assertFalse((self.project / ".run-artifacts/engineering-assistant").exists())

    def test_explicit_plugin_hook_fails_open_in_the_author_source_tree(self) -> None:
        author_root = self.project / "author"
        for relative in ("catalog", "skills", "schemas", "src/engineering_assistant"):
            (author_root / relative).mkdir(parents=True, exist_ok=True)
        output = io.StringIO()
        payload = {
            **self.common,
            "cwd": str(author_root),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "使用 engineering-assistant 插件评审当前变更。",
        }

        code = run_codex_hook(
            input_stream=io.StringIO(json.dumps(payload)),
            output_stream=output,
            schema_root=ROOT / "schemas",
            environment={"ENGINEERING_ASSISTANT_FEEDBACK_MODE": "candidates"},
        )

        self.assertEqual(0, code)
        self.assertEqual({}, json.loads(output.getvalue()))
        self.assertFalse((author_root / ".run-artifacts").exists())

    def test_retained_hash_window_is_bounded_without_limiting_tool_calls(self) -> None:
        self.activate()
        total = MAX_RETAINED_TOOL_EVENTS + 5

        for index in range(total):
            self.assertEqual(
                {},
                self.pre(
                    "Bash",
                    {"command": f"printf {index}"},
                    f"tool-{index}",
                ),
            )

        payload = self.ledger()
        self.assertEqual(total, payload["tool_calls"])
        self.assertLessEqual(
            len(payload["tool_use_signatures"]), MAX_RETAINED_TOOL_EVENTS
        )
        self.assertIn("retention_truncated", payload["signals"])

    def test_active_task_feedback_is_collected_after_activation(self) -> None:
        self.activate()
        response = self.run_hook(
            {
                "hook_event_name": "Stop",
                "last_assistant_message": "测试失败，需要返工。",
                "stop_hook_active": False,
            }
        )

        self.assertEqual({}, response)
        captures = list(
            (self.project / ".run-artifacts/engineering-assistant/feedback/captures").glob(
                "*.json"
            )
        )
        self.assertGreaterEqual(len(captures), 1)

    def test_stop_promotes_usage_signals_to_anonymous_nonblocking_feedback(self) -> None:
        self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "请用 $engineering-assistant:code-review 完成代码评审。",
            },
            output_reference=8,
        )
        command = {
            "command": (
                "sed -n '1,240p' "
                "'/tmp/plugins/engineering-assistant/1.0.0/skills/code-review/SKILL.md'"
            )
        }
        self.pre("Bash", command, "tool-efficiency")
        self.post(
            "Bash",
            command,
            "tool-efficiency",
            {"output": "private raw output that must not persist" * 2_000},
        )

        payload = {
            "hook_event_name": "Stop",
            "last_assistant_message": "任务已完成。",
            "stop_hook_active": False,
        }
        self.assertEqual({}, self.run_hook(payload, output_reference=8))
        self.assertEqual({}, self.run_hook(payload, output_reference=8))

        candidates = list(
            (
                self.project
                / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
            ).glob("*.json")
        )
        self.assertEqual(1, len(candidates))
        candidate_text = candidates[0].read_text(encoding="utf-8")
        candidate = json.loads(candidate_text)
        validate_instance(
            candidate,
            load_json(ROOT / "schemas/usage-efficiency-feedback.schema.json"),
            "usage-efficiency-feedback",
        )
        self.assertEqual("stop_hook", candidate["source"])
        self.assertEqual(
            [],
            list(
                (
                    self.project
                    / ".run-artifacts/engineering-assistant/usage-observations"
                ).rglob("turn-*.json")
            ),
        )
        self.assertEqual("pending", candidate["status"])
        self.assertFalse(candidate["reusable_candidate"])
        self.assertIn("large_single_output", candidate["signals"])
        self.assertIn("output_reference_exceeded", candidate["signals"])
        self.assertIn("plugin_skill_self_read", candidate["signals"])
        self.assertNotIn("private raw output", candidate_text)
        self.assertNotIn("code-review/SKILL.md", candidate_text)
        self.assertNotIn("task_digest", candidate)
        self.assertNotIn("session_ref", candidate)
        self.assertNotIn("turn_ref", candidate)
        self.assertNotIn("tool_use_signatures", candidate)
        self.assertNotIn("captured_at", candidate)
        index_payload = json.loads(
            next(
                (
                    self.project
                    / ".run-artifacts/engineering-assistant/feedback/efficiency-candidate-index"
                ).glob("*.json")
            ).read_text(encoding="utf-8")
        )
        self.assertNotIn("candidate_id", index_payload)
        self.assertEqual("committed", index_payload["status"])
        self.assertEqual(candidate["ledger_revision"], index_payload["ledger_revision"])
        self.assertEqual(
            [],
            list(
                (
                    self.project
                    / ".run-artifacts/engineering-assistant/feedback/efficiency-candidate-staging"
                ).glob("*.json")
            ),
        )

    def test_stop_records_tool_without_post_without_blocking(self) -> None:
        self.activate()
        self.assertEqual(
            {},
            self.pre(
                "mcp__codegraph__query",
                {"query": "symbol"},
                "tool-missing-post",
            ),
        )

        self.assertEqual(
            {},
            self.run_hook(
                {
                    "hook_event_name": "Stop",
                    "last_assistant_message": "任务继续完成。",
                    "stop_hook_active": False,
                }
            ),
        )

        candidate = json.loads(
            next(
                (
                    self.project
                    / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
                ).glob("*.json")
            ).read_text(encoding="utf-8")
        )
        self.assertIn("tool_without_post", candidate["signals"])

    def test_failed_candidate_write_is_recovered_by_the_next_stop(self) -> None:
        self.activate()
        command = {"command": "git diff --stat"}
        self.pre("Bash", command, "tool-efficiency-retry")
        self.post(
            "Bash",
            command,
            "tool-efficiency-retry",
            {"output": "x" * 70_000},
        )
        stop = {
            "hook_event_name": "Stop",
            "last_assistant_message": "任务已完成。",
            "stop_hook_active": False,
        }

        with patch(
            "engineering_assistant.runtime.feedback.FeedbackStore.save_efficiency_candidate",
            side_effect=OSError("injected write failure"),
        ):
            self.assertEqual({}, self.run_hook(stop))
        self.assertEqual({}, self.run_hook(stop))

        candidates = list(
            (
                self.project
                / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
            ).glob("*.json")
        )
        self.assertEqual(1, len(candidates))
        index_payload = json.loads(
            next(
                (
                    self.project
                    / ".run-artifacts/engineering-assistant/feedback/efficiency-candidate-index"
                ).glob("*.json")
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("committed", index_payload["status"])

    def test_concurrent_stops_publish_one_efficiency_candidate(self) -> None:
        self.activate()
        command = {"command": "git diff --stat"}
        self.pre("Bash", command, "tool-efficiency-concurrent")
        self.post(
            "Bash",
            command,
            "tool-efficiency-concurrent",
            {"output": "x" * 70_000},
        )
        stop = {
            "hook_event_name": "Stop",
            "last_assistant_message": "任务已完成。",
            "stop_hook_active": False,
        }

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: self.run_hook(stop), range(2)))

        self.assertEqual([{}, {}], responses)
        candidates = list(
            (
                self.project
                / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
            ).glob("*.json")
        )
        self.assertEqual(1, len(candidates))

    def test_commit_failure_reuses_the_staged_candidate_on_retry(self) -> None:
        self.activate()
        command = {"command": "git diff --stat"}
        self.pre("Bash", command, "tool-efficiency-commit-retry")
        self.post(
            "Bash",
            command,
            "tool-efficiency-commit-retry",
            {"output": "x" * 70_000},
        )
        stop = {
            "hook_event_name": "Stop",
            "last_assistant_message": "任务已完成。",
            "stop_hook_active": False,
        }

        with patch(
            "engineering_assistant.runtime.feedback.FeedbackStore.commit_efficiency_observation",
            side_effect=OSError("injected commit failure"),
        ):
            self.assertEqual({}, self.run_hook(stop))
        first_candidate = next(
            (
                self.project
                / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
            ).glob("*.json")
        )
        first_payload = first_candidate.read_text(encoding="utf-8")

        self.assertEqual({}, self.run_hook(stop))

        candidates = list(first_candidate.parent.glob("*.json"))
        self.assertEqual(1, len(candidates))
        self.assertEqual(first_payload, candidates[0].read_text(encoding="utf-8"))

    def test_cleanup_failure_is_recovered_without_republishing(self) -> None:
        self.activate()
        command = {"command": "git diff --stat"}
        self.pre("Bash", command, "tool-efficiency-cleanup-retry")
        self.post(
            "Bash",
            command,
            "tool-efficiency-cleanup-retry",
            {"output": "x" * 70_000},
        )
        stop = {
            "hook_event_name": "Stop",
            "last_assistant_message": "任务已完成。",
            "stop_hook_active": False,
        }

        with patch(
            "engineering_assistant.runtime.feedback.FeedbackStore.cleanup_efficiency_staging",
            side_effect=OSError("injected cleanup failure"),
        ):
            self.assertEqual({}, self.run_hook(stop))
        candidates_dir = (
            self.project
            / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
        )
        staging_dir = (
            self.project
            / ".run-artifacts/engineering-assistant/feedback/efficiency-candidate-staging"
        )
        self.assertEqual(1, len(list(candidates_dir.glob("*.json"))))
        self.assertEqual(1, len(list(staging_dir.glob("*.json"))))

        self.assertEqual({}, self.run_hook(stop))

        self.assertEqual(1, len(list(candidates_dir.glob("*.json"))))
        self.assertEqual([], list(staging_dir.glob("*.json")))

    def test_stop_collection_failure_is_silent_and_never_reinjects_the_model(self) -> None:
        self.activate()
        ledger = next(
            (
                self.project
                / ".run-artifacts/engineering-assistant/usage-observations"
            ).rglob("turn-*.json")
        )
        ledger.write_text("{}", encoding="utf-8")

        response = self.run_hook(
            {
                "hook_event_name": "Stop",
                "last_assistant_message": "任务已完成。",
                "stop_hook_active": False,
            }
        )

        self.assertEqual({}, response)
        self.assertFalse(
            (
                self.project
                / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
            ).exists()
        )

    def test_text_feedback_failure_keeps_ledger_for_stop_retry(self) -> None:
        observation_root = (
            self.project
            / ".run-artifacts/engineering-assistant/usage-observations"
        )
        self.activate()
        command = {"command": "git diff --stat"}
        self.pre("Bash", command, "tool-feedback-retry")
        self.post(
            "Bash",
            command,
            "tool-feedback-retry",
            {"output": "x" * 70_000},
        )
        stop = {
            "hook_event_name": "Stop",
            "last_assistant_message": "当前被测试失败阻断。",
            "stop_hook_active": False,
        }
        with patch(
            "engineering_assistant.runtime.feedback.FeedbackCollector.collect_codex",
            side_effect=OSError("feedback unavailable"),
        ):
            self.assertEqual({}, self.run_hook(stop))
        self.assertEqual(1, len(list(observation_root.rglob("*.json"))))

        self.assertEqual({}, self.run_hook(stop))

        self.assertEqual([], list(observation_root.rglob("*.json")))
        self.assertEqual(
            1,
            len(
                list(
                    (
                        self.project
                        / ".run-artifacts/engineering-assistant/feedback/events"
                    ).glob("*.json")
                )
            ),
        )

    def test_continued_stop_does_not_create_an_efficiency_candidate(self) -> None:
        self.activate()
        command = {"command": "git diff --stat"}
        self.pre("Bash", command, "tool-continuation")
        self.post("Bash", command, "tool-continuation", {"output": "x" * 70_000})

        response = self.run_hook(
            {
                "hook_event_name": "Stop",
                "last_assistant_message": "继续执行。",
                "stop_hook_active": True,
            }
        )

        self.assertEqual({}, response)
        self.assertFalse(
            (
                self.project
                / ".run-artifacts/engineering-assistant/feedback/efficiency-candidates"
            ).exists()
        )

    def test_feedback_redacts_local_paths_and_cloud_access_keys(self) -> None:
        access_key = "AKIA1234567890ABCDEF"
        local_path = "/Users/alice/private/secret.json"
        self.run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": (
                    "使用 $engineering-assistant:code-review，刚才的方案不对，请改为读取 "
                    f"{local_path}，凭据是 {access_key}"
                ),
            }
        )

        artifact_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                self.project / ".run-artifacts/engineering-assistant/feedback"
            ).rglob("*.json")
        )
        self.assertNotIn(access_key, artifact_text)
        self.assertNotIn(local_path, artifact_text)
        self.assertIn("raw hook content was omitted", artifact_text)
        events = list(
            (
                self.project / ".run-artifacts/engineering-assistant/feedback/events"
            ).glob("*.json")
        )
        self.assertEqual(1, len(events))
        event = json.loads(events[0].read_text(encoding="utf-8"))
        self.assertEqual(1, len(event["affected_asset_refs"]))
        self.assertTrue(event["affected_asset_refs"][0].startswith("asset-ref-sha256:"))


if __name__ == "__main__":
    unittest.main()
