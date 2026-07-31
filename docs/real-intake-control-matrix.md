# Controlled real-intake verification matrix

This matrix distinguishes code foundations from live controls. A code checkmark
does not mean a service is provisioned or that real-document intake may open.

| Control | Code/document foundation | Live evidence required before activation | Current status |
| --- | --- | --- | --- |
| Service partition | Private package/WSGI entrypoint; public app, `render.yaml`, and base requirements exclude it | Separate Render service and environment; public synthetic regression | Code complete; not provisioned |
| Final origin | Exact origin and Host/HTTPS checks pinned to `https://accessibility.coastlinecollegefoundation.com` | DNS, certificate, custom-domain routing, alternate-host rejection | Origin confirmed; DNS/service pending |
| Clerk owner identity | Networkless RS256, issuer/time/azp/v2/session/subject checks; email-only auth is rejected | Production instance, PEM public key, issuer, invitation acceptance, bound `user_…` ID, live positive/negative tests | Development settings hardened; invitation/production held |
| Future institutional SSO | COA-14 and deferred design boundary documented | Separate later threat model and tenant/domain/role/deprovisioning tests | Google and Entra disabled |
| Activation gate | Exact-true flag, manifest version, fresh runtime evidence, and an unconditional missing-handler blocker | Reviewed implementation release plus all evidence below | Locked in code |
| Quarantine upload | Five-minute owner/document-scoped authorization, canonical IDs, exact PDF/size/encryption/private-ACL conditions, database-enforced object keys, atomic single-use Postgres function | Private encrypted S3-compatible store, public-access block, least-privilege credentials, live signed-upload tests | Code/schema complete; store pending |
| Validation | Filename, MIME, size, PDF signature, owner/key, page/stream/expanded-stream limits | Isolated post-scan structural validator with resource limits | Policy complete; adapter pending |
| Malware scan | Bounded INSTREAM client and strict complete-response classification; unavailable/error/ambiguous/future/stale evidence denied | Private pinned ClamAV service, signature updater, freshness/health evidence, EICAR and outage tests | Client/policy complete; scanner pending |
| Durable records | Postgres schema for documents, authorizations, jobs, findings, consents, deletions, and audit | Private Render Postgres, restricted application/worker roles, migrations, restore test | Schema validated locally; Postgres pending |
| Owner scoping | Forced Postgres RLS on all owner tables; transaction owner setting; owner-scoped object keys | Live cross-owner denial tests using non-production fixtures | Local SQL test passes; live DB pending |
| Queue/worker | Clean-only deterministic job envelope; dormant locked worker imports no network or processing clients; lifecycle transition contract | Private Render Key Value, resource/time limits, and infrastructure-enforced outbound-denial proof | Dormant worker ready; Render environment isolation does not block public egress, so processing remains blocked |
| Audit | Code and database action allowlists reject content/OCR/prompts/responses/tokens/credentials/URLs; append-only DB trigger | Protected external sink, restricted roles, retention/access policy, recovery test | Code/schema complete; sink pending |
| Manual deletion | Inventory covers quarantine, clean, derivatives, evidence, jobs, findings, consents, and document; absence proof required | Storage/database deletion adapters, backup-expiry SLA, live positive/negative tests | Contract/runbook complete; adapters/SLA pending |
| Rate/abuse | Per-action limits, hashed owner buckets, malformed/over-limit counter replies and counter-store outages denied | Atomic private Render Key Value adapter and concurrency tests | Contract complete; adapter pending |
| Incident response | Disable-first, Clerk revoke/ban, credential rotation, queue stop, audit preservation, re-verification runbook | Confirmed contact/on-call path and exercised tabletop | Runbook complete; exercise pending |
| BYOK/model egress | Deterministic path needs no key; flags off; document/owner/provider/purpose consent and revocation checks | Separate reviewed feature, secret storage, consent UX, egress manifest, negative tests | Disabled |
| End-to-end suite | Unit, cryptographic, WSGI, lifecycle, ingestion, deletion, consent, rate, and PostgreSQL security tests | Deployed positive/negative canary run with a non-sensitive PDF | Local tests pass; deployed run pending |
| Locked infrastructure definition | Separate non-default Blueprint; protected network-isolated environment; previews/service auto-deploys off; runbook requires dashboard Auto Sync off; maintenance mode; exact custom domain; Render subdomain disabled | Billing approval, published source branch, Blueprint Auto Sync check, resource creation, and deployed inspection | Official schema and local scanner build pass; application paused before billing |

## Activation invariants

All of these must be true simultaneously:

1. The code-level missing-handler blocker has been removed only in a reviewed
   implementation that supplies no route to the public service.
2. `HUB_REAL_DOCUMENT_INTAKE` is exactly `true`; near-miss values remain false.
3. Static configuration is complete and contains no development Clerk key.
4. Runtime evidence has a bounded verification ID, is no more than five minutes
   old, and is not future-dated.
5. Every live control in the matrix reports verified.
6. BYOK/model egress remains off.
7. The first input is a non-sensitive canary and deletion is verified before
   any institutional test document is considered.
