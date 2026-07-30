# Controlled real-intake operations runbook

## Status

This runbook is pre-activation. It defines the required operator behavior but
does not claim that storage, backups, audit, queue, scanner, worker, or deletion
adapters are provisioned or verified. Real-document routes do not exist.

## Ownership and contact

Scott Wayman (`scott@coastlinecollegefoundation.com`) is the sole application
operator and incident owner. Application authorization uses his verified Clerk
`user_…` ID after the held invitation is eventually accepted; the email address
is only the human contact path.

The final private origin is
`https://accessibility.coastlinecollegefoundation.com`. The public synthetic
service and all preview URLs are outside this boundary.

## Retention

- Policy: `manual-owner-deletion-only`.
- A real test document has no automatic expiration date.
- Retain it until Scott submits an authenticated backend deletion request.
- Do not repurpose object-store lifecycle expiration as the primary deletion
  mechanism; a deletion must be initiated, tracked, verified, and audited.
- Activation is blocked until the selected storage and database backup products
  provide a documented maximum backup-expiry delay. Record the provider policy,
  plan/tier, effective date, and maximum delay in `HUB_BACKUP_DELETION_SLA`.

## Manual deletion

An owner deletion job must:

1. Reverify the Clerk session and exact owner subject.
2. Apply the deletion-request rate limit through private Render Key Value.
3. Mark the live document `deletion_pending` so it cannot be queued, viewed, or
   downloaded.
4. Inventory and delete:
   - `quarantine/<owner>/<document>.pdf`
   - `clean/<owner>/<document>.pdf`
   - every `derivative/<owner>/<document>/…` object
   - every `evidence/<owner>/<document>/…` object
5. Remove live processing-job, normalized-finding, model-consent, and document
   records in an owner-scoped database transaction.
6. Query storage and the database again. Any surviving object or record makes
   the deletion `failed`, not partially successful.
7. Preserve the deletion request/tombstone and append the protected audit event
   with counts and a verification ID. Never include object URLs or document
   content.
8. Tell Scott the documented maximum backup-expiry delay separately from live
   deletion completion.

## Rate and abuse controls

The code defines fail-closed private-counter limits:

| Action | Limit |
| --- | --- |
| Owner session probe | 30 per minute |
| Upload authorization | 5 per 10 minutes |
| Document view | 60 per minute |
| Document download | 20 per 10 minutes |
| Deletion request | 3 per hour |
| Future model egress | 5 per hour |

Counters are keyed by a hash of the verified Clerk owner ID and action. If the
private atomic counter store is unavailable or returns an invalid type,
negative count, impossible remaining count, or out-of-window retry value, the
sensitive operation is denied.

## Incident response

For suspected identity, origin, code, storage, malware, worker, or audit
compromise:

1. Disable intake first by removing or setting
   `HUB_REAL_DOCUMENT_INTAKE=false`, then redeploy the private service.
2. Confirm health reports `real_document_intake_enabled=false`.
3. Revoke Scott's active Clerk sessions. Temporarily ban the Clerk user if the
   account may be compromised.
4. Disable queued processing and revoke the worker/queue credentials.
5. Rotate affected object-storage, database, queue, Render, and Clerk
   credentials. A JWT public-key or issuer change requires a configuration
   update and full auth regression.
6. Preserve append-only audit records and protected sink data. Do not delete or
   rewrite evidence to make the system appear clean.
7. Inventory live quarantine, clean, derivative, and evidence objects without
   downloading their contents to an operator device.
8. Record scope, times, affected document IDs, credentials revoked, deletion
   results, backup-expiry expectations, and the verification-run ID.
9. Re-enable only after the root cause is fixed and the complete positive and
   negative activation suite passes again.

## Periodic verification before and after activation

- Clerk: restricted mode, TOTP required, only Scott invited/active, exact
  authorized party, no Google or Entra SSO.
- Storage: public access blocked, encryption on, credentials prefix-limited,
  signed URLs short-lived and single-use at the application layer.
- ClamAV: private endpoint, pinned image, current signatures, stale/unavailable
  behavior denied.
- Worker: no public listener, resource limits, no egress, clean-object-only job
  eligibility.
- Database/audit: private address, forced owner row-level security, application
  role cannot mutate/delete audit events, protected sink and restore test.
- Deletion: live objects and records absent, tombstone/audit present, backup
  delay communicated.
- Models: deterministic path works without a key; BYOK and egress remain off.
