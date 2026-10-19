from __future__ import annotations

import json
import hashlib
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.tools.eval_runner import (  # noqa: E402
    _canary_metrics,
    _cell_signature,
    _load_canary_observations,
    _pair_canary_observations,
    _validate_delegation_observation_coverage,
    _validate_reused_ablation_observation_claims,
    assemble_canary_result,
    run_canary_result,
    run_evals,
)
from engineering_assistant.cli import build_parser
from engineering_assistant.tools.cli import command_canary_assemble
from engineering_assistant.tools.cli import command_canary_validate
from engineering_assistant.runtime.validation import ValidationFailure  # noqa: E402


class EvalTests(unittest.TestCase):
    def test_delegation_ablation_rejects_cross_task_run_record_reuse(self) -> None:
        digest = "sha256:" + "a" * 64
        observations = []
        for index in range(5):
            cell = index
            bindings = [
                {
                    "run_id": f"run-{cell}-{arm}",
                    "workload_id": f"workload-{cell}",
                    "repeat_index": 1,
                    "arm_id": arm,
                    "run_record_digest": "sha256:"
                    + hashlib.sha256(f"{cell}:{arm}".encode()).hexdigest(),
                }
                for arm in (
                    "minimum_matrix_inline",
                    "minimum_matrix_risk_delegation",
                    "full_local_control",
                )
            ]
            if index == 1:
                bindings[0]["run_id"] = "run-0-minimum_matrix_inline"
                bindings[0]["run_record_digest"] = "sha256:" + hashlib.sha256(
                    b"0:minimum_matrix_inline"
                ).hexdigest()
            for variant in ("baseline", "candidate"):
                observations.append(
                    {
                        "task_id": f"task-{index}",
                        "variant": variant,
                        "experiment_kind": "delegation_ablation",
                        "experiment_protocol_digest": digest,
                        "workload_digest": "sha256:"
                        + hashlib.sha256(f"workload:{index}".encode()).hexdigest(),
                        "quality_rubric_digest": digest,
                        "environment_digest": digest,
                        "evaluator_id": "blind",
                        "git_ref": "fixed",
                        "execution_config_digest": digest,
                        "ablation_run_bindings": bindings,
                    }
                )
        with self.assertRaisesRegex(ValidationFailure, "cannot be reused"):
            _pair_canary_observations(observations)

    @staticmethod
    def _paired_observations(workload_digests: list[str]) -> list[dict]:
        fixed = "sha256:" + "a" * 64
        observations = []
        for index, workload_digest in enumerate(workload_digests):
            for variant in ("baseline", "candidate"):
                observations.append(
                    {
                        "task_id": f"task-{index}",
                        "variant": variant,
                        "experiment_kind": "paired_canary",
                        "experiment_protocol_digest": fixed,
                        "workload_digest": workload_digest,
                        "quality_rubric_digest": fixed,
                        "environment_digest": fixed,
                        "evaluator_id": "blind",
                        "git_ref": "fixed",
                        "execution_config_digest": fixed,
                    }
                )
        return observations

    def test_canary_requires_five_distinct_workload_digests(self) -> None:
        same = "sha256:" + "1" * 64
        with self.assertRaisesRegex(ValidationFailure, "distinct workloads"):
            _pair_canary_observations(self._paired_observations([same] * 5))

        distinct = [
            "sha256:" + hashlib.sha256(f"workload:{index}".encode()).hexdigest()
            for index in range(5)
        ]
        pairs, task_ids = _pair_canary_observations(
            self._paired_observations(distinct)
        )
        self.assertEqual(10, len(pairs))
        self.assertEqual(5, len(task_ids))

    @staticmethod
    def _delegation_bindings(workload_id: str, repeat: int) -> list[dict]:
        return [
            {
                "run_id": f"{workload_id}-{repeat}-{arm}",
                "workload_id": workload_id,
                "repeat_index": repeat,
                "arm_id": arm,
                "run_record_digest": "sha256:"
                + hashlib.sha256(
                    f"{workload_id}:{repeat}:{arm}".encode()
                ).hexdigest(),
            }
            for arm in (
                "minimum_matrix_inline",
                "minimum_matrix_risk_delegation",
                "full_local_control",
            )
        ]

    def _delegation_observation(
        self,
        *,
        variant: str,
        repeat: int,
        artifact_path: str = "shared.json",
        artifact_payload: bytes = b"shared closure",
    ) -> dict:
        digest = "sha256:" + hashlib.sha256(artifact_payload).hexdigest()
        return {
            "simulation": False,
            "experiment_kind": "delegation_ablation",
            "experiment_protocol_digest": "sha256:" + "a" * 64,
            "arm_id": (
                "full_local_control"
                if variant == "baseline"
                else "minimum_matrix_risk_delegation"
            ),
            "ablation_run_bindings": self._delegation_bindings(
                "workload-1", repeat
            ),
            "task_id": f"task-{repeat}",
            "workload_digest": "sha256:" + "b" * 64,
            "variant": variant,
            "product_repository": "product",
            "git_ref": "fixed",
            "treatment_digest": "sha256:" + "c" * 64,
            "execution_config_digest": "sha256:" + "d" * 64,
            "environment_digest": "sha256:" + "e" * 64,
            "quality_rubric_digest": "sha256:" + "f" * 64,
            "evaluator_id": "blind",
            "started_at": "2026-07-16T00:00:00+00:00",
            "finished_at": "2026-07-16T00:01:00+00:00",
            "artifact_refs": [
                {
                    "path": artifact_path,
                    "digest": digest,
                    "measurement_kinds": ["experiment_protocol"],
                }
            ],
            "assurance": "local_unattested",
        }

    @staticmethod
    def _promotion_projection(observation: dict) -> dict:
        selected = next(
            item
            for item in observation["ablation_run_bindings"]
            if item["arm_id"] == observation["arm_id"]
        )
        blind = {
            "run_id": selected["run_id"],
            "quality_score": 87,
            "blind_blocker_count": 1,
            "blind_major_count": 2,
        }
        return {
            "promotion_attempt_set_digest": "sha256:" + "1" * 64,
            "promotion_attempt_bindings": [selected],
            "quality_attempt_binding": selected,
            "blind_review_binding": blind,
            "input_tokens": 100,
            "noncached_input_tokens": 80,
            "output_tokens": 20,
            "wall_time_milliseconds": 1000,
            "cost_usd_micros": 50,
            "quality_score": 87,
            "blind_blocker_count": 1,
            "blind_major_count": 2,
            "document_noise_units": 3,
            "safety_violations": 2,
            "human_intervention_count": 1,
            "human_rework_minutes": 4,
            "applicable_matrix_cells": 5,
            "closed_matrix_cells": 4,
            "production_contract_failures": 1,
            "quality_blocker_count": 1,
            "quality_major_count": 2,
            "product_gate_failures": 1,
        }

    def _closure_metadata(self, observations: list[dict]) -> dict:
        bindings = observations[0]["ablation_run_bindings"]
        first = observations[0]
        return {
            "protocol_digest": first["experiment_protocol_digest"],
            "protocol_fields": {
                field: first[field]
                for field in (
                    "product_repository",
                    "git_ref",
                    "execution_config_digest",
                    "environment_digest",
                    "quality_rubric_digest",
                )
            },
            "workload_digests": {
                "workload-1": first["workload_digest"]
            },
            "arm_treatments": {
                item["arm_id"]: first["treatment_digest"] for item in bindings
            },
            "included_cells": {
                ("workload-1", 1): _cell_signature(bindings)
            },
            "projections": {
                (
                    item["ablation_run_bindings"][0]["workload_id"],
                    item["ablation_run_bindings"][0]["repeat_index"],
                    item["arm_id"],
                ): self._promotion_projection(item)
                for item in observations
            },
        }

    def test_canary_load_caches_shared_artifacts_and_replays_closure_once(self) -> None:
        payload = b"shared closure"
        observations = {
            "baseline.json": self._delegation_observation(
                variant="baseline", repeat=1, artifact_payload=payload
            ),
            "candidate.json": self._delegation_observation(
                variant="candidate", repeat=1, artifact_payload=payload
            ),
        }
        for observation in observations.values():
            observation.update(self._promotion_projection(observation))

        class FakeArtifacts:
            def __init__(self):
                self.reads = []

            def read_json_limited(self, _limit, *parts):
                return observations[Path(*parts).as_posix()], b""

            def read_bytes_limited(self, _limit, *parts):
                self.reads.append(Path(*parts).as_posix())
                return payload

        artifacts = FakeArtifacts()
        bindings = self._delegation_bindings("workload-1", 1)
        metadata = self._closure_metadata(list(observations.values()))
        with patch("engineering_assistant.tools.eval_runner.validate_instance"), patch(
            "engineering_assistant.tools.eval_runner.validate_canary_measurements"
        ) as measurement_validator, patch(
            "engineering_assistant.tools.eval_runner.validate_measurement_evidence_coverage"
        ), patch(
            "engineering_assistant.tools.eval_runner.validate_ablation_artifact_bindings",
            side_effect=lambda observation, _artifacts: self._promotion_projection(
                observation
            ),
        ) as formal_validator, patch(
            "engineering_assistant.tools.eval_runner._derive_formal_closure_metadata",
            return_value=metadata,
        ), patch(
            "engineering_assistant.tools.eval_runner._validate_reused_ablation_observation_claims"
        ) as reused_claim_validator:
            loaded = _load_canary_observations(
                artifacts,
                list(observations),
            )

        self.assertEqual(2, len(loaded))
        self.assertEqual(["shared.json"], artifacts.reads)
        self.assertEqual(2, measurement_validator.call_count)
        formal_validator.assert_called_once()
        reused_claim_validator.assert_called_once()

    def test_canary_load_does_not_reuse_a_different_closure_descriptor(self) -> None:
        payloads = {
            "first.json": b"first closure",
            "second.json": b"second closure",
        }
        observations = {
            "baseline.json": self._delegation_observation(
                variant="baseline",
                repeat=1,
                artifact_path="first.json",
                artifact_payload=payloads["first.json"],
            ),
            "candidate.json": self._delegation_observation(
                variant="candidate",
                repeat=1,
                artifact_path="second.json",
                artifact_payload=payloads["second.json"],
            ),
        }
        for observation in observations.values():
            observation.update(self._promotion_projection(observation))
        metadata = self._closure_metadata(list(observations.values()))

        class FakeArtifacts:
            def read_json_limited(self, _limit, *parts):
                return observations[Path(*parts).as_posix()], b""

            def read_bytes_limited(self, _limit, *parts):
                return payloads[Path(*parts).as_posix()]

        with patch("engineering_assistant.tools.eval_runner.validate_instance"), patch(
            "engineering_assistant.tools.eval_runner.validate_canary_measurements"
        ), patch(
            "engineering_assistant.tools.eval_runner.validate_measurement_evidence_coverage"
        ), patch(
            "engineering_assistant.tools.eval_runner.validate_ablation_artifact_bindings",
            side_effect=lambda observation, _artifacts: self._promotion_projection(
                observation
            ),
        ) as formal_validator, patch(
            "engineering_assistant.tools.eval_runner._derive_formal_closure_metadata",
            return_value=metadata,
        ), patch(
            "engineering_assistant.tools.eval_runner._validate_delegation_observation_coverage"
        ):
            _load_canary_observations(
                FakeArtifacts(),
                list(observations),
            )

        self.assertEqual(2, formal_validator.call_count)

    def test_delegation_requires_every_included_repeat_pair(self) -> None:
        descriptor = ("closure",)
        bindings = {
            repeat: self._delegation_bindings("workload-1", repeat)
            for repeat in (1, 2)
        }
        metadata = {
            "included_cells": {
                ("workload-1", repeat): _cell_signature(items)
                for repeat, items in bindings.items()
            }
        }

        def observation(repeat: int, variant: str) -> dict:
            item = self._delegation_observation(
                variant=variant, repeat=repeat
            )
            item["ablation_run_bindings"] = bindings[repeat]
            return item

        incomplete = [
            (observation(1, variant), descriptor, metadata)
            for variant in ("baseline", "candidate")
        ]
        with self.assertRaisesRegex(ValidationFailure, "every audit-included repeat"):
            _validate_delegation_observation_coverage(incomplete)

        complete = [
            (observation(repeat, variant), descriptor, metadata)
            for repeat in (1, 2)
            for variant in ("baseline", "candidate")
        ]
        _validate_delegation_observation_coverage(complete)
        with self.assertRaisesRegex(ValidationFailure, "exactly one"):
            _validate_delegation_observation_coverage(
                [*complete, complete[-1]]
            )
        with self.assertRaisesRegex(ValidationFailure, "inconsistent audit closures"):
            _validate_delegation_observation_coverage(
                [complete[0], (complete[1][0], ("other-closure",), metadata)]
            )

    def test_reused_closure_still_validates_each_observation_claim(self) -> None:
        observation = self._delegation_observation(
            variant="candidate", repeat=1
        )
        bindings = observation["ablation_run_bindings"]
        metadata = {
            "protocol_digest": observation["experiment_protocol_digest"],
            "protocol_fields": {
                field: observation[field]
                for field in (
                    "product_repository",
                    "git_ref",
                    "execution_config_digest",
                    "environment_digest",
                    "quality_rubric_digest",
                )
            },
            "workload_digests": {
                "workload-1": observation["workload_digest"]
            },
            "arm_treatments": {
                observation["arm_id"]: observation["treatment_digest"]
            },
            "included_cells": {
                ("workload-1", 1): _cell_signature(bindings)
            },
        }
        projection = self._promotion_projection(observation)
        observation.update(projection)
        metadata["projections"] = {
            ("workload-1", 1, observation["arm_id"]): projection
        }
        _validate_reused_ablation_observation_claims(observation, metadata)
        observation["treatment_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValidationFailure, "treatment"):
            _validate_reused_ablation_observation_claims(observation, metadata)

    def test_reused_closure_rejects_tampered_candidate_projection_fields(self) -> None:
        baseline = self._delegation_observation(variant="baseline", repeat=1)
        candidate = self._delegation_observation(variant="candidate", repeat=1)
        for observation in (baseline, candidate):
            observation.update(self._promotion_projection(observation))
        metadata = self._closure_metadata([baseline, candidate])
        payload = b"shared closure"

        class FakeArtifacts:
            def __init__(self, observations):
                self.observations = observations

            def read_json_limited(self, _limit, *parts):
                return self.observations[Path(*parts).as_posix()], b""

            def read_bytes_limited(self, _limit, *_parts):
                return payload

        tampering = {
            "input_tokens": 1,
            "cost_usd_micros": 0,
            "safety_violations": 0,
            "quality_score": 100,
        }
        for field, forged in tampering.items():
            with self.subTest(field=field):
                probe = dict(candidate)
                probe[field] = forged
                observations = {
                    "baseline.json": dict(baseline),
                    "candidate.json": probe,
                }
                with patch(
                    "engineering_assistant.tools.eval_runner.validate_instance"
                ), patch(
                    "engineering_assistant.tools.eval_runner.validate_canary_measurements"
                ), patch(
                    "engineering_assistant.tools.eval_runner.validate_measurement_evidence_coverage"
                ), patch(
                    "engineering_assistant.tools.eval_runner.validate_ablation_artifact_bindings",
                    return_value=self._promotion_projection(baseline),
                ), patch(
                    "engineering_assistant.tools.eval_runner._derive_formal_closure_metadata",
                    return_value=metadata,
                ):
                    with self.assertRaisesRegex(
                        ValidationFailure, f"observation {field}"
                    ):
                        _load_canary_observations(
                            FakeArtifacts(observations),
                            list(observations),
                        )

    def test_all_included_repeats_contribute_to_efficiency_metrics(self) -> None:
        digest = "sha256:" + "b" * 64

        def metrics_observation(task_id: str, repeat: int, variant: str) -> dict:
            baseline = variant == "baseline"
            return {
                "task_id": task_id,
                "variant": variant,
                "experiment_kind": "delegation_ablation",
                "workload_digest": digest,
                "ablation_run_bindings": self._delegation_bindings(
                    "workload-1", repeat
                ),
                "input_tokens": 100 if baseline or repeat == 1 else 130,
                "noncached_input_tokens": 50,
                "output_tokens": 20,
                "wall_time_milliseconds": 1000,
                "cost_usd_micros": 100,
                "document_noise_units": 100,
                "quality_score": 80,
                "safety_violations": 0,
                "blind_blocker_count": 0,
                "blind_major_count": 0,
                "applicable_matrix_cells": 1,
                "closed_matrix_cells": 1,
                "production_contract_failures": 0,
            }

        pairs = {
            (task_id, variant): metrics_observation(task_id, repeat, variant)
            for task_id, repeat in (("repeat-1", 1), ("repeat-2", 2))
            for variant in ("baseline", "candidate")
        }
        metrics = _canary_metrics(pairs, {"repeat-1", "repeat-2"})
        unfavorable = next(
            item
            for item in metrics["workload_efficiency"]
            if item["task_id"] == "repeat-2"
        )
        self.assertEqual(digest, unfavorable["workload_digest"])
        self.assertEqual("workload-1", unfavorable["workload_id"])
        self.assertIn(
            "total_input_token_reduction_ratio",
            unfavorable["overhead_fields"],
        )

    def test_cli_exposes_local_canary_assembly(self) -> None:
        args = build_parser().parse_args(
            [
                "canary-assemble",
                "--evidence-root",
                "/tmp/canary-bundle",
                "--evidence-ref",
                "observations/baseline.json",
                "--evidence-ref",
                "observations/candidate.json",
                "--output",
                "canary-result.json",
            ]
        )

        self.assertEqual("canary-assemble", args.command)
        self.assertEqual(2, len(args.evidence_ref))
        self.assertFalse(hasattr(args, "attestation"))

    def test_canary_assembly_never_overwrites_a_concurrent_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def competing_writer(*_args, **_kwargs):
                (root / "canary-result.json").write_text(
                    '{"winner":"other"}\n', encoding="utf-8"
                )
                return {"winner": "ours"}

            args = SimpleNamespace(
                repository_root=str(ROOT),
                evidence_root=str(root),
                evidence_ref=["baseline.json", "candidate.json"],
                output="canary-result.json",
            )
            with patch(
                "engineering_assistant.tools.cli.assemble_canary_result",
                side_effect=competing_writer,
            ):
                with self.assertRaisesRegex(ValidationFailure, "already exists"):
                    command_canary_assemble(args)
            self.assertEqual(
                '{"winner":"other"}\n',
                (root / "canary-result.json").read_text(encoding="utf-8"),
            )

    def test_canary_validate_returns_nonzero_when_thresholds_fail(self) -> None:
        args = SimpleNamespace(
            result="/tmp/canary-result.json",
        )
        with redirect_stdout(io.StringIO()):
            with patch(
                "engineering_assistant.tools.cli.run_canary_result",
                return_value={"status": "failed", "quality_delta_points": -3},
            ):
                self.assertEqual(2, command_canary_validate(args))
            with patch(
                "engineering_assistant.tools.cli.run_canary_result",
                return_value={"status": "passed"},
            ):
                self.assertEqual(0, command_canary_validate(args))

    def test_canary_efficiency_and_quality_thresholds_cannot_be_soft_passed(self) -> None:
        from engineering_assistant.tools.eval_runner import canary_threshold_failures

        passing = {
            "quality_delta_points": -2,
            "worst_workload_quality_delta_points": -5,
            "total_input_token_reduction_ratio": 0,
            "noncached_input_token_reduction_ratio": 0,
            "output_token_reduction_ratio": 0,
            "wall_time_reduction_ratio": 0,
            "worst_workload_total_input_token_reduction_ratio": 0,
            "worst_workload_noncached_input_token_reduction_ratio": 0,
            "worst_workload_output_token_reduction_ratio": 0,
            "worst_workload_wall_time_reduction_ratio": 0,
            "cost_reduction_ratio": 0.25,
            "document_noise_reduction_ratio": 0.30,
            "safety_violations": 0,
            "blind_blocker_count": 0,
            "blind_major_count": 0,
            "open_matrix_cells": 0,
            "production_contract_failures": 0,
        }
        self.assertEqual([], canary_threshold_failures(passing))
        floating_boundary = dict(passing)
        floating_boundary["total_input_token_reduction_ratio"] = 1 - 130 / 100
        self.assertEqual(
            ["total_input_token_reduction_ratio"],
            canary_threshold_failures(floating_boundary),
        )
        huge_integer = dict(passing)
        huge_integer["safety_violations"] = 10**4000
        self.assertEqual(
            ["safety_violations"], canary_threshold_failures(huge_integer)
        )
        nonfinite = dict(passing)
        nonfinite["quality_delta_points"] = float("nan")
        self.assertEqual(
            ["quality_delta_points"],
            canary_threshold_failures(nonfinite),
        )

        limits = {
            "quality_delta_points": -2.01,
            "worst_workload_quality_delta_points": -5.01,
            "total_input_token_reduction_ratio": -0.001,
            "noncached_input_token_reduction_ratio": -0.001,
            "output_token_reduction_ratio": -0.001,
            "wall_time_reduction_ratio": -0.001,
            "worst_workload_total_input_token_reduction_ratio": -0.001,
            "worst_workload_noncached_input_token_reduction_ratio": -0.001,
            "worst_workload_output_token_reduction_ratio": -0.001,
            "worst_workload_wall_time_reduction_ratio": -0.001,
            "cost_reduction_ratio": 0.249,
            "document_noise_reduction_ratio": 0.299,
            "safety_violations": 1,
            "blind_blocker_count": 1,
            "blind_major_count": 1,
            "open_matrix_cells": 1,
            "production_contract_failures": 1,
        }
        self.assertEqual(
            sorted(limits),
            canary_threshold_failures(limits),
        )

    def test_canary_assembly_rejects_an_author_source_evidence_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            author = Path(temporary) / "author"
            for relative in (
                "catalog",
                "skills",
                "schemas",
                "src/engineering_assistant",
            ):
                (author / relative).mkdir(parents=True, exist_ok=True)
            args = SimpleNamespace(
                repository_root=str(ROOT),
                evidence_root=str(author),
                evidence_ref=["baseline.json", "candidate.json"],
                output="canary-result.json",
            )

            with self.assertRaisesRegex(
                ValidationFailure, "author or installed plugin tree"
            ):
                command_canary_assemble(args)

    def test_real_routing_behavior_state_and_replay_gates(self) -> None:
        report = run_evals(ROOT)
        self.assertFalse(report["simulation"])
        self.assertGreaterEqual(report["routing"]["case_count"], 100)
        self.assertGreaterEqual(report["routing"]["top1_accuracy"], 0.90)
        self.assertLessEqual(report["routing"]["no_result_ratio"], 0.05)
        self.assertEqual(0, report["routing"]["unconfirmed_high_risk_writes"])
        self.assertEqual(1.0, report["behavior"]["pass_ratio"])
        self.assertEqual(1.0, report["state_machine"]["pass_ratio"])
        self.assertEqual(1.0, report["replay"]["pass_ratio"])
        self.assertEqual(4, report["capabilities"]["case_count"])
        self.assertEqual(1.0, report["capabilities"]["pass_ratio"])
        self.assertEqual(
            "selected_runtime_mechanisms_only",
            report["capabilities"]["coverage_claim"],
        )
        self.assertEqual(
            set(report["capabilities"]["required_mechanisms"]),
            {item["capability"] for item in report["capabilities"]["results"]},
        )
        self.assertEqual("not_run", report["canary"]["status"])

    def test_canary_rejects_simulated_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "canary.json"
            path.write_text(
                json.dumps(
                    {
                        "simulation": True,
                        "product_repository": "product",
                        "baseline_ref": "base",
                        "candidate_ref": "candidate",
                        "quality_delta_points": 0,
                        "cost_reduction_ratio": 0.3,
                        "document_noise_reduction_ratio": 0.4,
                        "safety_violations": 0,
                        "blind_blocker_count": 0,
                        "blind_major_count": 0,
                        "open_matrix_cells": 0,
                        "production_contract_failures": 0,
                        "evidence_refs": ["observed:test"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValidationFailure):
                run_canary_result(
                    path,
                )

    def test_legacy_paired_canary_cannot_be_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_refs = []
            digest = "sha256:" + "a" * 64
            for index in range(5):
                for variant in ("baseline", "candidate"):
                    artifact = root / f"{variant}-{index}.log"
                    artifact.write_text(
                        f"observed {variant} {index}\n", encoding="utf-8"
                    )
                    artifact_digest = "sha256:" + hashlib.sha256(
                        artifact.read_bytes()
                    ).hexdigest()
                    evidence = root / f"{variant}-{index}.json"
                    evidence.write_text(
                        json.dumps(
                            {
                                "simulation": False,
                                "experiment_kind": "paired_canary",
                                "experiment_protocol_digest": digest,
                                "arm_id": variant,
                                "task_id": f"task-{index}",
                                "workload_digest": "sha256:"
                                + hashlib.sha256(
                                    f"workload:{index}".encode()
                                ).hexdigest(),
                                "variant": variant,
                                "product_repository": "product",
                                "git_ref": "base",
                                "treatment_digest": "sha256:"
                                + ("b" if variant == "baseline" else "c") * 64,
                                "execution_config_digest": digest,
                                "environment_digest": digest,
                                "quality_rubric_digest": digest,
                                "evaluator_id": "ci-quality-evaluator",
                                "started_at": "2026-07-11T00:00:00+00:00",
                                "finished_at": "2026-07-11T00:10:00+00:00",
                                "input_tokens": 60 if variant == "baseline" else 43,
                                "noncached_input_tokens": 0,
                                "output_tokens": 0,
                                "wall_time_milliseconds": 600_000,
                                "cost_usd_micros": 100 if variant == "baseline" else 73,
                                "quality_score": 80 if variant == "baseline" else 78.5,
                                "document_noise_units": 100 if variant == "baseline" else 69,
                                "safety_violations": 0,
                                "blind_blocker_count": 0,
                                "blind_major_count": 0,
                                "applicable_matrix_cells": 4,
                                "closed_matrix_cells": 4,
                                "production_contract_failures": 0,
                                "artifact_refs": [
                                    {
                                        "path": artifact.name,
                                        "digest": artifact_digest,
                                        "measurement_kinds": [
                                            "usage",
                                            "timing",
                                            "billing",
                                            "quality_evaluation",
                                            "document_noise",
                                            "safety_audit",
                                        ],
                                    }
                                ],
                                "assurance": "local_unattested",
                            }
                        ),
                        encoding="utf-8",
                    )
                    evidence_refs.append(evidence.name)
            with self.assertRaisesRegex(ValidationFailure, "legacy.*not promotable"):
                assemble_canary_result(
                    root,
                    evidence_refs,
                )
            return
            self.assertEqual("product", assembled["product_repository"])
            self.assertEqual("base", assembled["baseline_ref"])
            self.assertEqual("base", assembled["candidate_ref"])
            self.assertNotEqual(
                assembled["baseline_treatment_digest"],
                assembled["candidate_treatment_digest"],
            )
            self.assertAlmostEqual(-1.5, assembled["quality_delta_points"])
            self.assertAlmostEqual(
                -1.5,
                assembled["worst_workload_quality_delta_points"],
            )
            self.assertAlmostEqual(
                1 - 43 / 60,
                assembled["total_input_token_reduction_ratio"],
            )
            self.assertAlmostEqual(
                0,
                assembled["noncached_input_token_reduction_ratio"],
            )
            self.assertAlmostEqual(
                0,
                assembled["output_token_reduction_ratio"],
            )
            self.assertAlmostEqual(0, assembled["wall_time_reduction_ratio"])
            self.assertAlmostEqual(0.27, assembled["cost_reduction_ratio"])
            with patch(
                "engineering_assistant.tools.canary_limits.MAX_TOTAL_ARTIFACTS",
                9,
            ), self.assertRaisesRegex(ValidationFailure, "too many artifacts"):
                assemble_canary_result(
                    root,
                    evidence_refs,
                )

            incomplete_mapping_path = root / "candidate-0.json"
            original_mapping_payload = incomplete_mapping_path.read_text(
                encoding="utf-8"
            )
            incomplete_mapping = json.loads(original_mapping_payload)
            incomplete_mapping["artifact_refs"][0]["measurement_kinds"] = [
                "usage"
            ]
            incomplete_mapping_path.write_text(
                json.dumps(incomplete_mapping), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ValidationFailure,
                "measurement artifact coverage",
            ):
                assemble_canary_result(
                    root,
                    evidence_refs,
                )
            incomplete_mapping_path.write_text(
                original_mapping_payload, encoding="utf-8"
            )

            originals = {}
            for evidence_ref in evidence_refs:
                if not evidence_ref.startswith("candidate-"):
                    continue
                evidence_path = root / evidence_ref
                originals[evidence_ref] = evidence_path.read_text(encoding="utf-8")
                observation = json.loads(originals[evidence_ref])
                observation["treatment_digest"] = "sha256:" + "b" * 64
                evidence_path.write_text(json.dumps(observation), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "treatment"):
                assemble_canary_result(
                    root,
                    evidence_refs,
                )
            for evidence_ref, payload in originals.items():
                (root / evidence_ref).write_text(payload, encoding="utf-8")

            result = root / "canary.json"
            result.write_text(json.dumps(assembled), encoding="utf-8")
            report = run_canary_result(
                result,
            )
            self.assertEqual("passed", report["status"])
            self.assertEqual(5, report["task_count"])
            self.assertEqual(5, len(report["workload_efficiency"]))

            inflated_baseline_path = root / "baseline-0.json"
            inflated_candidate_path = root / "candidate-0.json"
            inflated_baseline_original = inflated_baseline_path.read_text(
                encoding="utf-8"
            )
            inflated_candidate_original = inflated_candidate_path.read_text(
                encoding="utf-8"
            )
            inflated_baseline = json.loads(inflated_baseline_original)
            inflated_candidate = json.loads(inflated_candidate_original)
            inflated_baseline.update(
                {
                    "input_tokens": 2_000_000_000,
                    "noncached_input_tokens": 0,
                    "output_tokens": 0,
                }
            )
            inflated_candidate.update(
                {
                    "input_tokens": 2_000_000_001,
                    "noncached_input_tokens": 0,
                    "output_tokens": 0,
                }
            )
            inflated_baseline_path.write_text(
                json.dumps(inflated_baseline), encoding="utf-8"
            )
            inflated_candidate_path.write_text(
                json.dumps(inflated_candidate), encoding="utf-8"
            )
            inflated_result = assemble_canary_result(
                root,
                evidence_refs,
            )
            self.assertGreater(
                inflated_result["total_input_token_reduction_ratio"], 0
            )
            self.assertLess(
                inflated_result[
                    "worst_workload_total_input_token_reduction_ratio"
                ],
                0,
            )
            inflated_result_path = root / "inflated-canary.json"
            inflated_result_path.write_text(
                json.dumps(inflated_result), encoding="utf-8"
            )
            inflated_report = run_canary_result(
                inflated_result_path,
            )
            self.assertEqual("failed", inflated_report["status"])
            self.assertIn(
                "worst_workload_total_input_token_reduction_ratio",
                inflated_report["threshold_failures"],
            )
            task_zero_efficiency = next(
                item
                for item in inflated_result["workload_efficiency"]
                if item["task_id"] == "task-0"
            )
            self.assertEqual(
                ["total_input_token_reduction_ratio"],
                task_zero_efficiency["overhead_fields"],
            )
            self.assertEqual(
                0, task_zero_efficiency["noncached_input_token_reduction_ratio"]
            )
            self.assertEqual(
                0, task_zero_efficiency["output_token_reduction_ratio"]
            )
            inflated_baseline_path.write_text(
                inflated_baseline_original, encoding="utf-8"
            )
            inflated_candidate_path.write_text(
                inflated_candidate_original, encoding="utf-8"
            )

            artifact = root / "candidate-0.log"
            original_artifact = artifact.read_text(encoding="utf-8")
            artifact.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "digest"):
                run_canary_result(
                    result,
                )
            artifact.write_text(original_artifact, encoding="utf-8")

            observation_path = root / "candidate-0.json"
            original_observation = observation_path.read_text(encoding="utf-8")
            observation = json.loads(original_observation)
            observation["execution_config_digest"] = "sha256:" + "b" * 64
            observation_path.write_text(json.dumps(observation), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "execution config"):
                run_canary_result(
                    result,
                )
            observation_path.write_text(original_observation, encoding="utf-8")

            observation = json.loads(original_observation)
            observation["git_ref"] = "different-ref"
            observation_path.write_text(json.dumps(observation), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "git refs"):
                run_canary_result(
                    result,
                )
            observation_path.write_text(original_observation, encoding="utf-8")

            forged = json.loads(result.read_text(encoding="utf-8"))
            forged["cost_reduction_ratio"] = 0.5
            result.write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "does not match"):
                run_canary_result(
                    result,
                )


if __name__ == "__main__":
    unittest.main()
