#!/usr/bin/env python3
"""Loopback-only local PDF reviewer for Coastline Accessibility Studio."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from tina.remedy import MetadataRemediation, RemediationError

MAX_PDF_BYTES = 50 * 1024 * 1024


class UploadValidationError(ValueError):
    """Raised when an inbound local review request is not a supported PDF."""


def validate_pdf_upload(filename: str, payload: bytes) -> None:
    if not filename.lower().endswith(".pdf"):
        raise UploadValidationError("Choose a PDF file.")
    if not payload.startswith(b"%PDF-"):
        raise UploadValidationError("This file does not look like a PDF.")
    if len(payload) > MAX_PDF_BYTES:
        raise UploadValidationError("This PDF exceeds the 50 MB local review limit.")


def run_local_review(
    filename: str,
    payload: bytes,
    checker: Callable[[Path, Path], dict[str, Any]],
) -> dict[str, Any]:
    """Run a supplied checker against a temporary local copy and delete all inputs afterward."""
    validate_pdf_upload(filename, payload)
    safe_name = Path(filename).name
    with tempfile.TemporaryDirectory(prefix="coastline-pdf-review-") as directory:
        root = Path(directory)
        pdf_path = root / safe_name
        output_dir = root / "evidence"
        pdf_path.write_bytes(payload)
        return checker(pdf_path, output_dir)


def normalize_report_for_browser(report: dict[str, Any]) -> dict[str, Any]:
    """Remove implementation-local paths before returning a report to browser JavaScript."""
    normalized = json.loads(json.dumps(report))
    normalized.get("input", {}).pop("path", None)
    normalized.get("verapdf", {}).pop("report_path", None)
    return normalized


def run_local_fix(
    filename: str,
    payload: bytes,
    checker: Callable[[Path, Path], dict[str, Any]],
    title: str | None,
    language: str | None,
) -> dict[str, Any]:
    """Review, apply the requested metadata fixes to a copy, and review that copy again.

    Returns before/after reports, the remediation provenance record, and the
    fixed PDF encoded for a browser download. Nothing is persisted.
    """
    before = run_local_review(filename, payload, checker)
    remediation = MetadataRemediation.with_builtin_tools()
    fixed_payload, remediation_report = remediation.apply(filename, payload, title=title, language=language)
    fixed_filename = f"{Path(filename).stem}.updated.pdf"
    after = run_local_review(fixed_filename, fixed_payload, checker)
    return {
        "before": normalize_report_for_browser(before),
        "after": normalize_report_for_browser(after),
        "remediation": remediation_report,
        "fixed_filename": fixed_filename,
        "fixed_pdf_base64": base64.b64encode(fixed_payload).decode("ascii"),
    }


def run_spike_checker(pdf_path: Path, output_dir: Path) -> dict[str, Any]:
    """Invoke the deterministic checker and return its structured local report."""
    script = Path(__file__).with_name("check_pdf.py")
    result = subprocess.run(
        [sys.executable, str(script), str(pdf_path), "--output-dir", str(output_dir)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("deterministic checker returned a non-zero exit code")
    report_path = output_dir / "report.json"
    if not report_path.exists():
        raise RuntimeError("deterministic checker did not produce report.json")
    return json.loads(report_path.read_text())


def create_server(
    port: int,
    checker: Callable[[Path, Path], dict[str, Any]],
) -> ThreadingHTTPServer:
    """Create a localhost-only HTTP server for the browser workbench."""

    class LocalReviewerHandler(BaseHTTPRequestHandler):
        def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802
            request_url = urlparse(self.path)
            if request_url.path == "/api/health":
                self.send_json(HTTPStatus.OK, {"ok": True, "scope": "loopback-only", "ai": False})
                return
            static_files = {
                "/": ("local_reviewer.html", "text/html; charset=utf-8"),
                "/index.html": ("local_reviewer.html", "text/html; charset=utf-8"),
                "/delight-content.json": ("delight_content.json", "application/json; charset=utf-8"),
                "/api/knowledge": ("rule_knowledge.json", "application/json; charset=utf-8"),
            }
            selected = static_files.get(request_url.path)
            if selected is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            page = Path(__file__).with_name(selected[0])
            encoded = page.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", selected[1])
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:  # noqa: N802
            request_url = urlparse(self.path)
            if request_url.path not in {"/api/review", "/api/fix"}:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_PDF_BYTES:
                self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "PDF must be between 1 byte and 50 MB."})
                return
            query = parse_qs(request_url.query)
            filename = query.get("filename", [""])[0]
            try:
                if request_url.path == "/api/review":
                    payload = normalize_report_for_browser(run_local_review(filename, self.rfile.read(length), checker))
                else:
                    payload = run_local_fix(
                        filename,
                        self.rfile.read(length),
                        checker,
                        title=query.get("title", [None])[0],
                        language=query.get("language", [None])[0],
                    )
            except (UploadValidationError, RemediationError) as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            except Exception as error:  # Boundary: no stack traces to browser UI.
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Local review could not complete: {type(error).__name__}"})
                return
            self.send_json(HTTPStatus.OK, payload)

        def log_message(self, format: str, *_args: Any) -> None:
            return

    return ThreadingHTTPServer(("127.0.0.1", port), LocalReviewerHandler)


def main() -> int:
    server = create_server(8765, run_spike_checker)
    print("Coastline Accessibility Studio local reviewer: http://127.0.0.1:8765")
    print("Loopback only · PDF-only · deterministic checks and fixes · no AI")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
