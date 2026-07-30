# Progress Ledger — PRD phases vs shipped evidence

> The permanent record of what has actually been built against the
> [PRD](prd-accessibility-learning-journey.md) and
> [AI architecture](ai-architecture-byok.md), beyond what individual pull
> requests describe. Every "shipped" claim below names its implementation and
> its tests — the same evidence-before-claims discipline the product itself
> enforces. Last updated: 2026-07-20.

## Post-merge review fixes (2026-07-20)

Three correctness findings from an automated review of the merged Learning-OS
PR, all verified against the code and fixed as a follow-up (`tests/test_review_hardening.py`):

- **Truthful evidence when the validator is absent.** When veraPDF cannot run
  (Docker or the pinned image missing), `check_pdf.py` no longer emits the
  `PDF.VERAPDF.UA1` advisory claiming "a report was generated." It emits a
  `PDF.VERAPDF.UNAVAILABLE` `tool_failure_or_unsupported` finding instead, with
  its own teaching card.
- **Graceful degradation for encrypted PDFs without qpdf.** `analyze()` now
  honors pypdf's own `is_encrypted` verdict before touching pages, so a
  password-protected file returns a blocking-intake report instead of raising
  when qpdf is unavailable.
- **No cross-document evidence leak.** The workbench resets all
  document-scoped state (`lastReport`, `lastFix`, `attestations`, fixed-copy
  bytes) and returns to the pre-review layout when a new PDF is chosen, so an
  exported receipt can never describe a previous document.

## Engineering loop — gamification + BYOK intelligence (2026-07-22)

- **Motivational design shipped (PRD §12):** Accessibility Points awarded only
  for evidence-producing actions (`tina/learning.py` `POINT_VALUES`), humane
  practice streaks with a grace day and no punitive language, six
  evidence-based badges, and named milestones — all derived deterministically
  from the existing event log, with an explicit "practice, not compliance"
  claim boundary. Workbench HUD shows points, streak, milestone progress,
  "+N points earned" celebrations, and badge chips.
  Tests: `tests/test_gamification.py`.
- **Coastline College Foundation interstitials:** authored, deterministic,
  disable-able ad breaks (`foundation_ads.json`) shown during scans and after
  verified fixes, with an explicit sponsor disclosure line. Governance-scanned
  like every other surface.
- **BYOK intelligence layer shipped (AI architecture Phase 1, Modes 2–3):**
  `tina/intelligence.py` — provider-neutral gateway (OpenAI-compatible:
  Ollama/vLLM/OpenRouter/OpenAI, plus Anthropic), capability handshake, keys
  held in process memory only and never present in status output, per-request
  egress manifest with explicit consent, evidence-only payloads inside an
  untrusted-data boundary, schema-validated output with prohibited-claim
  rejection, and fail-closed fallback to the authored teaching card. One
  bounded task: `explain_finding` (Review Interpreter). Endpoints
  `/api/ai/configure`, `/api/ai/status`, `/api/ai/manifest`,
  `/api/ai/explain`. Tests: `tests/test_intelligence.py` (fake loopback
  model endpoint; consent, key-leak, prohibited-claim, injection-boundary,
  fail-closed cases). The deterministic engine remains the sole authority
  for findings, mutations, rechecks, and receipts.

## Engineering loop — micro-lessons and the practiced state (2026-07-24)

- **Authored micro-lessons shipped (PRD §11, next-loop Increment 1):**
  `lesson_content.json` carries one lesson per skill in the skill map, each
  following the full encounter → experience → explain → decide → verify →
  transfer sequence. `tina/lessons.py` loads, validates (unknown skill,
  duplicate id, out-of-range answer, missing rationale, exactly one decide
  step), and scores by exact match — no generation, no adaptive difficulty.
  The browser catalog withholds correct answers until scoring.
