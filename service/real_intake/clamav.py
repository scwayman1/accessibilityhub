"""Strict parsing and freshness policy for private ClamAV service evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from service.real_intake.upload_gate import ScanEvidence, ScanVerdict, UploadPolicy


MAX_RESPONSE_BYTES = 1_024


@dataclass(frozen=True)
class ClamAvVerdict:
    verdict: ScanVerdict
    reason_code: str


def classify_scan_response(response: bytes) -> ClamAvVerdict:
    """Classify the bounded clamd response; every ambiguity is indeterminate."""
    if not response or len(response) > MAX_RESPONSE_BYTES or b"\x00" in response:
        return ClamAvVerdict(ScanVerdict.INDETERMINATE, "scanner_response_invalid")
    try:
        text = response.decode("ascii").strip()
    except UnicodeDecodeError:
        return ClamAvVerdict(ScanVerdict.INDETERMINATE, "scanner_response_invalid")
    if "\n" in text or "\r" in text or ":" not in text:
        return ClamAvVerdict(ScanVerdict.INDETERMINATE, "scanner_response_invalid")
    _target, result = text.split(":", 1)
    result = result.strip()
    if result == "OK":
        return ClamAvVerdict(ScanVerdict.CLEAN, "scanner_clean")
    if result.endswith(" FOUND") and result.removesuffix(" FOUND").strip():
        return ClamAvVerdict(ScanVerdict.REJECTED, "malware_detected")
    return ClamAvVerdict(ScanVerdict.INDETERMINATE, "scanner_indeterminate")


def build_scan_evidence(
    *,
    response: bytes,
    engine_version: str,
    signature_database_version: str,
    definitions_updated_at: datetime,
    now: datetime,
    policy: UploadPolicy = UploadPolicy(),
) -> ScanEvidence:
    if (
        definitions_updated_at.tzinfo is None
        or definitions_updated_at.utcoffset() is None
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise ValueError("timezone-aware scanner timestamps are required")
    age = now - definitions_updated_at
    # Future timestamps beyond the same five-second clock allowance used for
    # identity tokens are treated as invalid/stale evidence.
    if age < timedelta(seconds=-5):
        age_seconds = policy.max_definition_age_seconds + 1
    else:
        age_seconds = max(0, int(age.total_seconds()))
    verdict = classify_scan_response(response)
    return ScanEvidence(
        verdict=verdict.verdict,
        definitions_age_seconds=age_seconds,
        engine_version=engine_version.strip(),
        signature_database_version=signature_database_version.strip(),
    )
