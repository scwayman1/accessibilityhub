"""Page layout for accessible copies: paragraphs and images in reading position.

Plain text extraction loses two things a rebuilt document needs: paragraphs
(lines come back one by one, so a wrapped sentence or URL breaks in two) and
where images sit relative to the text (they end up after everything on the
page). When poppler's ``pdftotext`` is installed, its layout analysis gives
text blocks with positions; images are located by walking each page's content
stream. Both are deterministic, read-only, and local.

Without poppler, or if its output does not line up with the PDF, callers fall
back to the plain extraction in ``tina.derive``.
"""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.generic import ContentStream

_URL_START = re.compile(r"^(?:https?://|mailto:|www\.)", re.IGNORECASE)
_URL_BREAK_CHARS = "/-_.?=&#:"


def _continues_url(token: str) -> bool:
    """A line ending in a URL that was wrapped at one of its break characters."""
    return bool(_URL_START.match(token)) and token[-1] in _URL_BREAK_CHARS


def _join_lines(lines: list[str]) -> str:
    """Join a block's lines into one paragraph. A URL wrapped at '/', '-',
    '?', '=' or '&' continues without a space; everything else gets one."""
    text = ""
    for line in (" ".join(line.split()) for line in lines):
        if not line:
            continue
        if not text:
            text = line
        elif _continues_url(text.rsplit(" ", 1)[-1]):
            text += line
        else:
            text += " " + line
    return text


def _poppler_blocks(payload: bytes) -> list[list[dict[str, Any]]] | None:
    """Per page: [{"text", "top"}] from ``pdftotext -bbox-layout``, or None."""
    binary = shutil.which("pdftotext")
    if not binary:
        return None
    with tempfile.TemporaryDirectory(prefix="hub-layout-") as workdir:
        source = Path(workdir) / "in.pdf"
        source.write_bytes(payload)
        try:
            completed = subprocess.run([binary, "-bbox-layout", "-enc", "UTF-8", str(source), "-"],
                                       capture_output=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
    if completed.returncode != 0:
        return None
    try:
        root = ElementTree.fromstring(completed.stdout)
    except ElementTree.ParseError:
        return None
    pages: list[list[dict[str, Any]]] = []
    for page in root.iter():
        if not page.tag.endswith("page"):
            continue
        blocks = []
        for block in page.iter():
            if not block.tag.endswith("block"):
                continue
            lines = [
                " ".join((word.text or "") for word in line.iter() if word.tag.endswith("word"))
                for line in block.iter() if line.tag.endswith("line")
            ]
            text = _join_lines(lines)
            if text:
                blocks.append({"text": text, "top": float(block.get("yMin") or 0)})
        pages.append(blocks)
    return pages


def _multiply(m: list[float], n: list[float]) -> list[float]:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return [a * a2 + b * c2, a * b2 + b * d2, c * a2 + d * c2, c * b2 + d * d2,
            e * a2 + f * c2 + e2, e * b2 + f * d2 + f2]


def image_tops(page: Any) -> dict[str, float]:
    """Top edge (points from the top of the page) of each image XObject drawn
    directly in the page's content stream, keyed by resource name."""
    try:
        resources = page.get("/Resources") or {}
        resources = resources.get_object() if hasattr(resources, "get_object") else resources
        xobjects = resources.get("/XObject") or {}
        xobjects = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
        height = float(page.mediabox.top) - float(page.mediabox.bottom)
        content = ContentStream(page.get_contents(), page.pdf)
    except Exception:
        return {}
    ctm, stack, tops = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0], [], {}
    for operands, operator in content.operations:
        if operator == b"q":
            stack.append(list(ctm))
        elif operator == b"Q" and stack:
            ctm = stack.pop()
        elif operator == b"cm" and len(operands) == 6:
            try:
                ctm = _multiply([float(v) for v in operands], ctm)
            except (TypeError, ValueError):
                continue
        elif operator == b"Do" and operands:
            name = str(operands[0])
            try:
                xobject = xobjects[name].get_object()
            except Exception:
                continue
            if xobject.get("/Subtype") != "/Image":
                continue
            a, b, c, d, e, f = ctm
            highest = max(f, b + f, d + f, b + d + f)  # the unit square's highest corner
            tops.setdefault(name.lstrip("/"), height - highest)
    return tops


def page_layout(payload: bytes) -> list[list[dict[str, Any]]] | None:
    """Per page, text blocks (and image tops) in reading order, or None to fall back.

    Each page is ``{"blocks": [{"text", "top"}], "image_tops": {name: top}}``.
    """
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
        if reader.is_encrypted:
            return None
        blocks = _poppler_blocks(payload)
        if blocks is None or len(blocks) != len(reader.pages):
            return None
        return [{"blocks": page_blocks, "image_tops": image_tops(page)}
                for page_blocks, page in zip(blocks, reader.pages)]
    except Exception:
        return None
