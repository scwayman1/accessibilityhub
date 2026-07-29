import io
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
        body = urlencode(form or {}).encode()
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)
        response = b"".join(self.app({
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
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
        self.assertIn(b"needs attention", page)
        self.assertIn(b"Apply a metadata repair", page)

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


if __name__ == "__main__":
    unittest.main()
