from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.model import (  # noqa: E402
    EvidenceRef,
    InvestigationDecisionGrant,
    RunApprovalGrant,
)
from engineering_assistant.cli import main as cli_main  # noqa: E402
from engineering_assistant.mcp_server import MCPServer, RuntimeTools  # noqa: E402
from engineering_assistant.trust import (  # noqa: E402
    ExternalTrustVerifier,
    MAX_BROKER_RESPONSE_BYTES,
    canary_observation_claims,
    decision_claims,
    evidence_claims,
    run_approval_claims,
    trust_bindings_from_host,
)
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.offset = 0

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class TrustTests(unittest.TestCase):
    @staticmethod
    def disabled_profile() -> SimpleNamespace:
        return SimpleNamespace(
            id="default",
            evidence_broker={"enabled": False},
            approval_broker={"enabled": False},
        )

    @staticmethod
    def repository_enabled_profile() -> SimpleNamespace:
        return SimpleNamespace(
            id="default",
            evidence_broker={
                "enabled": True,
                "id": "model-selected-evidence",
                "introspection_url": "https://attacker.example/evidence",
                "timeout_seconds": 1,
            },
            approval_broker={
                "enabled": True,
                "id": "model-selected-approval",
                "audience": "engineering-assistant",
                "introspection_url": "https://attacker.example/approval",
                "timeout_seconds": 1,
            },
        )

    @staticmethod
    def host_config() -> dict:
        return {
            "schema_version": "1.0",
            "profiles": {
                "default": {
                    "evidence_broker": {
                        "enabled": True,
                        "id": "enterprise-evidence",
                        "introspection_url": "https://broker.example/evidence",
                        "timeout_seconds": 3,
                    },
                    "approval_broker": {
                        "enabled": True,
                        "id": "enterprise-approval",
                        "audience": "engineering-assistant",
                        "introspection_url": "https://broker.example/approval",
                        "timeout_seconds": 3,
                    },
                }
            },
        }

    def verifier(self, *, url: str = "https://broker.example/evidence") -> ExternalTrustVerifier:
        return ExternalTrustVerifier(
            evidence_broker={
                "enabled": True,
                "introspection_url": url,
                "timeout_seconds": 2,
            },
            approval_broker={"enabled": False},
        )

    @staticmethod
    def evidence() -> EvidenceRef:
        return EvidenceRef(
            id="evidence-1",
            kind="test",
            uri="https://artifacts.example/evidence-1",
            producer="platform-observer",
            observed_at="2026-07-11T00:00:00+00:00",
            trust_level="observed",
            scope="changed code",
            subject_digest="sha256:" + "a" * 64,
            digest="sha256:" + "b" * 64,
            attestation="opaque-receipt-value",
        )

    def test_external_verifier_requires_exact_broker_claims(self) -> None:
        evidence = self.evidence()
        payload = (
            '{"active":true,"claims":'
            + json.dumps(evidence_claims("run-1", evidence))
            + "}"
        ).encode()
        with patch(
            "engineering_assistant.trust.urllib.request.urlopen",
            return_value=Response(payload),
        ) as urlopen:
            self.assertTrue(self.verifier().verify_evidence("run-1", evidence))
        request = urlopen.call_args.args[0]
        self.assertEqual("POST", request.method)
        self.assertEqual("https://broker.example/evidence", request.full_url)
        self.assertEqual(b'{"token": "opaque-receipt-value"}', request.data)

        with patch(
            "engineering_assistant.trust.urllib.request.urlopen",
            return_value=Response(b'{"active":true,"claims":{"run_id":"other"}}'),
        ):
            self.assertFalse(self.verifier().verify_evidence("run-1", evidence))

    def test_external_verifier_rejects_non_https_endpoint(self) -> None:
        with self.assertRaisesRegex(ValidationFailure, "HTTPS"):
            self.verifier(url="http://broker.example/evidence").verify_evidence(
                "run-1", self.evidence()
            )

    def test_external_verifier_bounds_response_size_and_total_deadline(self) -> None:
        with patch(
            "engineering_assistant.trust.urllib.request.urlopen",
            return_value=Response(b"x" * (MAX_BROKER_RESPONSE_BYTES + 1)),
        ):
            with self.assertRaisesRegex(ValidationFailure, "too large"):
                self.verifier().verify_evidence("run-1", self.evidence())
        with patch(
            "engineering_assistant.trust.urllib.request.urlopen",
            return_value=Response(b"{}"),
        ), patch(
            "engineering_assistant.trust.time.monotonic",
            side_effect=[0.0, 3.0],
        ):
            with self.assertRaisesRegex(ValidationFailure, "deadline"):
                self.verifier().verify_evidence("run-1", self.evidence())

    def test_canary_attestation_requires_exact_observation_claims(self) -> None:
        observation = {
            "task_id": "task-1",
            "input_tokens": 10,
            "trust_provenance": {
                "evidence_broker_id": "enterprise-evidence",
                "host_trust_config_digest": "sha256:" + "c" * 64,
            },
            "attestation": "opaque-canary-receipt",
        }
        payload = json.dumps(
            {"active": True, "claims": canary_observation_claims(observation)}
        ).encode()
        with patch(
            "engineering_assistant.trust.urllib.request.urlopen",
            return_value=Response(payload),
        ):
            self.assertTrue(
                self.verifier().verify_canary_observation(observation)
            )
        changed = {**observation, "input_tokens": 11}
        with patch(
            "engineering_assistant.trust.urllib.request.urlopen",
            return_value=Response(payload),
        ):
            self.assertFalse(self.verifier().verify_canary_observation(changed))

    def test_external_verifier_requires_exact_run_approval_claims(self) -> None:
        grant = RunApprovalGrant(
            grant_id="grant-1",
            broker_id="approval-broker",
            audience="engineering-assistant",
            action="run.approve",
            run_id="run-1",
            run_revision=3,
            approval_id="release-execution",
            scope=["flow:release", "approval:release-execution"],
            issued_at="2026-07-11T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
            actor_ref="opaque-human",
            nonce="0123456789abcdef",
            token="opaque-approval-token",
        )
        verifier = ExternalTrustVerifier(
            evidence_broker={"enabled": False},
            approval_broker={
                "enabled": True,
                "introspection_url": "https://broker.example/approval",
                "timeout_seconds": 2,
            },
        )
        payload = json.dumps(
            {"active": True, "claims": run_approval_claims(grant)}
        ).encode()
        with patch(
            "engineering_assistant.trust.urllib.request.urlopen",
            return_value=Response(payload),
        ):
            self.assertTrue(verifier.verify_run_approval(grant))

        wrong = json.dumps(
            {"active": True, "claims": {**run_approval_claims(grant), "run_revision": 2}}
        ).encode()
        with patch(
            "engineering_assistant.trust.urllib.request.urlopen",
            return_value=Response(wrong),
        ):
            self.assertFalse(verifier.verify_run_approval(grant))

    def test_external_verifier_requires_exact_investigation_decision_claims(self) -> None:
        now = datetime.now(timezone.utc)
        grant = InvestigationDecisionGrant(
            grant_id="investigation-grant-1",
            broker_id="enterprise-approval",
            audience="engineering-assistant",
            action="investigation.select_mode",
            run_id="run-1",
            investigation_id="investigation-1",
            run_revision=0,
            decision="approve",
            selected_mode="suggest_then_run",
            allowed_source_scope=["official_docs"],
            max_cost="low",
            issued_at=(now - timedelta(minutes=1)).isoformat(),
            expires_at=(now + timedelta(minutes=10)).isoformat(),
            actor_ref="opaque-reviewer",
            nonce="0123456789abcdef",
            token="opaque-decision-token",
        )
        verifier = ExternalTrustVerifier(
            evidence_broker={"enabled": False},
            approval_broker={
                "enabled": True,
                "introspection_url": "https://broker.example/approval",
                "timeout_seconds": 2,
            },
        )
        exact = Response(
            json.dumps({"active": True, "claims": decision_claims(grant)}).encode()
        )
        with patch(
            "engineering_assistant.trust.urllib.request.urlopen",
            return_value=exact,
        ):
            self.assertTrue(verifier.verify_decision(grant))
        tampered = Response(
            json.dumps(
                {
                    "active": True,
                    "claims": {**decision_claims(grant), "run_revision": 1},
                }
            ).encode()
        )
        with patch(
            "engineering_assistant.trust.urllib.request.urlopen",
            return_value=tampered,
        ):
            self.assertFalse(verifier.verify_decision(grant))

    def test_production_trust_module_exposes_no_issuer(self) -> None:
        import engineering_assistant.trust as trust

        self.assertFalse(hasattr(trust, "TrustIssuer"))

    def test_host_owned_config_enables_external_brokers_without_model_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "host-trust.json"
            path.write_text(json.dumps(self.host_config()), encoding="utf-8")
            path.chmod(0o600)

            with patch(
                "engineering_assistant.trust._host_trust_config_path",
                return_value=path,
            ), patch(
                "engineering_assistant.trust._trusted_host_owner_uid",
                return_value=os.geteuid(),
            ):
                bindings = trust_bindings_from_host(
                    self.disabled_profile(),
                    ROOT / "schemas",
                )

        self.assertIsInstance(bindings.verifier, ExternalTrustVerifier)
        self.assertEqual("enterprise-evidence", bindings.evidence_broker["id"])
        self.assertEqual("enterprise-approval", bindings.approval_broker["id"])
        self.assertRegex(bindings.config_digest or "", r"^sha256:[0-9a-f]{64}$")

    def test_host_trust_config_rejects_symlink_and_writable_files(self) -> None:
        profile = self.disabled_profile()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.json"
            target.write_text(json.dumps(self.host_config()), encoding="utf-8")
            target.chmod(0o600)
            symlink = root / "link.json"
            symlink.symlink_to(target)
            with patch(
                "engineering_assistant.trust._host_trust_config_path",
                return_value=symlink,
            ), patch(
                "engineering_assistant.trust._trusted_host_owner_uid",
                return_value=os.geteuid(),
            ):
                with self.assertRaisesRegex(ValidationFailure, "non-symlink"):
                    trust_bindings_from_host(profile, ROOT / "schemas")
            target.chmod(0o622)
            with patch(
                "engineering_assistant.trust._host_trust_config_path",
                return_value=target,
            ), patch(
                "engineering_assistant.trust._trusted_host_owner_uid",
                return_value=os.geteuid(),
            ):
                with self.assertRaisesRegex(ValidationFailure, "group/world writable"):
                    trust_bindings_from_host(profile, ROOT / "schemas")

    def test_host_trust_config_rejects_non_admin_owner_and_in_place_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "host-trust.json"
            path.write_text(json.dumps(self.host_config()), encoding="utf-8")
            path.chmod(0o600)
            with patch(
                "engineering_assistant.trust._host_trust_config_path",
                return_value=path,
            ), patch(
                "engineering_assistant.trust._trusted_host_owner_uid",
                return_value=os.geteuid() + 1,
            ):
                with self.assertRaisesRegex(ValidationFailure, "administrator"):
                    trust_bindings_from_host(
                        self.disabled_profile(), ROOT / "schemas"
                    )

            real_fstat = os.fstat
            calls = 0

            def changed_after_read(descriptor):
                nonlocal calls
                calls += 1
                observed = real_fstat(descriptor)
                if calls == 1:
                    return observed
                return SimpleNamespace(
                    st_dev=observed.st_dev,
                    st_ino=observed.st_ino,
                    st_mode=observed.st_mode,
                    st_uid=observed.st_uid,
                    st_size=observed.st_size,
                    st_mtime_ns=observed.st_mtime_ns,
                    st_ctime_ns=observed.st_ctime_ns + 1,
                )

            with patch(
                "engineering_assistant.trust._host_trust_config_path",
                return_value=path,
            ), patch(
                "engineering_assistant.trust._trusted_host_owner_uid",
                return_value=os.geteuid(),
            ), patch(
                "engineering_assistant.trust.os.fstat",
                side_effect=changed_after_read,
            ):
                with self.assertRaisesRegex(ValidationFailure, "changed while reading"):
                    trust_bindings_from_host(
                        self.disabled_profile(), ROOT / "schemas"
                    )

    def test_host_trust_config_cannot_override_policy_or_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "host-trust.json"
            payload = self.host_config()
            payload["profiles"]["default"]["store"] = {"run_root": "/tmp/escape"}
            path.write_text(json.dumps(payload), encoding="utf-8")
            path.chmod(0o600)

            with patch(
                "engineering_assistant.trust._host_trust_config_path",
                return_value=path,
            ), patch(
                "engineering_assistant.trust._trusted_host_owner_uid",
                return_value=os.geteuid(),
            ):
                with self.assertRaisesRegex(ValidationFailure, "additional property"):
                    trust_bindings_from_host(
                        self.disabled_profile(),
                        ROOT / "schemas",
                    )

    def test_model_environment_cannot_select_a_host_trust_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            attacker = Path(temporary) / "attacker.json"
            attacker.write_text(json.dumps(self.host_config()), encoding="utf-8")
            attacker.chmod(0o600)
            missing_fixed_path = Path(temporary) / "admin-path-does-not-exist.json"
            with patch.dict(
                os.environ,
                {"ENGINEERING_ASSISTANT_HOST_TRUST_CONFIG": str(attacker)},
            ), patch(
                "engineering_assistant.trust._host_trust_config_path",
                return_value=missing_fixed_path,
            ):
                bindings = trust_bindings_from_host(
                    self.disabled_profile(),
                    ROOT / "schemas",
                )

        self.assertIsNone(bindings.verifier)
        self.assertIsNone(bindings.config_digest)

    def test_repository_profile_cannot_become_a_trust_root_without_host_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing-host-trust.json"
            with patch(
                "engineering_assistant.trust._host_trust_config_path",
                return_value=missing,
            ):
                bindings = trust_bindings_from_host(
                    self.repository_enabled_profile(),
                    ROOT / "schemas",
                )

        self.assertIsNone(bindings.verifier)
        self.assertEqual({"enabled": False}, bindings.evidence_broker)
        self.assertEqual({"enabled": False}, bindings.approval_broker)
        self.assertIsNone(bindings.config_digest)

    def test_non_posix_host_never_falls_back_to_repository_brokers(self) -> None:
        with patch(
            "engineering_assistant.trust._host_trust_config_path",
            return_value=None,
        ):
            bindings = trust_bindings_from_host(
                self.repository_enabled_profile(),
                ROOT / "schemas",
            )

        self.assertIsNone(bindings.verifier)
        self.assertEqual({"enabled": False}, bindings.evidence_broker)
        self.assertEqual({"enabled": False}, bindings.approval_broker)

    def test_default_cli_start_works_without_host_trust_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intent = root / "intent.json"
            intent.write_text(
                json.dumps(
                    {
                        "task_kind": "review",
                        "requested_outcome": "review the current diff",
                        "scope": ["diff"],
                        "risk_signals": [],
                        "requested_external_actions": [],
                        "confidence": 0.99,
                        "evidence": ["user request"],
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            (root / "project").mkdir()
            with patch(
                "engineering_assistant.trust._host_trust_config_path",
                return_value=root / "missing-host-trust.json",
            ), redirect_stdout(output):
                code = cli_main(
                    [
                        "--repository-root",
                        str(ROOT),
                        "start",
                        "--intent",
                        str(intent),
                        "--task-id",
                        "cli-default-start",
                        "--project-root",
                        str(root / "project"),
                    ]
                )

        self.assertEqual(0, code, output.getvalue())
        self.assertIn("state", json.loads(output.getvalue()))

    def test_fixed_host_binding_drives_cli_evidence_introspection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "host-trust.json"
            config.write_text(json.dumps(self.host_config()), encoding="utf-8")
            config.chmod(0o600)
            intent = root / "intent.json"
            intent.write_text(
                json.dumps(
                    {
                        "task_kind": "review",
                        "requested_outcome": "review the current diff",
                        "scope": ["diff"],
                        "risk_signals": [],
                        "requested_external_actions": [],
                        "confidence": 0.99,
                        "evidence": ["user request"],
                    }
                ),
                encoding="utf-8",
            )
            project = root / "project"
            project.mkdir()
            start_output = io.StringIO()
            patches = (
                patch(
                    "engineering_assistant.trust._host_trust_config_path",
                    return_value=config,
                ),
                patch(
                    "engineering_assistant.trust._trusted_host_owner_uid",
                    return_value=os.geteuid(),
                ),
            )
            with patches[0], patches[1], redirect_stdout(start_output):
                self.assertEqual(
                    0,
                    cli_main(
                        [
                            "--repository-root",
                            str(ROOT),
                            "--profile",
                            "default",
                            "start",
                            "--intent",
                            str(intent),
                            "--task-id",
                            "broker-evidence-start",
                            "--project-root",
                            str(project),
                        ]
                    ),
                )
            run_id = json.loads(start_output.getvalue())["state"]["run_id"]
            observed = root / "observed.txt"
            observed.write_text("observed result\n", encoding="utf-8")
            evidence_payload = {
                "id": "broker-observed",
                "kind": "source",
                "uri": str(observed),
                "producer": "host-observer",
                "observed_at": "2026-07-14T00:00:00+00:00",
                "trust_level": "observed",
                "scope": "review source",
                "digest": "sha256:" + hashlib.sha256(observed.read_bytes()).hexdigest(),
                "attestation": "opaque-host-receipt",
            }
            evidence_file = root / "evidence.json"
            evidence_file.write_text(json.dumps(evidence_payload), encoding="utf-8")
            expected = evidence_claims(run_id, EvidenceRef(**evidence_payload))
            broker_response = Response(
                json.dumps({"active": True, "claims": expected}).encode("utf-8")
            )
            import_output = io.StringIO()
            with patch(
                "engineering_assistant.trust._host_trust_config_path",
                return_value=config,
            ), patch(
                "engineering_assistant.trust._trusted_host_owner_uid",
                return_value=os.geteuid(),
            ), patch(
                "engineering_assistant.trust.urllib.request.urlopen",
                return_value=broker_response,
            ), redirect_stdout(import_output):
                code = cli_main(
                    [
                        "--repository-root",
                        str(ROOT),
                        "--profile",
                        "default",
                        "evidence-import",
                        "--run-id",
                        run_id,
                        "--evidence",
                        str(evidence_file),
                        "--project-root",
                        str(project),
                    ]
                )

        self.assertEqual(0, code, import_output.getvalue())
        self.assertEqual(
            "broker-observed",
            json.loads(import_output.getvalue())["evidence"]["id"],
        )

    def test_fixed_host_binding_drives_investigation_selection_and_mcp_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "host-trust.json"
            config.write_text(json.dumps(self.host_config()), encoding="utf-8")
            config.chmod(0o600)
            project = root / "project"
            project.mkdir()

            def invoke(argv: list[str], broker_payload: dict | None = None) -> tuple[int, dict]:
                output = io.StringIO()
                response = Response(json.dumps(broker_payload or {}).encode())
                with patch(
                    "engineering_assistant.trust._host_trust_config_path",
                    return_value=config,
                ), patch(
                    "engineering_assistant.trust._trusted_host_owner_uid",
                    return_value=os.geteuid(),
                ), patch(
                    "engineering_assistant.trust.urllib.request.urlopen",
                    return_value=response,
                ), redirect_stdout(output):
                    code = cli_main(
                        ["--repository-root", str(ROOT), "--profile", "default", *argv]
                    )
                return code, json.loads(output.getvalue())

            intent = root / "intent.json"
            intent.write_text(
                json.dumps(
                    {
                        "task_kind": "review",
                        "requested_outcome": "review the current diff",
                        "scope": ["diff"],
                        "risk_signals": [],
                        "requested_external_actions": [],
                        "confidence": 0.99,
                        "evidence": ["user request"],
                    }
                ),
                encoding="utf-8",
            )
            code, started = invoke(
                [
                    "start",
                    "--intent",
                    str(intent),
                    "--task-id",
                    "investigation-selection",
                    "--run-id",
                    "investigation-selection-run",
                    "--project-root",
                    str(project),
                ]
            )
            self.assertEqual(0, code, started)
            run_id = started["state"]["run_id"]

            def propose(investigation_id: str) -> None:
                request = root / f"{investigation_id}.request.json"
                request.write_text(
                    json.dumps(
                        {
                            "id": investigation_id,
                            "run_id": run_id,
                            "question": "Which official contract applies?",
                            "reason": "The implementation boundary is uncertain.",
                            "source_scope": ["official_docs"],
                            "reported_blocking": False,
                            "mode": "suggest_then_run",
                            "estimated_cost": "low",
                            "stop_conditions": ["The primary contract is identified."],
                            "evidence_requirements": ["Official documentation."],
                            "status": "proposed",
                        }
                    ),
                    encoding="utf-8",
                )
                proposed_code, proposed = invoke(
                    [
                        "investigation-propose",
                        "--request",
                        str(request),
                        "--project-root",
                        str(project),
                    ]
                )
                self.assertEqual(0, proposed_code, proposed)

            propose("selection-1")
            now = datetime.now(timezone.utc)

            def grant_payload(
                investigation_id: str,
                *,
                run_revision: int = 0,
                expires_at: datetime | None = None,
            ) -> dict:
                return InvestigationDecisionGrant(
                    grant_id=f"grant-{investigation_id}",
                    broker_id="enterprise-approval",
                    audience="engineering-assistant",
                    action="investigation.select_mode",
                    run_id=run_id,
                    investigation_id=investigation_id,
                    run_revision=run_revision,
                    decision="approve",
                    selected_mode="suggest_then_run",
                    allowed_source_scope=["official_docs"],
                    max_cost="low",
                    issued_at=(now - timedelta(minutes=2)).isoformat(),
                    expires_at=(expires_at or now + timedelta(minutes=10)).isoformat(),
                    actor_ref="opaque-reviewer",
                    nonce=f"nonce-{investigation_id}-0123456789",
                    token=f"opaque-token-{investigation_id}",
                ).to_dict()

            selected_grant = grant_payload("selection-1")
            selected_path = root / "selection-1.grant.json"
            selected_path.write_text(json.dumps(selected_grant), encoding="utf-8")
            code, selected = invoke(
                [
                    "investigation-approval-import",
                    "--grant",
                    str(selected_path),
                    "--project-root",
                    str(project),
                ],
                {
                    "active": True,
                    "claims": decision_claims(
                        InvestigationDecisionGrant(**selected_grant)
                    ),
                },
            )
            self.assertEqual(0, code, selected)
            self.assertEqual("approved", selected["record"]["request"]["status"])
            self.assertEqual("grant-selection-1", selected["record"]["decision_ref"])
            self.assertEqual(1, selected["record"]["revision"])

            server = MCPServer(
                RuntimeTools(
                    ROOT,
                    trust_verifier=SimpleNamespace(),
                    evidence_broker_enabled=True,
                )
            )
            listed = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "engineering_assistant_investigation_list",
                        "arguments": {
                            "project_root": str(project),
                            "run_id": run_id,
                            "profile": "default",
                        },
                    },
                }
            )["result"]
            self.assertFalse(listed["isError"])
            self.assertEqual("approved", listed["structuredContent"]["records"][0]["request"]["status"])
            started_investigation = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "engineering_assistant_investigation_start",
                        "arguments": {
                            "project_root": str(project),
                            "run_id": run_id,
                            "investigation_id": "selection-1",
                            "profile": "default",
                        },
                    },
                }
            )["result"]
            self.assertFalse(started_investigation["isError"])
            self.assertEqual("running", started_investigation["structuredContent"]["record"]["request"]["status"])

            for investigation_id, invalid_grant, expected_message in (
                (
                    "selection-stale",
                    grant_payload("selection-stale", run_revision=1),
                    "stale run revision",
                ),
                (
                    "selection-expired",
                    grant_payload(
                        "selection-expired",
                        expires_at=now - timedelta(minutes=1),
                    ),
                    "not currently valid",
                ),
            ):
                propose(investigation_id)
                grant_path = root / f"{investigation_id}.grant.json"
                grant_path.write_text(json.dumps(invalid_grant), encoding="utf-8")
                invalid_code, invalid = invoke(
                    [
                        "investigation-approval-import",
                        "--grant",
                        str(grant_path),
                        "--project-root",
                        str(project),
                    ],
                    {
                        "active": True,
                        "claims": decision_claims(
                            InvestigationDecisionGrant(**invalid_grant)
                        ),
                    },
                )
                self.assertEqual(2, invalid_code, invalid)
                self.assertIn(expected_message, invalid["message"])

            after_failures = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "engineering_assistant_investigation_list",
                        "arguments": {
                            "project_root": str(project),
                            "run_id": run_id,
                            "profile": "default",
                        },
                    },
                }
            )["result"]["structuredContent"]["records"]
            failed_records = {
                item["request"]["id"]: item
                for item in after_failures
                if item["request"]["id"] in {"selection-stale", "selection-expired"}
            }
            self.assertEqual({"selection-stale", "selection-expired"}, set(failed_records))
            for record in failed_records.values():
                self.assertEqual("proposed", record["request"]["status"])
                self.assertEqual(0, record["revision"])
                self.assertIsNone(record["decision_ref"])


if __name__ == "__main__":
    unittest.main()
