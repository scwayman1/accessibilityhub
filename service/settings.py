"""Fail-closed configuration for the private staging service."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


HOSTED_CONTROL_VARS = (
    "HUB_PRIVATE_OBJECT_STORAGE",
    "HUB_MALWARE_SCAN_GATE",
    "HUB_WORKER_ISOLATION_ATTESTATION",
    "HUB_TENANT_AUTH_ISSUER",
    "HUB_LIFECYCLE_POLICY_ID",
    "HUB_AUDIT_SINK",
)


@dataclass(frozen=True)
class ServiceSettings:
    environment: str
    data_dir: Path
    access_code: str | None
    session_secret: str | None
    hosted_controls: tuple[str, ...]

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
        )

    @property
    def login_ready(self) -> bool:
        return bool(self.access_code and self.session_secret and len(self.session_secret) >= 32)

    @property
    def hosted_boundary_ready(self) -> bool:
        return len(self.hosted_controls) == len(HOSTED_CONTROL_VARS)

    @property
    def synthetic_intake_ready(self) -> bool:
        """Only the local synthetic slice is executable until hosted adapters exist."""
        return self.login_ready and self.environment == "development"

    def health_payload(self) -> dict[str, object]:
        return {
            "ok": True,
            "service": "accessibility-hub-staging",
            "environment": self.environment,
            "synthetic_only": True,
            "login_ready": self.login_ready,
            "synthetic_intake_ready": self.synthetic_intake_ready,
            "hosted_boundary_ready": self.hosted_boundary_ready,
            "hosted_intake_enabled": False,
            "configured_hosted_controls": list(self.hosted_controls),
        }
