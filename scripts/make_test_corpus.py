#!/usr/bin/env python3
"""Deterministic test-corpus generator for the transformation bench.

Writes a varied set of rights-cleared, generated PDFs into ./corpus/ (gitignored
— the generator is the committed artifact, never the binaries). Every document
except the encrypted one is byte-for-byte reproducible across runs, so the
bench can be used as a refinement loop with stable inputs.

    python3.11 scripts/make_test_corpus.py            # writes ./corpus/
    python3.11 scripts/make_test_corpus.py --list     # names + what each probes
    python3.11 scripts/make_test_corpus.py --only scan-only-page
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from service.fixtures import synthetic_handout_pdf, synthetic_scan_pdf  # noqa: E402
from tests.test_report_anchors import anchored_pdf, build_pdf, tagged_figure_pdf  # noqa: E402

# PIL stamps /CreationDate and /ModDate with wall-clock time. Pin both to a
# fixed instant (same byte length, so offsets stay valid) for reproducibility.
_PDF_DATE = re.compile(rb"D:\d{14}")
_FIXED_PDF_DATE = b"D:20260101000000"


def _pin_dates(payload: bytes) -> bytes:
    return _PDF_DATE.sub(_FIXED_PDF_DATE, payload)


def _text_stream(lines: list[str], leading: int = 26) -> bytes:
    commands = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append(f"0 -{leading} Td")
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj")
    commands.append("ET")
    return "\n".join(commands).encode("latin-1")


def _build_with_info(objects: list[bytes], info_number: int | None = None) -> bytes:
    """Raw builder variant that can reference an /Info dictionary in the trailer."""
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    info = f" /Info {info_number} 0 R" if info_number else ""
    out.write(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R{info} >>\nstartxref\n{xref_at}\n%%EOF\n".encode())
    return out.getvalue()


def untagged_multiblock_pdf() -> bytes:
    """Several visual blocks (heading, paragraphs, list-shaped lines), no tags at all."""
    stream = _text_stream([
        "Field Methods: Week 5 Overview",
        "",
        "This week moves from observation to structured description.",
        "Bring your notebook from week four; we build on those entries.",
        "",
        "Before class:",
        "- Re-read your three strongest observations.",
        "- Mark the one with the most specific language.",
        "",
        "During class:",
        "- Pair up and trade notebooks.",
        "- Describe your partner's observation back to them.",
        "",
        "After class, revise one entry until a stranger could follow it.",
    ])
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",  # no /Lang, no /MarkInfo, no tags
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ])


def clean_well_formed_pdf() -> bytes:
    """Title, language, and a tagged structure tree all present — the quiet case."""
    stream = _text_stream([
        "Studio Notes: Color and Light",
        "A short, well-formed handout used to confirm the pipeline",
        "leaves already-healthy documents alone.",
    ])
    return _build_with_info([
        b"<< /Type /Catalog /Pages 2 0 R /Lang (en-US) "
        b"/MarkInfo << /Marked true >> /StructTreeRoot 6 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /StructTreeRoot /K [7 0 R] >>",
        b"<< /S /P /P 6 0 R /Pg 3 0 R >>",
        b"<< /Title (Studio Notes: Color and Light) /Producer (corpus generator) >>",
    ], info_number=8)


def long_document_pdf(pages: int = 50) -> bytes:
    """~50 pages of plain text for timing runs; deliberately missing title/language."""
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # placeholder for the /Pages node, filled below
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids: list[str] = []
    for number in range(1, pages + 1):
        stream = _text_stream([
            f"Lecture notes, page {number} of {pages}.",
            "Each page carries real extractable text so timing reflects",
            "genuine per-page analysis work, not empty page shells.",
        ])
        page_obj = len(objects) + 1
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
            + str(page_obj + 1).encode() + b" 0 R >>"
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        kids.append(f"{page_obj} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {pages} >>".encode()
    return build_pdf(objects)


def scan_only_page_pdf() -> bytes:
    """Single raster page with no text layer, dates pinned for reproducibility."""
    return _pin_dates(synthetic_scan_pdf())


def encrypted_pdf() -> bytes:
    """Password-protected copy of the handout — the honest-decline case.

    pypdf's encryption salts are random, so this is the one corpus document
    whose bytes vary between runs; its behavior (decline) is what matters.
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(synthetic_handout_pdf()), strict=False)
    writer = PdfWriter(clone_from=reader)
    writer.encrypt("owner-only")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# name → (builder, deterministic, what it probes). Filenames intentionally
# include spaces and non-ASCII characters where noted.
CORPUS: dict[str, tuple] = {
    "missing-title-language.pdf": (
        synthetic_handout_pdf, True,
        "The staging handout fixture: no title, no language — the auto-improve happy path."),
    "unnamed links.pdf": (
        anchored_pdf, True,
        "Filename with a space; page 2 carries an image and an unnamed link annotation."),
    "tagged-figure-no-alt.pdf": (
        tagged_figure_pdf, True,
        "Tagged structure tree whose /Figure element has no /Alt text."),
    "untagged-multiblock.pdf": (
        untagged_multiblock_pdf, True,
        "Multi-block visual layout with no tag structure at all."),
    "scan-only-page.pdf": (
        scan_only_page_pdf, True,
        "One scanned page, no extractable text layer."),
    "encrypted.pdf": (
        encrypted_pdf, False,
        "Password-protected; the pipeline must decline honestly, never crash."),
    "clean-well-formed.pdf": (
        clean_well_formed_pdf, True,
        "Title + language + tags already present; nothing for the pipeline to change."),
    "long-50-pages.pdf": (
        long_document_pdf, True,
        "Fifty text pages for timing; skipped by the bench's --fast flag."),
    "Übungsblatt Woche 3.pdf": (
        synthetic_handout_pdf, True,
        "Unicode + space filename over the same repairable handout bytes."),
}


def write_corpus(out_dir: Path, only: str | None = None) -> list[Path]:
    names = [only] if only else list(CORPUS)
    for name in names:
        if name not in CORPUS:
            raise SystemExit(f"Unknown corpus document {name!r}. Use --list to see the names.")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in names:
        builder = CORPUS[name][0]
        path = out_dir / name
        path.write_bytes(builder())
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "corpus",
                        help="Output directory (default: ./corpus, gitignored)")
    parser.add_argument("--list", action="store_true", help="List document names and exit")
    parser.add_argument("--only", metavar="NAME", help="Generate a single named document")
    args = parser.parse_args(argv)
    if args.list:
        for name, (_, deterministic, note) in CORPUS.items():
            marker = "deterministic" if deterministic else "varies (encryption salts)"
            print(f"{name}\n    [{marker}] {note}")
        return 0
    written = write_corpus(args.out, args.only)
    for path in written:
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
