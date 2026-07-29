"""Generate the only document this staging slice is permitted to process."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont


def synthetic_handout_pdf() -> bytes:
    """Return a deterministic, rights-cleared course handout with two repairable metadata gaps."""
    lines = [
        "Week 3: Observe, Describe, Discuss",
        "Synthetic course handout for Accessibility Hub staging.",
        "Learning goal: describe one observation in clear, specific language.",
        "Before class: read the short scenario and note one question.",
        "During class: discuss your observation with a partner.",
        "After class: revise your note so another reader can follow it.",
    ]
    commands = ["BT", "/F1 22 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.extend(["0 -34 Td", "/F1 13 Tf"])
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",  # Deliberately no /Lang or tag tree.
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    output = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def synthetic_scan_pdf() -> bytes:
    """Return a rights-cleared scan-shaped page with no text layer for OCR recheck."""
    image = Image.new("RGB", (1275, 1650), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=48)
    for index, line in enumerate((
        "Week 3 field notes",
        "Synthetic scanned handout for Accessibility Hub staging.",
        "Review the generated text layer against this page image.",
    )):
        draw.text((120, 200 + index * 120), line, fill="black", font=font)
    output = io.BytesIO()
    image.save(output, "PDF", resolution=150.0)
    return output.getvalue()
