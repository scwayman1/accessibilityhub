# Next Engineering Loop — PRD and Handoff

> **Purpose of this document.** This is a self-contained work order for the
> next engineering loop on Coastline Accessibility Studio, written so a fresh
> agent (or human) with no prior session context can execute it. Read this top
> to bottom before writing code. It assumes only the repository as it stands at
> the merge of the "Learning OS" pull request (branch
> `claude/accessible-doc-editor-assessment-j052lf`).
>
> Companion documents you must read first:
> [`prd-accessibility-learning-journey.md`](prd-accessibility-learning-journey.md)
> (product vision), [`ai-architecture-byok.md`](ai-architecture-byok.md)
> (governs any future AI work), and
> [`progress-ledger.md`](progress-ledger.md) (what is already shipped, with
> tests). This PRD only defines the *next* increments.

## 0. Orientation — how the codebase works today

Everything is local, deterministic, Python 3.11 standard library plus `pypdf`
and `pillow`. There is no framework, no database, no cloud. The whole product
is a loopback HTTP server plus a single HTML page.

### Files

| File | Role |
|---|---|
| `check_pdf.py` | The deterministic checker. `analyze(pdf: Path, output_dir: Path) -> dict` runs qpdf → pypdf → pinned veraPDF and returns a report dict with `findings`, `strengths`, `metadata`, `tools`, `verapdf`. CLI entry point writes `report.json`/`report.md`. |
| `local_reviewer.py` | The loopback server (`127.0.0.1:8765`). Serves the HTML, static JSON, and the API. Endpoints below. |
| `local_reviewer.html` | The entire single-page workbench: inline CSS + vanilla JS, no build step, no external requests. |
| `rule_knowledge.json` | One teaching card per rule (`why_it_matters`, `who_it_affects`, `fix_at_source`, `auto_fixable`, and for fixable rules `fix_field`/`fix_label`). |
| `delight_content.json` | Authored companion voice lines cycled during a scan. |
| `tina/kernel.py` | The typed tool gateway. `ToolManifest` + `ToolGateway`. Every tool is registered with a version, purpose, `deterministic` flag, `mutates_document` flag, and a permission tuple. `ToolGateway.execute(name, input, granted_permissions)` enforces permissions. This is not a shell runner. |
| `tina/remedy.py` | `MetadataRemediation` — the first mutating tool (`document.remediate.metadata`): sets title (`/DisplayDocTitle`) and `/Lang` on a copy, records before/after hashes. |
| `tina/derive.py` | `HtmlDraftConverter` — non-mutating PDF → editable HTML draft (`document.derive.html_draft`); the draft embeds an offline improvement toolbar. |
| `tina/evidence.py` | `build_receipt(...)` + `verify_receipt_integrity(...)` — the evidence receipt (PRD §17) with a tamper-evident hash. |
| `tina/learning.py` | `LearningJourney` — the deterministic mastery/skill engine. Read §2 below carefully; the new work plugs into it. |
| `tests/` | `unittest`, one file per module. CI (`.github/workflows/test.yml`) installs `requirements.txt`, `py_compile`s the modules, and runs `python -m unittest discover -s tests`. |

### HTTP API (all on `127.0.0.1`, no auth, no persistence except the journey store)

- `GET  /api/health` → `{ok, scope, ai:false}`
- `GET  /api/journey` → the learning-journey snapshot (see §2)
- `GET  /api/knowledge` → serves `rule_knowledge.json`
- `GET  /delight-content.json` → companion voice content
- `POST /api/review?filename=…` (PDF body) → normalized review report
- `POST /api/fix?filename=…&title=…&language=…` (PDF body) → `{before, after, remediation, fixed_filename, fixed_pdf_base64}`
- `POST /api/convert?filename=…` (PDF body) → `{html, stats, draft_filename, …}`
- `POST /api/attest` (JSON `{rule_id, decision}`) → updated journey snapshot
- `POST /api/receipt` (JSON `{review, after?, remediation?, attestations?}`) → evidence receipt

### Non-negotiable invariants (do not break these; they are enforced by tests)

1. **No pass claims.** No product surface may use "fully compliant",
   "guaranteed accessible", "passed accessibility", "certified accessible", or
   "fully accessible" as an outcome. `tests/test_evidence.py::OutcomeLanguageGovernanceTests`
   greps every surface. **Any new file you add that is a product surface must
   be added to that test's `SURFACES` list.**
2. **Mutations only touch copies.** The original bytes are never written. Every
   mutating tool records `source_sha256` and `remediated_sha256`.
3. **Every tool is registered, versioned, permission-scoped, and declares
   `mutates_document`.** New capabilities go through `ToolGateway`, not around it.
