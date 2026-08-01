import unittest
from pathlib import Path


class FindingsOrderingTests(unittest.TestCase):
    """Document findings render first, most severe first; tool limitations move aside."""

    def setUp(self):
        self.source = Path("local_reviewer.html").read_text()

    def test_document_findings_are_sorted_by_category_rank(self):
        self.assertIn(
            "const categoryRank={blocking_technical_failure:0,deterministic_defect:1,review_required:2,advisory:3}",
            self.source,
        )
        self.assertIn("categoryRank[a.category]", self.source)
        self.assertIn("categoryRank[b.category]", self.source)

    def test_tool_limitations_are_split_out_of_the_main_list(self):
        self.assertIn("f.category!=='tool_failure_or_unsupported'", self.source)
        self.assertIn("f.category==='tool_failure_or_unsupported'", self.source)

    def test_first_document_finding_is_auto_selected(self):
        self.assertIn("if(firstRow)showDetail(docFindings[0],firstRow)", self.source)


class HeadlineCountTests(unittest.TestCase):
    """The summary counts only document findings, never tool limitations."""

    def setUp(self):
        self.source = Path("local_reviewer.html").read_text()

    def test_headline_counts_document_findings_only(self):
        self.assertIn("' in this document'", self.source)
        self.assertIn("docFindings.length", self.source)
        self.assertNotIn("findings.length?findings.length+' item'", self.source)

    def test_zero_document_findings_keeps_the_no_items_copy(self):
        self.assertIn("'No detectable items'", self.source)
        self.assertIn("'A quick human check is still recommended.'", self.source)

    def test_tool_limitations_get_their_own_line_in_the_completeness_block(self):
        self.assertIn("could not run on this computer", self.source)
        self.assertIn("not counted in the document findings above", self.source)


class ReviewCompletenessBlockTests(unittest.TestCase):
    """not_assessed areas and tool limitations live in a collapsed details block."""

    def setUp(self):
        self.source = Path("local_reviewer.html").read_text()

    def test_completeness_block_is_a_collapsed_details_element(self):
        self.assertIn("document.createElement('details')", self.source)
        self.assertIn("completeness.id='completeness'", self.source)
        self.assertIn("summaryEl.textContent='Could not be checked or assessed (", self.source)

    def test_not_assessed_areas_render_with_area_and_reason(self):
        self.assertIn("report.not_assessed||[]", self.source)
        self.assertIn("'Not assessed by this tool: '+(item.area||'')+' — '+(item.reason||'')", self.source)

    def test_absent_not_assessed_is_tolerated(self):
        # Older reports have no not_assessed key; the block only renders when needed.
        self.assertIn("if(toolFindings.length||notAssessed.length)", self.source)


class PageAnchorTests(unittest.TestCase):
    """Findings with a .pages list show the affected pages in the evidence line."""

    def setUp(self):
        self.source = Path("local_reviewer.html").read_text()

    def test_finding_rows_show_page_numbers_when_present(self):
        self.assertIn("f.pages&&f.pages.length", self.source)
        self.assertIn("' · Page'+(f.pages.length>1?'s':'')+' '+f.pages.join(', ')", self.source)


class ReadingOrderTests(unittest.TestCase):
    """The tag-tree builder lets a human reorder blocks and sends reading_order."""

    def setUp(self):
        self.source = Path("local_reviewer.html").read_text()

    def test_up_and_down_buttons_are_accessible(self):
        self.assertIn("'Move block '+(index+1)+' earlier in the reading order'", self.source)
        self.assertIn("'Move block '+(index+1)+' later in the reading order'", self.source)
        self.assertIn("up.textContent='Move up'", self.source)
        self.assertIn("down.textContent='Move down'", self.source)

    def test_position_changes_are_announced_politely(self):
        self.assertIn("orderStatus.setAttribute('aria-live','polite')", self.source)
        self.assertIn("' moved to position '", self.source)

    def test_reading_order_is_sent_only_when_it_differs_from_identity(self):
        self.assertIn(
            "if(order.some((value,position)=>value!==position))payload.reading_order=order.slice()",
            self.source,
        )
        self.assertIn("applyFixJson('/api/fix-structure',payload,apply)", self.source)

    def test_block_list_scrolls_and_apply_button_stays_reachable(self):
        self.assertIn(".fixlab .blocklist{max-height:340px;overflow-y:auto", self.source)
        self.assertIn(".fixlab .applybar{position:sticky;bottom:0", self.source)
        self.assertIn("applyBar.className='applybar'", self.source)

    def test_apply_button_copy_is_unchanged(self):
        self.assertIn("Build tag tree from my confirmations and re-check", self.source)


