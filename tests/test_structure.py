import io
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from check_pdf import analyze, indirect
from tina.derive import extract_blocks
from tina.kernel import ToolPermissionError
from tina.remedy import RemediationError
from tina.structure import REMEDIATE_STRUCTURE_PERMISSION, StructureRemediation
from tests.test_fixlab import build_pdf, tagged_figure_pdf, untagged_pdf


def content_pdf(stream: bytes) -> bytes:
    """Single untagged page carrying the given content stream."""
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ])


def syllabus_pdf() -> bytes:
    """Five text blocks: heading, subheading, paragraph, two list items."""
    return content_pdf(
        b"BT /F1 12 Tf 72 720 Td (Course Syllabus) Tj "
        b"0 -30 Td (Weekly plan) Tj "
        b"0 -30 Td (Week one covers foundations.) Tj "
        b"0 -30 Td (First topic in the list) Tj "
        b"0 -30 Td (Second topic in the list) Tj "
        b"ET"
    )


def three_block_pdf() -> bytes:
    return content_pdf(
        b"BT /F1 12 Tf 72 720 Td (Alpha item) Tj "
        b"0 -30 Td (Bridge paragraph.) Tj "
        b"0 -30 Td (Omega item) Tj "
        b"ET"
    )


def two_page_pdf() -> bytes:
    first = b"BT /F1 12 Tf 72 720 Td (Chapter one) Tj ET"
    second = b"BT /F1 12 Tf 72 720 Td (Body text on page two.) Tj ET"
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


def run_analyze(payload: bytes) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        pdf = Path(directory) / "doc.pdf"
        pdf.write_bytes(payload)
        return analyze(pdf, Path(directory) / "out")


def kid_elements(node) -> list:
    kids = indirect(indirect(node).get("/K"))
    kids = kids if isinstance(kids, list) else [kids]
    return [indirect(kid) for kid in kids]


def document_element(payload: bytes):
    reader = PdfReader(io.BytesIO(payload))
    root = reader.trailer["/Root"].get_object()
    struct_root = indirect(root["/StructTreeRoot"])
    return reader, root, struct_root, kid_elements(struct_root)[0]


