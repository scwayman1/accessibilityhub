"""Tina Phase 5: the review-record seal (an appended summary page, never a claim).

This module appends exactly ONE final "Review summary" page to a copy of a
reviewed PDF. The page is a provenance record: the seal wording, the review
date, a short evidence hash of the source bytes, the lane counts, the fixes
that were applied to the copy, and the verified signals a human confirmed.
It is deliberately NOT a certification, a score, or a conformance statement,
and the page says so in as many words.

Anti-vandal contract (asserted, never trusted — mirrors tina/structure.py):
after appending the page, the output is re-opened with a fresh parser and must
show exactly old_page_count + 1 pages and byte-identical extracted text on
every original page. Any deviation raises RemediationError and no bytes leave
the function. Encrypted PDFs and unparseable bytes decline honestly.
"""
from __future__ import annotations

import io
from hashlib import sha256
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from tina.kernel import ToolGateway, ToolManifest
from tina.remedy import RemediationError

SEAL_PERMISSION = "document.seal.append"

SEAL_WORDING = "Reviewed & improved with Coastline College Accessibility Hub"
RECORD_LINE = "A review record, not a certification."
EVIDENCE_HASH_CHARS = 12

# Brand ink and coral, from the service token block, as PDF RGB triples.
_INK_RGB = "0.137 0.165 0.200"
_CORAL_RGB = "0.941 0.337 0.247"
_HAIRLINE_RGB = "0.925 0.914 0.902"

_LANE_LABELS = {
    "needs_attention": "Needs attention",
    "review_recommended": "Review recommended",
    "verified_signal": "Verified signal",
    "not_assessed": "Not assessed",
}
_MAX_LIST_ITEMS = 8
_MAX_ITEM_CHARS = 90

_PAGE_WIDTH = 612.0
_PAGE_HEIGHT = 792.0
_MARGIN = 72.0
# Cubic-bezier circle constant (4/3 * tan(pi/8)).
_KAPPA = 0.5523


def _escape(text: str) -> str:
    """ASCII-sanitize and escape a string for a PDF literal string."""
    clean = text.encode("ascii", "replace").decode("ascii")
    return clean.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _centered_x(text: str, size: float) -> float:
    """Approximate Helvetica centering (avg glyph ~0.52 em); clamped to margin."""
    return max(_MARGIN, (_PAGE_WIDTH - 0.52 * size * len(text)) / 2)


def _circle_ops(cx: float, cy: float, r: float, width: float) -> str:
    k = _KAPPA * r
    return (
        f"{_CORAL_RGB} RG {width} w "
        f"{cx + r:.1f} {cy:.1f} m "
        f"{cx + r:.1f} {cy + k:.1f} {cx + k:.1f} {cy + r:.1f} {cx:.1f} {cy + r:.1f} c "
        f"{cx - k:.1f} {cy + r:.1f} {cx - r:.1f} {cy + k:.1f} {cx - r:.1f} {cy:.1f} c "
        f"{cx - r:.1f} {cy - k:.1f} {cx - k:.1f} {cy - r:.1f} {cx:.1f} {cy - r:.1f} c "
        f"{cx + k:.1f} {cy - r:.1f} {cx + r:.1f} {cy - k:.1f} {cx + r:.1f} {cy:.1f} c "
        "S "
    )


def _validate_summary(summary: Any) -> tuple[dict[str, int], list[str], list[str]]:
    if not isinstance(summary, dict):
        raise RemediationError("The review summary must be a mapping of lanes, applied fixes, and verified signals.")
    raw_lanes = summary.get("lanes") or {}
    if not isinstance(raw_lanes, dict):
        raise RemediationError("Lane counts must be a mapping of lane key to count.")
    lanes: dict[str, int] = {}
    for key, value in raw_lanes.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RemediationError(f"Lane count for '{key}' must be a whole number of findings.")
        lanes[str(key)] = value
    lists: list[list[str]] = []
    for field in ("applied_fixes", "verified"):
        raw = summary.get(field) or []
        if not isinstance(raw, (list, tuple)):
            raise RemediationError(f"'{field}' must be a list of short descriptions.")
        lists.append([str(item).strip() for item in raw if str(item).strip()])
    return lanes, lists[0], lists[1]


