**DRAFT — prepared for counsel review. Not legal advice. Not yet adopted.**

# Student Data Privacy and Data Processing Agreement — template

Between **[INSTITUTION LEGAL NAME]** ("Institution") and **[VENDOR LEGAL ENTITY NAME]** ("Provider") for Coastline Accessibility Hub (the "Service"). Effective [DATE].

> Drafting notes for counsel
> - Many California community colleges use the **California Student Data Privacy Agreement (CA-NDPA)** published by the Student Data Privacy Consortium, or a district-specific DPA. If Institution has one, sign that instead and attach Exhibit A–C below as the Provider-specific schedules.
> - California statutes cited below (Ed Code §49073.1 / AB 1584; SOPIPA, Bus. & Prof. Code §22584) are framed for **K-12 local educational agencies and operators**. Their direct application to a community college district is doubtful; this template adopts equivalent terms **contractually**. Counsel to confirm, and to check Ed Code §76200 et seq. (community college student records) and any district board policy.
> - Provider's operating entity, domain, and Render workspace are associated with the Coastline College Foundation. Counsel should confirm the contracting entity and whether any related-party or conflict-of-interest review applies.

## 1. Definitions

- **Institution Data**: all data, files, and records provided by or on behalf of Institution or its Authorized Users, including uploaded documents, derived copies, findings, evidence, and account data, together with any **Education Records** (as defined in FERPA, 20 U.S.C. §1232g; 34 C.F.R. Part 99) or personally identifiable information from them.
- **Security Incident**: an actual or reasonably suspected unauthorized access to, acquisition, use, disclosure, alteration, or destruction of Institution Data.
- **Subprocessor**: a third party that processes Institution Data on Provider's behalf.

## 2. FERPA school-official designation

2.1 Institution designates Provider as a **"school official" with a "legitimate educational interest"** under 34 C.F.R. §99.31(a)(1)(i)(B), because Provider performs an institutional service (document-accessibility review) for which Institution would otherwise use employees.
2.2 Provider is under Institution's **direct control** with respect to the use and maintenance of Institution Data, and will use Education Records only for the purposes authorized here.
2.3 Provider will not re-disclose personally identifiable information from Education Records except to Subprocessors bound by equivalent terms, or as required by law with prior notice to Institution where legally permitted (34 C.F.R. §99.33).
2.4 Institution is responsible for including in its annual FERPA notification criteria that cover contractors acting as school officials.

## 3. Ownership and control

3.1 Institution Data is and remains the property and under the control of Institution. Provider acquires no ownership.
3.2 Original files are never modified; the Service applies approved fixes only to copies, with before/after hashes recorded.
3.3 Authorized Users may retrieve their documents and outputs [PLANNED: download route]; Institution may request an export at any time (§9).

## 4. Permitted use; prohibitions

Provider will process Institution Data **only** to provide, secure, and support the Service as described in the Terms and SOW. Provider will **not**:

| Prohibition | Note |
|---|---|
| Sell, rent, or trade Institution Data | Absolute |
| Use Institution Data for targeted advertising | Sponsored cards (Coastline College Foundation) are static, non-targeted, and receive no Institution Data — see §11 |
| Build a profile of a student or user for any non-educational purpose | Learning-journey metrics serve the user/Institution only |
| Use Institution Data to train or fine-tune AI/ML models | No model is enabled; see §10 |
| Use Institution Data for any secondary purpose, including product improvement | [OPTION: permit content-free, de-identified aggregate rule-frequency statistics only with Institution's written consent] |
| Disclose to third parties | Except Subprocessors in Exhibit B or as legally required |

## 5. Security obligations

Provider will maintain administrative, technical, and physical safeguards appropriate to the sensitivity of Institution Data, including at minimum the controls in Exhibit C. Provider will not accept real Institution documents until every Exhibit C control marked "Required before real documents" has live verification evidence (see `docs/real-intake-control-matrix.md`).

## 6. Subprocessors

6.1 Exhibit B lists current Subprocessors. Provider will give Institution at least [30] days' written notice before adding or replacing a Subprocessor that processes Institution Data; Institution may object and terminate without penalty if unresolved.
6.2 Provider remains responsible for Subprocessors' performance and will bind each to written terms at least as protective as this Agreement.

## 7. Security Incident notification [COUNSEL TO SET TIMELINES]

| Step | Draft commitment |
|---|---|
| Initial notice to Institution's designated contact | Without unreasonable delay and no later than **[72] hours** after Provider confirms a Security Incident affecting Institution Data |
| Content of initial notice | Nature of incident, data categories and approximate records involved, date/time discovered, containment steps taken, Provider contact |
| Updates | Every [48] hours until contained, then a written root-cause report within [15] business days |
| Notice to affected individuals | Institution decides; Provider will cooperate and bear reasonable costs where the incident results from Provider's breach [COUNSEL] |
| Legal benchmarks to check | Cal. Civ. Code §1798.82 ("most expedient time possible and without unreasonable delay"); Ed Code §49073.1(b)(6) requires a description of notification procedures [K-12 framing]; any district policy |

Operational detail is in `incident-response-plan.md`.

## 8. Retention

Institution Data is retained only as long as needed to provide the Service or as Institution directs. Current Service behavior: documents are retained until the owning user deletes them (`manual-owner-deletion-only`); no automatic expiry. [DECISION: Institution-selected default retention period, e.g., delete all pilot documents [N] days after pilot end.] See `data-retention-and-deletion.md`, including identified gaps.

## 9. Return and deletion on termination

9.1 Within [30] days after termination or on written request, Provider will (at Institution's election) return Institution Data in a commonly used format (PDF for documents and copies; JSON for findings and evidence receipts) and then delete it from live systems.
9.2 Deletion is verified by re-querying storage and database for absence; any surviving object makes the deletion "failed," not partial. Provider will deliver a written deletion certificate with counts and verification ID.
9.3 Backup copies are deleted on the backup provider's expiry schedule, not to exceed **[MAXIMUM BACKUP-EXPIRY DELAY]**; restores re-apply all recorded deletions before reconnecting (`docs/real-intake-operations.md`).
9.4 Provider may retain content-free deletion tombstones and audit events (no document content, filenames are not included in audit detail) as evidence of deletion for [RETENTION PERIOD].
9.5 Known gap: the current design supports per-document deletion by the owning user only. Tenant-wide deletion at termination will be executed by Provider's operator under documented procedure until a reviewed bulk-deletion feature exists.

## 10. Artificial intelligence

No AI or external model processing is enabled. Any future use requires: written notice; explicit opt-in consent per document, provider, and purpose, revocable at any time (`service/real_intake/consent.py`); a pre-request data-egress manifest; a Subprocessor update under §6; and no use of Institution Data for model training.

## 11. Sponsored content

The Service may show static "Sponsored" cards for the Coastline College Foundation on processing screens. Provider verified in source (`service/app.py`, `_sponsored_card`) that the hosted card is server-rendered from `partner_ads.json`, rotates by clock time only, contains no script, pixel, or outbound link, and is served under a same-origin Content-Security-Policy with `Referrer-Policy: no-referrer`. No Institution Data is shared with any sponsor. [INSTITUTION DECISION: permit, or disable for the pilot tenant.]

## 12. Audits and assessments

Provider will complete Institution's security questionnaire (HECVAT Lite draft attached), provide its ACR, and permit [annual] review of controls on reasonable notice. Provider has no SOC 2 report; it relies on Subprocessor attestations [COUNSEL: acceptable for pilot scope?].

## 13. Data location

Hosted processing and storage in the United States (Render, Oregon). [Confirm Clerk and object-storage regions before signature.]

## 14. Term

Coterminous with the Terms/SOW; §§3, 4, 7, 9 survive until Institution Data is deleted.

---

## Exhibit A — Data elements

| Element | Purpose | Contains Education Records? |
|---|---|---|
| Authorized User name, email, auth identifiers, MFA status | Authentication | No (employee data) |
| Uploaded course documents (PDF) | Review and fix | **Possibly** — incidental student PII (rosters, graded work) [INSTITUTION: restrict pilot uploads?] |
| Original filename, hash, size, scan verdict | Integrity and malware gate | Possibly (filenames may contain names) |
| Findings, fixed copies, evidence receipts | Service output | Possibly (derived from documents) |
| Content-free audit events and deletion tombstones | Security and proof of deletion | No content; contains user identifier |
| Hashed rate-limit counters | Abuse prevention | No |

## Exhibit B — Subprocessors and service components

| Party | Role | Data | Location | Status |
|---|---|---|---|---|
| Render Services, Inc. | Hosting: web/API, worker, private ClamAV service, two Postgres databases (metadata, audit), Key Value queue/rate store | All hosted Institution Data | US — Oregon | Staging (synthetic only) live; private real-intake Blueprint defined, not applied |
| Clerk, Inc. | Authentication, MFA, sessions; broker for Microsoft Entra ID SSO [PLANNED] | Account data | [US — CONFIRM] | Development instance configured; production not created |
| [OBJECT STORAGE PROVIDER — NOT SELECTED] | Private encrypted storage of uploads, copies, evidence | Documents and outputs | [US — REQUIRED] | Gap — provider selection pending |
| [EMAIL / SUPPORT PROVIDER] | Support correspondence | Whatever users send to support | [CONFIRM] | Confirm provider for the operator mailbox |
| ClamAV (self-hosted) | Malware scanning inside Provider's Render environment | Documents (in Provider's environment only) | US — Oregon | **Not a separate Subprocessor.** Signature updates are downloaded from ClamAV mirrors; no Institution Data is sent |
| Microsoft Entra ID | Institution's own identity provider | Institution-controlled | Institution | Not a Provider Subprocessor |
| GitHub | Source code and CI (synthetic fixtures only) | None | — | Not a Subprocessor |
| AI model providers | None | None | — | None enabled |

## Exhibit C — Minimum security controls

| Control | Evidence | Required before real documents |
|---|---|---|
| Invite-only access; owner/tenant authorization on every query (forced Postgres RLS) | `service/real_intake/schema.sql`, `service/real_intake/auth.py` | Yes |
| MFA required | `docs/clerk-owner-only-setup.md` | Yes |
| Malware scan (pinned ClamAV 1.4.5, fail-closed on stale/unavailable) before parsing | `service/real_intake/clamav.py`, `deploy/clamav/Dockerfile` | Yes |
| Encryption in transit (HTTPS, exact origin) and at rest (storage/database) | `service/real_intake/settings.py`; provider docs [TO VERIFY] | Yes |
| No public datastore/scanner endpoints | `render.real-intake.yaml` (`ipAllowList: []`, private service) | Yes |
| Isolated worker with proven no-egress | `docs/real-intake-provisioning-checkpoint.md` | Yes — currently unmet |
| Content-free, append-only audit | `service/real_intake/audit.py`, schema triggers | Yes |
| Verified deletion with tombstone-aware restore | `service/real_intake/deletion.py`, `docs/real-intake-operations.md` | Yes |
| Rate limits, fail-closed | `service/real_intake/rate_limit.py` | Yes |
| Incident response owner and exercised tabletop | `incident-response-plan.md` | Yes |

Signatures: Institution [NAME/TITLE/DATE] · Provider [NAME/TITLE/DATE]
