"""Networkless Clerk session verification and sole-owner authorization."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from service.real_intake.settings import RealIntakeSettings


MAX_TOKEN_BYTES = 16_384
REQUIRED_SESSION_CLAIMS = ("azp", "exp", "iat", "iss", "jti", "nbf", "sid", "sub", "v")


class AuthenticationFailure(Exception):
    """An authentication or owner authorization failure safe to map generically."""

    def __init__(self, code: str, status: int = 401) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class OwnerIdentity:
    clerk_user_id: str
    session_id: str
    token_id: str


TokenDecoder = Callable[[str, str, str], Mapping[str, Any]]


def _decode_clerk_session(token: str, public_key: str, issuer: str) -> Mapping[str, Any]:
    """Verify a Clerk v2 session token without a Clerk Backend API call."""
    try:
        import jwt
    except ImportError as error:  # Missing verifier dependency must fail closed.
        raise AuthenticationFailure("jwt_verifier_unavailable") from error

    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or header.get("typ") != "JWT":
            raise AuthenticationFailure("jwt_header_rejected")
        return jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=issuer,
            leeway=5,
            options={
                "require": list(REQUIRED_SESSION_CLAIMS),
                "verify_aud": False,
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "verify_nbf": True,
                "verify_signature": True,
            },
        )
    except AuthenticationFailure:
        raise
    except Exception as error:
        raise AuthenticationFailure("session_token_rejected") from error


class OwnerAuthenticator:
    def __init__(
        self,
        settings: RealIntakeSettings,
        decoder: TokenDecoder | None = None,
    ) -> None:
        self.settings = settings
        self.decoder = decoder or _decode_clerk_session

    @staticmethod
    def _bearer_token(environ: Mapping[str, Any]) -> str:
        value = str(environ.get("HTTP_AUTHORIZATION", ""))
        scheme, separator, token = value.partition(" ")
        if (
            separator != " "
            or scheme != "Bearer"
            or not token
            or token != token.strip()
            or any(character.isspace() for character in token)
            or len(token.encode("utf-8")) > MAX_TOKEN_BYTES
        ):
            raise AuthenticationFailure("bearer_token_required")
        return token

    def authenticate(self, environ: Mapping[str, Any]) -> OwnerIdentity:
        if not self.settings.clerk_auth_ready:
            raise AuthenticationFailure("clerk_auth_not_configured", status=503)
        token = self._bearer_token(environ)
        claims = self.decoder(
            token,
            self.settings.value("CLERK_JWT_KEY"),
            self.settings.value("CLERK_ISSUER"),
        )
        missing = [
            claim
            for claim in REQUIRED_SESSION_CLAIMS
            if (
                claim not in claims
                or claims.get(claim) is None
                or claims.get(claim) == ""
            )
        ]
        if missing:
            raise AuthenticationFailure("session_claims_missing")
        for claim in ("azp", "iss", "jti", "sid", "sub"):
            value = claims.get(claim)
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 512
                or value != value.strip()
                or any(ord(character) < 32 for character in value)
            ):
                raise AuthenticationFailure("session_claims_invalid")
        for claim in ("exp", "iat", "nbf"):
            value = claims.get(claim)
            if not isinstance(value, int) or isinstance(value, bool):
                raise AuthenticationFailure("session_claims_invalid")
        if claims.get("iss") != self.settings.value("CLERK_ISSUER"):
            raise AuthenticationFailure("session_issuer_rejected")
        # The azp claim is mandatory here even though Clerk permits it to be
        # absent in some privacy contexts. This private service requires the
        # configured browser origin on every accepted session.
        if claims.get("azp") != self.settings.value("CLERK_AUTHORIZED_PARTY"):
            raise AuthenticationFailure("session_authorized_party_rejected")
        if claims.get("v") != 2:
            raise AuthenticationFailure("session_version_rejected")
        if claims.get("sts") == "pending":
            raise AuthenticationFailure("session_tasks_incomplete")
        # This partition never permits actor-token impersonation or an active
        # Organization context. Either claim indicates a different identity
        # mode than the reviewed sole-owner personal session.
        if "act" in claims:
            raise AuthenticationFailure("impersonated_session_rejected")
        if "o" in claims:
            raise AuthenticationFailure("organization_session_rejected")
        owner_id = self.settings.value("HUB_OWNER_CLERK_USER_ID")
        if claims.get("sub") != owner_id:
            # Authorization is by immutable Clerk user ID, never an email claim.
            raise AuthenticationFailure("owner_identity_required", status=403)
        session_id = str(claims.get("sid"))
        token_id = str(claims.get("jti"))
        if (
            not session_id.startswith("sess_")
            or len(session_id) > 256
            or len(token_id) > 256
        ):
            raise AuthenticationFailure("session_identifiers_rejected")
        return OwnerIdentity(
            clerk_user_id=owner_id,
            session_id=session_id,
            token_id=token_id,
        )
