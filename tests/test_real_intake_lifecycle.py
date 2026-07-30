import unittest
from datetime import UTC, datetime

from service.real_intake.consent import (
    ModelEgressConsent,
    ModelEgressRequest,
    authorize_model_egress,
)
from service.real_intake.deletion import (
    RETENTION_POLICY,
    automatic_retention_deadline,
    build_deletion_inventory,
    verify_deletion_completion,
)
from service.real_intake.lifecycle import (
    DocumentState,
    RealDocumentRecord,
    create_processing_job,
)
from service.real_intake.rate_limit import (
    POLICIES,
    SensitiveAction,
    check_rate_limit,
)
from service.real_intake.upload_gate import ReleaseDecision


OWNER_ID = "user_2RfWKJREkjKbHZy0Wqa5qrHeAnb"
OTHER_ID = "user_000000000000000000000000000"
DOCUMENT_ID = "c2b21f86-66f7-43f5-94a4-4c5f9f9c35af"
JOB_ID = "90111f60-5614-4b48-8407-44893c75fc3c"


def document(state=DocumentState.QUARANTINED, clean=False):
    return RealDocumentRecord(
        id=DOCUMENT_ID,
        owner_clerk_user_id=OWNER_ID,
        state=state,
        quarantine_key=f"quarantine/{OWNER_ID}/{DOCUMENT_ID}.pdf",
        clean_key=f"clean/{OWNER_ID}/{DOCUMENT_ID}.pdf" if clean else None,
    )


class DocumentLifecycleTests(unittest.TestCase):
    def test_quarantined_document_cannot_skip_to_processing(self):
        item = document()
        for state in (
            DocumentState.QUEUED,
            DocumentState.PROCESSING,
            DocumentState.READY,
        ):
            with self.assertRaises(ValueError, msg=state):
                item.transition(state)

    def test_clean_to_queue_to_processing_to_ready_is_explicit(self):
        clean = document(clean=True).transition(DocumentState.CLEAN)
        queued = clean.transition(DocumentState.QUEUED)
        processing = queued.transition(DocumentState.PROCESSING)
        ready = processing.transition(DocumentState.READY)
        self.assertEqual(ready.state, DocumentState.READY)

    def test_deleted_pending_is_terminal_in_live_record_state_machine(self):
        pending = document().transition(DocumentState.DELETION_PENDING)
        for state in DocumentState:
            with self.assertRaises(ValueError, msg=state):
                pending.transition(state)

    def test_owner_and_document_scoped_storage_keys_are_mandatory(self):
        invalid = (
            f"quarantine/{OTHER_ID}/{DOCUMENT_ID}.pdf",
            f"quarantine/{OWNER_ID}/other.pdf",
            f"clean/{OTHER_ID}/{DOCUMENT_ID}.pdf",
        )
        for key in invalid:
            with self.assertRaises(ValueError, msg=key):
                RealDocumentRecord(
                    id=DOCUMENT_ID,
                    owner_clerk_user_id=OWNER_ID,
                    state=DocumentState.QUARANTINED,
                    quarantine_key=(
                        key if key.startswith("quarantine") else
                        f"quarantine/{OWNER_ID}/{DOCUMENT_ID}.pdf"
                    ),
                    clean_key=key if key.startswith("clean") else None,
                )

    def test_identity_and_document_identifiers_are_canonical(self):
        for owner_id in ("user_", "user_../../escape", "owner@example.com"):
            with self.assertRaises(ValueError, msg=owner_id):
                RealDocumentRecord(
                    id=DOCUMENT_ID,
                    owner_clerk_user_id=owner_id,
                    state=DocumentState.QUARANTINED,
                    quarantine_key=f"quarantine/{owner_id}/{DOCUMENT_ID}.pdf",
                )
        with self.assertRaises(ValueError):
            RealDocumentRecord(
                id=DOCUMENT_ID.upper(),
                owner_clerk_user_id=OWNER_ID,
                state=DocumentState.QUARANTINED,
                quarantine_key=f"quarantine/{OWNER_ID}/{DOCUMENT_ID.upper()}.pdf",
            )


