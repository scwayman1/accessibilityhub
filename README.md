# Coastline College Accessibility Hub

A document accessibility reviewer built for educators, on one honest loop:
**Review → Understand → Improve → Verify.**

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

`index.html` (the entry — `landing.html` is kept byte-identical to it) and
`sample-review.html` (an interactive guided sample: four keyboard-operable
finding toggles walk one synthetic review through Review → Understand →
Improve → Verify). Serve the repo root with any static server:

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

### Also in the tree: the locked real-intake foundation

`service/real_intake/` holds the separate, locked foundation for eventual
real-document intake — Postgres schema, Clerk-based owner auth, ClamAV
scanning gate, consent/lifecycle/audit modules — with its own dependency set
(`requirements-real-intake.txt`) and test suites (`tests/test_real_intake_*`).
It is **not part of the demo**: no demo surface routes to it, and it stays
closed until its controls are provisioned and verified per the real-intake
documents linked below.

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

## Test bench

Generate a varied synthetic corpus, then watch the real pipeline — the same
`check_pdf.analyze` → auto-improve-a-copy → re-assess → `tina.seal` path the
staging worker runs — transform every document:

```sh
python3.11 scripts/make_test_corpus.py                 # writes ./corpus/ (gitignored)
python3.11 scripts/transform_bench.py corpus --out bench-out
python3.11 scripts/transform_bench.py corpus --fast --produce   # also build + recheck accessible copies
```

The corpus covers missing title/language, unnamed links, tagged figures without
alt text, an untagged multi-block document, a scanned page with no text layer,
an encrypted PDF, an already-well-formed document, a 50-page timing document,
and filenames with spaces and non-ASCII characters. `--list` names them,
`--only <name>` generates one, and every document except the encrypted one is
byte-for-byte reproducible.

The bench prints a per-document before/after table plus an honest toolchain
status block, writes the improved `.ready.pdf` copies and a self-contained
`bench-out/bench-report.html` (before→after lanes, what changed with
provenance, timing, tool status), and exits 0 only when every document either
transformed, needed no changes, or declined for an expected, plainly stated
reason (an encrypted PDF declining is expected; a crash is not). `--fast`
skips the 50-pager; `--json` emits machine-readable results for refinement
loops. Bench output is technical evidence and review routing only — never an
accessibility determination.

Toolchain visibility: `scripts/demo_up.sh` prints the same detection block on
startup, and `/healthz` reports it read-only under `"toolchain"`
(name → version line, or `null` when absent — absent tools are disclosed
per-review under *Review completeness*).

## Accessible copies: HTML + tagged PDF

From a reviewed document, the Hub can rebuild **accessible HTML** and a
**tagged PDF/UA-1** copy. It uses the title, language, headings and lists a
person confirms, plus a person's description (or decorative decision) for each
image. The tool never writes alt text and never produces a copy while any
image is undecided.

- Engine: `tina/author.py` (WeasyPrint `pdf/ua-1`). It rechecks its own PDF
  with the same checker, and with PdfCraft when present.
- Workbench: `POST /api/produce`.
- Staging: the **Get accessible HTML + tagged PDF** link opens
  `/documents/{id}/accessible`. Hosted environments keep it closed unless
  `HUB_ENABLE_PRODUCE=true`.
- The copy is re-flowed rather than a pixel replica. It ends with an "About
  this copy" note: a review record, not a certification.

## PdfCraft (optional second opinion, tagged-PDF fixes, page images)

[PdfCraft](https://github.com/storytold/pdfcraft) is the open-source,
Acrobat-comparable PDF workbench from the ArtCraft suite (MIT OR Apache-2.0).
To build the pinned CLI (needs Rust 1.94 or newer and a C compiler):

```sh
scripts/build_pdfcraft.sh            # -> vendor-bin/pdfcraft-cli (or set PDFCRAFT_BIN)
```

When it is present:
- Reviews add PdfCraft's 32-rule Acrobat-style check as a second opinion.
  Anything it flags goes to *Review recommended*.
- People can describe images in PDFs that are already tagged.
- Page images render without poppler.

When it is absent, reviews disclose the skipped check and everything else
works.

## veraPDF (PDF/UA-1 validator) and the full-toolchain image

```sh
scripts/install_verapdf.sh           # pinned veraPDF CLI -> vendor-bin/verapdf (needs Java + Maven)
docker build -t accessibility-hub . && scripts/docker_smoke.sh accessibility-hub
```

When veraPDF is installed, every review and every produced copy includes its
UA-1 results as evidence for a person to review. The `Dockerfile` bundles
PdfCraft, veraPDF, WeasyPrint's libraries, poppler, qpdf and tesseract. CI
builds and smoke-tests the image. Locally, `VERAPDF_BIN=/nonexistent` skips
veraPDF to keep the test suite fast.

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
| `service/real_intake/` | Locked real-intake foundation (separate from the demo; not routed) |
| `scripts/demo_up.sh` | One-command local staging demo launcher |
| `scripts/staging_smoke.py` | Repeatable per-deploy smoke test |
| `render.yaml` | Render Blueprint for the hosted staging service |
| `tina/` | Permission-gated tool kernel: remediation, evidence receipts, learning journey, accessible copies (`author.py`, `docmodel.py`), PdfCraft adapter (`pdfcraft.py`) |
| `scripts/build_pdfcraft.sh`, `Dockerfile` | Pinned PdfCraft build; full-toolchain container image |
| `docs/commercial/` | Pilot commercial pack drafts (counsel review pending) |
| `tests/` | Full suite (`python3.11 -m pytest tests/ -q`) |

## Deeper product documents

- [Demo runbook](docs/demo-runbook.md)
- [Private staging service boundary + Render runbook](docs/private-staging-service.md)
- [Progress ledger — PRD phases vs shipped evidence](docs/progress-ledger.md)
- [Product requirements — the accessibility learning journey](docs/prd-accessibility-learning-journey.md)
- [AI tool chain, model router, BYOK and evaluation architecture](docs/ai-architecture-byok.md)
- [Controlled real-intake Render safety plan](docs/render-controlled-real-intake.md)
- [Clerk owner-only setup and activation checklist](docs/clerk-owner-only-setup.md)
- [Controlled real-intake operations, deletion, and incident runbook](docs/real-intake-operations.md)
- [Controlled real-intake verification matrix](docs/real-intake-control-matrix.md)
- [Private ClamAV scanner specification](docs/clamav-private-scanner.md)
- [Private real-intake provisioning checkpoint](docs/real-intake-provisioning-checkpoint.md)
- [Next engineering loop — PRD and handoff](docs/next-loop-prd.md)
- [Product assessment (July 2026)](docs/product-assessment-2026-07.md)
- [Document editor vision](docs/document-editor-vision.md)
- [Private beta intake gates](docs/tina-private-beta-intake.md)
