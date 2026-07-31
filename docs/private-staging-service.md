# Synthetic staging service boundary

`service/` is the deployable public demo for Accessibility Hub. It is intentionally limited to server-generated sample documents while the separate private real-intake controls remain incomplete and locked.

## Product shell

The private service uses the unmodified official white Coastline College horizontal logo at `assets/coastline-college-logo-white.png`, sourced from Coastline's live header asset: `https://www.coastline.edu/_files/img/new-navigation-images/coastlinecollege_whitetext_800x240.png`. It is used only on the deep institutional-navy shell. The application does not create or recolor a Coastline mark, and it does not use GradRoots assets.

The workspace uses a persistent Coastline navy `#003764` workflow rail, a cool-white canvas, pure-white work surfaces, and restrained cyan interaction states. It deliberately avoids beige surfaces and gradient-heavy presentation.

## What runs locally now

With the hosted synthetic opt-in and its required session configuration, the service provides:

1. an authenticated browser session;
2. a tenant-scoped synthetic document record persisted in SQLite;
3. a persisted queued assessment job processed by the in-process staging worker;
4. deterministic evidence from `check_pdf.py`, translated into **Needs attention**, **Review recommended**, **Verified signal**, and **Not assessed** lanes;
5. persisted remediation provenance and a fresh queued recheck after a metadata repair or a human-confirmed tag-tree/reading-order repair;
6. an append-only local audit record that identifies the staging actor and action, without storing a user-supplied document.

The service calls the existing remediation implementations rather than duplicating them:

- `tina.remedy.MetadataRemediation` for title and primary-language copies;
- `tina.structure.StructureRemediation` for human-confirmed roles and reading order, including its page/text preservation verification.
- `tina.ocr.OcrRemediation` for the bundled scanned handout, after an educator confirms they will review the generated text layer against the page image.

Advanced structure/OCR controls remain secondary to the guided title-and-language demo. The service does not expose a general upload or AI route; it keeps those surfaces closed until their worker, storage, identity, and audit controls are independently deployed.

## Protected boundary

There is no PDF upload endpoint. The only create-document route generates the built-in fixture in `service/fixtures.py`.

In `HUB_ENV=development`, the synthetic fixture may be stored in a local service data directory so the complete vertical slice can be exercised.

