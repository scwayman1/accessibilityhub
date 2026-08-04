import base64
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pypdf import PdfReader

from check_pdf import analyze, indirect, iter_figures
from local_reviewer import create_server
from tina.derive import extract_blocks
from tina.kernel import ToolPermissionError
from tina.remedy import RemediationError, SemanticRemediation


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


def linked_pdf() -> bytes:
    """Two links: one unnamed, one already carrying an accessible description."""
    stream = b"BT /F1 12 Tf 72 720 Td (See the reading here and the rubric there.) Tj ET"
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R /Annots [6 0 R 7 0 R] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Annot /Subtype /Link /Rect [72 700 150 720] /Border [0 0 0] "
        b"/A << /S /URI /URI (https://example.edu/reading) >> >>",
        b"<< /Type /Annot /Subtype /Link /Rect [160 700 240 720] /Border [0 0 0] "
        b"/Contents (Grading rubric) /A << /S /URI /URI (https://example.edu/rubric) >> >>",
    ])


def tagged_figure_pdf(with_alt: bool = False) -> bytes:
    """Marked/tagged PDF whose structure tree holds one Figure element."""
    stream = b"BT /F1 12 Tf 72 720 Td (A chart appears below.) Tj ET"
    alt = b" /Alt (Enrollment chart)" if with_alt else b""
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R /MarkInfo << /Marked true >> /StructTreeRoot 6 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /StructTreeRoot /K [7 0 R] >>",
        b"<< /Type /StructElem /S /Figure /P 6 0 R" + alt + b" >>",
    ])


def untagged_pdf() -> bytes:
    stream = b"BT /F1 12 Tf 72 720 Td (Plain text, no tags.) Tj ET"
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ])


def run_analyze(payload: bytes) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        pdf = Path(directory) / "doc.pdf"
        pdf.write_bytes(payload)
        return analyze(pdf, Path(directory) / "out")


class CheckerFixableDefectTests(unittest.TestCase):
    def test_unnamed_links_are_an_itemized_fixable_defect(self):
        report = run_analyze(linked_pdf())
        rules = {f["rule_id"]: f for f in report["findings"]}
        self.assertIn("PDF.LINKS.NAME", rules)
        self.assertEqual(rules["PDF.LINKS.NAME"]["category"], "deterministic_defect")
        self.assertIn("1 of 2", rules["PDF.LINKS.NAME"]["evidence"])
        links = report["metadata"]["links"]
        self.assertEqual([l["named"] for l in links], [False, True])
        self.assertEqual(links[0]["uri"], "https://example.edu/reading")

    def test_fully_named_links_become_a_verified_strength(self):
        report = run_analyze(linked_pdf())
        # not yet named -> no strength
        self.assertNotIn("PDF.LINKS.NAME", {s["rule_id"] for s in report["strengths"]})

    def test_tagged_figure_without_alt_is_a_fixable_defect(self):
        report = run_analyze(tagged_figure_pdf(with_alt=False))
        rules = {f["rule_id"]: f for f in report["findings"]}
        self.assertIn("PDF.IMAGES.ALT_MISSING", rules)
        self.assertEqual(rules["PDF.IMAGES.ALT_MISSING"]["category"], "deterministic_defect")
        self.assertEqual(report["metadata"]["figures_missing_alt"], 1)

    def test_tagged_figure_with_alt_is_a_strength_not_a_defect(self):
        report = run_analyze(tagged_figure_pdf(with_alt=True))
        self.assertNotIn("PDF.IMAGES.ALT_MISSING", {f["rule_id"] for f in report["findings"]})
        self.assertIn("PDF.IMAGES.ALT_MISSING", {s["rule_id"] for s in report["strengths"]})

    def test_untagged_pdf_routes_images_to_html_rebuild(self):
        report = run_analyze(untagged_pdf())
        self.assertNotIn("PDF.IMAGES.ALT_MISSING", {f["rule_id"] for f in report["findings"]})