class ConfirmedTagTreeTests(unittest.TestCase):
    def test_confirmed_roles_build_a_walkable_verified_tag_tree(self):
        engine = StructureRemediation.with_builtin_tools()
        source = syllabus_pdf()
        before_text = PdfReader(io.BytesIO(source)).pages[0].extract_text()

        fixed, report = engine.apply(
            "doc.pdf", source, {"0": "h1", "1": "h2", "3": "li", "4": "li"},
        )

        reader, root, struct_root, document = document_element(fixed)
        self.assertTrue(indirect(root["/MarkInfo"])["/Marked"])
        self.assertEqual(str(document["/S"]), "/Document")
        kids = kid_elements(document)
        self.assertEqual([str(k["/S"]) for k in kids], ["/H1", "/H2", "/P", "/L"])
        items = kid_elements(kids[3])
        self.assertEqual([str(item["/S"]) for item in items], ["/LI", "/LI"])
        body = kid_elements(items[0])[0]
        self.assertEqual(str(body["/S"]), "/LBody")
        self.assertEqual(int(body["/K"]), 3)

        # MCIDs are wired through the ParentTree back to the leaf elements.
        nums = indirect(indirect(struct_root["/ParentTree"])["/Nums"])
        self.assertEqual(int(nums[0]), 0)
        slots = [indirect(entry) for entry in indirect(nums[1])]
        self.assertEqual([str(slot["/S"]) for slot in slots],
                         ["/H1", "/H2", "/P", "/LBody", "/LBody"])
        self.assertEqual([int(indirect(slot["/K"])) for slot in slots], [0, 1, 2, 3, 4])
        self.assertEqual(int(reader.pages[0]["/StructParents"]), 0)
        self.assertEqual(indirect(slots[0]["/Pg"]), reader.pages[0].get_object())

        # Text extraction is untouched and the checker's structure finding clears.
        self.assertEqual(reader.pages[0].extract_text(), before_text)
        recheck = run_analyze(fixed)
        self.assertNotIn("PDF.STRUCTURE.SEMANTICS", {f["rule_id"] for f in recheck["findings"]})
        self.assertIn("PDF.STRUCTURE.SEMANTICS", {s["rule_id"] for s in recheck["strengths"]})

        self.assertEqual(report["contract_version"], "tina-remediation-report/v1")
        self.assertTrue(report["mutates_document"])
        action = report["actions"][0]
        self.assertEqual(action["rule_id"], "PDF.STRUCTURE.SEMANTICS")
        self.assertEqual(action["action"], "build_confirmed_tag_tree")
        self.assertEqual(action["provenance"], "user_confirmed")
        self.assertEqual(action["counts"], {"blocks_tagged": 5, "headings": 2, "list_items": 2})
        self.assertFalse(action["reading_order_applied"])
        self.assertEqual(report["verification"], {"text_preserved": True, "pages_preserved": True})
        self.assertNotEqual(report["source_sha256"], report["remediated_sha256"])

    def test_consecutive_list_items_group_under_one_list_parent(self):
        engine = StructureRemediation.with_builtin_tools()
        fixed, _ = engine.apply("doc.pdf", syllabus_pdf(),
                                {"0": "h1", "3": "li", "4": "li"})
        _, _, _, document = document_element(fixed)
        kids = kid_elements(document)
        self.assertEqual([str(k["/S"]) for k in kids], ["/H1", "/P", "/P", "/L"])
        self.assertEqual(len(kid_elements(kids[3])), 2)

    def test_non_consecutive_list_items_get_separate_list_parents(self):
        engine = StructureRemediation.with_builtin_tools()
        fixed, _ = engine.apply("doc.pdf", three_block_pdf(), {"0": "li", "2": "li"})
        _, _, _, document = document_element(fixed)
        kids = kid_elements(document)
        self.assertEqual([str(k["/S"]) for k in kids], ["/L", "/P", "/L"])

    def test_blocks_without_a_confirmed_role_default_to_paragraph(self):
        engine = StructureRemediation.with_builtin_tools()
        fixed, report = engine.apply("doc.pdf", three_block_pdf(), {"0": "h1"})
        _, _, _, document = document_element(fixed)
        self.assertEqual([str(k["/S"]) for k in kid_elements(document)], ["/H1", "/P", "/P"])
        self.assertEqual(report["actions"][0]["counts"],
                         {"blocks_tagged": 3, "headings": 1, "list_items": 0})

    def test_reading_order_reorders_struct_elems_not_content(self):
        engine = StructureRemediation.with_builtin_tools()
        source = three_block_pdf()
        before_text = PdfReader(io.BytesIO(source)).pages[0].extract_text()
        fixed, report = engine.apply("doc.pdf", source, {"2": "h1"},
                                     reading_order=[2, 0, 1])
        reader, _, _, document = document_element(fixed)
        kids = kid_elements(document)
        self.assertEqual([str(k["/S"]) for k in kids], ["/H1", "/P", "/P"])
        # Logical order leads with block 2's MCID; the page content is unmoved.
        self.assertEqual([int(indirect(k["/K"])) for k in kids], [2, 0, 1])
        self.assertEqual(reader.pages[0].extract_text(), before_text)
        self.assertTrue(report["actions"][0]["reading_order_applied"])
        self.assertEqual(extract_blocks(fixed), extract_blocks(source))

    def test_reading_order_groups_list_items_in_logical_order(self):
        engine = StructureRemediation.with_builtin_tools()
        fixed, _ = engine.apply("doc.pdf", three_block_pdf(), {"0": "li", "2": "li"},
                                reading_order=[2, 0, 1])
        _, _, _, document = document_element(fixed)
        kids = kid_elements(document)
        self.assertEqual([str(k["/S"]) for k in kids], ["/L", "/P"])
        self.assertEqual(len(kid_elements(kids[0])), 2)

    def test_each_page_gets_its_own_parent_tree_key(self):
        engine = StructureRemediation.with_builtin_tools()
        fixed, report = engine.apply("doc.pdf", two_page_pdf(), {"0": "h1", "1": "p"})
        reader, _, struct_root, document = document_element(fixed)
        self.assertEqual([str(k["/S"]) for k in kid_elements(document)], ["/H1", "/P"])
        self.assertEqual(int(reader.pages[0]["/StructParents"]), 0)
        self.assertEqual(int(reader.pages[1]["/StructParents"]), 1)
        self.assertEqual(int(struct_root["/ParentTreeNextKey"]), 2)
        nums = indirect(indirect(struct_root["/ParentTree"])["/Nums"])
        self.assertEqual([int(nums[0]), int(nums[2])], [0, 1])
        self.assertEqual(report["verification"], {"text_preserved": True, "pages_preserved": True})


