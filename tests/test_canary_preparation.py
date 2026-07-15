from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CANARY_BROKER_ID = "enterprise-evidence"
CANARY_HOST_CONFIG_DIGEST = "sha256:" + "c" * 64
IMPORT_TRUST = {
    "evidence_broker_id": CANARY_BROKER_ID,
    "host_trust_config_digest": CANARY_HOST_CONFIG_DIGEST,
}
VALIDATION_TRUST = {
    "expected_evidence_broker_id": CANARY_BROKER_ID,
    "expected_host_trust_config_digest": CANARY_HOST_CONFIG_DIGEST,
}

from engineering_assistant.artifact_io import ArtifactIO  # noqa: E402
from engineering_assistant.canary import (  # noqa: E402
    import_canary_attestation,
    prepare_canary_bundle,
)
from engineering_assistant.cli import build_parser  # noqa: E402
from engineering_assistant.eval_runner import (  # noqa: E402
    assemble_canary_result,
    run_canary_result,
)
from engineering_assistant.validation import ValidationFailure  # noqa: E402
from engineering_assistant.trust import (  # noqa: E402
    ExternalTrustVerifier,
    canary_observation_claims,
)


class CanaryPreparationTests(unittest.TestCase):
    class CanaryVerifier:
        def verify_canary_observation(self, observation) -> bool:
            return observation.get("attestation") == "trusted-canary-receipt"

    class BrokerResponse:
        def __init__(self, claims: dict) -> None:
            self.payload = json.dumps(
                {"active": True, "claims": claims}
            ).encode("utf-8")
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            if size < 0:
                size = len(self.payload) - self.offset
            chunk = self.payload[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    def manifest(self, artifact: Path, **overrides) -> dict:
        digest = "sha256:" + "a" * 64
        run = {
            "task_id": "task-1",
            "workload_digest": digest,
            "variant": "candidate",
            "git_ref": "candidate-ref",
            "treatment_digest": "sha256:" + "b" * 64,
            "execution_config_digest": digest,
            "environment_digest": digest,
            "quality_rubric_digest": digest,
            "evaluator_id": "independent-quality-evaluator",
            "started_at": "2026-07-14T00:00:00+00:00",
            "finished_at": "2026-07-14T00:10:00+00:00",
            "input_tokens": 100,
            "output_tokens": 20,
            "cost_usd_micros": 250,
            "quality_score": 92.5,
            "document_noise_units": 8,
            "safety_violations": 0,
            "artifact_paths": [artifact.name],
            "artifact_measurements": {
                artifact.name: [
                    "usage",
                    "billing",
                    "quality_evaluation",
                    "document_noise",
                    "safety_audit",
                ]
            },
        }
        run.update(overrides)
        if "artifact_paths" in overrides and "artifact_measurements" not in overrides:
            run["artifact_measurements"] = {
                path: [
                    "usage",
                    "billing",
                    "quality_evaluation",
                    "document_noise",
                    "safety_audit",
                ]
                for path in run["artifact_paths"]
            }
        return {
            "schema_version": "1.0",
            "product_repository": "ai-platform",
            "runs": [run],
        }

    def test_prepare_copies_artifacts_and_emits_unsigned_claims_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text('{"type":"turn.completed"}\n', encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(self.manifest(artifact)), encoding="utf-8")
            output = root / "bundle"

            report = prepare_canary_bundle(
                manifest,
                output,
                repository_root=ROOT,
                **IMPORT_TRUST,
            )

            self.assertEqual("awaiting_attestation", report["status"])
            self.assertEqual(1, report["draft_count"])
            self.assertEqual([], report["incomplete_runs"])
            draft_path = output / report["draft_refs"][0]
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual("awaiting_attestation", draft["status"])
            self.assertEqual([], draft["missing_fields"])
            self.assertNotIn("attestation", draft["observation"])
            self.assertNotIn("attestation", json.dumps(draft["claims"]))
            copied = output / draft["observation"]["artifact_refs"][0]["path"]
            self.assertEqual(artifact.read_bytes(), copied.read_bytes())
            self.assertEqual(
                "sha256:" + hashlib.sha256(copied.read_bytes()).hexdigest(),
                draft["observation"]["artifact_refs"][0]["digest"],
            )
            self.assertEqual(
                [
                    "billing",
                    "document_noise",
                    "quality_evaluation",
                    "safety_audit",
                    "usage",
                ],
                draft["observation"]["artifact_refs"][0]["measurement_kinds"],
            )
            self.assertFalse((output / "canary-result.json").exists())

    def test_prepare_rejects_measurements_without_mapped_artifact_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            payload = self.manifest(artifact)
            payload["runs"][0]["artifact_measurements"][artifact.name] = ["usage"]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                ValidationFailure,
                "measurement artifact coverage",
            ):
                prepare_canary_bundle(
                    manifest,
                    root / "bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

    def test_missing_real_measurements_stays_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            payload = self.manifest(artifact)
            del payload["runs"][0]["cost_usd_micros"]
            del payload["runs"][0]["quality_score"]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            report = prepare_canary_bundle(
                manifest,
                root / "bundle",
                repository_root=ROOT,
                **IMPORT_TRUST,
            )

            self.assertEqual("incomplete", report["status"])
            self.assertEqual(
                ["cost_usd_micros", "quality_score"],
                report["incomplete_runs"][0]["missing_fields"],
            )

    def test_prepare_claims_are_the_exact_claims_verified_after_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(self.manifest(artifact)), encoding="utf-8"
            )
            bundle = root / "bundle"
            report = prepare_canary_bundle(
                manifest,
                bundle,
                repository_root=ROOT,
                **IMPORT_TRUST,
            )
            draft_ref = report["draft_refs"][0]
            draft_path = bundle / draft_ref
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "evidence_broker_id": CANARY_BROKER_ID,
                    "host_trust_config_digest": CANARY_HOST_CONFIG_DIGEST,
                },
                draft["observation"]["trust_provenance"],
            )
            self.assertEqual(
                canary_observation_claims(draft["observation"]),
                draft["claims"],
            )
            response_ref = "attestations/response.json"
            ArtifactIO(bundle, ".").create_immutable_json(
                {
                    "schema_version": "1.0",
                    "draft_digest": "sha256:"
                    + hashlib.sha256(draft_path.read_bytes()).hexdigest(),
                    "attestation": "trusted-canary-receipt",
                },
                *Path(response_ref).parts,
            )
            verifier = ExternalTrustVerifier(
                evidence_broker={
                    "enabled": True,
                    "id": CANARY_BROKER_ID,
                    "introspection_url": "https://broker.example/canary",
                    "timeout_seconds": 5,
                },
                approval_broker={"enabled": False},
            )
            with mock.patch(
                "urllib.request.urlopen",
                return_value=self.BrokerResponse(draft["claims"]),
            ):
                imported = import_canary_attestation(
                    bundle,
                    draft_ref,
                    response_ref,
                    "observations/run.json",
                    trust_verifier=verifier,
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )
            self.assertEqual("imported", imported["status"])

    def test_canary_writes_reject_a_separate_author_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            author = root / "other-author-tree"
            for relative in (
                "catalog",
                "skills",
                "schemas",
                "src/engineering_assistant",
            ):
                (author / relative).mkdir(parents=True, exist_ok=True)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(self.manifest(artifact)), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ValidationFailure, "author or installed plugin tree"
            ):
                prepare_canary_bundle(
                    manifest,
                    author / "canary-bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )
            with self.assertRaisesRegex(
                ValidationFailure, "author or installed plugin tree"
            ):
                import_canary_attestation(
                    author,
                    "observations/run.draft.json",
                    "attestations/run.json",
                    "observations/run.json",
                    trust_verifier=self.CanaryVerifier(),
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )

    def test_prepare_bounds_total_artifact_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = []
            for index in range(64):
                artifact = root / f"artifact-{index}.log"
                artifact.write_text("x\n", encoding="utf-8")
                artifacts.append(artifact.name)
            runs = []
            for index in range(9):
                runs.append(
                    self.manifest(
                        root / artifacts[0],
                        task_id=f"task-{index}",
                        artifact_paths=artifacts,
                    )["runs"][0]
                )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "product_repository": "ai-platform",
                        "runs": runs,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValidationFailure, "too many artifacts"):
                prepare_canary_bundle(
                    manifest,
                    root / "bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

    def test_prepare_bounds_total_artifact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.log"
            second = root / "second.log"
            first.write_text("aa", encoding="utf-8")
            second.write_text("bb", encoding="utf-8")
            payload = self.manifest(
                first,
                artifact_paths=[first.name, second.name],
            )
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch(
                "engineering_assistant.canary_limits.MAX_TOTAL_ARTIFACT_BYTES", 3
            ), self.assertRaisesRegex(
                ValidationFailure, "total artifact bytes"
            ):
                prepare_canary_bundle(
                    manifest,
                    root / "bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

    def test_attestation_import_bounds_external_response_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(self.manifest(artifact)), encoding="utf-8")
            bundle = root / "bundle"
            report = prepare_canary_bundle(
                manifest,
                bundle,
                repository_root=ROOT,
                **IMPORT_TRUST,
            )
            response = bundle / "attestations/oversized.json"
            response.parent.mkdir(parents=True)
            response.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "draft_digest": "sha256:" + "a" * 64,
                        "attestation": "x" * 4096,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch(
                "engineering_assistant.canary_limits.MAX_ATTESTATION_RESPONSE_BYTES",
                256,
            ), self.assertRaisesRegex(ValidationFailure, "size limit"):
                import_canary_attestation(
                    bundle,
                    report["draft_refs"][0],
                    "attestations/oversized.json",
                    "observations/run.json",
                    trust_verifier=self.CanaryVerifier(),
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )

    def test_prepare_rejects_symlink_artifact_and_repo_local_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(self.manifest(artifact)), encoding="utf-8")

            with self.assertRaisesRegex(ValidationFailure, "outside the author repository"):
                prepare_canary_bundle(
                    manifest,
                    repository / "bundle",
                    repository_root=repository,
                    **IMPORT_TRUST,
                )

            link = root / "linked-events.jsonl"
            link.symlink_to(artifact)
            manifest.write_text(json.dumps(self.manifest(link)), encoding="utf-8")
            with self.assertRaisesRegex(ValidationFailure, "symlink"):
                prepare_canary_bundle(
                    manifest,
                    root / "external-bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

    def test_prepare_never_publishes_or_cleans_a_replaced_staging_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(self.manifest(artifact)),
                encoding="utf-8",
            )
            replacement_marker = root / "replacement-marker"

            original_copy = ArtifactIO.copy_contents_to

            def replace_output_during_copy(
                source,
                destination,
                *,
                max_file_bytes,
            ):
                output = root / "bundle"
                output.rename(root / "held-original-output")
                output.mkdir()
                (output / replacement_marker.name).write_text(
                    "unrelated",
                    encoding="utf-8",
                )
                return original_copy(
                    source,
                    destination,
                    max_file_bytes=max_file_bytes,
                )

            with mock.patch.object(
                ArtifactIO,
                "copy_contents_to",
                new=replace_output_during_copy,
            ), self.assertRaisesRegex(ValidationFailure, "output directory identity"):
                prepare_canary_bundle(
                    manifest,
                    root / "bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

            self.assertEqual(
                "unrelated",
                (root / "bundle" / replacement_marker.name).read_text(encoding="utf-8"),
            )

    def test_prepare_rejects_absolute_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            payload = self.manifest(
                artifact,
                artifact_paths=[str(artifact)],
            )
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValidationFailure, "relative"):
                prepare_canary_bundle(
                    manifest,
                    root / "bundle",
                    repository_root=ROOT,
                    **IMPORT_TRUST,
                )

    def test_cli_exposes_canary_prepare_without_attestation_options(self) -> None:
        args = build_parser().parse_args(
            [
                "canary-prepare",
                "--manifest",
                "/tmp/canary-manifest.json",
                "--output",
                "/tmp/canary-bundle",
            ]
        )

        self.assertEqual("canary-prepare", args.command)
        self.assertEqual("/tmp/canary-manifest.json", args.manifest)
        self.assertEqual("/tmp/canary-bundle", args.output)
        self.assertFalse(hasattr(args, "attestation"))

        imported = build_parser().parse_args(
            [
                "canary-attestation-import",
                "--evidence-root",
                "/tmp/canary-bundle",
                "--draft-ref",
                "observations/run.draft.json",
                "--response-ref",
                "attestations/run.json",
                "--output",
                "observations/run.json",
            ]
        )
        self.assertEqual("canary-attestation-import", imported.command)
        self.assertFalse(hasattr(imported, "attestation"))

    def test_attestation_import_rejects_draft_claim_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(self.manifest(artifact)), encoding="utf-8"
            )
            bundle = root / "bundle"
            report = prepare_canary_bundle(
                manifest,
                bundle,
                repository_root=ROOT,
                **IMPORT_TRUST,
            )
            draft_ref = report["draft_refs"][0]
            draft_path = bundle / draft_ref
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["claims"]["canary_observation"]["quality_score"] = 0
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            response_ref = "attestations/response.json"
            ArtifactIO(bundle, ".").create_immutable_json(
                {
                    "schema_version": "1.0",
                    "draft_digest": "sha256:"
                    + hashlib.sha256(draft_path.read_bytes()).hexdigest(),
                    "attestation": "trusted-canary-receipt",
                },
                *Path(response_ref).parts,
            )

            with self.assertRaisesRegex(ValidationFailure, "claims"):
                import_canary_attestation(
                    bundle,
                    draft_ref,
                    response_ref,
                    "observations/run.json",
                    trust_verifier=self.CanaryVerifier(),
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )

    def test_prepare_attest_import_assemble_validate_vertical_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "events.jsonl"
            artifact.write_text('{"type":"turn.completed"}\n', encoding="utf-8")
            runs = []
            for index in range(5):
                runs.append(
                    self.manifest(
                        artifact,
                        task_id=f"task-{index}",
                        variant="baseline",
                        git_ref="base",
                        input_tokens=80,
                        output_tokens=20,
                        cost_usd_micros=100,
                        quality_score=90,
                        document_noise_units=10,
                    )["runs"][0]
                )
                runs.append(
                    self.manifest(
                        artifact,
                        task_id=f"task-{index}",
                        variant="candidate",
                        git_ref="candidate",
                        treatment_digest="sha256:" + "c" * 64,
                        input_tokens=55,
                        output_tokens=18,
                        cost_usd_micros=72,
                        quality_score=90,
                        document_noise_units=6,
                    )["runs"][0]
                )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "product_repository": "ai-platform",
                        "runs": runs,
                    }
                ),
                encoding="utf-8",
            )
            bundle = root / "bundle"
            preparation = prepare_canary_bundle(
                manifest,
                bundle,
                repository_root=ROOT,
                **IMPORT_TRUST,
            )

            evidence_refs = []
            for index, draft_ref in enumerate(preparation["draft_refs"]):
                draft_path = bundle / draft_ref
                response_ref = f"attestations/response-{index}.json"
                ArtifactIO(bundle, ".").create_immutable_json(
                    {
                        "schema_version": "1.0",
                        "draft_digest": "sha256:"
                        + hashlib.sha256(draft_path.read_bytes()).hexdigest(),
                        "attestation": "trusted-canary-receipt",
                    },
                    *Path(response_ref).parts,
                )
                evidence_ref = f"observations/observation-{index}.json"
                import_canary_attestation(
                    bundle,
                    draft_ref,
                    response_ref,
                    evidence_ref,
                    trust_verifier=self.CanaryVerifier(),
                    **IMPORT_TRUST,
                    repository_root=ROOT,
                )
                evidence_refs.append(evidence_ref)

            result = assemble_canary_result(
                bundle,
                evidence_refs,
                trust_verifier=self.CanaryVerifier(),
                **VALIDATION_TRUST,
            )
            ArtifactIO(bundle, ".").create_immutable_json(
                result,
                "canary-result.json",
            )
            validated = run_canary_result(
                bundle / "canary-result.json",
                trust_verifier=self.CanaryVerifier(),
                **VALIDATION_TRUST,
            )
            self.assertEqual("passed", validated["status"])
            self.assertEqual(5, validated["task_count"])
            self.assertEqual(
                {
                    "evidence_broker_id": CANARY_BROKER_ID,
                    "host_trust_config_digest": CANARY_HOST_CONFIG_DIGEST,
                },
                validated["trust_provenance"],
            )


if __name__ == "__main__":
    unittest.main()
