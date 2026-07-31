import unittest
from pathlib import Path
from unittest.mock import patch

from service.real_intake.deploy_check import (
    LockedDeployViolation,
    verify_locked_deploy,
)


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://accessibility.coastlinecollegefoundation.com"


def locked_environment(**overrides):
    values = {
        "HUB_ENV": "production",
        "HUB_REAL_DOCUMENT_INTAKE": "false",
        "HUB_REAL_INTAKE_CONTROL_MANIFEST": "2026-07-30.v1",
        "CLERK_AUTHORIZED_PARTY": ORIGIN,
        "HUB_BYOK_MODEL_ENABLED": "false",
        "HUB_MODEL_EGRESS_ENABLED": "false",
    }
    values.update(overrides)
    return values


class LockedDeployCheckTests(unittest.TestCase):
    def test_minimal_provisioning_environment_is_locked(self):
        verify_locked_deploy(locked_environment(), repository_root=ROOT)

    def test_activation_model_origin_manifest_and_environment_fail(self):
        cases = (
            {"HUB_REAL_DOCUMENT_INTAKE": "true"},
            {"HUB_REAL_DOCUMENT_INTAKE": ""},
            {"HUB_BYOK_MODEL_ENABLED": "true"},
            {"HUB_MODEL_EGRESS_ENABLED": "true"},
            {"CLERK_AUTHORIZED_PARTY": "https://preview.onrender.com"},
            {"HUB_REAL_INTAKE_CONTROL_MANIFEST": "unreviewed"},
            {"HUB_ENV": "development"},
        )
        for overrides in cases:
            with self.assertRaises(LockedDeployViolation, msg=overrides):
                verify_locked_deploy(
                    locked_environment(**overrides),
                    repository_root=ROOT,
                )

    def test_handler_constant_cannot_be_enabled_for_locked_deploy(self):
        with patch(
            "service.real_intake.deploy_check."
            "REAL_DOCUMENT_ACTION_HANDLERS_IMPLEMENTED",
            True,
        ):
            with self.assertRaises(LockedDeployViolation):
                verify_locked_deploy(
                    locked_environment(),
                    repository_root=ROOT,
                )


class SeparateBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.public = (ROOT / "render.yaml").read_text()
        self.private = (ROOT / "render.real-intake.yaml").read_text()
        self.scanner = (ROOT / "deploy/clamav/Dockerfile").read_text()

    def test_public_blueprint_remains_synthetic_only(self):
        for prohibited in (
            "service.real_intake",
            "HUB_REAL_DOCUMENT_INTAKE",
            "accessibility-hub-real-intake",
            "accessibility-hub-clamav",
        ):
            self.assertNotIn(prohibited, self.public)

    def test_private_blueprint_is_isolated_protected_and_manual(self):
        required = (
            'generation: "off"',
            "Coastline Accessibility Hub Private Real Intake",
            "isolation: enabled",
            "protection: enabled",
            'autoDeployTrigger: "off"',
            "maintenanceMode:",
            "enabled: true",
            "renderSubdomainPolicy: disabled",
            "accessibility.coastlinecollegefoundation.com",
            "HUB_REAL_DOCUMENT_INTAKE",
            'value: "false"',
            "HUB_MODEL_EGRESS_ENABLED",
            "type: worker",
            "type: pserv",
            "type: keyvalue",
            "maxmemoryPolicy: noeviction",
            "persistenceMode: journal-snapshot",
            "ipAllowList: []",
            "accessibility-hub-real-audit",
        )
        for value in required:
            self.assertIn(value, self.private)
        self.assertNotIn("generation: manual", self.private)
        self.assertNotIn("accessibility-hub-staging", self.private)

    def test_secret_values_are_prompt_only(self):
        for name in (
            "CLERK_PUBLISHABLE_KEY",
            "CLERK_JWT_KEY",
            "CLERK_ISSUER",
            "HUB_OWNER_CLERK_USER_ID",
            "HUB_OBJECT_STORAGE_ACCESS_KEY_ID",
            "HUB_OBJECT_STORAGE_SECRET_ACCESS_KEY",
        ):
            marker = f"- key: {name}\n                sync: false"
            self.assertIn(marker, self.private)

    def test_scanner_is_immutable_and_bounded(self):
        self.assertIn(
            "clamav/clamav:1.4.5_base@"
            "sha256:3e2eac6cdbd5c5cb408990e6fe02b81d"
            "91298bc71090e7f3bc2ab7f7a3a256f6",
            self.scanner,
        )
        for value in (
            "StreamMaxLength 25M",
            "MaxFileSize 25M",
            "MaxScanSize 250M",
            "ConcurrentDatabaseReload no",
        ):
            self.assertIn(value, self.scanner)
        for floating in (":latest", ":stable", ":1.4_base"):
            self.assertNotIn(floating, self.scanner)

    def test_dormant_worker_has_no_network_or_processing_imports(self):
        worker = (
            ROOT / "service/real_intake/locked_worker.py"
        ).read_text()
        for prohibited in (
            "socket",
            "requests",
            "urllib",
            "boto",
            "redis",
            "psycopg",
            "pypdf",
            "clamd_client",
        ):
            self.assertNotIn(prohibited, worker)


if __name__ == "__main__":
    unittest.main()
