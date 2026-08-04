import contextlib
import io
import json
import socket
import unittest
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

from local_reviewer import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_PDF_BYTES,
    UploadValidationError,
    _is_loopback_host,
    create_server,
    main,
    normalize_report_for_browser,
    parse_args,
    run_local_review,
    updated_filename,
    validate_pdf_upload,
)


class UploadValidationTests(unittest.TestCase):
    def test_accepts_small_pdf_with_pdf_magic_bytes(self):
        validate_pdf_upload("course-outline.pdf", b"%PDF-1.7\nexample")

    def test_rejects_non_pdf_magic_bytes_even_when_extension_is_pdf(self):
        with self.assertRaises(UploadValidationError):
            validate_pdf_upload("course-outline.pdf", b"not a PDF")

    def test_rejects_non_pdf_filename(self):
        with self.assertRaises(UploadValidationError):
            validate_pdf_upload("course-outline.docx", b"%PDF-1.7\nexample")

    def test_rejects_payload_above_local_limit(self):
        with self.assertRaises(UploadValidationError):
            validate_pdf_upload("course-outline.pdf", b"%PDF-" + b"x" * MAX_PDF_BYTES)


class UpdatedFilenameTests(unittest.TestCase):
    """Chained fixes must never stack '.updated' suffixes on the download name."""

    def test_first_fix_appends_a_single_suffix(self):
        self.assertEqual(updated_filename("demo_course_week3.pdf"), "demo_course_week3.updated.pdf")

    def test_fixing_an_already_updated_copy_keeps_one_suffix(self):
        self.assertEqual(updated_filename("demo_course_week3.updated.pdf"), "demo_course_week3.updated.pdf")

    def test_legacy_stacked_suffixes_collapse(self):
        self.assertEqual(updated_filename("week3.updated.updated.updated.pdf"), "week3.updated.pdf")


class CommandLineTests(unittest.TestCase):
    """python3 local_reviewer.py has a real CLI: --port, --host, --help."""

    def test_defaults_match_the_documented_contract(self):
        args = parse_args([])
        self.assertEqual(args.port, DEFAULT_PORT)
        self.assertEqual(args.host, DEFAULT_HOST)
        self.assertEqual(DEFAULT_PORT, 8765)
        self.assertEqual(DEFAULT_HOST, "127.0.0.1")

    def test_port_flag_is_honored(self):
        self.assertEqual(parse_args(["--port", "8812"]).port, 8812)

    def test_help_prints_usage_and_exits_zero_without_starting_a_server(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as context:
            parse_args(["--help"])
        self.assertEqual(context.exception.code, 0)
        self.assertIn("--port", stdout.getvalue())
        self.assertIn("Accessibility Hub", stdout.getvalue())

    def test_non_loopback_host_is_refused_before_binding(self):
        # The workbench promises documents stay on this computer; a LAN bind
        # would silently break that boundary.
        for host in ("0.0.0.0", "192.168.1.20", "example.com", "::"):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(["--host", host, "--port", "0"])
            self.assertEqual(exit_code, 2, host)
            self.assertIn("loopback", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_loopback_host_spellings_are_accepted(self):
        for host in ("127.0.0.1", "127.0.0.2", "localhost", "::1"):
            self.assertTrue(_is_loopback_host(host), host)

    def test_busy_port_yields_a_friendly_one_line_error_not_a_traceback(self):
        blocker = socket.socket()
        try:
            blocker.bind(("127.0.0.1", 0))
            blocker.listen(1)
            busy_port = blocker.getsockname()[1]
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(["--port", str(busy_port)])
            self.assertEqual(exit_code, 1)
            message = stderr.getvalue()
            self.assertIn(f"Port {busy_port} is already in use", message)
            self.assertIn("--port", message)
            self.assertNotIn("Traceback", message)
        finally:
            blocker.close()


class LocalReviewLifecycleTests(unittest.TestCase):
    def test_checker_receives_local_temporary_pdf_and_returns_report(self):
        observed = {}

        def fake_checker(pdf_path: Path, output_dir: Path):
            observed["path"] = pdf_path
            observed["output"] = output_dir
            observed["payload"] = pdf_path.read_bytes()
            return {"findings": [{"rule_id": "PDF.TEST", "category": "advisory"}]}

        report = run_local_review("course-outline.pdf", b"%PDF-1.7\nlocal", fake_checker)

        self.assertEqual(observed["payload"], b"%PDF-1.7\nlocal")
        self.assertEqual(report["findings"][0]["rule_id"], "PDF.TEST")
        self.assertFalse(observed["path"].exists())


class ReportBoundaryTests(unittest.TestCase):
    def test_browser_report_omits_temporary_file_paths(self):
        report = normalize_report_for_browser({
            "input": {"path": "/private/tmp/coastline-pdf-review-123/source.pdf", "sha256": "abc", "bytes": 12},
            "verapdf": {"report_path": "/private/tmp/coastline-pdf-review-123/evidence/report.json"},
            "findings": [],
        })
        self.assertNotIn("path", report["input"])
        self.assertNotIn("report_path", report["verapdf"])
        self.assertEqual(report["input"]["sha256"], "abc")

    def test_loopback_review_endpoint_returns_checker_report(self):
        def fake_checker(pdf_path: Path, output_dir: Path):
            return {"findings": [{"rule_id": "PDF.LOCAL", "category": "review_required"}]}

        server = create_server(0, fake_checker)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/review?filename=outline.pdf",
                data=b"%PDF-1.7\nlocal test",
                headers={"Content-Type": "application/pdf"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read())
            self.assertEqual(payload["findings"][0]["rule_id"], "PDF.LOCAL")
            self.assertEqual(server.server_address[0], "127.0.0.1")
            with urlopen(f"http://127.0.0.1:{server.server_port}/delight-content.json", timeout=5) as response:
                delight = json.loads(response.read())
            self.assertTrue(delight["categories"]["encouragement"]["enabled"])
        finally:
            server.shutdown()
            server.server_close()

    def test_favicon_is_served_so_the_console_stays_clean(self):
        server = create_server(0, lambda pdf, out: {"findings": []})
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path in ("/favicon.ico", "/assets/favicon.svg"):
                with urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get("Content-Type"), "image/svg+xml")
                    self.assertIn(b"<svg", response.read())
            with urlopen(f"http://127.0.0.1:{server.server_port}/assets/coastline-college-logo-white.png", timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get("Content-Type"), "image/png")
        finally:
            server.shutdown()
            server.server_close()
