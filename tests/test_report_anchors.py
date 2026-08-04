"""Report honesty anchors: not_assessed routing entries and per-finding page anchors."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import check_pdf
from check_pdf import analyze


STATIC_AREAS = {
    "visual contrast",
    "table structure semantics",
    "form field labels",
    "color-only meaning",
}
QPDF_AREA = "structural integrity (qpdf)"
VERAPDF_AREA = "PDF/UA-1 validator (veraPDF)"


def build_pdf(objects: list[bytes]) -> bytes:
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode())
    return out.getvalue()


def simple_pdf() -> bytes:
    stream = b"BT /F1 12 Tf 72 720 Td (Plain text, no tags.) Tj ET"
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ])


def anchored_pdf() -> bytes:
    """Two pages: page 1 is plain text; page 2 carries an image XObject and an unnamed link."""
    page1 = b"BT /F1 12 Tf 72 720 Td (Syllabus overview.) Tj ET"
    page2 = b"BT /F1 12 Tf 72 720 Td (A chart appears below.) Tj ET q 100 0 0 100 72 500 cm /Im1 Do Q"
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> /XObject << /Im1 8 0 R >> >> /Contents 7 0 R /Annots [9 0 R] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(page1)).encode() + b" >>\nstream\n" + page1 + b"\nendstream",
        b"<< /Length " + str(len(page2)).encode() + b" >>\nstream\n" + page2 + b"\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length 1 >>\nstream\n\x00\nendstream",
        b"<< /Type /Annot /Subtype /Link /Rect [72 700 150 720] /Border [0 0 0] "
        b"/A << /S /URI /URI (https://example.edu/reading) >> >>",
    ])


def named_link_pdf() -> bytes:
    """One page whose only link annotation carries an accessible description (/Contents)."""
    page1 = b"BT /F1 12 Tf 72 720 Td (Week 3 reading list.) Tj ET"
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R /Annots [6 0 R] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(page1)).encode() + b" >>\nstream\n" + page1 + b"\nendstream",
        b"<< /Type /Annot /Subtype /Link /Rect [72 700 150 720] /Border [0 0 0] "
        b"/Contents (Week 3 reading: chapter 4) "
        b"/A << /S /URI /URI (https://example.edu/reading) >> >>",
    ])


def tagged_figure_pdf() -> bytes:
    """One tagged page with a /Figure structure element (no /Alt) anchored to the page via /Pg."""
    page1 = b"BT /F1 12 Tf 72 720 Td (A chart appears below.) Tj ET q 100 0 0 100 72 500 cm /Im1 Do Q"
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R /MarkInfo << /Marked true >> /StructTreeRoot 7 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> /XObject << /Im1 6 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(page1)).encode() + b" >>\nstream\n" + page1 + b"\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length 1 >>\nstream\n\x00\nendstream",
        b"<< /Type /StructTreeRoot /K [8 0 R] >>",
        b"<< /S /Figure /P 7 0 R /Pg 3 0 R >>",
    ])


def partially_scanned_pdf() -> bytes:
    """Two pages: page 1 has extractable text; page 2 has an empty content stream."""
    page1 = b"BT /F1 12 Tf 72 720 Td (Text on page one.) Tj ET"
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 7 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(page1)).encode() + b" >>\nstream\n" + page1 + b"\nendstream",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ])


def run_analyze(payload: bytes) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        pdf = Path(directory) / "doc.pdf"
        pdf.write_bytes(payload)
        return analyze(pdf, Path(directory) / "out")


def areas(report: dict) -> set:
    return {entry["area"] for entry in report["not_assessed"]}


def rules(report: dict) -> dict:
    return {item["rule_id"]: item for item in report["findings"]}


class NotAssessedTests(unittest.TestCase):
    def test_static_areas_are_always_present(self):
        report = run_analyze(simple_pdf())
        self.assertIn("not_assessed", report)
        self.assertLessEqual(STATIC_AREAS, areas(report))
        for entry in report["not_assessed"]:
            self.assertEqual(set(entry), {"area", "reason"})
            self.assertIsInstance(entry["area"], str)
            self.assertIsInstance(entry["reason"], str)
            self.assertTrue(entry["reason"].strip())

    def test_entries_route_to_humans_without_implying_an_outcome(self):
        report = run_analyze(simple_pdf())
        for entry in report["not_assessed"]:
            lowered = entry["reason"].lower()
            self.assertNotIn("passed", lowered)
            self.assertNotIn("failed", lowered)
            self.assertNotIn("compliant", lowered)

    def test_qpdf_entry_appears_when_qpdf_is_missing(self):
        missing = {"command": ["qpdf"], "returncode": None, "stdout": "",
                   "stderr": "qpdf is not installed", "tool_missing": True}
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "doc.pdf"
            pdf.write_bytes(simple_pdf())
            with mock.patch.object(check_pdf, "run", return_value=missing):
                report = check_pdf.analyze(pdf, Path(directory) / "out")
        self.assertIn(QPDF_AREA, areas(report))
        self.assertIn("PDF.INTAKE.QPDF_UNAVAILABLE", rules(report))

    def test_verapdf_entry_appears_when_validator_unavailable(self):
        unavailable = {
            "image": check_pdf.VERAPDF_IMAGE,
            "profile": check_pdf.VERAPDF_PROFILE,
            "classification": "experimental_technical_findings_only",
            "returncode": None,
            "tool_available": False,
            "stderr": "Docker is not installed, so the containerized veraPDF validator did not run.",
            "report_path": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "doc.pdf"
            pdf.write_bytes(simple_pdf())
            with mock.patch.object(check_pdf, "run_verapdf", return_value=unavailable):
                report = check_pdf.analyze(pdf, Path(directory) / "out")
        self.assertIn(VERAPDF_AREA, areas(report))
        self.assertIn("PDF.VERAPDF.UNAVAILABLE", rules(report))

    def test_tool_entries_absent_when_both_tools_available(self):
        ok = {"command": ["tool"], "returncode": 0, "stdout": "tool ok", "stderr": ""}
        available = {
            "image": check_pdf.VERAPDF_IMAGE,
            "profile": check_pdf.VERAPDF_PROFILE,
            "classification": "experimental_technical_findings_only",
            "returncode": 0,
            "stderr": "",
            "report_path": "/tmp/out/verapdf-ua1.json",
        }
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "doc.pdf"
            pdf.write_bytes(simple_pdf())
            with mock.patch.object(check_pdf, "run", return_value=ok), \
                 mock.patch.object(check_pdf, "run_verapdf", return_value=available):
                report = check_pdf.analyze(pdf, Path(directory) / "out")
        found = areas(report)
        self.assertNotIn(QPDF_AREA, found)
        self.assertNotIn(VERAPDF_AREA, found)
        self.assertLessEqual(STATIC_AREAS, found)


class PageAnchorTests(unittest.TestCase):
    def test_unnamed_link_finding_points_at_its_page(self):
        report = run_analyze(anchored_pdf())
        found = rules(report)
        self.assertIn("PDF.LINKS.NAME", found)
        self.assertEqual(found["PDF.LINKS.NAME"]["pages"], [2])

    def test_image_alternatives_finding_points_at_image_pages(self):
        report = run_analyze(anchored_pdf())
        found = rules(report)
        self.assertIn("PDF.IMAGES.ALTERNATIVES", found)
        self.assertEqual(found["PDF.IMAGES.ALTERNATIVES"]["pages"], [2])
        self.assertEqual(report["metadata"]["image_objects"], 1)

    def test_no_text_layer_finding_when_every_page_has_text(self):
        report = run_analyze(anchored_pdf())
        self.assertNotIn("PDF.TEXT_LAYER", rules(report))

    def test_text_layer_finding_points_at_textless_pages(self):
        report = run_analyze(partially_scanned_pdf())
        found = rules(report)
        self.assertIn("PDF.TEXT_LAYER", found)
        self.assertEqual(found["PDF.TEXT_LAYER"]["pages"], [2])
        self.assertIn("1 of 2", found["PDF.TEXT_LAYER"]["evidence"])

    def test_existing_count_key_stays_an_integer(self):
        report = run_analyze(partially_scanned_pdf())
        self.assertEqual(report["metadata"]["pages_without_extractable_text"], 1)
        self.assertIsInstance(report["metadata"]["pages_without_extractable_text"], int)

    def test_link_purpose_review_fires_with_pages_while_links_lack_names(self):
        report = run_analyze(anchored_pdf())
        found = rules(report)
        self.assertIn("PDF.LINKS.PURPOSE", found)
        self.assertEqual(found["PDF.LINKS.PURPOSE"]["pages"], [2])

    def test_link_purpose_review_silent_when_every_link_has_a_verified_name(self):
        report = run_analyze(named_link_pdf())
        found = rules(report)
        self.assertNotIn("PDF.LINKS.PURPOSE", found)
        self.assertNotIn("PDF.LINKS.NAME", found)
        strengths = {item["rule_id"] for item in report["strengths"]}
        self.assertIn("PDF.LINKS.NAME", strengths)

    def test_figure_alt_finding_points_at_the_figure_page(self):
        report = run_analyze(tagged_figure_pdf())
        found = rules(report)
        self.assertIn("PDF.IMAGES.ALT_MISSING", found)
        self.assertEqual(found["PDF.IMAGES.ALT_MISSING"]["pages"], [1])

    def test_findings_without_page_evidence_carry_no_pages_key(self):
        report = run_analyze(anchored_pdf())
        found = rules(report)
        self.assertIn("PDF.METADATA.TITLE", found)
        self.assertNotIn("pages", found["PDF.METADATA.TITLE"])


class OutcomeLanguageTests(unittest.TestCase):
    """check_pdf and every report it emits stay free of conformance-outcome claims."""

    BANNED = (
        "fully compliant",
        "guaranteed accessible",
        "passed accessibility",
        "certified accessible",
        "fully accessible",
    )

    def test_checker_source_carries_no_prohibited_outcome_phrases(self):
        source = Path(check_pdf.__file__).read_text(encoding="utf-8").lower()
        for phrase in self.BANNED:
            self.assertNotIn(phrase, source)

    def test_json_and_markdown_reports_carry_no_prohibited_outcome_phrases(self):
        import json as json_module

        for payload in (simple_pdf(), anchored_pdf(), partially_scanned_pdf()):
            report = run_analyze(payload)
            for rendered in (json_module.dumps(report, default=str), check_pdf.markdown(report)):
                lowered = rendered.lower()
                for phrase in self.BANNED:
                    self.assertNotIn(phrase, lowered)

    def test_claim_boundary_survives_into_both_report_formats(self):
        report = run_analyze(simple_pdf())
        self.assertIn("No conformance", report["claim_boundary"])
        self.assertIn(report["claim_boundary"], check_pdf.markdown(report))


if __name__ == "__main__":
    unittest.main()
