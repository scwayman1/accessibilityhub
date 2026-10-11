"""The structured document model behind the Hub's produced files.

A produced document is re-authored from this model, never from guesses: every
heading level, list, and table header comes from a human-confirmed role, and
every figure carries a human decision — a description or "decorative". The
model is plain JSON-serializable data so it can travel through the workbench,
the staging service, and the evidence receipt unchanged.

    {
      "version": "tina-docmodel/v1",
      "title": "Week 1 syllabus",
      "language": "en-US",
      "source_sha256": "sha256:…",          # optional provenance
      "blocks": [
        {"kind": "heading", "level": 1, "text": "Syllabus"},
        {"kind": "paragraph", "text": "…"},
        {"kind": "list", "ordered": false, "items": ["…", "…"]},
        {"kind": "table", "caption": "…", "header_rows": 1, "rows": [["Item", "Weight"], ["Essay", "40%"]]},
        {"kind": "figure", "mime": "image/png", "base64": "…", "page": 2,
         "alt": "…" | null, "decorative": false, "caption": "…" | null},
        {"kind": "notice", "text": "…"}      # a visible note the Hub adds (e.g. an image it could not carry)
      ]
    }
"""
from __future__ import annotations

import base64
import binascii
import re
from typing import Any

DOCMODEL_VERSION = "tina-docmodel/v1"
BLOCK_KINDS = ("heading", "paragraph", "list", "table", "figure", "notice")
FIGURE_MIMES = ("image/png", "image/jpeg")
# BCP 47 shape check (language-region-variant), not a registry lookup.
LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
MAX_ALT_LENGTH = 1000


class DocModelError(ValueError):
    """Raised when a document model cannot be authored into produced files."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def pending_decisions(model: dict[str, Any]) -> list[dict[str, Any]]:
    """Figures that still need a human decision (a description or decorative)."""
    pending = []
    for index, block in enumerate(model.get("blocks") or []):
        if isinstance(block, dict) and block.get("kind") == "figure":
            if not block.get("decorative") and not _text(block.get("alt")):
                pending.append({"block": index, "figure": block.get("figure"), "page": block.get("page")})
    return pending


def validate_docmodel(model: Any) -> list[str]:
    """Every reason this model cannot be authored. Empty means it is ready."""
    if not isinstance(model, dict):
        return ["The document model must be an object."]
    problems: list[str] = []
    if model.get("version") != DOCMODEL_VERSION:
        problems.append(f"Unsupported document model version: {model.get('version')!r}.")
    if not _text(model.get("title")):
        problems.append("A document title is required.")
    language = str(model.get("language") or "").strip()
    if not LANGUAGE_PATTERN.match(language):
        problems.append("A document language such as en-US is required.")
    blocks = model.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        problems.append("The document has no content blocks.")
        return problems
    for index, block in enumerate(blocks):
        where = f"Block {index + 1}"
        if not isinstance(block, dict) or block.get("kind") not in BLOCK_KINDS:
            problems.append(f"{where} has an unknown kind.")
            continue
        kind = block["kind"]
        if kind in {"heading", "paragraph", "notice"} and not _text(block.get("text")):
            problems.append(f"{where} ({kind}) has no text.")
        if kind == "heading" and block.get("level") not in (1, 2, 3, 4, 5, 6):
            problems.append(f"{where} heading level must be 1–6.")
        if kind == "list":
            items = block.get("items")
            if not isinstance(items, list) or not items or not all(_text(item) for item in items):
                problems.append(f"{where} list needs at least one non-empty item.")
        if kind == "table":
            rows = block.get("rows")
            header_rows = block.get("header_rows")
            if not isinstance(rows, list) or not rows or not all(isinstance(row, list) and row for row in rows):
                problems.append(f"{where} table needs rows of cells.")
            elif not isinstance(header_rows, int) or not 1 <= header_rows <= len(rows):
                problems.append(f"{where} table needs at least one header row, confirmed by a person.")
        if kind == "figure":
            if block.get("mime") not in FIGURE_MIMES:
                problems.append(f"{where} figure must be PNG or JPEG.")
            try:
                base64.b64decode(str(block.get("base64") or ""), validate=True)
            except (binascii.Error, ValueError):
                problems.append(f"{where} figure image data is not valid base64.")
            alt = _text(block.get("alt"))
            decorative = bool(block.get("decorative"))
            if decorative and alt:
                problems.append(f"{where} figure is marked decorative and also described; choose one.")
            elif not decorative and not alt:
                page = block.get("page")
                problems.append(
                    f"{where} figure{f' (page {page})' if page else ''} needs a description or a decorative decision from a person."
                )
            if len(alt) > MAX_ALT_LENGTH:
                problems.append(f"{where} figure description is longer than {MAX_ALT_LENGTH} characters.")
    return problems


def require_valid(model: Any) -> dict[str, Any]:
    problems = validate_docmodel(model)
    if problems:
        raise DocModelError(problems)
    return model


def apply_figure_decisions(model: dict[str, Any], decisions: dict[Any, Any] | None) -> dict[str, Any]:
    """Return a copy of the model with human figure decisions applied.

    ``decisions`` maps a figure number (``block["figure"]``) to
    ``{"alt": "…"}`` or ``{"decorative": true}``. The tool records these
    decisions; it never authors them.
    """
    decisions = {str(key): value for key, value in (decisions or {}).items()}
    blocks = []
    for block in model.get("blocks") or []:
        block = dict(block)
        if block.get("kind") == "figure" and str(block.get("figure")) in decisions:
            decision = decisions[str(block.get("figure"))] or {}
            if decision.get("decorative"):
                block["decorative"], block["alt"] = True, None
            else:
                block["decorative"], block["alt"] = False, _text(decision.get("alt")) or None
        blocks.append(block)
    return {**model, "blocks": blocks}
