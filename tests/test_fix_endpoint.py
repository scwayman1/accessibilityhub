import base64
import io
import json
import re
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pypdf import PdfReader, PdfWriter

from local_reviewer import create_server


def minimal_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def title_aware_checker(pdf_path: Path, output_dir: Path) -> dict:
    reader = PdfReader(str(pdf_path))
    findings = []
    if not (reader.metadata or {}).get("/Title"):
        findings.append({"rule_id": "PDF.METADATA.TITLE", "category": "deterministic_defect"})
    return {"findings": findings, "input": {"path": str(pdf_path)}}


class FixEndpointTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(0, title_aware_checker)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, path: str, payload: bytes):
        request = Request(self.base + path, data=payload, headers={"Content-Type": "application/pdf"}, method="POST")
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    def test_fix_endpoint_returns_before_after_and_updated_pdf(self):
        result = self.post("/api/fix?filename=outline.pdf&title=Week%203%20Outline", minimal_pdf())

        self.assertEqual(result["before"]["findings"][0]["rule_id"], "PDF.METADATA.TITLE")
        self.assertEqual(result["after"]["findings"], [])
        self.assertEqual(result["fixed_filename"], "outline.updated.pdf")
        self.assertEqual(result["remediation"]["contract_version"], "tina-remediation-report/v1")
        fixed = base64.b64decode(result["fixed_pdf_base64"])
        self.assertTrue(fixed.startswith(b"%PDF-"))
        self.assertEqual(PdfReader(io.BytesIO(fixed)).metadata.get("/Title"), "Week 3 Outline")
        self.assertNotIn("path", result["before"]["input"])
        self.assertNotIn("path", result["after"]["input"])

    def test_fix_endpoint_rejects_request_without_any_fix(self):
        with self.assertRaises(HTTPError) as context:
            self.post("/api/fix?filename=outline.pdf", minimal_pdf())
        self.assertEqual(context.exception.code, 400)

    def test_knowledge_endpoint_serves_teaching_cards(self):
        with urlopen(self.base + "/api/knowledge", timeout=5) as response:
            knowledge = json.loads(response.read())
        self.assertIn("PDF.METADATA.TITLE", knowledge["rules"])
        self.assertTrue(knowledge["rules"]["PDF.METADATA.TITLE"]["auto_fixable"])


class KnowledgeCoverageTests(unittest.TestCase):
    def test_every_checker_rule_has_a_teaching_card(self):
        source = Path("check_pdf.py").read_text()
        checker_rules = set(re.findall(r'"(PDF\.[A-Z_.0-9]+)"', source))
        knowledge = json.loads(Path("rule_knowledge.json").read_text())
        self.assertTrue(checker_rules)
        missing = checker_rules - set(knowledge["rules"])
        self.assertEqual(missing, set(), f"Rules without teaching cards: {sorted(missing)}")
        for rule_id, card in knowledge["rules"].items():
            for field in ("title", "why_it_matters", "who_it_affects", "fix_at_source", "auto_fixable"):
                self.assertIn(field, card, f"{rule_id} is missing {field}")


class CheckerDegradationTests(unittest.TestCase):
    def test_missing_binary_is_reported_not_raised(self):
        from check_pdf import run, tool_missing

        result = run(["coastline-nonexistent-tool", "--version"])
        self.assertTrue(tool_missing(result))
        self.assertIsNone(result["returncode"])
        self.assertIn("is not installed", result["stderr"])


if __name__ == "__main__":
    unittest.main()
