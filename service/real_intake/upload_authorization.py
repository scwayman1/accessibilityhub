"""Short-lived, single-use quarantine upload authorization contracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from service.real_intake.identifiers import (
    require_owner_clerk_user_id,
    require_uuid4,
)
from service.real_intake.upload_gate import UploadPolicy


MAX_AUTHORIZATION_LIFETIME = timedelta(minutes=5)


@dataclass(frozen=True)
class UploadAuthorization:
    id: str
    document_id: str
    owner_clerk_user_id: str
    quarantine_key: str
    content_type: str
    max_bytes: int
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None


@dataclass(frozen=True)
class UploadAuthorizationDecision:
    allowed: bool
    reasons: tuple[str, ...]


def create_upload_authorization(
    *,
    document_id: str,
    owner_clerk_user_id: str,
    now: datetime | None = None,
    lifetime: timedelta = MAX_AUTHORIZATION_LIFETIME,
    policy: UploadPolicy = UploadPolicy(),
) -> UploadAuthorization:
    """Create storage conditions; an adapter later turns them into a signed form."""
    require_uuid4(document_id, label="document ID")
    require_owner_clerk_user_id(owner_clerk_user_id)
    if lifetime <= timedelta(0) or lifetime > MAX_AUTHORIZATION_LIFETIME:
        raise ValueError("upload authorization lifetime must be 1 second to 5 minutes")
    created = now or datetime.now(UTC)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("timezone-aware authorization time is required")
    return UploadAuthorization(
        id=str(uuid4()),
        document_id=document_id,
        owner_clerk_user_id=owner_clerk_user_id,
        quarantine_key=f"quarantine/{owner_clerk_user_id}/{document_id}.pdf",
        content_type="application/pdf",
        max_bytes=policy.max_bytes,
        created_at=created,
        expires_at=created + lifetime,
    )


def authorize_upload_completion(
    *,
    authorization: UploadAuthorization,
    actor_clerk_user_id: str,
    storage_key: str,
    content_type: str,
    object_size: int,
    now: datetime | None = None,
) -> UploadAuthorizationDecision:
    """Validate a durable authorization before atomically consuming it."""
    checked_at = now or datetime.now(UTC)
    reasons: list[str] = []
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        reasons.append("completion_time_invalid")
    elif checked_at < authorization.created_at:
        reasons.append("upload_authorization_not_yet_valid")
    elif checked_at > authorization.expires_at:
        reasons.append("upload_authorization_expired")
    if authorization.consumed_at is not None:
        reasons.append("upload_authorization_already_used")
    if actor_clerk_user_id != authorization.owner_clerk_user_id:
        reasons.append("upload_authorization_owner_mismatch")
    if storage_key != authorization.quarantine_key:
        reasons.append("upload_authorization_key_mismatch")
    if content_type != authorization.content_type:
        reasons.append("upload_authorization_content_type_mismatch")
    if object_size <= 0 or object_size > authorization.max_bytes:
        reasons.append("upload_authorization_size_mismatch")
    result = tuple(dict.fromkeys(reasons))
    return UploadAuthorizationDecision(not result, result)


def storage_signing_conditions(
    authorization: UploadAuthorization,
) -> tuple[tuple[str, object], ...]:
    """Return exact adapter conditions; never a URL, credential, or signature."""
    return (
        ("key", authorization.quarantine_key),
        ("Content-Type", authorization.content_type),
        ("content-length-range-min", 1),
        ("content-length-range-max", authorization.max_bytes),
        ("server-side-encryption-required", True),
        ("public-acl-forbidden", True),
        ("expires-at", authorization.expires_at.isoformat()),
    )
