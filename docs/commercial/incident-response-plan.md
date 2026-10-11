**DRAFT — prepared for counsel review. Not legal advice. Not yet adopted.**

# Incident Response Plan — Coastline Accessibility Hub (draft)

Builds on the technical runbook in `docs/real-intake-operations.md` (Incident response section) and `docs/clerk-owner-only-setup.md` (Emergency revocation). Those documents govern technical steps; this plan adds roles, severity, communications, and exercise requirements for an institutional pilot.

## 1. Scope

Any actual or suspected: unauthorized access to Institution Data; compromise of identity (Clerk), origin/DNS, source code, Render, object storage, database, queue, scanner, worker, or audit sink; malware that passes the scan gate; data loss or failed deletion; unintended data egress (including to any model provider or sponsor); and availability outages affecting the pilot.

## 2. Roles

| Role | Responsibility | Assignee |
|---|---|---|
| Incident Commander (IC) | Declares incident and severity, directs response, owns timeline | [NAME] — currently the sole operator (`docs/real-intake-operations.md`) |
| Technical Lead | Containment, forensics preservation, credential rotation, recovery | [NAME] — currently the same person as IC |
| Backup / second responder | Covers IC when unavailable; two-person check on re-enable | [NAME — REQUIRED BEFORE PILOT] |
| Communications Lead | Drafts notices to Institution; coordinates with counsel | [NAME] |
| Legal counsel | Notification obligations, privilege, regulator contact | [COUNSEL NAME / FIRM] |
| Institution Security Contact | Receives notices; coordinates campus response and any notice to individuals | [COASTLINE COLLEGE / DISTRICT ISO NAME, EMAIL, PHONE] |
| Institution Privacy / FERPA Officer | Determines education-record impact and notice to students | [NAME] |
| Subprocessor contacts | Render, Clerk, [object storage] support/security channels | [CONTACTS] |

> Single-operator risk: today one person holds every role. A named backup with documented, least-privilege emergency access is an open item before pilot start.

## 3. Severity levels

| Level | Definition (examples) | Response start | Institution notice |
|---|---|---|---|
| **SEV-1 Critical** | Confirmed unauthorized access to or disclosure of Institution Data; credential compromise with data access; malware executed in a processing component; data sent to an unapproved destination | Immediately; intake disabled within [1] hour | Initial notice ≤ **[24–72] hours** after confirmation [COUNSEL] |
| **SEV-2 High** | Suspected access not yet confirmed; control failure that could expose data (e.g., RLS or authorization defect, public endpoint discovered, audit sink unavailable); failed or partial deletion | Within [4] hours | Within [72] hours or upon confirmation as SEV-1 |
| **SEV-3 Moderate** | Security control degraded without evidence of exposure (stale ClamAV signatures causing fail-closed denials, rate-limit store outage, dependency CVE affecting service) | Within [1] business day | In next scheduled report, or within [5] business days if pilot affected |
| **SEV-4 Low** | Availability issue or minor bug, no data risk | Normal support | Status update as agreed in SOW |

## 4. Response phases

| Phase | Actions (technical detail in `docs/real-intake-operations.md`) |
|---|---|
| 1. Detect and declare | Log time of detection, reporter, initial facts. IC assigns severity. Open a private incident record. |
| 2. Contain | Set literal `HUB_REAL_DOCUMENT_INTAKE=false` and redeploy (never unset); confirm `/healthz` reports `real_document_intake_enabled=false`. Revoke Clerk sessions; ban affected users if needed. Stop queued processing; revoke worker/queue credentials. Disable any model egress (already off). |
| 3. Preserve evidence | Preserve append-only audit records and audit-sink data. Do not delete or rewrite evidence. Inventory objects without downloading contents to an operator device. Snapshot relevant Render logs. |
| 4. Eradicate | Rotate affected storage, database, queue, Render, and Clerk credentials; JWT key/issuer change requires full auth regression. Patch root cause through reviewed PR. |
| 5. Recover | Restore only into an isolated target; re-apply verified deletion tombstones; prove absence; run complete positive/negative activation suite; two-person check; re-enable. |
| 6. Notify | Per §5. |
| 7. Post-incident review | Written root-cause analysis within [15] business days; record scope, times, affected document IDs, credentials revoked, deletion results, backup-expiry expectations, verification-run ID; track corrective actions. |

## 5. Notification commitments [ALL TIMELINES FOR COUNSEL]

| Audience | Trigger | Draft timeline | Content |
|---|---|---|---|
| Institution Security Contact | SEV-1 confirmed | Without unreasonable delay, ≤ **[72] hours** after confirmation (target: initial call within [24] hours) | What happened, data categories, approximate records/users, discovery time, containment, next update time |
| Institution Security Contact | SEV-2 | ≤ [72] hours | Same, marked "suspected" |
| Institution (updates) | SEV-1/2 open | Every [48] hours | Progress, revised scope |
| Institution (final report) | Closure | ≤ [15] business days | Root cause, corrective actions, deletion/restore status |
| Affected individuals | As Institution determines | Per Cal. Civ. Code §1798.82 and Institution policy | Institution-led; Provider supports |
| Law enforcement / regulators | As counsel advises | — | Counsel-led |

Notices must never include document content, signed URLs, or credentials.

## 6. Contact sheet [FILL BEFORE PILOT]

| Party | Primary | Backup | Channel |
|---|---|---|---|
| Provider IC | [NAME, PHONE] | [NAME, PHONE] | [EMAIL / SIGNAL / PHONE] |
| Institution ISO | [NAME] | [NAME] | [ ] |
| Render support | [PLAN SUPPORT CHANNEL] | | |
| Clerk support | [ ] | | |
| Object storage provider | [ ] | | |
| Counsel | [ ] | | |

## 7. Tabletop exercise checklist (required before pilot; then each semester)

Status today: runbook complete; **exercise not performed** (`docs/real-intake-control-matrix.md`, Incident response row).

| # | Item | Done |
|---|---|---|
| 1 | Participants named: IC, backup, Institution ISO, counsel (optional) | [ ] |
| 2 | Contact sheet verified by test call/email to each party | [ ] |
| 3 | Scenario A — stolen faculty session: revoke Clerk sessions, confirm denial, review audit for `document_viewed`/`document_downloaded` by that subject | [ ] |
| 4 | Scenario B — scanner outage/stale signatures: confirm uploads fail closed and users see a plain message | [ ] |
| 5 | Scenario C — cross-owner data exposure bug: disable intake, preserve audit, scope affected IDs, draft Institution notice within the timeline | [ ] |
| 6 | Scenario D — operator laptop/credential compromise: rotate Render, storage, database, queue, Clerk credentials; confirm old credentials fail | [ ] |
| 7 | Scenario E — deletion request fails partway: confirm `failed` state, retry, absence proof, tombstone | [ ] |
| 8 | Scenario F — restore after deletion: isolated restore, tombstone re-application, absence proof | [ ] |
| 9 | Kill-switch drill: set `HUB_REAL_DOCUMENT_INTAKE=false`, redeploy, verify `/healthz`, time it | [ ] |
| 10 | Notice drafted from template and reviewed by counsel | [ ] |
| 11 | Lessons learned recorded; corrective actions assigned with dates | [ ] |
| 12 | Exercise date, attendees, and outcomes recorded in `docs/real-intake-control-matrix.md` evidence | [ ] |

## 8. Plan maintenance

Review after every SEV-1/2 incident, every tabletop, any subprocessor change, and at least [annually]. Owner: [NAME].
