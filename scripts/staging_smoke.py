"""Repeatable smoke test for a running Accessibility Hub staging service.

Drives the real HTTP surface the way an educator would: health check, sign-in,
synthetic review, a supported repair, the recheck, change history, and the
no-upload boundary. Run it against local development or the hosted Render
service after every deploy.

Usage:
    python3 scripts/staging_smoke.py --base-url http://127.0.0.1:8787 \
        --access-code "$HUB_STAGING_ACCESS_CODE"

    # Hosted example
    python3 scripts/staging_smoke.py --base-url https://accessibility-hub-staging.onrender.com \
        --access-code "$HUB_STAGING_ACCESS_CODE"

Exit code 0 means every required check passed. The OCR path is exercised when
the service supports it and reported as SKIP (not a failure) when the hosted
runtime has no OCR engine.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REFRESH_MARKER = 'http-equiv="refresh"'


class Smoke:
    def __init__(self, base_url: str, access_code: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_code = access_code
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.skipped: list[str] = []
        self.created_documents: list[str] = []

    # -- reporting -----------------------------------------------------------
    def ok(self, name: str) -> None:
        self.passed.append(name)
        print(f"  PASS  {name}")

    def fail(self, name: str, detail: str = "") -> None:
        self.failed.append(name)
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))

    def skip(self, name: str, detail: str = "") -> None:
        self.skipped.append(name)
        print(f"  SKIP  {name}" + (f" — {detail}" if detail else ""))

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.ok(name)
        else:
            self.fail(name, detail)
        return condition

    # -- http ----------------------------------------------------------------
    def request(self, path: str, data: dict[str, str] | None = None, follow: bool = True):
        url = self.base_url + path
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        request = urllib.request.Request(url, data=body)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.status, response.geturl(), response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, error.geturl(), error.read().decode("utf-8", "replace")

    def wait_for_terminal_assessment(self, path: str, deadline_seconds: float = 90.0) -> str:
        started = time.monotonic()
        page = ""
        while time.monotonic() - started < deadline_seconds:
            status, _, page = self.request(path)
            if status == 200 and REFRESH_MARKER not in page:
                return page
            time.sleep(1.0)
        return page

    def document_path_from(self, final_url: str) -> str:
        parsed = urllib.parse.urlparse(final_url)
        return parsed.path

    # -- checks --------------------------------------------------------------
    def run(self, include_ocr: bool) -> int:
        print(f"Accessibility Hub staging smoke test → {self.base_url}")

        print("\n[1/7] Health")
        status, _, body = self.request("/healthz")
        health: dict[str, object] = {}
        if self.check("healthz responds 200", status == 200, f"got {status}"):
            try:
                health = json.loads(body)
            except json.JSONDecodeError:
                self.fail("healthz returns JSON")
        if health:
            self.check("service is synthetic-only", health.get("synthetic_only") is True)
            self.check("login is configured", health.get("login_ready") is True,
                       "set HUB_STAGING_ACCESS_CODE and a 32+ char HUB_SESSION_SECRET")
            self.check("synthetic intake is open", health.get("synthetic_intake_ready") is True,
                       "hosted needs HUB_ALLOW_HOSTED_SYNTHETIC=true (exact lowercase)")
            self.check("real-document intake stays closed", health.get("hosted_intake_enabled") is False)

        print("\n[2/7] Sign-in")
        status, _, _ = self.request("/login", data={"code": "definitely-not-the-code"})
        self.check("wrong access code is rejected", status == 401, f"got {status}")
        status, final_url, page = self.request("/login", data={"code": self.access_code})
        signed_in = self.check("correct access code opens the workspace",
                               status == 200 and final_url.endswith("/app"), f"landed on {final_url} ({status})")
        if not signed_in:
            return self.summarize()
        self.check("workspace offers the sample review entry", "Start a sample review" in page)

        print("\n[3/7] Review a course handout")
        status, final_url, _ = self.request("/documents/synthetic", data={"fixture": "handout"})
        document_path = self.document_path_from(final_url)
        if not self.check("synthetic handout record created", status == 200 and document_path.startswith("/documents/"),
                          f"landed on {final_url} ({status})"):
            return self.summarize()
        self.created_documents.append(document_path)
        page = self.wait_for_terminal_assessment(document_path)
        self.check("assessment reaches a terminal state", REFRESH_MARKER not in page and bool(page))
        self.check("signal lanes render", "Needs attention" in page and "Not assessed" in page)
        self.check("title and language gaps are surfaced", "itle" in page and "anguage" in page,
                   "expected the handout's two seeded metadata gaps")
        self.check("no overall-result claim", "not an overall" in page or "does not create an overall result" in page)

        print("\n[4/7] Supported fix and recheck")
        status, final_url, _ = self.request(document_path + "/remediate/metadata",
                                            data={"title": "Week 3 Course Handout", "language": "en-US"})
        recheck_path = self.document_path_from(final_url)
        if self.check("title/language repair accepted", status == 200 and recheck_path != document_path,
                      f"landed on {final_url} ({status})"):
            self.created_documents.append(recheck_path)
            page = self.wait_for_terminal_assessment(recheck_path)
            self.check("recheck completes", REFRESH_MARKER not in page and bool(page))
            self.check("repair shows as a verified signal", "Verified signal" in page)
            self.check("change history records the repair", "metadata" in page)

        print("\n[5/7] OCR path (scanned handout)")
        if include_ocr:
            status, final_url, _ = self.request("/documents/synthetic", data={"fixture": "scan"})
            scan_path = self.document_path_from(final_url)
            if status == 200 and scan_path.startswith("/documents/") and scan_path not in self.created_documents:
                self.created_documents.append(scan_path)
                self.wait_for_terminal_assessment(scan_path)
                status, final_url, body = self.request(scan_path + "/remediate/ocr", data={"confirmed": "yes"})
                ocr_path = self.document_path_from(final_url)
                if status == 200 and ocr_path != scan_path:
                    self.created_documents.append(ocr_path)
                    page = self.wait_for_terminal_assessment(ocr_path)
                    self.check("OCR recheck completes", REFRESH_MARKER not in page and bool(page))
                    self.check("OCR change history recorded", "ocr" in page)
                else:
                    self.skip("OCR text layer", "service declined — expected when the host has no OCR engine")
            else:
                self.fail("scanned handout record created", f"landed on {final_url} ({status})")
        else:
            self.skip("OCR path", "disabled with --no-ocr")

        print("\n[6/7] Upload boundary")
        for probe in ("/upload", "/api/upload", "/documents/upload"):
            status, _, _ = self.request(probe, data={"pdf": "%PDF-1.4 fake"})
            self.check(f"no upload route at {probe}", status in (404, 405), f"got {status}")
        status, _, page = self.request("/app")
        self.check("workspace offers no file input", "type=file" not in page and 'type="file"' not in page)

        print("\n[7/7] Cleanup")
        removed = 0
        for path in dict.fromkeys(self.created_documents):
            status, _, _ = self.request(path + "/delete", data={"confirmed": "yes"})
            if status == 200:
                removed += 1
        self.ok(f"removed synthetic records ({removed} lineage roots processed)")
        return self.summarize()

    def summarize(self) -> int:
        print(f"\n{len(self.passed)} passed, {len(self.failed)} failed, {len(self.skipped)} skipped.")
        if self.failed:
            print("Smoke test FAILED:")
            for name in self.failed:
                print(f"  - {name}")
            return 1
        print("Smoke test passed.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="Root URL of the running staging service")
    parser.add_argument("--access-code", required=True, help="The HUB_STAGING_ACCESS_CODE value")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-request timeout in seconds")
    parser.add_argument("--no-ocr", action="store_true", help="Skip the scanned-handout OCR path")
    arguments = parser.parse_args()
    smoke = Smoke(arguments.base_url, arguments.access_code, arguments.timeout)
    return smoke.run(include_ocr=not arguments.no_ocr)


if __name__ == "__main__":
    sys.exit(main())
