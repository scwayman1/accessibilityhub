"""Inert WSGI control plane for pre-activation real-intake verification."""
from __future__ import annotations

import json
from typing import Any, Callable

from service.real_intake.auth import AuthenticationFailure, OwnerAuthenticator
from service.real_intake.settings import (
    APPROVED_AUTHORIZED_PARTY,
    RealIntakeSettings,
    RuntimeControlEvidence,
)


def _json_response(
    start_response: Callable,
    status: str,
    payload: dict[str, object],
) -> list[bytes]:
    body = json.dumps(payload, sort_keys=True).encode()
    start_response(
        status,
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
            ("Cross-Origin-Opener-Policy", "same-origin"),
            ("Cross-Origin-Resource-Policy", "same-origin"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
            ("Referrer-Policy", "no-referrer"),
            ("Strict-Transport-Security", "max-age=31536000"),
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("X-Permitted-Cross-Domain-Policies", "none"),
        ],
    )
    return [body]


def _approved_request_target(environ: dict[str, Any]) -> bool:
    approved_host = APPROVED_AUTHORIZED_PARTY.removeprefix("https://")
    forwarded_proto = str(environ.get("HTTP_X_FORWARDED_PROTO", "")).split(",", 1)[0]
    return (
        environ.get("HTTP_HOST") == approved_host
        and forwarded_proto.strip() == "https"
    )


def create_app(
    settings: RealIntakeSettings | None = None,
    runtime_evidence: RuntimeControlEvidence | None = None,
    authenticator: OwnerAuthenticator | None = None,
):
    settings = settings or RealIntakeSettings.from_environ()
    # No production entrypoint supplies evidence yet. The default is therefore
    # an all-false attestation, even if every environment variable is populated.
    evidence = runtime_evidence or RuntimeControlEvidence()
    authenticator = authenticator or OwnerAuthenticator(settings)

    def app(environ: dict[str, Any], start_response: Callable):
        path = environ.get("PATH_INFO", "/")
        method = environ.get("REQUEST_METHOD", "GET")
        if path == "/healthz" and method == "GET":
            return _json_response(
                start_response, "200 OK", settings.health_payload(evidence)
            )
        if (
            path == "/owner/session"
            or path.startswith("/api/real-documents")
            or path.startswith("/api/upload-authorizations")
        ) and not _approved_request_target(environ):
            return _json_response(
                start_response, "404 Not Found", {"error": "not_found"}
            )
        if path == "/owner/session" and method == "GET":
            try:
                identity = authenticator.authenticate(environ)
            except AuthenticationFailure as error:
                status = (
                    "503 Service Unavailable"
                    if error.status == 503
                    else "403 Forbidden"
                    if error.status == 403
                    else "401 Unauthorized"
                )
                return _json_response(
                    start_response, status, {"error": "access_denied"}
                )
            return _json_response(
                start_response,
                "200 OK",
                {
                    "authenticated": True,
                    "owner": True,
                    "clerk_user_id": identity.clerk_user_id,
                },
            )
        if path.startswith("/api/real-documents") or path.startswith(
            "/api/upload-authorizations"
        ):
            # Deliberately no upload, document, processing, download, or delete
            # handler exists in this foundation slice.
            return _json_response(
                start_response,
                "503 Service Unavailable",
                {
                    "error": "real_document_intake_locked",
                    "real_document_intake_enabled": False,
                },
            )
        return _json_response(start_response, "404 Not Found", {"error": "not_found"})

    return app
