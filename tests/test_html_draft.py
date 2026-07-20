import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

from pypdf import PdfReader, PdfWriter

from tina.derive import DERIVE_HTML_PERMISSION, DRAFT_SCRIPT, DerivationError, HtmlDraftConverter
from tina.kernel import ToolPermissionError
from local_reviewer import create_server


def text_pdf(text: str, title: str | None = None, language: str | None = None) -> bytes:
    """Assemble a minimal one-page PDF with real extractable text."""
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    catalog_extra = f" /Lang ({language})" if language else ""
    objects = [
        f"<< /Type /Catalog /Pages 2 0 R{catalog_extra} >>".encode(),
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    if title:
        objects.append(f"<< /Title ({title}) >>".encode())
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R"
    if title:
        trailer += f" /Info {len(objects)} 0 R"
    out.write(f"{trailer} >>\nstartxref\n{xref_at}\n%%EOF\n".encode())
    return out.getvalue()


def image_pdf() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (0, 90, 160)).save(buffer, format="PDF")
    return buffer.getvalue()


class HtmlDraftConverterTests(unittest.TestCase):
    def test_extracts_text_into_editable_blocks_with_source_metadata(self):
        pdf = text_pdf("Welcome to Week 3", title="Week 3 Outline", language="en-US")
        report = HtmlDraftConverter.with_builtin_tools().convert("outline.pdf", pdf)

        self.assertEqual(report["contract_version"], "tina-html-draft/v1")
        self.assertFalse(report["mutates_document"])
        self.assertIn("<p data-block>Welcome to Week 3</p>", report["html"])
        self.assertIn('<html lang="en-US">', report["html"])
        self.assertIn("<title>Week 3 Outline</title>", report["html"])
        self.assertIn("not a conformance result", report["html"])
        self.assertEqual(report["stats"]["paragraphs"], 1)

    def test_missing_metadata_is_flagged_not_invented(self):
        report = HtmlDraftConverter.with_builtin_tools().convert("outline.pdf", text_pdf("Hello"))
        self.assertIn('<html lang="">', report["html"])
        self.assertIn("<title>Untitled draft</title>", report["html"])
        self.assertIsNone(report["source_title"])
        self.assertIsNone(report["source_language"])

    def test_embeds_images_with_pending_alt_decision(self):
        report = HtmlDraftConverter.with_builtin_tools().convert("scan.pdf", image_pdf())
        self.assertEqual(report["stats"]["images_embedded"], 1)
        self.assertIn('alt="" data-needs-alt', report["html"])
        self.assertIn("data:image/jpeg;base64,", report["html"])
        self.assertEqual(report["stats"]["pages_without_text"], 1)

    def test_rejects_encrypted_pdf(self):
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.encrypt("secret")
        buffer = io.BytesIO()
        writer.write(buffer)
        with self.assertRaises(DerivationError):
            HtmlDraftConverter.with_builtin_tools().convert("locked.pdf", buffer.getvalue())

    def test_gateway_denies_conversion_without_derive_permission(self):
        converter = HtmlDraftConverter.with_builtin_tools()
        with self.assertRaises(ToolPermissionError):
            converter.gateway.execute("extract_html_draft", {"payload": text_pdf("Hi")}, {DERIVE_HTML_PERMISSION + ".other"})

    def test_embedded_editor_script_parses(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write(DRAFT_SCRIPT)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        Path(path).unlink(missing_ok=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class ConvertEndpointTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(0, lambda pdf_path, output_dir: {"findings": []})
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_convert_endpoint_returns_draft_html(self):
        request = Request(
            self.base + "/api/convert?filename=outline.pdf",
            data=text_pdf("Welcome to Week 3"),
            headers={"Content-Type": "application/pdf"},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read())
        self.assertEqual(result["draft_filename"], "outline.draft.html")
        self.assertIn("Welcome to Week 3", result["html"])
        self.assertIn("claim_boundary", result)


if __name__ == "__main__":
    unittest.main()
