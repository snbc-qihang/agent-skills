"""External trust-root verification for evidence receipts and approval grants."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from .model import EvidenceRef, InvestigationDecisionGrant, RunApprovalGrant
from .validation import ValidationFailure


def evidence_claims(run_id: str, evidence: EvidenceRef) -> dict[str, Any]:
    payload = evidence.to_dict()
    payload.pop("attestation", None)
    return {"run_id": run_id, "evidence": payload}


def decision_claims(grant: InvestigationDecisionGrant) -> dict[str, Any]:
    payload = grant.to_dict()
    payload.pop("token", None)
    return payload


def run_approval_claims(grant: RunApprovalGrant) -> dict[str, Any]:
    payload = grant.to_dict()
    payload.pop("token", None)
    return payload


def canary_observation_claims(observation: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(observation)
    payload.pop("attestation", None)
    return {"canary_observation": payload}


class TrustVerifier(Protocol):
    def verify_evidence(self, run_id: str, evidence: EvidenceRef) -> bool: ...

    def verify_decision(self, grant: InvestigationDecisionGrant) -> bool: ...

    def verify_run_approval(self, grant: RunApprovalGrant) -> bool: ...

    def verify_canary_observation(self, observation: Mapping[str, Any]) -> bool: ...


class ExternalTrustVerifier:
    """Verifies opaque receipts against profile-pinned HTTPS introspection services."""

    def __init__(
        self,
        *,
        evidence_broker: Mapping[str, Any],
        approval_broker: Mapping[str, Any],
    ) -> None:
        self.evidence_broker = dict(evidence_broker)
        self.approval_broker = dict(approval_broker)

    def verify_evidence(self, run_id: str, evidence: EvidenceRef) -> bool:
        if not evidence.attestation or not self.evidence_broker.get("enabled"):
            return False
        expected = evidence_claims(run_id, evidence)
        return self._verify(
            str(self.evidence_broker["introspection_url"]),
            evidence.attestation,
            expected,
            timeout_seconds=int(self.evidence_broker.get("timeout_seconds", 5)),
        )

    def verify_decision(self, grant: InvestigationDecisionGrant) -> bool:
        if not grant.token or not self.approval_broker.get("enabled"):
            return False
        return self._verify(
            str(self.approval_broker["introspection_url"]),
            grant.token,
            decision_claims(grant),
            timeout_seconds=int(self.approval_broker.get("timeout_seconds", 5)),
        )

    def verify_run_approval(self, grant: RunApprovalGrant) -> bool:
        if not grant.token or not self.approval_broker.get("enabled"):
            return False
        return self._verify(
            str(self.approval_broker["introspection_url"]),
            grant.token,
            run_approval_claims(grant),
            timeout_seconds=int(self.approval_broker.get("timeout_seconds", 5)),
        )

    def verify_canary_observation(self, observation: Mapping[str, Any]) -> bool:
        token = observation.get("attestation")
        if not isinstance(token, str) or not self.evidence_broker.get("enabled"):
            return False
        return self._verify(
            str(self.evidence_broker["introspection_url"]),
            token,
            canary_observation_claims(observation),
            timeout_seconds=int(self.evidence_broker.get("timeout_seconds", 5)),
        )

    @staticmethod
    def _verify(
        url: str,
        token: str,
        expected_claims: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> bool:
        if not url.startswith("https://"):
            raise ValidationFailure("trust introspection endpoint must use HTTPS")
        body = json.dumps({"token": token}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds,
                context=ssl.create_default_context(),
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise ValidationFailure("external trust introspection failed") from exc
        return result.get("active") is True and result.get("claims") == expected_claims


def verifier_from_profile(profile: Any) -> TrustVerifier | None:
    evidence = profile.evidence_broker
    approval = profile.approval_broker
    if not evidence.get("enabled") and not approval.get("enabled"):
        return None
    return ExternalTrustVerifier(evidence_broker=evidence, approval_broker=approval)


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationFailure(f"invalid date-time {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationFailure("date-time must include a timezone")
    return parsed.astimezone(timezone.utc)