- **The `practiced` mastery state is now reachable.** A passed lesson advances
  a skill from `not_started`/`introduced` to `practiced` and never outranks
  real-document evidence (`applied`/`verified`/`sustained`). Regression after a
  recurrence falls back to `practiced` rather than erasing completed practice.
  Distinct lessons earn points once; a Guided Learner badge marks the first
  correct judgment call. Endpoints `GET /api/lessons`,
  `POST /api/lesson-result`; the finding detail panel offers "Practice this
  skill" inline. Tests: `tests/test_lessons.py` (including a coverage test that
  fails CI if any skill ships without a lesson).
- **Post-review hardening of the AI boundary (P1 from automated review):** the
  prohibited-claim validator caught only exact phrases, so a model could assert
  "This document passes WCAG 2.2" or "satisfies PDF/UA" and have it displayed.
  `tina/intelligence.py` now detects the *shape* of a conformance claim — an
  assertion verb pointed at a standard — alongside the phrase list, verified
  against eight claim phrasings with no false positives on legitimate
  explanations. Tests: `tests/test_intelligence.py`.

## Rescue loop — the Fix Lab: remediation depth (2026-07-24)

Product-owner review found the core miss: the PRD's Fix Lab (§14.4) was mostly
unbuilt — the product found and taught but repaired only two metadata fields.
This loop closes the remediation gap:

- **Fixable defects, itemized (checker):** `PDF.LINKS.NAME` — links lacking an
  accessible description (/Contents), per-link detail with URI and page; and
  `PDF.IMAGES.ALT_MISSING` — tagged figure elements lacking /Alt, per-figure
  detail. Fully-named links and fully-described figures become verified
  strengths on re-check, so these fixes are *provable*.
- **Semantic write-back (`SemanticRemediation`, `document.remediate.semantics`):**
  attaches human-authored link descriptions to any PDF and figure alt text to
  tagged PDFs, with before/after hashes and `user_authored` provenance. On
  untagged PDFs the alt path declines honestly and routes to the HTML rebuild
  — refusal over faked success. `POST /api/fix-semantics` runs review → apply
  → re-review; `POST /api/images` shows the human what they are describing.
- **AI that helps fix (architecture §19–20):** `draft_alt_text` sends one
  image + nearby text (consent-gated, vision) and returns a labeled draft the
  human approves or rewrites — the model can never mark an image decorative;
  `propose_structure` sends extracted text blocks (manifest explicitly warns
  document text leaves) and returns allowlisted roles (h1/h2/h3/p/li) by block
  index only — the model never rewrites text, phantom indexes and off-list
  roles are rejected, and the deterministic serializer builds the draft with
  each proposal marked `data-proposed="model"` for human confirmation.
  `POST /api/convert-structured` applies confirmed/proposed roles, including
  list grouping.
- **Fix Lab UI:** per-link and per-figure panels with image previews, AI draft
  buttons with inline egress consent, apply-and-recheck; an outcome tracker
  ("Updated PDF / Accessible HTML / Evidence receipt") so every session ends
  with the accessible assets, not a report.

Tests: `tests/test_fixlab.py` (13) + drafting-task tests in
`tests/test_intelligence.py` (6); 124 total. Browser-verified end to end.

## Agent storm — tag trees and OCR text layers (2026-07-29)

The two hardest remaining in-place repairs, built by a parallel agent
pipeline (scout → build → adversary per track, six agents), then integrated
and browser-verified:

- **Human-confirmed tag-tree building (`tina/structure.py`,
  `StructureRemediation`, `document.remediate.structure`):** on an untagged
  PDF, the human confirms each extracted text block's role (h1/h2/h3/p/li,
  optional logical reading order) and the tool wraps every text run in
  marked content (BDC/EMC with MCIDs), builds
  StructTreeRoot → Document → leaf structure elements (consecutive list
  items grouped under /L → /LI → /LBody), and wires the ParentTree. The
  **anti-vandal contract** is asserted, never trusted: the output is
  re-opened with a fresh parser and must show identical page count and
  per-page extracted text, or no bytes leave the tool. It declines honestly —
  already-tagged PDFs, any existing marked content (including MP/DP),
  encrypted files, blocks that cannot be mapped 1:1 onto content runs,
  conflicting or malformed confirmations, non-permutation reading orders —
  and routes to the HTML rebuild instead of guessing.
