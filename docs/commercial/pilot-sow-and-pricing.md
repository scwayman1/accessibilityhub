**DRAFT — prepared for counsel review. Not legal advice. Not yet adopted.**

# Statement of Work and Pricing — Coastline Accessibility Hub Pilot (draft)

| Field | Value |
|---|---|
| Provider | Coastline College Foundation |
| Institution | [INSTITUTION LEGAL NAME] for Coastline College |
| Institution pilot lead | [NAME, TITLE] |
| Provider lead | [NAME] |
| Term | [SEMESTER, e.g., Spring 2027]: [START DATE] – [END DATE] |
| Governing documents | Terms of Service; Data Processing Agreement (`ferpa-dpa-template.md`); this SOW |

## 1. Purpose

Determine whether Coastline Accessibility Hub helps faculty find, understand, and fix technical accessibility barriers in their course PDFs, and whether faculty create fewer repeat barriers over a semester. The pilot measures **evidence of work done and learning** — it does not measure, and the product does not issue, a compliance score, certification, or pass determination.

## 2. Honest starting point (read before pricing)

| Component | Today | Needed for hosted pilot with real documents |
|---|---|---|
| Deterministic review engine, teaching cards, fixes on a copy, recheck, evidence receipt | Working (local workbench; hosted staging with synthetic samples) | — |
| Hosted real-document intake | Locked foundation only: schema, auth, scan, consent, deletion, audit contracts in code; **no upload/process/download/delete routes; infrastructure not provisioned** | Build routes; provision Render resources; select object store; prove worker no-egress; audit sink; deletion adapters; backup SLA; deployed canary run |
| Identity | Clerk, owner-only design; production instance not created | Multi-user faculty access via Microsoft Entra ID SSO through Clerk, with role and deprovisioning tests |
| Accessible HTML + tagged PDF output (PDF/UA-1 target) | **Planned** (WeasyPrint generation; checked by Provider's checker, PdfCraft — github.com/storytold/pdfcraft — and veraPDF when available) | Build, test, and accept per §7 |
| Product UI accessibility | Draft ACR from code inspection; AT testing pending | Complete AT testing; fix ACR-1…4 |

Because of this, the pilot is structured with a **readiness gate**: no institutional document is uploaded to hosted infrastructure until every DPA Exhibit C control has live evidence.

## 3. Scope

### Phase 0 — Readiness (Provider work, [N] weeks, no institutional documents hosted)
- Complete items in §2 "Needed" column; run deployed positive/negative canary with a non-sensitive PDF; complete tabletop exercise (`incident-response-plan.md` §7).
- Faculty may use the **local workbench** (documents stay on their computers) and the public guided sample during this phase.
- Deliverable: readiness evidence packet to Institution ISO (control matrix with live evidence, HECVAT update, ACR update).

### Phase 1 — Hosted pilot (one semester)
- Up to **[N, e.g., 10–15] faculty** in [DEPARTMENTS], invited by Institution.
- PDF documents only, ≤25 MiB each (schema limit); [DOCUMENT CAP, e.g., 40 per faculty].
- Data classification limit: [e.g., no SSN, health, or financial-aid records; rosters/graded work only with Institution approval].
- Onboarding workshop ([1] × [90] min), office hours ([biweekly]), email support business days [HOURS], response target [1 business day].
- Mid-pilot check-in and end-of-pilot report.
- No AI features; sponsored cards [shown / disabled for pilot tenant — DECISION].

### Out of scope
DOCX/PPTX/other formats; student-facing use; LMS integration; AI/model features; formal conformance auditing of documents; 24×7 support; multi-institution administration.

## 4. Responsibilities

| Institution | Provider |
|---|---|
| Name pilot lead and faculty; distribute surveys | Deliver Phase 0 readiness packet before any hosted upload |
| Entra ID admin creates app registration / approves SSO connection | Configure Clerk + Entra SSO, roles, deprovisioning |
| ISO reviews HECVAT, DPA, ACR, readiness packet | Operate service; monitor; incident response per plan |
| Provide data-classification guidance to faculty | Produce content-free metrics report |
| IT assists local workbench installs (Python 3.11 + packages) if used | Return and delete data at end (§9) |

## 5. Success metrics (honest measures only)

All metrics are computed from content-free records (rule IDs, lanes, timestamps, counts) or surveys. None is a statement that a document is conformant.

| # | Metric | Definition | Source | Target |
|---|---|---|---|---|
| M1 | Findings resolved on copies | Share of **Needs attention** findings in an original review that no longer appear on the recheck of the fixed copy | Before/after findings per document | [≥ X%] median |
| M2 | Repeat-defect reduction | For each faculty member, share of rule IDs flagged in their first [2] documents that recur in documents reviewed in the final [N] weeks | Learning-journey / findings history | [≥ Y% reduction] |
| M3 | Human-judgment follow-through | Share of **Review recommended** findings with a recorded human decision | Attestations | [≥ Z%] |
| M4 | Not-assessed transparency | Share of reports where **Not assessed** areas were displayed and acknowledged | UI/report records | 100% displayed |
| M5 | Time to fixed copy | Median minutes from review start to downloaded fixed copy | Content-free timestamps [PLANNED instrumentation] | [baseline + target] |
| M6 | Faculty-reported time saved | Self-reported minutes saved per document vs. prior practice | Pre/post survey | [target] |
| M7 | Learning | Faculty agreeing "I understand why this barrier matters and how to prevent it at the source" | Survey | [≥ X%] |
| M8 | Adoption | Active faculty / invited; documents reviewed | Counts | [target] |

**Not used as metrics:** percentage of documents "compliant," pass rates, or any conformance claim.

## 6. Deliverables and acceptance

| Deliverable | Acceptance |
|---|---|
| D1 Readiness packet (Phase 0) | Institution ISO confirms each Exhibit C control has live evidence |
| D2 Pilot tenant live with Entra SSO | Faculty sign-in works; non-pilot accounts denied; deprovisioning test passes |
| D3 Onboarding workshop + materials | Delivered |
| D4 Mid-pilot and final metrics report (M1–M8) | Delivered within [10] business days of milestone |
| D5 Data return and deletion certificate | Per §9 |
| D6 (Option C) Accessible output feature | Per §7 |

## 7. Planned output feature — acceptance criteria (Option C)

For generated accessible HTML and tagged PDF (PDF/UA-1 target):
1. Generated from the human-confirmed structure only; the original is never modified.
2. Provider's checker run on the output with results shown in the four lanes.
3. PdfCraft checker and (when the runtime has it) veraPDF PDF/UA-1 run, with results reported verbatim and tool versions recorded; when a tool is unavailable the report discloses the skipped check.
4. Not-assessed areas listed for human review.
5. Output and report labeled as technical evidence, not a conformance determination.

## 8. Pricing options

All figures are placeholders for decision. Fees are fixed per pilot (not per document) so faculty are never discouraged from re-checking.

| | **Option A — Local Workbench Pilot** | **Option B — Hosted Semester Pilot** | **Option C — Hosted Pilot + Accessible Output & Training** |
|---|---|---|---|
| What | Faculty use the local workbench on their own computers; workshop; office hours; survey-based report (M1–M3 from voluntarily shared evidence receipts) | Everything in A during Phase 0, then hosted pilot with Entra SSO for up to [N] faculty | Everything in B plus accessible HTML/tagged PDF output (D6), second workshop, department repeat-defect report, prioritized AT testing |
| Data held by Provider | None (documents never leave faculty computers) | Hosted documents under DPA | Hosted documents under DPA |
| Fee | **[PRICE_A]** fixed | **[PRICE_B]** fixed | **[PRICE_C]** fixed |
| Invoicing | 100% on start | [30]% on signature · [40]% on readiness gate (D1/D2) · [30]% on final report | [30]% · [40]% · [30]%, with D6 acceptance before final invoice |
| Main risk | Install friction; limited central metrics | Readiness gate schedule | Planned feature schedule |

**Rationale**
- *Fixed fee* keeps procurement simple [COUNSEL/PURCHASING: confirm district small-purchase threshold and whether a sole-source or informal-quote process applies].
- *Milestone invoicing tied to the readiness gate* means Institution does not pay for hosted service before the security controls are proven.
- *Cost basis* for B/C: the private Render topology (starter web + starter worker + Pro private ClamAV service + starter Key Value + Basic-1gb and Basic-256mb Postgres) at [MONTHLY INFRA COST] × [MONTHS], object storage [COST], Clerk [COST], plus support and engineering hours [HOURS × RATE].
- *Option A* is offered because it delivers the core review–learn–fix–verify loop with the smallest data-protection footprint while hosted controls are completed.

## 9. Exit, data return, and transition

- No automatic renewal; continuation requires a new purchase order.
- Within [10] business days of pilot end (or earlier on request): export of each faculty member's documents, fixed copies (PDF), and findings/evidence receipts (JSON) [operator-assisted until an export feature ships].
- Within [30] days after pilot end: verified deletion from live systems with a deletion certificate (counts, verification ID); backups expire within [MAX BACKUP-EXPIRY DELAY].
- Content-free deletion tombstones and audit events retained for [N] years (see `data-retention-and-deletion.md`).
- Clerk accounts for pilot users removed within [10] business days.
- If the readiness gate is not met by [DATE], Institution may end the hosted portion and pay only for delivered milestones; Option A services continue through the term.

## 10. Change control

Changes to scope, faculty count, or timeline by written change order signed by both pilot leads.

Signatures: Institution [NAME/TITLE/DATE] · Provider [NAME/TITLE/DATE]