def _list_lines(items: list[str], empty_line: str) -> list[str]:
    if not items:
        return [empty_line]
    shown = [f"- {item[:_MAX_ITEM_CHARS]}" for item in items[:_MAX_LIST_ITEMS]]
    remaining = len(items) - _MAX_LIST_ITEMS
    if remaining > 0:
        shown.append(f"...and {remaining} more")
    return shown


def _seal_page_stream(lanes: dict[str, int], applied_fixes: list[str],
                      verified: list[str], when_iso: str, evidence_short: str) -> bytes:
    """Author the summary page: white ground, ink text, a coral seal ring."""
    cx, cy = _PAGE_WIDTH / 2, 668.0
    ops: list[str] = ["q "]
    ops.append(_circle_ops(cx, cy, 54, 3))
    ops.append(_circle_ops(cx, cy, 46, 1))
    ops.append(f"{_HAIRLINE_RGB} RG 0.75 w {_MARGIN:.1f} 520 m {_PAGE_WIDTH - _MARGIN:.1f} 520 l S ")
    ops.append(f"{_INK_RGB} rg BT ")

    def line(text: str, x: float, y: float, size: float, bold: bool = False) -> None:
        font = "/F2" if bold else "/F1"
        ops.append(f"{font} {size} Tf 1 0 0 1 {x:.1f} {y:.1f} Tm ({_escape(text)}) Tj ")

    line("COASTLINE", _centered_x("COASTLINE", 12), cy + 4, 12, bold=True)
    line("ACCESSIBILITY HUB", _centered_x("ACCESSIBILITY HUB", 7.5), cy - 12, 7.5)

    line(SEAL_WORDING, _centered_x(SEAL_WORDING, 14), 584, 14, bold=True)
    meta = f"Reviewed on {when_iso[:32]} - evidence sha256:{evidence_short}"
    line(meta, _centered_x(meta, 10.5), 562, 10.5)
    line(RECORD_LINE, _centered_x(RECORD_LINE, 12), 540, 12)

    y = 494.0

    def section(heading: str, rows: list[str]) -> None:
        nonlocal y
        line(heading, _MARGIN, y, 12, bold=True)
        y -= 18
        for row in rows:
            line(row, _MARGIN, y, 10.5)
            y -= 16
        y -= 10

    lane_rows = [
        f"{_LANE_LABELS.get(key, key.replace('_', ' ').capitalize())}: {count}"
        for key, count in lanes.items()
    ] or ["No lane counts were recorded."]
    section("Where findings landed", lane_rows)
    section("Fixes applied to this copy", _list_lines(applied_fixes, "No automated fixes were applied."))
    section("Signals a human verified", _list_lines(verified, "No verified signals were recorded."))
    ops.append("ET Q")
    return "".join(ops).encode("ascii")


