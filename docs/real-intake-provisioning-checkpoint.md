# Private real-intake provisioning checkpoint

This checkpoint records the infrastructure definition that is safe to prepare
before any real-document handler, Clerk production identity, invitation,
secret, storage credential, or activation exists.

## Render account inventory

On July 30, 2026, the authenticated **Coastline College Foundation** Render
workspace was confirmed to use the Professional plan. The existing
**Coastline Accessibility Hub** project contains the public synthetic service.
It is not a target for this provisioning change.

The separate `render.real-intake.yaml` Blueprint creates a distinct
**Coastline Accessibility Hub Private Real Intake** project and a protected,
private-network-isolated **Locked Production** environment. Blueprint
previews and service automatic deploys are off. Render's Blueprint **Auto
Sync** setting is dashboard-managed, not a YAML field; set it to **No**
immediately when the Blueprint is created and verify it before any later
source update.

Applying the Blueprint is intentionally paused because it creates billable
resources. Render bills paid instances and storage by usage, and neither
private services nor background workers support free instances.

## Planned locked topology

| Resource | Plan | Locked behavior |
| --- | --- | --- |
| Real-intake web/API | Starter web service | Maintenance mode on; only the final custom domain; Render subdomain disabled; no real-document handlers |
| Assessment worker | Starter background worker | Dormant process only; no queue, storage, parser, model, or network calls; never eligible for documents until infrastructure-enforced outbound denial exists |
| ClamAV | Pro private service (4 GiB) | No public URL; pinned official 1.4.5 image; 25 MiB stream/file limit; persistent signature disk; FreshClam hourly |
| Queue/rate store | Starter Key Value | No external IPs; `noeviction`; journal + snapshot persistence |
| Metadata | Basic-1gb PostgreSQL 18 | No external IPs; fixed 15 GB disk; private connection only |
| Audit sink | Basic-256mb PostgreSQL 18 | Separate credentials and datastore; no external IPs; content-free append-only schema still required before use |

The environment uses Oregon for every component and enables Render environment
network isolation and destructive-action protection. The scanner receives no
Clerk, object-storage, database, queue, or audit credential.

Render's environment isolation blocks private traffic from crossing the
environment boundary. It does **not** block a service from reaching the public
internet. Consequently, it is not evidence for the required no-egress
assessment worker. The Blueprint can safely create only the dormant worker:
its entrypoint imports no queue, storage, parser, database, model, HTTP, or
socket client and receives no document-processing capability. Real work stays
blocked until a separately reviewed control can prove outbound denial while
still allowing only the required private dependencies. An environment flag or
application convention is not sufficient evidence.

## Object storage checkpoint

Render does not provide the required private object store. A provider and
account must be selected separately. Before credentials can be entered in
Render, the store must prove:

- private access only and public-access blocks;
- encryption at rest and TLS in transit;
- one exact bucket with owner/document-scoped `quarantine/`, `clean/`,
  `derivative/`, and `evidence/` prefixes;
- least-privilege API and worker credentials with no public-ACL permission;
- documented versioning, recovery, manual live deletion, and maximum backup
  expiry delay;
- an exercised delete-and-absence verification using non-sensitive data.

The Blueprint contains only `sync: false` names for these values. It contains no
credential or endpoint value.

## DNS and TLS checkpoint

The Blueprint defines only:

`accessibility.coastlinecollegefoundation.com`

Render's default subdomain is disabled and application code independently
requires that exact HTTPS host. Domain creation, DNS changes, verification, and
certificate issuance wait until the web service exists and DNS authority is
available. No preview or synthetic-service hostname is allowed.

## Deployment gates

Every API and worker deploy runs:

`python -m service.real_intake.deploy_check`

The check fails unless production, model, origin, manifest, missing-handler,
health, and public-service separation invariants remain locked. The only
accepted activation value at this stage is the literal `false`.

The next live sequence, after explicit billing approval and source publication,
is:

1. Create the Blueprint from the custom path `render.real-intake.yaml`, set
   Blueprint Auto Sync to No, and verify the protected isolated environment.
2. Deploy the locked web/API and dormant worker with no Clerk or storage values.
3. Create the private databases, Key Value instance, and private ClamAV service.
4. Confirm no public scanner/datastore endpoints and record the pinned scanner
   digest and signature freshness.
5. Select and provision private encrypted object storage.
6. Configure DNS/TLS and then disable the Render subdomain.
7. Provision Clerk production and bind the accepted owner user ID only after
   all other controls pass.
8. Keep real-document handlers absent and intake false until deployed
   positive/negative verification is complete.

## Local validation evidence

On July 30, 2026:

- the Blueprint passed Render's current official JSON schema;
- all 308 repository tests passed;
- the digest-pinned Linux/amd64 scanner image built locally;
- the built image reported ClamAV 1.4.5 and its effective configuration showed
  `StreamMaxLength 25M`, `MaxFileSize 25M`, `MaxScanSize 250M`, and
  `ConcurrentDatabaseReload no`.

These checks validate source and configuration only. They do not satisfy any
live-control row in the verification matrix.
