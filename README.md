# Coastline Accessibility Studio

**Review → Understand → Fix → Verify.** A local-first document remediation
and learning workbench: it finds accessibility barriers, teaches why they
matter, fixes what a machine can safely fix, proves the result with evidence
receipts, and tracks evidence-based skill mastery so the same defect stops
appearing. Runs locally, deterministic, works without AI.

Canonical product documents:

- [Product requirements — the accessibility learning journey](docs/prd-accessibility-learning-journey.md)
- [AI tool chain, model router, BYOK and evaluation architecture](docs/ai-architecture-byok.md)
- [Progress ledger — PRD phases vs shipped evidence](docs/progress-ledger.md)
- [Next engineering loop — PRD and handoff](docs/next-loop-prd.md)
- [Product assessment (July 2026)](docs/product-assessment-2026-07.md)
- [Document editor vision](docs/document-editor-vision.md)
- [Private beta intake gates](docs/tina-private-beta-intake.md)

---

# Spike 001 — PDF-only deterministic accessibility evidence checker

## Purpose

Validate whether Coastline Accessibility Studio can produce a useful, source-located **technical evidence report** for a controlled PDF without uploads, AI, mutation, or a public service.

## Boundary

- Local files only. The browser sends the selected PDF only to the loopback reviewer on this computer; there is no remote or public upload endpoint.
- No external AI or model calls.
- Remediation is limited to deterministic, permission-gated metadata fixes applied to an in-memory copy; the original file is never rewritten or persisted.
- Output is a technical findings report, **not** a PDF/UA, WCAG, Section 508, or legal compliance certification.
- Use the public Coastline sponsorship packet already in `client/public/` as the initial fixture; do not use student, faculty, or protected records.

## Given / When / Then

| Given | When | Then |
|---|---|---|
| A parseable local PDF | The checker runs | It emits JSON and Markdown findings with file hash, page count, tool versions, and source evidence. |
| A malformed, encrypted, or unsupported PDF | Intake runs | It returns a clear tool/format failure rather than continuing silently. |
| Missing or ambiguous semantic evidence | Structural checks run | It emits `review_required`, not an accessibility pass/fail. |

## Planned deterministic chain

```text
qpdf check
→ PDF structure extraction (pypdf)
→ pinned veraPDF report
→ scan/text-layer heuristics
→ normalized Coastline finding categories
```

## Finding categories

- `blocking_technical_failure`
- `deterministic_defect`
- `review_required`
- `advisory`
- `tool_failure_or_unsupported`

## Acceptance evidence

1. CLI runs against the controlled fixture with no network calls.
2. JSON is schema-valid and names every tool version.
3. Markdown report distinguishes technical evidence from human-review work.
4. No output contains the words `compliant`, `certified`, or `accessible` as a pass claim.

## Local workbench — shipped with this spike

The spike now includes a usable local browser workbench:

```text
local_reviewer.py
local_reviewer.html
```

Run it from this directory:

```bash
colima start --cpu 4 --memory 8 --disk 60
./.venv/bin/python local_reviewer.py
```

Then open:

```text
http://127.0.0.1:8765
```

The reviewer binds only to `127.0.0.1`. Choosing a PDF sends it only to that local process; it writes a temporary copy, runs the deterministic checker, returns normalized browser-safe findings, and deletes the temporary input/evidence directory before responding. There is no remote upload, persistence, AI call, document rewrite, or external sharing path.

Stop the local reviewer with `Ctrl-C`. Stop the container VM when finished with `colima stop`.

### Fix loop — review, learn, fix a copy, re-check

The workbench closes the loop on the findings it can deterministically resolve:

- `GET /api/knowledge` serves `rule_knowledge.json`, a teaching card for every
  checker rule: why it matters, who it affects, how to fix it at the source,
  and whether the tool can fix it. A CI test fails if a rule ships without one.
- `POST /api/fix` runs the review, applies requested metadata fixes (document
  title with `/DisplayDocTitle`, primary language `/Lang`) to an in-memory copy
  via the permission-gated `tina/remedy.py` tool, re-runs the review on the
  copy, and returns before/after reports plus the updated PDF for download.
  Fixes stack because the workbench keeps working from the updated copy.
- Structural findings (tags, reading order, image alternatives, OCR) remain
  routed to human review; the fix banner states explicitly that resolving
  technical findings is not a conformance result.

### Prove and improve — receipts, judgments, and the learning journey

- Every review can export an **evidence receipt** (`POST /api/receipt`,
  `tina/evidence.py`): fingerprints in and out, tool and ruleset versions,
  checks performed and not performed, findings before/after, mutation
  provenance, human decisions, unresolved items, and a verifiable integrity
  hash. The receipt states explicitly that it is not a certification.