- **OCR text layers for scans (`tina/ocr.py`, `OcrRemediation`,
  `document.remediate.ocr`):** pages that are a single full-page scan image
  with no extractable text gain an invisible (text rendering mode 3),
  positionally mapped text layer from local tesseract (word confidence
  floor 40). The scan image is never altered, texted pages are untouched
  (verified after the fact), provenance is `ocr_generated`, and the report
  says plainly that recognition errors are likely and a human must review.
  Declines honestly: no eligible pages, rotated pages, degenerate geometry,
  nothing legible, engine missing or timing out.
- **Adversary pass found and fixed 9 real defects** before integration,
  including silent role-key collisions, reading-order coercion that applied
  unconfirmed structure, an MP/DP marked-content blind spot, a KeyError
  crash on image-only pages without content streams, and OCR text collapsing
  on zero-area pages — each now a regression test.
- **Integration:** `POST /api/fix-structure`, `POST /api/fix-ocr`,
  `POST /api/blocks`; Fix Lab panels on the tags/reading-order and
  extractable-text findings (block-by-block role confirmation with optional
  consent-gated AI proposals, one-click OCR apply); knowledge cards updated;
  both modules under the outcome-language governance scan; CI now installs
  tesseract so the real OCR path runs.

Tests: `tests/test_structure.py` (30) + `tests/test_ocr.py` (18) + endpoint
tests in `tests/test_fixlab.py` (5 new); 177 total. Browser-verified: an
untagged three-block PDF gained a verified structure tree from confirmed
roles, and a scanned page's extractable-text finding resolved after OCR.

## UI-debt + hosted-testing storm (2026-07-30)

A second agent storm (7 agents: 3 engine, 2 UI sequential, 2 adversaries)
driven by a live product-render review of the merged build:

- **The report points at the document and admits its limits
  (`check_pdf.py`):** every report now carries `not_assessed` — visual
  contrast, table structure semantics, form field labels, color-only
  meaning, plus dynamic entries when qpdf/veraPDF are unavailable — and
  findings gain `pages` anchors (which pages lack text, hold unnamed links,
  contain images).