4. **Every checker rule has a teaching card.**
   `tests/test_fix_endpoint.py::KnowledgeCoverageTests` fails if a rule ID in
   `check_pdf.py` has no entry in `rule_knowledge.json`.
5. **The learning store never contains document content or full hashes** — only
   16-char hash prefixes, rule IDs, attested decision text, timestamps.
6. **No network egress from document tooling. No AI.** This loop stays in Mode 1
   (Deterministic Only) of the AI architecture doc.
7. **Learning must never break a review.** Journey recording in
   `local_reviewer.py` is wrapped in try/except; keep it that way.

### How to run and verify locally

```bash
pip install -r requirements.txt        # pypdf, pillow
python -m unittest discover -s tests    # full suite, must stay green
python local_reviewer.py                # opens 127.0.0.1:8765
```
Browser end-to-end checks used headless Chromium via Playwright with
`executablePath=/opt/pw-browsers/chromium` (already present in the dev image).
Assemble text-bearing PDF fixtures with the `text_pdf(...)` helper in
`tests/test_html_draft.py`; image fixtures with `image_pdf()` (Pillow).

## 1. The mastery state machine you are extending (read before §3)

`tina/learning.py` defines skills keyed to the rules that feed them
(`SKILLS`, `RULE_TO_SKILL`) and computes a per-skill mastery state from an
append-only event log. States, in order:

```
not_started → introduced → practiced → applied → verified → sustained
```

Today the engine emits: `not_started`, `introduced` (a finding appeared in a
real document), `applied` (the user attested a judgment or applied a fix),
`verified` (a fix was rechecked and resolved the finding), `sustained` (the
defect did not recur across ≥2 subsequent distinct documents; regression
demotes to `introduced`).

**`practiced` is defined but never currently reached** — there is no lesson to
practice with. Item 1 below fills that gap. Study `LearningJourney._record`,
`record_review`, `record_fix`, `record_attestation`, and `_skill_mastery`
before touching them. Events carry a `type`; add new event types rather than
overloading existing ones, and keep `journey()` output backward compatible
(the workbench and `test_journey_endpoints.py` read specific keys).

## 2. Scope of this loop

Five increments, in priority order. **Ship each as its own commit with its own
tests and keep the suite green between them.** They are ordered so each is
independently valuable; you may stop after any one. Do not start AI work — that
is a separate track governed by `ai-architecture-byok.md`.

Prime directive for all five: *machines handle certainty; people handle
meaning.* Nothing here may guess alt text, infer reading order, or decide
whether an image is meaningful. The tools present, the human decides, the
machine records.

---

### Increment 1 — Authored micro-lessons and the `practiced` state · ✅ SHIPPED 2026-07-24

> Delivered as specified: `lesson_content.json` (one lesson per skill, full
> encounter→transfer sequence), `tina/lessons.py` (load/validate/score),
> `record_lesson` advancing mastery to `practiced` without outranking
> real-document evidence, `GET /api/lessons` + `POST /api/lesson-result`, an
> inline "Practice this skill" flow in the finding detail panel, and
> `tests/test_lessons.py` with skill-coverage enforcement. Start at
> Increment 2 below.

**Why.** The product's thesis is behavior change, and the mastery ladder has a
missing rung: `practiced`. A lesson gives the user a safe place to demonstrate
understanding *before* touching a real document, which is exactly what
`practiced` should certify. This also delivers PRD §11's
encounter→experience→explain→decide→verify→transfer lesson shape.

**Build.**

1. `lesson_content.json` — authored lessons, one or more per skill in
   `tina/learning.py`'s `SKILLS`. Each lesson is deterministic content only
   (no generation). Suggested shape per lesson:
   ```json
   {
     "lesson_id": "headings-101",
     "skill": "structure_and_reading_order",
     "title": "Why heading levels matter",
     "steps": [
       {"kind": "encounter", "body": "..."},
       {"kind": "experience", "body": "...", "demo": "linear-reading-order"},
       {"kind": "explain", "body": "..."},
       {"kind": "decide", "prompt": "...", "options": ["...","...","..."], "correct_index": 0, "rationale": "..."},
       {"kind": "verify", "body": "..."},
       {"kind": "transfer", "body": "Now run this check on one of your own documents."}
     ]
   }
   ```
   The `decide` step is the only scored one; scoring is exact-match on
   `correct_index`, fully deterministic. Keep the voice aligned with PRD §22
   and `delight_content.json` — direct, respectful, never patronizing.
2. `tina/lessons.py` — a small loader/validator: load `lesson_content.json`,
   validate every lesson references a real skill and every `decide` step has a
   valid `correct_index`, and expose `score_decision(lesson_id, step_index,
   chosen_index) -> bool`. No gateway tool needed (read-only authored content),
   but follow the module conventions.
