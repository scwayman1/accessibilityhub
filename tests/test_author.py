"""Produced files: the document model, accessible HTML, and the tagged PDF."""
import base64
import io
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

from pypdf import PdfReader, PdfWriter

from tests.test_html_draft import image_pdf, text_pdf
from tina.derive import build_docmodel
from tina.docmodel import (
    DOCMODEL_VERSION,
    DocModelError,
    apply_figure_decisions,
    pending_decisions,
    require_valid,
    validate_docmodel,
)

try:
    import weasyprint  # noqa: F401
    HAVE_WEASYPRINT = True
except ImportError:  # pragma: no cover - CI installs it
    HAVE_WEASYPRINT = False

PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="


def mixed_pdf() -> bytes:
    """Page 1: titled text. Page 2: one image."""
    writer = PdfWriter()
    for payload in (text_pdf("Week 3 Outline", title="Week 3"), image_pdf()):
        for page in PdfReader(io.BytesIO(payload)).pages:
            writer.add_page(page)
    writer.add_metadata({"/Title": "Week 3"})
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def full_model() -> dict:
    return {
        "version": DOCMODEL_VERSION,
        "title": "Week 3 syllabus",
        "language": "en-US",
        "source_sha256": "sha256:" + "a" * 64,
        "blocks": [
            {"kind": "heading", "level": 1, "text": "Week 3 syllabus"},
            {"kind": "paragraph", "text": "Read chapter two before class."},
            {"kind": "heading", "level": 2, "text": "Grading"},
            {"kind": "list", "ordered": True, "items": ["Essay", "Quiz"]},
            {"kind": "table", "caption": "Weights", "header_rows": 1, "rows": [["Item", "Weight"], ["Essay", "40%"], ["Quiz", "60%"]]},
            {"kind": "figure", "figure": 1, "page": 2, "mime": "image/png", "base64": PNG_1PX,
             "alt": "Bar chart: essays outweigh quizzes", "decorative": False, "caption": "Figure 1"},
            {"kind": "figure", "figure": 2, "page": 2, "mime": "image/png", "base64": PNG_1PX,
             "alt": None, "decorative": True, "caption": None},
        ],
    }


def struct_tags(pdf_bytes: bytes) -> list[tuple[str, str | None]]:
    root = PdfReader(io.BytesIO(pdf_bytes)).trailer["/Root"]
    tags: list[tuple[str, str | None]] = []

    def walk(node):
        node = node.get_object() if hasattr(node, "get_object") else node
        if isinstance(node, dict) and "/S" in node:
            tags.append((str(node["/S"]), str(node["/Alt"]) if "/Alt" in node else None))
            kids = node.get("/K")
            for kid in kids if isinstance(kids, list) else ([kids] if kids is not None else []):
                walk(kid)

    kids = root["/StructTreeRoot"].get_object()["/K"]
    for kid in kids if isinstance(kids, list) else [kids]:
        walk(kid)
    return tags


