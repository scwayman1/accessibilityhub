# The best self-made document editor — vision

The question this document answers: if we build our own PDF/document editor,
what should it be?

## The core thesis: don't build a PDF editor

PDF is an output format — frozen print instructions with (optionally) a
semantic layer bolted on. Editing PDF content streams directly is the hardest
possible place to do accessibility work, which is why Acrobat's tag editor is
where remediation projects go to stall. Our own delight engine already states
the product philosophy: *"Fixing a source document is usually easier than
repairing an exported PDF."*

So the best self-made editor is **two tools sharing one evidence kernel**, and
neither is a general PDF editor:

## Tool 1 — the remediation workbench (repair what already exists)

This is today's local reviewer, grown up. Its unit of work is an existing PDF
that cannot be re-exported (source lost, third-party, scanned).

- **See the document, not the report.** Render pages (pdf.js) with findings
  anchored where they occur. A finding about images shows *the image*.
- **Guided fixes, smallest first.** Each fix is a permission-gated Tina tool
  with before/after hashes and an immediate re-check — the loop shipped in this
  pass. Ladder of mutations, in order of trustworthiness:
  1. Document metadata: title, language *(shipped)*
  2. Per-image `/Alt` text authored by a human, written by the tool
  3. Link purpose text, list/table repair on already-tagged documents
  4. Tag-tree and reading-order editing — a structure outline the reviewer
     drags into order, never raw tag surgery
- **OCR as intake, not magic.** A scanned page routes to an OCR lane whose
  output is always `review_required`, displayed side-by-side with the scan.
- **Teaching is the interface.** Every fix screen leads with the knowledge
  card: why, who, and how to prevent it next time. The workbench's success
  metric is not documents repaired — it is reviewers who stop producing the
  defect.

## Tool 2 — the accessible-by-default author (prevent the next one)

The endgame. A deliberately small structured editor where the document's
semantics *are* the document:

- **Structure-first model.** Headings, lists, tables, figures with required
  alt-text-or-decorative choice, link purpose text. Visual style derives from
  structure, so an untagged heading is unrepresentable. The blank-document
  flow asks for title and language before it asks for content.
- **HTML (or a constrained JSON doc model) as source of truth.** Accessible
  HTML is a first-class export, not an afterthought.
- **Tagged PDF as a build artifact.** Deterministic export path:
  structured source → WeasyPrint with the PDF/UA variant → our own checker and
  pinned veraPDF run against our own output in CI. The editor that ships a
  document proves its own export with the same evidence chain it applies to
  everyone else's — no other editor does this.
- **Teach while typing.** The same rule knowledge fires at authoring time:
  paste a wall of text and it suggests headings; add an image and the alt-text
  prompt explains *who* it is for. Delight engine included.

## Why two tools and not one

A repair tool must accept any malformed input and mutate it cautiously. An
authoring tool must make invalid documents impossible to express. Merging them
produces Acrobat. Keeping them separate lets each be honest: the workbench
never pretends repair equals conformance; the author never needs a repair mode.

Shared spine: Tina kernel (typed tools, permissions, evidence, claim
boundaries), the rule taxonomy, the knowledge cards, and the delight voice.

## Sequencing

1. **Now (shipped):** metadata fix loop with before/after evidence.
2. **Next:** image extraction + alt-text authoring in the workbench; page
   rendering with anchored findings.
3. **Then:** DOCX checking (fix-at-source for the dominant real workflow),
   ground-truth corpus validation of the taxonomy.
4. **Endgame:** the structured author with tagged-PDF export, once the checker
   is trusted enough to verify our own output. Cloud beta per
   `tina-private-beta-intake.md` can begin at any point after step 2 — the
   loop is architecture-compatible with the isolated-worker model.

## Boundaries that do not move

- No mutation without a registered, versioned, permission-scoped tool.
- No automated judgment calls: alt text, reading order, and OCR acceptance are
  human decisions the tool records as such.
- No conformance claims — the words "compliant," "certified," and
  "accessible" never appear as a pass claim, including for our own exports.
