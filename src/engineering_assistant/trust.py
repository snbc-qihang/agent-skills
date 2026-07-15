"""External trust-root verification for evidence receipts and approval grants."""

from __future__ import annotations

import json
import hashlib
import os
import ssl
import stat
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from .model import EvidenceRef, InvestigationDecisionGrant, RunApprovalGrant
from .validation import ValidationFailure, load_json, validate_instance


MAX_HOST_TRUST_CONFIG_BYTES = 65_536
MAX_BROKER_RESPONSE_BYTES = 65_536


@dataclass(frozen=True)
class HostTrustBindings:
    verifier: TrustVerifier | None
    evidence_broker: Mapping[str, Any]
    approval_broker: Mapping[str, Any]
    config_digest: str | None


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
        deadline = time.monotonic() + timeout_seconds
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds,
                context=ssl.create_default_context(),
            ) as response:
                payload = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValidationFailure(
                            "external trust introspection exceeded its deadline"
                        )
                    _set_response_timeout(response, remaining)
                    chunk = response.read(
                        min(8192, MAX_BROKER_RESPONSE_BYTES + 1 - len(payload))
                    )
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if len(payload) > MAX_BROKER_RESPONSE_BYTES:
                        raise ValidationFailure(
                            "external trust introspection response is too large"
                        )
                result = json.loads(bytes(payload).decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise ValidationFailure("external trust introspection failed") from exc
        if not isinstance(result, dict):
            raise ValidationFailure(
                "external trust introspection response must be an object"
            )
        return result.get("active") is True and result.get("claims") == expected_claims


def _set_response_timeout(response: Any, timeout_seconds: float) -> None:
    try:
        response.fp.raw._sock.settimeout(max(timeout_seconds, 0.001))
    except AttributeError:
        pass


def _host_trust_config_path() -> Path | None:
    if os.name != "posix":
        return None
    if sys.platform == "darwin":
        return Path(
            "/Library/Application Support/engineering-assistant/host-trust.json"
        )
    return Path("/etc/engineering-assistant/host-trust.json")


def _trusted_host_owner_uid() -> int:
    return 0


def _read_host_trust_config(path: Path, schema_root: Path) -> tuple[dict, str]:
    if getattr(os, "O_NOFOLLOW", None) is None:
        raise ValidationFailure(
            "host trust config requires no-follow file opening support"
        )
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValidationFailure("host trust config is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise ValidationFailure("host trust config must be a regular non-symlink file")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ValidationFailure("host trust config must not be group/world writable")
    if metadata.st_uid != _trusted_host_owner_uid():
        raise ValidationFailure("host trust config must be owned by the host administrator")
    if metadata.st_size > MAX_HOST_TRUST_CONFIG_BYTES:
        raise ValidationFailure("host trust config is too large")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ValidationFailure("host trust config is not a regular file")
            if before.st_uid != _trusted_host_owner_uid():
                raise ValidationFailure(
                    "host trust config must be owned by the host administrator"
                )
            if before.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise ValidationFailure(
                    "host trust config must not be group/world writable"
                )
            if (before.st_dev, before.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise ValidationFailure("host trust config changed while opening")
            chunks = bytearray()
            while len(chunks) <= MAX_HOST_TRUST_CONFIG_BYTES:
                chunk = os.read(
                    descriptor,
                    min(8192, MAX_HOST_TRUST_CONFIG_BYTES + 1 - len(chunks)),
                )
                if not chunk:
                    break
                chunks.extend(chunk)
            after = os.fstat(descriptor)
            stable_fields = (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_uid",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
            if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
                raise ValidationFailure("host trust config changed while reading")
            raw = bytes(chunks)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ValidationFailure("host trust config could not be read securely") from exc
    if len(raw) > MAX_HOST_TRUST_CONFIG_BYTES:
        raise ValidationFailure("host trust config is too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationFailure("host trust config is invalid JSON") from exc
    schema = load_json(schema_root / "host-trust-config.schema.json")
    validate_instance(payload, schema, "host-trust-config")
    if not payload["profiles"]:
        raise ValidationFailure("host trust config must contain a profile")
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    return payload, digest


def trust_bindings_from_host(
    profile: Any,
    schema_root: Path | str,
) -> HostTrustBindings:
    path = _host_trust_config_path()
    if path is None:
        return HostTrustBindings(
            verifier=None,
            evidence_broker={"enabled": False},
            approval_broker={"enabled": False},
            config_digest=None,
        )
    if path.is_symlink():
        raise ValidationFailure("host trust config must be a non-symlink file")
    if not path.exists():
        return HostTrustBindings(
            verifier=None,
            evidence_broker={"enabled": False},
            approval_broker={"enabled": False},
            config_digest=None,
        )
    payload, digest = _read_host_trust_config(path, Path(schema_root).resolve())
    selected = payload["profiles"].get(profile.id)
    if selected is None:
        raise ValidationFailure(
            f"host trust config has no binding for profile {profile.id}"
        )
    evidence = dict(selected["evidence_broker"])
    approval = dict(selected["approval_broker"])
    verifier = None
    if evidence.get("enabled") or approval.get("enabled"):
        verifier = ExternalTrustVerifier(
            evidence_broker=evidence,
            approval_broker=approval,
        )
    return HostTrustBindings(
        verifier=verifier,
        evidence_broker=evidence,
        approval_broker=approval,
        config_digest=digest,
    )


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationFailure(f"invalid date-time {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationFailure("date-time must include a timezone")
    return parsed.astimezone(timezone.utc)
