import io
import json
import time
import unittest
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from service.real_intake.app import create_app
from service.real_intake.audit import AuditAction, create_audit_event
from service.real_intake.auth import AuthenticationFailure, OwnerAuthenticator
from service.real_intake.settings import (
    CONTROL_MANIFEST_VERSION,
    REQUIRED_CONFIGURATION,
    RealIntakeSettings,
    RuntimeControlEvidence,
)
from service.real_intake.upload_gate import (
    QuarantineObject,
    ScanEvidence,
    ScanVerdict,
    StructuralEvidence,
    UploadPolicy,
    basic_validation_issues,
    release_decision,
)


OWNER_ID = "user_2RfWKJREkjKbHZy0Wqa5qrHeAnb"
OTHER_ID = "user_000000000000000000000000000"
ISSUER = "https://example.clerk.accounts.dev"
ORIGIN = "https://accessibility.coastlinecollegefoundation.com"
JWT_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "test-only-placeholder\n"
    "-----END PUBLIC KEY-----"
)


def complete_environment(**overrides):
    environment = {
        "HUB_ENV": "development",
        "HUB_REAL_DOCUMENT_INTAKE": "true",
        "HUB_REAL_INTAKE_CONTROL_MANIFEST": CONTROL_MANIFEST_VERSION,
        "CLERK_PUBLISHABLE_KEY": "pk_test_not-a-real-key",
        "CLERK_JWT_KEY": JWT_KEY,
        "CLERK_ISSUER": ISSUER,
        "CLERK_AUTHORIZED_PARTY": ORIGIN,
        "HUB_OWNER_CLERK_USER_ID": OWNER_ID,
        "HUB_POSTGRES_PRIVATE_URL": "postgresql://private.invalid/hub",
        "HUB_QUEUE_PRIVATE_URL": "redis://private.invalid/0",
        "HUB_OBJECT_STORAGE_ENDPOINT": "https://private-storage.invalid",
        "HUB_OBJECT_STORAGE_BUCKET": "hub-private-test",
        "HUB_OBJECT_STORAGE_ACCESS_KEY_ID": "test-access-id",
        "HUB_OBJECT_STORAGE_SECRET_ACCESS_KEY": "test-secret",
        "HUB_CLAMAV_PRIVATE_ENDPOINT": "clamav:3310",
        "HUB_WORKER_ISOLATION_ATTESTATION": "worker-attestation-id",
        "HUB_AUDIT_SINK": "protected-audit-sink-id",
        "HUB_LIFECYCLE_POLICY_ID": "manual-delete-policy-id",
        "HUB_BACKUP_DELETION_SLA": "documented-backup-expiry-id",
        "HUB_REAL_INTAKE_VERIFICATION_ID": "verification-run-id",
    }
    environment.update(overrides)
    return environment


def all_runtime_evidence():
    excluded = {"verification_id", "checked_at"}
    return RuntimeControlEvidence(
        **{
            item.name: True
            for item in fields(RuntimeControlEvidence)
            if item.name not in excluded
        },
        verification_id="runtime-check-2026-07-30",
        checked_at=datetime.now(UTC),
    )


def claims(subject=OWNER_ID, authorized_party=ORIGIN, **overrides):
    payload = {
        "azp": authorized_party,
        "exp": 2_000_000_000,
        "iat": 1_900_000_000,
        "iss": ISSUER,
        "jti": "token-id",
        "nbf": 1_900_000_000,
        "sid": "sess_test",
        "sub": subject,
        "v": 2,
    }
    payload.update(overrides)
    return payload


