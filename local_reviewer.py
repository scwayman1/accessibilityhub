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

from tina.derive import DerivationError, HtmlDraftConverter, extract_blocks as derive_blocks, extract_images
from tina.evidence import build_receipt
from tina.intelligence import IntelligenceError, IntelligenceGateway
from tina.learning import LearningJourney
from tina.lessons import LessonError, LessonLibrary
from tina.remedy import MetadataRemediation, RemediationError, SemanticRemediation

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_JSON_BYTES = 80 * 1024 * 1024  # fix-semantics carries the PDF as base64


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


def run_local_convert(filename: str, payload: bytes, roles: dict[str, str] | None = None) -> dict[str, Any]:
    """Derive an editable HTML working copy from the PDF without mutating or persisting it."""
    validate_pdf_upload(filename, payload)
    converter = HtmlDraftConverter.with_builtin_tools()
    report = converter.convert(filename, payload, roles=roles)
    report["draft_filename"] = f"{Path(filename).stem}.draft.html"
    return report


def run_local_fix_semantics(
    filename: str,
    payload: bytes,
    checker: Callable[[Path, Path], dict[str, Any]],
    link_names: dict[str, str] | None,
    alt_texts: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    """Attach human-authored link descriptions / figure alt text to a copy, then re-review it."""
    before = run_local_review(filename, payload, checker)
    remediation = SemanticRemediation.with_builtin_tools()
    fixed_payload, remediation_report = remediation.apply(filename, payload, link_names=link_names, alt_texts=alt_texts)
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
    journey: LearningJourney | None = None,
    intelligence: IntelligenceGateway | None = None,
) -> ThreadingHTTPServer:
    """Create a localhost-only HTTP server for the browser workbench."""
    if journey is None:
        journey = LearningJourney()  # in-memory unless a persistent journey is supplied
    if intelligence is None:
        intelligence = IntelligenceGateway()  # deterministic-only until configured
    try:
        lessons: LessonLibrary | None = LessonLibrary()
    except LessonError:  # Lessons are optional; a review never depends on them.
        lessons = None

    def record_review_event(report: dict[str, Any]) -> None:
        try:
            journey.record_review(
                (report.get("input") or {}).get("sha256"),
                [item.get("rule_id") for item in report.get("findings", [])],
            )
        except Exception:  # Learning must never break a review.
            pass

    def record_fix_event(result: dict[str, Any]) -> None:
        try:
            before = result["before"]
            after_ids = {item.get("rule_id") for item in result["after"].get("findings", [])}
            resolved = [
                item.get("rule_id")
                for item in before.get("findings", [])
                if item.get("rule_id") not in after_ids
            ]
            journey.record_review(
                (before.get("input") or {}).get("sha256"),
                [item.get("rule_id") for item in before.get("findings", [])],
            )
            journey.record_fix((before.get("input") or {}).get("sha256"), resolved)
        except Exception:
            pass

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
            if request_url.path == "/api/journey":
                self.send_json(HTTPStatus.OK, journey.journey())
                return
            if request_url.path == "/api/ai/status":
                self.send_json(HTTPStatus.OK, intelligence.status())
                return
            if request_url.path == "/api/lessons":
                if lessons is None:
                    self.send_json(HTTPStatus.OK, {"lessons": [], "note": "Lesson content is unavailable."})
                    return
                skill = parse_qs(request_url.query).get("skill", [None])[0]
                self.send_json(HTTPStatus.OK, lessons.catalog(skill))
                return
            static_files = {
                "/": ("local_reviewer.html", "text/html; charset=utf-8"),
                "/index.html": ("local_reviewer.html", "text/html; charset=utf-8"),
                "/delight-content.json": ("delight_content.json", "application/json; charset=utf-8"),
                "/api/knowledge": ("rule_knowledge.json", "application/json; charset=utf-8"),
                "/foundation-ads.json": ("foundation_ads.json", "application/json; charset=utf-8"),
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

        def read_json_body(self, length: int) -> dict[str, Any] | None:
            if length <= 0 or length > MAX_JSON_BYTES:
                self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Request body must be JSON under 10 MB."})
                return None
            try:
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError
                return body
            except (json.JSONDecodeError, ValueError):
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Request body must be a JSON object."})
                return None

        def do_POST(self) -> None:  # noqa: N802
            request_url = urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0

            if request_url.path == "/api/attest":
                body = self.read_json_body(length)
                if body is None:
                    return
                journey.record_attestation(str(body.get("rule_id", "")), str(body.get("decision", "")))
                self.send_json(HTTPStatus.OK, journey.journey())
                return
            if request_url.path == "/api/receipt":
                body = self.read_json_body(length)
                if body is None:
                    return
                try:
                    receipt = build_receipt(
                        review=body.get("review") or {},
                        after=body.get("after"),
                        remediation=body.get("remediation"),
                        attestations=body.get("attestations"),
                    )
                except ValueError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                try:
                    journey.record_activity("receipt", receipt.get("input", {}).get("sha256"))
                except Exception:
                    pass
                self.send_json(HTTPStatus.OK, receipt)
                return
            if request_url.path == "/api/fix-semantics":
                body = self.read_json_body(length)
                if body is None:
                    return
                try:
                    payload_bytes = base64.b64decode(str(body.get("pdf_base64", "")), validate=True)
                except Exception:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": "A base64-encoded PDF is required."})
                    return
                filename = str(body.get("filename") or "document.pdf")
                try:
                    result = run_local_fix_semantics(
                        filename, payload_bytes, checker,
                        link_names=body.get("link_names"), alt_texts=body.get("alt_texts"),
                    )
                except (UploadValidationError, RemediationError, DerivationError) as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                except Exception as error:
                    self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Local review could not complete: {type(error).__name__}"})
                    return
                record_fix_event(result)
                self.send_json(HTTPStatus.OK, result)
                return
            if request_url.path == "/api/lesson-result":
                body = self.read_json_body(length)
                if body is None:
                    return
                if lessons is None:
                    self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Lesson content is unavailable."})
                    return
                try:
                    result = lessons.score(str(body.get("lesson_id", "")), body.get("chosen_index"))
                except LessonError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                journey.record_lesson(result["skill"], result["lesson_id"], result["correct"])
                self.send_json(HTTPStatus.OK, {**result, "journey": journey.journey()})
                return
            if request_url.path == "/api/ai/configure":
                body = self.read_json_body(length)
                if body is None:
                    return
                try:
                    status = intelligence.configure(
                        base_url=str(body.get("base_url", "")),
                        model=str(body.get("model", "")),
                        api_key=str(body["api_key"]) if body.get("api_key") else None,
                        provider=str(body.get("provider", "openai_compatible")),
                    )
                except IntelligenceError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                self.send_json(HTTPStatus.OK, status)
                return
            if request_url.path == "/api/ai/manifest":
                body = self.read_json_body(length)
                if body is None:
                    return
                self.send_json(HTTPStatus.OK, IntelligenceGateway.egress_manifest(body.get("finding") or {}))
                return
            if request_url.path == "/api/ai/draft-alt":
                body = self.read_json_body(length)
                if body is None:
                    return
                image_b64 = str(body.get("image_base64", ""))
                context = str(body.get("context", ""))
                if not body.get("consent"):
                    self.send_json(HTTPStatus.OK, {"manifest": IntelligenceGateway.alt_draft_manifest(len(image_b64) * 3 // 4, context)})
                    return
                try:
                    draft = intelligence.draft_alt_text(image_b64, str(body.get("mime", "image/jpeg")), context, consent=True)
                except IntelligenceError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error), "fallback": "write_it_yourself"})
                    return
                self.send_json(HTTPStatus.OK, draft)
                return
            if request_url.path == "/api/ai/structure":
                body = self.read_json_body(length)
                if body is None:
                    return
                try:
                    payload_bytes = base64.b64decode(str(body.get("pdf_base64", "")), validate=True)
                    blocks = derive_blocks(payload_bytes)
                except Exception:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": "A readable base64-encoded PDF is required."})
                    return
                if not body.get("consent"):
                    self.send_json(HTTPStatus.OK, {"manifest": IntelligenceGateway.structure_manifest(blocks)})
                    return
                try:
                    proposal = intelligence.propose_structure(blocks, consent=True)
                except IntelligenceError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error), "fallback": "structure_it_yourself"})
                    return
                self.send_json(HTTPStatus.OK, proposal)
                return
            if request_url.path == "/api/convert-structured":
                body = self.read_json_body(length)
                if body is None:
                    return
                try:
                    payload_bytes = base64.b64decode(str(body.get("pdf_base64", "")), validate=True)
                except Exception:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": "A base64-encoded PDF is required."})
                    return
                try:
                    payload = run_local_convert(str(body.get("filename") or "document.pdf"), payload_bytes,
                                                roles=body.get("roles"))
                except (UploadValidationError, DerivationError) as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                try:
                    journey.record_activity("convert", payload.get("source_sha256"))
                except Exception:
                    pass
                self.send_json(HTTPStatus.OK, payload)
                return
            if request_url.path == "/api/ai/explain":
                body = self.read_json_body(length)
                if body is None:
                    return
                try:
                    explanation = intelligence.explain_finding(
                        finding=body.get("finding") or {},
                        knowledge_card=body.get("knowledge_card") or {},
                        consent=bool(body.get("consent")),
                    )
                except IntelligenceError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error), "fallback": "authored_card"})
                    return
                self.send_json(HTTPStatus.OK, explanation)
                return

            if request_url.path == "/api/images":
                if length <= 0 or length > MAX_PDF_BYTES:
                    self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "PDF must be between 1 byte and 50 MB."})
                    return
                try:
                    self.send_json(HTTPStatus.OK, {"images": extract_images(self.rfile.read(length))})
                except DerivationError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            if request_url.path not in {"/api/review", "/api/fix", "/api/convert"}:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            if length <= 0 or length > MAX_PDF_BYTES:
                self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "PDF must be between 1 byte and 50 MB."})
                return
            query = parse_qs(request_url.query)
            filename = query.get("filename", [""])[0]
            try:
                if request_url.path == "/api/review":
                    payload = normalize_report_for_browser(run_local_review(filename, self.rfile.read(length), checker))
                    record_review_event(payload)
                elif request_url.path == "/api/convert":
                    payload = run_local_convert(filename, self.rfile.read(length))
                    try:
                        journey.record_activity("convert", payload.get("source_sha256"))
                    except Exception:
                        pass
                else:
                    payload = run_local_fix(
                        filename,
                        self.rfile.read(length),
                        checker,
                        title=query.get("title", [None])[0],
                        language=query.get("language", [None])[0],
                    )
                    record_fix_event(payload)
            except (UploadValidationError, RemediationError, DerivationError) as error:
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
    journey = LearningJourney(Path.home() / ".coastline-studio" / "journey.json")
    server = create_server(8765, run_spike_checker, journey=journey)
    print("Coastline Accessibility Studio local reviewer: http://127.0.0.1:8765")
    print("Loopback only · PDF-only · deterministic · works without AI")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
