import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pypdf import PdfWriter

import check_pdf


def _write(pdf_bytes: bytes, directory: str, name: str = "doc.pdf") -> Path:
    path = Path(directory) / name
    path.write_bytes(pdf_bytes)
    return path


def encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def plain_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _rule_ids(report: dict) -> set:
    return {item["rule_id"] for item in report["findings"]}


class VeraPdfAvailabilityTests(unittest.TestCase):
    """The UA-1 advisory must never claim a report exists when the validator did not run."""

    def test_missing_validator_emits_tool_failure_not_advisory(self):
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
            pdf = _write(plain_pdf(), directory)
            with mock.patch.object(check_pdf, "run_verapdf", return_value=unavailable):
                report = check_pdf.analyze(pdf, Path(directory) / "out")
        rules = _rule_ids(report)
        self.assertIn("PDF.VERAPDF.UNAVAILABLE", rules)
        self.assertNotIn("PDF.VERAPDF.UA1", rules)
        unavailable_finding = next(f for f in report["findings"] if f["rule_id"] == "PDF.VERAPDF.UNAVAILABLE")
        self.assertEqual(unavailable_finding["category"], "tool_failure_or_unsupported")

    def test_available_validator_still_emits_advisory(self):
        available = {
            "image": check_pdf.VERAPDF_IMAGE,
            "profile": check_pdf.VERAPDF_PROFILE,
            "classification": "experimental_technical_findings_only",
            "returncode": 0,
            "stderr": "",
            "report_path": "/tmp/out/verapdf-ua1.json",
        }
        with tempfile.TemporaryDirectory() as directory:
            pdf = _write(plain_pdf(), directory)
            with mock.patch.object(check_pdf, "run_verapdf", return_value=available):
                report = check_pdf.analyze(pdf, Path(directory) / "out")
        rules = _rule_ids(report)
        self.assertIn("PDF.VERAPDF.UA1", rules)
        self.assertNotIn("PDF.VERAPDF.UNAVAILABLE", rules)


class EncryptedWithoutQpdfTests(unittest.TestCase):
    """An encrypted PDF must degrade to a blocking-intake report even when qpdf is absent."""

    def test_encrypted_pdf_does_not_crash_when_qpdf_unavailable(self):
        missing = {"command": ["qpdf"], "returncode": None, "stdout": "", "stderr": "qpdf is not installed", "tool_missing": True}

        with tempfile.TemporaryDirectory() as directory:
            pdf = _write(encrypted_pdf(), directory)
            # Simulate qpdf entirely absent so the qpdf-derived `encrypted` flag is False;
            # analyze() must rely on pypdf's own is_encrypted verdict instead of erroring.
            with mock.patch.object(check_pdf, "run", return_value=missing):
                report = check_pdf.analyze(pdf, Path(directory) / "out")

        rules = _rule_ids(report)
        self.assertIn("PDF.INTAKE.QPDF_UNAVAILABLE", rules)
        self.assertIn("PDF.INTAKE.ENCRYPTED", rules)
        # Page-loop findings must not appear: we never entered page inspection.
        self.assertFalse(rules & {"PDF.TEXT_LAYER", "PDF.IMAGES.ALTERNATIVES", "PDF.LINKS.PURPOSE"})
        self.assertEqual(report["metadata"], {})


class WorkbenchStateResetTests(unittest.TestCase):
    """The receipt/evidence trail must not leak a previous document into a new one."""

    def setUp(self):
        self.source = Path("local_reviewer.html").read_text()

    def test_reset_clears_document_scoped_state(self):
        self.assertIn("function resetDocumentState()", self.source)
        reset_body = self.source.split("function resetDocumentState()", 1)[1].split("}", 1)[0]
        for cleared in ("lastReport=null", "lastFix=null", "attestations=[]", "fixedBlob=null"):
            self.assertIn(cleared, reset_body, f"resetDocumentState must clear {cleared}")

    def test_choosing_a_new_pdf_invokes_the_reset(self):
        change_handler = self.source.split("input.addEventListener('change'", 1)[1].split("});", 1)[0]
        self.assertIn("resetDocumentState()", change_handler)


if __name__ == "__main__":
    unittest.main()
