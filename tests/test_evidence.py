import json
import re
import unittest
from pathlib import Path

from tina.evidence import DISCLAIMER, build_receipt, verify_receipt_integrity


def sample_review(findings=None, strengths=None):
    return {
        "schema_version": "0.1",
        "input": {"sha256": "f" * 64, "bytes": 1234},
        "tools": {"qpdf": None, "pypdf": "6.9.1"},
        "verapdf": {"tool_available": False, "stderr": "Docker is not installed"},
        "findings": findings if findings is not None else [
            {"rule_id": "PDF.METADATA.TITLE", "category": "deterministic_defect", "severity": "medium"},
            {"rule_id": "PDF.IMAGES.ALTERNATIVES", "category": "review_required", "severity": "medium"},
            {"rule_id": "PDF.INTAKE.QPDF_UNAVAILABLE", "category": "tool_failure_or_unsupported", "severity": "medium", "evidence": "qpdf is not installed"},
        ],
        "strengths": strengths or [],
    }


class ReceiptContentTests(unittest.TestCase):
    def test_receipt_records_findings_checks_skipped_and_disclaimer(self):
        receipt = build_receipt(sample_review())
        self.assertEqual(receipt["contract_version"], "tina-evidence-receipt/v1")
        self.assertEqual(receipt["disclaimer"], DISCLAIMER)
        self.assertEqual(len(receipt["findings_before"]), 3)
        skipped_rules = {item["rule_id"] for item in receipt["checks_not_performed"]}
        self.assertEqual(skipped_rules, {"PDF.INTAKE.QPDF_UNAVAILABLE", "PDF.VERAPDF.UA1"})
        self.assertIsNone(receipt["findings_after"])
        self.assertEqual(receipt["mutations"], [])

    def test_receipt_records_fix_resolution_and_mutation_provenance(self):
        remediation = {
            "tool": "set_document_metadata",
            "tool_version": "1.0.0",
            "source_sha256": "sha256:" + "f" * 64,
            "remediated_sha256": "sha256:" + "e" * 64,
            "remediated_bytes": 1300,
            "actions": [{"rule_id": "PDF.METADATA.TITLE", "action": "set_document_title"}],
        }
        after = sample_review(findings=[
            {"rule_id": "PDF.IMAGES.ALTERNATIVES", "category": "review_required", "severity": "medium"},
        ])
        receipt = build_receipt(sample_review(), after=after, remediation=remediation)
        self.assertIn("PDF.METADATA.TITLE", receipt["resolved_rule_ids"])
        self.assertEqual(receipt["output"]["sha256"], "sha256:" + "e" * 64)
        self.assertEqual(receipt["mutations"][0]["tool"], "set_document_metadata")
        self.assertEqual(len(receipt["unresolved"]), 1)

    def test_receipt_includes_user_attestations_and_drops_empty_ones(self):
        receipt = build_receipt(sample_review(), attestations=[
            {"rule_id": "PDF.IMAGES.ALTERNATIVES", "decision": "All images reviewed; two decorative.", "decided_at": "2026-07-20T00:00:00Z"},
            {"rule_id": "PDF.LINKS.PURPOSE", "decision": "   "},
        ])
        self.assertEqual(len(receipt["human_decisions"]), 1)
        self.assertEqual(receipt["human_decisions"][0]["status"], "user_attested")

    def test_receipt_integrity_hash_verifies_and_detects_tampering(self):
        receipt = build_receipt(sample_review())
        self.assertTrue(verify_receipt_integrity(receipt))
        receipt["findings_before"] = []
        self.assertFalse(verify_receipt_integrity(receipt))

    def test_receipt_requires_a_review_report(self):
        with self.assertRaises(ValueError):
            build_receipt({})


class OutcomeLanguageGovernanceTests(unittest.TestCase):
    """PRD §6.1: prohibited outcome language must not appear on product surfaces."""

    PROHIBITED = [
        "fully compliant",
        "guaranteed accessible",
        "passed accessibility",
        "certified accessible",
        "fully accessible",
    ]

    SURFACES = [
        "check_pdf.py",
        "local_reviewer.py",
        "local_reviewer.html",
        "rule_knowledge.json",
        "delight_content.json",
        "tina/kernel.py",
        "tina/remedy.py",
        "tina/derive.py",
        "tina/learning.py",
        "tina/intelligence.py",
        "foundation_ads.json",
    ]

    def test_product_surfaces_never_use_prohibited_outcome_language(self):
        for surface in self.SURFACES:
            text = Path(surface).read_text().lower()
            for phrase in self.PROHIBITED:
                self.assertNotIn(phrase, text, f"Prohibited phrase '{phrase}' found in {surface}")

    def test_evidence_receipt_disclaimer_denies_certification(self):
        self.assertIn("not a certification", DISCLAIMER)

    def test_strengths_are_never_aggregated_into_a_pass(self):
        source = Path("check_pdf.py").read_text()
        self.assertIn("never combined into an overall accessibility pass", source)


class VerifiedStrengthsTests(unittest.TestCase):
    def test_present_metadata_becomes_machine_verified_strengths(self):
        import tempfile

        from check_pdf import analyze
        from tests.test_html_draft import text_pdf

        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "titled.pdf"
            pdf_path.write_bytes(text_pdf("Hello", title="Week 3 Outline", language="en-US"))
            report = analyze(pdf_path, Path(directory) / "out")

        strength_rules = {item["rule_id"] for item in report["strengths"]}
        self.assertIn("PDF.METADATA.TITLE", strength_rules)
        self.assertIn("PDF.METADATA.LANGUAGE", strength_rules)
        finding_rules = {item["rule_id"] for item in report["findings"]}
        self.assertNotIn("PDF.METADATA.TITLE", finding_rules)
        self.assertTrue(all(item["status"] == "machine_verified" for item in report["strengths"]))
        self.assertIn("never combined", report["strengths_note"])


if __name__ == "__main__":
    unittest.main()
