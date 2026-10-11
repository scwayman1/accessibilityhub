**DRAFT — prepared for counsel review. Not legal advice. Not yet adopted.**

# HECVAT Lite — draft responses

Prepared [2026-10-11] from repository source. Transfer answers into the current official EDUCAUSE HECVAT workbook ([HECVAT VERSION]) before submission; this table is organized by question area, not by official question ID.

**Status key:** **Implemented** = in code and tested (locally/CI); **Planned** = designed/defined in code or docs but not provisioned or not live; **Gap** = not designed or not in place. "Implemented" for real-intake controls means *code/schema*, not live infrastructure — see `docs/real-intake-control-matrix.md`.

## A. Company and product overview

| Question area | Answer | Evidence | Status |
|---|---|---|---|
| Vendor legal entity, address, contact | [VENDOR LEGAL ENTITY], [ADDRESS], [CONTACT] | — | Gap (to fill) |
| Product description | Deterministic PDF accessibility review: findings in four lanes, educator teaching cards, permission-gated fixes on a copy, recheck. Technical evidence and routing only — no compliance score, certification, or pass | `README.md` | Implemented |
| Deployment model | Hosted SaaS on Render (US, Oregon) + optional local workbench running on the user's computer | `render.yaml`, `render.real-intake.yaml`, `local_reviewer.py` | Hosted real-document path Planned; local Implemented |
| Number of staff with production access | One operator (sole incident owner) | `docs/real-intake-operations.md` | Implemented — single point of failure noted |
| Third-party audit (SOC 2 / ISO 27001) | None for vendor; relies on Render and Clerk attestations [obtain and attach] | — | Gap |
| Cyber insurance | [CARRIER / LIMIT] | — | Gap (to confirm) |

## B. Documentation and policies

| Question area | Answer | Evidence | Status |
|---|---|---|---|
| Written information security policy | Engineering runbooks exist; no formal organizational ISP | `docs/real-intake-operations.md` | Gap |
| Incident response plan | Draft plan + technical runbook | `incident-response-plan.md`, `docs/real-intake-operations.md` | Planned (tabletop not exercised) |
| Data retention/deletion policy | Manual owner deletion with verification; gaps listed | `data-retention-and-deletion.md` | Planned |
| Privacy policy | Draft | `privacy-policy.md` | Planned |
| Accessibility (VPAT/ACR) | Draft ACR, AT testing pending | `accessibility-conformance-report.md` | Planned |
| Business continuity / disaster recovery plan | Tombstone-aware restore procedure only | `docs/real-intake-operations.md` | Gap (no BCP/DR plan, RTO/RPO undefined) |
| Security awareness training / background checks | — | — | Gap |

## C. Application security

| Question area | Answer | Evidence | Status |
|---|---|---|---|
| Secure SDLC, code review | Changes via pull requests; CI runs full unit suite + PostgreSQL security contract on every PR | `.github/workflows/test.yml` | Implemented |
| CI supply chain | GitHub Actions pinned by commit SHA; `contents: read` permission | `.github/workflows/test.yml` | Implemented |
| Dependency pinning | Exact versions pinned | `requirements.txt`, `requirements-real-intake.txt` | Implemented |
| Automated dependency/vulnerability scanning (SCA/SAST) | Not configured | — | Gap |
| Third-party penetration test | Not performed | — | Gap |
| Input validation for uploads | Filename, MIME, size (≤25 MiB), PDF signature, page/stream limits; DB-enforced object keys | `service/real_intake/upload_gate.py`, `schema.sql` | Implemented (code); live Planned |
| Malware scanning | Self-hosted ClamAV 1.4.5 (digest-pinned), private service, fail-closed on unavailable/stale/ambiguous results; scan before parsing | `service/real_intake/clamav.py`, `deploy/clamav/Dockerfile` | Implemented (code); live Planned |
| Parser isolation / no egress | Worker must have infrastructure-enforced outbound denial; Render isolation does not block internet egress, so processing remains blocked | `docs/real-intake-provisioning-checkpoint.md` | Gap (blocking) |
| Security headers | CSP `default-src 'self'`, `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` | `service/app.py` | Implemented (staging) |
| Rate limiting / abuse | Per-action limits, hashed owner keys, fail-closed when counter store unavailable | `service/real_intake/rate_limit.py` | Implemented (code); adapter Planned |
| Deploy guardrails | Predeploy check fails unless intake/model/origin/maintenance locks hold | `service/real_intake/deploy_check.py` | Implemented |
| Prohibited outcome language governance | CI test bans conformance-claim phrases on product surfaces | `tests/test_evidence.py` | Implemented |

## D. Authentication and access control

