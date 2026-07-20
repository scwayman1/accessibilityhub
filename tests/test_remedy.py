import io
import unittest

from pypdf import PdfReader, PdfWriter

from tina.kernel import ToolPermissionError
from tina.remedy import MetadataRemediation, RemediationError, validate_fix_request


def minimal_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class FixRequestValidationTests(unittest.TestCase):
    def test_rejects_empty_fix_request(self):
        with self.assertRaises(RemediationError):
            validate_fix_request(None, None)

    def test_rejects_blank_title(self):
        with self.assertRaises(RemediationError):
            validate_fix_request("   ", None)

    def test_rejects_malformed_language_tag(self):
        with self.assertRaises(RemediationError):
            validate_fix_request(None, "english please")

    def test_accepts_common_language_tags(self):
        for tag in ("en", "en-US", "es-MX", "zh-Hans"):
            validate_fix_request(None, tag)


class MetadataRemediationTests(unittest.TestCase):
    def test_sets_title_language_and_display_doc_title_on_a_copy(self):
        source = minimal_pdf()
        engine = MetadataRemediation.with_builtin_tools()
        fixed, report = engine.apply("outline.pdf", source, title="Week 3 Outline", language="en-US")

        reader = PdfReader(io.BytesIO(fixed))
        catalog = reader.trailer["/Root"].get_object()
        self.assertEqual(reader.metadata.get("/Title"), "Week 3 Outline")
        self.assertEqual(catalog.get("/Lang"), "en-US")
        self.assertTrue(catalog["/ViewerPreferences"].get_object().get("/DisplayDocTitle"))

    def test_report_records_provenance_and_claim_boundary(self):
        source = minimal_pdf()
        engine = MetadataRemediation.with_builtin_tools()
        fixed, report = engine.apply("outline.pdf", source, title="Week 3 Outline")

        self.assertEqual(report["contract_version"], "tina-remediation-report/v1")
        self.assertTrue(report["mutates_document"])
        self.assertTrue(report["deterministic"])
        self.assertNotEqual(report["source_sha256"], report["remediated_sha256"])
        self.assertEqual(report["remediated_bytes"], len(fixed))
        self.assertNotIn("remediated_payload", report)
        self.assertEqual([action["rule_id"] for action in report["actions"]], ["PDF.METADATA.TITLE"])
        self.assertIn("not make the document conformant", report["claim_boundary"])

    def test_language_only_fix_does_not_touch_title(self):
        source = minimal_pdf()
        engine = MetadataRemediation.with_builtin_tools()
        fixed, report = engine.apply("outline.pdf", source, language="es-MX")

        reader = PdfReader(io.BytesIO(fixed))
        self.assertEqual(reader.trailer["/Root"].get_object().get("/Lang"), "es-MX")
        self.assertEqual([action["rule_id"] for action in report["actions"]], ["PDF.METADATA.LANGUAGE"])

    def test_gateway_denies_mutation_without_remediate_permission(self):
        engine = MetadataRemediation.with_builtin_tools()
        with self.assertRaises(ToolPermissionError):
            engine.gateway.execute("set_document_metadata", {"payload": minimal_pdf(), "title": "x"}, set())

    def test_rejects_unparseable_payload(self):
        engine = MetadataRemediation.with_builtin_tools()
        with self.assertRaises(RemediationError):
            engine.apply("broken.pdf", b"%PDF-not really a pdf", title="Title")


if __name__ == "__main__":
    unittest.main()
