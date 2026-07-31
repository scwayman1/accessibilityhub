import unittest
import io
import struct
from datetime import UTC, datetime, timedelta
from uuid import UUID

from service.real_intake.clamav import build_scan_evidence, classify_scan_response
from service.real_intake.clamd_client import parse_private_endpoint, scan_stream
from service.real_intake.upload_authorization import (
    MAX_AUTHORIZATION_LIFETIME,
    authorize_upload_completion,
    create_upload_authorization,
    storage_signing_conditions,
)
from service.real_intake.upload_gate import ScanVerdict, UploadPolicy


OWNER_ID = "user_2RfWKJREkjKbHZy0Wqa5qrHeAnb"
OTHER_ID = "user_000000000000000000000000000"
DOCUMENT_ID = "c2b21f86-66f7-43f5-94a4-4c5f9f9c35af"
NOW = datetime(2026, 7, 30, 20, 0, tzinfo=UTC)


class UploadAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.authorization = create_upload_authorization(
            document_id=DOCUMENT_ID,
            owner_clerk_user_id=OWNER_ID,
            now=NOW,
        )

    def test_authorization_is_short_lived_owner_scoped_and_exact(self):
        UUID(self.authorization.id)
        self.assertEqual(
            self.authorization.quarantine_key,
            f"quarantine/{OWNER_ID}/{DOCUMENT_ID}.pdf",
        )
        self.assertEqual(self.authorization.content_type, "application/pdf")
        self.assertEqual(self.authorization.max_bytes, UploadPolicy().max_bytes)
        self.assertLessEqual(
            self.authorization.expires_at - self.authorization.created_at,
            MAX_AUTHORIZATION_LIFETIME,
        )

    def test_signing_conditions_require_encryption_and_forbid_public_acl(self):
        conditions = dict(storage_signing_conditions(self.authorization))
        self.assertEqual(conditions["key"], self.authorization.quarantine_key)
        self.assertEqual(conditions["Content-Type"], "application/pdf")
        self.assertTrue(conditions["server-side-encryption-required"])
        self.assertTrue(conditions["public-acl-forbidden"])
        serialized = repr(conditions).lower()
        for prohibited in ("credential", "secret", "signature", "https://"):
            self.assertNotIn(prohibited, serialized)

    def test_lifetime_cannot_exceed_five_minutes(self):
        for lifetime in (timedelta(0), timedelta(minutes=5, seconds=1)):
            with self.assertRaises(ValueError):
                create_upload_authorization(
                    document_id=DOCUMENT_ID,
                    owner_clerk_user_id=OWNER_ID,
                    now=NOW,
                    lifetime=lifetime,
                )

    def test_untrusted_identity_and_noncanonical_document_id_are_rejected(self):
        for owner_id in ("user_", "user_../../escape", "scott@example.com"):
            with self.assertRaises(ValueError, msg=owner_id):
                create_upload_authorization(
                    document_id=DOCUMENT_ID,
                    owner_clerk_user_id=owner_id,
                    now=NOW,
                )
        for document_id in (
            DOCUMENT_ID.upper(),
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "not-a-document-id",
        ):
            with self.assertRaises(ValueError, msg=document_id):
                create_upload_authorization(
                    document_id=document_id,
                    owner_clerk_user_id=OWNER_ID,
                    now=NOW,
                )

    def test_completion_requires_unused_unexpired_exact_owner_object(self):
        accepted = authorize_upload_completion(
            authorization=self.authorization,
            actor_clerk_user_id=OWNER_ID,
            storage_key=self.authorization.quarantine_key,
            content_type="application/pdf",
            object_size=1_024,
            now=NOW + timedelta(minutes=1),
        )
        self.assertTrue(accepted.allowed)

        cases = (
            {
                "actor_clerk_user_id": OTHER_ID,
                "reason": "upload_authorization_owner_mismatch",
            },
            {
                "storage_key": f"quarantine/{OWNER_ID}/other.pdf",
                "reason": "upload_authorization_key_mismatch",
            },
            {
                "content_type": "application/octet-stream",
                "reason": "upload_authorization_content_type_mismatch",
            },
            {
                "object_size": UploadPolicy().max_bytes + 1,
                "reason": "upload_authorization_size_mismatch",
            },
            {
                "now": NOW + timedelta(minutes=6),
                "reason": "upload_authorization_expired",
            },
        )
        base = {
            "authorization": self.authorization,
            "actor_clerk_user_id": OWNER_ID,
            "storage_key": self.authorization.quarantine_key,
            "content_type": "application/pdf",
            "object_size": 1_024,
            "now": NOW + timedelta(minutes=1),
        }
        for case in cases:
            reason = case.pop("reason")
            decision = authorize_upload_completion(**{**base, **case})
            self.assertFalse(decision.allowed)
            self.assertIn(reason, decision.reasons)

    def test_consumed_authorization_cannot_be_reused(self):
        consumed = self.authorization.__class__(
            **{**self.authorization.__dict__, "consumed_at": NOW}
        )
        decision = authorize_upload_completion(
            authorization=consumed,
            actor_clerk_user_id=OWNER_ID,
            storage_key=consumed.quarantine_key,
            content_type="application/pdf",
            object_size=1_024,
            now=NOW + timedelta(minutes=1),
        )
        self.assertFalse(decision.allowed)
        self.assertIn("upload_authorization_already_used", decision.reasons)

    def test_completion_time_before_authorization_creation_is_denied(self):
        decision = authorize_upload_completion(
            authorization=self.authorization,
            actor_clerk_user_id=OWNER_ID,
            storage_key=self.authorization.quarantine_key,
            content_type="application/pdf",
            object_size=1_024,
            now=NOW - timedelta(seconds=1),
        )
        self.assertFalse(decision.allowed)
        self.assertIn(
            "upload_authorization_not_yet_valid", decision.reasons
        )