class DocModelTests(unittest.TestCase):
    def test_complete_model_is_valid(self):
        self.assertEqual(validate_docmodel(full_model()), [])

    def test_undecided_figure_blocks_the_model(self):
        model = full_model()
        model["blocks"][5]["alt"] = None
        problems = validate_docmodel(model)
        self.assertTrue(any("needs a description or a decorative decision" in p for p in problems))
        self.assertEqual(pending_decisions(model), [{"block": 5, "figure": 1, "page": 2}])
        with self.assertRaises(DocModelError):
            require_valid(model)

    def test_described_and_decorative_at_once_is_rejected(self):
        model = full_model()
        model["blocks"][6]["alt"] = "A border"
        self.assertTrue(any("choose one" in p for p in validate_docmodel(model)))

    def test_title_language_and_table_headers_are_required(self):
        model = full_model()
        model["title"] = " "
        model["language"] = "english please"
        model["blocks"][4]["header_rows"] = 0
        problems = " ".join(validate_docmodel(model))
        self.assertIn("title is required", problems)
        self.assertIn("language", problems)
        self.assertIn("header row", problems)

    def test_build_docmodel_uses_confirmed_roles_and_never_describes_images(self):
        model = build_docmodel(mixed_pdf(), roles={"0": "h1"}, language="en-US")
        self.assertEqual(model["title"], "Week 3")  # from the source metadata
        self.assertEqual(model["blocks"][0], {"kind": "heading", "level": 1, "text": "Week 3 Outline", "page": 1})
        figure = model["blocks"][1]
        self.assertEqual((figure["kind"], figure["figure"], figure["page"]), ("figure", 1, 2))
        self.assertIsNone(figure["alt"])
        self.assertFalse(figure["decorative"])
        self.assertTrue(model["source_sha256"].startswith("sha256:"))

    def test_unconfirmed_blocks_stay_paragraphs(self):
        model = build_docmodel(text_pdf("Hello class"))
        self.assertEqual(model["blocks"][0]["kind"], "paragraph")
        self.assertEqual(model["title"], "")
        self.assertEqual(model["language"], "")

    def test_figure_decisions_are_recorded_not_authored(self):
        model = build_docmodel(mixed_pdf(), language="en-US")
        described = apply_figure_decisions(model, {1: {"alt": "  A blue   sample swatch "}})
        self.assertEqual(described["blocks"][1]["alt"], "A blue sample swatch")
        decorative = apply_figure_decisions(model, {"1": {"decorative": True}})
        self.assertTrue(decorative["blocks"][1]["decorative"])
        self.assertIsNone(decorative["blocks"][1]["alt"])
        self.assertIsNone(model["blocks"][1]["alt"])  # the input model is not mutated


class RenderHtmlTests(unittest.TestCase):
    def test_semantic_html(self):
        from tina.author import render_html

        page = render_html(full_model(), {"improvements": ["Title & language"]})
        self.assertIn('<html lang="en-US">', page)
        self.assertIn("<title>Week 3 syllabus</title>", page)
        self.assertEqual(page.count("<main>"), 1)
        self.assertEqual(page.count("<h1>"), 1)  # first block is already the h1
        self.assertIn("<ol><li>Essay</li><li>Quiz</li></ol>", page)
        self.assertIn('<th scope="col">Item</th>', page)
        self.assertIn('alt="Bar chart: essays outweigh quizzes"', page)
        self.assertIn('alt=""', page)  # the decorative image
        self.assertIn("About this copy", page)
        self.assertIn("not a certification", page)
        self.assertIn("<code>aaaaaaaaaaaa</code>", page)

    def test_title_becomes_h1_when_the_document_has_none(self):
        from tina.author import render_html

        model = full_model()
        model["blocks"] = model["blocks"][1:2]
        self.assertIn("<h1>Week 3 syllabus</h1>", render_html(model))

    def test_text_is_escaped(self):
        from tina.author import render_html

        model = full_model()
        model["blocks"][1]["text"] = "<script>alert(1)</script>"
        page = render_html(model)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)