class OcrReviewPanelTests(unittest.TestCase):
    """After an OCR fix, the recognized words are shown for human review."""

    def setUp(self):
        self.source = Path("local_reviewer.html").read_text()

    def test_panel_renders_from_the_remediation_words_contract(self):
        self.assertIn("function renderOcrReview(result)", self.source)
        self.assertIn("Review the recognized text", self.source)
        self.assertIn("const words=action.words", self.source)

    def test_low_confidence_words_are_highlighted_with_their_confidence(self):
        self.assertIn("word.conf<60", self.source)
        self.assertIn('<mark class="lowconf" title="OCR confidence ', self.source)

    def test_truncated_word_lists_are_disclosed(self):
        self.assertIn("action.words_truncated", self.source)
        self.assertIn("This word list was shortened", self.source)

    def test_machine_generated_boundary_line_stays_visible(self):
        self.assertIn("ocr-boundary", self.source)
        self.assertIn("machine-generated OCR output", self.source)

    def test_panel_is_cleared_on_new_reviews_and_new_documents(self):
        reset_body = self.source.split("function resetDocumentState()", 1)[1].split("}", 1)[0]
        self.assertIn("ocrReview", reset_body)
        render_body = self.source.split("function render(report)", 1)[1]
        self.assertIn("document.getElementById('ocrReview').classList.remove('show')", render_body)


class DetailPanelResetTests(unittest.TestCase):
    """A report with no document findings must not keep the previous finding's detail."""

    def setUp(self):
        self.source = Path("local_reviewer.html").read_text()

    def test_render_resets_detail_when_nothing_is_auto_selected(self):
        # Regression: after a fix resolved every document finding (or a report
        # carried only tool limitations), the detail panel kept showing the
        # previously selected finding's guidance from the earlier report.
        self.assertIn(
            "if(firstRow)showDetail(docFindings[0],firstRow);else resetDetailPanel(",
            self.source,
        )

    def test_reset_detail_panel_restores_the_neutral_state(self):
        self.assertIn("function resetDetailPanel(message)", self.source)
        self.assertIn("document.getElementById('detailTitle').textContent='Select a finding'", self.source)
        self.assertIn("document.getElementById('teach').innerHTML=''", self.source)

    def test_no_selection_message_stays_outcome_neutral(self):
        message = "No document finding is selected — this review surfaced none to select."
        self.assertIn(message, self.source)


class PriorityZeroAccessibilityTests(unittest.TestCase):
    """Core intake and Improve controls remain operable under keyboard and reflow."""

    def setUp(self):
        self.source = Path("local_reviewer.html").read_text()

    def test_pdf_input_remains_in_the_keyboard_focus_order(self):
        input_tag = self.source.split('<input id="pdf"', 1)[1].split(">", 1)[0]
        self.assertIn('class="file-picker"', input_tag)
        self.assertNotIn("hidden", input_tag)
        self.assertIn('aria-describedby="pdfPrivacy"', input_tag)

    def test_pdf_input_has_an_explicit_visible_label(self):
        self.assertIn('<label class="upload-title" for="pdf">Choose a PDF</label>', self.source)

    def test_pdf_input_can_shrink_inside_a_320px_layout(self):
        self.assertIn(".file-picker{display:block;width:100%;min-width:0", self.source)

    def test_narrow_layout_hides_only_the_setup_guide(self):
        self.assertIn(
            ".layout{grid-template-columns:1fr}#guide{display:none}"
            ".detail .side{display:block;position:static}",
            self.source,
        )
        self.assertNotIn(".layout{grid-template-columns:1fr}.side{display:none}", self.source)


