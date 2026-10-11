"""PdfCraft adapter: the subprocess contract (fake binary) and the real binary when present."""
import io
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from pypdf import PdfReader

from tina.kernel import ToolPermissionError
from tina.pdfcraft import (
    RULE_MAP,
    PdfCraft,
    PdfCraftError,
    PdfCraftRunner,
    PdfCraftUnavailable,
    find_binary,
    parse_json_stream,
    second_opinion,
)
from tina.remedy import RemediationError
from tests.test_html_draft import text_pdf

REAL_BINARY = find_binary()

CHECK_RESULT = {
    "passed": 1, "failed": 1, "manual": 0, "skipped": 0,
    "results": [
        {"category": "document", "rule": "title", "name": "Title", "status": "failed",
         "findings": [{"message": "No title", "page": None}]},
        {"category": "document", "rule": "primary-language", "name": "Primary language", "status": "passed", "findings": []},
    ],
}


def fake_binary(directory: Path, body: str) -> str:
    """A stand-in pdfcraft-cli: a Python script with a controlled behavior."""
    path = directory / "pdfcraft-cli"
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_parse_json_stream_reads_back_to_back_values(self):
        self.assertEqual(parse_json_stream('{"a": 1}\n{\n "b": [2]\n}  '), [{"a": 1}, {"b": [2]}])
        with self.assertRaises(PdfCraftError):
            parse_json_stream("{not json")

    def test_missing_binary_is_unavailable_not_a_crash(self):
        runner = PdfCraftRunner(binary=None)
        runner.binary = None
        with self.assertRaises(PdfCraftUnavailable):
            runner.run_script([], {})
        craft = PdfCraft.with_builtin_tools(runner)
        self.assertFalse(craft.available)

    def test_check_runs_in_a_sandbox_root_with_a_minimal_environment(self):
        binary = fake_binary(self.dir, f"""
            import json, os, sys
            assert sys.argv[1:4] == ["run", "--script", "steps.json"], sys.argv
            steps = json.load(open("steps.json"))
            assert [s["tool"] for s in steps] == ["doc_open", "accessibility_check"]
            assert open("in.pdf", "rb").read().startswith(b"%PDF")
            assert not any(k.lower().endswith("_proxy") for k in os.environ), os.environ
            print(json.dumps({{"doc": 1}}))
            print({json.dumps(json.dumps(CHECK_RESULT))})
        """)
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.invalid"}):
            result = PdfCraft.with_builtin_tools(PdfCraftRunner(binary)).check(text_pdf("Hi"))
        self.assertEqual(result["summary"], {"passed": 1, "failed": 1, "manual": 0, "skipped": 0})
        self.assertEqual(result["results"][0]["maps_to"], "PDF.METADATA.TITLE")
        self.assertIn("not a conformance result", result["claim_boundary"])

    def test_nonzero_exit_and_timeouts_raise_pdfcraft_errors(self):
        failing = fake_binary(self.dir, """
            import sys
            sys.stderr.write("pdfcraft-cli: cannot open in.pdf\\n")
            sys.exit(1)
        """)
        with self.assertRaises(PdfCraftError) as raised:
            PdfCraftRunner(failing).run_script([{"tool": "doc_open", "args": {}}], {"in.pdf": b"%PDF"})
        self.assertIn("cannot open", str(raised.exception))
        slow = fake_binary(self.dir, "import time; time.sleep(5)\n")
        with self.assertRaises(PdfCraftError):
            PdfCraftRunner(slow, timeout=0.5).run_script([], {})

    def test_incomplete_step_output_is_an_error(self):
        binary = fake_binary(self.dir, 'print("{}")\n')
        with self.assertRaises(PdfCraftError):
            PdfCraftRunner(binary).run_script([{"tool": "a"}, {"tool": "b"}], {})

    def test_tools_enforce_their_permissions(self):
        craft = PdfCraft.with_builtin_tools(PdfCraftRunner(binary=None))
        for tool in ("pdfcraft_accessibility_check", "pdfcraft_list_figures", "pdfcraft_semantic_fix", "pdfcraft_render_page"):
            with self.assertRaises(ToolPermissionError):
                craft.gateway.execute(tool, {"payload": b""}, set())

    def test_semantic_fix_declines_untagged_pdfs_before_running_anything(self):
        craft = PdfCraft.with_builtin_tools(PdfCraftRunner(binary=None))
        with self.assertRaises(RemediationError) as raised:
            craft.apply_semantics("a.pdf", text_pdf("Hi"), language="en-US")
        self.assertIn("no tag structure", str(raised.exception))

    def test_second_opinion_without_pdfcraft_is_disclosed(self):
        with mock.patch.dict(os.environ, {"PDFCRAFT_BIN": str(self.dir / "absent")}):
            block = second_opinion(text_pdf("Hi"), [], [])
        self.assertFalse(block["available"])
        self.assertIn("not installed", block["reason"])

    def test_second_opinion_surfaces_disagreements_for_a_person(self):
        binary = fake_binary(self.dir, f"""
            import json
            print(json.dumps({{"doc": 1}}))
            print({json.dumps(json.dumps(CHECK_RESULT))})
        """)
        with mock.patch.dict(os.environ, {"PDFCRAFT_BIN": binary}):
            block = second_opinion(text_pdf("Hi"), [], [{"rule_id": "PDF.METADATA.TITLE"}])
        self.assertTrue(block["available"])
        self.assertEqual(block["disagreements"], [
            {"pdfcraft_rule": "title", "hub_rule": "PDF.METADATA.TITLE", "pdfcraft": "failed", "hub": "verified"},
        ])

    def test_every_mapped_rule_and_the_second_opinion_rule_have_teaching_cards(self):
        rules = json.loads(Path("rule_knowledge.json").read_text())["rules"]
        for hub_rule in set(RULE_MAP.values()) | {"PDF.SECOND_OPINION.PDFCRAFT"}:
            self.assertIn(hub_rule, rules)


