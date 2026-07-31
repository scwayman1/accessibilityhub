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


PRIVATE_BLUEPRINT_REQUIRED = (
    'generation: "off"',
    "Coastline Accessibility Hub Private Real Intake",
    "isolation: enabled",
    "protection: enabled",
    'autoDeployTrigger: "off"',
    "maintenanceMode:",
    "enabled: true",
    "renderSubdomainPolicy: disabled",
    "accessibility.coastlinecollegefoundation.com",
    "python -m service.real_intake.deploy_check",
    "python -m service.real_intake.locked_worker",
    "HUB_REAL_DOCUMENT_INTAKE",
    'value: "false"',
    "HUB_BYOK_MODEL_ENABLED",
    "HUB_MODEL_EGRESS_ENABLED",
)

WORKER_FORBIDDEN_CAPABILITIES = (
    "HUB_POSTGRES_PRIVATE_URL",
    "HUB_QUEUE_PRIVATE_URL",
    "HUB_OBJECT_STORAGE_ENDPOINT",
    "HUB_OBJECT_STORAGE_BUCKET",
    "HUB_OBJECT_STORAGE_ACCESS_KEY_ID",
    "HUB_OBJECT_STORAGE_SECRET_ACCESS_KEY",
    "HUB_CLAMAV_PRIVATE_ENDPOINT",
    "HUB_AUDIT_SINK",
)


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

    private_blueprint = (root / "render.real-intake.yaml").read_text(
        encoding="utf-8"
    )
    if any(
        required not in private_blueprint
        for required in PRIVATE_BLUEPRINT_REQUIRED
    ):
        problems.append("private_blueprint_lock_missing")
    if private_blueprint.count("branch: main") != 3:
        problems.append("private_blueprint_not_pinned_to_main")
    if "codex/controlled-real-intake-foundation" in private_blueprint:
        problems.append("private_blueprint_feature_branch_present")

    worker_marker = "          - type: worker\n"
    scanner_marker = "          - type: pserv\n"
    if worker_marker not in private_blueprint or scanner_marker not in private_blueprint:
        problems.append("private_blueprint_topology_missing")
    else:
        worker_block = private_blueprint.split(worker_marker, 1)[1].split(
            scanner_marker, 1
        )[0]
        if any(name in worker_block for name in WORKER_FORBIDDEN_CAPABILITIES):
            problems.append("dormant_worker_has_live_capability")

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
