"""Deployment guard that proves a real-intake release is still locked."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from service.real_intake.settings import (
    APPROVED_AUTHORIZED_PARTY,
    CONTROL_MANIFEST_VERSION,
    REAL_DOCUMENT_ACTION_HANDLERS_IMPLEMENTED,
    RealIntakeSettings,
)


class LockedDeployViolation(RuntimeError):
    pass


def verify_locked_deploy(
    environ: Mapping[str, str] | None = None,
    *,
    repository_root: Path | None = None,
) -> None:
    """Reject a deploy that weakens any pre-activation invariant."""
    values = dict(os.environ if environ is None else environ)
    settings = RealIntakeSettings.from_environ(values)
    problems: list[str] = []

    if settings.environment != "production":
        problems.append("environment_not_production")
    if values.get("HUB_REAL_DOCUMENT_INTAKE") != "false":
        problems.append("real_document_intake_not_explicitly_false")
    if settings.activation_requested:
        problems.append("activation_requested")
    if values.get("HUB_BYOK_MODEL_ENABLED") != "false":
        problems.append("byok_model_not_explicitly_false")
    if values.get("HUB_MODEL_EGRESS_ENABLED") != "false":
        problems.append("model_egress_not_explicitly_false")
    if settings.value("CLERK_AUTHORIZED_PARTY") != APPROVED_AUTHORIZED_PARTY:
        problems.append("authorized_party_not_approved")
    if settings.control_manifest_version != CONTROL_MANIFEST_VERSION:
        problems.append("control_manifest_not_pinned")
    if REAL_DOCUMENT_ACTION_HANDLERS_IMPLEMENTED:
        problems.append("real_document_handlers_present")
    health = settings.health_payload()
    if (
        health.get("real_document_intake_enabled") is not False
        or health.get("synthetic_only") is not True
        or health.get("model_egress_enabled") is not False
    ):
        problems.append("health_contract_not_locked")

    root = repository_root or Path(__file__).resolve().parents[2]
    public_blueprint = (root / "render.yaml").read_text(encoding="utf-8")
    for prohibited in (
        "service.real_intake",
        "HUB_REAL_DOCUMENT_INTAKE",
        "accessibility-hub-real-intake",
    ):
        if prohibited in public_blueprint:
            problems.append("public_blueprint_boundary_changed")
            break

    if problems:
        raise LockedDeployViolation(",".join(dict.fromkeys(problems)))


def main() -> int:
    try:
        verify_locked_deploy()
    except (LockedDeployViolation, OSError, ValueError):
        print("locked-deploy-verification: failed")
        return 78
    print("locked-deploy-verification: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
