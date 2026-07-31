"""Document-level external model egress consent contract."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from service.real_intake.identifiers import (
    require_uuid4,
    valid_owner_clerk_user_id,
)


CONSENT_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
SECRET_REFERENCE = re.compile(
    r"^[a-z][a-z0-9-]{1,31}:[A-Za-z0-9][A-Za-z0-9._/-]{2,127}$"
)


@dataclass(frozen=True)
class ModelEgressConsent:
    id: str
    document_id: str
    owner_clerk_user_id: str
    provider: str
    purpose: str
    granted_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class ModelEgressRequest:
    document_id: str
    actor_clerk_user_id: str
    provider: str
    purpose: str
    byok_credential_reference: str | None


@dataclass(frozen=True)
class ModelEgressDecision:
    allowed: bool
    reasons: tuple[str, ...]


def authorize_model_egress(
    *,
    feature_enabled: bool,
    request: ModelEgressRequest,
    document_owner_clerk_user_id: str,
    consent: ModelEgressConsent | None,
    now: datetime | None = None,
) -> ModelEgressDecision:
    """Require every future model use to pass a document-specific consent."""
    checked_at = now or datetime.now(UTC)
    reasons: list[str] = []
    if not feature_enabled:
        reasons.append("model_egress_disabled")
    try:
        require_uuid4(request.document_id, label="model egress document ID")
    except ValueError:
        reasons.append("model_request_document_invalid")
    if (
        not valid_owner_clerk_user_id(request.actor_clerk_user_id)
        or not valid_owner_clerk_user_id(document_owner_clerk_user_id)
    ):
        reasons.append("model_request_owner_invalid")
    if request.actor_clerk_user_id != document_owner_clerk_user_id:
        reasons.append("verified_document_owner_required")
    if not isinstance(request.provider, str) or not CONSENT_TOKEN.fullmatch(
        request.provider
    ):
        reasons.append("model_provider_invalid")
    if not isinstance(request.purpose, str) or not CONSENT_TOKEN.fullmatch(
        request.purpose
    ):
        reasons.append("model_purpose_invalid")
    if (
        not isinstance(request.byok_credential_reference, str)
        or not SECRET_REFERENCE.fullmatch(request.byok_credential_reference)
    ):
        reasons.append("byok_credential_required")
    if consent is None:
        reasons.append("document_consent_required")
    else:
        try:
            require_uuid4(consent.id, label="model consent ID")
            require_uuid4(consent.document_id, label="model consent document ID")
        except ValueError:
            reasons.append("document_consent_identifier_invalid")
        if not valid_owner_clerk_user_id(consent.owner_clerk_user_id):
            reasons.append("document_consent_owner_invalid")
        if (
            not isinstance(consent.provider, str)
            or not CONSENT_TOKEN.fullmatch(consent.provider)
            or not isinstance(consent.purpose, str)
            or not CONSENT_TOKEN.fullmatch(consent.purpose)
        ):
            reasons.append("document_consent_scope_invalid")
        granted_at = consent.granted_at
        if (
            not isinstance(granted_at, datetime)
            or granted_at.tzinfo is None
            or granted_at.utcoffset() is None
            or checked_at.tzinfo is None
            or checked_at.utcoffset() is None
            or granted_at > checked_at + timedelta(seconds=5)
        ):
            reasons.append("document_consent_time_invalid")
        if consent.revoked_at is not None:
            reasons.append("document_consent_revoked")
            if (
                not isinstance(consent.revoked_at, datetime)
                or consent.revoked_at.tzinfo is None
                or consent.revoked_at.utcoffset() is None
                or not isinstance(granted_at, datetime)
                or consent.revoked_at < granted_at
                or consent.revoked_at > checked_at + timedelta(seconds=5)
            ):
                reasons.append("document_consent_revocation_time_invalid")
        if consent.document_id != request.document_id:
            reasons.append("consent_document_mismatch")
        if consent.owner_clerk_user_id != request.actor_clerk_user_id:
            reasons.append("consent_owner_mismatch")
        if consent.provider != request.provider:
            reasons.append("consent_provider_mismatch")
        if consent.purpose != request.purpose:
            reasons.append("consent_purpose_mismatch")
    result = tuple(dict.fromkeys(reasons))
    return ModelEgressDecision(allowed=not result, reasons=result)
