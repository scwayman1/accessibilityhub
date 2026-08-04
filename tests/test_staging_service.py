import io
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

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
        self.assertIn(b"coastline-college-logo-white.png", self.request("/login")[2])

    def test_private_workspace_uses_labeled_workflow_steps_and_finding_chips(self):
        self.login()
        status, _, workspace = self.request("/app")
        self.assertTrue(status.startswith("200"))
        for label in (b"Add material", b"Review", b"Improve", b"Check again"):
            self.assertIn(label, workspace)
        self.assertIn(b"panel rail", workspace)
        self.assertIn(b":focus-visible", workspace)
        self.assertIn(b"@media(max-width:800px)", workspace)
        self.assertIn(b".workspace { grid-template-columns:1fr }", workspace)

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
        self.assertIn(b"Fix Lab", page)
        self.assertIn(b"Update title and language", page)

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
        self.assertIn(b"refreshes automatically", page)
        self.assertNotIn(b"location.reload", page)  # CSP blocks inline script; refresh must not rely on it.
        self.assertTrue(self.worker.run_once())
        job = self.repository.latest_job("coastline-staging", document_id)
        self.assertIn(job["state"], {"succeeded", "failed"})
        status, _, page = self.request(f"/documents/{document_id}")
        self.assertTrue(status.startswith("200"))
        self.assertNotIn(b'http-equiv="refresh"', page)

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