@unittest.skipUnless(HAVE_WEASYPRINT, "WeasyPrint is not installed")
class RenderPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tina.author import render_pdf

        cls.pdf = render_pdf(full_model())
        cls.reader = PdfReader(io.BytesIO(cls.pdf))

    def test_catalog_marks_a_tagged_titled_language_set_document(self):
        root = self.reader.trailer["/Root"]
        self.assertIn("/StructTreeRoot", root)
        self.assertTrue(root["/MarkInfo"]["/Marked"])
        self.assertEqual(str(root["/Lang"]), "en-US")
        self.assertTrue(root["/ViewerPreferences"]["/DisplayDocTitle"])
        self.assertEqual(self.reader.metadata.title, "Week 3 syllabus")

    def test_structure_tree_carries_headings_lists_tables_and_alt(self):
        tags = struct_tags(self.pdf)
        names = [name for name, _ in tags]
        for expected in ("/H1", "/H2", "/P", "/L", "/LI", "/Table", "/TH", "/TD", "/Figure"):
            self.assertIn(expected, names)
        figures = [alt for name, alt in tags if name == "/Figure"]
        # Only the described image is a tagged figure; decorative is an artifact.
        self.assertEqual(figures, ["Bar chart: essays outweigh quizzes"])

    def test_every_font_is_embedded(self):
        for page in self.reader.pages:
            for font in page["/Resources"]["/Font"].values():
                font = font.get_object()
                descriptor = font.get("/FontDescriptor") or font["/DescendantFonts"][0].get_object()["/FontDescriptor"]
                keys = set(descriptor.get_object().keys())
                self.assertTrue(keys & {"/FontFile", "/FontFile2", "/FontFile3"}, font.get("/BaseFont"))

    def test_tables_carry_a_summary_from_their_caption(self):
        root = self.reader.trailer["/Root"]["/StructTreeRoot"].get_object()
        summaries = []

        def walk(node):
            node = node.get_object() if hasattr(node, "get_object") else node
            if isinstance(node, dict) and "/S" in node:
                if node["/S"] == "/Table":
                    summaries.append(str(node["/A"]["/Summary"]))
                kids = node.get("/K")
                for kid in kids if isinstance(kids, list) else ([kids] if kids is not None else []):
                    walk(kid)

        walk(root["/K"] if not isinstance(root["/K"], list) else root["/K"][0])
        self.assertEqual(summaries, ["Weights"])

    def test_pdfcraft_second_opinion_finds_no_failures_in_our_output(self):
        from tina.pdfcraft import PdfCraft

        craft = PdfCraft.with_builtin_tools()
        if not craft.available:
            self.skipTest("pdfcraft-cli is not installed")
        result = craft.check(self.pdf)
        failed = [(item["rule"], item["findings"]) for item in result["results"] if item["status"] == "failed"]
        self.assertEqual(failed, [])

    def test_decorative_image_is_drawn_as_an_artifact(self):
        contents = b"".join(page.get_contents().get_data() for page in self.reader.pages)
        self.assertIn(b"/Artifact", contents)

    def test_renderer_never_fetches_remote_resources(self):
        from tina.author import render_pdf

        model = full_model()
        model["blocks"][1]["text"] = "safe"
        import tina.author as author

        original = author.render_html
        author.render_html = lambda *a, **k: original(*a, **k).replace(
            "</main>", '<img alt="x" src="https://example.invalid/tracker.png"></main>')
        try:
            with self.assertRaises(RuntimeError) as raised:
                render_pdf(model)
            self.assertIn("outside the document", str(raised.exception))
        finally:
            author.render_html = original


@unittest.skipUnless(HAVE_WEASYPRINT, "WeasyPrint is not installed")
class ProducerTests(unittest.TestCase):
    def test_producer_runs_behind_the_gateway_and_rechecks_its_own_pdf(self):
        from tina.author import AccessiblePackageProducer

        model = apply_figure_decisions(
            build_docmodel(mixed_pdf(), roles={"0": "h1"}, language="en-US"),
            {1: {"alt": "Blue rectangle used as a color sample"}},
        )
        package = AccessiblePackageProducer.with_builtin_tools().produce(model)
        self.assertEqual(package["contract_version"], "tina-accessible-package/v1")
        self.assertFalse(package["mutates_document"])
        self.assertTrue(package["pdf"].startswith(b"%PDF"))
        self.assertTrue(package["pdf_sha256"].startswith("sha256:"))
        self.assertEqual(package["source_sha256"], model["source_sha256"])
        check = package["self_check"]
        self.assertEqual(check["checker"], "check_pdf")
        # The Hub's own output must not land anything in Needs attention.
        self.assertEqual(check["needs_attention"], [], json.dumps(check["needs_attention"]))
        self.assertGreater(check["lanes"].get("verified_signal", 0), 0)

    def test_producer_refuses_undecided_figures(self):
        from tina.author import AccessiblePackageProducer

        model = build_docmodel(mixed_pdf(), language="en-US")
        with self.assertRaises(DocModelError) as raised:
            AccessiblePackageProducer.with_builtin_tools().produce(model, verify=False)
        self.assertIn("Figure 1 on page 2", str(raised.exception))

    def test_producer_requires_its_permission(self):
        from tina.author import AccessiblePackageProducer

        producer = AccessiblePackageProducer.with_builtin_tools()
        with self.assertRaises(PermissionError):
            producer.gateway.execute("produce_accessible_package", {"model": full_model()}, set())


