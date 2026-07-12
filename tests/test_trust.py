from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.model import EvidenceRef, RunApprovalGrant  # noqa: E402
from engineering_assistant.trust import (  # noqa: E402
    ExternalTrustVerifier,
    canary_observation_claims,
    evidence_claims,
    run_approval_claims,
)
from engineering_assistant.validation import ValidationFailure  # noqa: E402


class Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class TrustTests(unittest.TestCase):
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

    def test_canary_attestation_requires_exact_observation_claims(self) -> None:
        observation = {
            "task_id": "task-1",
            "input_tokens": 10,
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

    def test_production_trust_module_exposes_no_issuer(self) -> None:
        import engineering_assistant.trust as trust

        self.assertFalse(hasattr(trust, "TrustIssuer"))


if __name__ == "__main__":
    unittest.main()