class TextIntegrityTests(unittest.TestCase):
    """Naive segmentation must either preserve extracted text exactly or decline."""

    def setUp(self):
        self.engine = StructureRemediation.with_builtin_tools()

    def assert_text_identical(self, source: bytes, fixed: bytes):
        before = [p.extract_text() or "" for p in PdfReader(io.BytesIO(source)).pages]
        after = [p.extract_text() or "" for p in PdfReader(io.BytesIO(fixed)).pages]
        self.assertEqual(before, after)

    def test_multiple_bt_et_blocks_survive_with_identical_text(self):
        source = content_pdf(
            b"BT /F1 12 Tf 72 720 Td (First block) Tj ET "
            b"BT /F1 12 Tf 72 690 Td (Second block) Tj ET"
        )
        fixed, report = self.engine.apply("doc.pdf", source, {"0": "h1"})
        self.assert_text_identical(source, fixed)
        self.assertEqual(report["actions"][0]["counts"]["blocks_tagged"], 2)

    def test_tj_kerning_numbers_are_not_text_and_text_is_identical(self):
        source = content_pdf(
            b"BT /F1 12 Tf 72 720 Td [(Hel) -250 (lo world)] TJ "
            b"0 -30 Td (Second line here.) Tj ET"
        )
        fixed, _ = self.engine.apply("doc.pdf", source, {"0": "h1", "1": "p"})
        self.assert_text_identical(source, fixed)

    def test_escaped_and_nested_parens_round_trip_exactly(self):
        source = content_pdf(
            b"BT /F1 12 Tf 72 720 Td (Hello \\(world\\) and (nested) \\101 end) Tj ET"
        )
        fixed, _ = self.engine.apply("doc.pdf", source, {"0": "h1"})
        self.assert_text_identical(source, fixed)

    def test_graphics_and_inline_images_survive_the_rewrite(self):
        source = content_pdf(
            b"0.5 0.2 0.9 rg 100 100 50 50 re f "
            b"BT /F1 12 Tf 72 720 Td (Before image) Tj ET "
            b"q BI /W 1 /H 1 /CS /RGB /BPC 8 ID \x00\x00\x00 EI Q "
            b"BT /F1 12 Tf 72 600 Td (After image) Tj ET"
        )
        fixed, _ = self.engine.apply("doc.pdf", source, {"0": "h1"})
        self.assert_text_identical(source, fixed)
        data = PdfReader(io.BytesIO(fixed)).pages[0].get_contents().get_data()
        for token in (b"BI", b"ID", b"EI", b"re", b"rg"):
            self.assertIn(token, data)

    def test_string_with_newline_escape_that_splits_blocks_is_declined(self):
        # One Tj run whose literal \n makes extract_text yield two blocks:
        # run-to-block matching would be ambiguous, so the tool declines.
        source = content_pdf(b"BT /F1 12 Tf 72 720 Td (Line1\\nLine2) Tj ET")
        with self.assertRaises(RemediationError) as context:
            self.engine.apply("doc.pdf", source, {"0": "h1"})
        self.assertIn("HTML working copy", str(context.exception))

    def test_text_hidden_in_a_form_xobject_is_declined_not_mistagged(self):
        form = b"BT /F1 12 Tf 0 0 Td (XObject text) Tj ET"
        page_stream = b"BT /F1 12 Tf 72 720 Td (Page text) Tj ET q /Fm1 Do Q"
        source = build_pdf([
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> /XObject << /Fm1 6 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(page_stream)).encode() + b" >>\nstream\n" + page_stream + b"\nendstream",
            b"<< /Type /XObject /Subtype /Form /BBox [0 0 200 50] "
            b"/Resources << /Font << /F1 4 0 R >> >> "
            b"/Length " + str(len(form)).encode() + b" >>\nstream\n" + form + b"\nendstream",
        ])
        with self.assertRaises(RemediationError) as context:
            self.engine.apply("doc.pdf", source, {"0": "h1"})
        self.assertIn("HTML working copy", str(context.exception))