class RealIntakeConfigurationTests(unittest.TestCase):
    def test_activation_flag_requires_exact_true(self):
        for value in ("", "TRUE", "True", "1", "yes", " true", "true ", "true\n"):
            settings = RealIntakeSettings.from_environ(
                complete_environment(HUB_REAL_DOCUMENT_INTAKE=value)
            )
            self.assertFalse(settings.activation_requested, value)
            self.assertFalse(
                settings.real_document_intake_enabled(all_runtime_evidence()), value
            )

    def test_every_configuration_reference_is_required(self):
        for code, variable in REQUIRED_CONFIGURATION.items():
            environment = complete_environment()
            environment.pop(variable)
            settings = RealIntakeSettings.from_environ(environment)
            self.assertIn(code, settings.configuration_blockers, variable)

    def test_staging_rejects_development_publishable_key(self):
        settings = RealIntakeSettings.from_environ(
            complete_environment(HUB_ENV="staging")
        )
        self.assertIn(
            "clerk_publishable_key_environment_mismatch",
            settings.configuration_blockers,
        )

    def test_authorized_party_is_one_exact_https_origin(self):
        invalid = (
            "http://real-intake.example.edu",
            "https://*.example.edu",
            "https://real-intake.example.edu/path",
            "https://real-intake.example.edu?next=bad",
            "https://user@real-intake.example.edu",
        )
        for origin in invalid:
            settings = RealIntakeSettings.from_environ(
                complete_environment(CLERK_AUTHORIZED_PARTY=origin)
            )
            self.assertIn(
                "clerk_authorized_party_must_be_exact_https_origin",
                settings.configuration_blockers,
                origin,
            )

    def test_authorized_party_is_pinned_to_the_approved_private_origin(self):
        for origin in (
            "https://accessibility-hub-staging.onrender.com",
            "https://preview-accessibility.onrender.com",
            "https://coastlinecollegefoundation.com",
            "https://accessibility.coastlinecollegefoundation.com/",
        ):
            settings = RealIntakeSettings.from_environ(
                complete_environment(CLERK_AUTHORIZED_PARTY=origin)
            )
            self.assertIn(
                "clerk_authorized_party_not_approved_origin",
                settings.configuration_blockers,
                origin,
            )

    def test_environment_values_cannot_replace_runtime_control_evidence(self):
        settings = RealIntakeSettings.from_environ(complete_environment())
        self.assertFalse(settings.configuration_blockers)
        self.assertFalse(settings.real_document_intake_enabled())
        self.assertTrue(
            any(
                blocker.startswith("runtime_")
                for blocker in settings.activation_blockers()
            )
        )
        self.assertFalse(
            settings.real_document_intake_enabled(all_runtime_evidence())
        )
        self.assertIn(
            "real_document_action_handlers_not_implemented",
            settings.activation_blockers(all_runtime_evidence()),
        )

    def test_model_egress_is_a_blocker_even_with_all_other_controls(self):
        settings = RealIntakeSettings.from_environ(
            complete_environment(HUB_MODEL_EGRESS_ENABLED="true")
        )
        self.assertIn(
            "model_egress_must_remain_disabled",
            settings.activation_blockers(all_runtime_evidence()),
        )
        self.assertFalse(
            settings.real_document_intake_enabled(all_runtime_evidence())
        )

    def test_runtime_evidence_requires_fresh_timestamp_and_verification_id(self):
        evidence = all_runtime_evidence()
        now = datetime.now(UTC)
        self.assertFalse(evidence.blockers_at(now))
        missing = RuntimeControlEvidence(
            **{
                item.name: True
                for item in fields(RuntimeControlEvidence)
                if item.name not in {"verification_id", "checked_at"}
            }
        )
        self.assertIn(
            "runtime_verification_id_missing", missing.blockers_at(now)
        )
        self.assertIn(
            "runtime_evidence_timestamp_missing", missing.blockers_at(now)
        )
        stale = RuntimeControlEvidence(
            **{
                **evidence.__dict__,
                "checked_at": now - timedelta(minutes=6),
            }
        )
        self.assertIn("runtime_evidence_stale", stale.blockers_at(now))
        future = RuntimeControlEvidence(
            **{
                **evidence.__dict__,
                "checked_at": now + timedelta(minutes=1),
            }
        )
        self.assertIn(
            "runtime_evidence_timestamp_in_future", future.blockers_at(now)
        )


class OwnerAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.settings = RealIntakeSettings.from_environ(complete_environment())

    def authenticate(self, payload):
        authenticator = OwnerAuthenticator(
            self.settings, decoder=lambda _token, _key, _issuer: payload
        )
        return authenticator.authenticate({"HTTP_AUTHORIZATION": "Bearer token"})

    def test_verified_subject_becomes_the_actor_identity(self):
        identity = self.authenticate(claims())
        self.assertEqual(identity.clerk_user_id, OWNER_ID)
        self.assertEqual(identity.session_id, "sess_test")

    def test_email_claim_never_authorizes_a_different_subject(self):
        with self.assertRaises(AuthenticationFailure) as captured:
            self.authenticate(
                claims(
                    subject=OTHER_ID,
                    email="scott@coastlinecollegefoundation.com",
                )
            )
        self.assertEqual(captured.exception.status, 403)
        self.assertEqual(captured.exception.code, "owner_identity_required")

    def test_wrong_or_missing_authorized_party_fails_closed(self):
        for payload in (
            claims(authorized_party="https://other.example.edu"),
            {key: value for key, value in claims().items() if key != "azp"},
        ):
            with self.assertRaises(AuthenticationFailure):
                self.authenticate(payload)

    def test_pending_session_task_fails_closed(self):
        with self.assertRaises(AuthenticationFailure) as captured:
            self.authenticate(claims(sts="pending"))
        self.assertEqual(captured.exception.code, "session_tasks_incomplete")

    def test_near_miss_bearer_headers_are_rejected(self):
        authenticator = OwnerAuthenticator(
            self.settings, decoder=lambda _token, _key, _issuer: claims()
        )
        for header in (
            "",
            "bearer token",
            "Bearer",
            "Bearer  token",
            "Bearer token ",
            "Basic token",
        ):
            with self.assertRaises(AuthenticationFailure, msg=header):
                authenticator.authenticate({"HTTP_AUTHORIZATION": header})


class ClerkJwtCryptographicVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        cls.other_private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        cls.public_pem = cls.private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode().strip()

    def token(self, signing_key=None, **overrides):
        now = int(time.time())
        payload = claims()
        payload.update({"exp": now + 60, "iat": now, "nbf": now - 5})
        payload.update(overrides)
        return jwt.encode(
            payload,
            signing_key or self.private_key,
            algorithm="RS256",
            headers={"typ": "JWT"},
        )

    def authenticator(self, **environment_overrides):
        settings = RealIntakeSettings.from_environ(
            complete_environment(
                CLERK_JWT_KEY=self.public_pem,
                **environment_overrides,
            )
        )
        return OwnerAuthenticator(settings)

    def test_valid_rs256_signature_and_claims_are_accepted(self):
        identity = self.authenticator().authenticate(
            {"HTTP_AUTHORIZATION": f"Bearer {self.token()}"}
        )
        self.assertEqual(identity.clerk_user_id, OWNER_ID)

    def test_wrong_signature_issuer_expiry_and_not_before_are_rejected(self):
        now = int(time.time())
        tokens = (
            self.token(signing_key=self.other_private_key),
            self.token(iss="https://wrong.clerk.accounts.dev"),
            self.token(exp=now - 30, iat=now - 90, nbf=now - 90),
            self.token(exp=now + 120, iat=now, nbf=now + 60),
        )
        for token in tokens:
            with self.assertRaises(AuthenticationFailure):
                self.authenticator().authenticate(
                    {"HTTP_AUTHORIZATION": f"Bearer {token}"}
                )

    def test_non_rs256_algorithm_is_rejected_before_claim_use(self):
        now = int(time.time())
        token = jwt.encode(
            claims(exp=now + 60, iat=now, nbf=now - 5),
            "test-only-hmac-key",
            algorithm="HS256",
            headers={"typ": "JWT"},
        )
        with self.assertRaises(AuthenticationFailure) as captured:
            self.authenticator().authenticate(
                {"HTTP_AUTHORIZATION": f"Bearer {token}"}
            )
        self.assertEqual(captured.exception.code, "jwt_header_rejected")


