# Private staging service boundary

`service/` is the first deployable control plane for Accessibility Hub. It is separate from the public static landing and walkthrough. The service is intentionally limited to its bundled synthetic course handout while the Coastline data and infrastructure decisions are incomplete.

## What runs locally now

With an explicit staging access code and session secret, the service provides:

1. an authenticated browser session;
2. a tenant-scoped synthetic document record persisted in SQLite;
3. a persisted queued assessment job processed by the in-process staging worker;
4. deterministic evidence from `check_pdf.py`, translated into **Needs attention**, **Review recommended**, **Verified signal**, and **Not assessed** lanes;
5. persisted remediation provenance and a fresh queued recheck after a metadata repair or a human-confirmed tag-tree/reading-order repair;
6. an append-only local audit record that identifies the staging actor and action, without storing a user-supplied document.

The service calls the existing remediation implementations rather than duplicating them:

- `tina.remedy.MetadataRemediation` for title and primary-language copies;
- `tina.structure.StructureRemediation` for human-confirmed roles and reading order, including its page/text preservation verification.

The established local Fix Lab still owns the current semantic-description and OCR user interactions. The service does not expose a general upload, OCR, or AI route in this staging slice; it keeps that surface closed until its worker and storage controls are independently deployed.

## Protected boundary

There is no PDF upload endpoint. The only create-document route generates the built-in fixture in `service/fixtures.py`.

In `HUB_ENV=development`, the synthetic fixture may be stored in a local service data directory so the complete vertical slice can be exercised.

In `HUB_ENV=staging`, synthetic intake is closed. The following references define the required hosted boundary before an adapter implementation can be enabled:

| Required control reference | Intended enforcement point |
|---|---|
| `HUB_PRIVATE_OBJECT_STORAGE` | Tenant-private object store; no browser-accessible document URL. |
| `HUB_MALWARE_SCAN_GATE` | Quarantine and malware scan before parser/worker release. |
| `HUB_WORKER_ISOLATION_ATTESTATION` | Separate worker with enforced no-egress and resource limits. |
| `HUB_TENANT_AUTH_ISSUER` | Institutional identity and tenant authorization. |
| `HUB_LIFECYCLE_POLICY_ID` | Retention, deletion, and recovery policy. |
| `HUB_AUDIT_SINK` | Immutable audit destination and operational review. |

Setting a name is not an integration. This repository has no object-store, scanner, identity-provider, isolated-worker, or audit-sink adapter yet. The staging web process therefore stays available for `/healthz` and login setup but always refuses to create a document record in hosted mode until the controls are implemented and independently validated.

## Claim boundaries

- A deterministic signal is evidence about a particular artifact detail, not an overall result.
- AI output is not enabled in this service. Any future suggestion must remain attributable, editable, and human-approved before a mutation.
- Human-confirmed structure and OCR-derived text are recorded with their own provenance. They are not certifications or conformance determinations.
- Contrast, tables, forms, and other unsupported checks appear as **Not assessed** instead of being inferred.

## Local run

```sh
export HUB_ENV=development
export HUB_STAGING_ACCESS_CODE='choose-a-local-code'
export HUB_SESSION_SECRET='at-least-32-characters-of-local-secret-material'
export HUB_DATA_DIR="$PWD/.hub-staging"
python3.11 -m service
```

Open `http://127.0.0.1:8787/login`. Use only the bundled synthetic fixture.

## Render configuration

`render.yaml` declares a separate `accessibility-hub-staging` **web service**. It does not modify the existing static site and it does not provision a service, disk, database, object store, scanner, or identity provider.

The web process uses `/healthz` as a liveness endpoint. Hosted document intake will remain closed until the required control references above have working integrations.

### Exact next control-plane step before a functional hosted intake

A Coastline-authorized Render administrator must create the `accessibility-hub-staging` web service from this repository/Blueprint and provide dashboard-managed secrets for the access/session values. Before enabling any document route, the administrator must also approve and provision: a tenant-private object-store bucket with deletion policy, a malware/quarantine scanner, an isolated no-egress worker runtime, an institutional identity integration, an audit sink, and a persistence choice. Those resources may incur provider charges and require Coastline cloud, security, identity, and data-lifecycle permissions; no current cost or approval has been asserted here.
