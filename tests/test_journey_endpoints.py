import base64
import hashlib
import io
import json
import unittest
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

from pypdf import PdfReader, PdfWriter

from local_reviewer import create_server
from tina.learning import LearningJourney


def minimal_pdf(page_width: float = 612) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=page_width, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def title_checker(pdf_path: Path, output_dir: Path) -> dict:
    payload = pdf_path.read_bytes()
    reader = PdfReader(io.BytesIO(payload))
    findings = []
    if not (reader.metadata or {}).get("/Title"):
        findings.append({"rule_id": "PDF.METADATA.TITLE", "category": "deterministic_defect", "severity": "medium"})
    return {
        "schema_version": "0.1",
        "input": {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)},
        "tools": {"pypdf": "6.9.1"},
        "findings": findings,
        "strengths": [],
    }


class JourneyEndpointTests(unittest.TestCase):
    def setUp(self):
        self.journey = LearningJourney()
        self.server = create_server(0, title_checker, journey=self.journey)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def get_json(self, path: str):
        with urlopen(self.base + path, timeout=10) as response:
            return json.loads(response.read())

    def post(self, path: str, payload: bytes, content_type: str = "application/pdf"):
        request = Request(self.base + path, data=payload, headers={"Content-Type": content_type}, method="POST")
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    def test_reviews_feed_the_learning_journey_and_detect_repeat_defects(self):
        self.post("/api/review?filename=a.pdf", minimal_pdf(612))
        journey = self.get_json("/api/journey")
        self.assertEqual(journey["skills"]["titles_and_language"]["state"], "introduced")

        self.post("/api/review?filename=b.pdf", minimal_pdf(600))
        journey = self.get_json("/api/journey")
        self.assertEqual(journey["documents_reviewed"], 2)
        self.assertEqual(len(journey["repeat_defects"]), 1)

    def test_fix_advances_mastery_to_verified(self):
        self.post("/api/fix?filename=a.pdf&title=Week%203", minimal_pdf())
        journey = self.get_json("/api/journey")
        self.assertEqual(journey["skills"]["titles_and_language"]["state"], "verified")

    def test_attest_endpoint_records_judgment_decisions(self):
        body = json.dumps({"rule_id": "PDF.IMAGES.ALTERNATIVES", "decision": "Reviewed; two decorative."}).encode()
        journey = self.post("/api/attest", body, content_type="application/json")
        self.assertEqual(journey["skills"]["images_and_meaning"]["state"], "applied")

    def test_fixed_copy_rereview_does_not_scold_with_repeat_defects(self):
        # Regression: every fix produced a copy with a new hash, and re-reviewing
        # that copy counted as the defect appearing in a NEW document, so fixing
        # one document progressively triggered red repeat-defect warnings.
        def links_checker(pdf_path: Path, output_dir: Path) -> dict:
            payload = pdf_path.read_bytes()
            reader = PdfReader(io.BytesIO(payload))
            findings = [{"rule_id": "PDF.LINKS.PURPOSE", "category": "review_required", "severity": "medium"}]
            if not (reader.metadata or {}).get("/Title"):
                findings.append({"rule_id": "PDF.METADATA.TITLE", "category": "deterministic_defect", "severity": "medium"})
            return {
                "schema_version": "0.1",
                "input": {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)},
                "tools": {"pypdf": "6.9.1"},
                "findings": findings,
                "strengths": [],
            }

        server = create_server(0, links_checker, journey=LearningJourney())
        Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            def post(path: str, payload: bytes):
                request = Request(base + path, data=payload,
                                  headers={"Content-Type": "application/pdf"}, method="POST")
                with urlopen(request, timeout=10) as response:
                    return json.loads(response.read())

            result = post("/api/fix?filename=a.pdf&title=Week%203", minimal_pdf())
            fixed_pdf = base64.b64decode(result["fixed_pdf_base64"])
            self.assertNotEqual(result["before"]["input"]["sha256"], result["after"]["input"]["sha256"])
            post(f"/api/review?filename={result['fixed_filename']}", fixed_pdf)

            with urlopen(base + "/api/journey", timeout=10) as response:
                journey = json.loads(response.read())
            self.assertEqual(journey["repeat_defects"], [])
            self.assertEqual(journey["documents_reviewed"], 1)
        finally:
            server.shutdown()
            server.server_close()

    def test_receipt_endpoint_builds_verifiable_receipt(self):
        review = self.post("/api/review?filename=a.pdf", minimal_pdf())
        body = json.dumps({
            "review": review,
            "attestations": [{"rule_id": "PDF.IMAGES.ALTERNATIVES", "decision": "Reviewed.", "decided_at": "2026-07-20T00:00:00Z"}],
        }).encode()
        receipt = self.post("/api/receipt", body, content_type="application/json")
        self.assertEqual(receipt["contract_version"], "tina-evidence-receipt/v1")
        self.assertIn("not a certification", receipt["disclaimer"])
        self.assertTrue(receipt["receipt_sha256"].startswith("sha256:"))
        self.assertEqual(len(receipt["human_decisions"]), 1)


if __name__ == "__main__":
    unittest.main()