@unittest.skipUnless(HAVE_WEASYPRINT, "WeasyPrint is not installed")
class LocalProduceEndpointTests(unittest.TestCase):
    def test_run_local_produce_returns_both_files_or_the_pending_figures(self):
        from local_reviewer import run_local_produce

        pdf = mixed_pdf()
        with self.assertRaises(DocModelError) as raised:
            run_local_produce("outline.pdf", pdf, language="en-US")
        self.assertEqual(raised.exception.pending, [{"block": 1, "figure": 1, "page": 2}])

        result = run_local_produce("outline.pdf", pdf, language="en-US", roles={"0": "h1"},
                                   figures={"1": {"decorative": True}})
        self.assertEqual(result["html_filename"], "outline.accessible.html")
        self.assertEqual(result["pdf_filename"], "outline.accessible.pdf")
        self.assertTrue(base64.b64decode(result["pdf_base64"]).startswith(b"%PDF"))
        self.assertIn('<html lang="en-US">', result["html"])
        self.assertNotIn("pdf", {k for k, v in result.items() if isinstance(v, bytes)})


@unittest.skipUnless(HAVE_WEASYPRINT, "WeasyPrint is not installed")
class ServiceAccessibleCopyTests(unittest.TestCase):
    def setUp(self):
        from service.app import create_app
        from service.repository import StagingRepository
        from service.settings import ServiceSettings
        from service.worker import AssessmentWorker

        self.temp = tempfile.TemporaryDirectory()
        self.settings = ServiceSettings("development", Path(self.temp.name), "synthetic-only-code", "s" * 48, ())
        self.repository = StagingRepository(self.settings.data_dir)
        self.worker = AssessmentWorker(self.repository)
        self.app = create_app(self.settings, self.repository, self.worker)
        self.cookie = ""

    def tearDown(self):
        self.worker.stop()
        self.temp.cleanup()

    def request(self, path, method="GET", form=None):
        body = urlencode(form or {}).encode()
        captured = {}

        def start_response(status, headers):
            captured["status"], captured["headers"] = status, dict(headers)

        response = b"".join(self.app({
            "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/x-www-form-urlencoded",
            "wsgi.input": io.BytesIO(body), "HTTP_COOKIE": self.cookie,
        }, start_response))
        return captured["status"], captured["headers"], response

    def start(self, fixture):
        status, headers, _ = self.request("/login", "POST", {"code": "synthetic-only-code"})
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, headers, _ = self.request("/documents/synthetic", "POST", {"fixture": fixture})
        self.assertTrue(status.startswith("303"), status)
        document_id = headers["Location"].rsplit("/", 1)[-1]
        for _ in range(200):
            job = self.repository.latest_job("coastline-staging", document_id)
            if job and job["state"] in {"succeeded", "failed"}:
                break
            time.sleep(0.05)
        return document_id

    def test_handout_downloads_as_tagged_pdf_and_html(self):
        document_id = self.start("handout")
        status, _, page = self.request(f"/documents/{document_id}/accessible")
        self.assertTrue(status.startswith("200"), status)
        self.assertIn(b"Get an accessible HTML page and a tagged PDF", page)
        form = {"title": "Week 3 Course Handout", "language": "en-US", "format": "pdf", "block_count": "1", "role_0": "h1"}
        status, headers, body = self.request(f"/documents/{document_id}/accessible", "POST", form)
        self.assertTrue(status.startswith("200"), status)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertIn(".accessible.pdf", headers["Content-Disposition"])
        self.assertIn("/H1", [name for name, _ in struct_tags(body)])
        status, headers, body = self.request(f"/documents/{document_id}/accessible", "POST", {**form, "format": "html"})
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn(b'<html lang="en-US">', body)
        events = [row["event"] if isinstance(row, dict) and "event" in row else row for row in self.repository.audit_events("coastline-staging")] if hasattr(self.repository, "audit_events") else None
        if events is not None:
            self.assertTrue(any("accessible_copy_produced" in json.dumps(event, default=str) for event in events))

    def test_scan_requires_a_figure_decision_before_producing(self):
        document_id = self.start("scan")
        status, _, page = self.request(f"/documents/{document_id}/accessible")
        self.assertIn(b"Image 1 (page 1)", page)
        self.assertIn(f"/documents/{document_id}/figure/1".encode(), page)
        status, headers, image = self.request(f"/documents/{document_id}/figure/1")
        self.assertTrue(status.startswith("200"))
        self.assertIn(headers["Content-Type"], {"image/png", "image/jpeg"})
        status, _, page = self.request(f"/documents/{document_id}/accessible", "POST",
                                       {"title": "Scanned handout", "language": "en-US", "format": "pdf"})
        self.assertTrue(status.startswith("422"), status)
        self.assertIn(b"needs a description or a decorative decision", page)
        status, headers, body = self.request(f"/documents/{document_id}/accessible", "POST", {
            "title": "Scanned handout", "language": "en-US", "format": "pdf",
            "fig_1_choice": "describe", "fig_1_alt": "Scanned handout page: Week 3 reading list",
        })
        self.assertTrue(status.startswith("200"), status)
        self.assertIn(("/Figure", "Scanned handout page: Week 3 reading list"), struct_tags(body))

    def test_scanned_pages_can_be_recognized_reviewed_and_corrected(self):
        import shutil

        if not shutil.which("tesseract"):
            self.skipTest("tesseract is not installed")
        document_id = self.start("scan")
        status, _, page = self.request(f"/documents/{document_id}/accessible")
        self.assertIn(b"Recognize the text on scanned pages", page)
        base = {"title": "Week 3 field notes", "language": "en-US", "format": "pdf", "use_ocr": "yes",
                "fig_1_choice": "decorative"}
        # First pass: recognition runs, and the person must check the text before anything is produced.
        status, _, page = self.request(f"/documents/{document_id}/accessible", "POST", base)
        self.assertTrue(status.startswith("422"), status)
        self.assertIn(b"Check the recognized text", page)
        self.assertIn(b"name=ocr_0", page)
        self.assertIn(b"Week 3 field notes", page)
        count = int(re.search(rb"name=ocr_count value=(\d+)", page).group(1))
        self.assertGreaterEqual(count, 1)
        corrected = {f"ocr_{i}": "" for i in range(count)}
        corrected["ocr_0"] = "Week 3 field notes (corrected by the instructor)"
        status, headers, body = self.request(f"/documents/{document_id}/accessible", "POST",
                                             {**base, **corrected, "ocr_count": str(count), "ocr_reviewed": "yes"})
        self.assertTrue(status.startswith("200"), status)
        text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(body)).pages)
        self.assertIn("Week 3 field notes (corrected by the instructor)", text)
        self.assertIn("checked and corrected by a person", text)
        self.assertNotIn("Synthetic scanned handout", text)  # emptied boxes are left out

    def test_hosted_staging_keeps_accessible_copies_closed_unless_enabled(self):
        from service.settings import ServiceSettings

        closed = ServiceSettings.from_environ({"HUB_ENV": "staging"})
        self.assertFalse(closed.produce_ready)
        opened = ServiceSettings.from_environ({"HUB_ENV": "staging", "HUB_ENABLE_PRODUCE": "true"})
        self.assertTrue(opened.produce_ready)
        self.assertFalse(ServiceSettings.from_environ({"HUB_ENV": "staging", "HUB_ENABLE_PRODUCE": "1"}).produce_ready)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_WEASYPRINT, "WeasyPrint is not installed")