@unittest.skipUnless(REAL_BINARY, "pdfcraft-cli is not installed (scripts/build_pdfcraft.sh)")
class RealBinaryTests(unittest.TestCase):
    def test_check_reports_acrobat_style_rules(self):
        result = PdfCraft.with_builtin_tools().check(text_pdf("Hello", title="Week 1", language="en-US"))
        rules = {item["rule"]: item for item in result["results"]}
        self.assertEqual(rules["primary-language"]["status"], "passed")
        # Acrobat's rule also wants DisplayDocTitle, which this fixture lacks.
        self.assertEqual(rules["title"]["status"], "failed")
        self.assertIn("file name, not the title", rules["title"]["findings"][0]["message"])
        rules = {name: item["status"] for name, item in rules.items()}
        self.assertEqual(rules.get("tagged-pdf"), "failed")
        self.assertEqual(sum(result["summary"].values()), len(result["results"]))

    def test_render_page_returns_a_png(self):
        image = PdfCraft.with_builtin_tools().render_page(text_pdf("Hello"), 1, dpi=36)
        self.assertTrue(image.startswith(b"\x89PNG"))

    def test_semantic_fix_on_a_tagged_pdf_sets_language_title_and_alt(self):
        try:
            from tina.author import render_pdf
        except ImportError:  # pragma: no cover
            self.skipTest("WeasyPrint is not installed")
        from tests.test_author import full_model

        model = full_model()
        model["language"] = "fr"
        tagged = render_pdf(model)
        craft = PdfCraft.with_builtin_tools()
        figures = craft.list_figures(tagged)
        self.assertEqual([(f["position"], f["alt"]) for f in figures], [(1, "Bar chart: essays outweigh quizzes")])
        fixed, report = craft.apply_semantics(
            "syllabus.pdf", tagged, language="en-US", title="Week 3 syllabus (revised)",
            figures={"1": {"alt": "Revised description"}},
        )
        self.assertTrue(report["mutates_document"])
        self.assertNotEqual(report["source_sha256"], report["remediated_sha256"])
        reader = PdfReader(io.BytesIO(fixed))
        self.assertEqual(str(reader.trailer["/Root"]["/Lang"]), "en-US")
        self.assertEqual(reader.metadata.title, "Week 3 syllabus (revised)")
        from tests.test_author import struct_tags

        self.assertIn(("/Figure", "Revised description"), struct_tags(fixed))

    def test_checker_report_carries_the_second_opinion(self):
        import check_pdf

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "doc.pdf"
            path.write_bytes(text_pdf("Hello", title="Week 1", language="en-US"))
            report = check_pdf.analyze(path, Path(directory) / "out")
        self.assertTrue(report["second_opinion"]["available"])
        self.assertTrue(report["tools"]["pdfcraft"])
        flagged = [f for f in report["findings"] if f["rule_id"] == "PDF.SECOND_OPINION.PDFCRAFT"]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["category"], "advisory")  # routes to review, never a verdict


