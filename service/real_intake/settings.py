"""Configuration and runtime evidence gates for controlled real-document intake."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Mapping
from urllib.parse import urlsplit

from service.real_intake.identifiers import valid_owner_clerk_user_id


CONTROL_MANIFEST_VERSION = "2026-07-30.v1"
APPROVED_AUTHORIZED_PARTY = "https://accessibility.coastlinecollegefoundation.com"
# This foundation deliberately has no real-document action handlers. Removing
# this blocker requires a reviewed implementation change, not an environment
# variable or runtime self-attestation.
REAL_DOCUMENT_ACTION_HANDLERS_IMPLEMENTED = False
RUNTIME_EVIDENCE_MAX_AGE = timedelta(minutes=5)
RUNTIME_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")

REQUIRED_CONFIGURATION = {
    "clerk_publishable_key_missing": "CLERK_PUBLISHABLE_KEY",
    "clerk_jwt_key_missing": "CLERK_JWT_KEY",
    "clerk_issuer_missing": "CLERK_ISSUER",
    "clerk_authorized_party_missing": "CLERK_AUTHORIZED_PARTY",
    "owner_clerk_user_id_missing": "HUB_OWNER_CLERK_USER_ID",
    "postgres_private_url_missing": "HUB_POSTGRES_PRIVATE_URL",
    "queue_private_url_missing": "HUB_QUEUE_PRIVATE_URL",
    "object_storage_endpoint_missing": "HUB_OBJECT_STORAGE_ENDPOINT",
    "object_storage_bucket_missing": "HUB_OBJECT_STORAGE_BUCKET",
    "object_storage_access_key_missing": "HUB_OBJECT_STORAGE_ACCESS_KEY_ID",
    "object_storage_secret_key_missing": "HUB_OBJECT_STORAGE_SECRET_ACCESS_KEY",
    "clamav_private_endpoint_missing": "HUB_CLAMAV_PRIVATE_ENDPOINT",
    "worker_isolation_attestation_missing": "HUB_WORKER_ISOLATION_ATTESTATION",
    "audit_sink_missing": "HUB_AUDIT_SINK",
    "lifecycle_policy_missing": "HUB_LIFECYCLE_POLICY_ID",
    "backup_deletion_sla_missing": "HUB_BACKUP_DELETION_SLA",
    "verification_id_missing": "HUB_REAL_INTAKE_VERIFICATION_ID",
}


def _exact_https_origin(value: str) -> bool:
    """Return true only for a complete HTTPS origin with no path or wildcard."""
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and "*" not in value
        )
    except ValueError:
        return False


def _exact_https_issuer(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and "*" not in value
        )
    except ValueError:
        return False


@dataclass(frozen=True)
class RuntimeControlEvidence:
    """Health evidence supplied by provisioned adapters, never by request input."""

    private_encrypted_storage_verified: bool = False
    quarantine_credentials_prefix_limited: bool = False
    scanner_private_and_healthy: bool = False
    scanner_definitions_fresh: bool = False
    postgres_private_and_ready: bool = False
    queue_private_and_ready: bool = False
    worker_isolated: bool = False
    worker_no_egress_verified: bool = False
    audit_sink_append_only_verified: bool = False
    deletion_end_to_end_verified: bool = False
    backup_deletion_timing_verified: bool = False
    positive_and_negative_paths_verified: bool = False
    verification_id: str | None = None
    checked_at: datetime | None = None

    def blockers_at(self, now: datetime | None = None) -> tuple[str, ...]:
        blockers = [
            f"runtime_{name}_missing"
            for name in (
                "private_encrypted_storage_verified",
                "quarantine_credentials_prefix_limited",
                "scanner_private_and_healthy",
                "scanner_definitions_fresh",
                "postgres_private_and_ready",
                "queue_private_and_ready",
                "worker_isolated",
                "worker_no_egress_verified",
                "audit_sink_append_only_verified",
                "deletion_end_to_end_verified",
                "backup_deletion_timing_verified",
                "positive_and_negative_paths_verified",
            )
            if not getattr(self, name)
        ]
        if not self.verification_id or not RUNTIME_EVIDENCE_ID.fullmatch(
            self.verification_id
        ):
            blockers.append("runtime_verification_id_missing")
        checked = self.checked_at
        current = now or datetime.now(UTC)
        if (
            checked is None
            or checked.tzinfo is None
            or checked.utcoffset() is None
            or current.tzinfo is None
            or current.utcoffset() is None
        ):
            blockers.append("runtime_evidence_timestamp_missing")
        else:
            age = current - checked
            if age < timedelta(seconds=-5):
                blockers.append("runtime_evidence_timestamp_in_future")
            elif age > RUNTIME_EVIDENCE_MAX_AGE:
                blockers.append("runtime_evidence_stale")
        return tuple(blockers)

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.blockers_at()

    @property
    def ready(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class RealIntakeSettings:
    """Static configuration for the separate real-intake service.

    Environment variables can request activation, but they cannot assert that
    infrastructure controls are healthy. RuntimeControlEvidence is a separate,
    mandatory input to the activation decision.
    """

    environment: str
    activation_requested: bool
    control_manifest_version: str
    values: Mapping[str, str]
    byok_model_enabled: bool = False
    model_egress_enabled: bool = False

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "RealIntakeSettings":
        import os

        values = dict(os.environ if environ is None else environ)
        environment = values.get("HUB_ENV", "development").strip().lower()
        if environment not in {"development", "staging", "production"}:
            raise ValueError("HUB_ENV must be development, staging, or production.")
        return cls(
            environment=environment,
            # Near-miss values must remain disabled.
            activation_requested=values.get("HUB_REAL_DOCUMENT_INTAKE", "") == "true",
            control_manifest_version=values.get("HUB_REAL_INTAKE_CONTROL_MANIFEST", ""),
            values=values,
            byok_model_enabled=values.get("HUB_BYOK_MODEL_ENABLED", "") == "true",
            model_egress_enabled=values.get("HUB_MODEL_EGRESS_ENABLED", "") == "true",
        )

    def value(self, name: str) -> str:
        return self.values.get(name, "").strip()

    @property
    def clerk_auth_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        for code in (
            "clerk_publishable_key_missing",
            "clerk_jwt_key_missing",
            "clerk_issuer_missing",
            "clerk_authorized_party_missing",
            "owner_clerk_user_id_missing",
        ):
            if not self.value(REQUIRED_CONFIGURATION[code]):
                blockers.append(code)

        publishable = self.value("CLERK_PUBLISHABLE_KEY")
        if publishable:
            allowed_prefixes = ("pk_test_",) if self.environment == "development" else ("pk_live_",)
            if not publishable.startswith(allowed_prefixes):
                blockers.append("clerk_publishable_key_environment_mismatch")
        jwt_key = self.value("CLERK_JWT_KEY")
        if jwt_key and not (
            jwt_key.startswith("-----BEGIN PUBLIC KEY-----")
            and jwt_key.endswith("-----END PUBLIC KEY-----")
        ):
            blockers.append("clerk_jwt_key_not_pem_public_key")
        issuer = self.value("CLERK_ISSUER")
        if issuer and not _exact_https_issuer(issuer):
            blockers.append("clerk_issuer_must_be_exact_https_url")
        party = self.value("CLERK_AUTHORIZED_PARTY")
        if party and not _exact_https_origin(party):
            blockers.append("clerk_authorized_party_must_be_exact_https_origin")
        elif party and party != APPROVED_AUTHORIZED_PARTY:
            blockers.append("clerk_authorized_party_not_approved_origin")
        owner_id = self.value("HUB_OWNER_CLERK_USER_ID")
        if owner_id and not valid_owner_clerk_user_id(owner_id):
            blockers.append("owner_clerk_user_id_invalid")
        return tuple(blockers)

    @property
    def configuration_blockers(self) -> tuple[str, ...]:
        blockers = list(self.clerk_auth_blockers)
        clerk_codes = {
            "clerk_publishable_key_missing",
            "clerk_jwt_key_missing",
            "clerk_issuer_missing",
            "clerk_authorized_party_missing",
            "owner_clerk_user_id_missing",
        }
        for code, variable in REQUIRED_CONFIGURATION.items():
            if code not in clerk_codes and not self.value(variable):
                blockers.append(code)
        scanner_endpoint = self.value("HUB_CLAMAV_PRIVATE_ENDPOINT")
        if scanner_endpoint:
            try:
                from service.real_intake.clamd_client import parse_private_endpoint

                parse_private_endpoint(scanner_endpoint)
            except ValueError:
                blockers.append("clamav_endpoint_not_private_service")
        if self.control_manifest_version != CONTROL_MANIFEST_VERSION:
            blockers.append("control_manifest_version_unverified")
        if self.byok_model_enabled or self.model_egress_enabled:
            blockers.append("model_egress_must_remain_disabled")
        return tuple(dict.fromkeys(blockers))

    @property
    def clerk_auth_ready(self) -> bool:
        return not self.clerk_auth_blockers

    def activation_blockers(
        self, evidence: RuntimeControlEvidence | None = None
    ) -> tuple[str, ...]:
        blockers = list(self.configuration_blockers)
        if not self.activation_requested:
            blockers.append("activation_not_requested")
        if not REAL_DOCUMENT_ACTION_HANDLERS_IMPLEMENTED:
            blockers.append("real_document_action_handlers_not_implemented")
        blockers.extend(
            (evidence or RuntimeControlEvidence()).blockers
        )
        return tuple(dict.fromkeys(blockers))

    def real_document_intake_enabled(
        self, evidence: RuntimeControlEvidence | None = None
    ) -> bool:
        return not self.activation_blockers(evidence)

    def health_payload(
        self, evidence: RuntimeControlEvidence | None = None
    ) -> dict[str, object]:
        runtime = evidence or RuntimeControlEvidence()
        enabled = self.real_document_intake_enabled(runtime)
        return {
            "ok": True,
            "service": "accessibility-hub-real-intake",
            "environment": self.environment,
            "real_document_intake_enabled": enabled,
            "synthetic_only": not enabled,
            "byok_model_enabled": False,
            "model_egress_enabled": False,
        }