| Question area | Answer | Evidence | Status |
|---|---|---|---|
| Authentication provider | Clerk; networkless RS256 JWT verification with issuer, time, `azp`, session, subject checks; rejects impersonation and org-context tokens | `service/real_intake/auth.py`, `docs/clerk-owner-only-setup.md` | Implemented (code); production instance Planned |
| SSO (SAML/OIDC) with institution IdP | Microsoft Entra ID via Clerk targeted for pilot; requires separate threat model, tenant/domain restriction, role mapping, deprovisioning tests | `docs/clerk-owner-only-setup.md` ("Deferred institutional SSO") | Planned |
| MFA | TOTP required; SMS not sole factor (operator account) | `docs/clerk-owner-only-setup.md` | Implemented (dev instance config) |
| Invite-only / no self-registration | Clerk Restricted mode | `docs/clerk-owner-only-setup.md` | Implemented (dev instance config) |
| Multi-user roles (faculty, institution admin) | Current design is single owner; owner-scoped RLS generalizes per user, but no admin role | `schema.sql` | Gap |
| Session management | Clerk short-lived tokens (real-intake); staging: HMAC-signed 8-hour cookie, HttpOnly, SameSite=Lax, Secure | `service/app.py` | Implemented |
| Deprovisioning | Manual Clerk revocation/ban documented for incidents | `docs/real-intake-operations.md` | Gap (routine offboarding procedure) |
| Least privilege for infrastructure | Separate storage identities per function; scanner gets no other credentials; dormant worker gets none | `docs/real-intake-provisioning-checkpoint.md`, `render.real-intake.yaml` | Planned |

## E. Data protection

| Question area | Answer | Evidence | Status |
|---|---|---|---|
| Data classification handled | Course documents; may incidentally contain student PII (FERPA). No SSN, health, payment data intended | `ferpa-dpa-template.md` Exhibit A | Planned |
| Tenant/owner isolation | Forced Postgres row-level security on all owner tables; owner-scoped object keys enforced by CHECK constraints | `service/real_intake/schema.sql`, `tests/real_intake_schema_security.sql` | Implemented (local Postgres 18 + CI); live Planned |
| Encryption in transit | HTTPS on single exact origin; Host/HTTPS checks in code; Render subdomain disabled | `service/real_intake/settings.py`, `render.real-intake.yaml` | Implemented (code); DNS/TLS Planned |
| Encryption at rest | Required of object store (upload policy requires encryption); database at-rest encryption per Render [VERIFY Render documentation] | `docs/real-intake-provisioning-checkpoint.md` | Planned |
| Key management / customer-managed keys | Not offered | — | Gap |
| Data location | US — Render Oregon for all components | `render.real-intake.yaml` | Planned (staging live) |
| Fixes never touch originals | All mutations on a copy with before/after hashes | `tina/remedy.py`, `tina/structure.py`, `tina/ocr.py` | Implemented |
| Logging of document content | Prohibited; audit detail allowlists enforced in code and DB | `service/real_intake/audit.py`, `schema.sql` | Implemented (code) |
| Audit trail | Append-only (UPDATE/DELETE/TRUNCATE blocked); separate audit Postgres sink planned | `schema.sql`, `render.real-intake.yaml` | Outbox Implemented; sink Planned |
| Deletion | Owner-initiated, verified absence, immutable tombstone | `service/real_intake/deletion.py` | Implemented (contract); adapters Planned |
| Backups and restore | Render Postgres backups; restore must re-apply tombstones in isolated target | `docs/real-intake-operations.md` | Planned; backup-expiry SLA Gap |
| Data export / portability | No download/export route yet | — | Gap |
| Subprocessors | Render, Clerk, [object storage TBD] | `ferpa-dpa-template.md` Exhibit B | Planned |

## F. AI / machine learning

| Question area | Answer | Evidence | Status |
|---|---|---|---|
| Does the product use AI? | No AI in the hosted service; review is deterministic. Model flags locked `false` | `render.real-intake.yaml` | Implemented |
| Optional AI anywhere? | Local workbench only: user-configured BYOK connection; per-request manifest and "Allow once"; key in memory only | `local_reviewer.html`, `tina/intelligence.py` | Implemented (off by default) |
| Consent model for any future hosted AI | Explicit per-document/provider/purpose consent, revocable; consent table and audit actions exist | `service/real_intake/consent.py`, `docs/ai-architecture-byok.md` | Planned (disabled) |
| Training on customer data | Never | `ferpa-dpa-template.md` §4 | Implemented (policy) |
| Model can issue a compliance verdict? | No — prohibited by design | `docs/ai-architecture-byok.md` §31 | Implemented (policy) |

## G. Infrastructure and operations

| Question area | Answer | Evidence | Status |
|---|---|---|---|
| Hosting provider | Render (Professional plan workspace) | `docs/real-intake-provisioning-checkpoint.md` | Implemented (staging) |
| Network isolation | Protected, network-isolated environment; datastores `ipAllowList: []`; scanner is a private service | `render.real-intake.yaml` | Planned (Blueprint not applied) |
| Change management | Auto-deploy off; previews off; Blueprint Auto Sync off; maintenance mode on; `main`-only | `render.real-intake.yaml` | Planned |
| Monitoring / alerting | Health endpoint; no alerting configured | `service/real_intake/app.py` (`/healthz`) | Gap (alerting) |
| Vulnerability/patch management | Pinned images verified by digest; hourly signature updates for ClamAV | `deploy/clamav/Dockerfile`, `docs/real-intake-provisioning-checkpoint.md` | Planned; patch cadence policy Gap |
| End-to-end deployed verification | Positive/negative canary run required before first real document | `docs/real-intake-control-matrix.md` | Planned |

## H. Accessibility of the product

| Question area | Answer | Evidence | Status |
|---|---|---|---|
| ACR / VPAT | Draft WCAG 2.2 ACR based on code inspection | `accessibility-conformance-report.md` | Planned |
| AT testing | Not yet performed | — | Gap |
| Design contract tests | Skip links, reduced motion, 16px base, 14px floor, polite/assertive status regions | `tests/test_design_contract.py`, `tests/test_ui_debt.py` | Implemented |
