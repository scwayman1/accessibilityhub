# Clerk owner-only setup for controlled real-document intake

## Current state

As of July 30, 2026, the dedicated **Coastline Accessibility Hub** Clerk
application exists in Scott's Personal workspace and is still using its
development instance. Restricted mode is on, email is the only account
identifier, authenticator-app TOTP is on and required, and SMS/social/
enterprise/Organizations access is off. No invitation has been sent and no key
has been shared.

This checklist does not activate real-document intake. Development may use only
synthetic data. A Clerk production instance and the final HTTPS origin are
required before a real document can be considered.

## Safe dashboard configuration now

Complete these settings without creating a user or invitation:

1. Open **Restrictions**, enable **Restricted mode**, and save. Do not use an
   email allowlist as the application authorization control. Restricted mode
   prevents uninvited sign-up; the API's Clerk user-ID comparison remains the
   decisive authorization check.
2. Open **Multi-factor**, enable **Authenticator application (TOTP)** and backup
   codes, turn on **Require multi-factor authentication**, and save. Do not use
   SMS as the only second factor.
3. Under **User & authentication**, keep email address as the required account
   identifier. Disable phone, username, social connections, enterprise
   connections, Organizations, and other sign-in methods that this one-owner
   application does not need.
4. Do not add custom session-token claims or a JWT template. The backend uses
   Clerk's version 2 session token and its standard claims.
5. Keep the Users and Invitations lists empty until the infrastructure
   activation checklist is complete.

