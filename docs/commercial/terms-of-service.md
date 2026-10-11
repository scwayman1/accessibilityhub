**DRAFT — prepared for counsel review. Not legal advice. Not yet adopted.**

# Coastline Accessibility Hub — Terms of Service (draft)

| Field | Value |
|---|---|
| Provider | [VENDOR LEGAL ENTITY NAME], [ADDRESS] ("Provider") |
| Customer | [INSTITUTION LEGAL NAME, e.g., COAST COMMUNITY COLLEGE DISTRICT on behalf of Coastline College] ("Institution") |
| Effective date | [EFFECTIVE DATE] |
| Order of precedence | (1) Signed Data Processing Agreement (`ferpa-dpa-template.md`); (2) Statement of Work (`pilot-sow-and-pricing.md`); (3) these Terms; (4) Privacy Policy |

> Drafting note: for an institutional pilot these Terms are expected to be attached to, or superseded by, the Institution's own purchase-order terms. Counsel should reconcile conflicts rather than rely on click-through acceptance.

## 1. The service

1.1 **What it is.** A document-accessibility review tool that (a) runs deterministic technical checks on PDFs, (b) explains each finding with an educator teaching card, (c) applies fixes the user approves **to a copy only**, and (d) rechecks the copy. Results are sorted into four lanes: Needs attention, Review recommended, Verified signal, Not assessed.

1.2 **What it is not.** The service provides technical evidence and review routing only. It does **not** provide a compliance score, certification, or overall pass, and its output is not a WCAG, Section 508, PDF/UA, ADA, or other legal conformance determination. Areas the tool does not assess (for example color contrast inside documents, table semantics, forms, color-only meaning) are reported as **Not assessed** and require human review. Institution remains responsible for its own accessibility obligations and determinations.

1.3 **Surfaces.** (a) Public site and guided sample (synthetic content); (b) hosted workspace; (c) local workbench that runs on the user's own computer, where the selected PDF does not leave that computer unless the user separately configures and approves an optional AI connection.

1.4 **Planned features.** Features labeled Planned in the SOW (including accessible HTML and tagged PDF output targeting PDF/UA-1, generated with WeasyPrint and checked by Provider's checker, the open-source PdfCraft checker, and veraPDF when available) are not warranted until delivered and accepted under the SOW. Checker results on generated output are evidence, not a conformance claim.

## 2. Accounts and access

2.1 Access is invite-only. Institution designates authorized users ("Authorized Users"). Authentication is provided through Clerk; Microsoft Entra ID single sign-on is [PLANNED — see SOW readiness gate].
2.2 Users must keep credentials and MFA factors confidential and promptly report suspected compromise to [SECURITY CONTACT].
2.3 Institution must promptly notify Provider when an Authorized User should be deprovisioned [until SSO deprovisioning is live].

## 3. Acceptable use

Users must not: upload content they lack the right to process; upload malware or attempt to bypass the malware gate, rate limits, or access controls; probe or load-test the service without written permission; upload documents classified above [INSTITUTION DATA CLASSIFICATION LEVEL, e.g., "Confidential — no SSNs, health, or financial aid records"] during the pilot; or use output to represent that a document has been certified or determined conformant.

## 4. Institution data

4.1 **Ownership.** Institution (or its users) retains all rights in documents uploaded and in outputs derived from them ("Institution Data"). Provider receives a limited license to process Institution Data solely to provide the service.
4.2 **No sale, no secondary use, no advertising based on Institution Data, no model training.** Governed in detail by the DPA.
4.3 **Fixes on copies.** Provider never modifies the original file; each mutation records before/after hashes.

## 5. Sponsored messages

The hosted workspace may show a clearly labeled "Sponsored" card for the Coastline College Foundation while a review runs. The card is server-rendered without scripts or tracking, never delays results, and receives no Institution Data. [COUNSEL/INSTITUTION DECISION: retain, disable for the pilot tenant, or limit to the local workbench.]

## 6. Artificial intelligence

No AI model is enabled in the hosted service. Any future model feature requires (a) advance written notice to Institution, (b) explicit opt-in consent per document, provider, and purpose, revocable at any time, and (c) a subprocessor update. A model can never resolve a human-judgment item, apply alternative text without human approval, or generate a compliance verdict (`docs/ai-architecture-byok.md` §31).

## 7. Fees

As set out in the SOW: [PRICE], invoiced [INVOICE SCHEDULE], payable net [30] days. No automatic renewal into a paid term without a new purchase order.

## 8. Warranties and disclaimers

8.1 Provider warrants that the service will perform materially as described in the SOW and that Provider will not knowingly introduce malicious code.
8.2 **Disclaimer.** Except as stated, the service is provided "as is." Provider does not warrant that use of the service, or any fixed copy, will make a document conformant with any accessibility standard or law, or that the checks detect every barrier. [COUNSEL: confirm enforceability against a public entity and align with Institution's standard terms.]

## 9. Indemnity and liability

9.1 Provider indemnity for third-party IP claims against the service: [COUNSEL TO DRAFT].
9.2 Mutual limitation of liability: [CAP, e.g., fees paid in prior 12 months]; carve-outs for breach of the DPA's confidentiality/security obligations: [SUPER-CAP OR UNCAPPED — COUNSEL].
9.3 Insurance: Provider to maintain [CYBER LIABILITY $____] and [GENERAL LIABILITY $____] [CONFIRM WITH INSTITUTION RISK MANAGEMENT].

## 10. Term, suspension, termination

10.1 Term per SOW. Either party may terminate for material breach uncured within [30] days, or Institution for convenience on [30] days' notice [with pro-rata refund — DECISION].
10.2 Provider may suspend access immediately to contain a security incident (see `incident-response-plan.md`), with prompt notice.
10.3 On termination, data return and deletion per the DPA and `data-retention-and-deletion.md`.

## 11. Accessibility of the service itself

Provider publishes an Accessibility Conformance Report for the product's own interface (`accessibility-conformance-report.md`) and will remediate reported barriers in its interface per [REMEDIATION TIMELINE]. Formal assistive-technology testing is pending.

## 12. General

Governing law: State of California [COUNSEL CONFIRM]. Venue: [COUNTY]. Public records: Provider acknowledges Institution is subject to the California Public Records Act [COUNSEL CONFIRM SCOPE]. Notices: [NOTICE ADDRESSES]. Entire agreement; amendments in writing; assignment requires consent.

## 13. Contact

[SUPPORT CONTACT] · [SECURITY CONTACT] · [PRIVACY CONTACT]