class BenchProduceTests(unittest.TestCase):
    def test_bench_produce_mode_rechecks_each_copy(self):
        import scripts.transform_bench as bench

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "outline.pdf"
            source.write_bytes(mixed_pdf())
            produced = bench.run_produce(source, Path(directory))
            self.assertEqual(produced["status"], "produced", produced.get("note"))
            self.assertEqual(produced["needs_attention"], [])
            self.assertEqual(produced["figures"], 1)
            self.assertTrue((Path(directory) / "outline.bench.accessible.pdf").is_file())
            self.assertTrue((Path(directory) / "outline.bench.accessible.html").is_file())


class LinkTests(unittest.TestCase):
    def test_link_annotations_attach_to_the_paragraph_under_them(self):
        from tests.test_report_anchors import anchored_pdf

        model = build_docmodel(anchored_pdf(), title="Syllabus", language="en-US")
        paragraph = next(b for b in model["blocks"] if b.get("links"))
        self.assertEqual(paragraph["text"], "A chart appears below.")
        self.assertEqual(paragraph["links"][0]["href"], "https://example.edu/reading")
        self.assertTrue(paragraph["text"].startswith(paragraph["links"][0]["text"]))

    def test_addresses_written_in_text_become_links(self):
        model = build_docmodel(text_pdf("Readings at https://example.edu/week3 today"), title="T", language="en-US")
        self.assertEqual(model["blocks"][0]["links"], [{"text": "https://example.edu/week3", "href": "https://example.edu/week3", "source": "text"}])

    def test_unsafe_or_mismatched_links_are_rejected(self):
        model = full_model()
        model["blocks"][1]["links"] = [{"text": "chapter two", "href": "javascript:alert(1)"}]
        self.assertTrue(any("web or email" in p for p in validate_docmodel(model)))
        model["blocks"][1]["links"] = [{"text": "not in the text", "href": "https://example.edu"}]
        self.assertTrue(any("text is not in the block" in p for p in validate_docmodel(model)))

    def test_links_render_as_escaped_anchors(self):
        from tina.author import _text_with_links, render_html

        self.assertEqual(
            _text_with_links('See <the> site & more', [{"text": "site", "href": "https://example.edu/?a=1&b=\"2\""}]),
            'See &lt;the&gt; <a href="https://example.edu/?a=1&amp;b=&quot;2&quot;">site</a> &amp; more')
        model = full_model()
        model["blocks"][1]["links"] = [{"text": "chapter two", "href": "https://example.edu/ch2"}]
        self.assertIn('Read <a href="https://example.edu/ch2">chapter two</a> before class.', render_html(model))

    @unittest.skipUnless(HAVE_WEASYPRINT, "WeasyPrint is not installed")
    def test_pdf_carries_a_tagged_link_annotation(self):
        from tina.author import render_pdf

        model = full_model()
        model["blocks"][1]["links"] = [{"text": "chapter two", "href": "https://example.edu/ch2"}]
        pdf = render_pdf(model)
        annotations = [a.get_object() for page in PdfReader(io.BytesIO(pdf)).pages for a in page.get("/Annots", [])]
        self.assertEqual([str(a["/A"]["/URI"]) for a in annotations if a.get("/Subtype") == "/Link"], ["https://example.edu/ch2"])
        self.assertIn("/Link", [name for name, _ in struct_tags(pdf)])