class LockedControlPlaneTests(unittest.TestCase):
    def request(self, app, path, method="GET", authorization=""):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(
            app(
                {
                    "REQUEST_METHOD": method,
                    "PATH_INFO": path,
                    "HTTP_AUTHORIZATION": authorization,
                    "HTTP_HOST": "accessibility.coastlinecollegefoundation.com",
                    "HTTP_X_FORWARDED_PROTO": "https",
                    "wsgi.input": io.BytesIO(),
                },
                start_response,
            )
        )
        return captured["status"], captured["headers"], json.loads(body)

    def test_health_is_locked_without_runtime_attestations(self):
        settings = RealIntakeSettings.from_environ(complete_environment())
        app = create_app(settings)
        status, _, payload = self.request(app, "/healthz")
        self.assertTrue(status.startswith("200"))
        self.assertFalse(payload["real_document_intake_enabled"])
        self.assertTrue(payload["synthetic_only"])
        for header in (
            "Content-Security-Policy",
            "Cross-Origin-Opener-Policy",
            "Cross-Origin-Resource-Policy",
            "Permissions-Policy",
            "Strict-Transport-Security",
            "X-Content-Type-Options",
            "X-Frame-Options",
        ):
            self.assertIn(header, _)
        for sensitive_status in (
            "activation_requested",
            "configuration_ready",
            "runtime_controls_ready",
            "blockers",
        ):
            self.assertNotIn(sensitive_status, payload)

    def test_real_document_routes_do_not_exist_even_with_all_evidence(self):
        settings = RealIntakeSettings.from_environ(complete_environment())
        app = create_app(settings, runtime_evidence=all_runtime_evidence())
        for path in (
            "/api/upload-authorizations",
            "/api/real-documents",
            "/api/real-documents/document-id",
            "/api/real-documents/document-id/delete",
        ):
            status, _, payload = self.request(app, path, method="POST")
            self.assertTrue(status.startswith("503"), path)
            self.assertEqual(payload["error"], "real_document_intake_locked")
            self.assertFalse(payload["real_document_intake_enabled"])

    def test_protected_surface_rejects_alternate_host_and_http(self):
        settings = RealIntakeSettings.from_environ(complete_environment())
        authenticator = OwnerAuthenticator(
            settings, decoder=lambda _token, _key, _issuer: claims()
        )
        app = create_app(settings, authenticator=authenticator)

        def raw_request(host, forwarded_proto):
            captured = {}

            def start_response(status, headers):
                captured["status"] = status

            body = b"".join(
                app(
                    {
                        "REQUEST_METHOD": "GET",
                        "PATH_INFO": "/owner/session",
                        "HTTP_AUTHORIZATION": "Bearer token",
                        "HTTP_HOST": host,
                        "HTTP_X_FORWARDED_PROTO": forwarded_proto,
                        "wsgi.input": io.BytesIO(),
                    },
                    start_response,
                )
            )
            return captured["status"], json.loads(body)

        for host, proto in (
            ("accessibility-hub-staging.onrender.com", "https"),
            ("preview.onrender.com", "https"),
            ("accessibility.coastlinecollegefoundation.com", "http"),
            ("accessibility.coastlinecollegefoundation.com:443", "https"),
        ):
            status, payload = raw_request(host, proto)
            self.assertTrue(status.startswith("404"), (host, proto))
            self.assertEqual(payload["error"], "not_found")

    def test_owner_probe_returns_only_bound_user_id(self):
        settings = RealIntakeSettings.from_environ(complete_environment())
        authenticator = OwnerAuthenticator(
            settings, decoder=lambda _token, _key, _issuer: claims()
        )
        app = create_app(settings, authenticator=authenticator)
        status, _, payload = self.request(
            app, "/owner/session", authorization="Bearer token"
        )
        self.assertTrue(status.startswith("200"))
        self.assertEqual(payload["clerk_user_id"], OWNER_ID)
        self.assertNotIn("session_id", payload)
        self.assertNotIn("token_id", payload)


