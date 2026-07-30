"""Pure upload/scan eligibility policy. This module performs no upload or parsing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from service.real_intake.identifiers import valid_owner_clerk_user_id


QUARANTINE_KEY = re.compile(
    r"^quarantine/(?P<owner>user_[A-Za-z0-9_-]+)/"
    r"(?P<object>[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.pdf$"
)


@dataclass(frozen=True)
class UploadPolicy:
    max_bytes: int = 25 * 1024 * 1024
    max_pages: int = 200
    max_streams: int = 10_000
    max_expanded_stream_bytes: int = 250 * 1024 * 1024
    max_definition_age_seconds: int = 24 * 60 * 60


@dataclass(frozen=True)
class QuarantineObject:
    owner_clerk_user_id: str
    storage_key: str
    original_filename: str
    declared_content_type: str
    object_size: int
    signature_prefix: bytes


class ScanVerdict(str, Enum):
    CLEAN = "clean"
    REJECTED = "rejected"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class ScanEvidence:
    verdict: ScanVerdict
    definitions_age_seconds: int
    engine_version: str
    signature_database_version: str


@dataclass(frozen=True)
class StructuralEvidence:
    parser_completed: bool
    page_count: int
    stream_count: int
    expanded_stream_bytes: int


@dataclass(frozen=True)
class ReleaseDecision:
    eligible_for_processing: bool
    reasons: tuple[str, ...]


def basic_validation_issues(
    item: QuarantineObject, policy: UploadPolicy = UploadPolicy()
) -> tuple[str, ...]:
    issues: list[str] = []
    filename = item.original_filename
    if not valid_owner_clerk_user_id(item.owner_clerk_user_id):
        issues.append("owner_identity_rejected")
    if (
        not filename
        or len(filename) > 200
        or filename != filename.strip()
        or "/" in filename
        or "\\" in filename
        or any(ord(character) < 32 for character in filename)
        or not filename.lower().endswith(".pdf")
    ):
        issues.append("filename_rejected")
    if item.declared_content_type != "application/pdf":
        issues.append("declared_content_type_rejected")
    if item.object_size <= 0 or item.object_size > policy.max_bytes:
        issues.append("object_size_rejected")
    if not item.signature_prefix.startswith(b"%PDF-"):
        issues.append("file_signature_rejected")
    match = QUARANTINE_KEY.fullmatch(item.storage_key)
    if match is None:
        issues.append("quarantine_key_rejected")
    elif match.group("owner") != item.owner_clerk_user_id:
        issues.append("quarantine_owner_mismatch")
    return tuple(issues)


def release_decision(
    item: QuarantineObject,
    scan: ScanEvidence | None,
    structure: StructuralEvidence | None,
    policy: UploadPolicy = UploadPolicy(),
) -> ReleaseDecision:
    """Require basic validation, a fresh clean scan, then bounded structure."""
    reasons = list(basic_validation_issues(item, policy))
    if scan is None:
        reasons.append("scanner_unavailable")
    else:
        if scan.verdict is not ScanVerdict.CLEAN:
            reasons.append(f"scan_{scan.verdict.value}")
        if (
            scan.definitions_age_seconds < 0
            or scan.definitions_age_seconds > policy.max_definition_age_seconds
        ):
            reasons.append("scan_definitions_stale")
        if not scan.engine_version or not scan.signature_database_version:
            reasons.append("scan_identity_missing")
    if structure is None:
        reasons.append("structural_validation_missing")
    else:
        if not structure.parser_completed:
            reasons.append("structural_validation_indeterminate")
        if structure.page_count < 1 or structure.page_count > policy.max_pages:
            reasons.append("page_limit_rejected")
        if structure.stream_count < 0 or structure.stream_count > policy.max_streams:
            reasons.append("stream_count_rejected")
        if (
            structure.expanded_stream_bytes < 0
            or structure.expanded_stream_bytes > policy.max_expanded_stream_bytes
        ):
            reasons.append("expanded_stream_limit_rejected")
    deduplicated = tuple(dict.fromkeys(reasons))
    return ReleaseDecision(not deduplicated, deduplicated)
