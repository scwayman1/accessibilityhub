**DRAFT — prepared for counsel review. Not legal advice. Not yet adopted.**

# Commercial and procurement pack — Coastline Accessibility Hub

Prepared [2026-10-11] for an invoiced, single-institution pilot with Coastline College. Every statement about the product was drawn from the repository (README, `docs/`, `render*.yaml`, `service/`). Anything unknown is a `[BRACKETED PLACEHOLDER]`. Where a control exists in code but is not provisioned, the documents say **Planned**, not Implemented.

## Product facts the pack relies on

- Produces technical evidence and review routing only — four lanes (Needs attention / Review recommended / Verified signal / Not assessed); **no compliance score, certification, or pass**.
- Fixes are applied only to a copy, with before/after hashes.
- Deterministic; works without AI. No model is enabled in the hosted service; any future model use requires explicit opt-in consent (`docs/ai-architecture-byok.md`, `service/real_intake/consent.py`). The local workbench has an optional, user-configured key with a per-request "Allow once" manifest.
- Hosting: Render, Oregon (US). Postgres with forced row-level security. Self-hosted ClamAV scan before parsing. Clerk authentication; Microsoft Entra ID SSO planned for the pilot.
- Hosted real-document intake is a **locked foundation**: no upload/process/download/delete routes; Render Blueprint not applied; object store not selected.
- Planned output: accessible HTML + tagged PDF (PDF/UA-1 target) generated with WeasyPrint, checked by our checker, PdfCraft (github.com/storytold/pdfcraft), and veraPDF when available.
- Sponsored Coastline College Foundation cards appear on processing screens. Verified in `service/app.py` (`_sponsored_card`): server-rendered from `partner_ads.json`, clock-based rotation, no script/pixel/link, same-origin CSP and `Referrer-Policy: no-referrer` — **no user or document data reaches a sponsor**. Local workbench version includes a plain link to `https://www.coastline.edu` (`local_reviewer.html`, `renderAd`).

## Documents

| File | Purpose | Status |
|---|---|---|
| [privacy-policy.md](privacy-policy.md) | Public privacy policy | Draft — counsel review; several [PLANNED] statements cannot be published as present-tense facts yet |
| [terms-of-service.md](terms-of-service.md) | Service terms and claim boundary | Draft — expect to be reconciled with Institution PO terms |
| [ferpa-dpa-template.md](ferpa-dpa-template.md) | FERPA school-official DPA with subprocessor and security exhibits | Draft — prefer the CA-NDPA if Institution uses it; CA statute applicability flagged |
| [data-retention-and-deletion.md](data-retention-and-deletion.md) | Retention map against actual code/schema, with gaps G1–G9 | Draft — accurate to source as of date; 9 gaps |
| [hecvat-lite-draft.md](hecvat-lite-draft.md) | HECVAT Lite answers with evidence paths | Draft — many items Planned/Gap; transfer into official workbook |
| [accessibility-conformance-report.md](accessibility-conformance-report.md) | VPAT 2.5 (WCAG 2.2) style ACR for the product UI | Draft — code inspection only; AT testing pending; 4 known defects |
| [incident-response-plan.md](incident-response-plan.md) | Roles, severity, notification, tabletop checklist | Draft — tabletop not yet exercised; single-operator risk |
| [pilot-sow-and-pricing.md](pilot-sow-and-pricing.md) | Scope, readiness gate, honest metrics, three pricing options, exit terms | Draft — prices and counts are placeholders |

## Open items requiring a human decision

| # | Decision | Owner | Docs affected |
|---|---|---|---|
| 1 | **Contracting entity.** Operator domain and Render workspace belong to the Coastline College Foundation, and the customer is Coastline College / its district. Confirm the vendor legal entity and whether related-party, conflict-of-interest, or gift/sponsorship rules apply. | Counsel, Foundation, District purchasing | All |
| 2 | **Hosted readiness vs. pilot date.** Hosted intake has no routes and no provisioned infrastructure; worker no-egress is unproven. Choose Option A (local) to start, or commit engineering time and a gate date for Option B/C. | Product owner | SOW, DPA, HECVAT |
| 3 | **Object storage provider** (private, encrypted, US, documented backup expiry). Becomes a listed subprocessor. | Product owner, ISO | DPA Exhibit B, retention, privacy |
| 4 | **Microsoft Entra SSO + multi-user roles.** Current design is owner-only; needs threat model, role design (faculty vs. admin), deprovisioning. | Product owner, Institution IdP admin | SOW, HECVAT, ToS |
| 5 | **Sponsored cards in an institutional tool.** Keep, disable for the pilot tenant, or limit to the local workbench; confirm acceptability under district advertising policy and SOPIPA-style terms. | Institution, counsel | ToS §5, DPA §11, privacy §5 |
| 6 | **Breach-notice timelines** (draft uses [72] hours after confirmation) and liability cap/super-cap. | Counsel | DPA §7, IRP §5, ToS §9 |
| 7 | **Retention defaults**: post-pilot deletion window, backup-expiry maximum, how long tombstones and audit events are kept. | Institution, counsel | Retention §6, DPA §8–9 |
| 8 | **Secondary use**: strict no-use (draft default) vs. content-free aggregate rule statistics with consent. | Counsel, Institution | DPA §4, privacy §3 |
| 9 | **Data classification limit for pilot uploads** (e.g., no rosters with student IDs). | Institution ISO / FERPA officer | SOW §3, DPA Exhibit A |
| 10 | **Named backup incident responder** with least-privilege emergency access; tabletop date. | Product owner | IRP |
| 11 | **ACR**: schedule AT testing; fix ACR-1 (field-border contrast 1.5:1), ACR-2 (no pause control), ACR-3 (meta refresh / session expiry), ACR-4 (labels); obtain Clerk and Microsoft sign-in ACRs. | Product owner | ACR |
| 12 | **California law applicability** (Ed Code §49073.1/AB 1584 and SOPIPA are K-12-framed; Ed Code §76200 et seq.; CCPA/CPRA for the operating entity; Public Records Act; ADA Title II web-rule timelines — product messaging must not imply it satisfies them). | Counsel | DPA, ToS, privacy |
| 13 | **Prices, faculty count, document cap, semester dates**; confirm district purchasing threshold. | Product owner, purchasing | SOW §8 |
| 14 | **Third-party assurance**: no vendor SOC 2 or pen test; decide whether Render/Clerk attestations plus readiness packet suffice for pilot. | Institution ISO | HECVAT, DPA §12 |
| 15 | Use of the Coastline College name and logo in product surfaces — confirm written permission/brand approval. | Institution marketing, counsel | ToS, ACR |

## Language rule

All documents avoid conformance-outcome claims, consistent with the product's CI governance test (`tests/test_evidence.py`). Keep it that way in edits.