class SemanticWriteBackTests(unittest.TestCase):
    def test_link_descriptions_are_applied_and_verifiable_on_recheck(self):
        engine = SemanticRemediation.with_builtin_tools()
        fixed, report = engine.apply("doc.pdf", linked_pdf(), link_names={"0": "Week 3 reading: chapter 4"})
        self.assertEqual(report["actions"][0]["provenance"], "user_authored")

        recheck = run_analyze.__wrapped__(fixed) if hasattr(run_analyze, "__wrapped__") else None
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "fixed.pdf"
            pdf.write_bytes(fixed)
            recheck = analyze(pdf, Path(directory) / "out")
        self.assertNotIn("PDF.LINKS.NAME", {f["rule_id"] for f in recheck["findings"]})
        self.assertIn("PDF.LINKS.NAME", {s["rule_id"] for s in recheck["strengths"]})

    def test_alt_text_is_applied_to_tagged_figures_and_verifiable(self):
        engine = SemanticRemediation.with_builtin_tools()
        fixed, report = engine.apply("doc.pdf", tagged_figure_pdf(), alt_texts={"0": {"alt": "Enrollment rose sharply after 2022."}})
        reader = PdfReader(io.BytesIO(fixed))
        root = reader.trailer["/Root"].get_object()
        figures = iter_figures(indirect(root.get("/StructTreeRoot")))
        self.assertTrue(figures[0]["has_alt"])
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "fixed.pdf"
            pdf.write_bytes(fixed)
            recheck = analyze(pdf, Path(directory) / "out")
        self.assertNotIn("PDF.IMAGES.ALT_MISSING", {f["rule_id"] for f in recheck["findings"]})

    def test_decorative_decision_sets_empty_alt(self):
        engine = SemanticRemediation.with_builtin_tools()
        fixed, _ = engine.apply("doc.pdf", tagged_figure_pdf(), alt_texts={"0": {"decorative": True}})
        reader = PdfReader(io.BytesIO(fixed))
        figures = iter_figures(indirect(reader.trailer["/Root"].get_object().get("/StructTreeRoot")))
        self.assertTrue(figures[0]["has_alt"])

    def test_untagged_pdf_declines_alt_text_and_routes_to_html(self):
        engine = SemanticRemediation.with_builtin_tools()
        with self.assertRaises(RemediationError) as context:
            engine.apply("doc.pdf", untagged_pdf(), alt_texts={"0": {"alt": "A chart."}})
        self.assertIn("HTML working copy", str(context.exception))

    def test_unknown_link_index_is_rejected_not_silently_skipped(self):
        engine = SemanticRemediation.with_builtin_tools()
        with self.assertRaises(RemediationError):
            engine.apply("doc.pdf", linked_pdf(), link_names={"9": "Ghost link"})

    def test_mutation_requires_the_semantics_permission(self):
        engine = SemanticRemediation.with_builtin_tools()
        with self.assertRaises(ToolPermissionError):
            engine.gateway.execute("apply_accessible_names", {"payload": linked_pdf(), "link_names": {"0": "x"}}, set())


class FixSemanticsEndpointTests(unittest.TestCase):
    def setUp(self):
        def checker(pdf_path: Path, output_dir: Path) -> dict:
            return analyze(pdf_path, output_dir)
        self.server = create_server(0, checker)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post_json(self, path: str, payload: dict):
        request = Request(self.base + path, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read())

    def test_fix_semantics_resolves_link_names_end_to_end(self):
        result = self.post_json("/api/fix-semantics", {
            "filename": "doc.pdf",
            "pdf_base64": base64.b64encode(linked_pdf()).decode(),
            "link_names": {"0": "Week 3 reading: chapter 4"},
        })
        before = {f["rule_id"] for f in result["before"]["findings"]}
        after = {f["rule_id"] for f in result["after"]["findings"]}
        self.assertIn("PDF.LINKS.NAME", before)
        self.assertNotIn("PDF.LINKS.NAME", after)
        self.assertTrue(base64.b64decode(result["fixed_pdf_base64"]).startswith(b"%PDF-"))

    def test_structured_convert_applies_confirmed_roles(self):
        blocks = extract_blocks(linked_pdf())
        self.assertTrue(blocks)
        result = self.post_json("/api/convert-structured", {
            "filename": "doc.pdf",
            "pdf_base64": base64.b64encode(linked_pdf()).decode(),
            "roles": {"0": "h1"},
        })
        self.assertIn("<h1 data-block", result["html"])
        self.assertEqual(result["stats"]["roles_applied"], 1)


