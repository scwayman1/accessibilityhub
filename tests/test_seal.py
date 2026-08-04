"""Seal engine tests: the appended Review summary page is additive, honest, and on-record.

The seal is a review record, never a certification. These tests hold the
anti-vandal contract (page count +1, byte-identical prior text), the honest
declines (encrypted, garbage), provenance determinism, and the outcome-language
governance boundary on both the seal page and the partner ad copy.
"""
import io
import json
import unittest
from hashlib import sha256
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from tests.test_fixlab import build_pdf, untagged_pdf
from tina.evidence import PROHIBITED_OUTCOME_PHRASES
from tina.remedy import RemediationError
from tina.seal import EVIDENCE_HASH_CHARS, RECORD_LINE, SEAL_WORDING, append_review_summary

# The claim boundary the seal must never cross, in either direction: the
# governance phrase list plus the certification/approval vocabulary.
PROHIBITED = list(PROHIBITED_OUTCOME_PHRASES) + [
    "approved as accessible",
    "certified",
    "compliant",
]

WHEN = "2026-08-04"

SUMMARY = {
    "lanes": {
        "needs_attention": 2,
        "review_recommended": 1,
        "verified_signal": 3,
        "not_assessed": 4,
    },
    "applied_fixes": ["Set document title", "Set primary language to en"],
    "verified": ["Document title displays instead of the filename"],
}


def two_page_pdf() -> bytes:
    """A real generated two-page PDF with extractable text on each page."""
    first = b"BT /F1 12 Tf 72 720 Td (Course Syllabus) Tj 0 -30 Td (Week one covers foundations.) Tj ET"
    second = b"BT /F1 12 Tf 72 720 Td (Week two continues the plan.) Tj ET"
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(first)).encode() + b" >>\nstream\n" + first + b"\nendstream",
        b"<< /Length " + str(len(second)).encode() + b" >>\nstream\n" + second + b"\nendstream",
    ])


def encrypted_pdf() -> bytes:
    reader = PdfReader(io.BytesIO(untagged_pdf()), strict=False)
    writer = PdfWriter(clone_from=reader)
    writer.encrypt("owner-only")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def seal_page_text(sealed: bytes) -> str:
    reader = PdfReader(io.BytesIO(sealed), strict=False)
    return reader.pages[-1].extract_text() or ""


class SealAppendsOnePageTests(unittest.TestCase):
    def test_page_count_increases_by_exactly_one(self):
        source = two_page_pdf()
        sealed, provenance = append_review_summary("syllabus.pdf", source, SUMMARY, WHEN)
        reader = PdfReader(io.BytesIO(sealed), strict=False)
        self.assertEqual(len(reader.pages), 3)
        self.assertEqual(provenance["source_pages"], 2)
        self.assertEqual(provenance["result_pages"], 3)

    def test_prior_pages_keep_byte_identical_extracted_text(self):
        source = two_page_pdf()
        before = [page.extract_text() or "" for page in PdfReader(io.BytesIO(source), strict=False).pages]
        sealed, _ = append_review_summary("syllabus.pdf", source, SUMMARY, WHEN)
        after_reader = PdfReader(io.BytesIO(sealed), strict=False)
        for index, expected in enumerate(before):
            self.assertEqual(after_reader.pages[index].extract_text() or "", expected)

    def test_seal_page_carries_wording_date_hash_and_record_line(self):
        source = two_page_pdf()
        sealed, provenance = append_review_summary("syllabus.pdf", source, SUMMARY, WHEN)
        text = seal_page_text(sealed)
        self.assertIn(SEAL_WORDING, text)
        self.assertIn(RECORD_LINE, text)
        self.assertIn(WHEN, text)
        short = sha256(source).hexdigest()[:EVIDENCE_HASH_CHARS]
        self.assertIn(short, text)
        self.assertEqual(provenance["evidence_hash_short"], short)

    def test_seal_page_carries_lane_counts_fixes_and_verified_signals(self):
        sealed, _ = append_review_summary("syllabus.pdf", two_page_pdf(), SUMMARY, WHEN)
        text = seal_page_text(sealed)
        self.assertIn("Needs attention: 2", text)
        self.assertIn("Review recommended: 1", text)
        self.assertIn("Verified signal: 3", text)
        self.assertIn("Not assessed: 4", text)
        self.assertIn("Set document title", text)
        self.assertIn("Set primary language to en", text)
        self.assertIn("Document title displays instead of the filename", text)

    def test_seal_page_never_uses_prohibited_outcome_language(self):
        sealed, provenance = append_review_summary("syllabus.pdf", two_page_pdf(), SUMMARY, WHEN)
        text = seal_page_text(sealed).lower()
        for phrase in PROHIBITED:
            # "not a certification" is the mandated denial, not a claim.
            scrubbed = text.replace("not a certification", "")
            self.assertNotIn(phrase, scrubbed, f"Prohibited phrase '{phrase}' on the seal page")
        boundary = provenance["claim_boundary"].lower().replace("not a certification", "")
        for phrase in PROHIBITED:
            self.assertNotIn(phrase, boundary)

    def test_empty_summary_lists_still_seal_honestly(self):
        summary = {"lanes": {}, "applied_fixes": [], "verified": []}
        sealed, provenance = append_review_summary("doc.pdf", untagged_pdf(), summary, WHEN)
        text = seal_page_text(sealed)
        self.assertIn("No automated fixes were applied.", text)
        self.assertIn("No verified signals were recorded.", text)
        self.assertEqual(provenance["applied_fixes_count"], 0)


