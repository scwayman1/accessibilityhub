# Product assessment — July 2026

Goal stated for this pass: a fully functional product that **changes outcomes for
documents that are not accessible**, and that **works as a teaching tool**.

## Where the product stood before this pass

| Dimension | State | Evidence |
|---|---|---|
| Finds problems | Strong for a spike | Deterministic qpdf/pypdf/veraPDF chain, normalized findings, honest claim boundary |
| Changes outcomes | **Absent** | Read-only by design; every finding ended in "go fix it somewhere else" |
| Teaches | Thin | Findings carried a `next_action` sentence; no why/who/how; the delight engine was the only teaching voice |
| Trust and governance | Exceptional | Claim boundaries, permission-gated tool gateway, pinned validator, no-network worker, beta gates doc |
| Reach | One machine | Loopback-only workbench; crashed outright if qpdf was not installed |
| Deployability | Documented, not built | Beta intake doc specifies the cloud slice; none of it exists yet |

The honest summary: this was a very well-governed **camera**, not a **repair
shop**. It could photograph the problem beautifully and then handed the student
back their broken document. The governance work is genuinely ahead of most
commercial checkers — that is the moat, keep it — but zero findings ever got
*resolved inside the product*, so outcomes did not change.

## What this pass shipped

The closed loop that changes an outcome, end to end, still local-only:

```text
review → learn (per-rule teaching card) → fix a copy (permission-gated mutation)
→ re-review the copy → see findings resolve → download the updated PDF
```

- `tina/remedy.py` — first mutating tool, registered through the same
  `ToolGateway` with `mutates_document=True` and a dedicated
  `document.remediate.metadata` permission, outside the read-only kernel as the
  kernel contract requires. It fixes what is deterministically fixable today:
  document title (plus `/DisplayDocTitle`) and primary language (`/Lang`), and
  records before/after hashes for every mutation.
- `POST /api/fix` — one call runs review, remediation on an in-memory copy,
  and a second review, returning before/after reports plus the updated PDF.
  Fixes stack: the workbench keeps working from the updated copy.
- `rule_knowledge.json` + `GET /api/knowledge` — a teaching card for every rule
  the checker can emit (why it matters, who it affects, how to fix at the
  source, whether the tool can fix it). The knowledge-coverage test fails CI if
  a rule ever ships without its card.
- Degradation instead of crash — missing qpdf or Docker now yields an explicit
  `tool_failure_or_unsupported` finding; the review completes with the evidence
  it can gather.

The claim boundary holds: the fix banner says "resolves specific technical
findings; it is not a conformance result," and structural work (tags, reading
order, alternatives, OCR) stays routed to humans.

## Gap analysis to "fully functional product"

Ordered by outcome-changed-per-unit-effort:

1. **Alt-text authoring (next mutation).** Images are the most common finding in
   real course packets (seven in the fixture). Render each image in the
   workbench, let the reviewer write the description or mark it decorative, and
   write real `/Alt` entries into tagged content. This is the first fix that
   requires human judgment *inside* the loop — which is exactly the teaching
   moment.
2. **Ground-truth corpus.** The README already names it: validate the rule
   taxonomy against an accessibility-specialist-reviewed corpus before trusting
   the checker's coverage. Without it we do not know our false-negative rate.
3. **The deployable slice.** The beta intake doc's "first implementation
   ticket" (authenticated API, fake storage adapter, PostgreSQL state) is the
   bridge from one laptop to a department. Nothing in this pass blocks it; the
   fix loop drops into that worker model unchanged.
4. **Page-level visual context.** Findings currently point at "document
   catalog" and "page resources." Rendering pages (pdf.js) with findings
   anchored to locations turns the report into a workbench.
5. **Format expansion (DOCX before PPTX).** Fix-at-source is the pedagogy, and
   most course PDFs are born in Word. Checking the DOCX *before* export
   prevents the defect instead of repairing it.

## What not to build

- A general WYSIWYG PDF content editor (see `document-editor-vision.md`).
- Auto-tagging that claims conformance. Automated tag guessing without human
  review is how competitors turn inaccessible documents into differently
  inaccessible documents with a green checkmark.
- Any pass/fail badge. The category system (`deterministic_defect` vs
  `review_required`) is the product's most honest feature.