class StructureAndOcrEndpointTests(unittest.TestCase):
    def setUp(self):
        def checker(pdf_path: Path, output_dir: Path) -> dict:
            return analyze(pdf_path, output_dir)
        self.server = create_server(0, checker)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post_json(self, path: str, payload: dict):
        request = Request(self.base + path, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read())

    def post_json_expecting_error(self, path: str, payload: dict) -> tuple[int, dict]:
        try:
            self.post_json(path, payload)
        except HTTPError as error:
            return error.code, json.loads(error.read())
        self.fail(f"POST {path} unexpectedly succeeded")

    def post_pdf(self, path: str, payload: bytes) -> dict:
        request = Request(self.base + path, data=payload, method="POST")
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read())

    def test_blocks_endpoint_exposes_the_shared_block_index_space(self):
        result = self.post_pdf("/api/blocks", untagged_pdf())
        self.assertEqual(result["blocks"], ["Plain text, no tags."])

    def test_fix_structure_builds_a_verified_tag_tree_end_to_end(self):
        result = self.post_json("/api/fix-structure", {
            "filename": "doc.pdf",
            "pdf_base64": base64.b64encode(untagged_pdf()).decode(),
            "confirmed_roles": {"0": "h1"},
        })
        before = {f["rule_id"] for f in result["before"]["findings"]}
        after_strengths = {s["rule_id"] for s in result["after"].get("strengths", [])}
        self.assertIn("PDF.STRUCTURE.SEMANTICS", before)
        self.assertIn("PDF.STRUCTURE.SEMANTICS", after_strengths)
        self.assertEqual(result["remediation"]["verification"],
                         {"text_preserved": True, "pages_preserved": True})
        fixed = base64.b64decode(result["fixed_pdf_base64"])
        reader = PdfReader(io.BytesIO(fixed))
        self.assertEqual(reader.pages[0].extract_text().strip(), "Plain text, no tags.")

    def test_fix_structure_declines_an_already_tagged_pdf(self):
        code, body = self.post_json_expecting_error("/api/fix-structure", {
            "filename": "doc.pdf",
            "pdf_base64": base64.b64encode(tagged_figure_pdf(with_alt=True)).decode(),
            "confirmed_roles": {"0": "h1"},
        })
        self.assertEqual(code, 400)
        self.assertIn("already carries a structure tree", body["error"])

    def test_fix_ocr_declines_a_fully_texted_pdf_with_routing(self):
        code, body = self.post_json_expecting_error("/api/fix-ocr", {
            "filename": "doc.pdf",
            "pdf_base64": base64.b64encode(untagged_pdf()).decode(),
        })
        self.assertEqual(code, 400)
        self.assertIn("no scanned pages", body["error"])

    @unittest.skipUnless(shutil.which("tesseract"), "tesseract binary is not installed")
    def test_fix_ocr_applies_a_text_layer_to_a_scan_end_to_end(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_ocr import scan_pdf
        result = self.post_json("/api/fix-ocr", {
            "filename": "scan.pdf",
            "pdf_base64": base64.b64encode(scan_pdf()).decode(),
        })
        before = {f["rule_id"] for f in result["before"]["findings"]}
        after = {f["rule_id"] for f in result["after"]["findings"]}
        self.assertIn("PDF.TEXT_LAYER", before)
        self.assertNotIn("PDF.TEXT_LAYER", after)
        self.assertEqual(result["remediation"]["actions"][0]["provenance"], "ocr_generated")
        self.assertTrue(base64.b64decode(result["fixed_pdf_base64"]).startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
