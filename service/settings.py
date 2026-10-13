"""Fail-closed configuration for the private staging service."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from service.sso import normalize_provider


HOSTED_CONTROL_VARS = (
    "HUB_PRIVATE_OBJECT_STORAGE",
    "HUB_MALWARE_SCAN_GATE",
    "HUB_WORKER_ISOLATION_ATTESTATION",
    "HUB_TENANT_AUTH_ISSUER",
    "HUB_LIFECYCLE_POLICY_ID",
    "HUB_AUDIT_SINK",
)

DEFAULT_RETENTION_DAYS = 365
MAX_RETENTION_DAYS = 3650


def _retention_days(value: str | None) -> int:
    """Whole days a document is kept before automatic deletion (default 365)."""
    text = (value or "").strip()
    if not text:
        return DEFAULT_RETENTION_DAYS
    if not text.isdigit() or not 1 <= int(text) <= MAX_RETENTION_DAYS:
        raise ValueError(f"HUB_RETENTION_DAYS must be a whole number of days from 1 to {MAX_RETENTION_DAYS}.")
    return int(text)


@dataclass(frozen=True)
class ServiceSettings:
    environment: str
    data_dir: Path
    access_code: str | None
    session_secret: str | None
    hosted_controls: tuple[str, ...]
    allow_hosted_synthetic: bool = False
    public_access: bool = False
    enable_produce: bool = False
    sso_provider: str = ""
    accept_uploads: bool = False
    retention_days: int = DEFAULT_RETENTION_DAYS

    @classmethod
    def from_environ(cls, environ: dict[str, str] | None = None) -> "ServiceSettings":
        values = environ or os.environ
        environment = values.get("HUB_ENV", "development").strip().lower()
        if environment not in {"development", "staging"}:
            raise ValueError("HUB_ENV must be development or staging.")
        return cls(
            environment=environment,
            data_dir=Path(values.get("HUB_DATA_DIR", ".hub-staging")).expanduser().resolve(),
            access_code=values.get("HUB_STAGING_ACCESS_CODE"),
            session_secret=values.get("HUB_SESSION_SECRET"),
            hosted_controls=tuple(name for name in HOSTED_CONTROL_VARS if values.get(name)),
            # Explicit opt-in only: the value must be exactly "true". Anything
            # else (unset, "1", "TRUE", "yes") keeps hosted intake closed.
            allow_hosted_synthetic=values.get("HUB_ALLOW_HOSTED_SYNTHETIC", "") == "true",
            public_access=values.get("HUB_PUBLIC_ACCESS", "") == "true",
            # Producing downloadable copies stays off in hosted environments
            # until the pilot opens it explicitly (exactly "true").
            enable_produce=values.get("HUB_ENABLE_PRODUCE", "") == "true",
            # Placeholder only: shows where SSO will live (service/sso.py).
            sso_provider=normalize_provider(values.get("HUB_SSO_PROVIDER")),
            # Real PDF uploads in hosted staging: exactly "true" opens them, and
            # only behind sign-in (see uploads_ready).
            accept_uploads=values.get("HUB_ACCEPT_UPLOADS", "") == "true",
            retention_days=_retention_days(values.get("HUB_RETENTION_DAYS")),
        )

    @property
    def login_ready(self) -> bool:
        return bool(self.access_code and self.session_secret and len(self.session_secret) >= 32)

    @property
    def produce_ready(self) -> bool:
        return self.environment == "development" or self.enable_produce

    @property
    def uploads_ready(self) -> bool:
        """Real PDF uploads: always in development; hosted only behind the
        explicit HUB_ACCEPT_UPLOADS opt-in, and never on a public (no sign-in)
        workspace."""
        if not self.login_ready:
            return False
        if self.environment == "development":
            return True
        return self.environment == "staging" and self.accept_uploads and not self.public_access

    @property
    def hosted_uploads_open(self) -> bool:
        return self.environment == "staging" and self.uploads_ready

    @property
    def hosted_boundary_ready(self) -> bool:
        return len(self.hosted_controls) == len(HOSTED_CONTROL_VARS)

    @property
    def synthetic_intake_ready(self) -> bool:
        """Bundled-fixture intake runs locally, or hosted behind an explicit
        opt-in (HUB_ALLOW_HOSTED_SYNTHETIC, or HUB_ACCEPT_UPLOADS, which is the
        wider of the two).

        The separate locked real-intake service (service/real_intake) is a
        different boundary and is unaffected by either flag.
        """
        if not self.login_ready:
            return False
        if self.environment == "development":
            return True
        return self.environment == "staging" and (self.allow_hosted_synthetic or self.uploads_ready)

    def health_payload(self) -> dict[str, object]:
        # Imported lazily so configuration parsing never depends on tool probes.
        from service.toolchain import toolchain_versions

        return {
            "ok": True,
            "service": "accessibility-hub-staging",
            "environment": self.environment,
            "synthetic_only": not self.hosted_uploads_open,
            "login_ready": self.login_ready,
            "synthetic_intake_ready": self.synthetic_intake_ready,
            "hosted_boundary_ready": self.hosted_boundary_ready,
            "hosted_intake_enabled": self.hosted_uploads_open,
            "retention_days": self.retention_days,
            "hosted_synthetic_optin": self.allow_hosted_synthetic,
            "configured_hosted_controls": list(self.hosted_controls),
            # Read-only visibility: which document tools this environment has.
            # Names map to a version line, or null when the tool is absent —
            # absent tools are disclosed per-review by the checker itself.
            "toolchain": dict(toolchain_versions()),
        }
