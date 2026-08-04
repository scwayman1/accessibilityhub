"""Fail-closed rate-limit contract for future sensitive owner operations."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from service.real_intake.identifiers import require_owner_clerk_user_id


class SensitiveAction(str, Enum):
    OWNER_SESSION_PROBE = "owner_session_probe"
    UPLOAD_AUTHORIZATION = "upload_authorization"
    DOCUMENT_VIEW = "document_view"
    DOCUMENT_DOWNLOAD = "document_download"
    DELETION_REQUEST = "deletion_request"
    MODEL_EGRESS = "model_egress"


@dataclass(frozen=True)
class RateLimitPolicy:
    limit: int
    window_seconds: int


POLICIES = {
    SensitiveAction.OWNER_SESSION_PROBE: RateLimitPolicy(30, 60),
    SensitiveAction.UPLOAD_AUTHORIZATION: RateLimitPolicy(5, 10 * 60),
    SensitiveAction.DOCUMENT_VIEW: RateLimitPolicy(60, 60),
    SensitiveAction.DOCUMENT_DOWNLOAD: RateLimitPolicy(20, 10 * 60),
    SensitiveAction.DELETION_REQUEST: RateLimitPolicy(3, 60 * 60),
    SensitiveAction.MODEL_EGRESS: RateLimitPolicy(5, 60 * 60),
}


class AtomicRateLimitStore(Protocol):
    def consume(
        self, bucket: str, *, limit: int, window_seconds: int
    ) -> tuple[bool, int, int]:
        """Return allowed, remaining, retry-after seconds atomically."""


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int
    reason: str | None = None


def _bucket(owner_clerk_user_id: str, action: SensitiveAction) -> str:
    require_owner_clerk_user_id(owner_clerk_user_id)
    digest = hashlib.sha256(owner_clerk_user_id.encode()).hexdigest()[:32]
    return f"real-intake:{action.value}:{digest}"


def check_rate_limit(
    *,
    store: AtomicRateLimitStore,
    owner_clerk_user_id: str,
    action: SensitiveAction,
) -> RateLimitDecision:
    """Use an atomic private-store counter and deny when the store is unavailable."""
    if not isinstance(action, SensitiveAction):
        raise ValueError("recognized sensitive action is required")
    policy = POLICIES[action]
    try:
        allowed, remaining, retry_after = store.consume(
            _bucket(owner_clerk_user_id, action),
            limit=policy.limit,
            window_seconds=policy.window_seconds,
        )
    except Exception:
        return RateLimitDecision(
            allowed=False,
            remaining=0,
            retry_after_seconds=policy.window_seconds,
            reason="rate_limit_store_unavailable",
        )
    if (
        not isinstance(allowed, bool)
        or not isinstance(remaining, int)
        or isinstance(remaining, bool)
        or not isinstance(retry_after, int)
        or isinstance(retry_after, bool)
        or remaining < 0
        or remaining > policy.limit
        or retry_after < 0
        or retry_after > policy.window_seconds
    ):
        return RateLimitDecision(
            allowed=False,
            remaining=0,
            retry_after_seconds=policy.window_seconds,
            reason="rate_limit_store_invalid_response",
        )
    return RateLimitDecision(
        allowed=bool(allowed),
        remaining=remaining,
        retry_after_seconds=retry_after,
        reason=None if allowed else "rate_limit_exceeded",
    )