class ConfirmedTagTreeDeclineTests(unittest.TestCase):
    def setUp(self):
        self.engine = StructureRemediation.with_builtin_tools()

    def test_bad_reading_order_permutation_is_declined(self):
        for bad_order in ([0, 1], [0, 1, 1], [0, 1, 5]):
            with self.assertRaises(RemediationError) as context:
                self.engine.apply("doc.pdf", three_block_pdf(), {"0": "h1"},
                                  reading_order=bad_order)
            self.assertIn("permutation", str(context.exception))

    def test_already_tagged_pdf_is_declined_not_rebuilt(self):
        with self.assertRaises(RemediationError) as context:
            self.engine.apply("doc.pdf", tagged_figure_pdf(), {"0": "h1"})
        self.assertIn("already carries a structure tree", str(context.exception))

    def test_encrypted_pdf_is_declined(self):
        with self.assertRaises(RemediationError) as context:
            self.engine.apply("doc.pdf", encrypted_pdf(), {"0": "h1"})
        self.assertIn("Encrypted", str(context.exception))

    def test_off_list_role_is_declined(self):
        with self.assertRaises(RemediationError) as context:
            self.engine.apply("doc.pdf", untagged_pdf(), {"0": "title"})
        self.assertIn("not supported", str(context.exception))

    def test_empty_roles_are_declined(self):
        with self.assertRaises(RemediationError):
            self.engine.apply("doc.pdf", untagged_pdf(), {})

    def test_unmatchable_block_index_routes_to_html_rebuild(self):
        blocks = extract_blocks(untagged_pdf())
        with self.assertRaises(RemediationError) as context:
            self.engine.apply("doc.pdf", untagged_pdf(), {str(len(blocks) + 8): "h1"})
        self.assertIn("HTML working copy", str(context.exception))

    def test_merged_runs_that_defeat_block_matching_are_declined(self):
        # Two Tj runs on one visual line merge into a single extracted block,
        # so MCID-to-block assignment would be ambiguous.
        source = content_pdf(
            b"BT /F1 12 Tf 72 720 Td (Hello ) Tj 40 0 Td (world) Tj "
            b"0 -30 Td (Second line.) Tj ET"
        )
        with self.assertRaises(RemediationError) as context:
            self.engine.apply("doc.pdf", source, {"0": "h1"})
        self.assertIn("HTML working copy", str(context.exception))

    def test_applying_to_its_own_output_is_declined(self):
        # Idempotence/no-clobber: the tool must refuse to rebuild over the
        # structure tree it just built.
        fixed, _ = self.engine.apply("doc.pdf", syllabus_pdf(), {"0": "h1"})
        with self.assertRaises(RemediationError) as context:
            self.engine.apply("doc.pdf", fixed, {"0": "h1"})
        self.assertIn("already carries a structure tree", str(context.exception))

    def test_existing_marked_content_without_a_tree_is_declined(self):
        for stream in (
            # BMC/EMC artifact sequence, no StructTreeRoot in the catalog.
            b"/Artifact BMC BT /F1 12 Tf 72 720 Td (Header art) Tj ET EMC "
            b"BT /F1 12 Tf 72 600 Td (Body text) Tj ET",
            # A marked-content point op is authored marked content too.
            b"/Tag MP BT /F1 12 Tf 72 720 Td (Body text) Tj ET",
        ):
            with self.assertRaises(RemediationError) as context:
                self.engine.apply("doc.pdf", content_pdf(stream), {"0": "h1"})
            self.assertIn("marked-content", str(context.exception))

    def test_non_pdf_and_empty_payloads_are_declined_not_crashed(self):
        for payload in (b"", b"hello, not a pdf", b"%PDF-1.4\ngarbage with no xref"):
            with self.assertRaises(RemediationError) as context:
                self.engine.apply("doc.pdf", payload, {"0": "h1"})
            self.assertIn("could not be parsed", str(context.exception))

    def test_integer_role_keys_are_accepted_like_their_string_forms(self):
        fixed, _ = self.engine.apply("doc.pdf", three_block_pdf(), {0: "h1", 2: "li"})
        _, _, _, document = document_element(fixed)
        self.assertEqual([str(k["/S"]) for k in kid_elements(document)], ["/H1", "/P", "/L"])

    def test_conflicting_duplicate_role_keys_are_declined_not_last_write_wins(self):
        # "1", "01", and 1 all name block 1; which confirmation would win is
        # dict-order luck, so conflicting confirmations must decline.
        for roles in ({"1": "h1", "01": "li"}, {"1": "h1", 1: "li"}):
            with self.assertRaises(RemediationError) as context:
                self.engine.apply("doc.pdf", syllabus_pdf(), roles)
            self.assertIn("more than once", str(context.exception))

    def test_non_canonical_index_keys_are_declined(self):
        # int() would quietly accept "1_0" as 10, " 1 " as 1, and "+1" as 1.
        for key in ("1_0", " 1", "1 ", "+1", "0x1", "", "one"):
            with self.assertRaises(RemediationError) as context:
                self.engine.apply("doc.pdf", syllabus_pdf(), {key: "h1"})
            self.assertIn("not a valid block index", str(context.exception))

    def test_negative_index_is_declined(self):
        with self.assertRaises(RemediationError) as context:
            self.engine.apply("doc.pdf", syllabus_pdf(), {"-1": "h1"})
        self.assertIn("HTML working copy", str(context.exception))

    def test_non_mapping_roles_and_non_string_role_values_decline_cleanly(self):
        for roles in (["h1", "p"], "h1", 42):
            with self.assertRaises(RemediationError) as context:
                self.engine.apply("doc.pdf", syllabus_pdf(), roles)
            self.assertIn("mapping", str(context.exception))
        for value in (1, None, ["h1"], b"h1"):
            with self.assertRaises(RemediationError) as context:
                self.engine.apply("doc.pdf", syllabus_pdf(), {"0": value})
            self.assertIn("not supported", str(context.exception))

    def test_reading_order_of_the_wrong_shape_is_declined_not_coerced(self):
        # A dict would be iterated as keys (ignoring the intended mapping), a
        # string char-by-char, floats truncated, bools reinterpreted — all of
        # which would apply an order the human never confirmed.
        for order in ({0: 1, 1: 0, 2: 2}, "210", [2.0, 0.0, 1.0], [True, False, 2], 5):
            with self.assertRaises(RemediationError) as context:
                self.engine.apply("doc.pdf", three_block_pdf(), {"0": "h1"},
                                  reading_order=order)
            self.assertIn("permutation", str(context.exception))

    def test_mutation_requires_the_structure_permission(self):
        with self.assertRaises(ToolPermissionError) as context:
            self.engine.gateway.execute(
                "build_confirmed_tag_tree",
                {"payload": untagged_pdf(), "confirmed_roles": {"0": "h1"}},
                set(),
            )
        self.assertIn(REMEDIATE_STRUCTURE_PERMISSION, str(context.exception))


if __name__ == "__main__":
    unittest.main()
