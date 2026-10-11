"""Single sign-on: the placeholder the Coastline pilot shows until Entra is connected.

For the pilot, sign-in stays the shared access code ("headless"): nothing here
contacts a directory, and there is no SSO route in hosted environments. With
``HUB_SSO_PROVIDER=entra`` the hosted sign-in page shows where "Sign in with
your Coastline Microsoft account" will live, as a disabled control with a
plain note, so the demo shows the intended path without pretending it works.

Connecting Microsoft Entra ID later (OIDC authorization-code flow with PKCE):

1. Coastline IT registers the app (single tenant) and supplies the tenant ID,
   client ID, and the redirect URI ``https://<host>/login/sso/callback``.
2. Add ``GET /login/sso`` (redirect to the tenant's v2.0 authorize endpoint
   with state, nonce, and PKCE challenge) and ``GET /login/sso/callback``
   (exchange the code, validate the ID token's issuer, audience, nonce, and
   signature against the tenant's JWKS, map ``oid`` to the session actor).
3. Keep the existing session cookie, server-side revocation, and rate limits;
   decide deprovisioning (session lifetime vs. Entra sign-out) with IT.
The locked real-intake foundation (``service/real_intake/auth.py``) already
validates Clerk-issued JWTs and is the other route to the same outcome.
"""
from __future__ import annotations

from html import escape

SSO_PROVIDERS = {
    "entra": "Sign in with your Coastline Microsoft account",
}


def normalize_provider(value: str | None) -> str:
    provider = (value or "").strip().lower()
    return provider if provider in SSO_PROVIDERS else ""


def placeholder_html(provider: str) -> str:
    """A visible, disabled sign-in control and an honest note; empty when no provider is set."""
    label = SSO_PROVIDERS.get(provider)
    if not label:
        return ""
    return (
        f'<div class=actions><button type=button class=secondary disabled aria-describedby=sso-note>{escape(label)}</button></div>'
        '<p class=sso-caption id=sso-note>Microsoft sign-in is being connected with Coastline IT. '
        "Until then, use the access code below.</p>"
        '<div class=login-divider aria-hidden=true>or</div>'
    )
