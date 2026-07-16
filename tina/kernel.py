"""Tina Phase 1: typed, deterministic, evidence-grade scan kernel.

This module deliberately contains no model provider, shell execution, repair action,
or conformance decision. Tools are explicitly registered and permission-scoped.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable


@dataclass(frozen=True)
class ToolManifest:
    name: str
    version: str
    purpose: str
    deterministic: bool
    mutates_document: bool | None
    permissions: tuple[str, ...]
    timeout_ms: int = 5_000

    def __post_init__(self) -> None:
        if self.mutates_document is None:
            raise ValueError("Tool manifests must explicitly declare mutation status.")
        if not self.permissions:
            raise ValueError("Tool manifests must declare at least one permission.")


class ToolPermissionError(PermissionError):
    pass


class ToolGateway:
    """A registry of typed, allow-listed tool adapters—not a command runner."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolManifest, Callable[[dict[str, Any]], dict[str, Any]]]] = {}

    def register(self, manifest: ToolManifest, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        if manifest.name in self._tools:
            raise ValueError(f"Tool already registered: {manifest.name}")
        self._tools[manifest.name] = (manifest, handler)

    def execute(self, name: str, input_data: dict[str, Any], granted_permissions: set[str]) -> dict[str, Any]:
        registration = self._tools.get(name)
        if registration is None:
            raise ToolPermissionError(f"Tool is not registered: {name}")
        manifest, handler = registration
        missing = set(manifest.permissions) - granted_permissions
        if missing:
            raise ToolPermissionError(f"Tool permission denied: {', '.join(sorted(missing))}")
        output = handler(input_data)
        if not isinstance(output, dict):
            raise TypeError(f"Tool {name} returned a non-object result")
        return {
            "tool": manifest.name,
            "tool_version": manifest.version,
            "deterministic": manifest.deterministic,
            "mutates_document": manifest.mutates_document,
            "output": output,
        }


def _inspect_file_signature(input_data: dict[str, Any]) -> dict[str, Any]:
    payload = input_data["payload"]
    declared = input_data.get("declared_mime_type")
    is_pdf = payload.startswith(b"%PDF-")
    return {
        "declared_mime_type": declared,
        "detected_mime_type": "application/pdf" if is_pdf else "application/octet-stream",
        "signature_valid": is_pdf,
        "size_bytes": len(payload),
        "sha256": f"sha256:{sha256(payload).hexdigest()}",
    }


class DeterministicScan:
    """Evidence-first, local in-memory scan orchestrator for Tina Phase 1."""

    CONTRACT_VERSION = "tina-scan-report/v1"
    DAR_VERSION = "tina-dar/v0"
    INTAKE_RULE = {
        "rule_id": "TINA-INTAKE-PDF-001",
        "version": "1.0.0",
        "title": "PDF signature must match the declared document type",
        "evaluation_mode": "fully_automated",
        "standard_mappings": [],
    }

    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    @classmethod
    def with_builtin_pdf_intake_tools(cls) -> "DeterministicScan":
        gateway = ToolGateway()
        gateway.register(
            ToolManifest(
                name="inspect_file_signature",
                version="1.0.0",
                purpose="Inspect PDF magic bytes and compute a source hash.",
                deterministic=True,
                mutates_document=False,
                permissions=("document.intake.read",),
            ),
            _inspect_file_signature,
        )
        return cls(gateway)

    def inspect_bytes(self, filename: str, payload: bytes, declared_mime_type: str) -> dict[str, Any]:
        execution = self.gateway.execute(
            "inspect_file_signature",
            {"payload": payload, "declared_mime_type": declared_mime_type},
            {"document.intake.read"},
        )
        evidence = {
            "evidence_id": "ev:signature:1",
            "type": "file_signature",
            "tool": execution["tool"],
            "tool_version": execution["tool_version"],
            "value": execution["output"],
        }
        is_pdf = execution["output"]["signature_valid"]
        outcome = "pass" if is_pdf else "fail"
        finding = {
            "finding_id": "finding:intake:pdf-signature",
            "rule_id": self.INTAKE_RULE["rule_id"],
            "rule_version": self.INTAKE_RULE["version"],
            "outcome": outcome,
            "severity": "info" if is_pdf else "high",
            "confidence": {"detection_confidence": 1.0, "overall_decision_confidence": 1.0},
            "evidence": [evidence],
            "review_status": "not_required",
            "claim_boundary": "Technical evidence only; this result is not a conformance determination.",
        }
        return {
            "contract_version": self.CONTRACT_VERSION,
            "conformance_determined": False,
            "claim_boundary": "Tina reports reproducible tool evidence and review routing, not accessibility conformance.",
            "document": {
                "dar_version": self.DAR_VERSION,
                "document_id": f"local:{execution['output']['sha256'][7:23]}",
                "version_id": f"source:{execution['output']['sha256'][7:23]}",
                "filename": filename,
                "declared_mime_type": declared_mime_type,
                "detected_mime_type": execution["output"]["detected_mime_type"],
                "source_hash": execution["output"]["sha256"],
                "size_bytes": execution["output"]["size_bytes"],
                "elements": [],
                "provenance": [{"tool": execution["tool"], "version": execution["tool_version"]}],
            },
            "rules": [self.INTAKE_RULE],
            "tool_executions": [execution],
            "findings": [finding],
        }