@unittest.skipUnless(REAL_BINARY, "pdfcraft-cli is not installed (scripts/build_pdfcraft.sh)")
class ServiceTaggedFigureTests(unittest.TestCase):
    def test_tagged_pdf_figures_are_described_on_a_new_copy(self):
        import time
        from urllib.parse import urlencode

        try:
            from tina.author import render_pdf
        except ImportError:  # pragma: no cover
            self.skipTest("WeasyPrint is not installed")
        from service.app import create_app
        from service.repository import StagingRepository
        from service.settings import ServiceSettings
        from service.worker import AssessmentWorker
        from tests.test_author import full_model, struct_tags

        with tempfile.TemporaryDirectory() as directory:
            settings = ServiceSettings("development", Path(directory), "synthetic-only-code", "s" * 48, ())
            repository = StagingRepository(settings.data_dir)
            worker = AssessmentWorker(repository)
            app = create_app(settings, repository, worker)
            try:
                cookie = {"value": ""}

                def request(path, method="GET", form=None):
                    body = urlencode(form or {}).encode()
                    captured = {}

                    def start_response(status, headers):
                        captured["status"], captured["headers"] = status, dict(headers)

                    response = b"".join(app({
                        "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
                        "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/x-www-form-urlencoded",
                        "wsgi.input": io.BytesIO(body), "HTTP_COOKIE": cookie["value"],
                    }, start_response))
                    return captured["status"], captured["headers"], response

                _, headers, _ = request("/login", "POST", {"code": "synthetic-only-code"})
                cookie["value"] = headers["Set-Cookie"].split(";", 1)[0]
                document = repository.create_document("coastline-staging", "syllabus.pdf", "bundled_synthetic_fixture", render_pdf(full_model()))
                repository.enqueue(document["id"], kind="assessment")
                for _ in range(200):
                    job = repository.latest_job("coastline-staging", document["id"])
                    if job and job["state"] in {"succeeded", "failed"}:
                        break
                    time.sleep(0.05)
                status, _, page = request(f"/documents/{document['id']}")
                self.assertIn(b"Describe images in this tagged PDF", page)
                self.assertIn("Current description: “Bar chart: essays outweigh quizzes”".encode(), page)
                status, headers, _ = request(f"/documents/{document['id']}/remediate/figures", "POST", {
                    "figure_count": "1", "fig_1_choice": "describe", "fig_1_alt": "Essays count for 40 percent",
                })
                self.assertTrue(status.startswith("303"), status)
                child_id = headers["Location"].rsplit("/", 1)[-1]
                child = repository.document_bytes("coastline-staging", child_id)
                self.assertIn(("/Figure", "Essays count for 40 percent"), struct_tags(child))
                self.assertEqual(repository.document_bytes("coastline-staging", document["id"])[:4], b"%PDF")
            finally:
                worker.stop()


if __name__ == "__main__":
    unittest.main()
