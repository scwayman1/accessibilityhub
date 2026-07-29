"""Tina Phase 2: permission-gated deterministic metadata remediation.

This module lives outside the read-only scan kernel on purpose. It performs a
small, fully deterministic set of document mutations (document title, primary
language, and title display preference), records before/after hashes for every
mutation, and never claims the result is accessible or conformant. Structural
work — tags, reading order, alternatives — is deliberately not automated here.
"""
from __future__ import annotations

import io
import re
from hashlib import sha256
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, DictionaryObject, NameObject, TextStringObject

from tina.kernel import ToolGateway, ToolManifest

REMEDIATE_METADATA_PERMISSION = "document.remediate.metadata"
REMEDIATE_SEMANTICS_PERMISSION = "document.remediate.semantics"
MAX_TITLE_CHARS = 512
LANGUAGE_TAG_PATTERN = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


class RemediationError(ValueError):
    """Raised when a requested remediation cannot be applied safely."""


def validate_fix_request(title: str | None, language: str | None) -> None:
    if title is None and language is None:
        raise RemediationError("No supported fix was requested.")
    if title is not None:
        if not title.strip():
            raise RemediationError("A document title cannot be empty.")
        if len(title) > MAX_TITLE_CHARS:
            raise RemediationError(f"A document title must be {MAX_TITLE_CHARS} characters or fewer.")
    if language is not None and not LANGUAGE_TAG_PATTERN.match(language):
        raise RemediationError("The language must be a tag like en, en-US, or es-MX.")


def _set_document_metadata(input_data: dict[str, Any]) -> dict[str, Any]:
    payload: bytes = input_data["payload"]
    title: str | None = input_data.get("title")
    language: str | None = input_data.get("language")
    validate_fix_request(title, language)

    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except Exception as error:
        raise RemediationError(f"The PDF could not be parsed for remediation: {type(error).__name__}") from error
    if reader.is_encrypted:
        raise RemediationError("Encrypted PDFs are not remediated; request an unencrypted source copy.")

    writer = PdfWriter(clone_from=reader)
    actions: list[dict[str, Any]] = []
    if title is not None:
        clean_title = title.strip()
        writer.add_metadata({"/Title": clean_title})
        root = writer.root_object
        viewer_preferences = root.get("/ViewerPreferences")
        if viewer_preferences is None:
            root[NameObject("/ViewerPreferences")] = writer._add_object(DictionaryObject())
        root["/ViewerPreferences"].get_object()[NameObject("/DisplayDocTitle")] = BooleanObject(True)
        actions.append({
            "rule_id": "PDF.METADATA.TITLE",
            "action": "set_document_title",
            "value": clean_title,
            "detail": "Set /Title in the document information dictionary and /DisplayDocTitle true so viewers show the title instead of the filename.",
        })
    if language is not None:
        writer.root_object[NameObject("/Lang")] = TextStringObject(language)
        actions.append({
            "rule_id": "PDF.METADATA.LANGUAGE",
            "action": "set_primary_language",
            "value": language,
            "detail": "Set /Lang in the document catalog so assistive technology can select the right voice and pronunciation.",
        })

    output = io.BytesIO()
    writer.write(output)
    remediated = output.getvalue()
    return {
        "actions": actions,
        "source_sha256": f"sha256:{sha256(payload).hexdigest()}",
        "remediated_sha256": f"sha256:{sha256(remediated).hexdigest()}",
        "source_bytes": len(payload),
        "remediated_bytes": len(remediated),
        "remediated_payload": remediated,
    }