In `HUB_ENV=staging`, synthetic intake is closed by default. The only exception is the explicit `HUB_ALLOW_HOSTED_SYNTHETIC=true` opt-in described in [Hosted synthetic testing](#hosted-synthetic-testing-explicit-opt-in), which re-opens the bundled-fixture route only — nothing else. For any real or user-supplied document, the following references define the required hosted boundary before an adapter implementation can be enabled:

| Required control reference | Intended enforcement point |
|---|---|
| `HUB_PRIVATE_OBJECT_STORAGE` | Tenant-private object store; no browser-accessible document URL. |
| `HUB_MALWARE_SCAN_GATE` | Quarantine and malware scan before parser/worker release. |
| `HUB_WORKER_ISOLATION_ATTESTATION` | Separate worker with enforced no-egress and resource limits. |
| `HUB_TENANT_AUTH_ISSUER` | Institutional identity and tenant authorization. |
| `HUB_LIFECYCLE_POLICY_ID` | Retention, deletion, and recovery policy. |
| `HUB_AUDIT_SINK` | Immutable audit destination and operational review. |

Setting a name is not an integration. This repository has no object-store, scanner, identity-provider, isolated-worker, or audit-sink adapter yet. The staging web process therefore stays available for `/healthz` and login setup but refuses to create a document record in hosted mode unless the owner sets the explicit synthetic opt-in flag below — and even with that flag set, the only documents it will ever create are the two bundled synthetic fixtures. Real-document intake stays refused until the controls are implemented and independently validated.

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

## Hosted synthetic testing (explicit opt-in)

`HUB_ALLOW_HOSTED_SYNTHETIC` is an environment variable and it is off by default. When `HUB_ENV=staging` **and** the value is exactly `true` (lowercase; `1`, `TRUE`, or `yes` do not count), the hosted web service allows the same bundled-synthetic-fixture intake that already runs in development:

- optionally access-code gated when `HUB_PUBLIC_ACCESS` is unset; the checked-in public demo Blueprint sets it to exact `true`, exposing only this synthetic fixture experience;
- still tenant-scoped — records live under the single staging tenant;
- still audit-recorded — every create, remediation, and delete writes an append-only audit event;
- still limited to the two fixtures generated in `service/fixtures.py`. The intake route accepts a fixture name, not a file.

### What this flag deliberately does NOT open

- **No upload endpoint exists.** There is no route that accepts PDF bytes from a browser, with or without this flag.
- **Real-document intake stays refused.** The six control references in the table above (private object storage, malware scan gate, worker isolation, tenant auth issuer, lifecycle policy, audit sink) remain the required — and currently unimplemented — boundary for any non-fixture document.
- **No AI route is enabled.**
- `/healthz` continues to report `"hosted_intake_enabled": false`; the flag's own state is reported as `"hosted_synthetic_optin"`.
- Signals remain per-detail evidence, not an overall result. Nothing this service shows is a conformance or certification determination, in any environment.
- Render's default filesystem is ephemeral: synthetic records and their assessment history do not survive a deploy or restart. That is acceptable here precisely because only disposable synthetic fixtures exist.

### Render runbook for the owner

1. Sign in at `https://dashboard.render.com`.
2. Click **New** → **Blueprint**. Connect the GitHub account/repository if prompted, then select this repository. Render reads `render.yaml` and shows one web service, `accessibility-hub-staging`. It creates no database, disk, or other resource.
3. Before clicking **Apply**, Render asks for the `sync: false` environment variables. Set exactly three; leave the six control-reference variables empty (they are placeholders for future integrations, and filling them enables nothing):
   - `HUB_STAGING_ACCESS_CODE` — a long random code you will type at `/login`. Treat it as a secret.
   - `HUB_SESSION_SECRET` — at least 32 characters of random material (e.g. output of `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`). Login stays closed if it is shorter.
   - `HUB_ALLOW_HOSTED_SYNTHETIC` — the exact value `true`.
4. Click **Apply** and wait for the first deploy to finish (service status **Live**).
5. Open `https://<your-service>.onrender.com/healthz`. Confirm the JSON shows `"environment": "staging"`, `"login_ready": true`, `"hosted_synthetic_optin": true`, and — still — `"hosted_intake_enabled": false`.
6. Open `https://<your-service>.onrender.com/`. With the checked-in `HUB_PUBLIC_ACCESS=true` value, no access code is requested; this does not expose any upload or real-intake route.
7. **Choose sample:** click **Start a sample review**. You land on a progress page that checks again every five seconds while the queued assessment runs.
8. **Review findings:** expect **Needs attention** on the document title and language, alongside **Review recommended**, **Verified signal**, and collapsed specialist-review checks. Each signal stands alone; there is no overall score.
9. **Improve:** use **Fix the clearest issues**, keep or edit the suggested values, and click **Apply and recheck**. You are redirected to a new rechecked sample version.
10. **Check again:** the completion banner reports the two newly verified signals, while the original sample remains unchanged. The provenance panel records the repair; the document is not given an overall status.
11. Optionally repeat with **Review a scanned handout** for the OCR path, and use **Remove this synthetic record** to clean up.
12. When testing is done, either delete the service or clear `HUB_ALLOW_HOSTED_SYNTHETIC` in the dashboard (the service restarts and hosted document creation closes again).

## Render configuration

`render.yaml` declares a separate `accessibility-hub-staging` **web service**. It does not modify the existing static site and it does not provision a service, disk, database, object store, scanner, or identity provider.

The web process uses `/healthz` as a liveness endpoint. Hosted document intake will remain closed until the required control references above have working integrations.

### Exact next control-plane step before a functional hosted intake

A Coastline-authorized Render administrator must create the `accessibility-hub-staging` web service from this repository/Blueprint and provide dashboard-managed secrets for the access/session values. Before enabling any document route, the administrator must also approve and provision: a tenant-private object-store bucket with deletion policy, a malware/quarantine scanner, an isolated no-egress worker runtime, an institutional identity integration, an audit sink, and a persistence choice. Those resources may incur provider charges and require Coastline cloud, security, identity, and data-lifecycle permissions; no current cost or approval has been asserted here.