class ProcessingEligibilityTests(unittest.TestCase):
    def test_only_bound_owner_clean_state_and_complete_release_can_queue(self):
        clean = document(state=DocumentState.CLEAN, clean=True)
        job = create_processing_job(
            job_id=JOB_ID,
            actor_clerk_user_id=OWNER_ID,
            document=clean,
            release=ReleaseDecision(True, ()),
        )
        self.assertEqual(job.clean_storage_key, clean.clean_key)
        self.assertTrue(job.deterministic_only)
        self.assertFalse(job.external_egress_allowed)

    def test_owner_state_and_release_fail_closed_independently(self):
        clean = document(state=DocumentState.CLEAN, clean=True)
        cases = (
            {
                "actor_clerk_user_id": OTHER_ID,
                "document": clean,
                "release": ReleaseDecision(True, ()),
            },
            {
                "actor_clerk_user_id": OWNER_ID,
                "document": document(state=DocumentState.QUARANTINED),
                "release": ReleaseDecision(True, ()),
            },
            {
                "actor_clerk_user_id": OWNER_ID,
                "document": clean,
                "release": ReleaseDecision(False, ("scan_indeterminate",)),
            },
        )
        for case in cases:
            with self.assertRaises(ValueError, msg=case):
                create_processing_job(job_id=JOB_ID, **case)


class ManualDeletionTests(unittest.TestCase):
    def test_retention_has_no_automatic_deadline(self):
        self.assertEqual(RETENTION_POLICY, "manual-owner-deletion-only")
        self.assertIsNone(automatic_retention_deadline())

    def test_inventory_covers_original_clean_derivative_and_evidence(self):
        item = document(state=DocumentState.READY, clean=True)
        inventory = build_deletion_inventory(
            actor_clerk_user_id=OWNER_ID, document=item
        )
        self.assertEqual(
            set(inventory.exact_object_keys),
            {item.quarantine_key, item.clean_key},
        )
        self.assertEqual(
            set(inventory.object_prefixes),
            {
                f"derivative/{OWNER_ID}/{DOCUMENT_ID}/",
                f"evidence/{OWNER_ID}/{DOCUMENT_ID}/",
            },
        )

    def test_non_owner_cannot_build_deletion_inventory(self):
        with self.assertRaises(ValueError):
            build_deletion_inventory(
                actor_clerk_user_id=OTHER_ID,
                document=document(),
            )

    def test_completion_requires_every_object_and_record_class_absent(self):
        inventory = build_deletion_inventory(
            actor_clerk_user_id=OWNER_ID,
            document=document(state=DocumentState.READY, clean=True),
        )
        proof = verify_deletion_completion(
            inventory=inventory,
            remaining_exact_keys=(),
            remaining_prefixed_keys=(),
            document_record_exists=False,
            processing_job_count=0,
            finding_count=0,
            consent_count=0,
            objects_deleted=4,
            records_deleted=4,
        )
        self.assertTrue(proof.verified)

        failed = verify_deletion_completion(
            inventory=inventory,
            remaining_exact_keys=(inventory.exact_object_keys[0],),
            remaining_prefixed_keys=(
                f"evidence/{OWNER_ID}/{DOCUMENT_ID}/page-1.json",
            ),
            document_record_exists=True,
            processing_job_count=1,
            finding_count=1,
            consent_count=1,
            objects_deleted=0,
            records_deleted=0,
        )
        self.assertFalse(failed.verified)
        self.assertEqual(
            set(failed.reasons),
            {
                "original_object_still_present",
                "derived_or_evidence_object_still_present",
                "document_record_still_present",
                "processing_job_record_still_present",
                "finding_record_still_present",
                "model_consent_record_still_present",
            },
        )