def _apply_accessible_names(input_data: dict[str, Any]) -> dict[str, Any]:
    """Class-2 user-supplied semantic repairs: link descriptions and figure alt text.

    Every string applied here was written by a human. The tool attaches it; it
    never authors, infers, or improves it. Alt text requires a tag structure —
    on untagged PDFs the tool declines honestly and routes to the HTML rebuild.
    """
    payload: bytes = input_data["payload"]
    link_names: dict[str, str] = {str(k): str(v) for k, v in (input_data.get("link_names") or {}).items() if str(v).strip()}
    alt_texts: dict[str, dict[str, Any]] = {str(k): v for k, v in (input_data.get("alt_texts") or {}).items()}
    if not link_names and not alt_texts:
        raise RemediationError("No link description or alternative text was supplied.")

    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except Exception as error:
        raise RemediationError(f"The PDF could not be parsed for remediation: {type(error).__name__}") from error
    if reader.is_encrypted:
        raise RemediationError("Encrypted PDFs are not remediated; request an unencrypted source copy.")

    writer = PdfWriter(clone_from=reader)
    actions: list[dict[str, Any]] = []

    if link_names:
        link_index = -1
        applied = 0
        for page in writer.pages:
            for raw in page.get("/Annots", []) or []:
                annotation = raw.get_object()
                if not annotation or annotation.get("/Subtype") != "/Link":
                    continue
                link_index += 1
                name = link_names.get(str(link_index))
                if name:
                    annotation[NameObject("/Contents")] = TextStringObject(name.strip()[:500])
                    applied += 1
        if applied != len(link_names):
            raise RemediationError(
                f"Only {applied} of {len(link_names)} link indexes exist in this document; re-run the review and try again."
            )
        actions.append({
            "rule_id": "PDF.LINKS.NAME",
            "action": "apply_link_descriptions",
            "count": applied,
            "provenance": "user_authored",
            "detail": "Set /Contents (accessible description) on each named link annotation.",
        })

    if alt_texts:
        from check_pdf import indirect, iter_figures  # deterministic walker shared with the checker

        struct_root = indirect((indirect(writer.root_object) or {}).get("/StructTreeRoot"))
        if struct_root is None:
            raise RemediationError(
                "This PDF has no tag structure, so alternative text cannot be attached to it. "
                "Rebuild it as an accessible HTML working copy instead — that path carries your descriptions."
            )
        figures = iter_figures(struct_root)
        applied = 0
        for key, decision in alt_texts.items():
            try:
                figure = figures[int(key)]
            except (ValueError, IndexError):
                raise RemediationError(f"Figure index {key} does not exist in this document's structure tree.")
            if decision.get("decorative"):
                value = ""
            else:
                value = str(decision.get("alt", "")).strip()[:1000]
                if not value:
                    raise RemediationError("Each figure needs a description or an explicit decorative decision.")
            figure["element"][NameObject("/Alt")] = TextStringObject(value)
            applied += 1
        actions.append({
            "rule_id": "PDF.IMAGES.ALT_MISSING",
            "action": "apply_figure_alt_text",
            "count": applied,
            "provenance": "user_authored",
            "detail": "Set /Alt on each decided figure element (empty /Alt marks a decorative image).",
        })

    output = io.BytesIO()
    writer.write(output)
    remediated = output.getvalue()
    return {
        "actions": actions,
        "source_sha256": f"sha256:{sha256(payload).hexdigest()}",
        "remediated_sha256": f"sha256:{sha256(remediated).hexdigest()}",
        "source_bytes": len(payload),
        "remediated_bytes": len(remediated),
        "remediated_payload": remediated,
    }


class SemanticRemediation:
    """Applies human-authored link descriptions and figure alt text to a copy."""

    CONTRACT_VERSION = "tina-remediation-report/v1"
    CLAIM_BOUNDARY = (
        "These fixes attach human-written descriptions to a copy of the document. "
        "They resolve specific technical findings only; whether each description "
        "is meaningful remains a human judgment, and no conformance is implied."
    )

    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    @classmethod
    def with_builtin_tools(cls) -> "SemanticRemediation":
        gateway = ToolGateway()
        gateway.register(
            ToolManifest(
                name="apply_accessible_names",
                version="1.0.0",
                purpose="Attach user-authored link descriptions and figure alt text to a PDF copy.",
                deterministic=True,
                mutates_document=True,
                permissions=(REMEDIATE_SEMANTICS_PERMISSION,),
                timeout_ms=30_000,
            ),
            _apply_accessible_names,
        )
        return cls(gateway)

    def apply(self, filename: str, payload: bytes,
              link_names: dict[str, str] | None = None,
              alt_texts: dict[str, dict[str, Any]] | None = None) -> tuple[bytes, dict[str, Any]]:
        execution = self.gateway.execute(
            "apply_accessible_names",
            {"payload": payload, "link_names": link_names, "alt_texts": alt_texts},
            {REMEDIATE_SEMANTICS_PERMISSION},
        )
        remediated: bytes = execution["output"].pop("remediated_payload")
        report = {
            "contract_version": self.CONTRACT_VERSION,
            "claim_boundary": self.CLAIM_BOUNDARY,
            "filename": filename,
            "tool": execution["tool"],
            "tool_version": execution["tool_version"],
            "deterministic": execution["deterministic"],
            "mutates_document": execution["mutates_document"],
            **execution["output"],
        }
        return remediated, report


class MetadataRemediation:
    """Deterministic, evidence-recorded metadata fixer for local PDFs."""

    CONTRACT_VERSION = "tina-remediation-report/v1"
    CLAIM_BOUNDARY = (
        "These fixes resolve specific technical findings only. They do not make the "
        "document conformant, and structural review work remains with a human."
    )

    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    @classmethod
    def with_builtin_tools(cls) -> "MetadataRemediation":
        gateway = ToolGateway()
        gateway.register(
            ToolManifest(
                name="set_document_metadata",
                version="1.0.0",
                purpose="Set document title, primary language, and title display preference in a PDF copy.",
                deterministic=True,
                mutates_document=True,
                permissions=(REMEDIATE_METADATA_PERMISSION,),
                timeout_ms=30_000,
            ),
            _set_document_metadata,
        )
        return cls(gateway)

    def apply(
        self,
        filename: str,
        payload: bytes,
        title: str | None = None,
        language: str | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        """Apply the requested fixes to an in-memory copy; return (new bytes, report)."""
        execution = self.gateway.execute(
            "set_document_metadata",
            {"payload": payload, "title": title, "language": language},
            {REMEDIATE_METADATA_PERMISSION},
        )
        remediated: bytes = execution["output"].pop("remediated_payload")
        report = {
            "contract_version": self.CONTRACT_VERSION,
            "claim_boundary": self.CLAIM_BOUNDARY,
            "filename": filename,
            "tool": execution["tool"],
            "tool_version": execution["tool_version"],
            "deterministic": execution["deterministic"],
            "mutates_document": execution["mutates_document"],
            **execution["output"],
        }
        return remediated, report
