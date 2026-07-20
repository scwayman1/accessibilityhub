# Progress Ledger — PRD phases vs shipped evidence

> The permanent record of what has actually been built against the
> [PRD](prd-accessibility-learning-journey.md) and
> [AI architecture](ai-architecture-byok.md), beyond what individual pull
> requests describe. Every "shipped" claim below names its implementation and
> its tests — the same evidence-before-claims discipline the product itself
> enforces. Last updated: 2026-07-20.

## Phase status at a glance

| PRD phase | Status |
|---|---|
| 1. Honest Local Review | **Shipped** (spike scope: PDF only) |
| 2. Fix and Verify | **Shipped** (metadata repairs; evidence receipts; judgment attestations) |
| 3. Learning Journey | **Tracer bullet shipped** (evidence-based mastery, repeat-defect tracking; lessons/challenges not yet built) |
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