- `review_required` findings carry a **judgment attestation** flow
  (`POST /api/attest`): the human records the decision; the receipt marks it
  `user_attested`.
- A deterministic **learning journey** (`tina/learning.py`,
  `GET /api/journey`) tracks evidence-based mastery per skill —
  introduced → applied → verified → **sustained** (the defect has not
  recurred across subsequent documents; regression demotes it) — and flags
  repeat defects with deterministic recommendations. The local store keeps
  only hash prefixes, rule IDs, and attested decisions; never filenames or
  content.
- Reviews also report **verified strengths**: individual pieces of machine
  evidence (title present, language declared, structure tree exists), never
  combined into an overall pass. A CI governance test bans prohibited
  outcome language across all product surfaces.

### HTML working copy — convert the asset and make the improvements

When repairing the PDF is the wrong medium, the workbench derives an editable
HTML working copy instead:

- `POST /api/convert` runs `tina/derive.py` (`extract_html_draft`, gated by the
  `document.derive.html_draft` permission, `mutates_document=False`). It
  deterministically extracts text blocks and images into a structured HTML
  draft, carrying over the source title/language only if they actually exist.
- The draft embeds a self-contained, offline improvement toolbar: set the
  title and language, promote text blocks to headings, correct extracted text
  in place, and describe each image or mark it decorative. A live checklist
  tracks the decisions still needed.
- "Export clean HTML" strips all editing chrome and produces a working HTML
  document — the accessible-HTML deliverable path from the editor vision. The
  draft banner states it is a re-authoring workspace, not a conformance result.

If qpdf or Docker is not installed, the review no longer fails: the missing
tool is reported as an explicit `tool_failure_or_unsupported` finding and the
review completes with the evidence it can gather.

The workbench now includes an optional, pluggable local **Delight Engine** configured in:

```text
delight_content.json
```

It cycles encouraging accessibility tips and gentle humor during a real local scan. Categories are individually enabled/disabled in the JSON file. It does not use AI, retrieve external content, play audio, or claim that a stage has passed before the actual checker returns.

## Tina Phase 1 — deterministic evidence kernel

The repository also contains the first Tina architecture tracer bullet in `tina/kernel.py`.
It is deliberately small, local, and non-agentic:

```text
registered typed tool → permission check → versioned DAR v0 document record
→ versioned rule → evidence-backed finding → explicit claim boundary
```

`ToolGateway` accepts only registered tool adapters with declared version, purpose,
determinism, mutation status, timeout, and permissions. It is not a shell-command
runner. The initial `inspect_file_signature` tool creates reproducible intake evidence
and never makes a conformance determination.

Future models and remediation tools must remain outside this read-only kernel and use
workflow-issued permissions plus evidence references.

## Tina Phase 2 — permission-gated metadata remediation

`tina/remedy.py` is the first mutating tool, registered through the same
`ToolGateway` with `mutates_document=True` and a dedicated
`document.remediate.metadata` permission, outside the read-only kernel. It
fixes only what is deterministic (title, language, title display preference),
records before/after hashes for every mutation, and its report carries the
claim boundary that resolving findings does not make a document conformant.

Product direction lives in `docs/product-assessment-2026-07.md` and
`docs/document-editor-vision.md`.

## Execution evidence

Executed locally on 2026-07-15 using the public Coastline sponsorship packet already present in the repository.

- Fixture: 12-page PDF, SHA-256 `36d88645530fc39125384199898038c61f1ab0c13df11275e415d5df05d46198`
- `qpdf 12.3.2` intake check executed.
- `pypdf 6.9.1` structure extraction executed.
- `veraPDF 1.30.2` ran in a read-only Docker container with `--network none`; its UA-1 output was retained as experimental technical evidence only.
- The normalized report found seven image objects and routed them to human review rather than issuing a pass claim.
- Generated malformed and encrypted fixtures both produced blocking-intake reports; veraPDF was not run after blocking intake.
- No network upload or document mutation occurred.

## Verdict: VALIDATED — constrained local evidence chain

### What worked

- Local-only PDF input produced normalized JSON and Markdown evidence artifacts.
- Parser/safety failures were surfaced as explicit blocking findings.
- Structural ambiguity and image alternatives routed to human review.
- The validator runs in an isolated, no-network container using a pinned local image digest; the reviewer does not pull images during a check.

### What did not become a product claim

- No PDF/UA, WCAG, Section 508, legal, or publish-readiness result is produced.
- The experimental veraPDF UA-1 profile is recorded only as technical evidence.
- OCR, document repair, AI assistance, uploads, and production storage remain out of scope.

### Recommendation for the real build

Use this spike as the starting contract for an isolated PDF worker. Next validate the rule taxonomy against a Coastline accessibility-specialist ground-truth corpus before any user upload or production deployment.
