# Coastline College Accessibility Hub

A document accessibility reviewer built for educators, on one honest loop:
**Add material → Review → Improve → Check again.**

It finds accessibility barriers in course PDFs, teaches why each one matters,
fixes what a machine can safely fix (always on a copy, never the original),
and proves the result by rechecking. Every detail lands in one of four lanes —
**Needs attention**, **Review recommended**, **Verified signal**, or
**Not assessed** — and never in a single overall grade. The product produces
technical evidence and review routing only: no compliance score, no
certification, no overall pass.

Everything runs locally and deterministically, and works without AI.

## Quickstart

From the repository root:

```sh
pip install -r requirements.txt
python3.11 -m pytest tests/ -q
```

The suite passes on a machine with only Python and the pinned packages —
qpdf, Docker/veraPDF, and tesseract are optional. When a tool is missing, a
review still completes and discloses the skipped check under *Review
completeness* instead of failing.

## The three surfaces

### 1. Public site (static)

`index.html` (landing) and `sample-review.html` (a canned walkthrough of one
review). Serve the repo root with any static server:

```sh
python3.11 -m http.server 8000
```

Then open `http://127.0.0.1:8000/`.

### 2. Local workbench (Fix Lab)

The full review-and-repair workbench, loopback-only — the PDF you choose never
leaves your computer:

```sh
python3.11 local_reviewer.py
```

Then open `http://127.0.0.1:8765`. Use `--port` to pick another port. The
workbench reviews a PDF, explains each finding with a teaching card, applies
permission-gated fixes (title, language, link names, alt text, human-confirmed
tag trees, OCR text layers) to an in-memory copy, rechecks it, and exports an
evidence receipt.

### 3. Private staging service (hosted-style workspace)

The access-code-gated workspace that reviews only bundled synthetic fixtures
(no upload route exists). One command starts it locally:

```sh
scripts/demo_up.sh
```

It prints the login URL (`http://127.0.0.1:8787/login` by default) and a
generated access code. Set `HUB_PORT` to change the port. Port contract: the
service honors `PORT` first, then `HUB_PORT`, then defaults to `8787`.

## Verify a running staging service

`scripts/staging_smoke.py` drives the real HTTP surface end to end — health
check, sign-in, synthetic review, a repair, the recheck, change history, and
the no-upload boundary:

```sh
python3.11 scripts/staging_smoke.py --base-url http://127.0.0.1:8787 \
    --access-code "$HUB_STAGING_ACCESS_CODE"
```

Use the access code printed by `scripts/demo_up.sh`. Exit code 0 means every
required check passed. Run it against the hosted URL after every deploy.

## Demo

The click-by-click morning demo script — setup, storyline, talking points,
deploy path, and pre-demo checklist — is in
[docs/demo-runbook.md](docs/demo-runbook.md).

## Deploying the staging service

`render.yaml` declares the `accessibility-hub-staging` web service as a Render
Blueprint. The owner runbook — required environment variables, the explicit
`HUB_ALLOW_HOSTED_SYNTHETIC` opt-in, and the hosted boundary — is in
[docs/private-staging-service.md](docs/private-staging-service.md). Note the
hosted runtime installs Python packages only: qpdf, veraPDF, and tesseract are
absent there, and reviews disclose those skipped checks honestly.

## How the engine works

`check_pdf.py` is a local-only deterministic checker:

```text
qpdf structural check
→ PDF structure extraction (pypdf)
→ pinned veraPDF report (Docker, --network none, --pull=never)
→ scan/text-layer heuristics
→ normalized finding categories with page anchors
```

Finding categories: `blocking_technical_failure`, `deterministic_defect`,
`review_required`, `advisory`, `tool_failure_or_unsupported`. Every report also
carries `strengths` (individual verified signals, never aggregated into a
pass) and `not_assessed` (areas this tool gathers no evidence about — contrast,
tables, forms, color-only meaning — routed to a human reviewer).

Key boundaries, enforced by tests:

- Local files only; no upload, telemetry, or external calls during a review.
- Remediation is permission-gated and applied only to a copy; every mutation
  records before/after hashes (`tina/remedy.py`, `tina/structure.py`,
  `tina/ocr.py`).
- Output is technical evidence, **not** a PDF/UA, WCAG, Section 508, or legal
  conformance determination; a CI governance test bans prohibited outcome
  language across product surfaces (`tests/test_evidence.py`).
- Every checker rule ships with an educator teaching card in
  `rule_knowledge.json` — card titles product-wide come from its `title`
  fields.

Run the checker directly if you want raw artifacts:

```sh
python3.11 check_pdf.py path/to/document.pdf --output-dir out
```

It writes `out/report.json` and `out/report.md`.

## Repository map

| Path | What it is |
|---|---|
| `check_pdf.py` | Deterministic PDF evidence engine (JSON + Markdown reports) |
| `rule_knowledge.json` | Teaching card and canonical title for every checker rule |
| `local_reviewer.py` / `local_reviewer.html` | Loopback workbench server and UI |
| `index.html`, `sample-review.html` | Public landing and canned walkthrough |
| `service/` | Private staging service (WSGI app, worker, SQLite repository) |
| `scripts/demo_up.sh` | One-command local staging demo launcher |
| `scripts/staging_smoke.py` | Repeatable per-deploy smoke test |
| `render.yaml` | Render Blueprint for the hosted staging service |
| `tina/` | Permission-gated tool kernel: remediation, evidence receipts, learning journey |
| `tests/` | Full suite (`python3.11 -m pytest tests/ -q`) |

## Deeper product documents

- [Demo runbook](docs/demo-runbook.md)
- [Private staging service boundary + Render runbook](docs/private-staging-service.md)
- [Progress ledger — PRD phases vs shipped evidence](docs/progress-ledger.md)
- [Product requirements — the accessibility learning journey](docs/prd-accessibility-learning-journey.md)
- [AI tool chain, model router, BYOK and evaluation architecture](docs/ai-architecture-byok.md)
- [Next engineering loop — PRD and handoff](docs/next-loop-prd.md)
- [Product assessment (July 2026)](docs/product-assessment-2026-07.md)
- [Document editor vision](docs/document-editor-vision.md)
- [Private beta intake gates](docs/tina-private-beta-intake.md)
