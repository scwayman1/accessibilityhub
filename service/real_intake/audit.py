"""Content-free audit event construction for controlled real-document actions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from service.real_intake.identifiers import (
    require_owner_clerk_user_id,
    require_uuid4,
)


class AuditAction(str, Enum):
    UPLOAD_AUTHORIZATION_CREATED = "upload_authorization_created"
    UPLOAD_RECEIVED = "upload_received"
    VALIDATION_COMPLETED = "validation_completed"
    SCAN_COMPLETED = "scan_completed"
    PROCESSING_QUEUED = "processing_queued"
    PROCESSING_STARTED = "processing_started"
    PROCESSING_SUCCEEDED = "processing_succeeded"
    PROCESSING_FAILED = "processing_failed"
    DOCUMENT_VIEWED = "document_viewed"
    DOCUMENT_DOWNLOADED = "document_downloaded"
    DELETION_REQUESTED = "deletion_requested"
    DELETION_COMPLETED = "deletion_completed"
    DELETION_FAILED = "deletion_failed"
    MODEL_EGRESS_CONSENTED = "model_egress_consented"
    MODEL_EGRESS_USED = "model_egress_used"


ALLOWED_DETAILS = {
    AuditAction.UPLOAD_AUTHORIZATION_CREATED: {
        "authorization_id", "max_bytes", "expires_at",
    },
    AuditAction.UPLOAD_RECEIVED: {
        "object_size", "sha256", "source_kind",
    },
    AuditAction.VALIDATION_COMPLETED: {
        "outcome", "reason_code", "page_count", "stream_count",
    },
    AuditAction.SCAN_COMPLETED: {
        "outcome", "reason_code", "engine_version",
        "signature_database_version", "definitions_age_seconds",
    },
    AuditAction.PROCESSING_QUEUED: {"job_id"},
    AuditAction.PROCESSING_STARTED: {"job_id", "attempt"},
    AuditAction.PROCESSING_SUCCEEDED: {"job_id", "finding_count"},
    AuditAction.PROCESSING_FAILED: {"job_id", "error_code"},
    AuditAction.DOCUMENT_VIEWED: set(),
    AuditAction.DOCUMENT_DOWNLOADED: {"derivative_kind"},
    AuditAction.DELETION_REQUESTED: {"deletion_request_id"},
    AuditAction.DELETION_COMPLETED: {
        "deletion_request_id", "objects_deleted", "records_deleted",
        "verification_id",
    },
    AuditAction.DELETION_FAILED: {
        "deletion_request_id", "error_code",
    },
    AuditAction.MODEL_EGRESS_CONSENTED: {
        "consent_id", "provider", "purpose",
    },
    AuditAction.MODEL_EGRESS_USED: {
        "consent_id", "provider", "purpose", "request_id",
    },
}

SENSITIVE_FIELD_FRAGMENTS = (
    "content", "document_bytes", "ocr", "text", "prompt", "response",
    "signed_url", "presigned", "credential", "secret", "token", "key",
)


@dataclass(frozen=True)
class AuditEvent:
    id: str
    owner_clerk_user_id: str
    actor_clerk_user_id: str
    action: AuditAction
    target_id: str | None
    request_id: str
    detail: dict[str, str | int | bool | None]
    occurred_at: str


def _safe_scalar(value: object) -> bool:
    if not isinstance(value, (str, int, bool, type(None))):
        return False
    if isinstance(value, str):
        return len(value) <= 256 and not value.lower().startswith(
            ("http://", "https://")
        )
    return True


def create_audit_event(
    *,
    owner_clerk_user_id: str,
    actor_clerk_user_id: str,
    action: AuditAction,
    target_id: str | None,
    request_id: str,
    detail: dict[str, str | int | bool | None] | None = None,
) -> AuditEvent:
    """Build a schema-constrained event that cannot carry document content."""
    if not isinstance(action, AuditAction):
        raise ValueError("recognized audit action is required")
    require_owner_clerk_user_id(owner_clerk_user_id)
    if actor_clerk_user_id != owner_clerk_user_id:
        raise ValueError("audit actor must be the verified owner")
    if target_id is not None:
        require_uuid4(target_id, label="audit target ID")
    if not request_id or len(request_id) > 128:
        raise ValueError("bounded request ID is required")
    values = detail or {}
    allowed = ALLOWED_DETAILS[action]
    unknown = set(values) - allowed
    sensitive = {
        key for key in values
        if any(fragment in key.lower() for fragment in SENSITIVE_FIELD_FRAGMENTS)
    }
    if unknown or sensitive:
        raise ValueError("audit detail contains a disallowed field")
    if any(not _safe_scalar(value) for value in values.values()):
        raise ValueError("audit detail values must be bounded non-URL scalars")
    return AuditEvent(
        id=str(uuid4()),
        owner_clerk_user_id=owner_clerk_user_id,
        actor_clerk_user_id=actor_clerk_user_id,
        action=action,
        target_id=target_id,
        request_id=request_id,
        detail=dict(values),
        occurred_at=datetime.now(UTC).isoformat(),
    )
