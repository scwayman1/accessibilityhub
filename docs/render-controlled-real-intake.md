# Render controlled real-document test environment

## Scope and safety boundary

This is a design and provisioning plan for a **Scott Wayman-only**, controlled test path. It does not enable real-document uploads. The existing public synthetic reviewer remains separate and unchanged.

No real document may be accepted until every required service, secret, and negative-path test listed below is complete.

## Render topology

Deploy these in one dedicated Render environment and region:

1. **Real-intake web API** — a separate Render web service. It exposes only authenticated owner operations and never shares routes or storage with the public synthetic reviewer.
2. **Assessment worker** — a Render background worker, not a web-process thread. It reads only clean, queued objects and has strict CPU, memory, and execution-time limits.
3. **Render Postgres** — durable owner-scoped metadata, job state, deletion requests, and audit references. Use its private network address; do not use the public URL.
4. **Render Key Value** — queue and rate-limit state, connected only over the Render private network.
5. **ClamAV scanner service** — a private Render service with no public URL. It receives only quarantine objects or scanner jobs and returns clean, rejected, or indeterminate verdicts.

Keep all Render components in the same workspace, environment, and region. Block cross-environment private connections. The real-intake API is the sole public component; the worker and scanner have no public URL.

## External dependencies

Render does not provide a private object store or a malware verdict service. Provision these before implementation:

- A private encrypted S3-compatible object store with separate **quarantine**, **clean**, **derivative**, and **evidence** prefixes; no public bucket policy or public URLs.
- Least-privilege credentials that permit only the required prefix actions.
- A pinned ClamAV scanner image and signature-update procedure. Scanner-health failures, stale definitions, and indeterminate results must fail closed; no parser may read those files.
- A retention and backup policy that honors Scott's manual deletion requests and records any backup-expiry delay.
- A protected, append-only audit destination. Render Postgres can store application audit records, but the chosen audit retention and access policy must be confirmed separately.

## Clerk owner-only boundary

Use Clerk for the real-intake web API only.

Required Render secrets:

- `CLERK_PUBLISHABLE_KEY`
- `CLERK_SECRET_KEY` or a Clerk JWT verification public key
- `CLERK_ISSUER`
- `CLERK_AUTHORIZED_PARTY` for the final HTTPS origin
- `HUB_OWNER_CLERK_USER_ID`

The API must verify Clerk session tokens server-side on every real-document request, reject expired or invalid tokens, verify the issuer and authorized party, then require the token subject to equal `HUB_OWNER_CLERK_USER_ID`. Configure a Clerk invitation for Scott's verified Coastline College Foundation email, then record the resulting Clerk user ID as the owner secret. The exact email address is not stored in this repository. Do not use an email comparison as the authorization control.

## Required document lifecycle

1. Owner-authenticated API creates a short-lived, single-use upload authorization with an explicit PDF-only size and page limit.
2. The browser uploads directly to the private **quarantine** prefix.
3. The scan gate verifies file signature, declared type, size, page/stream limits, and malware verdict. It fails closed.
4. Only a clean file moves to the **clean** prefix and becomes eligible for a queued assessment.
5. The background worker processes a private copy, writes normalized findings and evidence references to Postgres, and never logs document bytes, OCR text, or signed URLs.
6. Scott can request deletion. A durable deletion job removes original, derivatives, and evidence objects; it records and verifies completion.

## Incident ownership

Scott Wayman is the incident owner for this controlled test environment. The audit and incident procedure must use his verified Coastline College Foundation identity after Clerk is configured. This does not replace the need for a documented contact path and an access-revocation procedure.

## Activation gate

Keep `HUB_REAL_DOCUMENT_INTAKE` unset or false until all of the following have passing integration and negative-path tests:

- Clerk owner token accepted; all other identities rejected.
- Storage is private, encrypted, and prefix-limited.
- Unsafe, oversized, malformed, ClamAV-rejected, stale-definition, and indeterminate-scan uploads are rejected before parsing.
- The worker cannot receive public traffic and processes only clean queued objects.
- Every action records the Clerk user ID in the audit trail.
- Owner deletion removes all live objects and records the verified result.
- Backup/deletion timing, Scott's incident ownership, and the access-revocation procedure are documented.

## AI and BYOK

No model key is required. Deterministic PDF inspection, assessment, remediation, and deletion operate without external AI. Any future model-assisted explanation or drafting must be separate, disabled by default, and require document-specific egress consent.
