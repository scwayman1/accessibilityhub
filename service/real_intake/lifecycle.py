"""Owner-scoped document state and clean-only worker eligibility contracts."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from service.real_intake.identifiers import (
    require_owner_clerk_user_id,
    require_uuid4,
)
from service.real_intake.upload_gate import ReleaseDecision


class DocumentState(str, Enum):
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    CLEAN = "clean"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    DELETION_PENDING = "deletion_pending"


ALLOWED_TRANSITIONS = {
    DocumentState.QUARANTINED: {
        DocumentState.REJECTED,
        DocumentState.CLEAN,
        DocumentState.DELETION_PENDING,
    },
    DocumentState.REJECTED: {DocumentState.DELETION_PENDING},
    DocumentState.CLEAN: {
        DocumentState.QUEUED,
        DocumentState.DELETION_PENDING,
    },
    DocumentState.QUEUED: {
        DocumentState.PROCESSING,
        DocumentState.DELETION_PENDING,
    },
    DocumentState.PROCESSING: {
        DocumentState.READY,
        DocumentState.CLEAN,
        DocumentState.DELETION_PENDING,
    },
    DocumentState.READY: {
        DocumentState.QUEUED,
        DocumentState.DELETION_PENDING,
    },
    DocumentState.DELETION_PENDING: set(),
}


@dataclass(frozen=True)
class RealDocumentRecord:
    id: str
    owner_clerk_user_id: str
    state: DocumentState
    quarantine_key: str
    clean_key: str | None = None

    def __post_init__(self) -> None:
        require_uuid4(self.id, label="document ID")
        require_owner_clerk_user_id(self.owner_clerk_user_id)
        required_quarantine = (
            f"quarantine/{self.owner_clerk_user_id}/{self.id}.pdf"
        )
        if self.quarantine_key != required_quarantine:
            raise ValueError("document quarantine key is not owner/document scoped")
        if self.clean_key is not None:
            required_clean = f"clean/{self.owner_clerk_user_id}/{self.id}.pdf"
            if self.clean_key != required_clean:
                raise ValueError("document clean key is not owner/document scoped")

    def transition(self, next_state: DocumentState) -> "RealDocumentRecord":
        if next_state not in ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(
                f"document transition {self.state.value}->{next_state.value} denied"
            )
        if next_state in {
            DocumentState.CLEAN,
            DocumentState.QUEUED,
            DocumentState.PROCESSING,
            DocumentState.READY,
        } and not self.clean_key:
            raise ValueError("clean object reference required for this state")
        return replace(self, state=next_state)


@dataclass(frozen=True)
class ProcessingJobEnvelope:
    id: str
    document_id: str
    owner_clerk_user_id: str
    clean_storage_key: str
    deterministic_only: bool = True
    external_egress_allowed: bool = False


def create_processing_job(
    *,
    job_id: str,
    actor_clerk_user_id: str,
    document: RealDocumentRecord,
    release: ReleaseDecision,
) -> ProcessingJobEnvelope:
    """Create a worker envelope only for the bound owner and clean evidence."""
    require_uuid4(job_id, label="job ID")
    if actor_clerk_user_id != document.owner_clerk_user_id:
        raise ValueError("verified document owner required")
    if document.state is not DocumentState.CLEAN:
        raise ValueError("document must be in clean state before queueing")
    if not release.eligible_for_processing or release.reasons:
        raise ValueError("complete clean release evidence required")
    if not document.clean_key:
        raise ValueError("clean storage key required")
    return ProcessingJobEnvelope(
        id=job_id,
        document_id=document.id,
        owner_clerk_user_id=document.owner_clerk_user_id,
        clean_storage_key=document.clean_key,
    )
