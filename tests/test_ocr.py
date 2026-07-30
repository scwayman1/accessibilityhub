import io
import shutil
import subprocess
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject, NumberObject

from tests.test_fixlab import build_pdf, run_analyze, untagged_pdf
from tina.kernel import ToolPermissionError
from tina.ocr import OcrRemediation
from tina.remedy import RemediationError

SCAN_LINES = [
    "Accessibility review notes",
    "This scanned page has no text layer.",
    "Route it for OCR assessment.",
]


def scan_pdf(lines: list[str] = SCAN_LINES) -> bytes:
    """One-page scan-like PDF: a single full-page image, no text layer."""
    image = Image.new("RGB", (1275, 1650), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=48)
    y = 200
    for line in lines:
        draw.text((120, y), line, fill="black", font=font)
        y += 120
    out = io.BytesIO()
    image.save(out, "PDF", resolution=150.0)
    return out.getvalue()


def mixed_pdf() -> bytes:
    """Page 1: scan image without text. Page 2: ordinary text page."""
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(scan_pdf()), strict=False))
    writer.append(PdfReader(io.BytesIO(untagged_pdf()), strict=False))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def two_scan_pdf() -> bytes:
    """Two scan-like pages, both eligible for OCR."""
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(scan_pdf()), strict=False))
    writer.append(PdfReader(io.BytesIO(scan_pdf()), strict=False))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def rotated_scan_pdf() -> bytes:
    """The scan fixture with an explicit /Rotate 90 on its only page."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(scan_pdf()), strict=False))
    writer.pages[0][NameObject("/Rotate")] = NumberObject(90)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _small_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, "JPEG")
    return buf.getvalue()


def image_no_contents_pdf() -> bytes:
    """A page holding an image XObject in /Resources but no /Contents at all."""
    jpg = _small_jpeg()
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /XObject << /Im0 4 0 R >> >> >>",
        b"<< /Type /XObject /Subtype /Image /Width 100 /Height 100 /ColorSpace /DeviceRGB "
        b"/BitsPerComponent 8 /Filter /DCTDecode /Length " + str(len(jpg)).encode() +
        b" >>\nstream\n" + jpg + b"\nendstream",
    ])


def degenerate_mediabox_pdf() -> bytes:
    """A scan-shaped page whose MediaBox has zero width."""
    jpg = _small_jpeg()
    stream = b"q 612 0 0 792 0 0 cm /Im0 Do Q"
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 0 792] /Contents 4 0 R "
        b"/Resources << /XObject << /Im0 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 100 /Height 100 /ColorSpace /DeviceRGB "
        b"/BitsPerComponent 8 /Filter /DCTDecode /Length " + str(len(jpg)).encode() +
        b" >>\nstream\n" + jpg + b"\nendstream",
    ])


def fake_tsv(rows: list[tuple[int, int, int, int, float, str]]) -> str:
    """Build tesseract-shaped TSV output from (left, top, width, height, conf, text) rows."""
    lines = ["level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"]
    for left, top, width, height, conf, text in rows:
        lines.append(f"5\t1\t1\t1\t1\t1\t{left}\t{top}\t{width}\t{height}\t{conf}\t{text}")
    return "\n".join(lines) + "\n"


def page_content_bytes(page) -> bytes:
    contents = page.raw_get("/Contents").get_object()
    if isinstance(contents, (ArrayObject, list)):
        return b"\n".join(part.get_object().get_data() for part in contents)
    return contents.get_data()


class RealEngineTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("tesseract"), "tesseract binary is not installed")
    def test_scanned_page_gains_a_reviewable_text_layer_end_to_end(self):
        payload = scan_pdf()
        before = run_analyze(payload)
        self.assertIn("PDF.TEXT_LAYER", {f["rule_id"] for f in before["findings"]})
        self.assertEqual(before["metadata"]["pages_without_extractable_text"], 1)

        engine = OcrRemediation.with_builtin_tools()
        fixed, report = engine.apply("scan.pdf", payload)

        text = PdfReader(io.BytesIO(fixed)).pages[0].extract_text()
        for expected in ("Accessibility", "review", "scanned", "OCR"):
            self.assertIn(expected, text)

        after = run_analyze(fixed)
        self.assertNotIn("PDF.TEXT_LAYER", {f["rule_id"] for f in after["findings"]})
        self.assertEqual(after["metadata"]["pages_without_extractable_text"], 0)

        # The scan image itself is untouched.
        img_before = list(PdfReader(io.BytesIO(payload)).pages[0].images)[0].data
        img_after = list(PdfReader(io.BytesIO(fixed)).pages[0].images)[0].data
        self.assertEqual(img_before, img_after)

        self.assertEqual(report["contract_version"], "tina-remediation-report/v1")
        self.assertEqual(report["actions"][0]["pages_ocred"], 1)
        self.assertGreater(report["actions"][0]["words_applied"], 0)

        words = report["actions"][0]["words"]
        self.assertGreater(len(words), 0)
        for entry in words:
            self.assertEqual(entry["page"], 1)
            self.assertIsInstance(entry["text"], str)
            self.assertIsInstance(entry["conf"], float)


class FakeRunnerTests(unittest.TestCase):
    def test_word_placement_math_produces_an_invisible_positioned_overlay(self):
        # 1275x1650 px image on a 612x792 pt page -> scale 0.48 on both axes.
        runner = lambda image_bytes: fake_tsv([(120, 200, 400, 50, 96.0, "Hello")])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        fixed, _ = engine.apply("scan.pdf", scan_pdf())

        page = PdfReader(io.BytesIO(fixed)).pages[0]
        content = page_content_bytes(page)
        self.assertIn(b"3 Tr", content)
        self.assertIn(b"(Hello) Tj", content)
        self.assertIn(b"/FOCR 24.00 Tf", content)  # 50 px * 0.48
        self.assertIn(b"1 0 0 1 57.60 672.00 Tm", content)  # x=120*0.48, y=792-250*0.48
        self.assertIn("Hello", page.extract_text())

    def test_confidence_floor_filters_low_confidence_words(self):
        runner = lambda image_bytes: fake_tsv([
            (120, 200, 400, 50, 95.0, "Solid"),
            (120, 400, 400, 50, 20.0, "Ghost"),
        ])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        fixed, report = engine.apply("scan.pdf", scan_pdf())

        text = PdfReader(io.BytesIO(fixed)).pages[0].extract_text()
        self.assertIn("Solid", text)
        self.assertNotIn("Ghost", text)
        action = report["actions"][0]
        self.assertEqual(action["words_applied"], 1)
        self.assertEqual(action["mean_confidence"], 95.0)
        self.assertEqual(action["confidence_floor"], 40.0)

    def test_mixed_document_skips_texted_pages_untouched(self):
        payload = mixed_pdf()
        texted_before = PdfReader(io.BytesIO(payload)).pages[1]
        text_before = texted_before.extract_text()
        self.assertTrue(text_before.strip())

        calls = []
        def runner(image_bytes):
            calls.append(image_bytes)
            return fake_tsv([(120, 200, 400, 50, 96.0, "Hello")])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        fixed, report = engine.apply("mixed.pdf", payload)

        self.assertEqual(len(calls), 1)  # OCR ran on the scan page only
        after = PdfReader(io.BytesIO(fixed))
        self.assertEqual(after.pages[1].extract_text(), text_before)
        self.assertEqual(len(list(after.pages[1].images)), len(list(texted_before.images)))
        action = report["actions"][0]
        self.assertEqual(action["pages_ocred"], 1)
        self.assertIn({"page": 2, "reason": "page already has extractable text"}, action["pages_skipped"])

    def test_document_with_no_eligible_pages_declines(self):
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=lambda b: fake_tsv([]))
        with self.assertRaises(RemediationError) as context:
            engine.apply("text.pdf", untagged_pdf())
        self.assertIn("no scanned pages found to OCR", str(context.exception))

    def test_zero_confident_words_declines_instead_of_writing_empty_layer(self):
        engine = OcrRemediation.with_builtin_tools(
            tesseract_runner=lambda b: fake_tsv([(120, 200, 400, 50, 10.0, "blur")])
        )
        with self.assertRaises(RemediationError) as context:
            engine.apply("scan.pdf", scan_pdf())
        self.assertIn("no legible text", str(context.exception))

    def test_missing_binary_declines_with_install_guidance(self):
        def runner(image_bytes):
            raise FileNotFoundError("No such file or directory: 'tesseract'")
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        with self.assertRaises(RemediationError) as context:
            engine.apply("scan.pdf", scan_pdf())
        message = str(context.exception)
        self.assertIn("The OCR engine (tesseract) is not installed", message)
        self.assertIn("Install tesseract", message)

    def test_mutation_requires_the_ocr_permission(self):
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=lambda b: fake_tsv([]))
        with self.assertRaises(ToolPermissionError):
            engine.gateway.execute("apply_text_layer", {"payload": scan_pdf()}, set())

    def test_provenance_is_recorded_as_ocr_generated_with_review_note(self):
        runner = lambda image_bytes: fake_tsv([(120, 200, 400, 50, 96.0, "Hello")])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        _, report = engine.apply("scan.pdf", scan_pdf())
        action = report["actions"][0]
        self.assertEqual(action["rule_id"], "PDF.TEXT_LAYER")
        self.assertEqual(action["action"], "apply_ocr_text_layer")
        self.assertEqual(action["provenance"], "ocr_generated")
        self.assertIn("human must review", action["note"])
        self.assertIn("human must review", report["claim_boundary"])
        self.assertTrue(report["mutates_document"])
        self.assertTrue(report["source_sha256"].startswith("sha256:"))
        self.assertTrue(report["remediated_sha256"].startswith("sha256:"))
        self.assertNotEqual(report["source_sha256"], report["remediated_sha256"])

    def test_injection_shaped_words_are_escaped_and_survive_reparse(self):
        runner = lambda image_bytes: fake_tsv([
            (120, 200, 150, 50, 96.0, "a(b"),
            (300, 200, 150, 50, 96.0, "c)d"),
            (120, 300, 150, 50, 96.0, "e\\f"),
            (300, 300, 150, 50, 96.0, ")\\("),
            (120, 400, 300, 50, 96.0, "x) Tj ET Q (y"),
            (120, 500, 150, 50, 96.0, "café"),
        ])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        fixed, report = engine.apply("scan.pdf", scan_pdf())

        # The output must re-parse and extract without raising, with every word
        # intact — no operator injection, no mangling of latin-1 characters.
        page = PdfReader(io.BytesIO(fixed), strict=False).pages[0]
        text = page.extract_text()
        for word in ("a(b", "c)d", "e\\f", ")\\(", "x) Tj ET Q (y", "café"):
            self.assertIn(word, text)
        self.assertEqual(report["actions"][0]["words_applied"], 6)

    def test_malformed_tsv_rows_are_ignored_without_crashing(self):
        def runner(image_bytes):
            return (
                "level\tpage\n"
                "5\t1\t1\t1\t1\t1\t10\t10\t10\t10\t95.0\t\n"          # empty text
                "5\t1\t1\t1\t1\t1\t10\t10\t10\t95.0\tmissingcol\n"      # 11 columns
                "5\t1\t1\t1\t1\t1\tx\ty\tz\tw\tabc\tbadnums\n"          # non-numeric
                "garbage line without tabs\n"
                "4\t1\t1\t1\t1\t1\t10\t10\t10\t10\t95.0\tline-level\n"  # not level 5
                "5\t1\t1\t1\t1\t1\t120\t200\t400\t50\t96.0\tSurvivor\n"
            )
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        fixed, report = engine.apply("scan.pdf", scan_pdf())
        self.assertEqual(report["actions"][0]["words_applied"], 1)
        self.assertIn("Survivor", PdfReader(io.BytesIO(fixed)).pages[0].extract_text())

    def test_applying_ocr_to_its_own_output_declines(self):
        runner = lambda image_bytes: fake_tsv([(120, 200, 400, 50, 96.0, "Hello")])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        fixed, _ = engine.apply("scan.pdf", scan_pdf())
        with self.assertRaises(RemediationError) as context:
            engine.apply("scan.pdf", fixed)
        self.assertIn("no scanned pages found to OCR", str(context.exception))

    def test_rotated_scan_page_declines_instead_of_misplacing_text(self):
        runner = lambda image_bytes: fake_tsv([(120, 200, 400, 50, 96.0, "Hello")])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        with self.assertRaises(RemediationError) as context:
            engine.apply("rotated.pdf", rotated_scan_pdf())
        self.assertIn("no scanned pages found to OCR", str(context.exception))

    def test_page_with_image_but_no_content_stream_declines_not_crashes(self):
        # Regression: this page used to pass eligibility and then crash with a
        # raw KeyError('/Contents') while attaching the overlay.
        runner = lambda image_bytes: fake_tsv([(10, 10, 50, 20, 96.0, "ghost")])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        with self.assertRaises(RemediationError) as context:
            engine.apply("nocontents.pdf", image_no_contents_pdf())
        self.assertIn("no scanned pages found to OCR", str(context.exception))

    def test_degenerate_mediabox_page_declines_instead_of_collapsing_text(self):
        # Regression: a zero-width MediaBox used to yield scale 0, silently
        # stacking every word at x=0 instead of declining.
        runner = lambda image_bytes: fake_tsv([(10, 10, 50, 20, 96.0, "ghost")])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        with self.assertRaises(RemediationError) as context:
            engine.apply("degenerate.pdf", degenerate_mediabox_pdf())
        self.assertIn("no scanned pages found to OCR", str(context.exception))

    def test_engine_timeout_declines_with_routing_not_raw_exception(self):
        # Regression: subprocess.TimeoutExpired used to escape untranslated.
        def runner(image_bytes):
            raise subprocess.TimeoutExpired(cmd=["tesseract"], timeout=120)
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        with self.assertRaises(RemediationError) as context:
            engine.apply("scan.pdf", scan_pdf())
        message = str(context.exception)
        self.assertIn("timed out", message)
        self.assertIn("HTML working copy", message)

    def test_module_and_report_strings_carry_no_conformance_claims(self):
        forbidden = ("fully compliant", "guaranteed accessible", "passed accessibility",
                     "certified accessible", "fully accessible")
        source = (Path(__file__).resolve().parent.parent / "tina" / "ocr.py").read_text(encoding="utf-8").lower()
        for phrase in forbidden:
            self.assertNotIn(phrase, source)
        runner = lambda image_bytes: fake_tsv([(120, 200, 400, 50, 96.0, "Hello")])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        _, report = engine.apply("scan.pdf", scan_pdf())
        import json
        flattened = json.dumps(report, default=str).lower()
        for phrase in forbidden:
            self.assertNotIn(phrase, flattened)

    def test_words_are_surfaced_for_review_with_pages_and_confidence(self):
        pages_tsv = [
            fake_tsv([(120, 200, 400, 50, 96.0, "Alpha"),
                      (540, 200, 200, 50, 88.5, "Beta")]),
            fake_tsv([(120, 200, 400, 50, 72.0, "Gamma")]),
        ]
        calls = []
        def runner(image_bytes):
            calls.append(image_bytes)
            return pages_tsv[len(calls) - 1]
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        _, report = engine.apply("two-scans.pdf", two_scan_pdf())

        action = report["actions"][0]
        self.assertEqual(action["words"], [
            {"page": 1, "text": "Alpha", "conf": 96.0},
            {"page": 1, "text": "Beta", "conf": 88.5},
            {"page": 2, "text": "Gamma", "conf": 72.0},
        ])
        self.assertFalse(action["words_truncated"])
        import json
        json.dumps(action["words"])  # must be JSON-safe

    def test_dropped_words_do_not_appear_in_the_review_list(self):
        runner = lambda image_bytes: fake_tsv([
            (120, 200, 400, 50, 96.0, "Kept"),
            (120, 400, 400, 50, 10.0, "Ghost"),   # below the confidence floor
            (540, 200, 200, 50, 96.0, "€42"),     # non latin-1 encodable
        ])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        _, report = engine.apply("scan.pdf", scan_pdf())
        action = report["actions"][0]
        surfaced = [entry["text"] for entry in action["words"]]
        self.assertEqual(surfaced, ["Kept"])
        self.assertNotIn("Ghost", surfaced)
        self.assertNotIn("€42", surfaced)
        self.assertFalse(action["words_truncated"])

    def test_words_list_is_capped_at_400_with_truncation_flag(self):
        rows = [(10 + (i % 50) * 25, 10 + (i // 50) * 30, 20, 20, 90.0, f"w{i}")
                for i in range(450)]
        engine = OcrRemediation.with_builtin_tools(
            tesseract_runner=lambda b: fake_tsv(rows)
        )
        _, report = engine.apply("scan.pdf", scan_pdf())
        action = report["actions"][0]
        self.assertEqual(action["words_applied"], 450)
        self.assertEqual(len(action["words"]), 400)
        self.assertTrue(action["words_truncated"])
        # The cap keeps the first words in reading order, not an arbitrary slice.
        self.assertEqual(action["words"][0]["text"], "w0")
        self.assertEqual(action["words"][399]["text"], "w399")

    def test_words_list_of_exactly_400_is_not_flagged_truncated(self):
        rows = [(10 + (i % 50) * 25, 10 + (i // 50) * 30, 20, 20, 90.0, f"w{i}")
                for i in range(400)]
        engine = OcrRemediation.with_builtin_tools(
            tesseract_runner=lambda b: fake_tsv(rows)
        )
        _, report = engine.apply("scan.pdf", scan_pdf())
        action = report["actions"][0]
        self.assertEqual(len(action["words"]), 400)
        self.assertFalse(action["words_truncated"])

    def test_non_latin1_words_are_dropped_and_counted_not_mangled(self):
        runner = lambda image_bytes: fake_tsv([
            (120, 200, 400, 50, 96.0, "Total"),
            (540, 200, 200, 50, 96.0, "€42"),  # euro sign is outside latin-1
        ])
        engine = OcrRemediation.with_builtin_tools(tesseract_runner=runner)
        fixed, report = engine.apply("scan.pdf", scan_pdf())
        action = report["actions"][0]
        self.assertEqual(action["words_applied"], 1)
        self.assertEqual(action["words_dropped_non_encodable"], 1)
        self.assertIn("Total", PdfReader(io.BytesIO(fixed)).pages[0].extract_text())


if __name__ == "__main__":
    unittest.main()
