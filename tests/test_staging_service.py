import io
import json
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode


def visible_text(page: bytes) -> str:
    """The text a teacher can actually read: no styles, no tags, lowercased."""
    text = page.decode("utf-8", "replace")
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return text.lower()


# Words that must never appear on an educator-facing page (drop, processing,
# ready). The classic access-code surface keeps its honest environment labels.
SCRUBBED_WORDS = ("synthetic", "development", "staging", "workspace")

from service.app import create_app
from service.repository import StagingRepository
from service.settings import ServiceSettings
from service.worker import AssessmentWorker


class StagingServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = ServiceSettings(
            environment="development",
            data_dir=Path(self.temp.name),
            access_code="synthetic-only-code",
            session_secret="s" * 48,
            hosted_controls=(),
        )
        self.repository = StagingRepository(self.settings.data_dir)
        self.worker = AssessmentWorker(self.repository)
        self.app = create_app(self.settings, self.repository, self.worker)
        self.cookie = ""

    def tearDown(self):
        self.worker.stop()
        self.temp.cleanup()

    def request(self, path, method="GET", form=None, cookie=None):
        query = ""
        if "?" in path:
            path, query = path.split("?", 1)
        body = urlencode(form or {}).encode()
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)
        response = b"".join(self.app({
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/x-www-form-urlencoded",
            "wsgi.input": io.BytesIO(body),
            "HTTP_COOKIE": cookie or self.cookie,
        }, start_response))
        return captured["status"], captured["headers"], response

    def login(self):
        status, headers, _ = self.request("/login", "POST", {"code": "synthetic-only-code"})
        self.assertTrue(status.startswith("303"))
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]

    def login_sso(self):
        # The demo educator session (development only): unlocks the real
        # local-upload workspace that access-code sessions never see.
        status, headers, _ = self.request("/login/sso", "POST")
        self.assertTrue(status.startswith("303"))
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]

    def wait_for_result(self, document_id):
        for _ in range(160):
            job = self.repository.latest_job("coastline-staging", document_id)
            if job and job["state"] in {"succeeded", "failed"}:
                return job
            time.sleep(0.05)
        self.fail("assessment did not complete")

    def test_health_is_visible_but_closed_service_requires_access_setup(self):
        status, _, body = self.request("/healthz")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"synthetic_only", body)
        status, headers, _ = self.request("/app")
        self.assertTrue(status.startswith("303"))
        self.assertEqual(headers["Location"], "/login")
        # The configured local app accepts only an explicit staging-code session.
        status, _, _ = self.request("/app")
        self.assertTrue(status.startswith("303"))

    def test_private_shell_serves_the_unmodified_official_coastline_logo(self):
        status, headers, payload = self.request("/assets/coastline-college-logo-white.png")
        self.assertTrue(status.startswith("200"))
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
        self.login()
        self.assertIn(b"coastline-college-logo-white.png", self.request("/app")[2])

    def test_private_workspace_uses_labeled_workflow_steps_and_finding_chips(self):
        # The classic access-code surface keeps the labeled rail and lanes.
        self.login()
        status, _, workspace = self.request("/app")
        self.assertTrue(status.startswith("200"))
        for label in (b"Review", b"Understand", b"Improve", b"Verify"):
            self.assertIn(label, workspace)
        self.assertIn(b"class=app-shell", workspace)
        self.assertIn(b"class=sidebar", workspace)
        self.assertIn(b'href="#main-content"', workspace)
        self.assertEqual(workspace.count(b'aria-current="step"'), 1)
        self.assertIn(b"Start a sample review", workspace)
        self.assertIn(b"Try the scanned sample", workspace)
        self.assertIn(b":focus-visible", workspace)
        self.assertIn(b"@media(max-width:900px)", workspace)
        self.assertIn(b".app-shell { grid-template-columns:1fr }", workspace)
        self.assertIn(b"prefers-reduced-motion:reduce", workspace)

        _, headers, _ = self.request("/documents/synthetic", "POST")
        document_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(document_id)
        status, _, page = self.request(f"/documents/{document_id}")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b'class="chip"', page)
        self.assertIn(b"Needs attention", page)
        self.assertIn(b"signal-icon", page)

    def test_private_synthetic_document_to_recheck_flow(self):
        self.login()
        status, headers, _ = self.request("/documents/synthetic", "POST")
        self.assertTrue(status.startswith("303"))
        document_id = headers["Location"].rsplit("/", 1)[-1]
        job = self.wait_for_result(document_id)
        self.assertEqual(job["state"], "succeeded")
        before = job["result"]
        self.assertIn("PDF.METADATA.TITLE", {item["rule_id"] for item in before["signals"]})
        status, _, page = self.request(f"/documents/{document_id}")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Needs attention", page)
        self.assertIn(b"Fix the clearest issues", page)
        self.assertIn(b'for=document-title', page)
        self.assertIn(b'for=document-language', page)
        source_hash = self.repository.document("coastline-staging", document_id)["sha256"]

        status, headers, _ = self.request(
            f"/documents/{document_id}/remediate/metadata", "POST",
            {"title": "Week 3 Course Handout", "language": "en-US"},
        )
        self.assertTrue(status.startswith("303"))
        child_id = headers["Location"].rsplit("/", 1)[-1]
        after = self.wait_for_result(child_id)["result"]
        verified = {item["rule_id"] for item in after["signals"] if item["lane"] == "verified_signal"}
        self.assertIn("PDF.METADATA.TITLE", verified)
        self.assertIn("PDF.METADATA.LANGUAGE", verified)
        provenance = self.repository.remediations("coastline-staging", child_id)
        self.assertEqual(provenance[0]["kind"], "metadata")
        self.assertTrue(provenance[0]["provenance"]["mutates_document"])
        self.assertEqual(provenance[0]["provenance"]["actions"][0]["rule_id"], "PDF.METADATA.TITLE")
        status, _, child_page = self.request(f"/documents/{child_id}")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Recheck complete", child_page)
        self.assertIn(b"Your improved copy is ready", child_page)
        self.assertIn(b"2 accessibility signals are now verified", child_page)
        self.assertIn(document_id.encode(), child_page)
        self.assertIn(b'aria-current="step"', child_page)
        self.assertEqual(self.repository.document("coastline-staging", document_id)["sha256"], source_hash)
        status, headers, _ = self.request(f"/documents/{document_id}/delete", "POST", {"confirmed": "yes"})
        self.assertTrue(status.startswith("303"))
        self.assertEqual(headers["Location"], "/app")
        self.assertIsNone(self.repository.document("coastline-staging", document_id))
        self.assertIsNone(self.repository.document("coastline-staging", child_id))

    def test_hosted_staging_refuses_to_create_document_without_all_required_controls(self):
        self.settings = ServiceSettings("staging", Path(self.temp.name) / "hosted", "synthetic-only-code", "s" * 48, ())
        self.repository = StagingRepository(self.settings.data_dir)
        self.worker = AssessmentWorker(self.repository)
        self.app = create_app(self.settings, self.repository, self.worker)
        self.login()
        status, _, page = self.request("/documents/synthetic", "POST")
        self.assertTrue(status.startswith("503"))
        self.assertIn(b"not ready", page)

    def test_hosted_staging_stays_closed_even_when_control_references_are_present(self):
        controls = (
            "HUB_PRIVATE_OBJECT_STORAGE", "HUB_MALWARE_SCAN_GATE", "HUB_WORKER_ISOLATION_ATTESTATION",
            "HUB_TENANT_AUTH_ISSUER", "HUB_LIFECYCLE_POLICY_ID", "HUB_AUDIT_SINK",
        )
        settings = ServiceSettings("staging", Path(self.temp.name) / "configured-hosted", "synthetic-only-code", "s" * 48, controls)
        repository = StagingRepository(settings.data_dir)
        worker = AssessmentWorker(repository)
        app = create_app(settings, repository, worker)
        original_app, original_repository, original_worker = self.app, self.repository, self.worker
        try:
            self.app, self.repository, self.worker = app, repository, worker
            self.login()
            status, _, _ = self.request("/documents/synthetic", "POST")
            self.assertTrue(status.startswith("503"))
            self.assertTrue(settings.hosted_boundary_ready)
            self.assertFalse(settings.synthetic_intake_ready)
        finally:
            worker.stop()
            self.app, self.repository, self.worker = original_app, original_repository, original_worker

    def test_healthz_reports_hosted_synthetic_optin_alongside_existing_keys(self):
        status, _, body = self.request("/healthz")
        self.assertTrue(status.startswith("200"))
        payload = json.loads(body)
        self.assertIn("hosted_synthetic_optin", payload)
        self.assertFalse(payload["hosted_synthetic_optin"])
        for key in ("ok", "service", "environment", "synthetic_only", "login_ready",
                    "synthetic_intake_ready", "hosted_boundary_ready", "hosted_intake_enabled",
                    "configured_hosted_controls"):
            self.assertIn(key, payload)
        # Read-only toolchain visibility: every tool name maps to a version
        # string or null (absent). No behavior key hides in here.
        self.assertIn("toolchain", payload)
        self.assertEqual(set(payload["toolchain"]), {"qpdf", "tesseract", "verapdf"})
        for value in payload["toolchain"].values():
            self.assertTrue(value is None or isinstance(value, str))

    def test_hosted_synthetic_flag_requires_exact_true_and_leaves_development_unaffected(self):
        base = {"HUB_ENV": "staging", "HUB_STAGING_ACCESS_CODE": "code", "HUB_SESSION_SECRET": "s" * 48}
        # The implementation opens the route only on the byte-exact value "true".
        # Case variants, numeric/word aliases, and any surrounding whitespace or
        # trailing newline must all stay closed. Pin every near-miss adversary
        # probed empirically so a future "be lenient" change fails loudly here.
        for value in ("", "1", "TRUE", "True", "yes", " true ", "tRuE", "true ", " true",
                      "true\n", "true\t", "TRUE\t", "yes\n", "on", "enabled", "0", "false", "y"):
            settings = ServiceSettings.from_environ({**base, "HUB_ALLOW_HOSTED_SYNTHETIC": value})
            self.assertFalse(settings.allow_hosted_synthetic, value)
            self.assertFalse(settings.synthetic_intake_ready, value)
        unset = ServiceSettings.from_environ(base)
        self.assertFalse(unset.allow_hosted_synthetic)
        self.assertFalse(unset.synthetic_intake_ready)
        enabled = ServiceSettings.from_environ({**base, "HUB_ALLOW_HOSTED_SYNTHETIC": "true"})
        self.assertTrue(enabled.allow_hosted_synthetic)
        self.assertTrue(enabled.synthetic_intake_ready)
        self.assertFalse(enabled.health_payload()["hosted_intake_enabled"])
        # Development behaves as before, with or without the flag.
        dev = {"HUB_ENV": "development", "HUB_STAGING_ACCESS_CODE": "code", "HUB_SESSION_SECRET": "s" * 48}
        self.assertTrue(ServiceSettings.from_environ(dev).synthetic_intake_ready)
        self.assertTrue(ServiceSettings.from_environ({**dev, "HUB_ALLOW_HOSTED_SYNTHETIC": "true"}).synthetic_intake_ready)

    def test_hosted_staging_with_explicit_optin_allows_gated_audited_synthetic_intake(self):
        settings = ServiceSettings("staging", Path(self.temp.name) / "optin-hosted", "synthetic-only-code", "s" * 48, (), allow_hosted_synthetic=True)
        repository = StagingRepository(settings.data_dir)
        worker = AssessmentWorker(repository)
        app = create_app(settings, repository, worker)
        original_app, original_repository, original_worker = self.app, self.repository, self.worker
        try:
            self.app, self.repository, self.worker = app, repository, worker
            # Still access-code gated: unauthenticated intake is redirected to login.
            self.cookie = ""
            status, headers, _ = self.request("/documents/synthetic", "POST")
            self.assertTrue(status.startswith("303"))
            self.assertEqual(headers["Location"], "/login")
            self.login()
            status, headers, _ = self.request("/documents/synthetic", "POST")
            self.assertTrue(status.startswith("303"))
            document_id = headers["Location"].rsplit("/", 1)[-1]
            job = self.wait_for_result(document_id)
            self.assertEqual(job["state"], "succeeded")
            # Tenant-scoped record and audit trail, exactly as in development.
            self.assertIsNotNone(repository.document("coastline-staging", document_id))
            with repository._connect() as db:
                actions = [row["action"] for row in db.execute("SELECT action FROM audit_events WHERE tenant_id='coastline-staging'")]
            self.assertIn("synthetic_document_created", actions)
            # Everything else stays closed: no upload endpoint, hosted intake still off.
            status, _, _ = self.request("/documents/upload", "POST")
            self.assertTrue(status.startswith("404"))
            payload = json.loads(self.request("/healthz")[2])
            self.assertTrue(payload["hosted_synthetic_optin"])
            self.assertTrue(payload["synthetic_intake_ready"])
            self.assertFalse(payload["hosted_intake_enabled"])
        finally:
            worker.stop()
            self.app, self.repository, self.worker = original_app, original_repository, original_worker
            self.cookie = ""

    def test_document_page_auto_refreshes_while_running_and_stops_when_terminal(self):
        self.worker.stop()  # Keep the job queued so the pending page is observable.
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        document_id = headers["Location"].rsplit("/", 1)[-1]
        status, _, page = self.request(f"/documents/{document_id}")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b'http-equiv="refresh"', page)
        self.assertIn(b"checks again every five seconds", page)
        self.assertIn(b"role=status", page)
        self.assertIn(b"aria-live=polite", page)
        self.assertIn(b"Refresh now", page)
        self.assertNotIn(b"Fix the clearest issues", page)
        self.assertNotIn(b"location.reload", page)  # CSP blocks inline script; refresh must not rely on it.
        self.assertTrue(self.worker.run_once())
        job = self.repository.latest_job("coastline-staging", document_id)
        self.assertIn(job["state"], {"succeeded", "failed"})
        status, _, page = self.request(f"/documents/{document_id}")
        self.assertTrue(status.startswith("200"))
        self.assertNotIn(b'http-equiv="refresh"', page)

    def test_public_demo_is_unauthenticated_but_remains_bundled_fixture_only(self):
        settings = ServiceSettings(
            "staging", Path(self.temp.name) / "public-demo", "synthetic-only-code", "s" * 48,
            (), allow_hosted_synthetic=True, public_access=True,
        )
        repository = StagingRepository(settings.data_dir)
        worker = AssessmentWorker(repository)
        app = create_app(settings, repository, worker)
        original_app, original_repository, original_worker = self.app, self.repository, self.worker
        try:
            self.app, self.repository, self.worker = app, repository, worker
            self.cookie = ""
            status, _, page = self.request("/app")
            self.assertTrue(status.startswith("200"))
            self.assertIn(b"Synthetic demo only", page)
            self.assertIn(b'action="/documents/synthetic"', page)
            self.assertNotIn(b"multipart/form-data", page)
            self.assertNotIn(b"<input id=upload-file", page)
            self.assertNotIn(b'action="/documents/upload"', page)
            for path in ("/documents/upload", "/api/real-documents", "/api/upload-authorizations"):
                status, _, _ = self.request(path, "POST")
                self.assertTrue(status.startswith("404"), path)
            payload = json.loads(self.request("/healthz")[2])
            self.assertTrue(payload["synthetic_only"])
            self.assertFalse(payload["hosted_intake_enabled"])
        finally:
            worker.stop()
            self.app, self.repository, self.worker = original_app, original_repository, original_worker
            self.cookie = ""

    def test_human_confirmed_structure_recheck_uses_the_existing_tag_tree_remediator(self):
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        source_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(source_id)
        status, headers, _ = self.request(
            f"/documents/{source_id}/remediate/structure", "POST",
            {"confirmed": "yes", "roles": '{"0":"h1","1":"p"}', "order": "[0,1,2,3,4,5]"},
        )
        self.assertTrue(status.startswith("303"))
        child_id = headers["Location"].rsplit("/", 1)[-1]
        result = self.wait_for_result(child_id)["result"]
        verified = {item["rule_id"] for item in result["signals"] if item["lane"] == "verified_signal"}
        self.assertIn("PDF.STRUCTURE.SEMANTICS", verified)
        provenance = self.repository.remediations("coastline-staging", child_id)[0]["provenance"]
        self.assertEqual(provenance["actions"][0]["provenance"], "user_confirmed")
        self.assertTrue(provenance["verification"]["text_preserved"])

    @unittest.skipUnless(shutil.which("tesseract"), "tesseract binary is not installed")
    def test_synthetic_scan_uses_existing_ocr_remediator_and_rechecks_the_text_layer(self):
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST", {"fixture": "scan"})
        source_id = headers["Location"].rsplit("/", 1)[-1]
        before = self.wait_for_result(source_id)["result"]
        self.assertIn("PDF.TEXT_LAYER", {item["rule_id"] for item in before["signals"]})
        status, headers, _ = self.request(f"/documents/{source_id}/remediate/ocr", "POST", {"confirmed": "yes"})
        self.assertTrue(status.startswith("303"))
        child_id = headers["Location"].rsplit("/", 1)[-1]
        after = self.wait_for_result(child_id)["result"]
        self.assertNotIn("PDF.TEXT_LAYER", {item["rule_id"] for item in after["signals"] if item["lane"] != "not_assessed"})
        provenance = self.repository.remediations("coastline-staging", child_id)[0]["provenance"]
        self.assertEqual(provenance["actions"][0]["provenance"], "ocr_generated")
        # Once OCR exists in the lineage and text is extractable, the OCR
        # action is no longer offered on the rechecked copy.
        _, _, child_page = self.request(f"/documents/{child_id}")
        self.assertNotIn(b"Add a text layer from this scan", child_page)
        # A recheck that resolves signals without minting new verified strengths
        # must not claim "The accessibility signals are now verified" — the
        # banner falls back to an honest compare-the-lanes line.
        self.assertIn(b"Your improved copy is ready", child_page)
        self.assertNotIn(b"The accessibility signal", child_page)
        self.assertIn(b"Compare the lanes with the previous version", child_page)


    def _optin_app(self):
        settings = ServiceSettings("staging", Path(self.temp.name) / "adv", "synthetic-only-code", "s" * 48, (), allow_hosted_synthetic=True)
        repository = StagingRepository(settings.data_dir)
        worker = AssessmentWorker(repository)
        self.app, self.repository, self.worker = create_app(settings, repository, worker), repository, worker
        return settings, repository, worker

    def _raw_request(self, path, body, content_type, content_length=None, method="POST"):
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)
        response = b"".join(self.app({
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_LENGTH": content_length if content_length is not None else str(len(body)),
            "CONTENT_TYPE": content_type,
            "wsgi.input": io.BytesIO(body),
            "HTTP_COOKIE": self.cookie,
        }, start_response))
        return captured["status"], captured["headers"], response

    def test_no_body_driven_path_can_smuggle_arbitrary_bytes_into_a_record(self):
        """Adversary: the only bytes a record can hold are a bundled fixture, never body input."""
        self._optin_app()
        self.login()
        # A multipart 'file' upload to the fixture route is ignored; the created
        # record still holds the bundled fixture, not the smuggled PDF bytes.
        smuggled = b"%PDF-1.4 SMUGGLED_EVIL_BYTES"
        multipart = (
            b'------b\r\nContent-Disposition: form-data; name="file"; filename="evil.pdf"\r\n'
            b'Content-Type: application/pdf\r\n\r\n' + smuggled + b'\r\n------b--\r\n'
        )
        status, headers, _ = self._raw_request("/documents/synthetic", multipart, "multipart/form-data; boundary=----b")
        self.assertTrue(status.startswith("303"), status)
        smuggled_id = headers["Location"].rsplit("/", 1)[-1]
        stored = self.repository.document("coastline-staging", smuggled_id)
        self.assertEqual(stored["source_kind"], "bundled_synthetic_fixture")
        self.assertNotIn(smuggled, self.repository.document_bytes("coastline-staging", smuggled_id))
        # Body fields named like payloads are ignored too.
        from urllib.parse import urlencode
        status, headers, _ = self.request(
            "/documents/synthetic", "POST",
            {"fixture": "handout", "payload": "AAAA", "bytes": "BBBB", "content": "CCCC"},
        )
        injected = self.repository.document_bytes("coastline-staging", headers["Location"].rsplit("/", 1)[-1])
        for needle in (b"AAAA", b"BBBB", b"CCCC"):
            self.assertNotIn(needle, injected)
        # There is no upload endpoint, with or without the opt-in flag.
        status, _, _ = self.request("/documents/upload", "POST")
        self.assertTrue(status.startswith("404"))
        status, _, _ = self.request("/documents/x/remediate/upload", "POST", {"confirmed": "yes"})
        self.assertIn(status[:3], {"400", "404"})

    def test_malformed_or_hostile_content_length_does_not_crash_or_defeat_the_cap(self):
        """Adversary: a bogus Content-Length must fail closed, not raise or read unbounded."""
        self._optin_app()
        self.login()
        # Non-integer header: no crash, request still handled (fixture defaults to handout).
        status, _, _ = self._raw_request("/documents/synthetic", b"fixture=handout", "application/x-www-form-urlencoded", content_length="not-a-number")
        self.assertTrue(status.startswith("303"), status)
        # Negative header must be clamped, not passed to read() as read-everything.
        status, _, _ = self._raw_request("/documents/synthetic", b"fixture=handout", "application/x-www-form-urlencoded", content_length="-5")
        self.assertTrue(status.startswith("303"), status)

    def test_access_code_and_session_secret_never_appear_on_any_surface(self):
        secret_code = "SUPER-SECRET-ACCESS-CODE-XYZ"
        secret_session = "TOPSECRETSESSIONMATERIAL-0123456789-abcdefghij"
        settings = ServiceSettings("staging", Path(self.temp.name) / "hygiene", secret_code, secret_session, (), allow_hosted_synthetic=True)
        repository = StagingRepository(settings.data_dir)
        worker = AssessmentWorker(repository)
        self.app, self.repository, self.worker = create_app(settings, repository, worker), repository, worker
        surfaces = [self.request("/healthz")[2], self.request("/login")[2]]
        status, headers, _ = self.request("/login", "POST", {"code": secret_code})
        self.assertTrue(status.startswith("303"))
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        # The session cookie is an HMAC token, not the raw secret material.
        self.assertNotIn(secret_session, self.cookie)
        self.assertNotIn(secret_code, self.cookie)
        surfaces.append(self.request("/app")[2])
        _, headers, _ = self.request("/documents/synthetic", "POST")
        surfaces.append(self.request(headers["Location"])[2])
        for surface in surfaces:
            self.assertNotIn(secret_code.encode(), surface)
            self.assertNotIn(secret_session.encode(), surface)

    # ------------------------------------------------------------------
    # Demo-readiness behaviors: titles, lanes, logout, lineage naming,
    # guided structure form, Fix Lab gating, provenance, error surfaces.
    # ------------------------------------------------------------------

    def test_signal_titles_come_from_rule_knowledge_never_mangled_ids(self):
        from service.worker import normalize_report
        report = {
            "findings": [
                {"category": "deterministic_defect", "rule_id": "PDF.METADATA.TITLE", "evidence": "e", "next_action": "n", "location": "l"},
                {"category": "tool_failure_or_unsupported", "rule_id": "PDF.VERAPDF.UNAVAILABLE", "evidence": "e", "next_action": "n", "location": "l"},
                {"category": "deterministic_defect", "rule_id": "PDF.SOME.NEW_RULE", "evidence": "e", "next_action": "n", "location": "l"},
            ],
            "strengths": [{"rule_id": "PDF.IMAGES.ALT_MISSING", "evidence": "e"}],
            "not_assessed": [],
        }
        result = normalize_report(report)
        titles = {signal["title"] for signal in result["signals"]}
        self.assertIn("Document title", titles)  # educator title from rule_knowledge.json
        self.assertNotIn("Metadata.Title", titles)
        self.assertNotIn("Veraunavailable", json.dumps(result))
        # Unknown rule ids humanize (no dots, no mangling), never render raw.
        self.assertIn("Some New Rule", titles)
        # A verified strength is not named after the defect it disproves.
        strength = next(s for s in result["signals"] if s["lane"] == "verified_signal")
        self.assertEqual(strength["title"], "Figure descriptions in place")

    def test_tool_availability_moves_to_completeness_and_lanes_are_grouped(self):
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        document_id = headers["Location"].rsplit("/", 1)[-1]
        result = self.wait_for_result(document_id)["result"]
        rule_ids = {signal["rule_id"] for signal in result["signals"]}
        # Toolchain gaps never render as lane cards; they live in completeness.
        self.assertNotIn("PDF.INTAKE.QPDF_UNAVAILABLE", rule_ids)
        self.assertNotIn("PDF.VERAPDF.UNAVAILABLE", rule_ids)
        for note in result.get("completeness", []):
            self.assertNotIn("Install", note)  # plain language, not ops instructions
        # Signals are grouped in canonical lane order, defects first.
        order = ["needs_attention", "review_recommended", "verified_signal", "not_assessed"]
        ranks = [order.index(signal["lane"]) for signal in result["signals"]]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(result["signals"][0]["lane"], "needs_attention")
        # The report's full not_assessed list is carried, including color-only meaning.
        titles = {signal["title"] for signal in result["signals"] if signal["lane"] == "not_assessed"}
        self.assertIn("Color-only meaning", titles)
        # The page shows a collapsed completeness strip after the lane cards.
        _, _, page = self.request(f"/documents/{document_id}")
        if result.get("completeness"):
            self.assertIn(b"Review completeness", page)
            self.assertLess(page.index(b"Needs attention"), page.index(b"Review completeness"))
        self.assertNotIn(b"Veraunavailable", page)

    def test_unreadable_documents_land_in_needs_attention_with_plain_copy(self):
        from service.worker import normalize_report
        report = {
            "findings": [{
                "category": "blocking_technical_failure", "rule_id": "PDF.INTAKE.ENCRYPTED",
                "evidence": "qpdf reported encrypted content", "next_action": "Do not process this file in the spike.",
                "location": "document",
            }],
            "strengths": [], "not_assessed": [],
        }
        result = normalize_report(report)
        signal = result["signals"][0]
        self.assertEqual(signal["lane"], "needs_attention")
        self.assertNotIn("spike", (signal["next_action"] or "").lower())
        self.assertIn("password-protected", signal["evidence"])

    def test_logout_clears_session_and_lands_on_login_with_note(self):
        self.login()
        _, _, workspace = self.request("/app")
        self.assertIn(b"Sign out", workspace)
        self.assertIn(b'action="/logout"', workspace)
        status, headers, _ = self.request("/logout", "POST")
        self.assertTrue(status.startswith("303"))
        self.assertEqual(headers["Location"], "/login?signed-out=1")
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        # The cleared cookie no longer opens the workspace.
        cleared = headers["Set-Cookie"].split(";", 1)[0]
        status, headers, _ = self.request("/app", cookie=cleared)
        self.assertTrue(status.startswith("303"))
        self.assertEqual(headers["Location"], "/login")
        status, _, page = self.request("/login?signed-out=1", cookie=cleared)
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"You are signed out.", page)
        self.cookie = ""

    def test_404_page_links_back_to_the_workspace(self):
        self.login()
        status, _, page = self.request("/no-such-page")
        self.assertTrue(status.startswith("404"))
        self.assertIn(b'href="/app"', page)
        status, _, page = self.request("/documents/does-not-exist")
        self.assertTrue(status.startswith("404"))
        self.assertIn(b'href="/app"', page)

    def test_lineage_naming_uses_versions_and_workspace_shows_one_row(self):
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        source_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(source_id)
        _, headers, _ = self.request(
            f"/documents/{source_id}/remediate/metadata", "POST",
            {"title": "Week 3 Course Handout", "language": "en-US"},
        )
        v2_id = headers["Location"].rsplit("/", 1)[-1]
        v2 = self.repository.document("coastline-staging", v2_id)
        self.assertEqual(v2["filename"], "coastline-synthetic-course-handout.v2.pdf")
        self.wait_for_result(v2_id)
        _, headers, _ = self.request(
            f"/documents/{v2_id}/remediate/metadata", "POST",
            {"title": "Week 3 Course Handout", "language": "en-US"},
        )
        v3_id = headers["Location"].rsplit("/", 1)[-1]
        v3 = self.repository.document("coastline-staging", v3_id)
        self.assertEqual(v3["filename"], "coastline-synthetic-course-handout.v3.pdf")
        self.assertNotIn("rechecked", v3["filename"])
        self.wait_for_result(v3_id)
        _, _, workspace = self.request("/app")
        # One row per lineage: the base name appears once, with a version tag.
        self.assertEqual(workspace.count(b"<strong>coastline-synthetic-course-handout.pdf</strong>"), 1)
        self.assertIn(b">v3<", workspace)
        self.assertIn(b"3 versions", workspace)
        self.assertNotIn(b"rechecked", workspace)

    def test_guided_structure_form_replaces_raw_json_and_submits_roles(self):
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        source_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(source_id)
        _, _, page = self.request(f"/documents/{source_id}")
        # Per-block rows with labeled selects; no raw JSON textareas.
        self.assertIn(b"name=role_0", page)
        self.assertIn(b"for=role_0", page)
        self.assertIn(b"name=block_count", page)
        self.assertNotIn(b"Confirmed roles (JSON)", page)
        self.assertNotIn(b"<textarea", page)
        # The first block defaults to a heading, later blocks to paragraphs.
        self.assertRegex(page, rb"role_0[^/]*?<option value=h1 selected")
        status, headers, _ = self.request(
            f"/documents/{source_id}/remediate/structure", "POST",
            {"confirmed": "yes", "block_count": "6", "role_0": "h1", "role_1": "p",
             "role_2": "p", "role_3": "p", "role_4": "p", "role_5": "p"},
        )
        self.assertTrue(status.startswith("303"), status)
        child_id = headers["Location"].rsplit("/", 1)[-1]
        result = self.wait_for_result(child_id)["result"]
        verified = {item["rule_id"] for item in result["signals"] if item["lane"] == "verified_signal"}
        self.assertIn("PDF.STRUCTURE.SEMANTICS", verified)

    def test_fix_lab_is_gated_until_the_assessment_is_terminal(self):
        self.worker.stop()  # Keep the job queued so the pending page is observable.
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        document_id = headers["Location"].rsplit("/", 1)[-1]
        _, _, page = self.request(f"/documents/{document_id}")
        self.assertIn(b"Review first", page)
        self.assertNotIn(b"Apply and recheck", page)
        self.assertNotIn(b"Build tags and recheck", page)
        self.assertTrue(self.worker.run_once())
        _, _, page = self.request(f"/documents/{document_id}")
        self.assertNotIn(b"Review first", page)
        self.assertIn(b"Apply and recheck", page)

    def test_provenance_panel_shows_kind_time_and_short_hashes(self):
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        source_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(source_id)
        _, headers, _ = self.request(
            f"/documents/{source_id}/remediate/metadata", "POST",
            {"title": "Week 3 Course Handout", "language": "en-US"},
        )
        child_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(child_id)
        provenance = self.repository.remediations("coastline-staging", child_id)[0]["provenance"]
        source_hash = provenance["source_sha256"].removeprefix("sha256:")[:10]
        result_hash = provenance["remediated_sha256"].removeprefix("sha256:")[:10]
        _, _, page = self.request(f"/documents/{child_id}")
        text = page.decode()
        self.assertIn("Title &amp; language", text)
        self.assertIn("<span class=tag>metadata</span>", text)  # raw kind stays visible
        self.assertIn(f"{source_hash}… → {result_hash}…", text)

    def test_error_surfaces_never_show_raw_python_exception_text(self):
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        source_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(source_id)
        # Legacy JSON field with malformed JSON: friendly copy, no parser text.
        status, _, page = self.request(
            f"/documents/{source_id}/remediate/structure", "POST",
            {"confirmed": "yes", "roles": "{not json", "order": "[0]"},
        )
        self.assertTrue(status.startswith("400"))
        self.assertNotIn(b"Expecting property name", page)
        self.assertNotIn(b"JSONDecodeError", page)
        self.assertNotIn(b"Traceback", page)
        self.assertIn(b"could not be read", page)
        # Guided path with a missing block count: friendly copy as well.
        status, _, page = self.request(
            f"/documents/{source_id}/remediate/structure", "POST",
            {"confirmed": "yes", "block_count": "wat"},
        )
        self.assertTrue(status.startswith("400"))
        self.assertIn(b"structure form was incomplete", page)

    def test_favicon_served_for_both_paths_no_console_404(self):
        for path in ("/favicon.ico", "/assets/favicon.svg"):
            status, headers, payload = self.request(path)
            self.assertTrue(status.startswith("200"), path)
            self.assertEqual(headers["Content-Type"], "image/svg+xml")
            self.assertIn(b"<svg", payload)
        # The shell references the icon so browsers never guess at /favicon.ico.
        self.assertIn(b'rel="icon" href="/assets/favicon.svg"', self.request("/login")[2])

    def test_header_uses_coastline_navy_with_sky_border(self):
        _, _, page = self.request("/login")
        self.assertIn(b"header { background:var(--navy)", page)
        self.assertIn(b"border-bottom:3px solid var(--sky)", page)

    def test_port_contract_honors_port_then_hub_port_then_default(self):
        from service.__main__ import resolve_port
        self.assertEqual(resolve_port({}), 8787)
        self.assertEqual(resolve_port({"HUB_PORT": "8813"}), 8813)
        self.assertEqual(resolve_port({"PORT": "9001", "HUB_PORT": "8813"}), 9001)
        self.assertEqual(resolve_port({"PORT": "  9002  "}), 9002)
        with self.assertRaises(SystemExit):
            resolve_port({"PORT": "not-a-port"})

    # ------------------------------------------------------------------
    # Teacher happy path: stub SSO, dev-only upload, sponsored loader,
    # summary chips, one-click fixes, produced (sealed) download, and the
    # staging-mode boundary regression.
    # ------------------------------------------------------------------

    def _multipart(self, filename, payload, field="file", boundary="hubtestboundary"):
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
        return body, f"multipart/form-data; boundary={boundary}"

    def _upload(self, filename, payload):
        body, content_type = self._multipart(filename, payload)
        return self._raw_request("/documents/upload", body, content_type)

    def _controlled_staging_app(self):
        """Hosted staging with EVERY flag and control present — the strongest adversary."""
        controls = (
            "HUB_PRIVATE_OBJECT_STORAGE", "HUB_MALWARE_SCAN_GATE", "HUB_WORKER_ISOLATION_ATTESTATION",
            "HUB_TENANT_AUTH_ISSUER", "HUB_LIFECYCLE_POLICY_ID", "HUB_AUDIT_SINK",
        )
        settings = ServiceSettings(
            "staging", Path(self.temp.name) / "boundary", "synthetic-only-code", "s" * 48,
            controls, allow_hosted_synthetic=True,
        )
        repository = StagingRepository(settings.data_dir)
        worker = AssessmentWorker(repository)
        self.app, self.repository, self.worker = create_app(settings, repository, worker), repository, worker
        return settings

    def test_dev_login_shows_stub_sso_above_access_code_and_signs_in_demo_educator(self):
        status, _, page = self.request("/login")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Sign in with your Coastline Microsoft account", page)
        self.assertIn("Demo sign-in — no Microsoft account is contacted.".encode(), page)
        # The stub button renders ABOVE the access-code form.
        self.assertLess(page.index(b"Coastline Microsoft account"), page.index(b"Access code"))
        self.assertIn(b'action="/login/sso"', page)
        status, headers, _ = self.request("/login/sso", "POST")
        self.assertTrue(status.startswith("303"))
        self.assertEqual(headers["Location"], "/app")
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, _, workspace = self.request("/app")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Jordan Rivera, Faculty", workspace)
        self.assertIn(b"Signed in", workspace)
        self.cookie = ""

    def test_hosted_login_keeps_access_code_only_and_sso_route_404s(self):
        self._controlled_staging_app()
        status, _, page = self.request("/login")
        self.assertTrue(status.startswith("200"))
        self.assertNotIn(b"Microsoft", page)
        self.assertNotIn(b'action="/login/sso"', page)
        self.assertIn(b"Access code", page)
        status, _, _ = self.request("/login/sso", "POST")
        self.assertTrue(status.startswith("404"))

    def test_dev_upload_stores_educator_upload_and_runs_the_same_review(self):
        from service.fixtures import synthetic_handout_pdf
        self.login_sso()
        pdf = synthetic_handout_pdf()
        status, headers, _ = self._upload("My Course – Week 5_notes.pdf", pdf)
        self.assertTrue(status.startswith("303"), status)
        document_id = headers["Location"].rsplit("/", 1)[-1]
        stored = self.repository.document("coastline-staging", document_id)
        self.assertEqual(stored["source_kind"], "educator_upload")
        self.assertTrue(stored["filename"].endswith(".pdf"))
        self.assertNotIn("/", stored["filename"])
        self.assertEqual(self.repository.document_bytes("coastline-staging", document_id), pdf)
        job = self.wait_for_result(document_id)
        self.assertEqual(job["state"], "succeeded")
        # The original upload is never modified in place.
        self.assertEqual(self.repository.document_bytes("coastline-staging", document_id), pdf)
        with self.repository._connect() as db:
            actions = [row["action"] for row in db.execute("SELECT action FROM audit_events")]
        self.assertIn("educator_document_uploaded", actions)
        # The classic detail page — with the full Fix Lab — stays reachable
        # for the educator through the Advanced tools link.
        _, _, page = self.request(f"/documents/{document_id}?view=advanced")
        self.assertIn(b"Your upload", page)
        self.assertIn(b"Signals and next actions", page)

    def test_dev_access_code_session_keeps_the_synthetic_only_workspace(self):
        # The smoke script signs in with the access code against a dev
        # instance and must find the classic sample workspace: no file input,
        # no upload route. Only the demo educator (stub SSO) session uploads.
        from service.fixtures import synthetic_handout_pdf
        self.login()
        status, _, workspace = self.request("/app")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Start a sample review", workspace)
        self.assertNotIn(b"Upload your course material", workspace)
        self.assertNotIn(b"type=file", workspace)
        self.assertNotIn(b'action="/documents/upload"', workspace)
        self.assertIn(b"Real-document upload opens with the demo educator sign-in.", workspace)
        before = len(self.repository.list_documents("coastline-staging"))
        status, _, _ = self._upload("real-course-material.pdf", synthetic_handout_pdf())
        self.assertTrue(status.startswith("404"), status)
        self.assertEqual(len(self.repository.list_documents("coastline-staging")), before)

    def test_upload_rejects_non_pdf_oversized_and_missing_file(self):
        self.login_sso()
        before = len(self.repository.list_documents("coastline-staging"))
        # Wrong extension fails closed with friendly copy.
        status, _, page = self._upload("notes.txt", b"%PDF-1.4 not really")
        self.assertTrue(status.startswith("400"), status)
        self.assertIn(b"Choose a PDF file.", page)
        # PDF extension but non-PDF bytes.
        status, _, page = self._upload("notes.pdf", b"MZ this is an executable")
        self.assertTrue(status.startswith("400"))
        self.assertIn(b"does not look like a PDF", page)
        # A hostile Content-Length over the cap is refused before reading.
        status, _, page = self._raw_request(
            "/documents/upload", b"", "multipart/form-data; boundary=x",
            content_length=str(80 * 1024 * 1024),
        )
        self.assertTrue(status.startswith("413"), status)
        self.assertIn(b"50 MB", page)
        # No file part at all.
        status, _, page = self._raw_request(
            "/documents/upload", b"fixture=handout", "application/x-www-form-urlencoded")
        self.assertTrue(status.startswith("400"))
        self.assertIn(b"Choose a PDF file", page)
        self.assertEqual(len(self.repository.list_documents("coastline-staging")), before)

    def test_sponsored_card_shows_while_running_and_never_after_terminal(self):
        self.worker.stop()  # Keep the job queued so the pending page is observable.
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        document_id = headers["Location"].rsplit("/", 1)[-1]
        status, _, page = self.request(f"/documents/{document_id}")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b">Sponsored</span>", page)
        self.assertIn(b'aria-label="Sponsored message"', page)
        self.assertIn(b'class="panel sponsor-card"', page)
        # Server-rendered and first-party only: no scripts, no external assets.
        self.assertNotIn(b"<script", page)
        self.assertNotIn(b"https://", page)
        self.assertIn(b"never delay your results", page)
        # The refresh cadence is untouched by the ad.
        self.assertIn(b'http-equiv="refresh"', page)
        ads = json.loads(Path("partner_ads.json").read_text(encoding="utf-8"))
        self.assertTrue(any(partner["name"].encode() in page for partner in ads["partners"]))
        self.assertIn(ads["disclosure"].encode(), page)
        # The moment the job is terminal, results render with no sponsor card.
        self.assertTrue(self.worker.run_once())
        _, _, page = self.request(f"/documents/{document_id}")
        self.assertNotIn(b'class="panel sponsor-card"', page)
        self.assertNotIn(b'aria-label="Sponsored message"', page)
        self.assertNotIn(b">Sponsored</span>", page)
        self.assertIn(b"Signals and next actions", page)

    def test_missing_or_broken_partner_ads_file_never_breaks_the_review_flow(self):
        import service.app as app_module
        self.worker.stop()
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        document_id = headers["Location"].rsplit("/", 1)[-1]
        original = app_module.PARTNER_ADS_PATH
        try:
            app_module.PARTNER_ADS_PATH = Path(self.temp.name) / "no-such-ads.json"
            status, _, page = self.request(f"/documents/{document_id}")
            self.assertTrue(status.startswith("200"))
            self.assertNotIn(b'class="panel sponsor-card"', page)
            self.assertIn(b"Looking for useful accessibility signals", page)
            broken = Path(self.temp.name) / "broken-ads.json"
            broken.write_text("{not json", encoding="utf-8")
            app_module.PARTNER_ADS_PATH = broken
            status, _, page = self.request(f"/documents/{document_id}")
            self.assertTrue(status.startswith("200"))
            self.assertNotIn(b'class="panel sponsor-card"', page)
        finally:
            app_module.PARTNER_ADS_PATH = original

    def test_summary_chip_row_math_matches_the_lane_counts(self):
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        document_id = headers["Location"].rsplit("/", 1)[-1]
        result = self.wait_for_result(document_id)["result"]
        counts = {"needs_attention": 0, "review_recommended": 0, "verified_signal": 0, "not_assessed": 0}
        for signal in result["signals"]:
            counts[signal["lane"]] += 1
        _, _, page = self.request(f"/documents/{document_id}")
        self.assertIn(b"summary-chips", page)
        phrases = {
            "needs_attention": ("needs attention", "need attention"),
            "review_recommended": ("to review", "to review"),
            "verified_signal": ("verified", "verified"),
            "not_assessed": ("not assessed", "not assessed"),
        }
        for lane, count in counts.items():
            singular, plural = phrases[lane]
            expected = f"{count} {singular if count == 1 else plural}".encode()
            self.assertIn(expected, page, lane)
        # The chip row sits above the lane cards.
        self.assertLess(page.index(b"summary-chips"), page.index(b"Signals and next actions"))

    def test_one_click_apply_suggested_fixes_batches_the_metadata_remediation(self):
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        document_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(document_id)
        _, _, page = self.request(f"/documents/{document_id}")
        self.assertIn(b"Apply suggested fixes and recheck", page)
        self.assertIn(b'<input type=hidden name=title value="Week 3 Course Handout">', page)
        self.assertIn(b'<input type=hidden name=language value="en-US">', page)
        status, headers, _ = self.request(
            f"/documents/{document_id}/remediate/metadata", "POST",
            {"title": "Week 3 Course Handout", "language": "en-US"},
        )
        self.assertTrue(status.startswith("303"))
        child_id = headers["Location"].rsplit("/", 1)[-1]
        after = self.wait_for_result(child_id)["result"]
        verified = {item["rule_id"] for item in after["signals"] if item["lane"] == "verified_signal"}
        self.assertIn("PDF.METADATA.TITLE", verified)
        self.assertIn("PDF.METADATA.LANGUAGE", verified)
        # The recheck resolved the metadata defects, so the one-click offer is gone
        # on the rechecked version (it is a recheck page, not a first review).
        _, _, child_page = self.request(f"/documents/{child_id}")
        self.assertNotIn(b"Apply suggested fixes and recheck", child_page)

    def test_produce_seals_a_download_with_one_added_page_and_records_provenance(self):
        from pypdf import PdfReader
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        source_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(source_id)
        _, headers, _ = self.request(
            f"/documents/{source_id}/remediate/metadata", "POST",
            {"title": "Week 3 Course Handout", "language": "en-US"},
        )
        child_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(child_id)
        _, _, page = self.request(f"/documents/{child_id}")
        self.assertIn(b"Produce your document", page)
        self.assertIn(b"A review record, not a certification.", page)
        self.assertIn(b"seal-badge", page)
        self.assertIn(b"Reviewed &amp; improved", page)
        self.assertIn(f'href="/documents/{child_id}/produced"'.encode(), page)

        source_bytes = self.repository.document_bytes("coastline-staging", child_id)
        status, headers, sealed = self.request(f"/documents/{child_id}/produced")
        self.assertTrue(status.startswith("200"), status)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn('filename="coastline-synthetic-course-handout.sealed.pdf"', headers["Content-Disposition"])
        self.assertTrue(sealed.startswith(b"%PDF"))
        source_reader = PdfReader(io.BytesIO(source_bytes))
        sealed_reader = PdfReader(io.BytesIO(sealed))
        self.assertEqual(len(sealed_reader.pages), len(source_reader.pages) + 1)
        # Prior pages keep byte-identical extracted text (anti-vandal mirror).
        for index, source_page in enumerate(source_reader.pages):
            self.assertEqual(sealed_reader.pages[index].extract_text() or "",
                             source_page.extract_text() or "")
        final_text = sealed_reader.pages[-1].extract_text() or ""
        self.assertIn("Reviewed & improved with Coastline College Accessibility Hub", final_text)
        self.assertIn("A review record, not a certification.", final_text)
        # Provenance kind "seal" recorded once via the remediation machinery.
        seals = [row for row in self.repository.remediations("coastline-staging", child_id) if row["kind"] == "seal"]
        self.assertEqual(len(seals), 1)
        provenance = seals[0]["provenance"]
        self.assertEqual(provenance["kind"], "seal")
        self.assertTrue(provenance["mutates_document"])
        self.assertTrue(provenance["source_sha256"].startswith("sha256:"))
        self.assertTrue(provenance["result_sha256"].startswith("sha256:"))
        # The document record itself is untouched: producing applies nothing new.
        self.assertEqual(self.repository.document_bytes("coastline-staging", child_id), source_bytes)
        # Repeated downloads do not duplicate the provenance row.
        status, _, again = self.request(f"/documents/{child_id}/produced")
        self.assertTrue(status.startswith("200"))
        self.assertTrue(again.startswith(b"%PDF"))
        seals = [row for row in self.repository.remediations("coastline-staging", child_id) if row["kind"] == "seal"]
        self.assertEqual(len(seals), 1)

    def test_produce_refuses_direct_url_on_first_review_with_needs_attention(self):
        # The route mirrors the produce-card eligibility: a first review that
        # still has needs-attention signals cannot be produced by URL alone.
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        source_id = headers["Location"].rsplit("/", 1)[-1]
        result = self.wait_for_result(source_id)["result"]
        self.assertTrue(any(s["lane"] == "needs_attention" for s in result["signals"]))
        _, _, page = self.request(f"/documents/{source_id}")
        self.assertNotIn(b"Produce your document", page)
        status, _, body = self.request(f"/documents/{source_id}/produced")
        self.assertTrue(status.startswith("409"), status)
        self.assertFalse(body.startswith(b"%PDF"))
        self.assertIn(b"not ready to produce", body.lower())
        seals = [row for row in self.repository.remediations("coastline-staging", source_id) if row["kind"] == "seal"]
        self.assertEqual(seals, [])

    def test_produce_fails_soft_when_the_seal_module_is_unavailable(self):
        import sys
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        source_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(source_id)
        _, headers, _ = self.request(
            f"/documents/{source_id}/remediate/metadata", "POST",
            {"title": "Week 3 Course Handout", "language": "en-US"},
        )
        child_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(child_id)
        saved = sys.modules.pop("tina.seal", None)
        sys.modules["tina.seal"] = None  # forces ImportError on the lazy import
        try:
            status, _, page = self.request(f"/documents/{child_id}")
            self.assertTrue(status.startswith("200"))
            self.assertIn(b"Producing is not available yet", page)
            self.assertNotIn(b"/produced", page)
            status, _, page = self.request(f"/documents/{child_id}/produced")
            self.assertTrue(status.startswith("503"))
            self.assertIn(b"review itself is unaffected", page)
        finally:
            del sys.modules["tina.seal"]
            if saved is not None:
                sys.modules["tina.seal"] = saved

    def test_staging_mode_still_has_no_upload_sso_or_produced_route_regression(self):
        """SECURITY BOUNDARY: hosted staging refuses uploads exactly as before,
        no matter which flags or control references are present."""
        from service.fixtures import synthetic_handout_pdf
        settings = self._controlled_staging_app()
        self.assertTrue(settings.hosted_boundary_ready)
        self.assertTrue(settings.synthetic_intake_ready)
        self.login()
        # Workspace: samples only, refusal note intact, no upload form.
        status, _, workspace = self.request("/app")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Real-document upload is not available in this environment.", workspace)
        self.assertIn(b"Real-document upload is unavailable.", workspace)
        self.assertNotIn(b"<input id=upload-file", workspace)
        self.assertNotIn(b'action="/documents/upload"', workspace)
        self.assertNotIn(b"Upload your course material", workspace)
        # The upload route does not exist: a real PDF multipart POST 404s and
        # stores nothing.
        before = len(self.repository.list_documents("coastline-staging"))
        status, _, _ = self._upload("real-course-material.pdf", synthetic_handout_pdf())
        self.assertTrue(status.startswith("404"), status)
        self.assertEqual(len(self.repository.list_documents("coastline-staging")), before)
        # Stub SSO does not exist either.
        status, _, _ = self.request("/login/sso", "POST")
        self.assertTrue(status.startswith("404"))
        # Synthetic flow still works, but the produced route does not exist.
        _, headers, _ = self.request("/documents/synthetic", "POST")
        document_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_result(document_id)
        _, _, page = self.request(f"/documents/{document_id}")
        self.assertNotIn(b"Produce your document", page)
        status, _, _ = self.request(f"/documents/{document_id}/produced")
        self.assertTrue(status.startswith("404"), status)
        # Health payload still reports hosted intake closed.
        payload = json.loads(self.request("/healthz")[2])
        self.assertFalse(payload["hosted_intake_enabled"])
        self.assertTrue(payload["synthetic_only"])
        self.cookie = ""

    # ------------------------------------------------------------------
    # The three-step educator flow: drop page, one-pass improving pipeline,
    # ready page with insight cards, and the educator copy scrub.
    # ------------------------------------------------------------------

    def wait_for_pipeline(self, document_id, deadline=12.0):
        """Wait until the pipeline is fully terminal: the document's job AND,
        if an improved copy was created, that copy's job too. Returns the
        final document id (the improved copy when one exists)."""
        started = time.monotonic()
        while time.monotonic() - started < deadline:
            job = self.repository.latest_job("coastline-staging", document_id)
            if job and job["state"] in {"succeeded", "failed"}:
                child = self.repository.latest_child("coastline-staging", document_id)
                if child is None:
                    return document_id
                child_job = self.repository.latest_job("coastline-staging", child["id"])
                if child_job and child_job["state"] in {"succeeded", "failed"}:
                    return child["id"]
            time.sleep(0.05)
        self.fail("pipeline did not reach a terminal state")

    def assert_scrubbed(self, page, context):
        text = visible_text(page)
        for word in SCRUBBED_WORDS:
            self.assertNotIn(word, text, f"'{word}' is visible on the {context} page")

    def assert_csp_scripts(self, page):
        """CSP compliance: same-origin scripts only, never inline code. Every
        <script> tag on an educator page is the first-party journey file with
        an empty body."""
        tags = re.findall(rb"<script([^>]*)>(.*?)</script>", page, re.S)
        self.assertTrue(tags, "expected the journey script tag on this page")
        for attributes, body in tags:
            self.assertIn(b'src="/assets/journey.js"', attributes)
            self.assertEqual(body.strip(), b"", "inline script code is forbidden by the CSP")

    def test_educator_lands_on_a_single_drop_page_after_sso(self):
        self.login_sso()
        status, _, page = self.request("/app")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Make your course material ready for students.", page)
        self.assertIn(b"Transform my document", page)
        self.assertIn(b"type=file", page)
        self.assertIn(b'accept="application/pdf,.pdf"', page)
        self.assertIn(b'enctype="multipart/form-data"', page)
        self.assertIn(b'action="/documents/upload"', page)
        # A tiny footer link to the sample, wired to the existing fixture route.
        self.assertIn(b"No file handy?", page)
        self.assertIn(b"Try a sample document.", page)
        self.assertIn(b'action="/documents/synthetic"', page)
        # No multistep ceremony: no rail, no document-records table, no lanes.
        self.assertNotIn(b'aria-current="step"', page)
        self.assertNotIn(b"Document records", page)
        self.assertNotIn(b"Start a sample review", page)
        # No recent list until something exists.
        self.assertNotIn(b"id=recent-heading", page)
        self.assert_scrubbed(page, "drop")
        self.cookie = ""

    def test_educator_drop_page_lists_recent_documents_quietly(self):
        from service.fixtures import synthetic_handout_pdf
        self.login_sso()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        source_id = headers["Location"].rsplit("/", 1)[-1]
        self.wait_for_pipeline(source_id)
        _, _, page = self.request("/app")
        self.assertIn(b"Recent", page)
        self.assertIn(b"id=recent-heading", page)
        # The fixture never leaks its internal name to a teacher.
        self.assertIn(b"Sample course handout", page)
        self.assert_scrubbed(page, "drop")
        self.cookie = ""

    def test_educator_processing_page_shows_stages_and_sponsor_and_refresh(self):
        from service.fixtures import synthetic_handout_pdf
        self.worker.stop()  # Keep the job queued so the processing page is observable.
        self.login_sso()
        status, headers, _ = self._upload("week 5-handout.pdf", synthetic_handout_pdf())
        self.assertTrue(status.startswith("303"), status)
        document_id = headers["Location"].rsplit("/", 1)[-1]
        status, _, page = self.request(f"/documents/{document_id}")
        self.assertTrue(status.startswith("200"))
        self.assertIn("Reading your document…".encode(), page)
        self.assertIn(b"Applying safe improvements", page)
        self.assertIn(b"Verifying the new copy", page)
        # The sponsored card runs during processing, never gating results.
        self.assertIn(b">Sponsored</span>", page)
        self.assertIn(b"never delay your results", page)
        # Meta-refresh cadence unchanged as the no-JS fallback (inside
        # noscript so the journey script can drive without reload races), and
        # the only script is the same-origin journey file — no inline code.
        self.assertIn(b'<noscript><meta http-equiv="refresh" content="5"></noscript>', page)
        self.assert_csp_scripts(page)
        self.assert_scrubbed(page, "processing")
        # First worker pass: assess + auto-improve; the parent page now moves
        # the teacher forward to the improved copy without any click.
        self.assertTrue(self.worker.run_once())
        status, headers, _ = self.request(f"/documents/{document_id}")
        self.assertTrue(status.startswith("303"), status)
        child_id = headers["Location"].rsplit("/", 1)[-1]
        self.assertNotEqual(child_id, document_id)
        # The improved copy is still verifying: stage 3 active, earlier done.
        status, _, page = self.request(f"/documents/{child_id}")
        self.assertTrue(status.startswith("200"))
        self.assertIn("Verifying the new copy…".encode(), page)
        self.assertIn(b'class="done"', page)
        self.assertIn(b">Sponsored</span>", page)
        self.assert_scrubbed(page, "processing (verify stage)")
        # Second worker pass: re-assessment of the copy → terminal, no sponsor.
        self.assertTrue(self.worker.run_once())
        status, _, page = self.request(f"/documents/{child_id}")
        self.assertTrue(status.startswith("200"))
        self.assertNotIn(b'http-equiv="refresh"', page)
        self.assertIn(b"Your document is ready.", page)
        self.assertNotIn(b">Sponsored</span>", page)
        self.cookie = ""

    def test_educator_pipeline_auto_fixes_metadata_with_provenance_and_reassessment(self):
        from service.fixtures import synthetic_handout_pdf
        self.login_sso()
        pdf = synthetic_handout_pdf()
        _, headers, _ = self._upload("week 5-handout.pdf", pdf)
        document_id = headers["Location"].rsplit("/", 1)[-1]
        final_id = self.wait_for_pipeline(document_id)
        self.assertNotEqual(final_id, document_id)
        # Provenance chain: the metadata remediation is recorded on the copy
        # exactly as the manual path records it.
        rows = self.repository.remediations("coastline-staging", final_id)
        self.assertEqual([row["kind"] for row in rows if row["kind"] != "seal"], ["metadata"])
        provenance = rows[0]["provenance"]
        self.assertTrue(provenance["mutates_document"])
        applied = {action["rule_id"]: action for action in provenance["actions"]}
        self.assertEqual(set(applied), {"PDF.METADATA.TITLE", "PDF.METADATA.LANGUAGE"})
        # Prettified filename: extension stripped, dashes/underscores to
        # spaces, title-case.
        self.assertEqual(applied["PDF.METADATA.TITLE"]["value"], "Week 5 Handout")
        self.assertEqual(applied["PDF.METADATA.LANGUAGE"]["value"], "en-US")
        # The re-assessment ran and verified both fixes.
        final_job = self.repository.latest_job("coastline-staging", final_id)
        self.assertEqual(final_job["state"], "succeeded")
        verified = {s["rule_id"] for s in final_job["result"]["signals"] if s["lane"] == "verified_signal"}
        self.assertIn("PDF.METADATA.TITLE", verified)
        self.assertIn("PDF.METADATA.LANGUAGE", verified)
        # Nothing else was changed silently: exactly one derived copy, one
        # remediation, and the upload's own bytes are untouched.
        self.assertEqual(self.repository.document_bytes("coastline-staging", document_id), pdf)
        self.assertIsNone(self.repository.latest_child("coastline-staging", final_id))
        # The audit trail names the automated actor.
        with self.repository._connect() as db:
            row = db.execute("SELECT actor FROM audit_events WHERE action='remediation_applied' ORDER BY created_at DESC").fetchone()
        self.assertEqual(row["actor"], "automated-pipeline")
        self.cookie = ""

    def test_educator_ready_page_has_download_seal_and_insight_cards(self):
        from service.fixtures import synthetic_handout_pdf
        self.login_sso()
        _, headers, _ = self._upload("week 5-handout.pdf", synthetic_handout_pdf())
        document_id = headers["Location"].rsplit("/", 1)[-1]
        final_id = self.wait_for_pipeline(document_id)
        status, _, page = self.request(f"/documents/{final_id}")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Your document is ready.", page)
        self.assertIn(f'href="/documents/{final_id}/produced"'.encode(), page)
        # The coral seal badge with the exact existing wording.
        self.assertIn(b"seal-badge", page)
        self.assertIn(b"Reviewed &amp; improved", page)
        self.assertIn(b"A review record, not a certification.", page)
        # Insight cards.
        self.assertIn(b"What we improved", page)
        self.assertIn(b"Title added", page)
        self.assertIn("“Week 5 Handout”".encode(), page)
        self.assertIn(b"Language set to English (US)", page)
        self.assertIn(b"Worth a human look", page)
        self.assertIn(b"Verified in your document", page)
        self.assertIn(b"Not checked by this tool", page)
        # The honest gaps strip names the human-judgment areas.
        self.assertIn(b"Color-only meaning", page)
        # Navigation: another round, and the quiet advanced door.
        self.assertIn(b"Transform another document", page)
        self.assertIn(f'href="/documents/{final_id}?view=advanced"'.encode(), page)
        self.assert_scrubbed(page, "ready")
        # Advanced tools opens the classic detail page with lanes and Fix Lab.
        status, _, classic = self.request(f"/documents/{final_id}?view=advanced")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Signals and next actions", classic)
        self.assertIn(b"Remediation provenance", classic)
        self.cookie = ""

    def test_educator_ready_download_serves_sealed_ready_pdf(self):
        from pypdf import PdfReader
        from service.fixtures import synthetic_handout_pdf
        self.login_sso()
        _, headers, _ = self._upload("week 5-handout.pdf", synthetic_handout_pdf())
        document_id = headers["Location"].rsplit("/", 1)[-1]
        final_id = self.wait_for_pipeline(document_id)
        source_bytes = self.repository.document_bytes("coastline-staging", final_id)
        status, headers, sealed = self.request(f"/documents/{final_id}/produced")
        self.assertTrue(status.startswith("200"), status)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertIn('filename="week 5-handout.ready.pdf"', headers["Content-Disposition"])
        self.assertTrue(sealed.startswith(b"%PDF"))
        source_reader = PdfReader(io.BytesIO(source_bytes))
        sealed_reader = PdfReader(io.BytesIO(sealed))
        self.assertEqual(len(sealed_reader.pages), len(source_reader.pages) + 1)
        final_text = sealed_reader.pages[-1].extract_text() or ""
        self.assertIn("Reviewed & improved with Coastline College Accessibility Hub", final_text)
        self.assertIn("A review record, not a certification.", final_text)
        # Provenance kind "seal" recorded once via the existing machinery.
        seals = [row for row in self.repository.remediations("coastline-staging", final_id) if row["kind"] == "seal"]
        self.assertEqual(len(seals), 1)
        self.assertEqual(self.repository.document_bytes("coastline-staging", final_id), source_bytes)
        self.cookie = ""

    def test_educator_pipeline_with_nothing_to_fix_goes_straight_to_ready(self):
        from tina.remedy import MetadataRemediation
        from service.fixtures import synthetic_handout_pdf
        clean, _ = MetadataRemediation.with_builtin_tools().apply(
            "clean.pdf", synthetic_handout_pdf(), title="Week 5 Handout", language="en-US")
        self.login_sso()
        _, headers, _ = self._upload("clean-handout.pdf", clean)
        document_id = headers["Location"].rsplit("/", 1)[-1]
        final_id = self.wait_for_pipeline(document_id)
        # Nothing was auto-fixable: no derived copy, no remediation rows.
        self.assertEqual(final_id, document_id)
        self.assertEqual(self.repository.remediations("coastline-staging", document_id), [])
        status, _, page = self.request(f"/documents/{document_id}")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Your document is ready.", page)
        self.assertNotIn(b"What we improved", page)
        self.assertIn(b"Not checked by this tool", page)
        self.assert_scrubbed(page, "ready (nothing fixed)")
        self.cookie = ""

    def test_access_code_sessions_never_get_the_automatic_pipeline(self):
        # The classic surface's contract is untouched: a sample review is
        # assess-only, and no copy is ever created without an explicit click.
        self.login()
        _, headers, _ = self.request("/documents/synthetic", "POST")
        document_id = headers["Location"].rsplit("/", 1)[-1]
        job = self.wait_for_result(document_id)
        self.assertEqual(job["kind"], "assessment")
        time.sleep(0.3)  # A pipeline child would be created before terminal; give it every chance.
        self.assertIsNone(self.repository.latest_child("coastline-staging", document_id))
        self.assertEqual(self.repository.remediations("coastline-staging", document_id), [])

    def test_educator_pages_never_use_internal_environment_words(self):
        """COPY SCRUB: 'synthetic', 'development', 'staging', 'workspace' are
        internal words. A teacher never sees them on the three-step flow."""
        from service.fixtures import synthetic_handout_pdf
        self.worker.stop()
        self.login_sso()
        surfaces = [("drop", self.request("/app")[2])]
        _, headers, _ = self._upload("week 5-handout.pdf", synthetic_handout_pdf())
        document_id = headers["Location"].rsplit("/", 1)[-1]
        surfaces.append(("processing", self.request(f"/documents/{document_id}")[2]))
        self.assertTrue(self.worker.run_once())
        self.assertTrue(self.worker.run_once())
        final_id = self.wait_for_pipeline(document_id)
        surfaces.append(("ready", self.request(f"/documents/{final_id}")[2]))
        surfaces.append(("drop with recent list", self.request("/app")[2]))
        for context, page in surfaces:
            self.assert_scrubbed(page, context)
        self.cookie = ""

    # ------------------------------------------------------------------
    # The galactic journey layer: status feed, same-origin script, sprite,
    # and CSP compliance across the educator flow.
    # ------------------------------------------------------------------

    def test_journey_status_endpoint_is_educator_gated_and_follows_the_lineage(self):
        from service.fixtures import synthetic_handout_pdf
        self.worker.stop()  # Hold jobs queued so each stage is observable.
        self.login_sso()
        _, headers, _ = self._upload("week 5-handout.pdf", synthetic_handout_pdf())
        document_id = headers["Location"].rsplit("/", 1)[-1]
        educator_cookie = self.cookie
        # No session at all: the login wall intercepts before the route.
        status, headers, _ = self.request(f"/documents/{document_id}/status.json", cookie="none=1")
        self.assertTrue(status.startswith("303"), status)
        self.assertEqual(headers["Location"], "/login")
        # An access-code session never sees the route: it does not exist.
        self.login()
        status, _, _ = self.request(f"/documents/{document_id}/status.json")
        self.assertTrue(status.startswith("404"), status)
        # The educator session gets the JSON feed: reading first.
        self.cookie = educator_cookie
        status, headers, body = self.request(f"/documents/{document_id}/status.json")
        self.assertTrue(status.startswith("200"), status)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertEqual(headers["Cache-Control"], "no-store")
        payload = json.loads(body)
        self.assertEqual(set(payload), {"state", "stage", "location", "display"})
        self.assertEqual(payload["stage"], "reading")
        self.assertEqual(payload["state"], "queued")
        self.assertEqual(payload["location"], f"/documents/{document_id}")
        self.assertEqual(payload["display"], "week 5-handout.pdf")
        # First worker pass: the improved copy exists and is queued — polling
        # the ORIGINAL id follows the lineage to the improving/verifying stage.
        self.assertTrue(self.worker.run_once())
        payload = json.loads(self.request(f"/documents/{document_id}/status.json")[2])
        self.assertIn(payload["stage"], {"improving", "verifying"})
        child_location = payload["location"]
        self.assertNotEqual(child_location, f"/documents/{document_id}")
        # Second pass: terminal. Stage ready, location is the final copy.
        self.assertTrue(self.worker.run_once())
        payload = json.loads(self.request(f"/documents/{document_id}/status.json")[2])
        self.assertEqual(payload["stage"], "ready")
        self.assertEqual(payload["state"], "succeeded")
        self.assertEqual(payload["location"], child_location)
        self.cookie = ""

    def test_journey_script_is_served_first_party_and_pages_carry_scene_sprite_and_motion_gates(self):
        from service.fixtures import synthetic_handout_pdf
        # The asset itself: same-origin, JavaScript, no third-party reach.
        status, headers, body = self.request("/assets/journey.js")
        self.assertTrue(status.startswith("200"))
        self.assertTrue(headers["Content-Type"].startswith("text/javascript"))
        self.assertNotIn(b"http://", body)
        self.assertNotIn(b"https://", body)
        self.assertIn(b"prefers-reduced-motion", body)
        self.worker.stop()
        self.login_sso()
        drop = self.request("/app")[2]
        _, headers, _ = self._upload("week 5-handout.pdf", synthetic_handout_pdf())
        document_id = headers["Location"].rsplit("/", 1)[-1]
        processing = self.request(f"/documents/{document_id}")[2]
        self.assertTrue(self.worker.run_once())
        self.assertTrue(self.worker.run_once())
        final_id = self.wait_for_pipeline(document_id)
        ready = self.request(f"/documents/{final_id}")[2]
        for name, page in (("drop", drop), ("processing", processing), ("ready", ready)):
            self.assert_csp_scripts(page)
            self.assertIn(b"<symbol id=i-doc", page, name)
            self.assertIn(b"<symbol id=i-star", page, name)
            self.assertIn(b"prefers-reduced-motion", page, name)
            self.assertIn(b"prefers-reduced-motion:no-preference", page, name)
        # Drop page: the enhanced drop zone wraps the plain form control.
        self.assertIn(b"data-dropzone", drop)
        self.assertIn(b"data-drop-hint", drop)
        # Processing page: journey scene, status feed wiring, staged stops,
        # and the labeled sponsor fly-by outside the live region.
        self.assertIn(b"data-journey=processing", processing)
        self.assertIn(f'data-status-url="/documents/{document_id}/status.json"'.encode(), processing)
        self.assertIn(b"data-stage=reading", processing)
        for marker in (b"journey-scene", b"journey-doc", b"journey-comet", b"journey-star",
                       b'data-stage-item=reading', b'data-stage-item=improving', b'data-stage-item=verifying'):
            self.assertIn(marker, processing)
        self.assertIn(b"sponsor-fly", processing)
        self.assertIn(b">Sponsored</span>", processing)
        sponsor_tag = re.search(rb'<aside class="panel sponsor-card[^"]*"[^>]*>', processing)
        self.assertIsNotNone(sponsor_tag)
        self.assertNotIn(b"aria-live", sponsor_tag.group(0))  # Sponsor content is never a live region.
        # Ready page: celebration hooks, no sponsor, no status polling.
        self.assertIn(b"data-journey=ready", ready)
        self.assertIn(b"ready-stars", ready)
        self.assertNotIn(b"data-status-url", ready)
        self.assertNotIn(b">Sponsored</span>", ready)
        self.cookie = ""

    def test_classic_surfaces_stay_script_free_and_hosted_never_serves_the_status_route(self):
        # The access-code surface keeps its no-script pages byte-for-byte in
        # spirit: no script tags anywhere on login, workspace, or documents.
        status, _, login_page = self.request("/login")
        self.assertTrue(status.startswith("200"))
        self.assertNotIn(b"<script", login_page)
        self.login()
        workspace = self.request("/app")[2]
        self.assertNotIn(b"<script", workspace)
        self.worker.stop()  # Hold the job so the classic running page is observable.
        _, headers, _ = self.request("/documents/synthetic", "POST")
        document_id = headers["Location"].rsplit("/", 1)[-1]
        running = self.request(f"/documents/{document_id}")[2]
        self.assertNotIn(b"<script", running)
        # The classic sponsor card keeps its exact presentation: no fly-by.
        self.assertIn(b'<aside class="panel sponsor-card" aria-label="Sponsored message">', running)
        self.assertTrue(self.worker.run_once())  # Drive the held job to terminal.
        classic = self.request(f"/documents/{document_id}")[2]
        self.assertNotIn(b"<script", classic)
        self.cookie = ""
        # Hosted staging: no educator session exists, so the status route 404s
        # even for a signed-in access-code session — boundary untouched.
        hosted = ServiceSettings("staging", Path(self.temp.name) / "journey-hosted", "synthetic-only-code", "s" * 48, (), allow_hosted_synthetic=True)
        repository = StagingRepository(hosted.data_dir)
        worker = AssessmentWorker(repository)
        self.app = create_app(hosted, repository, worker)
        try:
            self.login()
            _, headers, _ = self.request("/documents/synthetic", "POST")
            hosted_doc = headers["Location"].rsplit("/", 1)[-1]
            status, _, _ = self.request(f"/documents/{hosted_doc}/status.json")
            self.assertTrue(status.startswith("404"), status)
            # Hosted environments serve no script assets at all: the journey
            # file is a development-only route, so the hosted surface gains
            # zero new endpoints.
            status, _, _ = self.request("/assets/journey.js")
            self.assertTrue(status.startswith("404"), status)
        finally:
            worker.stop()
            self.app = create_app(self.settings, self.repository, self.worker)
            self.cookie = ""

    def test_new_educator_text_ground_pairs_meet_contrast_contract(self):
        from tests.test_design_contract import contrast_ratio
        pairs = (
            ("#1D6E4C", "#DFF2E6"),  # improved-card heading on success wash
            ("#3A434E", "#DFF2E6"),  # improved-card body on success wash
            ("#0C6172", "#DDF0F2"),  # look icon chip on review wash
            ("#565E68", "#ECEDEF"),  # unchecked icon chip on neutral wash
            ("#5C6670", "#FFFFFF"),  # quiet link + strips on white
            ("#5C6670", "#FAFAF8"),  # look-card body on wash
            ("#CF3A24", "#FFFFFF"),  # sample footer link on white
            ("#232A33", "#FAFAF8"),  # look-card heading on wash
        )
        for foreground, background in pairs:
            self.assertGreaterEqual(contrast_ratio(foreground, background), 4.5, (foreground, background))

    def test_service_files_and_doc_never_use_prohibited_outcome_language(self):
        """CI governance mirror for the files this boundary owns.

        The canonical phrase list is imported from tina.evidence (the exempt
        source of truth) so this test does not itself embed the phrases.
        """
        from tina.evidence import PROHIBITED_OUTCOME_PHRASES
        root = Path(__file__).resolve().parents[1]
        surfaces = list((root / "service").glob("*.py")) + [
            root / "docs" / "private-staging-service.md", root / "render.yaml"]
        for surface in surfaces:
            text = surface.read_text().lower()
            for phrase in PROHIBITED_OUTCOME_PHRASES:
                self.assertNotIn(phrase, text, f"Prohibited phrase '{phrase}' found in {surface.name}")


if __name__ == "__main__":
    unittest.main()
