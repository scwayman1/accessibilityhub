import unittest
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
import json

from local_reviewer import (
    MAX_PDF_BYTES,
    UploadValidationError,
    create_server,
    normalize_report_for_browser,
    run_local_review,
    validate_pdf_upload,
)


class UploadValidationTests(unittest.TestCase):
    def test_accepts_small_pdf_with_pdf_magic_bytes(self):
        validate_pdf_upload("course-outline.pdf", b"%PDF-1.7\nexample")

    def test_rejects_non_pdf_magic_bytes_even_when_extension_is_pdf(self):
        with self.assertRaises(UploadValidationError):
            validate_pdf_upload("course-outline.pdf", b"not a PDF")

    def test_rejects_non_pdf_filename(self):
        with self.assertRaises(UploadValidationError):
            validate_pdf_upload("course-outline.docx", b"%PDF-1.7\nexample")

    def test_rejects_payload_above_local_limit(self):
        with self.assertRaises(UploadValidationError):
            validate_pdf_upload("course-outline.pdf", b"%PDF-" + b"x" * MAX_PDF_BYTES)


class LocalReviewLifecycleTests(unittest.TestCase):
    def test_checker_receives_local_temporary_pdf_and_returns_report(self):
        observed = {}

        def fake_checker(pdf_path: Path, output_dir: Path):
            observed["path"] = pdf_path
            observed["output"] = output_dir
            observed["payload"] = pdf_path.read_bytes()
            return {"findings": [{"rule_id": "PDF.TEST", "category": "advisory"}]}

        report = run_local_review("course-outline.pdf", b"%PDF-1.7\nlocal", fake_checker)

        self.assertEqual(observed["payload"], b"%PDF-1.7\nlocal")
        self.assertEqual(report["findings"][0]["rule_id"], "PDF.TEST")
        self.assertFalse(observed["path"].exists())


class ReportBoundaryTests(unittest.TestCase):
    def test_browser_report_omits_temporary_file_paths(self):
        report = normalize_report_for_browser({
            "input": {"path": "/private/tmp/coastline-pdf-review-123/source.pdf", "sha256": "abc", "bytes": 12},
            "verapdf": {"report_path": "/private/tmp/coastline-pdf-review-123/evidence/report.json"},
            "findings": [],
        })
        self.assertNotIn("path", report["input"])
        self.assertNotIn("report_path", report["verapdf"])
        self.assertEqual(report["input"]["sha256"], "abc")

    def test_loopback_review_endpoint_returns_checker_report(self):
        def fake_checker(pdf_path: Path, output_dir: Path):
            return {"findings": [{"rule_id": "PDF.LOCAL", "category": "review_required"}]}

        server = create_server(0, fake_checker)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/review?filename=outline.pdf",
                data=b"%PDF-1.7\nlocal test",
                headers={"Content-Type": "application/pdf"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read())
            self.assertEqual(payload["findings"][0]["rule_id"], "PDF.LOCAL")
            self.assertEqual(server.server_address[0], "127.0.0.1")
            with urlopen(f"http://127.0.0.1:{server.server_port}/delight-content.json", timeout=5) as response:
                delight = json.loads(response.read())
            self.assertTrue(delight["categories"]["encouragement"]["enabled"])
        finally:
            server.shutdown()
            server.server_close()