class ModelEgressConsentTests(unittest.TestCase):
    def setUp(self):
        self.request = ModelEgressRequest(
            document_id=DOCUMENT_ID,
            actor_clerk_user_id=OWNER_ID,
            provider="future-provider",
            purpose="draft-explanation",
            byok_credential_reference="render-secret:future-provider-key",
        )
        self.consent = ModelEgressConsent(
            id="consent-id",
            document_id=DOCUMENT_ID,
            owner_clerk_user_id=OWNER_ID,
            provider="future-provider",
            purpose="draft-explanation",
            granted_at=datetime.now(UTC),
        )

    def test_default_disabled_state_denies_even_with_consent_and_byok(self):
        decision = authorize_model_egress(
            feature_enabled=False,
            request=self.request,
            document_owner_clerk_user_id=OWNER_ID,
            consent=self.consent,
        )
        self.assertFalse(decision.allowed)
        self.assertIn("model_egress_disabled", decision.reasons)

    def test_future_enabled_path_requires_exact_document_owner_provider_purpose(self):
        decision = authorize_model_egress(
            feature_enabled=True,
            request=self.request,
            document_owner_clerk_user_id=OWNER_ID,
            consent=self.consent,
        )
        self.assertTrue(decision.allowed)

        mismatched = ModelEgressConsent(
            **{
                **self.consent.__dict__,
                "document_id": "90111f60-5614-4b48-8407-44893c75fc3c",
                "provider": "other-provider",
            }
        )
        denied = authorize_model_egress(
            feature_enabled=True,
            request=self.request,
            document_owner_clerk_user_id=OWNER_ID,
            consent=mismatched,
        )
        self.assertFalse(denied.allowed)
        self.assertIn("consent_document_mismatch", denied.reasons)
        self.assertIn("consent_provider_mismatch", denied.reasons)

    def test_revoked_missing_consent_and_missing_byok_are_denied(self):
        revoked = ModelEgressConsent(
            **{**self.consent.__dict__, "revoked_at": datetime.now(UTC)}
        )
        no_byok = ModelEgressRequest(
            **{**self.request.__dict__, "byok_credential_reference": None}
        )
        for request, consent, reason in (
            (self.request, revoked, "document_consent_revoked"),
            (self.request, None, "document_consent_required"),
            (no_byok, self.consent, "byok_credential_required"),
        ):
            decision = authorize_model_egress(
                feature_enabled=True,
                request=request,
                document_owner_clerk_user_id=OWNER_ID,
                consent=consent,
            )
            self.assertFalse(decision.allowed)
            self.assertIn(reason, decision.reasons)


class FakeRateLimitStore:
    def __init__(self, response=(True, 1, 0), error=None):
        self.response = response
        self.error = error
        self.calls = []

    def consume(self, bucket, *, limit, window_seconds):
        self.calls.append((bucket, limit, window_seconds))
        if self.error:
            raise self.error
        return self.response


class RateLimitContractTests(unittest.TestCase):
    def test_every_sensitive_action_has_a_positive_bounded_policy(self):
        self.assertEqual(set(POLICIES), set(SensitiveAction))
        for policy in POLICIES.values():
            self.assertGreater(policy.limit, 0)
            self.assertGreater(policy.window_seconds, 0)
            self.assertLessEqual(policy.window_seconds, 60 * 60)

    def test_bucket_uses_hashed_owner_not_raw_identity(self):
        store = FakeRateLimitStore()
        decision = check_rate_limit(
            store=store,
            owner_clerk_user_id=OWNER_ID,
            action=SensitiveAction.DELETION_REQUEST,
        )
        self.assertTrue(decision.allowed)
        bucket = store.calls[0][0]
        self.assertNotIn(OWNER_ID, bucket)
        self.assertTrue(bucket.startswith("real-intake:deletion_request:"))

    def test_limit_exceeded_store_failure_and_invalid_response_deny(self):
        cases = (
            (
                FakeRateLimitStore(response=(False, 0, 10)),
                "rate_limit_exceeded",
            ),
            (
                FakeRateLimitStore(error=RuntimeError("unavailable")),
                "rate_limit_store_unavailable",
            ),
            (
                FakeRateLimitStore(response=(True, -1, -1)),
                "rate_limit_store_invalid_response",
            ),
            (
                FakeRateLimitStore(response=("yes", 1, 0)),
                "rate_limit_store_invalid_response",
            ),
            (
                FakeRateLimitStore(response=(True, 6, 0)),
                "rate_limit_store_invalid_response",
            ),
        )
        for store, reason in cases:
            decision = check_rate_limit(
                store=store,
                owner_clerk_user_id=OWNER_ID,
                action=SensitiveAction.UPLOAD_AUTHORIZATION,
            )
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.reason, reason)


if __name__ == "__main__":
    unittest.main()
