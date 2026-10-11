**DRAFT — prepared for counsel review. Not legal advice. Not yet adopted.**

# Data retention and deletion — what the code supports today

Prepared [2026-10-11] from source. Status key: **Implemented** = in code and tested locally; **Defined** = contract/schema/runbook exists, live adapter not built or not provisioned; **Gap** = not designed yet.

> Important context: the hosted real-document path (`service/real_intake/`) is a locked foundation. It has **no upload, process, download, or delete HTTP route**, and its Render resources are not provisioned (`docs/real-intake-provisioning-checkpoint.md`). The hosted staging service handles bundled synthetic fixtures only. Every "Defined" row below must reach live verification before the pilot accepts a real document.

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
| Hosted staging (synthetic only) | Synthetic documents in SQLite; audit rows | User can "Remove this synthetic record" (deletes version and rechecked copies); audit remains | Implemented (`service/repository.py` `delete_document_lineage`) |
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
| G6 | No automatic retention default | Institution may require fixed retention | Institution-selected default (e.g., delete [N] days after pilot end), executed and verified by operator |
| G7 | Quarantine object kept after clean promotion | Unnecessary duplicate copy | Delete quarantine object on promotion (reviewed change) |
| G8 | Clerk account offboarding undefined | Account data retention | Written deprovisioning procedure; SSO-driven later |
| G9 | Log retention undefined | HECVAT/DPA questions | Document Render log retention; confirm no content in logs via test |

## 6. Proposed pilot retention schedule [FOR DECISION]

| Data | Proposed |
|---|---|
| Documents and outputs | Until owner deletes, or [30] days after pilot end, whichever first |
| Return/export on request | Within [10] business days |
| Deletion after termination | Within [30] days, with deletion certificate |
| Backups | Expire within [MAX DELAY] days |
| Deletion tombstones and audit events | [N] years, content-free |
| Clerk accounts | Removed within [10] business days of pilot end or user offboarding |