3. Extend `tina/learning.py`: add a `record_lesson(skill, lesson_id, passed:
   bool)` event and make a passed `decide` step advance a `not_started`/
   `introduced` skill to `practiced` (never downgrade a higher state). Update
   `_skill_mastery` so the ordering holds: a later real-document fix still
   moves `practiced` → `applied` → `verified`.
4. Endpoints: `GET /api/lessons` (all lessons, or `?skill=` filtered) and
   `POST /api/lesson-result` (JSON `{lesson_id, step_index, chosen_index}`) →
   `{correct, rationale, journey}`.
5. Workbench: when a finding's skill has a lesson, offer a "Practice this
   skill" affordance in the finding detail panel that runs the lesson inline
   (steps rendered in sequence, the decide step scored, rationale shown). The
   journey panel should show `practiced` chips. Keep it keyboard-operable and
   screen-reader-friendly (the product must model accessibility — PRD §6.7:
   focus states, non-color status, `aria-live` for step changes).

**Governance.** Add `lesson_content.json` and `tina/lessons.py` to the
`SURFACES` list in `tests/test_evidence.py`. Add a coverage test: every skill
in `SKILLS` has ≥1 lesson, and every lesson's `skill` and `correct_index` are
valid.

**Acceptance.** A user can practice a skill from a finding, a correct answer
advances that skill to `practiced` in `/api/journey`, the mastery ordering with
later real-document evidence still holds, and the full suite is green.

---

### Increment 2 — Alt text written back into the PDF (`/Alt`), human-authored

**Why.** Images are the most common real finding
(`PDF.IMAGES.ALTERNATIVES` → skill `images_and_meaning`). Today the only path
that fixes them is the HTML escape hatch. For the many cases where PDF must
remain the deliverable, we need a Class-2 "user-supplied semantics" repair: the
human writes the description (or marks the image decorative), and a
deterministic tool applies it. **The tool must never author or infer alt text.**

**Build.**

1. New gateway tool in `tina/remedy.py` (or a sibling `tina/remedy_images.py`
   if cleaner) named e.g. `apply_image_alt_text`, permission
   `document.remediate.alt_text`, `mutates_document=True`. Input: the PDF bytes
   plus a list of `{image_ref, alt}` or `{image_ref, decorative: true}`
   decisions supplied entirely by the human. Output: new bytes + before/after
   hashes + an actions log, exactly like `MetadataRemediation`.
   - Applying `/Alt` in PDF requires the image to be reachable through the tag
     tree (a marked-content `/Figure` structure element). Research the pypdf
     capabilities honestly: **if a PDF has no structure tree, you cannot
     attach a conformant `/Alt` to it** — in that case the tool must *decline*
     with a clear reason that routes the user to the HTML escape hatch or
     source repair, not silently no-op or fake success. This honesty is the
     feature. Encode "tagged vs untagged" detection deterministically.
   - Marking decorative means associating the image with an `/Artifact` (or the
     appropriate structural signal). Same tagged-vs-untagged caveat applies.
2. Endpoint `POST /api/fix-images` mirroring `/api/fix`: review → apply the
   human's decisions to a copy → re-review → return before/after + fixed PDF.
   Feed the resolution into the learning journey (`record_fix`), so resolving
   images advances `images_and_meaning`.
