"""Document-level external model egress consent contract."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
) -> ModelEgressDecision:
    """Require every future model use to pass a document-specific consent."""
    reasons: list[str] = []
    if not feature_enabled:
        reasons.append("model_egress_disabled")
    if request.actor_clerk_user_id != document_owner_clerk_user_id:
        reasons.append("verified_document_owner_required")
    if not request.byok_credential_reference:
        reasons.append("byok_credential_required")
    if consent is None:
        reasons.append("document_consent_required")
    else:
        if consent.revoked_at is not None:
            reasons.append("document_consent_revoked")
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
