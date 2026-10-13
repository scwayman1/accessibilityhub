**DRAFT — prepared for counsel review. Not legal advice. Not yet adopted.**

# Data retention and deletion — what the code supports today

Prepared [2026-10-11] from source. Status key: **Implemented** = in code and tested locally; **Defined** = contract/schema/runbook exists, live adapter not built or not provisioned; **Gap** = not designed yet.

## 0. The hosted pilot service: decided 2026-10-13

The product owner decided to open real PDF uploads on the hosted pilot service, with a **365-day retention period**. This is the service that runs on Render today (`render.yaml`). It is separate from the locked real-intake foundation described in the rest of this document, which stays as it is.

| Item | What the code does | Where |
|---|---|---|
| Who can upload | Signed-in users only (pilot access code). Uploads never open on a workspace with `HUB_PUBLIC_ACCESS=true`. Only the exact value `HUB_ACCEPT_UPLOADS=true` opens them. | `service/settings.py` `uploads_ready` |
| What is accepted | PDF only (`.pdf` name and `%PDF-` header), 50 MB maximum. Uploads stop with an honest message when the data disk has less than about 150 MB free. | `service/app.py` |
| Where files live | One Render persistent disk at `/var/data` (SQLite records, original PDFs, improved copies, page-1 thumbnails) | `render.yaml` |
| **Automatic deletion** | **365 days after upload**, the original and every copy made from it are deleted together: files, records, jobs and remediation rows. The worker checks hourly and at startup. Each deletion writes a content-free audit event (`document_expired`: document ID, count, retention days, upload time; no filename or content). Set by `HUB_RETENTION_DAYS` (1–3650). | `service/worker.py` `sweep_retention` |
| Deleting sooner | Any signed-in user can delete a document (the original and every copy) from its page. The deletion is audited as `document_deleted`. | `service/app.py` |
| Shown to users | The upload page says documents are kept for 365 days and that everyone who signs in can see them. Each finished document shows its "Kept until" date. | `service/app.py` |
| Audit events | Kept indefinitely in the same SQLite file and hold no document content. A retention period for them is still open (G5). | `service/repository.py` |

**Known limits of the pilot service. Disclose these to the Institution:**
- **One shared workspace.** Everyone who signs in with the pilot access code sees every uploaded document. Per-person separation comes with SSO (open item 4).
- **No malware scanning.** PDFs are parsed by the worker inside the web service container, which runs as an unprivileged user with time limits. The ClamAV gate belongs to the locked real-intake path.
- **Disk snapshots.** Render takes disk snapshots. Their expiry delay still needs to be recorded (G4).
- **Size.** The disk is 1 GB. It can be resized in the Render dashboard (resizing up is one-way).

> Context for the sections below: the hosted real-document path (`service/real_intake/`) is a locked foundation. It has **no upload, process, download, or delete HTTP route**, and its Render resources are not provisioned (`docs/real-intake-provisioning-checkpoint.md`). The hosted staging service handles bundled synthetic fixtures only. Every "Defined" row below must reach live verification before the pilot accepts a real document.

## 1. Current policy

- Lifecycle policy ID: `manual-owner-deletion-only` (`render.real-intake.yaml`, `HUB_LIFECYCLE_POLICY_ID`).
- Real documents have **no time-based deletion deadline** (`service/real_intake/deletion.py`, "Real documents have no time-based deletion deadline").
- Object-store lifecycle expiry must **not** be used as the primary deletion mechanism; deletions must be initiated, tracked, verified, and audited (`docs/real-intake-operations.md`).
- Activation is blocked until the backup products document a maximum backup-expiry delay, recorded in `HUB_BACKUP_DELETION_SLA`.

## 2. Data inventory and retention map — hosted real-intake (pilot path)

