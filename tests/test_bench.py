"""Transformation bench tests: corpus determinism, the real pipeline end to end,
JSON output shape, honest declines, the qpdf-live wiring, and the outcome-language
governance boundary on the bench's HTML report."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pypdf import PdfReader

from tina.evidence import PROHIBITED_OUTCOME_PHRASES

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(script: str):
    spec = importlib.util.spec_from_file_location(script, REPO_ROOT / "scripts" / f"{script}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


corpus_module = _load("make_test_corpus")
bench_module = _load("transform_bench")

# Deterministic documents pinned byte-for-byte across generator runs.
DETERMINISTIC_DOCS = ("missing-title-language.pdf", "clean-well-formed.pdf",
                      "untagged-multiblock.pdf", "unnamed links.pdf")


class CorpusDeterminismTests(unittest.TestCase):
    def test_builders_reproduce_identical_bytes_across_calls(self):
        for name in DETERMINISTIC_DOCS:
            builder = corpus_module.CORPUS[name][0]
            self.assertEqual(builder(), builder(), f"{name} bytes differ between builder calls")

    def test_generator_writes_identical_files_across_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp) / "a", Path(temp) / "b"
            for name in DETERMINISTIC_DOCS:
                corpus_module.write_corpus(first, only=name)
                corpus_module.write_corpus(second, only=name)
            for name in DETERMINISTIC_DOCS:
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)

    def test_every_catalog_entry_generates_a_parseable_or_encrypted_pdf(self):
        for name, (builder, _deterministic, note) in corpus_module.CORPUS.items():
            if name == "long-50-pages.pdf":
                continue  # covered by the bench run; skip regeneration cost here
            payload = builder()
            self.assertTrue(payload.startswith(b"%PDF"), name)
            self.assertTrue(note.strip(), name)

    def test_list_and_unknown_name_behave(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(corpus_module.main(["--list"]), 0)
        for name in DETERMINISTIC_DOCS:
            self.assertIn(name, stdout.getvalue())
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SystemExit):
                corpus_module.write_corpus(Path(temp), only="no-such-document.pdf")


@unittest.skipUnless(shutil.which("qpdf"), "qpdf is not installed in this environment")
class QpdfLiveWiringTests(unittest.TestCase):
    """With qpdf present, the checker must take the real qpdf path end to end."""

    def test_qpdf_unavailable_finding_is_absent_and_integrity_evidence_is_real(self):
        from check_pdf import analyze

        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "doc.pdf"
            pdf.write_bytes(corpus_module.CORPUS["missing-title-language.pdf"][0]())
            report = analyze(pdf, Path(temp) / "evidence")
        rule_ids = {item["rule_id"] for item in report["findings"]}
        self.assertNotIn("PDF.INTAKE.QPDF_UNAVAILABLE", rule_ids)
        self.assertNotIn("structural integrity (qpdf)",
                         {entry["area"] for entry in report["not_assessed"]})
        strengths = {item["rule_id"] for item in report["strengths"]}
        self.assertIn("PDF.INTAKE.QPDF_CHECK", strengths)
        self.assertIsNotNone(report["tools"]["qpdf"])
        self.assertIn("qpdf", report["tools"]["qpdf"])

    def test_encrypted_pdf_takes_the_real_qpdf_blocking_path(self):
        from check_pdf import analyze

        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "locked.pdf"
            pdf.write_bytes(corpus_module.CORPUS["encrypted.pdf"][0]())
            report = analyze(pdf, Path(temp) / "evidence")
        blocking = {item["rule_id"] for item in report["findings"]
                    if item["category"] == "blocking_technical_failure"}
        self.assertTrue(blocking & {"PDF.INTAKE.ENCRYPTED", "PDF.INTAKE.QPDF_CHECK"})
        self.assertNotIn("PDF.INTAKE.QPDF_UNAVAILABLE",
                         {item["rule_id"] for item in report["findings"]})

    def test_toolchain_module_reports_a_qpdf_version(self):
        from service.toolchain import toolchain_versions

        toolchain_versions.cache_clear()
        versions = toolchain_versions()
        self.assertIsNotNone(versions["qpdf"])
        self.assertEqual(set(versions), {"qpdf", "tesseract", "pdftoppm", "verapdf"})


class BenchEndToEndTests(unittest.TestCase):
    """The bench drives the real pipeline over a 3-document mini corpus."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="bench-e2e-")
        root = Path(cls.temp.name)
        cls.corpus_dir = root / "corpus"
        cls.out_dir = root / "out"
        for name in ("missing-title-language.pdf", "clean-well-formed.pdf", "encrypted.pdf"):
            corpus_module.write_corpus(cls.corpus_dir, only=name)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            cls.exit_code = bench_module.main(
                [str(cls.corpus_dir), "--out", str(cls.out_dir), "--json"])
        cls.payload = json.loads(stdout.getvalue())
        cls.by_name = {doc["name"]: doc for doc in cls.payload["documents"]}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_exit_code_zero_when_every_document_behaves_expectedly(self):
        self.assertEqual(self.exit_code, 0)
        self.assertTrue(self.payload["ok"])

    def test_json_shape_carries_toolchain_documents_and_claim(self):
        self.assertEqual(set(self.payload) >= {"ok", "toolchain", "documents", "report_html", "claim"}, True)
        self.assertEqual(set(self.payload["toolchain"]) >=
                         {"qpdf", "tesseract", "verapdf", "verapdf_unavailable_reason"}, True)
        for doc in self.payload["documents"]:
            self.assertEqual(set(doc) >= {"name", "status", "expected", "pages_before", "pages_after",
                                          "lanes_before", "lanes_after", "applied", "narration",
                                          "decline_reason", "output", "elapsed_ms"}, True)

    def test_repairable_document_gains_title_language_and_seal_page(self):
        doc = self.by_name["missing-title-language.pdf"]
        self.assertEqual(doc["status"], "transformed")
        self.assertEqual(doc["pages_before"] + 1, doc["pages_after"])
        self.assertTrue(any("title" in item.lower() for item in doc["applied"]))
        self.assertTrue(any("language" in item.lower() for item in doc["applied"]))
        ready = self.out_dir / doc["output"]
        reader = PdfReader(str(ready))
        self.assertEqual(len(reader.pages), doc["pages_after"])
        self.assertEqual(reader.metadata.get("/Title"), "Missing Title Language")
        self.assertEqual(str(reader.trailer["/Root"].get("/Lang")), "en-US")
        self.assertIn("review record, not a certification",
                      (reader.pages[-1].extract_text() or ""))
        self.assertEqual(doc["lanes_after"]["needs_attention"], 0)
        self.assertGreater(doc["lanes_after"]["verified_signal"],
                           doc["lanes_before"]["verified_signal"])

    def test_clean_document_reports_nothing_to_improve(self):
        doc = self.by_name["clean-well-formed.pdf"]
        self.assertEqual(doc["status"], "nothing_to_improve")
        self.assertEqual(doc["applied"], [])
        self.assertIsNotNone(doc["output"])
        # Still sealed with the review record; the source lanes are unchanged.
        self.assertEqual(doc["lanes_before"], doc["lanes_after"])

    def test_encrypted_document_declines_expectedly_without_output(self):
        doc = self.by_name["encrypted.pdf"]
        self.assertEqual(doc["status"], "declined_expected")
        self.assertTrue(doc["expected"])
        self.assertIsNone(doc["output"])
        self.assertTrue(doc["decline_reason"])
        self.assertFalse((self.out_dir / "encrypted.ready.pdf").exists())

    def test_html_report_exists_and_carries_no_prohibited_outcome_language(self):
        report = (self.out_dir / "bench-report.html").read_text(encoding="utf-8").lower()
        for phrase in PROHIBITED_OUTCOME_PHRASES:
            self.assertNotIn(phrase, report)
        for extra in ("certified", "conformant", "score"):
            self.assertNotIn(extra, report)
        self.assertIn("a review record, not a certification", report)
        self.assertIn("verapdf", report)  # tool status strip is present and honest

    def test_kpi_facts_are_computed_from_the_two_reviews(self):
        doc = self.by_name["missing-title-language.pdf"]
        facts = doc["kpis"]
        self.assertIsNotNone(facts)
        self.assertEqual(facts["fields_set"], len(doc["applied"]))
        # Content preserved is page math, never a typed-in number: every
        # original page carried into the improved copy before sealing.
        self.assertEqual(facts["content_preserved_pct"], 100)
        self.assertEqual(facts["pages_added"], 1)
        self.assertEqual(doc["pages_after"], doc["pages_before"] + facts["pages_added"])
        self.assertGreaterEqual(facts["signals_resolved"], 2)  # title + language verified
        self.assertEqual(facts["human_review"],
                         doc["lanes_after"]["needs_attention"] + doc["lanes_after"]["review_recommended"])
        # A document the pipeline could not read has no facts to state.
        self.assertIsNone(self.by_name["encrypted.pdf"]["kpis"])

    @unittest.skipUnless(shutil.which("pdftoppm"), "pdftoppm is not installed in this environment")
    def test_html_report_carries_side_by_side_page_images_and_kpi_row(self):
        doc = self.by_name["missing-title-language.pdf"]
        for key in ("page1_before", "page1_after"):
            self.assertTrue(str(doc[key]).startswith("data:image/png;base64,"), key)
        # Render from the run's own records (another test re-runs the bench
        # into the shared out dir, so the file on disk is not stable here).
        report = bench_module.render_html(self.payload["documents"], "corpus", "now")
        self.assertIn("data:image/png;base64,", report)
        self.assertIn("First page of the original document", report)
        self.assertIn("First page of the improved copy", report)
        self.assertIn("Transformation facts", report)
        for label in ("content preserved", "fields set", "signals resolved",
                      "review-record page", "still for human review"):
            self.assertIn(label, report)
        # The callout badges mirror the applied provenance labels exactly.
        import html as html_module
        for applied in doc["applied"]:
            self.assertIn(f'<span class="callout">{html_module.escape(applied)}</span>', report)
        self.assertIn("never a rating of the document", report)

    def test_report_renders_gracefully_without_the_rasterizer(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            stdout = io.StringIO()
            with mock.patch.object(bench_module, "rasterize_page1_png", return_value=None):
                with contextlib.redirect_stdout(stdout):
                    code = bench_module.main([str(self.corpus_dir / "clean-well-formed.pdf"),
                                              "--out", str(out), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            doc = payload["documents"][0]
            self.assertIsNone(doc["page1_before"])
            self.assertIsNone(doc["page1_after"])
            self.assertIsNotNone(doc["kpis"])  # facts never depended on images
            report = (out / "bench-report.html").read_text(encoding="utf-8")
            self.assertNotIn("data:image/png", report)
            self.assertIn("Transformation facts", report)

    def test_console_table_mode_also_exits_zero(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = bench_module.main([str(self.corpus_dir / "clean-well-formed.pdf"),
                                      "--out", str(self.out_dir)])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("Toolchain status:", text)
        self.assertIn("clean-well-formed.pdf", text)
        self.assertIn("no changes needed", text)

    def test_a_crash_inside_the_pipeline_fails_the_bench(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            stdout = io.StringIO()
            with mock.patch.object(bench_module, "analyze",
                                   side_effect=RuntimeError("synthetic crash")):
                with contextlib.redirect_stdout(stdout):
                    code = bench_module.main(
                        [str(self.corpus_dir / "clean-well-formed.pdf"), "--out", str(out)])
        self.assertEqual(code, 1)
        self.assertIn("ERROR", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