class UploadGateTests(unittest.TestCase):
    def setUp(self):
        self.item = QuarantineObject(
            owner_clerk_user_id=OWNER_ID,
            storage_key=(
                f"quarantine/{OWNER_ID}/"
                "c2b21f86-66f7-43f5-94a4-4c5f9f9c35af.pdf"
            ),
            original_filename="course-handout.pdf",
            declared_content_type="application/pdf",
            object_size=1_024,
            signature_prefix=b"%PDF-1.7",
        )
        self.scan = ScanEvidence(
            verdict=ScanVerdict.CLEAN,
            definitions_age_seconds=60,
            engine_version="test-clamav",
            signature_database_version="test-signatures",
        )
        self.structure = StructuralEvidence(
            parser_completed=True,
            page_count=10,
            stream_count=20,
            expanded_stream_bytes=4_096,
        )

    def test_only_fully_verified_object_is_eligible(self):
        decision = release_decision(self.item, self.scan, self.structure)
        self.assertTrue(decision.eligible_for_processing)
        self.assertFalse(decision.reasons)

    def test_scanner_failures_and_stale_definitions_are_rejected(self):
        cases = (
            (None, "scanner_unavailable"),
            (
                ScanEvidence(
                    ScanVerdict.REJECTED, 60, "test-clamav", "test-signatures"
                ),
                "scan_rejected",
            ),
            (
                ScanEvidence(
                    ScanVerdict.INDETERMINATE,
                    60,
                    "test-clamav",
                    "test-signatures",
                ),
                "scan_indeterminate",
            ),
            (
                ScanEvidence(
                    ScanVerdict.CLEAN,
                    UploadPolicy().max_definition_age_seconds + 1,
                    "test-clamav",
                    "test-signatures",
                ),
                "scan_definitions_stale",
            ),
        )
        for scan, reason in cases:
            decision = release_decision(self.item, scan, self.structure)
            self.assertFalse(decision.eligible_for_processing)
            self.assertIn(reason, decision.reasons)

    def test_owner_prefix_mime_signature_and_size_are_all_enforced(self):
        hostile = QuarantineObject(
            owner_clerk_user_id=OWNER_ID,
            storage_key=(
                f"quarantine/{OTHER_ID}/"
                "c2b21f86-66f7-43f5-94a4-4c5f9f9c35af.pdf"
            ),
            original_filename="../course-handout.exe",
            declared_content_type="application/octet-stream",
            object_size=UploadPolicy().max_bytes + 1,
            signature_prefix=b"MZ",
        )
        issues = basic_validation_issues(hostile)
        for expected in (
            "filename_rejected",
            "declared_content_type_rejected",
            "object_size_rejected",
            "file_signature_rejected",
            "quarantine_owner_mismatch",
        ):
            self.assertIn(expected, issues)

    def test_structure_must_be_bounded_after_clean_scan(self):
        oversized = StructuralEvidence(
            parser_completed=True,
            page_count=UploadPolicy().max_pages + 1,
            stream_count=UploadPolicy().max_streams + 1,
            expanded_stream_bytes=UploadPolicy().max_expanded_stream_bytes + 1,
        )
        decision = release_decision(self.item, self.scan, oversized)
        self.assertFalse(decision.eligible_for_processing)
        self.assertEqual(
            set(decision.reasons),
            {
                "page_limit_rejected",
                "stream_count_rejected",
                "expanded_stream_limit_rejected",
            },
        )