| Data | Location | Retention today | Deleted by owner deletion? | Status |
|---|---|---|---|---|
| Uploaded PDF (quarantine) | Object store `quarantine/<owner>/<doc>.pdf` | Until owner deletion | Yes — in deletion inventory | Defined (storage provider not selected; adapter pending) |
| Clean promoted copy | `clean/<owner>/<doc>.pdf` | Until owner deletion | Yes | Defined |
| Fixed copies / derivatives (incl. planned HTML + tagged PDF output) | `derivative/<owner>/<doc>/…` | Until owner deletion | Yes | Defined |
| Evidence (reports, receipts) | `evidence/<owner>/<doc>/…` | Until owner deletion | Yes | Defined |
| Document record (filename ≤200 chars, SHA-256, size, scan verdict/engine/signature version) | Postgres `real_documents` | Until owner deletion | Yes | Implemented (schema); live DB pending |
| Processing jobs | `real_processing_jobs` | Until owner deletion (FK cascade) | Yes | Implemented (schema) |
| Upload authorizations | `real_upload_authorizations` | Usable ≤5 minutes, single-use (DB-enforced); row persists until document deletion (cascade) | Yes | Implemented (schema) |
| Findings (rule ID, lane, evidence key) | `real_findings` | Until owner deletion (cascade) | Yes | Implemented (schema) |
| Model-egress consents | `real_model_egress_consents` | Until owner deletion (cascade); feature disabled | Yes | Implemented (schema); unused |
| Deletion request / tombstone (doc UUID, owner ID, counts, verification ID, timestamps) | `real_deletion_requests` | **Permanent** — immutable once verified; deliberately no FK so it survives document removal; DB trigger blocks DELETE | No (by design) | Implemented (schema) — **retention period undefined (Gap)** |
| Audit events (action, owner/actor ID, target UUID, request ID, allowlisted detail) | `real_audit_events` (outbox) → separate audit Postgres sink | **Permanent** — append-only; UPDATE/DELETE/TRUNCATE blocked by triggers | No (by design) | Outbox implemented; authoritative sink Defined; **retention period undefined (Gap)** |
| Rate-limit counters (hash of owner ID + action) | Render Key Value | Per time window (1 min – 1 h) | N/A | Defined (adapter pending) |
| Account data (email, MFA, sessions) | Clerk | Until account removed in Clerk | No — separate process | **Gap**: offboarding/deprovisioning procedure not written; SSO deprovisioning Planned |
| Database backups | Render Postgres | Provider schedule | Expire on schedule; restore re-applies tombstones | Restore runbook Defined; **max expiry delay not documented (Gap)** |
| Object-store versions/backups | Provider TBD | Provider TBD | Must be covered | **Gap** (provider not selected) |
| Application logs | Render | Render plan default | No | Policy: no document content, OCR text, prompts, or signed URLs in logs (Defined). **Log retention not documented (Gap)** |
| Support email | [EMAIL PROVIDER] | [TBD] | No | **Gap** |

## 3. Owner deletion — what happens (per `docs/real-intake-operations.md`)

1. Reverify session and exact owner subject.
2. Apply deletion rate limit (3/hour).
3. Mark document `deletion_pending` (cannot be queued, viewed, downloaded).
4. Delete every object in the inventory (quarantine, clean, derivatives, evidence).
5. Delete job, finding, consent, and document records in one owner-scoped transaction.
6. Re-query storage and database; any survivor = `failed`.
7. Preserve tombstone; append content-free audit event with counts and verification ID.
8. Tell the owner the backup-expiry delay separately.

## 4. Other surfaces

| Surface | Data | Retention / deletion | Status |
|---|---|---|---|
| Hosted pilot service (real PDF uploads since 2026-10-13; see §0) | Uploaded PDFs, copies and thumbnails on the Render disk; SQLite records; audit rows | Automatic deletion 365 days after upload, and user deletion at any time. Audit rows remain. | Implemented (`service/worker.py` `sweep_retention`, `service/repository.py` `delete_document_lineage`) |
| Hosted staging session | 20-hour signed cookie | Expires after 20 h; sign-out revokes it server-side | Implemented |
| Local workbench | PDF processed in memory on the user's machine; outputs downloaded by user | Nothing sent to Provider | Implemented |
| Local learning journey | `~/.coastline-studio/journey.json` (hash prefixes, rule IDs, attested decision text, timestamps) | User-controlled; delete the file | Implemented; **no in-app "clear history" control (Gap)** |

## 5. Gaps that block DPA commitments

| # | Gap | Why it matters | Proposed fix |
|---|---|---|---|
| G1 | No live deletion adapters (storage + DB) | DPA §9 deletion cannot be performed in-product | Build/verify adapters with non-sensitive canary before pilot |
| G2 | Deletion is owner-only (schema CHECK `requested_by = owner`) | Institution admin cannot delete departed faculty's documents; tenant-wide deletion at termination unsupported | Operator procedure for pilot; later reviewed admin/bulk deletion with audit |
| G3 | No export/return feature (no download route yet) | DPA §9.1 return obligation | Planned download route; operator-assisted export for pilot |
| G4 | Backup-expiry delay undocumented | Required to state deletion completeness | Record Render plan backup retention and object-store versioning policy in `HUB_BACKUP_DELETION_SLA` |
| G5 | Tombstone and audit retention undefined | Indefinite retention of identifiers may conflict with Institution policy | Decide period (e.g., [N] years) and an archival/purge path for the audit sink |
| G6 | ~~No automatic retention default~~ **Resolved for the hosted pilot service, 2026-10-13: 365 days** (§0) | Institution may require a different period | Change `HUB_RETENTION_DAYS` if the Institution sets one; deletion after pilot end is still operator-run |
| G7 | Quarantine object kept after clean promotion | Unnecessary duplicate copy | Delete quarantine object on promotion (reviewed change) |
| G8 | Clerk account offboarding undefined | Account data retention | Written deprovisioning procedure; SSO-driven later |
| G9 | Log retention undefined | HECVAT/DPA questions | Document Render log retention; confirm no content in logs via test |

## 6. Proposed pilot retention schedule [FOR DECISION]

| Data | Proposed |
|---|---|
| Documents and outputs | **365 days after upload (decided 2026-10-13, automatic)**, or sooner if a user deletes them. Deletion after pilot end: [30] days |
| Return/export on request | Within [10] business days |
| Deletion after termination | Within [30] days, with deletion certificate |
| Backups | Expire within [MAX DELAY] days |
| Deletion tombstones and audit events | [N] years, content-free |
| Clerk accounts | Removed within [10] business days of pilot end or user offboarding |