class SealDeclineTests(unittest.TestCase):
    def test_encrypted_pdf_declines_with_clear_message(self):
        with self.assertRaises(RemediationError) as context:
            append_review_summary("locked.pdf", encrypted_pdf(), SUMMARY, WHEN)
        self.assertIn("Encrypted", str(context.exception))

    def test_garbage_bytes_decline(self):
        with self.assertRaises(RemediationError):
            append_review_summary("junk.pdf", b"this is not a pdf at all", SUMMARY, WHEN)

    def test_empty_bytes_decline(self):
        with self.assertRaises(RemediationError):
            append_review_summary("empty.pdf", b"", SUMMARY, WHEN)

    def test_missing_date_declines(self):
        with self.assertRaises(RemediationError):
            append_review_summary("doc.pdf", untagged_pdf(), SUMMARY, "  ")

    def test_malformed_lane_counts_decline(self):
        with self.assertRaises(RemediationError):
            append_review_summary("doc.pdf", untagged_pdf(),
                                  {"lanes": {"needs_attention": "two"}}, WHEN)

    def test_non_mapping_summary_declines(self):
        with self.assertRaises(RemediationError):
            append_review_summary("doc.pdf", untagged_pdf(), ["not", "a", "dict"], WHEN)


class SealProvenanceTests(unittest.TestCase):
    def test_provenance_declares_kind_seal_and_mutation(self):
        source = untagged_pdf()
        _, provenance = append_review_summary("doc.pdf", source, SUMMARY, WHEN)
        self.assertEqual(provenance["kind"], "seal")
        self.assertTrue(provenance["mutates_document"])
        self.assertTrue(provenance["deterministic"])
        self.assertEqual(provenance["filename"], "doc.pdf")
        self.assertEqual(provenance["source_sha256"], f"sha256:{sha256(source).hexdigest()}")
        self.assertTrue(provenance["result_sha256"].startswith("sha256:"))
        self.assertIn("not a certification", provenance["claim_boundary"])
        self.assertEqual(provenance["verification"],
                         {"pages_appended": True, "prior_text_preserved": True})

    def test_provenance_fields_are_deterministic_across_runs(self):
        source = two_page_pdf()
        first_bytes, first = append_review_summary("doc.pdf", source, SUMMARY, WHEN)
        second_bytes, second = append_review_summary("doc.pdf", source, SUMMARY, WHEN)
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first, second)


class PartnerAdsContractTests(unittest.TestCase):
    REQUIRED_FIELDS = ("id", "name", "tagline", "message", "cta_label")

    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(Path("partner_ads.json").read_text())

    def test_top_level_contract_fields(self):
        self.assertIsInstance(self.config["disclosure"], str)
        self.assertTrue(self.config["disclosure"].strip())
        self.assertIn("Sponsored", self.config["disclosure"])
        self.assertIsInstance(self.config["rotation_seconds"], int)
        self.assertGreater(self.config["rotation_seconds"], 0)
        self.assertIsInstance(self.config["partners"], list)
        self.assertTrue(self.config["partners"])

    def test_every_partner_carries_all_contract_fields(self):
        for partner in self.config["partners"]:
            for field in self.REQUIRED_FIELDS:
                self.assertIn(field, partner, f"Partner {partner.get('id')} missing '{field}'")
                self.assertIsInstance(partner[field], str)
                self.assertTrue(partner[field].strip(), f"Partner {partner.get('id')} has empty '{field}'")

    def test_generic_placeholder_slot_exists_without_real_company_names(self):
        slots = [p for p in self.config["partners"] if p["id"] == "partner-slot"]
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]["name"], "Your partner here")

    def test_partner_copy_never_uses_prohibited_outcome_language(self):
        serialized = json.dumps(self.config).lower()
        for phrase in PROHIBITED:
            self.assertNotIn(phrase, serialized, f"Prohibited phrase '{phrase}' in partner_ads.json")


if __name__ == "__main__":
    unittest.main()