- **Findings UX debt paid (`local_reviewer.html`):** document findings
  sorted by actionability and counted honestly ("N items in this
  document"); tool limitations and the not-assessed lanes live in a
  collapsed "Review completeness" strip instead of leading the page; the
  first *document* finding is auto-selected.
- **Engine capabilities finally surfaced:** the tag-tree builder gained
  accessible Up/Down **reading-order** controls (the engine validated
  permutations since the first storm; the UI never exposed them), and the
  OCR fix now shows a **"Review the recognized text"** panel — words per
  page with low-confidence highlighting — so the human review the claim
  boundary requires is actually possible in place. `tina/ocr.py` reports
  the applied words (capped at 400, truncation disclosed).
- **Design convergence:** the workbench adopted the staging shell's design
  system — navy header, porcelain surfaces, serif display headings, copper
  repair emphasis, the four-lane chip language (Needs attention / Review
  recommended / Verified signal / Not assessed), and the Add material →
  Review → Improve → Check again path rail. One product, two deployment
  modes. The landing hero's dead image region was fixed with a graceful
  fallback.
- **Hosted testing path (`service/`):** a new explicit
  `HUB_ALLOW_HOSTED_SYNTHETIC` opt-in (byte-exact `"true"` only) lets the
  Render-deployed staging service run the bundled synthetic-handout flow
  hosted — access-code gated, audit-recorded, still zero upload routes;
  the queued-assessment page now genuinely auto-refreshes (the old inline
  script was silently blocked by the page's own CSP); the doc gained a
  click-by-click Render runbook.
- **Adversaries found and fixed:** a stale detail panel on reports with no
  document findings, a cross-document output-chip leak in
  `resetDocumentState`, and a request-handler crash on malformed
  Content-Length in the staging service. Every hosted-boundary probe held:
  no upload path exists with or without the flag, flag-value strictness
  verified against 15+ variants, secrets never leak into HTML/logs/healthz.

Tests: 240 total (was 185). Browser-verified before/after across the
workbench, landing, and staging surfaces.

## Phase status at a glance

| PRD phase | Status |
|---|---|
| 1. Honest Local Review | **Shipped** (spike scope: PDF only) |
| 2. Fix and Verify | **Shipped** (metadata, link-name, and alt-text repairs; human-confirmed tag-tree building; OCR text layers; evidence receipts; judgment attestations) |
| 3. Learning Journey | **Substantially shipped** (evidence-based mastery incl. practiced via authored micro-lessons, points/streaks/badges, repeat-defect tracking; challenges and portfolio not yet built) |
| 4. HTML Escape Hatch | **Shipped** (extraction draft + offline editor; AI-assisted reconstruction not built) |
| 5. Institutional Transformation | **Not started** (design only: `tina-private-beta-intake.md`) |
| AI intelligence layer | **Not started by design** (architecture doc governs any future work; Mode 1 "Deterministic Only" is the shipped product) |

## Phase 1 — Honest Local Review · SHIPPED

- Deterministic chain qpdf → pypdf → pinned veraPDF with finding categories
  (`check_pdf.py`); loopback-only workbench (`local_reviewer.py`,
  `local_reviewer.html`).
- Findings split exactly as PRD §14.2 requires: technical findings /
  needs-your-judgment / could-not-review, plus **verified strengths**
  (`check_pdf.py` `strengths`, shown as individual machine evidence, never
  aggregated — enforced by `tests/test_evidence.py`).
- Missing tools degrade to explicit `tool_failure_or_unsupported` findings
  instead of crashing (`tests/test_fix_endpoint.py`).
- **Outcome-language governance (PRD §6.1) is a CI gate:**
  `tests/test_evidence.py::OutcomeLanguageGovernanceTests` fails the build if
  any product surface uses prohibited phrases ("fully compliant", "certified
  accessible", "passed accessibility", …).

## Phase 2 — Fix and Verify · SHIPPED

- Permission-gated repairs to an in-memory copy: `tina/remedy.py`
  (`document.remediate.metadata`; title + `/DisplayDocTitle`, primary
  language `/Lang`) with before/after hashes. Tests: `tests/test_remedy.py`.
- Recheck workflow: `POST /api/fix` runs review → mutate copy → re-review in
  one call (`local_reviewer.py`); UI shows the PRD §14.6 outcome ("6 before,
  4 after; resolved: …"). Tests: `tests/test_fix_endpoint.py`.
- **Evidence receipts (PRD §17):** `tina/evidence.py` — fingerprints in/out,
  tool and ruleset versions, checks performed and not performed, findings
  before/after, resolved rules, mutation provenance, human decisions,
  unresolved items, required disclaimer, and a verifiable integrity hash
  (`verify_receipt_integrity`). Endpoint `POST /api/receipt`; workbench
  "Export evidence receipt". Tests: `tests/test_evidence.py`,
  `tests/test_journey_endpoints.py`.
- **Judgment attestations (Judgment Queue seed, PRD §14.5):**
  `review_required` findings carry a "Record your judgment" flow in the
  workbench; decisions are recorded as `user_attested` in receipts and feed
  mastery. Endpoint `POST /api/attest`.

## Phase 3 — Learning Journey · TRACER BULLET SHIPPED

- **Deterministic learning engine:** `tina/learning.py`. Skill map keyed to
  PRD worlds (titles/language, structure, images, links, scans, integrity);
  every mastery transition requires evidence, per PRD §6.3/§12.4:
  - *Introduced* — the defect appeared in a real reviewed document.
  - *Applied* — the user attested a judgment or applied a fix.
  - *Verified* — a repair was rechecked and the finding resolved.
  - *Sustained* — the defect has not recurred across ≥2 subsequent distinct
    documents; regression resets mastery.
- **Repeat-defect tracking (north-star metric, PRD §18):** a skill whose
  findings appear across ≥2 distinct documents becomes a repeat defect with
  a deterministic recommendation (PRD §13 — no AI).
- **Privacy:** the local journey store records only 16-char hash prefixes,
  rule IDs, attested decisions, and timestamps — never filenames or content
  (enforced by `tests/test_learning.py`).
- Surfaces: `GET /api/journey`; "Your learning journey" panel in the
  workbench with mastery chips and the path to *sustained*.
- **Not yet built:** authored micro-lessons, guided challenges, practice
  scenarios, spaced review, points/streaks, portfolio (PRD §11, §12.2–12.6,
  §14.8–14.9). The mastery/state machinery these attach to now exists.

## Phase 4 — HTML Escape Hatch · SHIPPED

- `tina/derive.py` (`document.derive.html_draft`, non-mutating) converts a
  PDF into a structured HTML draft; the draft embeds a fully offline
  improvement toolbar (title, language, heading toggle, in-place text
  correction, per-image describe-or-decorative decisions, live checklist)
  and a clean-HTML export that strips all editing chrome. Endpoint
  `POST /api/convert`. Tests: `tests/test_html_draft.py`; browser-driven
  verification in headless Chromium.
- **Not yet built:** lists/tables/landmarks tooling in the draft editor;
  AI-assisted AST reconstruction (architecture doc §20 governs it).

## Phase 5 — Institutional Transformation · NOT STARTED

Design exists in `tina-private-beta-intake.md` (deployable slice, states,
security gates). No cohorts, campaigns, dashboards, or metadata sync are
implemented. Nothing shipped contradicts the privacy architecture: there is
no telemetry of any kind today.

## AI intelligence layer · NOT STARTED, BY DESIGN

The shipped product is Mode 1 ("Deterministic Only") of
[`ai-architecture-byok.md`](ai-architecture-byok.md). Positioning has been
updated accordingly: the workbench now says "works without AI" rather than
"no AI." Before any AI work begins, the acceptance criteria in §31 of that
document apply in full — starting with "remains functional with no model
configured," which is trivially true today because that is the whole
product.

## Architecture invariants currently enforced by tests

1. Every tool is registered, versioned, permission-scoped, and declares its
   mutation status (`tina/kernel.py`; `tests/test_tina_kernel.py`).
2. Mutations only ever touch copies; provenance hashes recorded
   (`tests/test_remedy.py`).
3. Every checker rule ships with a teaching card
   (`tests/test_fix_endpoint.py::KnowledgeCoverageTests`).
4. Prohibited outcome language fails CI
   (`tests/test_evidence.py::OutcomeLanguageGovernanceTests`).
5. Receipts are integrity-hashed and tamper-evident
   (`tests/test_evidence.py`).
6. Mastery cannot advance without evidence; regression demotes it
   (`tests/test_learning.py`).
7. The learning store never contains document content or full hashes
   (`tests/test_learning.py`).
8. The veraPDF container never pulls images or touches the network during a
   check (`tests/test_pdf_worker_hardening.py`).

## Recommended next loop (in order)

The next loop is fully specified as an executable, self-contained work order
in [`next-loop-prd.md`](next-loop-prd.md) (written for pickup in a fresh
agent/tool with no session context). Summary of its five increments:

1. Authored micro-lessons attached to knowledge cards (PRD §11's
   encounter→transfer sequence) and the *practiced* mastery state they
   unlock.
2. Alt-text writing back into PDFs (`/Alt`) for the PDF-must-remain cases —
   the first Class-2 user-supplied-semantics repair from architecture §12,
   with an honest tagged-vs-untagged decline path.
3. Page rendering with findings anchored to locations.
4. Lists/tables/landmarks in the HTML draft editor.
5. Ground-truth corpus (architecture §23) before widening the rule set,
   including known-good documents that must not be "fixed."

Beyond this loop: the Phase 5 "first implementation ticket" from
`tina-private-beta-intake.md` when cloud beta becomes a priority, and the AI
intelligence layer only after `ai-architecture-byok.md` §31 is addressed.