class PriorityTwoActionWorkspaceTests(unittest.TestCase):
    """Results become a semantic action queue without changing report contracts."""

    def setUp(self):
        self.source = Path("local_reviewer.html").read_text()

    def test_internal_categories_are_mapped_only_in_the_presentation(self):
        self.assertIn("label:'Fix now'", self.source)
        self.assertIn("new Set(['blocking_technical_failure','deterministic_defect'])", self.source)
        self.assertIn("label:'Needs your judgment'", self.source)
        self.assertIn("new Set(['review_required','advisory'])", self.source)
        self.assertIn("group.categories.has(f.category)", self.source)

    def test_tool_limitations_stay_in_a_separate_collapsed_block(self):
        self.assertIn("document.createElement('details')", self.source)
        self.assertIn("Could not be checked or assessed", self.source)
        self.assertIn("listed here as tool limitations", self.source)

    def test_findings_control_one_labeled_action_workspace(self):
        self.assertIn('aria-label="Prioritized action queue"', self.source)
        self.assertIn('aria-labelledby="detailTitle"', self.source)
        self.assertIn('class="workspace-label">Action workspace', self.source)
        self.assertIn("row.setAttribute('aria-controls','detail')", self.source)

    def test_selection_exposes_only_one_current_finding(self):
        self.assertIn("x.removeAttribute('aria-current')", self.source)
        self.assertIn("row.setAttribute('aria-current','true')", self.source)

    def test_explicit_selection_moves_focus_to_the_updated_heading(self):
        self.assertIn('id="detailTitle" tabindex="-1"', self.source)
        self.assertIn("row.onclick=()=>showDetail(f,row,true)", self.source)
        self.assertIn("if(userInitiated){detailTitle.focus({preventScroll:true})", self.source)
        self.assertIn("detail.scrollIntoView({block:'nearest'})", self.source)

    def test_narrow_selection_expands_inline_beneath_the_finding(self):
        self.assertIn("window.matchMedia('(max-width:760px)')", self.source)
        self.assertIn("selectedFindingRow.insertAdjacentElement('afterend',detail)", self.source)
        self.assertIn("detail.classList.toggle('inline-detail',inline)", self.source)
        self.assertIn("else layout.appendChild(detail)", self.source)


class NewDocumentResetTests(unittest.TestCase):
    """Choosing a new PDF must clear every per-document artifact of the last review."""

    def setUp(self):
        self.source = Path("local_reviewer.html").read_text()
        self.reset_body = self.source.split("function resetDocumentState()", 1)[1].split("\nfunction ", 1)[0]

    def test_output_chips_are_cleared_for_the_new_document(self):
        # Regression: "✓ Updated PDF" earned on document A stayed lit while
        # reviewing document B, implying outputs that were never produced.
        self.assertIn("['outPdf','outHtml','outReceipt']", self.reset_body)
        self.assertIn("chip.classList.remove('done')", self.reset_body)
        self.assertIn("chip.textContent.replace(/^✓ /,'')", self.reset_body)

    def test_meta_line_returns_to_its_pre_review_copy(self):
        self.assertIn("document.getElementById('meta').textContent='PDF only'", self.reset_body)

    def test_detail_panel_is_reset_with_the_document(self):
        self.assertIn("resetDetailPanel()", self.reset_body)

    def test_workflow_returns_to_step_one(self):
        self.assertIn("setWorkflowStep(1)", self.reset_body)


class OutcomeLanguageTests(unittest.TestCase):
    """The workbench must never present a conformance or certification outcome."""

    BANNED = (
        "fully compliant",
        "guaranteed accessible",
        "passed accessibility",
        "certified accessible",
        "fully accessible",
    )

    def test_workbench_carries_no_prohibited_outcome_phrases(self):
        source = Path("local_reviewer.html").read_text().lower()
        for phrase in self.BANNED:
            self.assertNotIn(phrase, source)

    def test_summary_copy_never_declares_the_document_clean(self):
        source = Path("local_reviewer.html").read_text()
        self.assertIn("'A quick human check is still recommended.'", source)
        self.assertIn("it is not a conformance result", source)


if __name__ == "__main__":
    unittest.main()