3. Workbench: on a `PDF.IMAGES.ALTERNATIVES` finding, let the user enter a
   description per image or mark it decorative (reuse the alt-editor pattern
   already in the HTML draft in `tina/derive.py`'s embedded script), then apply.
   If the document is untagged, surface the tool's decline reason and point to
   "Create editable HTML draft" instead.
4. Receipts: `tina/evidence.py` must distinguish alt-text provenance
   (`user_authored` for these) — extend the receipt's `mutations`/
   `human_decisions` so an auditor can see the description was written by a
   person, not a machine.

**Acceptance.** On a tagged PDF, a human-written description is applied to a
copy, the re-review resolves the finding, the receipt records it as
user-authored, and mastery advances. On an untagged PDF, the tool declines with
a routing message and applies nothing. Tests cover both paths (build a tagged
fixture; if pypdf cannot produce one, document the limitation in the test and
assert the untagged decline path).

---

### Increment 3 — Page rendering with findings anchored to locations

**Why.** Findings currently point at abstract locations ("document catalog",
"page resources"). Turning the report into a workbench means showing the page
and anchoring each finding to where it occurs (PRD §14.2/§14.3, "show me the
student experience").

**Build.**

1. Deterministic page rendering to images. Prefer a dependency already viable
   locally; if you add one, pin it in `requirements.txt` and confirm it needs
   no network at runtime. Expose per-page render as a non-mutating gateway tool
   (`document.render.page`, `mutates_document=False`).
2. Extend `check_pdf.py` findings to carry a `page` number and, where
   determinable (images, links, annotations), a bounding box, without changing
   existing rule IDs or categories. Keep additions backward compatible — the
   receipt and journey code read findings by `rule_id`/`category`.
3. Endpoint `POST /api/render?filename=…&page=N` returning a page image
   (base64, like the fix flow) with the anchor rectangles for that page's
   findings.
4. Workbench: a page view that draws finding markers over the rendered page and
   links them to the finding cards. Non-color status indicators required.

**Acceptance.** A reviewed PDF can be viewed page by page with image/link
findings visually anchored; nothing about the existing report contract breaks;
suite green. This increment is the largest — it is acceptable to land rendering
+ anchoring for images/links only and leave text-region anchoring to a later
loop, as long as that limitation is logged in the progress ledger.

---

### Increment 4 — Lists, tables, and landmarks in the HTML draft editor

**Why.** The HTML escape hatch (`tina/derive.py`) currently handles headings,
text, title/language, and images. Real course documents have lists and tables;
these are where PDF accessibility most often fails and where rebuilding as HTML
pays off most (PRD §10 Worlds 4–5).

**Build.** Extend the deterministic extraction and the embedded offline editor
in `tina/derive.py`:
- Detect list-like and table-like content deterministically from the extracted
  layout (candidates only — never assert structure the user has not confirmed).
- Add editor controls to mark a block as a list, or to confirm a table's header
  row/column and cell structure. As always, the tool proposes candidates; the
  human confirms; the serializer emits semantic `<ul>/<ol>/<table>` with proper
  `<th scope>`.
- Keep the clean-export contract: no script, no external dependency, semantic
  HTML, the existing "not a conformance result" banner.

**Acceptance.** A draft can express confirmed lists and tables with correct
semantics in the exported HTML; the embedded editor script still passes
`node --check`; suite green.

---

### Increment 5 — Ground-truth corpus and false-negative baseline

**Why.** The README's original recommendation and the AI architecture doc §23:
before widening the rule set or trusting coverage, validate the taxonomy
against specialist-reviewed ground truth. Without it we do not know our
false-negative rate.

**Build.**
- A rights-cleared fixture corpus under `tests/corpus/` (or generated
  deterministically) spanning the categories in `ai-architecture-byok.md` §23,
  **including "good documents that must not be fixed."**
- Each fixture carries expected machine findings, expected human-judgment
  items, allowed/prohibited repairs, and recheck expectations.
- A test harness that runs `analyze` over the corpus and asserts the checker's
  findings match expectations, surfacing false positives and false negatives as
  explicit failures. An overenthusiastic fixer is a vandal with a progress bar;
  this corpus is the guardrail against becoming one.

**Acceptance.** The corpus runs in CI, documents the current false-positive/
false-negative baseline, and at minimum proves the checker leaves known-good
documents untouched.

## 3. Definition of done for the loop

For each increment shipped:
- New/changed behavior is covered by `unittest` tests and the full suite is
  green (`python -m unittest discover -s tests`).
- Any new product surface is in the `SURFACES` governance list.
- Any new tool is registered through `ToolGateway` with an explicit permission
  and `mutates_document` flag.
- No prohibited outcome language anywhere.
- **`docs/progress-ledger.md` is updated** to move the increment from "next
  loop" to "shipped", naming its implementation and tests, and logging any
  scoped-down limitations (e.g. "page anchoring covers images/links only").
- Commit messages describe the change and end with the repo's required
  `Co-Authored-By` / session trailer convention. Push to the working branch and
  open/refresh a draft PR.

## 4. Explicit non-goals for this loop

- No AI, no model calls, no BYOK work — that is a separate track under
  `ai-architecture-byok.md` and starts only after its §31 acceptance criteria
  are addressed.
- No automated authoring of alt text, reading order, table structure, or any
  judgment call. Tools propose and record; humans decide.
- No pass/fail badge, score, or compliance verdict.
- No cloud, no upload endpoint, no telemetry, no persistence beyond the local
  journey store.
- No silent structural rewrites of complex documents.

## 5. Suggested sequencing for a fresh agent

1. Read this doc, the PRD, the AI architecture doc, and the progress ledger.
2. Run the suite green locally to confirm the baseline.
3. Do Increment 1 end to end (it is self-contained and the highest leverage:
   it completes the mastery ladder). Ship it.
4. Then Increment 2 (alt text write-back) — highest real-document impact.
5. Then 3, 4, 5 as time and priority allow, each as its own commit/PR.
6. Keep the ledger honest at every step.