Clerk documents [Restricted mode](https://clerk.com/docs/guides/secure/restricting-access),
[required MFA](https://clerk.com/docs/guides/configure/auth-strategies/sign-up-sign-in-options),
and [invitations](https://clerk.com/docs/guides/users/inviting). An invitation
alone does not restrict an otherwise public application, which is why
Restricted mode comes first.

## Deferred institutional SSO

Microsoft 365 / Entra ID and Google are recorded future SSO providers, not part
of the controlled owner-only launch. Keep both disabled in Clerk.

That later institutional-access phase requires a separate threat model, tenant
and domain restrictions, identity-to-authorization mapping, role design,
deprovisioning and revocation behavior, audit changes, and positive/negative
tests. It may begin only after the Scott-only real-intake flow and every
storage, scanner, worker, audit, deletion, and incident control are complete
and verified. Enabling either provider must not replace immutable Clerk subject
authorization with an email or domain comparison.

## Production partition and exact origin

Do not use the development instance for real documents. The single approved
private frontend/API origin is:

`https://accessibility.coastlinecollegefoundation.com`

It is distinct from the public synthetic service and from Render preview URLs.
Once DNS and the separate Render service are ready:

1. Create the Clerk production instance for this same dedicated application.
2. Set its primary domain to the domain used by the private real-intake
   frontend. Complete Clerk's DNS and certificate verification.
3. Enable **Allowed Subdomains** and allow only the one subdomain needed by the
   real-intake frontend. Do not permit a wildcard and do not add the public
   synthetic service's origin.
4. Define the authorized party as exactly:

   `https://accessibility.coastlinecollegefoundation.com`

   It must contain the scheme and hostname, with no wildcard, user information,
   path, query, or fragment. The backend compares this value byte-for-byte with
   the session token's `azp` claim.
5. Keep the sign-in, sign-up, and post-authentication destination on that same
   HTTPS origin. Do not accept arbitrary `redirect_url` destinations. The Clerk
   Dashboard invitation flow uses Clerk's Account Portal and cannot set a custom
   redirect URL; no programmatic invitation is needed for this single owner.
6. Do not include localhost, preview deployments, the public synthetic service,
   or unrelated subdomains in production allowed origins or redirects.

Clerk recommends an explicit `authorizedParties` allowlist and a production
[subdomain allowlist](https://clerk.com/docs/guides/dashboard/dns-domains/subdomain-allowlist)
to reduce subdomain-cookie exposure. See Clerk's
[production deployment guidance](https://clerk.com/docs/guides/development/deployment/production).

## Code-side environment variables

Configure these only on the future separate Render real-intake service, never
on `accessibility-hub-staging`:

The private service build must install `requirements-real-intake.txt`. The
existing public synthetic service continues to install `requirements.txt` and
does not acquire the Clerk JWT dependency.

| Variable | Source and rule |
| --- | --- |
| `CLERK_PUBLISHABLE_KEY` | Production publishable key from the dedicated instance. Staging/production rejects a `pk_test_` key. |
| `CLERK_JWT_KEY` | PEM public key from **API keys → Show JWT public key → PEM Public Key**. Keep the multiline value in Render; do not paste it into chat or source control. |
| `CLERK_ISSUER` | Exact production Frontend API URL used as the JWT `iss` value. HTTPS only. |
| `CLERK_AUTHORIZED_PARTY` | Exactly `https://accessibility.coastlinecollegefoundation.com`; code rejects every alternative, including a trailing slash. |
| `HUB_OWNER_CLERK_USER_ID` | Clerk `user_…` ID captured only after Scott accepts the invitation. Never substitute the email address. |
| `HUB_REAL_DOCUMENT_INTAKE` | Set the literal `false` in the locked Blueprint. Unset is not valid for a deploy. A future reviewed active release may accept exact `true` only after every control passes. |
| `HUB_REAL_INTAKE_CONTROL_MANIFEST` | Leave unset until the reviewed manifest version is approved. Current code expects `2026-07-30.v1`. |
| `HUB_REAL_INTAKE_VERIFICATION_ID` | Reference to the completed positive/negative verification run, not a self-attestation entered in advance. |
| `HUB_BYOK_MODEL_ENABLED` | Leave unset or `false`. |
| `HUB_MODEL_EGRESS_ENABLED` | Leave unset or `false`. |

The service also requires private Postgres, queue, object-storage, scanner,
worker-isolation, audit, lifecycle, backup-deletion, and verification references.
Their exact variable names are enforced in
`service/real_intake/settings.py`. Merely populating them cannot activate the
service: live adapter evidence is separately required.

`CLERK_SECRET_KEY` is not required for request authentication. The code uses the
JWT public key for networkless verification, avoiding a per-request Clerk API
call and avoiding an unnecessary privileged backend credential.

## Server-side JWT verification contract

Every real-document request must pass the same backend authorization function:

1. Accept one `Authorization: Bearer <session-token>` header. Do not authorize
   from browser state, request parameters, or an email claim.
2. Require a JWT no larger than 16 KiB with header `alg=RS256` and `typ=JWT`.
3. Verify its signature using `CLERK_JWT_KEY`; allow only RS256.
4. Verify `exp`, `iat`, `nbf`, and the exact `CLERK_ISSUER`, with five seconds of
   clock skew.
5. Require Clerk v2 standard claims `azp`, `jti`, `sid`, `sub`, and `v`.
6. Require `azp` to equal `CLERK_AUTHORIZED_PARTY`. This implementation rejects
   a missing `azp` rather than using Clerk's optional skip behavior.
7. Reject a session with `sts=pending`, including an unfinished MFA task.
8. Reject any `act` actor/impersonation claim and any active `o` Organization
   claim. This launch accepts only Scott's direct personal session.
9. Require `sub` to equal `HUB_OWNER_CLERK_USER_ID`. A matching email claim with
   a different subject is rejected.
10. Attach the verified `sub` to each future document, job, deletion request, and
   audit event. Do not accept an actor ID from request input.

Clerk's [session-token reference](https://clerk.com/docs/guides/sessions/session-tokens)
defines these standard claims, and its
[manual verification guidance](https://clerk.com/docs/guides/sessions/manual-jwt-verification)
describes signature, time, and authorized-party checks.

## Invitation and immutable owner-ID binding

Do not perform these steps until private storage, ClamAV, isolated processing,
durable audit, deletion, backup treatment, and negative tests are ready:

1. Reconfirm Restricted mode and required MFA in the production instance.
2. Open **Invitations** and create exactly one invitation for
   `scott@coastlinecollegefoundation.com`. Do not share the invitation URL in
   chat or a ticket.
3. Scott accepts the invitation, completes account setup, enrolls TOTP, stores
   backup codes securely, signs out, and signs back in.
4. In **Users**, open Scott's verified user and copy its `user_…` ID directly
   into the Render secret `HUB_OWNER_CLERK_USER_ID`. Do not place the ID in
   client code, an email allowlist, logs, Linear, or chat.
5. Recheck that Users contains no unexpected identities and Invitations contains
   no other pending invitations.
6. Test the backend owner probe with Scott's session. Then run missing-token,
   altered-signature, wrong-issuer, wrong-`azp`, expired, not-yet-valid,
   pending-MFA, and different-subject tests. Return generic denial responses.

## Activation sequence

Activation is a two-person-style operational checkpoint even though Scott is
the sole application owner:

1. Deploy the separate real-intake service entrypoint with
   `HUB_REAL_DOCUMENT_INTAKE=false`. The existing public synthetic service and
   its `render.yaml` remain unchanged.
2. Configure the production Clerk values and private infrastructure secrets in
   Render. Confirm `/healthz` still reports
   `real_document_intake_enabled=false`.
3. After all non-auth controls pass, send and accept the single invitation and
   bind the resulting Clerk user ID.
4. Pass owner authentication, unauthorized-identity, malware, stale-scanner,
   oversized, malformed, no-egress worker, audit-recovery, deletion, backup,
   rate-limit, and credential-revocation tests.
5. Record the immutable verification-run ID and reviewed control-manifest
   version.
6. Prepare and review a separate active-release source and Blueprint change that
   implements the handlers, replaces the locked-only predeploy invariant, binds
   runtime evidence to the configured verification-run ID, and specifies the
   exact maintenance-mode transition. Changing the environment variable alone
   can never activate this foundation.
7. Only after that reviewed release is approved may it accept exact
   `HUB_REAL_DOCUMENT_INTAKE=true`; runtime evidence must still pass before
   maintenance mode is disabled.
8. Upload one non-sensitive canary PDF first. Stop immediately if any audit,
   scan, lifecycle, or deletion evidence is incomplete.

The current foundation intentionally has no upload, process, download, or
delete route, so it cannot be activated yet even with configuration present.

## Emergency revocation

If identity, origin, or credentials may be compromised:

1. Set the literal `HUB_REAL_DOCUMENT_INTAKE=false` and redeploy first. Do not
   remove it; the locked deploy check intentionally rejects an unset value.
2. Revoke Scott's Clerk sessions. Ban the user temporarily if the account itself
   may be compromised.
3. Rotate affected Render and storage credentials; revoke queue, database, and
   scanner access as appropriate.
4. Preserve protected audit evidence, record the incident, and verify that no
   queued work can continue.
5. Re-enable only after new positive and negative verification evidence exists.