class AuditBoundaryTests(unittest.TestCase):
    def test_verified_owner_and_allowlisted_metadata_create_event(self):
        event = create_audit_event(
            owner_clerk_user_id=OWNER_ID,
            actor_clerk_user_id=OWNER_ID,
            action=AuditAction.SCAN_COMPLETED,
            target_id="c2b21f86-66f7-43f5-94a4-4c5f9f9c35af",
            request_id="request-id",
            detail={
                "outcome": "clean",
                "engine_version": "test-clamav",
                "signature_database_version": "test-signatures",
                "definitions_age_seconds": 60,
            },
        )
        self.assertEqual(event.actor_clerk_user_id, OWNER_ID)
        self.assertEqual(event.action, AuditAction.SCAN_COMPLETED)

    def test_audit_target_and_owner_identifiers_are_canonical(self):
        for owner_id, target_id in (
            ("user_../../escape", None),
            (OWNER_ID, "document-id"),
            (OWNER_ID, "6ba7b810-9dad-11d1-80b4-00c04fd430c8"),
        ):
            with self.assertRaises(ValueError):
                create_audit_event(
                    owner_clerk_user_id=owner_id,
                    actor_clerk_user_id=owner_id,
                    action=AuditAction.DOCUMENT_VIEWED,
                    target_id=target_id,
                    request_id="request-id",
                )

    def test_audit_actor_cannot_be_supplied_as_another_identity(self):
        with self.assertRaises(ValueError):
            create_audit_event(
                owner_clerk_user_id=OWNER_ID,
                actor_clerk_user_id=OTHER_ID,
                action=AuditAction.DOCUMENT_VIEWED,
                target_id=None,
                request_id="request-id",
            )

    def test_unknown_action_is_rejected(self):
        with self.assertRaises(ValueError):
            create_audit_event(
                owner_clerk_user_id=OWNER_ID,
                actor_clerk_user_id=OWNER_ID,
                action="arbitrary_action",
                target_id=None,
                request_id="request-id",
            )

    def test_content_urls_tokens_and_unbounded_values_are_rejected(self):
        unsafe_details = (
            {"ocr_text": "private words"},
            {"signed_url": "https://storage.invalid/private"},
            {"engine_version": "https://unexpected.invalid"},
            {"engine_version": "x" * 257},
        )
        for detail in unsafe_details:
            with self.assertRaises(ValueError, msg=detail):
                create_audit_event(
                    owner_clerk_user_id=OWNER_ID,
                    actor_clerk_user_id=OWNER_ID,
                    action=AuditAction.SCAN_COMPLETED,
                    target_id=None,
                    request_id="request-id",
                    detail=detail,
                )


class DeploymentSeparationTests(unittest.TestCase):
    def test_public_service_never_imports_or_deploys_real_intake(self):
        public_sources = (
            Path("service/app.py").read_text(),
            Path("service/wsgi.py").read_text(),
            Path("render.yaml").read_text(),
        )
        for source in public_sources:
            self.assertNotIn("service.real_intake", source)
            self.assertNotIn("HUB_REAL_DOCUMENT_INTAKE", source)
        self.assertNotIn("real-intake", public_sources[-1])
        self.assertNotIn("PyJWT", Path("requirements.txt").read_text())
        self.assertIn(
            "PyJWT[crypto]==2.10.1",
            Path("requirements-real-intake.txt").read_text(),
        )

    def test_postgres_schema_forces_owner_rls_and_append_only_audit(self):
        schema = Path("service/real_intake/schema.sql").read_text()
        for table in (
            "real_documents",
            "real_processing_jobs",
            "real_upload_authorizations",
            "real_deletion_requests",
            "real_findings",
            "real_model_egress_consents",
            "real_audit_events",
        ):
            self.assertIn(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY", schema)
        self.assertIn("BEFORE UPDATE OR DELETE ON real_audit_events", schema)
        self.assertIn("actor_clerk_user_id = owner_clerk_user_id", schema)
        self.assertIn("consume_real_upload_authorization", schema)
        self.assertIn("AND consumed_at IS NULL", schema)
        self.assertIn("real_audit_detail_is_safe", schema)
        self.assertIn(
            "'quarantine/' || owner_clerk_user_id || '/' || id::text || '.pdf'",
            schema,
        )
        self.assertIn("RETURNING *", schema)
        self.assertNotIn(" BYTEA", schema)


if __name__ == "__main__":
    unittest.main()
