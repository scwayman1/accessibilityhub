"""Canonical validation for identities and object-scoping identifiers."""
from __future__ import annotations

import re
from uuid import UUID


OWNER_CLERK_USER_ID = re.compile(r"^user_[A-Za-z0-9_-]{8,128}$")


def valid_owner_clerk_user_id(value: object) -> bool:
    return isinstance(value, str) and OWNER_CLERK_USER_ID.fullmatch(value) is not None


def require_owner_clerk_user_id(value: object) -> str:
    if not valid_owner_clerk_user_id(value):
        raise ValueError("valid owner Clerk user ID is required")
    return value


def require_uuid4(value: object, *, label: str) -> str:
    """Require the canonical lowercase/hyphenated representation of a UUIDv4."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a canonical UUIDv4")
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a canonical UUIDv4") from error
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(f"{label} must be a canonical UUIDv4")
    return value
