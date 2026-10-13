"""Hosted real-PDF uploads (HUB_ACCEPT_UPLOADS) and the document retention period."""
import io
import json
import re
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from service import app as service_app
from service.app import create_app
from service.fixtures import synthetic_handout_pdf
from service.repository import StagingRepository
from service.settings import DEFAULT_RETENTION_DAYS, ServiceSettings
from service.worker import AssessmentWorker

TENANT = "coastline-staging"
CODE = "pilot-access-code"
SCRUBBED_WORDS = ("synthetic", "development", "staging", "workspace")


def visible_text(page: bytes) -> str:
    text = re.sub(r"<style.*?</style>|<script.*?</script>", " ", page.decode("utf-8", "replace"), flags=re.S)
    return re.sub(r"<[^>]+>", " ", text).lower()


BASE_ENV = {"HUB_ENV": "staging", "HUB_STAGING_ACCESS_CODE": CODE, "HUB_SESSION_SECRET": "s" * 48}


class UploadSettingsTests(unittest.TestCase):
    def test_uploads_open_only_on_the_exact_value_true(self):
        for value in ("", "1", "TRUE", "True", "yes", " true", "true ", "true\n", "on"):
            settings = ServiceSettings.from_environ({**BASE_ENV, "HUB_ACCEPT_UPLOADS": value})
            self.assertFalse(settings.uploads_ready, repr(value))
            self.assertFalse(settings.health_payload()["hosted_intake_enabled"])
        opened = ServiceSettings.from_environ({**BASE_ENV, "HUB_ACCEPT_UPLOADS": "true"})
        self.assertTrue(opened.uploads_ready)
        self.assertTrue(opened.synthetic_intake_ready)
        payload = opened.health_payload()
        self.assertTrue(payload["hosted_intake_enabled"])
        self.assertFalse(payload["synthetic_only"])

    def test_uploads_need_sign_in_and_never_open_on_a_public_workspace(self):
        public = ServiceSettings.from_environ({**BASE_ENV, "HUB_ACCEPT_UPLOADS": "true", "HUB_PUBLIC_ACCESS": "true"})
        self.assertFalse(public.uploads_ready)
        no_login = ServiceSettings.from_environ({"HUB_ENV": "staging", "HUB_ACCEPT_UPLOADS": "true"})
        self.assertFalse(no_login.uploads_ready)

    def test_retention_defaults_to_365_days_and_rejects_nonsense(self):
        self.assertEqual(DEFAULT_RETENTION_DAYS, 365)
        self.assertEqual(ServiceSettings.from_environ(BASE_ENV).retention_days, 365)
        self.assertEqual(ServiceSettings.from_environ({**BASE_ENV, "HUB_RETENTION_DAYS": "30"}).retention_days, 30)
        for value in ("0", "-5", "abc", "1.5", "3651"):
            with self.assertRaises(ValueError, msg=value):
                ServiceSettings.from_environ({**BASE_ENV, "HUB_RETENTION_DAYS": value})
        self.assertEqual(ServiceSettings.from_environ(BASE_ENV).health_payload()["retention_days"], 365)


class HostedUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.make_app()

    def tearDown(self):
        self.worker.stop()
        self.temp.cleanup()

    def make_app(self, **overrides):
        if getattr(self, "worker", None):
            self.worker.stop()
        options = {"accept_uploads": True, "enable_produce": True, **overrides}
        self.settings = ServiceSettings("staging", Path(self.temp.name) / "hub", CODE, "s" * 48, (), **options)
        self.repository = StagingRepository(self.settings.data_dir)
        self.worker = AssessmentWorker(self.repository, retention_days=self.settings.retention_days)
        self.app = create_app(self.settings, self.repository, self.worker)
        self.cookie = ""

    def call(self, path, method="GET", body=b"", content_type="application/x-www-form-urlencoded"):
        query = ""
        if "?" in path:
            path, query = path.split("?", 1)
        captured = {}

        def start_response(status, headers):
            captured["status"], captured["headers"] = status, dict(headers)

        response = b"".join(self.app({
            "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
            "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": content_type,
            "wsgi.input": io.BytesIO(body), "HTTP_COOKIE": self.cookie,
        }, start_response))
        return captured["status"], captured["headers"], response

    def post(self, path, form):
        return self.call(path, "POST", urlencode(form).encode())

    def login(self):
        status, headers, _ = self.post("/login", {"code": CODE})
        self.assertTrue(status.startswith("303"), status)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]

    def upload(self, filename="ENGL101 syllabus.pdf", payload=None):
        boundary = "hubtestboundary"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                "Content-Type: application/pdf\r\n\r\n").encode() + (payload or synthetic_handout_pdf()) + f"\r\n--{boundary}--\r\n".encode()
        return self.call("/documents/upload", "POST", body, f"multipart/form-data; boundary={boundary}")

    def wait_for_ready(self, document_id):
        """Follow the pipeline to its final version and return that version's id."""
        for _ in range(400):
            status, headers, _ = self.call(f"/documents/{document_id}")
            if status.startswith("303"):
                document_id = headers["Location"].rsplit("/", 1)[-1]
                continue
            job = self.repository.latest_job(TENANT, document_id)
            if job and job["state"] in {"succeeded", "failed"} and self.repository.latest_child(TENANT, document_id) is None:
                return document_id
            time.sleep(0.05)
        self.fail("pipeline did not finish")

    def audit_actions(self):
        with self.repository._connect() as db:
            return [row["action"] for row in db.execute("SELECT action FROM audit_events ORDER BY created_at")]

    def test_sign_in_is_required_before_any_upload(self):
        status, headers, _ = self.upload()
        self.assertTrue(status.startswith("303"))
        self.assertEqual(headers["Location"], "/login")
        self.assertEqual(self.repository.list_documents(TENANT), [])

    def test_signed_in_teacher_uploads_a_real_pdf_and_downloads_the_result(self):
        status, _, page = self.call("/login")
        self.assertIn(b"Sign in to the Accessibility Hub", page)
        self.assertNotIn(b"staging workspace", page)
        self.login()
        status, _, landing = self.call("/app")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b'action="/documents/upload"', landing)
        self.assertIn(b'enctype="multipart/form-data"', landing)
        self.assertIn(b"kept for 365 days, then deleted automatically", landing)
        self.assertIn(b"Everyone who signs in here can see these documents.", landing)
        self.assertNotIn(b"Real-document upload is not available", landing)

        # The flow's same-origin script is served (the processing page relies
        # on it to move forward), even before sign-in, like the other assets.
        self.assertIn(b'src="/assets/journey.js"', landing)
        self.assertTrue(self.call("/assets/journey.js")[0].startswith("200"))
        status, headers, _ = self.upload()
        self.assertTrue(status.startswith("303"), status)
        original_id = headers["Location"].rsplit("/", 1)[-1]
        self.assertEqual(self.repository.document(TENANT, original_id)["source_kind"], "educator_upload")
        final_id = self.wait_for_ready(original_id)

        status, _, ready = self.call(f"/documents/{final_id}")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Your document is ready.", ready)
        self.assertIn(f'/documents/{final_id}/produced'.encode(), ready)
        self.assertIn(f'/documents/{final_id}/accessible'.encode(), ready)
        until = (datetime.now(UTC) + timedelta(days=365)).strftime("%B")
        self.assertIn(b"Kept until " + until.encode(), ready)
        self.assertIn(f'action="/documents/{original_id}/delete"'.encode(), ready)
        status, headers, body = self.call(f"/documents/{final_id}/produced")
        self.assertTrue(status.startswith("200"), status)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertTrue(body.startswith(b"%PDF-"))
        self.assertTrue(self.call(f"/documents/{final_id}/thumbnail.png")[0][:3] in {"200", "404"})
        self.assertIn("educator_document_uploaded", self.audit_actions())
        for page in (landing, ready):
            for word in SCRUBBED_WORDS:
                self.assertNotIn(word, visible_text(page))

    def test_teacher_deletes_the_original_and_every_copy(self):
        self.login()
        _, headers, _ = self.upload()
        original_id = headers["Location"].rsplit("/", 1)[-1]
        final_id = self.wait_for_ready(original_id)
        self.assertNotEqual(original_id, final_id)
        stored = list((self.settings.data_dir / "documents").iterdir())
        self.assertGreaterEqual(len(stored), 2)
        status, headers, _ = self.post(f"/documents/{original_id}/delete", {"confirmed": "yes", "scope": "all"})
        self.assertTrue(status.startswith("303"))
        self.assertEqual(self.repository.list_documents(TENANT), [])
        self.assertEqual([p for p in (self.settings.data_dir / "documents").iterdir() if p.suffix != ".png"], [])
        self.assertIn("document_deleted", self.audit_actions())

    def test_uploads_stay_closed_without_the_opt_in_or_on_a_public_workspace(self):
        for overrides in ({"accept_uploads": False}, {"public_access": True}):
            self.make_app(**overrides)
            if not overrides.get("public_access"):
                self.login()
            status, _, landing = self.call("/app")
            self.assertNotIn(b'action="/documents/upload"', landing, overrides)
            status, _, _ = self.upload()
            self.assertTrue(status.startswith("404"), (overrides, status))
            self.assertTrue(self.call("/assets/journey.js")[0].startswith("404"), overrides)
            self.assertEqual(self.repository.list_documents(TENANT), [])

    def test_a_full_disk_refuses_the_upload_honestly(self):
        self.login()
        full = mock.Mock(free=10 * 1024 * 1024)
        with mock.patch.object(service_app.shutil, "disk_usage", return_value=full):
            status, _, page = self.upload()
        self.assertTrue(status.startswith("507"), status)
        self.assertIn(b"out of storage space", page)
        self.assertEqual(self.repository.list_documents(TENANT), [])
        self.assertIn("upload_refused_storage_full", self.audit_actions())

    def test_not_a_pdf_is_refused(self):
        self.login()
        status, _, page = self.upload("notes.pdf", b"hello, not a pdf")
        self.assertTrue(status.startswith("400"))
        self.assertIn(b"does not look like a PDF", page)


class RetentionSweepTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repository = StagingRepository(Path(self.temp.name))
        self.worker = AssessmentWorker(self.repository, retention_days=365)

    def tearDown(self):
        self.worker.stop()
        self.temp.cleanup()

    def age(self, document_id, days):
        stamp = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self.repository._connect() as db:
            db.execute("UPDATE documents SET created_at=? WHERE id=?", (stamp, document_id))

    def test_documents_past_365_days_are_deleted_with_their_copies_and_audited(self):
        old = self.repository.create_document(TENANT, "old.pdf", "educator_upload", b"%PDF-1.7 old")
        copy = self.repository.create_document(TENANT, "old.rechecked.pdf", "synthetic_remediated_copy", b"%PDF-1.7 copy", parent_document_id=old["id"])
        recent = self.repository.create_document(TENANT, "recent.pdf", "educator_upload", b"%PDF-1.7 new")
        self.age(old["id"], 366)
        self.age(recent["id"], 364)
        self.assertEqual(self.worker.sweep_retention(), 1)
        self.assertIsNone(self.repository.document(TENANT, old["id"]))
        self.assertIsNone(self.repository.document(TENANT, copy["id"]))
        self.assertIsNotNone(self.repository.document(TENANT, recent["id"]))
        self.assertFalse((self.repository.documents_dir / old["storage_key"]).exists())
        self.assertFalse((self.repository.documents_dir / copy["storage_key"]).exists())
        with self.repository._connect() as db:
            rows = [dict(row) for row in db.execute("SELECT actor, action, target_id, detail_json FROM audit_events")]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["actor"], rows[0]["action"], rows[0]["target_id"]), ("retention-policy", "document_expired", old["id"]))
        detail = json.loads(rows[0]["detail_json"])
        self.assertEqual(detail["deleted_document_count"], 2)
        self.assertEqual(detail["retention_days"], 365)
        self.assertNotIn("old.pdf", rows[0]["detail_json"])
        # A second sweep finds nothing new.
        self.assertEqual(self.worker.sweep_retention(), 0)

    def test_without_a_retention_period_nothing_is_swept(self):
        document = self.repository.create_document(TENANT, "old.pdf", "educator_upload", b"%PDF-1.7 old")
        self.age(document["id"], 5000)
        self.assertEqual(AssessmentWorker(self.repository).sweep_retention(), 0)
        self.assertIsNotNone(self.repository.document(TENANT, document["id"]))

    def test_the_running_worker_sweeps_on_start(self):
        document = self.repository.create_document(TENANT, "old.pdf", "educator_upload", b"%PDF-1.7 old")
        self.age(document["id"], 400)
        self.worker.start()
        for _ in range(100):
            if self.repository.document(TENANT, document["id"]) is None:
                break
            time.sleep(0.02)
        self.assertIsNone(self.repository.document(TENANT, document["id"]))


if __name__ == "__main__":
    unittest.main()
