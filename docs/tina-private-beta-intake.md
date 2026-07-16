# Tina private PDF assessment beta

## Purpose and claim boundary

This is a **private, invite-only, PDF-only** assessment beta. It produces
technical evidence and review routing; it does not issue an accessibility,
WCAG, PDF/UA, Section 508, legal, or publication-readiness determination.

The current loopback reviewer is a local spike. It must not be exposed as a
public upload endpoint or used for real documents outside the controls below.

## Smallest deployable vertical slice

```text
Invited user
  → authenticated session
  → one-time upload session
  → private quarantine object
  → malware/type gate
  → isolated deterministic PDF worker
  → normalized evidence/finding report
  → authenticated status/report view
  → owner-initiated deletion
```

## Proposed beta stack (assumption, not deployed infrastructure)

| Concern | Proposed service | Beta constraint |
|---|---|---|
| Identity | Cognito invite-only user pool | MFA for staff/admin roles; fail closed |
| API/web | FastAPI service on ECS Fargate | No parser runs in web request process |
| Object storage | Private S3 bucket + KMS | Block public access; quarantine/evidence prefixes |
| State | PostgreSQL/RDS | Tenant and object ownership enforced in every query |
| Queue | SQS | At-least-once safe jobs with idempotency key |
| Workers | Separate Fargate tasks | No internet egress; non-root; CPU/memory/time limits |
| Malware | Dedicated scanner task | Assessment worker cannot read before clean verdict |
| Audit | CloudWatch/CloudTrail + append-only audit table | No document bytes or extracted instructional text in logs |

AWS is a practical implementation recommendation, not provisioned infrastructure.
The named-user beta assumes US regional processing; data residency, contractual,
or institution-specific requirements must be confirmed before provisioning.

## Required upload lifecycle

1. API authorizes an invite-only user and creates a `document_version` row with
   tenant/owner, size ceiling, expected MIME type, upload expiry, and idempotency key.
2. Browser uploads only to a short-lived signed URL under `quarantine/`.
3. Quarantine worker verifies signature, MIME, hash, archive/stream/page limits,
   and scans for malware. It records a verdict without logging file contents.
4. Only a clean PDF moves to an immutable private assessment object key.
5. Worker runs qpdf, pypdf, and exact pinned veraPDF in an isolated job with no
   network. Every tool execution records version, duration, outcome, and evidence ID.
6. Findings are persisted as Tina rule/evidence objects. Browser shows only
   normalized fields and the claim boundary.
7. Owner can delete the document. A deletion job removes original, derivative,
   and evidence objects, records completion, and verifies deletion state.

## Minimal data records

```text
Tenant(id, name)
User(id, tenant_id, role)
Document(id, tenant_id, owner_id, source_hash, state)
DocumentVersion(id, document_id, storage_key, bytes, detected_mime, state)
Assessment(id, document_version_id, state, idempotency_key, toolchain_version)
ToolExecution(id, assessment_id, tool, version, outcome, duration_ms)
Evidence(id, assessment_id, tool_execution_id, type, safe_value)
Finding(id, assessment_id, rule_id, rule_version, outcome, severity, evidence_ids)
AuditEvent(id, tenant_id, actor_id, action, subject_type, subject_id, created_at)
DeletionRequest(id, document_id, state, verified_at)
```

## Assessment states

```text
UPLOAD_AUTHORIZED
→ QUARANTINED
→ MALWARE_SCAN_PENDING
→ REJECTED | CLEAN
→ ASSESSMENT_QUEUED
→ ASSESSING
→ REPORT_READY | ASSESSMENT_FAILED | UNSUPPORTED
→ DELETION_PENDING
→ DELETED
```

All transitions must be idempotent, auditable, and authorization-checked.

## Non-negotiable deployment gates

No actual institutional/student/faculty PDF is accepted until each blocker has
implementation evidence and a negative-path test:

- [ ] Invite-only authentication and tenant/owner authorization
- [ ] No public buckets, public report URLs, or direct worker URLs
- [ ] Signed-upload expiry, content length, MIME/signature, page, and archive limits
- [ ] Quarantine + malware verdict before parser access
- [ ] Isolated parser/renderer worker with egress blocked and resource limits
- [ ] Pinned tool image/version policy; no runtime image pull
- [ ] KMS encryption at rest and TLS in transit
- [ ] Per-tenant object/key separation and query-level authorization tests
- [ ] Evidence/finding/tool-version provenance and immutable audit records
- [ ] Retention defaults, owner deletion, deletion verification, and backup policy
- [ ] No document content, OCR text, prompts, or signed URLs in logs/telemetry
- [ ] Incident response owner, abuse/rate limits, and alerting
- [ ] Real upload → assessment → report → deletion end-to-end test

## Deliberately deferred

- AI or external model processing
- Automatic repairs or document mutation
- DOCX/PPTX/XLSX/EPUB/media formats
- Public/self-service registration
- Multi-institution administration
- Conformance/certification reports

## First implementation ticket

Build an authenticated API with a **fake storage adapter** and durable PostgreSQL
state locally first. It must demonstrate:

```text
authorized user → document row → signed-upload contract → queued assessment
→ worker state update → normalized report → owner-only deletion
```

The real S3/SQS/Fargate adapters are introduced only after this contract has
integration tests and the cloud account/security boundary is available.