class ClamAvEvidenceTests(unittest.TestCase):
    def test_only_exact_single_line_ok_is_clean(self):
        self.assertEqual(
            classify_scan_response(b"stream: OK").verdict,
            ScanVerdict.CLEAN,
        )
        near_misses = (
            b"",
            b"OK",
            b"anything: OK",
            b" stream: OK",
            b"stream: OK ",
            b"stream: ok",
            b"stream: OK\nsecond: OK",
            b"stream: OK\x00",
            b"x" * 1_025,
            b"stream: \xff",
            b"stream: ERROR",
            b"other: Win.Test FOUND",
            b"stream:  Win.Test FOUND",
        )
        for response in near_misses:
            self.assertEqual(
                classify_scan_response(response).verdict,
                ScanVerdict.INDETERMINATE,
                response[:50],
            )

    def test_found_is_rejected_without_exposing_signature_as_reason(self):
        verdict = classify_scan_response(
            b"stream: Win.Test.EICAR_HDB-1 FOUND"
        )
        self.assertEqual(verdict.verdict, ScanVerdict.REJECTED)
        self.assertEqual(verdict.reason_code, "malware_detected")
        self.assertNotIn("EICAR", verdict.reason_code)

    def test_definition_age_is_computed_and_future_clock_is_stale(self):
        fresh = build_scan_evidence(
            response=b"stream: OK",
            engine_version="ClamAV test",
            signature_database_version="test-db",
            definitions_updated_at=NOW - timedelta(minutes=5),
            now=NOW,
        )
        self.assertEqual(fresh.definitions_age_seconds, 300)
        self.assertEqual(fresh.verdict, ScanVerdict.CLEAN)

        future = build_scan_evidence(
            response=b"stream: OK",
            engine_version="ClamAV test",
            signature_database_version="test-db",
            definitions_updated_at=NOW + timedelta(minutes=5),
            now=NOW,
        )
        self.assertGreater(
            future.definitions_age_seconds,
            UploadPolicy().max_definition_age_seconds,
        )


class FakeClamdSocket:
    def __init__(self, response=b"stream: OK\n", error=None):
        self.responses = [response]
        self.error = error
        self.sent = []
        self.closed = False

    def sendall(self, data):
        if self.error:
            raise self.error
        self.sent.append(data)

    def recv(self, _size):
        if self.error:
            raise self.error
        return self.responses.pop(0) if self.responses else b""

    def close(self):
        self.closed = True


class ClamdClientTests(unittest.TestCase):
    def test_private_endpoint_rejects_urls_public_hosts_and_bad_ports(self):
        self.assertEqual(parse_private_endpoint("clamav-scanner:3310"), ("clamav-scanner", 3310))
        for endpoint in (
            "https://scanner.example.com",
            "scanner.example.com:3310",
            "127.0.0.1:3310",
            "clamav_scanner:3310",
            "clamav:0",
            "clamav:65536",
        ):
            with self.assertRaises(ValueError, msg=endpoint):
                parse_private_endpoint(endpoint)

    def test_instream_frames_bounded_bytes_and_zero_terminator(self):
        fake = FakeClamdSocket()
        result = scan_stream(
            endpoint="clamav-scanner:3310",
            stream=io.BytesIO(b"%PDF-test"),
            chunk_bytes=4,
            socket_factory=lambda address, timeout: fake,
        )
        self.assertEqual(result.verdict.verdict, ScanVerdict.CLEAN)
        self.assertEqual(result.bytes_streamed, len(b"%PDF-test"))
        self.assertEqual(fake.sent[0], b"nINSTREAM\n")
        self.assertEqual(fake.sent[-1], struct.pack("!I", 0))
        framed_lengths = [
            struct.unpack("!I", fake.sent[index])[0]
            for index in range(1, len(fake.sent) - 1, 2)
        ]
        self.assertEqual(framed_lengths, [4, 4, 1])
        self.assertTrue(fake.closed)

    def test_oversize_timeout_and_scanner_error_fail_closed(self):
        oversize = FakeClamdSocket()
        with self.assertRaises(ValueError):
            scan_stream(
                endpoint="clamav-scanner:3310",
                stream=io.BytesIO(b"12345"),
                max_bytes=4,
                socket_factory=lambda address, timeout: oversize,
            )
        self.assertTrue(oversize.closed)

        failed = FakeClamdSocket(error=TimeoutError())
        result = scan_stream(
            endpoint="clamav-scanner:3310",
            stream=io.BytesIO(b"1234"),
            socket_factory=lambda address, timeout: failed,
        )
        self.assertEqual(result.verdict.verdict, ScanVerdict.INDETERMINATE)
        self.assertTrue(failed.closed)

        unavailable = scan_stream(
            endpoint="clamav-scanner:3310",
            stream=io.BytesIO(b"1234"),
            socket_factory=lambda address, timeout: (_ for _ in ()).throw(
                ConnectionRefusedError()
            ),
        )
        self.assertEqual(
            unavailable.verdict.verdict, ScanVerdict.INDETERMINATE
        )

        for incomplete in (b"stream: OK", b"stream: OK\nextra"):
            malformed = FakeClamdSocket(response=incomplete)
            result = scan_stream(
                endpoint="clamav-scanner:3310",
                stream=io.BytesIO(b"1234"),
                socket_factory=lambda address, timeout: malformed,
            )
            self.assertEqual(
                result.verdict.verdict, ScanVerdict.INDETERMINATE
            )


if __name__ == "__main__":
    unittest.main()