def _append_review_summary(input_data: dict[str, Any]) -> dict[str, Any]:
    payload: bytes = input_data["payload"]
    when_iso = str(input_data.get("when_iso") or "").strip()
    if not when_iso:
        raise RemediationError("A review date is required to record the seal.")
    lanes, applied_fixes, verified = _validate_summary(input_data.get("summary"))

    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except Exception as error:
        raise RemediationError(f"The PDF could not be parsed for sealing: {type(error).__name__}") from error
    if reader.is_encrypted:
        raise RemediationError("Encrypted PDFs are not sealed; request an unencrypted source copy.")
    try:
        source_page_count = len(reader.pages)
    except Exception as error:
        raise RemediationError(f"The PDF could not be parsed for sealing: {type(error).__name__}") from error

    # Recorded BEFORE any mutation; the anti-vandal check compares against these.
    source_page_texts = [page.extract_text() or "" for page in reader.pages]
    evidence_short = sha256(payload).hexdigest()[:EVIDENCE_HASH_CHARS]

    writer = PdfWriter(clone_from=reader)
    page = writer.add_blank_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)

    stream = DecodedStreamObject()
    stream.set_data(_seal_page_stream(lanes, applied_fixes, verified, when_iso, evidence_short))
    page[NameObject("/Contents")] = writer._add_object(stream)
    fonts = DictionaryObject()
    for key, base_font in (("/F1", "/Helvetica"), ("/F2", "/Helvetica-Bold")):
        fonts[NameObject(key)] = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject(base_font),
        }))
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): fonts})

    output = io.BytesIO()
    writer.write(output)
    sealed = output.getvalue()

    # ANTI-VANDAL CONTRACT: re-open the output with a fresh parser and prove the
    # mutation was purely additive — exactly one appended page, byte-identical
    # extracted text on every original page. Assert, do not trust; on any
    # mismatch, no output leaves.
    pages_appended = text_preserved = False
    try:
        verifier = PdfReader(io.BytesIO(sealed), strict=False)
        pages_appended = len(verifier.pages) == source_page_count + 1
        if pages_appended:
            text_preserved = all(
                (verifier.pages[index].extract_text() or "") == source_page_texts[index]
                for index in range(source_page_count)
            )
    except Exception:
        pages_appended = text_preserved = False
    if not (pages_appended and text_preserved):
        raise RemediationError(
            "Verification failed: the sealed copy did not preserve the source pages "
            "exactly (page count +1, byte-identical text), so no output was produced."
        )

    return {
        "actions": [{
            "rule_id": "PDF.SEAL.REVIEW_SUMMARY",
            "action": "append_review_summary_page",
            "detail": (
                "Appended one final Review summary page carrying the seal wording, "
                "review date, short evidence hash, lane counts, applied fixes, and "
                "verified signals. No original page was altered."
            ),
        }],
        "when": when_iso,
        "evidence_hash_short": evidence_short,
        "lanes": lanes,
        "applied_fixes_count": len(applied_fixes),
        "verified_count": len(verified),
        "source_pages": source_page_count,
        "result_pages": source_page_count + 1,
        "verification": {"pages_appended": True, "prior_text_preserved": True},
        "source_sha256": f"sha256:{sha256(payload).hexdigest()}",
        "result_sha256": f"sha256:{sha256(sealed).hexdigest()}",
        "source_bytes": len(payload),
        "result_bytes": len(sealed),
        "sealed_payload": sealed,
    }


class ReviewSeal:
    """Appends the one-page review-record seal to a PDF copy."""

    CONTRACT_VERSION = "tina-seal-record/v1"
    CLAIM_BOUNDARY = (
        "The seal page records that a review happened, what was fixed in a copy, "
        "and what a human verified. It is a review record, not a certification, "
        "and no conformance is implied."
    )

    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    @classmethod
    def with_builtin_tools(cls) -> "ReviewSeal":
        gateway = ToolGateway()
        gateway.register(
            ToolManifest(
                name="append_review_summary",
                version="1.0.0",
                purpose="Append one Review summary seal page to a PDF copy.",
                deterministic=True,
                mutates_document=True,
                permissions=(SEAL_PERMISSION,),
                timeout_ms=30_000,
            ),
            _append_review_summary,
        )
        return cls(gateway)

    def apply(self, filename: str, payload: bytes, summary: dict,
              when_iso: str) -> tuple[bytes, dict[str, Any]]:
        """Append the seal page to an in-memory copy; return (sealed bytes, provenance)."""
        execution = self.gateway.execute(
            "append_review_summary",
            {"payload": payload, "summary": summary, "when_iso": when_iso},
            {SEAL_PERMISSION},
        )
        sealed: bytes = execution["output"].pop("sealed_payload")
        provenance = {
            "kind": "seal",
            "contract_version": self.CONTRACT_VERSION,
            "claim_boundary": self.CLAIM_BOUNDARY,
            "filename": filename,
            "tool": execution["tool"],
            "tool_version": execution["tool_version"],
            "deterministic": execution["deterministic"],
            "mutates_document": execution["mutates_document"],
            **execution["output"],
        }
        return sealed, provenance


def append_review_summary(filename: str, pdf_bytes: bytes, summary: dict,
                          when_iso: str) -> tuple[bytes, dict]:
    """Append ONE Review summary seal page to a copy of the PDF.

    Interface contract entry point: returns (sealed_bytes, provenance_dict).
    The provenance dict carries kind "seal", source/result hashes, and
    mutates_document True. Declines (RemediationError) on encrypted or
    unparseable input, and whenever the anti-vandal verification cannot prove
    the mutation was purely additive.
    """
    return ReviewSeal.with_builtin_tools().apply(filename, pdf_bytes, summary, when_iso)
