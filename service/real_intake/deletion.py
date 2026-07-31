"""Manual owner deletion inventory and verified-completion contracts."""
from __future__ import annotations

from dataclasses import dataclass

from service.real_intake.lifecycle import RealDocumentRecord


RETENTION_POLICY = "manual-owner-deletion-only"


@dataclass(frozen=True)
class DeletionInventory:
    document_id: str
    owner_clerk_user_id: str
    exact_object_keys: tuple[str, ...]
    object_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class DeletionProof:
    verified: bool
    reasons: tuple[str, ...]
    objects_deleted: int
    records_deleted: int


def build_deletion_inventory(
    *, actor_clerk_user_id: str, document: RealDocumentRecord
) -> DeletionInventory:
    if actor_clerk_user_id != document.owner_clerk_user_id:
        raise ValueError("verified document owner required")
    base = f"{document.owner_clerk_user_id}/{document.id}"
    exact = [document.quarantine_key]
    if document.clean_key:
        exact.append(document.clean_key)
    return DeletionInventory(
        document_id=document.id,
        owner_clerk_user_id=document.owner_clerk_user_id,
        exact_object_keys=tuple(exact),
        object_prefixes=(
            f"derivative/{base}/",
            f"evidence/{base}/",
        ),
    )


def verify_deletion_completion(
    *,
    inventory: DeletionInventory,
    remaining_exact_keys: tuple[str, ...],
    remaining_prefixed_keys: tuple[str, ...],
    document_record_exists: bool,
    processing_job_count: int,
    finding_count: int,
    consent_count: int,
    objects_deleted: int,
    records_deleted: int,
) -> DeletionProof:
    """Require absence checks across every live object and durable record class."""
    reasons: list[str] = []
    unexpected_exact = set(remaining_exact_keys) & set(inventory.exact_object_keys)
    if unexpected_exact:
        reasons.append("original_object_still_present")
    if any(
        key.startswith(prefix)
        for key in remaining_prefixed_keys
        for prefix in inventory.object_prefixes
    ):
        reasons.append("derived_or_evidence_object_still_present")
    if document_record_exists:
        reasons.append("document_record_still_present")
    if processing_job_count:
        reasons.append("processing_job_record_still_present")
    if finding_count:
        reasons.append("finding_record_still_present")
    if consent_count:
        reasons.append("model_consent_record_still_present")
    if min(
        processing_job_count,
        finding_count,
        consent_count,
        objects_deleted,
        records_deleted,
    ) < 0:
        reasons.append("deletion_count_invalid")
    result = tuple(dict.fromkeys(reasons))
    return DeletionProof(
        verified=not result,
        reasons=result,
        objects_deleted=objects_deleted,
        records_deleted=records_deleted,
    )


def automatic_retention_deadline() -> None:
    """Real documents have no time-based deletion deadline."""
    return None
