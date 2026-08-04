"""Tina evidence receipts (PRD §17).

A receipt memorializes what actually happened in a review session: which
checks ran, which could not run, what was found, what was fixed and
rechecked, and which decisions a human attested to. It is a defensible
evidence trail — explicitly not a certification.
"""
from __future__ import annotations

import datetime as dt
import json
from hashlib import sha256
from typing import Any

CONTRACT_VERSION = "tina-evidence-receipt/v1"

DISCLAIMER = (
    "This receipt records the review actions completed with the Coastline "
    "College Accessibility Hub. It is not a certification that the document "
    "is fully accessible or legally compliant."
)

# PRD §6.1 prohibited outcome language. Kept here (this module is exempt from the
# literal-phrase governance scan because the disclaimer must quote the concepts)
# so validators elsewhere can import the list without embedding the phrases.
PROHIBITED_OUTCOME_PHRASES = (
    "fully compliant",
    "guaranteed accessible",
    "passed accessibility",
    "certified accessible",
    "fully accessible",
    "legally compliant",
    "is compliant",
    "is accessible",
    "wcag compliant",
    "ada compliant",
)


def _finding_summary(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": item.get("rule_id"),
            "category": item.get("category"),
            "severity": item.get("severity"),
        }
        for item in report.get("findings", [])
    ]


def _checks_not_performed(report: dict[str, Any]) -> list[dict[str, Any]]:
    skipped = [
        {"rule_id": item.get("rule_id"), "reason": item.get("evidence")}
        for item in report.get("findings", [])
        if item.get("category") == "tool_failure_or_unsupported"
    ]
    verapdf = report.get("verapdf") or {}
    if verapdf.get("classification") == "not_run_due_to_blocking_intake":
        skipped.append({"rule_id": "PDF.VERAPDF.UA1", "reason": "veraPDF was not run after blocking intake."})
    elif verapdf.get("tool_available") is False:
        skipped.append({"rule_id": "PDF.VERAPDF.UA1", "reason": verapdf.get("stderr") or "validator unavailable"})
    return skipped


def receipt_integrity_hash(receipt: dict[str, Any]) -> str:
    """Deterministic hash over the receipt content, excluding the hash field itself."""
    content = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


def verify_receipt_integrity(receipt: dict[str, Any]) -> bool:
    return receipt.get("receipt_sha256") == receipt_integrity_hash(receipt)


def build_receipt(
    review: dict[str, Any],
    after: dict[str, Any] | None = None,
    remediation: dict[str, Any] | None = None,
    attestations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble an evidence receipt from review reports, an optional remediation
    record, and optional human attestations. Pure function; no persistence."""
    if not isinstance(review, dict) or "findings" not in review:
        raise ValueError("A review report with findings is required to build a receipt.")

    before_findings = _finding_summary(review)
    after_findings = _finding_summary(after) if after else None
    before_ids = {item["rule_id"] for item in before_findings}
    after_ids = {item["rule_id"] for item in after_findings} if after_findings is not None else None

    clean_attestations = [
        {
            "rule_id": item.get("rule_id"),
            "decision": (item.get("decision") or "").strip()[:2000],
            "status": "user_attested",
            "decided_at": item.get("decided_at"),
        }
        for item in (attestations or [])
        if item.get("rule_id") and (item.get("decision") or "").strip()
    ]

    receipt: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "disclaimer": DISCLAIMER,
        "input": {
            "sha256": (review.get("input") or {}).get("sha256"),
            "bytes": (review.get("input") or {}).get("bytes"),
        },
        "output": {
            "sha256": (remediation or {}).get("remediated_sha256"),
            "bytes": (remediation or {}).get("remediated_bytes"),
        },
        "tool_versions": review.get("tools", {}),
        "ruleset_version": review.get("schema_version"),
        "checks_not_performed": _checks_not_performed(review),
        "verified_strengths": review.get("strengths", []),
        "findings_before": before_findings,
        "findings_after": after_findings,
        "resolved_rule_ids": sorted(before_ids - after_ids) if after_ids is not None else [],
        "mutations": [
            {
                "tool": remediation.get("tool"),
                "tool_version": remediation.get("tool_version"),
                "source_sha256": remediation.get("source_sha256"),
                "remediated_sha256": remediation.get("remediated_sha256"),
                "actions": remediation.get("actions", []),
            }
        ]
        if remediation
        else [],
        "human_decisions": clean_attestations,
        "unresolved": [
            item
            for item in (after_findings if after_findings is not None else before_findings)
            if item["category"] in {"review_required", "deterministic_defect", "blocking_technical_failure"}
        ],
    }
    receipt["receipt_sha256"] = receipt_integrity_hash(receipt)
    return receipt
